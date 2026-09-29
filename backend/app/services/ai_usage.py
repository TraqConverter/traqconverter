"""Records the tokens and USD cost of every model request, attributed through a context variable."""
import contextvars
import functools
import logging
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# USD per million tokens as (input, output). The longest matching prefix wins, so dated snapshots resolve.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.0, 8.0),
}
CACHE_READ_MULTIPLIER = Decimal("0.1")
CACHE_WRITE_5M_MULTIPLIER = Decimal("1.25")
CACHE_WRITE_1H_MULTIPLIER = Decimal("2")
OPENAI_CACHED_INPUT_MULTIPLIER = Decimal("0.25")

UNKNOWN_ACTION = "unknown"
_ATTRS = ("action", "project_id", "team_id", "user_id")
_context: contextvars.ContextVar[dict] = contextvars.ContextVar("ai_context", default={})
_installed = False


@dataclass
class TokenCounts:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0

    @property
    def cache_write(self) -> int:
        return self.cache_write_5m + self.cache_write_1h


@contextmanager
def ai_context(**attrs: Any):
    unknown = set(attrs) - set(_ATTRS)
    if unknown:
        raise TypeError(f"Unknown ai_context attributes: {sorted(unknown)}")
    merged = {**_context.get(), **{k: v for k, v in attrs.items() if v is not None}}
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


def bind(fn: Callable, **attrs: Any) -> Callable:
    """Wrap fn so it runs under the given attribution, for background tasks and thread pools."""

    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> Any:
        with ai_context(**attrs):
            return fn(*args, **kwargs)

    return run


