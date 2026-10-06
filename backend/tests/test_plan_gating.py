"""Trial and Basic plans: no translation memory, glossary, templates or certifications beyond what the plan includes."""
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.dependencies import feature_guard
from app.models.credit import CreditWallet
from app.models.glossary import Glossary
from app.models.learning import DocumentTemplate, PendingLearning
from app.models.project import ProjectStatus
from app.models.translation_memory import TranslationMemory
from app.models.translation_segment import TranslationSegment
from app.services import ai_translation_service as ats
from app.services import claude_params, docx_blocks, learning, template_fill
from app.services import translation_memory_service as tm
from tests.test_learning import KEY, PROFILE, _docx

SOURCE = [
    "L'UFFICIALE D'ANAGRAFE, visti gli atti d'ufficio,",
    "che il Sig. BIANCHI LUCA, nato a Bari il 12/03/1987,",
    "Ufficio Anagrafe e Stato Civile",
]
FIRST_PASS = [
    "THE REGISTRY OFFICER, having examined the records,",
    "that Mr. BIANCHI LUCA, born in Bari on 12/03/1987,",
    "Registry and Civil Status Office",
]
MEMORY = "THE REGISTRAR, having examined the office records,"


@pytest.fixture(autouse=True)
def no_claude(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("no model call expected")

    monkeypatch.setattr(claude_params, "create_message", boom)


@pytest.fixture()
def gated_project(db, storage, make_user, make_project):
    def _make(plan="PRO", **user_kw):
        owner = make_user(plan=plan, **user_kw)
        project = make_project(owner, segments=SOURCE)
        for seg in db.query(TranslationSegment).filter(TranslationSegment.project_id == project.id):
            seg.translated_text = FIRST_PASS[seg.segment_index]
        key = f"uploads/{uuid.uuid4()}_authored.docx"
        storage["objects"][key] = _docx(*FIRST_PASS)
        project.authored_docx_s3_key = key
        project.doc_key, project.doc_profile = KEY, PROFILE
        db.commit()
        return owner, project

    return _make


def _set_wallet(db, team_id, **values):
    db.query(CreditWallet).filter(CreditWallet.team_id == team_id).update(values)
    db.commit()


def _add_glossary(db, team_id):
    db.add(Glossary(team_id=team_id, source_language="Italian", target_language="English",
                    source_term="Stato Civile", target_term="Civil Registry", origin="manual"))
    db.commit()


def _add_memory(db, team_id):
    tm.store_tm_entry(db, team_id, "it", "en", SOURCE[0], MEMORY, origin="approved")


def _open(client, owner, project):
    r = client.get(f"/projects/{project.id}/document", headers=owner["headers"])
    return r.content, int(r.headers["X-Document-Version"])


# Plan resolution

def test_team_has_feature_follows_the_plan_matrix(db, make_user):
    pro, basic, trial = make_user(plan="PRO"), make_user(plan="BASIC"), make_user(plan="TRIAL")
    has = lambda owner, f: feature_guard.team_has_feature(db, owner["team"].id, f)
    for f in ("terminology_memory", "glossaries", "certifications", "templates"):
        assert has(pro, f) and not has(trial, f)
    assert has(basic, "templates") and not has(basic, "terminology_memory") and not has(basic, "glossaries")
    assert not has(basic, "certifications")
    assert feature_guard.team_has_feature(db, None, "templates") is False
    assert feature_guard.team_has_feature(db, uuid.uuid4(), "templates") is False


def test_team_has_feature_expired_plans_fail_closed(db, make_user):
    trial = make_user(plan="TRIAL", expires_in_days=-1)
    assert feature_guard.team_plan(db, trial["team"].id) == "EXPIRED"
    lapsed = make_user(plan="PRO")
    _set_wallet(db, lapsed["team"].id, subscription_status="CANCELED")
    assert feature_guard.team_plan(db, lapsed["team"].id) == "EXPIRED"
    assert not feature_guard.team_has_feature(db, lapsed["team"].id, "templates")


def test_team_has_feature_admin_owner_is_pro(db, make_user):
    admin = make_user(plan="TRIAL", expires_in_days=-1)
    admin["user"].role = "SUPER_ADMIN"
    db.commit()
    assert feature_guard.team_has_feature(db, admin["team"].id, "terminology_memory")
    assert feature_guard.effective_plan(db, admin["user"]) == "PRO"
    # An admin who is only a member doesn't lift the team's plan; the owner's role does.
    trial = make_user(plan="TRIAL")
    member = make_user(team=trial["team"])
    member["user"].role = "ADMIN"
    db.commit()
    assert not feature_guard.team_has_feature(db, trial["team"].id, "templates")
    assert feature_guard.effective_plan(db, trial["user"]) == "TRIAL"


def test_lookup_failure_denies_but_keeps_the_session(db, make_user, monkeypatch):
    pro = make_user(plan="PRO")

    def broken(db, team_id):
        from sqlalchemy import text

        db.execute(text("SELECT no_such_column FROM teams"))

    monkeypatch.setattr(feature_guard, "team_plan", broken)
    assert feature_guard.team_has_feature(db, pro["team"].id, "templates") is False
    assert db.query(CreditWallet).count() == 1


def test_project_plan_is_resolved_once(db, gated_project, monkeypatch):
    _, project = gated_project("PRO")
    calls = []
    real = feature_guard.team_plan
    monkeypatch.setattr(feature_guard, "team_plan", lambda db, team_id: calls.append(team_id) or real(db, team_id))
    for f in ("templates", "glossaries", "terminology_memory", "templates"):
        assert feature_guard.project_has_feature(db, project, f)
    assert len(calls) == 1


# Routes

LEARNING_ROUTES = [
    ("get", "/templates"),
    ("delete", "/templates/{tid}"),
    ("post", "/projects/{pid}/template"),
    ("get", "/projects/{pid}/learning"),
    ("get", "/learning/summary"),
    ("post", "/learning/terms/{term}/reject"),
]


@pytest.mark.parametrize("plan,expired", [("TRIAL", False), ("TRIAL", True)])
def test_learning_routes_refuse_trial_and_expired(client, db, gated_project, plan, expired):
    owner, project = gated_project(plan, expires_in_days=-1 if expired else 30)
    template, _ = learning.store_template(db, owner["team"].id, KEY, "English", PROFILE, _docx("t"), "src")
    term = Glossary(team_id=owner["team"].id, source_language="Italian", target_language="English",
                    source_term="Prefettura", target_term="Prefecture", origin="learned")
    db.add(term)
    db.commit()
    for method, path in LEARNING_ROUTES:
        url = path.format(pid=project.id, tid=template.id, term=term.id)
        assert getattr(client, method)(url, headers=owner["headers"]).status_code == 403, url
    db.expire_all()
    assert db.query(DocumentTemplate).count() == 1 and db.query(Glossary).one().origin == "learned"


def test_basic_has_templates_but_no_learned_terms(client, db, gated_project):
    owner, project = gated_project("BASIC")
    _add_glossary(db, owner["team"].id)
    db.add(Glossary(team_id=owner["team"].id, source_language="Italian", target_language="English",
                    source_term="Prefettura", target_term="Prefecture", origin="learned", learned_from_project_id=project.id))
    db.commit()
    h = owner["headers"]

    assert client.post(f"/projects/{project.id}/template", headers=h).status_code == 200
    assert len(client.get("/templates", headers=h).json()) == 1
    body = client.get(f"/projects/{project.id}/learning", headers=h).json()
    assert body["saved_as_template"] and body["terms_applied"] == [] and body["terms_learned_here"] == []
    assert client.get("/learning/summary", headers=h).json() == {"templates": 1, "learned_terms": 0, "recent_terms": []}
    learned = db.query(Glossary).filter(Glossary.origin == "learned").one()
    assert client.post(f"/learning/terms/{learned.id}/reject", headers=h).status_code == 403
    template = db.query(DocumentTemplate).one()
    assert client.delete(f"/templates/{template.id}", headers=h).status_code == 200


def test_trial_upload_drops_the_certification_request(client, db, make_user, monkeypatch, tmp_path):
    from tests.conftest import make_pdf
    from app.models.project import TranslationProject

    trial = make_user(plan="TRIAL", credits=5)
    pdf = make_pdf(tmp_path / "doc.pdf")
    with open(pdf, "rb") as f:
        r = client.post("/projects/upload", headers=trial["headers"], files={"file": ("doc.pdf", f, "application/pdf")},
                        data={"source_language": "Italian", "target_language": "English", "request_certification": "true"})
    assert r.status_code in (200, 201), r.text
    assert db.query(TranslationProject).one().add_certification is False


# Background writes

@pytest.mark.parametrize("plan,template,memory", [("TRIAL", False, False), ("BASIC", True, False), ("PRO", True, True)])
def test_certified_status_stores_what_the_plan_allows(client, db, gated_project, plan, template, memory):
    owner, project = gated_project(plan)
    r = client.patch(f"/projects/{project.id}/review-status", headers=owner["headers"], json={"status": "CERTIFIED"})
    assert r.status_code == 200
    db.expire_all()
    assert (db.query(DocumentTemplate).count() == 1) is template
    assert (db.query(TranslationMemory).count() > 0) is memory


def test_trial_delivery_capture_stores_nothing(client, db, gated_project):
    owner, project = gated_project("TRIAL")
    learning.capture_template_in_background(project.id, owner["user"].id)
    assert client.get(f"/projects/{project.id}/export", headers=owner["headers"]).status_code == 403
    db.expire_all()
    assert db.query(DocumentTemplate).count() == 0 and db.query(TranslationMemory).count() == 0


@pytest.mark.parametrize("plan,queued,memory", [("TRIAL", 0, 0), ("BASIC", 0, 0), ("PRO", 1, 1)])
def test_editor_edits_follow_the_plan(client, db, gated_project, plan, queued, memory):
    owner, project = gated_project(plan)
    data, v = _open(client, owner, project)
    ids = docx_blocks.block_ids(data)
    r = client.post(f"/projects/{project.id}/document/edits", headers=owner["headers"],
                    json={"version": v, "edits": [{"block_id": ids[0], "text": "THE REGISTRAR, having examined the records,"}]})
    assert r.status_code == 200, r.text
    assert db.query(PendingLearning).count() == queued
    assert db.query(TranslationMemory).count() == memory


def test_queued_edits_of_a_trial_team_are_dropped_without_a_model_call(db, gated_project):
    _, project = gated_project("TRIAL")
    db.add(PendingLearning(project_id=project.id, block_id="b1", before_text="THE REGISTRY OFFICER",
                           after_text="THE REGISTRAR", origin="typed", created_at=datetime.utcnow() - timedelta(minutes=5)))
    db.commit()
    assert learning.process_pending(now=datetime.utcnow()) == 1
    db.expire_all()
    assert db.query(PendingLearning).count() == 0 and db.query(Glossary).count() == 0


def test_trial_chat_edit_gets_no_team_terminology(client, db, gated_project, monkeypatch):
    owner, project = gated_project("TRIAL")
    _add_glossary(db, owner["team"].id)
    data, v = _open(client, owner, project)
    ids = docx_blocks.block_ids(data)
    seen = []

    def fake(client_, **kw):
        import json

        seen.append(kw)
        body = {"reply": "Done.", "operations": [{"op": "set_text", "target": ids[0], "content": "THE REGISTRAR, having examined the records,"}]}
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(body))], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0),
                               model=kw["model"])

    monkeypatch.setattr(claude_params, "create_message", fake)
    monkeypatch.setattr(claude_params, "api_key", lambda: "test-key")
    r = client.post(f"/projects/{project.id}/document/chat", headers=owner["headers"], json={"version": v, "message": "use Registrar"})
    assert r.status_code == 200, r.text
    joined = "\n".join(b.get("text", "") for b in seen[0]["messages"][0]["content"] if isinstance(b, dict))
    assert "TEAM TERMINOLOGY" not in joined
    assert db.query(PendingLearning).count() == 0


