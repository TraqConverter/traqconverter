"""Editable copy (DTP mode): a same-language editable Word file of the original, never translated or certified."""
import io

import pytest
from docx import Document

from app.models.credit import CreditWallet
from app.models.learning import DocumentTemplate, PendingLearning
from app.models.project import TranslationProject
from app.models.translation_memory import TranslationMemory
from app.models.translation_segment import TranslationSegment
from app.services import claude_params, docx_blocks, learning
from tests.conftest import make_pdf
from tests.test_learning import _FakeClaude
from tests.test_pipeline_multiturn import GOOD_DOCX, _response, _run, _tool, loop_env  # noqa: F401
from tests.test_plan_gating import SOURCE, _open, _run_pipeline, _seed_team, gated_project  # noqa: F401

REPRODUCE = "EDITABLE COPY: DO NOT TRANSLATE"


@pytest.fixture()
def no_model(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("no model call expected")

    monkeypatch.setattr(claude_params, "create_message", boom)


def _upload(client, owner, tmp_path, pages=2, **extra):
    pdf = make_pdf(tmp_path / "doc.pdf", pages=pages)
    data = {"source_language": "Italian", "target_language": "English", **extra}
    with open(pdf, "rb") as f:
        return client.post("/projects/upload", headers=owner["headers"], files={"file": ("doc.pdf", f, "application/pdf")}, data=data)


def _dtp(db, project):
    project.mode = "dtp"
    project.target_language = project.source_language
    project.use_tm = project.apply_glossary = False
    db.commit()
    return project


# Upload

def test_upload_stores_the_mode_and_charges_per_page(client, db, make_user, tmp_path, no_model):
    owner = make_user(credits=10)
    r = _upload(client, owner, tmp_path, pages=3, mode="dtp", ai_instructions="Use British spelling",
                request_certification="true", apply_glossary="true", use_tm="true")
    assert r.status_code == 200, r.text
    assert r.json()["credits_used"] == 3
    project = db.get(TranslationProject, r.json()["project_id"])
    assert project.mode == "dtp"
    assert project.source_language == project.target_language == "Italian"
    assert project.ai_instructions is None and project.model == "claude-authored"
    assert not (project.use_tm or project.apply_glossary or project.add_certification)
    assert db.query(CreditWallet).one().subscription_credits == 7

    body = client.get(f"/projects/{project.id}", headers=owner["headers"]).json()
    assert body["mode"] == "dtp"
    listed = client.get("/projects/", headers=owner["headers"]).json()
    assert listed[0]["mode"] == "dtp"


def test_upload_defaults_to_translate_and_rejects_unknown_modes(client, db, make_user, tmp_path, no_model):
    owner = make_user(credits=10)
    r = _upload(client, owner, tmp_path)
    assert db.get(TranslationProject, r.json()["project_id"]).mode == "translate"
    assert _upload(client, owner, tmp_path, mode="ocr").status_code == 400
    assert db.query(TranslationProject).count() == 1
    assert db.query(CreditWallet).one().subscription_credits == 8


# Pipeline

def test_pipeline_rebuilds_verbatim_without_memory_glossary_or_template(db, gated_project, monkeypatch, no_model):
    owner, project = gated_project("PRO")
    _seed_team(db, owner)
    project.ai_instructions = "Use British spelling"
    _dtp(db, project)
    seen = _run_pipeline(db, project, monkeypatch)

    assert seen["fill"] is None and seen["prompts"] == [] and seen["classify"] == 0
    author = seen["author"]
    assert author["reproduce"] is True
    assert author["source_lang"] == author["target_lang"] == "Italian"
    assert author["terminology"] == "" and author["instructions"] == ""
    db.expire_all()
    segs = db.query(TranslationSegment).filter(TranslationSegment.project_id == project.id).order_by(TranslationSegment.segment_index).all()
    assert [s.translated_text for s in segs] == SOURCE
    assert all(s.tm_pct is None for s in segs)
    assert project.status.value == "COMPLETED" and project.template_id is None
    assert db.query(DocumentTemplate).one().use_count == 0


def test_pipeline_auto_source_copies_into_the_detected_language(db, gated_project, monkeypatch, no_model):
    _, project = gated_project("PRO")
    _dtp(db, project)
    seen = _run_pipeline(db, project, monkeypatch, source_language="auto")
    assert seen["classify"] == 1 and seen["fill"] is None
    db.expire_all()
    assert project.target_language == "Italian"
    assert seen["author"]["source_lang"] == seen["author"]["target_lang"] == "Italian"


def test_scanned_images_are_rebuilt_from_a_pdf():
    from PIL import Image

    from app.services import translation_processor as tp

    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, format="PNG")
    assert tp._image_to_pdf(buf.getvalue(), "scan.png").startswith(b"%PDF")


def test_reproduce_block_leads_the_single_shot_prompt(monkeypatch):
    from app.services import claude_authored_rebuild as car

    monkeypatch.setattr(claude_params, "api_key", lambda: "k")
    for reproduce in (True, False):
        fake = _FakeClaude([{"x": 1}])
        monkeypatch.setattr(claude_params, "create_message", fake)
        car._call_claude_to_author(b"%PDF", "Italian", "Italian", "/tmp/out.docx", [], [], model="claude-opus-4-8",
                                   reproduce=reproduce)
        prompt = fake.requests[0]["messages"][0]["content"][1]["text"]
        assert prompt.startswith(REPRODUCE) is reproduce
        # The notation rules stay in force.
        assert "[Signature]" in prompt and "[illegible]" in prompt
    assert "copy verbatim in Italian" in car.reproduce_block("Italian")

    seen = {}
    from app.services import claude_multiturn_rebuild as mt

    monkeypatch.setattr(mt, "author_rebuild_docx_multiturn", lambda *a, **kw: seen.update(kw) or b"docx")
    car.author_rebuild_docx(b"pdf", "Italian", "Italian", reproduce=True)
    assert seen["reproduce"] is True