def project_task(action: str) -> Callable:
    """Decorator for jobs whose first argument is the project id."""

    def decorate(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def run(project_id, *args: Any, **kwargs: Any) -> Any:
            with ai_context(action=action, project_id=project_id):
                return fn(project_id, *args, **kwargs)

        return run

    return decorate


def current() -> dict:
    return dict(_context.get())


def price_for(model: str) -> Optional[tuple[float, float]]:
    name = (model or "").lower()
    # Bedrock/Vertex ids carry a provider prefix or an @version suffix.
    if "claude-" in name:
        name = name[name.index("claude-"):]
    name = name.split("@", 1)[0]
    best = max((k for k in PRICES_PER_MTOK if name.startswith(k)), key=len, default=None)
    return PRICES_PER_MTOK[best] if best else None


def cost_usd(model: str, counts: TokenCounts, provider: str = "anthropic") -> Decimal:
    price = price_for(model)
    if price is None:
        logger.warning("No price for model %r; recording its usage at $0", model)
        return Decimal(0)
    per_in = Decimal(str(price[0])) / Decimal(1_000_000)
    per_out = Decimal(str(price[1])) / Decimal(1_000_000)
    read_multiplier = OPENAI_CACHED_INPUT_MULTIPLIER if provider == "openai" else CACHE_READ_MULTIPLIER
    usd = (
        counts.input * per_in
        + counts.output * per_out
        + counts.cache_read * per_in * read_multiplier
        + counts.cache_write_5m * per_in * CACHE_WRITE_5M_MULTIPLIER
        + counts.cache_write_1h * per_in * CACHE_WRITE_1H_MULTIPLIER
    )
    return usd.quantize(Decimal("0.000001"))


def anthropic_counts(usage: Any) -> TokenCounts:
    total_write = getattr(usage, "cache_creation_input_tokens", None) or 0
    breakdown = getattr(usage, "cache_creation", None)
    write_1h = (getattr(breakdown, "ephemeral_1h_input_tokens", None) or 0) if breakdown else 0
    write_5m = (getattr(breakdown, "ephemeral_5m_input_tokens", None) or 0) if breakdown else 0
    # Responses without the TTL breakdown report only the total, which is the 5-minute default.
    write_5m += max(0, total_write - write_1h - write_5m)
    return TokenCounts(
        input=getattr(usage, "input_tokens", None) or 0,
        output=getattr(usage, "output_tokens", None) or 0,
        cache_read=getattr(usage, "cache_read_input_tokens", None) or 0,
        cache_write_5m=write_5m,
        cache_write_1h=write_1h,
    )


def openai_counts(usage: Any) -> TokenCounts:
    prompt = getattr(usage, "prompt_tokens", None) or 0
    details = getattr(usage, "prompt_tokens_details", None)
    cached = (getattr(details, "cached_tokens", None) or 0) if details else 0
    return TokenCounts(
        input=max(0, prompt - cached),
        output=getattr(usage, "completion_tokens", None) or 0,
        cache_read=cached,
    )


def _uuid(value: Any) -> Optional[uuid.UUID]:
    if value is None:
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        return None


def write_usage(attrs: dict, model: str, counts: TokenCounts, usd: Decimal) -> None:
    from app.database import SessionLocal
    from app.models.ai_usage import AiUsage
    from app.models.project import TranslationProject

    db = SessionLocal()
    try:
        project_id = _uuid(attrs.get("project_id"))
        team_id = _uuid(attrs.get("team_id"))
        user_id = _uuid(attrs.get("user_id"))
        if project_id and (team_id is None or user_id is None):
            owner = (
                db.query(TranslationProject.team_id, TranslationProject.user_id)
                .filter(TranslationProject.id == project_id)
                .first()
            )
            if owner is None:
                project_id = None
            else:
                team_id = team_id or owner.team_id
                user_id = user_id or owner.user_id
        db.add(AiUsage(
            team_id=team_id,
            project_id=project_id,
            user_id=user_id,
            action=attrs.get("action") or UNKNOWN_ACTION,
            model=model or "unknown",
            input_tokens=counts.input,
            output_tokens=counts.output,
            cache_read_tokens=counts.cache_read,
            cache_write_tokens=counts.cache_write,
            usd=usd,
        ))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Couldn't record AI usage (model=%s action=%s)", model, attrs.get("action"))
    finally:
        db.close()


def record_anthropic(response: Any) -> None:
    try:
        usage = getattr(response, "usage", None)
        if usage is None or not hasattr(usage, "input_tokens"):
            return
        model = getattr(response, "model", "") or ""
        counts = anthropic_counts(usage)
        write_usage(current(), model, counts, cost_usd(model, counts, "anthropic"))
    except Exception:
        logger.exception("Couldn't meter an Anthropic response")


def record_openai(response: Any) -> None:
    try:
        usage = getattr(response, "usage", None)
        if usage is None or not hasattr(usage, "prompt_tokens"):
            return
        model = getattr(response, "model", "") or ""
        counts = openai_counts(usage)
        write_usage(current(), model, counts, cost_usd(model, counts, "openai"))
    except Exception:
        logger.exception("Couldn't meter an OpenAI response")


def _wrap_create(cls: Any, recorder: Callable[[Any], None]) -> None:
    original = cls.create

    @functools.wraps(original)
    def create(self, *args, **kwargs):
        response = original(self, *args, **kwargs)
        recorder(response)
        return response

    cls.create = create


def install_hooks() -> None:
    """Patch the SDK classes once so every request anywhere in the process is metered."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        from anthropic.lib.streaming import MessageStream
        from anthropic.resources.beta.messages import Messages as BetaMessages
        from anthropic.resources.messages import Messages

        _wrap_create(Messages, record_anthropic)
        _wrap_create(BetaMessages, record_anthropic)
        original_final = MessageStream.get_final_message

        @functools.wraps(original_final)
        def get_final_message(self):
            message = original_final(self)
            # get_final_text() and repeat calls return the same message; meter it once.
            if not getattr(self, "_ai_usage_recorded", False):
                self._ai_usage_recorded = True
                record_anthropic(message)
            return message

        MessageStream.get_final_message = get_final_message
    except Exception:
        logger.exception("Anthropic usage hooks not installed")
    try:
        from openai.resources.chat.completions import Completions

        _wrap_create(Completions, record_openai)
    except Exception:
        logger.exception("OpenAI usage hooks not installed")


_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_PROJECT_PATH_RE = re.compile(r"^/projects/(" + _UUID_RE.pattern + r")(?:/|$)")


async def attribution_middleware(request, call_next):
    """Default attribution for any AI call a route makes without setting its own context."""
    path = request.url.path
    match = _PROJECT_PATH_RE.match(path)
    action = f"http:{request.method} {_UUID_RE.sub('{id}', path)}"
    with ai_context(action=action, project_id=match.group(1) if match else None):
        return await call_next(request)