# Translation pipeline

def _run_pipeline(db, project, monkeypatch, source_language="Italian"):
    from app.services import claude_authored_rebuild as car
    from app.services import translation_processor as tp

    seen = {"fill": None, "author": None, "prompts": [], "classify": 0}
    monkeypatch.setattr(tp, "download_file_from_s3", lambda key, dest: Path(dest).write_bytes(b"%PDF"))
    monkeypatch.setattr(tp, "extract_segments", lambda path: ("PDF", [SimpleNamespace(text=s, layout={}) for s in SOURCE]))

    def classify(data, name, hint=""):
        seen["classify"] += 1
        return dict(PROFILE)

    monkeypatch.setattr(learning, "classify_document", classify)

    def call_model(**kw):
        seen["prompts"].append(kw["cache_prefix"] + kw["user"])
        n = len(kw["user"].split("INPUT:\n", 1)[1].split("\n<<<SEG>>>\n"))
        return "<<<SEG>>>".join(f"EN {i}" for i in range(n))

    monkeypatch.setattr(ats, "_call_model", call_model)

    def rebuild(**kw):
        Path(kw["output_path"]).write_bytes(b"docx")
        return kw["output_path"]

    monkeypatch.setattr(tp, "rebuild_output", rebuild)
    monkeypatch.setattr(tp, "upload_file_to_s3", lambda path: "uploads/out.docx")
    monkeypatch.setattr(car, "author_rebuild_docx", lambda **kw: seen.update(author=kw) or b"docx")

    def fill(**kw):
        seen["fill"] = kw
        return docx_blocks.tag_blocks(_docx("filled")), {"seconds": 1}

    monkeypatch.setattr(template_fill, "fill_from_template", fill)
    project.status = ProjectStatus.PENDING
    project.model = "claude-authored"
    project.source_language = source_language
    project.doc_key, project.doc_profile = None, None
    db.commit()
    tp.process_translation_job(str(project.id))
    return seen


