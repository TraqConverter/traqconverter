"""In-app Help chat: Claude answers product questions. Messages are relayed, never stored."""
import logging
from typing import Iterator, Literal

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.core.company import SUPPORT_EMAIL
from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.rate_limit import user_rate_limit
from app.dependencies.tenant import team_ids_for
from app.models.user import User
from app.services import ai_usage, support_knowledge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/support", tags=["support"])

MAX_MESSAGES = 20
MAX_MESSAGE_CHARS = 4_000
MAX_QUESTION_CHARS = 1_500
MAX_TOTAL_CHARS = 20_000
CUT_OFF = f"\n\n(The answer was cut off. Please ask again, or email {SUPPORT_EMAIL}.)"


class SupportTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class SupportChatRequest(BaseModel):
    messages: list[SupportTurn] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_shape(self):
        msgs = self.messages
        if len(msgs) > MAX_MESSAGES:
            raise ValueError("This chat is too long. Start a new one to ask another question.")
        if any(m.role != ("user" if i % 2 == 0 else "assistant") for i, m in enumerate(msgs)):
            raise ValueError("Messages must alternate, starting with a question.")
        if msgs[-1].role != "user":
            raise ValueError("The last message must be a question.")
        if len(msgs[-1].content) > MAX_QUESTION_CHARS:
            raise ValueError(f"Keep a question under {MAX_QUESTION_CHARS} characters.")
        if sum(len(m.content) for m in msgs) > MAX_TOTAL_CHARS:
            raise ValueError("This chat is too long. Start a new one to ask another question.")
        return self


def _client() -> anthropic.Anthropic:
    from app.services.ai_translation_service import _get_anthropic

    return _get_anthropic()


def _relay(manager, stream, user_id, team_id, count: int) -> Iterator[str]:
    try:
        try:
            for text in stream.text_stream:
                yield text
            with ai_usage.ai_context(action="support_chat", user_id=user_id, team_id=team_id):
                final = stream.get_final_message()
        except anthropic.APIError as e:
            logger.warning("Support chat stream failed: %s", type(e).__name__)
            yield CUT_OFF
            return
        if final.stop_reason == "max_tokens":
            yield CUT_OFF
        u = final.usage
        # Counts only: the questions and answers are never logged or stored.
        logger.info(
            "Support chat answered: user=%s messages=%d input=%s output=%s cache_read=%s cache_write=%s",
            user_id, count, u.input_tokens, u.output_tokens,
            getattr(u, "cache_read_input_tokens", 0), getattr(u, "cache_creation_input_tokens", 0),
        )
    finally:
        manager.__exit__(None, None, None)


@router.post(
    "/chat",
    dependencies=[Depends(user_rate_limit("support_chat", max_requests=30, per_seconds=3600))],
)
def support_chat(
    payload: SupportChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    unavailable = f"The Help chat isn't available right now. Please email {SUPPORT_EMAIL}."
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail=unavailable)
    team_id = next(iter(team_ids_for(db, user)), None)
    messages = [m.model_dump() for m in payload.messages]
    manager = _client().messages.stream(
        model=settings.SUPPORT_CHAT_MODEL,
        max_tokens=settings.SUPPORT_CHAT_MAX_TOKENS,
        system=support_knowledge.system_blocks(),
        messages=messages,
        output_config={"effort": "low"},
    )
    try:
        # Entering sends the request, so auth, quota and model errors become a clean HTTP error here.
        stream = manager.__enter__()
    except anthropic.APIError as e:
        logger.warning("Support chat request failed: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail=unavailable)
    return StreamingResponse(
        _relay(manager, stream, user.id, team_id, len(messages)),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
