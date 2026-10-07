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
    owner, project = doc_project(credits=5, pages=1, used=3)
    r = chat(owner, project)
    assert r.status_code == 200, r.text
    assert r.json()["ai_edits_remaining"] == 1

    assert chat(owner, project).json()["ai_edits_remaining"] == 0
    assert _wallet(db, owner).subscription_credits == 5

    # The 6th edit on a 1-page document opens the first paid block.
    r = chat(owner, project)
    assert r.status_code == 200 and r.json()["ai_edits_remaining"] == 0
    assert _edit_charges(db, project) == [f"{project.id}:ai-edits:0"]
    assert _wallet(db, owner).subscription_credits == 4

    for _ in range(4):
        assert chat(owner, project).status_code == 200
    assert _project(db, project.id).ai_edits_used == 10
    assert _wallet(db, owner).subscription_credits == 4

    # The 11th opens the second.
    assert chat(owner, project).status_code == 200
    assert _edit_charges(db, project) == [f"{project.id}:ai-edits:0", f"{project.id}:ai-edits:1"]
    assert _wallet(db, owner).subscription_credits == 3

    a = client.get(f"/projects/{project.id}/ai-allowance", headers=owner["headers"]).json()
    assert a == {
        "included": 5,
        "used": 11,
        "remaining_included": 0,
        "next_block_cost_credits": 1,
        "edits_per_extra_credit": 5,
        "credits_charged": 2,
        "regenerations_used": 0,
        "regenerations_max": 3,
        "regenerations_free": 1,
        "next_regenerate_cost_credits": 0,
    }


@pytest.mark.parametrize("pages,included", [(1, 5), (3, 15)])
def test_included_edits_scale_with_pages(pages, included):
    from app.services import ai_allowance

    project = TranslationProject(page_count=pages, ai_edits_used=0)
    assert ai_allowance.included_edits(project) == included
    assert ai_allowance._block_of(project, included) is None
    assert ai_allowance._block_of(project, included + 1) == 0
    assert ai_allowance._block_of(project, included + 5) == 0
    assert ai_allowance._block_of(project, included + 6) == 1


def test_edit_allowance_follows_settings(monkeypatch):
    from app.config import settings
    from app.services import ai_allowance

    monkeypatch.setattr(settings, "AI_EDITS_PER_PAGE", 10)
    monkeypatch.setattr(settings, "AI_EDITS_PER_EXTRA_CREDIT", 10)
    project = TranslationProject(page_count=2, ai_edits_used=0)
    assert ai_allowance.included_edits(project) == 20
    assert ai_allowance._block_of(project, 30) == 0 and ai_allowance._block_of(project, 31) == 1
    assert ai_allowance.out_of_edits_message().endswith("1 credit adds 10 more.")


def test_existing_project_over_the_new_allowance_is_not_charged_retroactively(client, db, doc_project, chat):
    owner, project = doc_project(credits=5, pages=1, used=8)
    a = client.get(f"/projects/{project.id}/ai-allowance", headers=owner["headers"]).json()
    assert (a["remaining_included"], a["credits_charged"]) == (0, 0)
    assert _wallet(db, owner).subscription_credits == 5

    # Only the next edit is charged: the 9th falls in the first paid block.
    assert chat(owner, project).status_code == 200
    assert _edit_charges(db, project) == [f"{project.id}:ai-edits:0"]
    assert _wallet(db, owner).subscription_credits == 4


def test_chat_usage_is_attributed_to_the_editing_user(db, doc_project, chat):
    owner, project = doc_project()
    assert chat(owner, project).status_code == 200
    [row] = _usage_rows(db)
    assert (row.action, row.project_id, row.team_id, row.user_id) == ("document_chat", project.id, owner["team"].id, owner["user"].id)
    assert row.usd == USAGE_USD


def test_out_of_edits_without_credits_is_402_before_calling_claude(db, doc_project, chat):
    owner, project = doc_project(credits=0, pages=1, used=5)
    r = chat(owner, project)
    assert r.status_code == 402
    assert r.json()["detail"] == "You've used the AI edits included with this document. 1 credit adds 5 more."
    assert _project(db, project.id).ai_edits_used == 5
    assert _usage_rows(db) == []


