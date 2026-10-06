import anthropic
import httpx2
import pytest

from app.services import claude_params


def _status_error(cls, status):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(status, request=request), body=None)


@pytest.mark.parametrize("model", ["claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-5"])
def test_no_sampling_models_get_adaptive_thinking_and_never_temperature(model):
    params = claude_params.request_params(model, max_tokens=64000, thinking=True, temperature=0.2)
    assert params == {"thinking": {"type": "adaptive"}}
    assert claude_params.request_params(model, max_tokens=16000, temperature=0.1) == {}


@pytest.mark.parametrize("model", ["claude-opus-4-6", "claude-sonnet-4-6"])
def test_46_models_adaptive_with_temperature_only_without_thinking(model):
    assert claude_params.request_params(model, max_tokens=32000, thinking=True, temperature=0.2) == {
        "thinking": {"type": "adaptive"}
    }
    assert claude_params.request_params(model, max_tokens=8000, temperature=0.1) == {
        "extra_body": {"temperature": 0.1}
    }


@pytest.mark.parametrize("model", ["claude-haiku-4-5-20251001", "claude-haiku-4-5", "claude-sonnet-4-5-20250929"])
def test_budget_models_use_budget_tokens_below_max_tokens(model):
    params = claude_params.request_params(model, max_tokens=64000, thinking=True, temperature=0.2)
    budget = params["thinking"]["budget_tokens"]
    assert params["thinking"]["type"] == "enabled"
    assert 1024 <= budget < 64000
    assert "extra_body" not in params
    assert claude_params.request_params(model, max_tokens=20, thinking=True, temperature=0) == {
        "extra_body": {"temperature": 0}
    }


def test_effort_is_mapped_per_model():
    assert claude_params.request_params("claude-opus-4-8", max_tokens=1000, effort="xhigh")["output_config"] == {
        "effort": "xhigh"
    }
    assert claude_params.request_params("claude-opus-4-6", max_tokens=1000, effort="xhigh")["output_config"] == {
        "effort": "high"
    }
    assert "output_config" not in claude_params.request_params("claude-haiku-4-5", max_tokens=1000, effort="low")


def test_always_thinking_models_send_no_thinking_or_temperature():
    assert claude_params.request_params("claude-fable-5", max_tokens=8000, temperature=0.3) == {}


def test_opus_55_never_gets_thinking_disabled():
    assert claude_params.request_params("claude-opus-5-5", max_tokens=8000, temperature=0.3) == {}
    assert claude_params.request_params("claude-opus-5-5", max_tokens=8000, effort="low") == {
        "output_config": {"effort": "low"}
    }


def test_opus_5_disables_thinking_only_at_high_effort_or_below():
    assert claude_params.request_params("claude-opus-5", max_tokens=8000) == {"thinking": {"type": "disabled"}}
    assert claude_params.request_params("claude-opus-5", max_tokens=8000, effort="xhigh") == {
        "output_config": {"effort": "xhigh"}
    }


def test_rebuild_model_prefers_explicit_then_default(monkeypatch):
    assert claude_params.rebuild_model("claude-sonnet-4-6") == "claude-sonnet-4-6"
    monkeypatch.setattr(claude_params, "REBUILD_MODEL", "claude-opus-4-6")
    assert claude_params.rebuild_model(None) == "claude-opus-4-6"
    assert claude_params.rebuild_model("  ") == "claude-opus-4-6"


def test_create_message_streams_above_threshold():
    calls = []

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return "streamed"

    class _Messages:
        def create(self, **kwargs):
            calls.append(("create", kwargs["max_tokens"]))
            return "created"

        def stream(self, **kwargs):
            calls.append(("stream", kwargs["max_tokens"]))
            return _Stream()

    client = type("C", (), {"messages": _Messages()})()
    assert claude_params.create_message(client, model="m", max_tokens=16000, messages=[]) == "created"
    assert claude_params.create_message(client, model="m", max_tokens=64000, messages=[]) == "streamed"
    assert calls == [("create", 16000), ("stream", 64000)]


def test_fallback_error_classification():
    assert claude_params.is_fallback_error(_status_error(anthropic.OverloadedError, 529))
    assert claude_params.is_fallback_error(_status_error(anthropic.NotFoundError, 404))
    assert claude_params.is_fallback_error(_status_error(anthropic.BadRequestError, 400))
    assert claude_params.is_fallback_error(_status_error(anthropic.RateLimitError, 429))
    assert not claude_params.is_fallback_error(_status_error(anthropic.AuthenticationError, 401))
    assert not claude_params.is_fallback_error(_status_error(anthropic.PermissionDeniedError, 403))
    assert not claude_params.is_fallback_error(ValueError("x"))


def test_cache_minimums():
    assert claude_params.worth_caching("claude-sonnet-4-6", "x" * 4200)
    assert not claude_params.worth_caching("claude-haiku-4-5-20251001", "x" * 4200)
    assert claude_params.system_param("claude-sonnet-4-6", "short") == "short"
