"""Model defaults and per-model request parameters shared by every Claude call site."""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import anthropic

logger = logging.getLogger(__name__)

REBUILD_MODEL = os.getenv("REBUILD_DEFAULT_MODEL", "claude-opus-4-8")
REBUILD_FALLBACK_MODELS = ("claude-sonnet-4-6", "claude-sonnet-4-5-20250929")
CLASSIFIER_MODEL = os.getenv("REBUILD_CLASSIFIER_MODEL", "claude-haiku-4-5-20251001")
FORM_DUMP_MODEL = os.getenv("REBUILD_FORM_DUMP_MODEL", "claude-opus-4-8")
TABLE_EXTRACT_MODEL = os.getenv("REBUILD_TABLE_MODEL", "claude-opus-4-8")
IMAGE_REGION_MODEL = os.getenv("REBUILD_IMAGE_REGION_MODEL", "claude-opus-4-6")

STREAMING_THRESHOLD_TOKENS = 16000

ALWAYS_THINKING = "always_thinking"
ADAPTIVE_NO_SAMPLING = "adaptive_no_sampling"
ADAPTIVE = "adaptive"
BUDGET = "budget"

_CATEGORIES = (
    (("claude-fable", "claude-mythos", "claude-opus-5-5"), ALWAYS_THINKING),
    (("claude-opus-5", "claude-sonnet-5", "claude-opus-4-8", "claude-opus-4-7"), ADAPTIVE_NO_SAMPLING),
    (("claude-opus-4-6", "claude-sonnet-4-6"), ADAPTIVE),
    (("claude-opus-4", "claude-sonnet-4", "claude-haiku-4", "claude-3"), BUDGET),
)

_CACHE_MIN_TOKENS = (
    (("claude-opus-5", "claude-fable", "claude-mythos-5"), 512),
    (("claude-opus-4-8", "claude-sonnet-5", "claude-sonnet-4-6", "claude-sonnet-4-5", "claude-opus-4-1"), 1024),
    (("claude-opus-4-7", "claude-mythos-preview"), 2048),
)


def rebuild_model(model: Optional[str] = None) -> str:
    return (model or "").strip() or REBUILD_MODEL


def model_category(model: str) -> str:
    m = (model or "").strip().lower()
    for prefixes, category in _CATEGORIES:
        if m.startswith(prefixes):
            return category
    return ADAPTIVE_NO_SAMPLING


def request_params(
    model: str,
    *,
    max_tokens: int,
    thinking: bool = False,
    effort: Optional[str] = None,
    temperature: Optional[float] = None,
) -> dict[str, Any]:
    """Return the thinking / effort / sampling kwargs this model accepts."""
    category = model_category(model)
    m = (model or "").strip().lower()
    params: dict[str, Any] = {}
    thinking_on = thinking or category == ALWAYS_THINKING

    if category == BUDGET:
        if thinking and max_tokens > 2048:
            budget = min(max(1024, max_tokens // 2), max_tokens - 1024)
            params["thinking"] = {"type": "enabled", "budget_tokens": budget}
        else:
            thinking_on = False
    elif thinking:
        params["thinking"] = {"type": "adaptive"}
    elif m.startswith("claude-opus-5"):
        params["thinking"] = {"type": "disabled"}

    if effort:
        if category in (ALWAYS_THINKING, ADAPTIVE_NO_SAMPLING):
            params["output_config"] = {"effort": effort}
        elif category == ADAPTIVE or m.startswith("claude-opus-4-5"):
            params["output_config"] = {"effort": "high" if effort == "xhigh" else effort}

    if temperature is not None and category in (ADAPTIVE, BUDGET) and not thinking_on:
        # anthropic>=1.0 dropped `temperature` from the method signatures; these models still accept it.
        params["extra_body"] = {"temperature": temperature}
    return params


def cache_min_tokens(model: str) -> int:
    m = (model or "").strip().lower()
    for prefixes, minimum in _CACHE_MIN_TOKENS:
        if m.startswith(prefixes):
            return minimum
    return 4096


def worth_caching(model: str, text: str) -> bool:
    return len(text) // 4 >= cache_min_tokens(model)


def cached_text_block(text: str, ttl: Optional[str] = None) -> dict[str, Any]:
    cache_control: dict[str, Any] = {"type": "ephemeral"}
    if ttl:
        cache_control["ttl"] = ttl
    return {"type": "text", "text": text, "cache_control": cache_control}


def system_param(model: str, text: str) -> Any:
    return [cached_text_block(text)] if worth_caching(model, text) else text


def create_message(client: Any, **kwargs: Any) -> Any:
    """messages.create, switching to streaming when max_tokens is large enough to risk an HTTP timeout."""
    if kwargs.get("max_tokens", 0) > STREAMING_THRESHOLD_TOKENS:
        with client.messages.stream(**kwargs) as stream:
            return stream.get_final_message()
    return client.messages.create(**kwargs)


def is_fallback_error(exc: BaseException) -> bool:
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in (400, 404, 408, 409, 429) or exc.status_code >= 500
    return False


def log_usage(label: str, resp: Any) -> None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    logger.info(
        "%s usage: model=%s in=%s out=%s cache_read=%s cache_write=%s",
        label,
        getattr(resp, "model", "?"),
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
        getattr(usage, "cache_read_input_tokens", None),
        getattr(usage, "cache_creation_input_tokens", None),
    )


def api_key() -> Optional[str]:
    """Environment first (production), then settings, which also read backend/.env locally."""
    import os

    from app.config import settings

    return os.getenv("ANTHROPIC_API_KEY") or settings.ANTHROPIC_API_KEY