def _seed_team(db, owner):
    team_id = owner["team"].id
    _add_glossary(db, team_id)
    _add_memory(db, team_id)
    learning.store_template(db, team_id, KEY, "English", PROFILE, _docx("TEMPLATE"), "src")


def test_pipeline_pro_uses_memory_glossary_and_template(db, gated_project, monkeypatch):
    owner, project = gated_project("PRO")
    _seed_team(db, owner)
    calls = []
    real = feature_guard.team_plan
    monkeypatch.setattr(feature_guard, "team_plan", lambda db, team_id: calls.append(team_id) or real(db, team_id))
    seen = _run_pipeline(db, project, monkeypatch)

    assert len(calls) == 1
    assert seen["classify"] == 1 and seen["author"] is None
    assert "Civil Registry" in seen["fill"]["terminology"] and tm.PROMPT_HEADING in seen["fill"]["terminology"]
    assert all("Civil Registry" in p for p in seen["prompts"])
    db.expire_all()
    seg = db.query(TranslationSegment).filter(TranslationSegment.project_id == project.id, TranslationSegment.segment_index == 0).one()
    assert seg.translated_text == MEMORY and seg.tm_pct == 100


def test_pipeline_basic_uses_the_template_only(db, gated_project, monkeypatch):
    owner, project = gated_project("BASIC")
    _seed_team(db, owner)
    seen = _run_pipeline(db, project, monkeypatch)

    assert seen["classify"] == 1 and seen["fill"] is not None
    assert seen["fill"]["terminology"] == ""
    assert seen["prompts"] and not any("Civil Registry" in p or "REFERENCE TRANSLATIONS" in p for p in seen["prompts"])
    db.expire_all()
    assert db.query(TranslationSegment).filter(TranslationSegment.tm_pct == 100).count() == 0


