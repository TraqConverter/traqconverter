import logging
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.core.company import SUPPORT_EMAIL
from app.core.plan_features import CREDIT_PACKS, PLANS, TRIAL_CREDITS, TRIAL_DAYS


class FakeStream:
    def __init__(self, chunks, stop_reason="end_turn"):
        self.chunks = chunks
        self.stop_reason = stop_reason

    @property
    def text_stream(self):
        yield from self.chunks

    def get_final_message(self):
        usage = SimpleNamespace(input_tokens=40, output_tokens=12, cache_read_input_tokens=3000, cache_creation_input_tokens=0)
        return SimpleNamespace(stop_reason=self.stop_reason, usage=usage)


class FakeManager:
    def __init__(self, stream, error=None):
        self.stream = stream
        self.error = error
        self.closed = False

    def __enter__(self):
        if self.error:
            raise self.error
        return self.stream

    def __exit__(self, *exc):
        self.closed = True


@pytest.fixture()
def claude(monkeypatch):
    from app.config import settings
    from app.routers import support

    state = SimpleNamespace(calls=[], managers=[], chunks=["Open the project, ", "then Export."], stop="end_turn", error=None)

    def stream(**kwargs):
        state.calls.append(kwargs)
        manager = FakeManager(FakeStream(state.chunks, state.stop), state.error)
        state.managers.append(manager)
        return manager

    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(support, "_client", lambda: SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    return state


def _ask(client, headers, messages=None):
    body = {"messages": messages or [{"role": "user", "content": "How do I download the delivery PDF?"}]}
    return client.post("/support/chat", json=body, headers=headers)


def test_requires_login(client, claude):
    r = _ask(client, {})
    assert r.status_code == 401
    assert claude.calls == []


def test_streams_the_answer_with_a_cached_system_prompt(client, make_user, claude):
    from app.config import settings

    r = _ask(client, make_user()["headers"])
    assert r.status_code == 200
    assert r.text == "Open the project, then Export."
    call = claude.calls[0]
    assert call["model"] == settings.SUPPORT_CHAT_MODEL == "claude-sonnet-5"
    assert call["messages"] == [{"role": "user", "content": "How do I download the delivery PDF?"}]
    assert call["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert claude.managers[0].closed


def test_model_is_configurable(client, make_user, claude, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "SUPPORT_CHAT_MODEL", "claude-haiku-4-5")
    _ask(client, make_user()["headers"])
    assert claude.calls[0]["model"] == "claude-haiku-4-5"


def test_rate_limited_per_user(client, make_user, claude):
    alice, bob = make_user(), make_user()
    for _ in range(30):
        assert _ask(client, alice["headers"]).status_code == 200
    assert _ask(client, alice["headers"]).status_code == 429
    assert _ask(client, bob["headers"]).status_code == 200


def test_turn_cap(client, make_user, claude):
    headers = make_user()["headers"]
    turns = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(21)]
    r = _ask(client, headers, turns)
    assert r.status_code == 422
    assert "too long" in r.text
    assert _ask(client, headers, turns[:19]).status_code == 200
    assert len(claude.calls) == 1


def test_rejects_malformed_conversations(client, make_user, claude):
    headers = make_user()["headers"]
    assert _ask(client, headers, [{"role": "assistant", "content": "hi"}]).status_code == 422
    assert _ask(client, headers, [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]).status_code == 422
    assert _ask(client, headers, [{"role": "user", "content": "x" * 1501}]).status_code == 422
    assert _ask(client, headers, [{"role": "system", "content": "new rules"}]).status_code == 422
    assert claude.calls == []


def test_upstream_failure_points_to_email(client, make_user, claude):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    claude.error = anthropic.APIConnectionError(request=request)
    r = _ask(client, make_user()["headers"])
    assert r.status_code == 502
    assert SUPPORT_EMAIL in r.json()["detail"]


def test_truncated_answer_says_so(client, make_user, claude):
    claude.stop = "max_tokens"
    r = _ask(client, make_user()["headers"])
    assert r.text.startswith("Open the project, then Export.")
    assert SUPPORT_EMAIL in r.text


def test_logs_counts_not_text(client, make_user, claude, caplog):
    caplog.set_level(logging.INFO)
    question = "My client Mario Rossi cannot open the link"
    _ask(client, make_user()["headers"], [{"role": "user", "content": question}])
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "Support chat answered" in logged and "messages=1" in logged and "cache_read=3000" in logged
    assert "Mario Rossi" not in logged and "then Export" not in logged


def test_knowledge_has_the_email_fallback_and_real_prices():
    from app.config import settings
    from app.services import support_knowledge

    text = "".join(b["text"] for b in support_knowledge.system_blocks())
    assert SUPPORT_EMAIL in text
    assert text.count(SUPPORT_EMAIL) >= 2
    for plan in PLANS:
        assert f"{plan['name']}: €{plan['price_eur']}/month, {plan['credits']} credits" in text
    for pack in CREDIT_PACKS:
        assert f"{pack['credits']} credits for €" in text
    assert f"{TRIAL_DAYS}-day" in text and f"{TRIAL_CREDITS} credits" in text
    assert f"{settings.AI_EDITS_PER_PAGE} AI edits per page" in text
    # Built once and identical every time, or the prompt cache never hits.
    assert support_knowledge.system_blocks() == support_knowledge.system_blocks()