def test_failed_chat_is_not_counted_and_block_charge_is_idempotent(db, doc_project, chat, monkeypatch):
    owner, project = doc_project(credits=5, pages=1, used=5)

    def fail(*a, **k):
        raise document_editor.ChatEditError("The AI assistant couldn't complete that edit")

    with monkeypatch.context() as m:
        m.setattr(document_editor, "chat_edit", fail)
        assert chat(owner, project).status_code == 502
        assert chat(owner, project).status_code == 502
    assert _project(db, project.id).ai_edits_used == 5
    assert _wallet(db, owner).subscription_credits == 4

    assert chat(owner, project).status_code == 200
    assert _project(db, project.id).ai_edits_used == 6
    assert _wallet(db, owner).subscription_credits == 4
    assert _edit_charges(db, project) == [f"{project.id}:ai-edits:0"]


def test_staff_are_counted_but_never_charged(db, doc_project, chat):
    owner, project = doc_project(credits=0, pages=1, used=5, role="ADMIN")
    assert chat(owner, project).status_code == 200
    assert _project(db, project.id).ai_edits_used == 6
    assert _edit_charges(db, project) == []


def test_allowance_scales_with_pages_and_hides_other_tenants(client, doc_project, make_user):
    owner, project = doc_project(pages=3, used=4)
    a = client.get(f"/projects/{project.id}/ai-allowance", headers=owner["headers"]).json()
    assert (a["included"], a["remaining_included"]) == (15, 11)
    assert client.get(f"/projects/{project.id}/ai-allowance", headers=make_user()["headers"]).status_code == 404


# --- Regenerate: first free, then one credit per page, hard cap ------------


@pytest.fixture()
def no_background_ai(monkeypatch):
    from app.services import ai_actions

    calls = []
    monkeypatch.setattr(ai_actions, "run_rebuild", lambda *a: calls.append(("rebuild", a)))
    return calls


def _finish_rebuild(db, project):
    db.query(TranslationProject).filter(TranslationProject.id == project.id).update({"rebuild_status": "done"})
    db.commit()


def _regenerate(client, owner, project):
    return client.post(f"/projects/{project.id}/rebuild-with-claude", headers=owner["headers"])


def _regen_rows(db, project):
    db.expire_all()
    return (
        db.query(CreditTransaction)
        .filter(CreditTransaction.reference_id.like(f"%regenerate:{project.id}:%"))
        .order_by(CreditTransaction.created_at)
        .all()
    )


def _age_charge(db, reference, hours=2):
    db.query(CreditTransaction).filter(CreditTransaction.reference_id == reference).update(
        {"created_at": datetime.utcnow() - timedelta(hours=hours)}
    )
    db.commit()


def test_first_regenerate_is_free_then_one_credit_per_page_up_to_three(client, db, make_user, make_project, no_background_ai):
    owner = make_user(credits=10)
    project = make_project(owner, pages=3)
    a = client.get(f"/projects/{project.id}/ai-allowance", headers=owner["headers"]).json()
    assert (a["next_regenerate_cost_credits"], a["regenerations_max"], a["regenerations_free"]) == (0, 3, 1)

    r = _regenerate(client, owner, project)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["charged"], body["credits_charged"], body["regenerations_left"], body["next_regenerate_cost_credits"]) == (False, 0, 2, 3)
    assert _wallet(db, owner).subscription_credits == 10 and _regen_rows(db, project) == []
    _finish_rebuild(db, project)

    r = _regenerate(client, owner, project)
    assert r.status_code == 200, r.text
    assert (r.json()["charged"], r.json()["credits_charged"], r.json()["regenerations_left"]) == (True, 3, 1)
    [row] = _regen_rows(db, project)
    assert (row.type, row.amount, row.reference_id) == ("USAGE", -3, f"regenerate:{project.id}:1")
    assert (row.from_subscription, row.from_purchased) == (3, 0)
    assert _wallet(db, owner).subscription_credits == 7
    _finish_rebuild(db, project)

    assert _regenerate(client, owner, project).status_code == 200
    _finish_rebuild(db, project)
    assert _wallet(db, owner).subscription_credits == 4

    r = _regenerate(client, owner, project)
    assert r.status_code == 403
    assert r.json()["detail"] == "Regenerate is limited to 3 per document"
    assert _wallet(db, owner).subscription_credits == 4
    assert len(no_background_ai) == 3
    a = client.get(f"/projects/{project.id}/ai-allowance", headers=owner["headers"]).json()
    assert (a["regenerations_used"], a["regenerations_max"]) == (3, 3)


