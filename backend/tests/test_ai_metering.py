import io
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import anthropic
import httpx
import httpx2
import openai
import pytest
from docx import Document

from app.models.ai_usage import AiUsage
from app.models.credit import CreditTransaction, CreditWallet
from app.models.project import TranslationProject
from app.services import ai_usage, claude_params, document_editor


def _docx(*paras):
    doc = Document()
    for text in paras:
        doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _wallet(db, owner):
    db.expire_all()
    return db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).one()


def _project(db, project_id):
    db.expire_all()
    return db.query(TranslationProject).filter(TranslationProject.id == project_id).one()


def _usage_rows(db):
    db.expire_all()
    return db.query(AiUsage).order_by(AiUsage.created_at).all()


def _message_json(model, text, usage):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": usage,
    }


def _sse(model, text, usage):
    start = {**_message_json(model, "", {**usage, "output_tokens": 1}), "content": []}
    events = [
        ("message_start", {"type": "message_start", "message": start}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": usage["output_tokens"]}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(body)}\n\n" for name, body in events)


USAGE = {
    "input_tokens": 1000,
    "output_tokens": 500,
    "cache_read_input_tokens": 2000,
    "cache_creation_input_tokens": 500,
    "cache_creation": {"ephemeral_5m_input_tokens": 400, "ephemeral_1h_input_tokens": 100},
}
# 1000*3 + 500*15 + 2000*3*0.1 + 400*3*1.25 + 100*3*2, per million.
USAGE_USD = Decimal("0.013200")


def _anthropic_client(text="ok", model="claude-sonnet-4-6", usage=USAGE):
    def handler(request):
        if json.loads(request.content).get("stream"):
            return httpx2.Response(200, text=_sse(model, text, usage), headers={"content-type": "text/event-stream"})
        return httpx2.Response(200, json=_message_json(model, text, usage))

    return anthropic.Anthropic(api_key="test-key", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))


@pytest.fixture()
def hooks(db):
    ai_usage.install_hooks()


def test_price_table_resolves_snapshots_and_provider_prefixes():
    assert ai_usage.price_for("claude-haiku-4-5-20251001") == (1.0, 5.0)
    assert ai_usage.price_for("us.anthropic.claude-sonnet-4-6") == (3.0, 15.0)
    assert ai_usage.price_for("gpt-4.1-mini-2025-04-14") == (0.40, 1.60)
    assert ai_usage.price_for("gpt-4.1-2025-04-14") == (2.0, 8.0)
    assert ai_usage.price_for("mystery-model") is None


def test_sdk_create_hook_records_attributed_cost_with_cache_pricing(hooks, db, make_user, make_project):
    owner = make_user()
    project = make_project(owner)
    client = _anthropic_client()
    with ai_usage.ai_context(action="document_chat", project_id=project.id):
        client.messages.create(model="claude-sonnet-4-6", max_tokens=100, messages=[{"role": "user", "content": "hi"}])

    [row] = _usage_rows(db)
    assert row.action == "document_chat"
    assert row.project_id == project.id
    assert row.team_id == owner["team"].id
    assert row.user_id == owner["user"].id
    assert row.model == "claude-sonnet-4-6"
    assert (row.input_tokens, row.output_tokens, row.cache_read_tokens, row.cache_write_tokens) == (1000, 500, 2000, 500)
    assert row.usd == USAGE_USD


def test_stream_final_message_is_recorded_once(hooks, db):
    client = _anthropic_client(model="claude-opus-4-8")
    with ai_usage.ai_context(action="regenerate"):
        with client.messages.stream(model="claude-opus-4-8", max_tokens=100, messages=[{"role": "user", "content": "hi"}]) as stream:
            stream.get_final_message()
            stream.get_final_text()

    [row] = _usage_rows(db)
    assert row.action == "regenerate" and row.team_id is None
    assert row.output_tokens == 500
    # Opus is 5/3 of Sonnet on every component.
    assert row.usd == (USAGE_USD * 5 / 3).quantize(Decimal("0.000001"))