def test_pipeline_trial_gets_no_memory_glossary_or_template(db, gated_project, monkeypatch):
    owner, project = gated_project("TRIAL")
    _seed_team(db, owner)
    seen = _run_pipeline(db, project, monkeypatch)

    assert seen["classify"] == 0 and seen["fill"] is None
    assert seen["author"] is not None and seen["author"]["terminology"] == ""
    assert len(seen["prompts"]) == 1
    assert "Civil Registry" not in seen["prompts"][0] and "REFERENCE TRANSLATIONS" not in seen["prompts"][0]
    db.expire_all()
    assert db.query(TranslationSegment).filter(TranslationSegment.tm_pct == 100).count() == 0
    template = db.query(DocumentTemplate).one()
    assert (template.use_count or 0) == 0


def test_pipeline_trial_auto_source_still_detects_the_language(db, gated_project, monkeypatch):
    owner, project = gated_project("TRIAL")
    _seed_team(db, owner)
    seen = _run_pipeline(db, project, monkeypatch, source_language="auto")

    assert seen["classify"] == 1 and seen["fill"] is None
    assert seen["author"]["terminology"] == ""
    db.expire_all()
    assert project.doc_profile["source_language"] == "Italian"


def test_pipeline_survives_a_failed_plan_lookup(db, gated_project, monkeypatch):
    owner, project = gated_project("PRO")
    _seed_team(db, owner)

    def broken(db, team_id):
        raise RuntimeError("wallet table unavailable")

    monkeypatch.setattr(feature_guard, "team_plan", broken)
    seen = _run_pipeline(db, project, monkeypatch)
    assert seen["fill"] is None and seen["author"]["terminology"] == ""
    db.expire_all()
    assert project.status == ProjectStatus.COMPLETED