def test_paid_regenerate_splits_subscription_and_purchased_credits(client, db, make_user, make_project, no_background_ai):
    owner = make_user(credits=1)
    project = make_project(owner, pages=3)
    project.revision_count = 1
    db.commit()
    wallet = _wallet(db, owner)
    wallet.purchased_credits = 5
    db.commit()

    assert _regenerate(client, owner, project).status_code == 200
    [row] = _regen_rows(db, project)
    assert (row.from_subscription, row.from_purchased) == (1, 2)
    wallet = _wallet(db, owner)
    assert (wallet.subscription_credits, wallet.purchased_credits) == (0, 3)


def test_regenerate_without_enough_credits_is_402(client, db, make_user, make_project, no_background_ai):
    owner = make_user(credits=2)
    project = make_project(owner, pages=3)
    project.revision_count = 1
    db.commit()

    r = _regenerate(client, owner, project)
    assert r.status_code == 402
    assert r.json()["detail"] == "Regenerating again costs 3 credits (one per page). Add credits in Billing."
    row = _project(db, project.id)
    assert row.revision_count == 1 and row.rebuild_status is None
    assert no_background_ai == [] and _regen_rows(db, project) == []
    assert _wallet(db, owner).subscription_credits == 2


def test_failed_paid_regenerate_refunds_once_and_gives_the_attempt_back(client, db, make_user, make_project, monkeypatch):
    from app.services import ai_actions

    real_run_rebuild = ai_actions.run_rebuild
    monkeypatch.setattr(ai_actions, "run_rebuild", lambda *a: None)
    owner = make_user(credits=10)
    project = make_project(owner, pages=2)
    project.revision_count = 1
    db.commit()
    assert _regenerate(client, owner, project).status_code == 200
    assert _wallet(db, owner).subscription_credits == 8

    _project(db, project.id).file_path = "uploads/missing.pdf"
    db.commit()
    real_run_rebuild(str(project.id), None)
    row = _project(db, project.id)
    assert row.rebuild_status == "failed" and row.revision_count == 1
    assert _wallet(db, owner).subscription_credits == 10

    # A second give-back of the same attempt (the stale sweep) must not refund it again.
    row.rebuild_status = "running"
    row.revision_count = 2
    row.rebuild_started_at = datetime.utcnow() - timedelta(hours=2)
    db.commit()
    _age_charge(db, f"regenerate:{project.id}:1")
    assert ai_actions.expire_stale_rebuilds(db) == 1
    db.commit()
    assert _wallet(db, owner).subscription_credits == 10
    refunds = [r for r in _regen_rows(db, project) if r.type == "REFUND"]
    assert [(r.amount, r.reference_id) for r in refunds] == [(2, f"refund:regenerate:{project.id}:1")]

    # The retry is a fresh charge under the next reference.
    row = _project(db, project.id)
    row.rebuild_status = "failed"
    row.revision_count = 1
    db.commit()
    assert _regenerate(client, owner, project).status_code == 200
    assert _wallet(db, owner).subscription_credits == 8
    assert [r.reference_id for r in _regen_rows(db, project) if r.type == "USAGE"] == [
        f"regenerate:{project.id}:1",
        f"regenerate:{project.id}:2",
    ]