def test_unattributed_call_is_recorded_as_unknown(hooks, db):
    usage = {"input_tokens": 100, "output_tokens": 10, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 0}
    _anthropic_client(model="claude-haiku-4-5-20251001", usage=usage).messages.create(
        model="claude-haiku-4-5", max_tokens=10, messages=[{"role": "user", "content": "hi"}]
    )
    [row] = _usage_rows(db)
    assert row.action == "unknown" and row.project_id is None
    # Without the TTL breakdown the whole cache write is priced at the 5-minute rate.
    assert row.usd == Decimal("0.001400")


def test_openai_hook_records_cached_input(hooks, db):
    def handler(request):
        return httpx.Response(200, json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-4.1-mini-2025-04-14",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100, "prompt_tokens_details": {"cached_tokens": 200}},
        })

    client = openai.OpenAI(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with ai_usage.ai_context(action="retranslate"):
        client.chat.completions.create(model="gpt-4.1-mini", messages=[{"role": "user", "content": "hi"}])
    [row] = _usage_rows(db)
    assert (row.input_tokens, row.cache_read_tokens, row.output_tokens) == (800, 200, 100)
    assert row.usd == Decimal("0.000500")


def test_usage_write_failure_never_breaks_the_call(hooks, db, monkeypatch):
    import app.database

    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(app.database, "SessionLocal", broken)
    resp = _anthropic_client().messages.create(model="claude-sonnet-4-6", max_tokens=10, messages=[{"role": "user", "content": "hi"}])
    assert resp.content[0].text == "ok"


# --- AI edit allowance -------------------------------------------------------


@pytest.fixture()
def doc_project(db, storage, make_user, make_project):
    def _make(credits=100, pages=1, used=0, role=None):
        owner = make_user(credits=credits)
        if role:
            owner["user"].role = role
        project = make_project(owner, pages=pages)
        key = f"uploads/{uuid.uuid4()}_authored.docx"
        storage["objects"][key] = _docx("CERTIFICATE", "Mr. BIANCHI LUCA")
        project.authored_docx_s3_key = key
        project.ai_edits_used = used
        db.commit()
        return owner, project

    return _make


@pytest.fixture()
def chat(client, monkeypatch):
    monkeypatch.setattr(claude_params, "api_key", lambda: "test-key")
    reply = json.dumps({"reply": "The stamp reads 'Registry'.", "operations": []})
    real_client = _anthropic_client(text=reply)
    monkeypatch.setattr(document_editor.anthropic, "Anthropic", lambda **kw: real_client)

    def send(owner, project):
        v = client.get(f"/projects/{project.id}/document", headers=owner["headers"]).headers["X-Document-Version"]
        return client.post(
            f"/projects/{project.id}/document/chat",
            headers=owner["headers"],
            json={"version": int(v), "message": "What does the stamp say?"},
        )

    return send


def _edit_charges(db, project):
    db.expire_all()
    return sorted(
        r.reference_id
        for r in db.query(CreditTransaction).filter(CreditTransaction.reference_id.like(f"{project.id}:ai-edits:%"))
    )


def test_included_edits_then_one_credit_per_block(client, db, doc_project, chat):
    owner, project = doc_project(credits=5, pages=1, used=8)
    r = chat(owner, project)
    assert r.status_code == 200, r.text
    assert r.json()["ai_edits_remaining"] == 1

    assert chat(owner, project).json()["ai_edits_remaining"] == 0
    assert _wallet(db, owner).subscription_credits == 5

    r = chat(owner, project)
    assert r.status_code == 200 and r.json()["ai_edits_remaining"] == 0
    assert _edit_charges(db, project) == [f"{project.id}:ai-edits:0"]
    assert _wallet(db, owner).subscription_credits == 4

    project_row = _project(db, project.id)
    project_row.ai_edits_used = 20
    db.commit()
    chat(owner, project)
    assert _edit_charges(db, project) == [f"{project.id}:ai-edits:0", f"{project.id}:ai-edits:1"]
    assert _wallet(db, owner).subscription_credits == 3

    a = client.get(f"/projects/{project.id}/ai-allowance", headers=owner["headers"]).json()
    assert a == {
        "included": 10,
        "used": 21,
        "remaining_included": 0,
        "next_block_cost_credits": 1,
        "credits_charged": 2,
        "regenerations_used": 0,
        "regenerations_max": 2,
    }


def test_chat_usage_is_attributed_to_the_editing_user(db, doc_project, chat):
    owner, project = doc_project()
    assert chat(owner, project).status_code == 200
    [row] = _usage_rows(db)
    assert (row.action, row.project_id, row.team_id, row.user_id) == ("document_chat", project.id, owner["team"].id, owner["user"].id)
    assert row.usd == USAGE_USD


def test_out_of_edits_without_credits_is_402_before_calling_claude(db, doc_project, chat):
    owner, project = doc_project(credits=0, pages=1, used=10)
    r = chat(owner, project)
    assert r.status_code == 402
    assert r.json()["detail"] == "You've used the AI edits included with this document. 1 credit adds 10 more."
    assert _project(db, project.id).ai_edits_used == 10
    assert _usage_rows(db) == []


def test_failed_chat_is_not_counted_and_block_charge_is_idempotent(db, doc_project, chat, monkeypatch):
    owner, project = doc_project(credits=5, pages=1, used=10)

    def fail(*a, **k):
        raise document_editor.ChatEditError("The AI assistant couldn't complete that edit")

    with monkeypatch.context() as m:
        m.setattr(document_editor, "chat_edit", fail)
        assert chat(owner, project).status_code == 502
        assert chat(owner, project).status_code == 502
    assert _project(db, project.id).ai_edits_used == 10
    assert _wallet(db, owner).subscription_credits == 4

    assert chat(owner, project).status_code == 200
    assert _project(db, project.id).ai_edits_used == 11
    assert _wallet(db, owner).subscription_credits == 4
    assert _edit_charges(db, project) == [f"{project.id}:ai-edits:0"]


def test_staff_are_counted_but_never_charged(db, doc_project, chat):
    owner, project = doc_project(credits=0, pages=1, used=10, role="ADMIN")
    assert chat(owner, project).status_code == 200
    assert _project(db, project.id).ai_edits_used == 11
    assert _edit_charges(db, project) == []


def test_allowance_scales_with_pages_and_hides_other_tenants(client, doc_project, make_user):
    owner, project = doc_project(pages=3, used=4)
    a = client.get(f"/projects/{project.id}/ai-allowance", headers=owner["headers"]).json()
    assert (a["included"], a["remaining_included"]) == (30, 26)
    assert client.get(f"/projects/{project.id}/ai-allowance", headers=make_user()["headers"]).status_code == 404


# --- Regenerate hard cap -----------------------------------------------------


@pytest.fixture()
def no_background_ai(monkeypatch):
    from app.services import ai_actions

    calls = []
    monkeypatch.setattr(ai_actions, "run_rebuild", lambda *a: calls.append(("rebuild", a)))
    return calls


def _finish_rebuild(db, project):
    db.query(TranslationProject).filter(TranslationProject.id == project.id).update({"rebuild_status": "done"})
    db.commit()


def test_regenerate_has_a_hard_limit_of_two(client, db, make_user, make_project, no_background_ai):
    owner = make_user(credits=5)
    project = make_project(owner, pages=2)

    r = client.post(f"/projects/{project.id}/rebuild-with-claude", headers=owner["headers"])
    assert r.status_code == 200 and r.json()["charged"] is False and r.json()["regenerations_left"] == 1
    _finish_rebuild(db, project)
    r = client.post(f"/projects/{project.id}/rebuild-with-claude", headers=owner["headers"])
    assert r.status_code == 200, r.text
    _finish_rebuild(db, project)

    r = client.post(f"/projects/{project.id}/rebuild-with-claude", headers=owner["headers"])
    assert r.status_code == 403
    assert r.json()["detail"] == "Regenerate is limited to 2 per document"

    assert _wallet(db, owner).subscription_credits == 5
    assert len(no_background_ai) == 2
    a = client.get(f"/projects/{project.id}/ai-allowance", headers=owner["headers"]).json()
    assert (a["regenerations_used"], a["regenerations_max"]) == (2, 2)


def test_failed_rebuild_gives_the_attempt_back(client, db, make_user, make_project, monkeypatch):
    from app.services import ai_actions

    owner = make_user()
    project = make_project(owner)
    project.file_path = "uploads/missing.pdf"
    project.revision_count = 2
    project.rebuild_status = "running"
    db.commit()
    ai_actions.run_rebuild(str(project.id), None)
    row = _project(db, project.id)
    assert row.rebuild_status == "failed" and row.revision_count == 1


def test_stale_rebuild_gives_the_attempt_back(db, make_user, make_project):
    from app.services import ai_actions

    owner = make_user()
    project = make_project(owner)
    project.revision_count = 1
    project.rebuild_status = "running"
    project.rebuild_started_at = datetime.utcnow() - timedelta(hours=2)
    db.commit()
    assert ai_actions.expire_stale_rebuilds(db) == 1
    db.commit()
    assert _project(db, project.id).revision_count == 0


def test_regenerate_background_task_is_attributed(client, db, make_user, make_project, monkeypatch):
    from app.services import ai_actions

    seen = []
    monkeypatch.setattr(ai_actions, "run_rebuild", lambda *a: seen.append(ai_usage.current()))
    owner = make_user()
    project = make_project(owner)
    assert client.post(f"/projects/{project.id}/rebuild-with-claude", headers=owner["headers"]).status_code == 200
    assert seen[0]["action"] == "regenerate"
    assert str(seen[0]["user_id"]) == str(owner["user"].id)


# --- Admin report ------------------------------------------------------------


def test_admin_report_is_staff_only(client, make_user):
    member = make_user()
    assert client.get("/admin/ai-usage", headers=member["headers"]).status_code == 403


def test_admin_report_aggregates(client, db, make_user, make_project, monkeypatch):
    from app.config import settings
    from app.services.credit_service import CreditService

    monkeypatch.setattr(settings, "CREDIT_PRICE_CENTS", 100)
    staff = make_user()
    staff["user"].role = "SUPER_ADMIN"
    db.commit()
    a = make_user(credits=20)
    b = make_user(credits=20)
    a["team"].name = "Studio A"
    b["team"].name = "Studio B"
    pa = make_project(a)
    pb = make_project(b)
    now = datetime.utcnow()
    db.add_all([
        AiUsage(team_id=a["team"].id, project_id=pa.id, action="translation", model="claude-opus-4-8", usd=Decimal("1.50")),
        AiUsage(team_id=a["team"].id, project_id=pa.id, action="document_chat", model="claude-opus-4-8", usd=Decimal("0.25")),
        AiUsage(team_id=b["team"].id, project_id=pb.id, action="translation", model="claude-opus-4-8", usd=Decimal("0.40")),
        AiUsage(action="unknown", model="claude-haiku-4-5", usd=Decimal("0.05")),
        AiUsage(team_id=a["team"].id, action="translation", model="claude-opus-4-8", usd=Decimal("9"), created_at=now - timedelta(days=40)),
    ])
    CreditService.deduct_credits(db, str(a["team"].id), 3, "a-job")
    CreditService.deduct_credits(db, str(b["team"].id), 2, "b-job")
    db.flush()
    CreditService.refund_usage(db, "b-job")
    db.commit()

    r = client.get("/admin/ai-usage?days=30", headers=staff["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"]["calls"] == 4
    assert body["totals"]["usd"] == 2.2
    assert body["totals"]["credits"] == 3
    assert body["totals"]["margin_usd"] == 0.8
    assert [(x["action"], x["usd"], x["calls"]) for x in body["by_action"]] == [
        ("translation", 1.9, 2), ("document_chat", 0.25, 1), ("unknown", 0.05, 1)
    ]
    teams = {t["name"]: t for t in body["by_team"]}
    assert (teams["Studio A"]["usd"], teams["Studio A"]["credits"], teams["Studio A"]["revenue_usd"], teams["Studio A"]["margin_usd"]) == (1.75, 3, 3.0, 1.25)
    assert (teams["Studio B"]["credits"], teams["Studio B"]["margin_usd"]) == (0, -0.4)
    assert teams["Unattributed"]["usd"] == 0.05
    assert [p["project_id"] for p in body["top_projects"]] == [str(pa.id), str(pb.id)]
    assert body["top_projects"][0]["team_name"] == "Studio A"

    assert client.get("/admin/ai-usage?days=90", headers=staff["headers"]).json()["totals"]["usd"] == 11.2