def test_reproduce_block_leads_the_multiturn_prompt(loop_env, monkeypatch):  # noqa: F811
    from app.services import claude_multiturn_rebuild as mt

    monkeypatch.setattr(mt, "_run_in_sandbox", lambda *a, **k: (True, "", GOOD_DOCX))
    requests = loop_env([_response([_tool("a", "t1")])])
    _run(reproduce=True)
    prompt = requests[0][1]["messages"][0]["content"][1]["text"]
    assert prompt.startswith(REPRODUCE) and "[Signature]" in prompt


def test_form_pages_are_copied_not_translated(monkeypatch):
    from app.services import claude_multiturn_rebuild as mt

    monkeypatch.setattr(mt, "_split_pdf_per_page", lambda pdf: [b"p1", b"p2"])
    monkeypatch.setattr(mt, "_pdf_page_count", lambda pdf: 2)
    monkeypatch.setattr(mt, "_merge_authored_docx_fragments", lambda frags: b"merged")
    seen = []
    monkeypatch.setattr(mt, "_author_rebuild_docx_multiturn_core", lambda *a, **kw: seen.append(kw) or b"page")
    mt._author_rebuild_form_page_by_page(b"pdf", "it", "it", reproduce=True)
    assert all(kw["reproduce"] and "Copy this page only" in kw["extra_instructions"] for kw in seen)


def test_regenerate_reproduces_without_memory_or_instructions(db, gated_project, monkeypatch, no_model):
    from app.services import ai_actions
    from app.services import claude_authored_rebuild as car
    from app.services import claude_multiturn_rebuild as mt

    owner, project = gated_project("PRO")
    _seed_team(db, owner)
    project.ai_instructions = "Use British spelling"
    _dtp(db, project)
    calls = []
    monkeypatch.setattr(mt, "author_rebuild_docx_multiturn", lambda *a, **kw: calls.append((a, kw)) or GOOD_DOCX)
    monkeypatch.setattr(car, "author_rebuild_docx", lambda **kw: calls.append(((), kw)) or GOOD_DOCX)
    ai_actions.run_rebuild(str(project.id), "Keep the table borders")
    ai_actions.run_rebuild(str(project.id), None)
    (margs, multi), (_, single) = calls
    assert margs[1:] == ("Italian", "Italian")
    assert single["source_lang"] == single["target_lang"] == "Italian"
    for kw in (multi, single):
        assert kw["reproduce"] is True and kw["terminology"] == "" and kw["instructions"] == ""


# Learning and certification

def test_delivery_learns_nothing(client, db, gated_project, no_model):
    owner, project = gated_project("PRO")
    _dtp(db, project)
    learning.capture_template_in_background(project.id, owner["user"].id)
    data, v = _open(client, owner, project)
    ids = docx_blocks.block_ids(data)
    r = client.post(f"/projects/{project.id}/document/edits", headers=owner["headers"],
                    json={"version": v, "edits": [{"block_id": ids[0], "text": "L'UFFICIALE D'ANAGRAFE, visti gli atti,"}]})
    assert r.status_code == 200, r.text
    assert client.post(f"/projects/{project.id}/template", headers=owner["headers"]).status_code == 409
    db.expire_all()
    assert db.query(DocumentTemplate).count() == 0
    assert db.query(TranslationMemory).count() == 0
    assert db.query(PendingLearning).count() == 0


def test_certify_endpoints_refuse(client, db, gated_project, no_model):
    owner, project = gated_project("PRO")
    _dtp(db, project)
    h, base = owner["headers"], f"/projects/{project.id}"
    _, v = _open(client, owner, project)
    assert client.post(f"{base}/certify", headers=h).status_code == 409
    assert client.patch(f"{base}/review-status", headers=h, json={"status": "CERTIFIED"}).status_code == 409
    assert client.patch(base, headers=h, json={"certification_template_id": "standard"}).status_code == 409
    assert client.post(f"{base}/document/certification", headers=h, json={"version": v}).status_code == 409
    assert client.put(f"{base}/document/certification", headers=h, json={"version": v, "fields": {}}).status_code == 409
    assert client.patch(f"{base}/review-status", headers=h, json={"status": "IN_REVIEW"}).status_code == 200
    db.expire_all()
    assert project.review_status == "IN_REVIEW"
    assert db.query(DocumentTemplate).count() == 0


def test_export_is_the_edited_copy_alone(client, db, gated_project, no_model):
    owner, project = gated_project("PRO")
    _dtp(db, project)
    r = client.get(f"/projects/{project.id}/export", headers=owner["headers"])
    assert r.status_code == 200, r.text
    text = "\n".join(p.text for p in Document(io.BytesIO(r.content)).paragraphs)
    assert "THE REGISTRY OFFICER" in text
    assert "certify" not in text.lower()


@pytest.mark.parametrize("status", ["CERTIFIED", "IN_REVIEW"])
def test_batch_status_never_certifies_a_copy(client, db, gated_project, status, no_model):
    from app.models.batch import Batch

    owner, project = gated_project("PRO")
    batch = Batch(team_id=owner["team"].id, name="Rossi", created_by=owner["user"].id)
    db.add(batch)
    db.flush()
    project.batch_id = batch.id
    _dtp(db, project)
    r = client.post(f"/batches/{batch.id}/review-status", headers=owner["headers"], json={"status": status})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == (0 if status == "CERTIFIED" else 1)