def test_stale_paid_regenerate_is_refunded(client, db, make_user, make_project, no_background_ai):
    from app.services import ai_actions

    owner = make_user(credits=10)
    project = make_project(owner, pages=4)
    project.revision_count = 1
    db.commit()
    assert _regenerate(client, owner, project).status_code == 200
    assert _wallet(db, owner).subscription_credits == 6

    _project(db, project.id).rebuild_started_at = datetime.utcnow() - timedelta(hours=2)
    db.commit()
    _age_charge(db, f"regenerate:{project.id}:1")
    assert ai_actions.expire_stale_rebuilds(db) == 1
    db.commit()
    assert _project(db, project.id).revision_count == 1
    assert _wallet(db, owner).subscription_credits == 10


def test_failed_uncharged_regenerate_keeps_earlier_charges(db, make_user, make_project):
    from app.services import ai_actions
    from app.services.credit_service import CreditService

    owner = make_user(credits=10)
    project = make_project(owner, pages=2)
    project.revision_count = 2
    CreditService.deduct_credits(db, str(owner["team"].id), 2, f"regenerate:{project.id}:1")
    db.commit()
    _age_charge(db, f"regenerate:{project.id}:1", hours=24)
    project = _project(db, project.id)
    project.file_path = "uploads/missing.pdf"
    project.rebuild_status = "running"
    project.rebuild_started_at = datetime.utcnow()
    db.commit()

    ai_actions.run_rebuild(str(project.id), None)
    row = _project(db, project.id)
    assert row.rebuild_status == "failed" and row.revision_count == 1
    assert _wallet(db, owner).subscription_credits == 8


def test_staff_regenerate_for_free(client, db, make_user, make_project, no_background_ai):
    staff = make_user(credits=0)
    staff["user"].role = "SUPER_ADMIN"
    project = make_project(staff, pages=5)
    project.revision_count = 1
    db.commit()
    a = client.get(f"/projects/{project.id}/ai-allowance", headers=staff["headers"]).json()
    assert a["next_regenerate_cost_credits"] == 0
    r = _regenerate(client, staff, project)
    assert r.status_code == 200, r.text
    assert r.json()["charged"] is False
    assert _regen_rows(db, project) == []


def test_existing_project_with_two_old_free_regenerations_pays_for_the_third(client, db, make_user, make_project, no_background_ai):
    owner = make_user(credits=10)
    project = make_project(owner, pages=2)
    project.revision_count = 2
    db.commit()
    a = client.get(f"/projects/{project.id}/ai-allowance", headers=owner["headers"]).json()
    assert (a["regenerations_used"], a["next_regenerate_cost_credits"]) == (2, 2)
    assert client.get(f"/projects/{project.id}", headers=owner["headers"]).json()["next_regenerate_cost_credits"] == 2
    assert _wallet(db, owner).subscription_credits == 10

    assert _regenerate(client, owner, project).status_code == 200
    assert _wallet(db, owner).subscription_credits == 8
    _finish_rebuild(db, project)
    assert _regenerate(client, owner, project).status_code == 403


def test_editable_copy_regenerate_follows_the_same_rules(client, db, make_user, make_project, no_background_ai):
    from app.models.project import MODE_DTP

    owner = make_user(credits=10)
    project = make_project(owner, pages=2)
    project.mode = MODE_DTP
    db.commit()
    assert _regenerate(client, owner, project).json()["charged"] is False
    _finish_rebuild(db, project)
    r = _regenerate(client, owner, project)
    assert r.status_code == 200 and r.json()["credits_charged"] == 2
    assert _wallet(db, owner).subscription_credits == 8


def test_regenerate_rules_follow_settings(client, db, make_user, make_project, monkeypatch, no_background_ai):
    from app.config import settings

    monkeypatch.setattr(settings, "REGENERATE_FREE_PER_PROJECT", 2)
    monkeypatch.setattr(settings, "REGENERATE_LIMIT_PER_PROJECT", 2)
    owner = make_user(credits=10)
    project = make_project(owner, pages=2)
    for _ in range(2):
        r = _regenerate(client, owner, project)
        assert r.status_code == 200 and r.json()["charged"] is False
        _finish_rebuild(db, project)
    assert _regenerate(client, owner, project).json()["detail"] == "Regenerate is limited to 2 per document"


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
