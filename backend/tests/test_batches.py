import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.models.batch import Batch, BatchTerm
from app.models.project import ProjectStatus, TranslationProject
from app.services import batch_terms, learning
from tests.conftest import make_pdf
from tests.test_learning import doc_project, fake_claude  # noqa: F401

PAIRS = [
    ("DIPLOMA DI LAUREA", "DEGREE CERTIFICATE"),
    ("Università di Bologna", "University of Bologna"),
    ("si certifica che ROSSI Mario, nato a Bologna,", "this is to certify that ROSSI Mario, born in Bologna,"),
    ("ha conseguito la Laurea Magistrale in Ingegneria", "has been awarded the Master's Degree in Engineering"),
]
TERMS = {
    "terms": [
        {"source_term": "Università di Bologna", "target_term": "University of Bologna", "kind": "institution"},
        {"source_term": "ROSSI Mario", "target_term": "ROSSI Mario", "kind": "person"},
        {"source_term": "Laurea Magistrale in Ingegneria", "target_term": "Master's Degree in Engineering", "kind": "degree"},
        {"source_term": "Politecnico di Milano", "target_term": "Polytechnic of Milan", "kind": "institution"},
        {"source_term": "Bologna", "target_term": "Bologne", "kind": "place"},
    ]
}


def _batch(client, owner, name="Rossi family"):
    r = client.post("/batches", headers=owner["headers"], json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _upload(client, owner, tmp_path, batch_id=None, pages=1, name="doc.pdf"):
    pdf = make_pdf(tmp_path / name, pages=pages)
    data = {"source_language": "Italian", "target_language": "English"}
    if batch_id:
        data["batch_id"] = batch_id
    with open(pdf, "rb") as f:
        return client.post("/projects/upload", headers=owner["headers"], files={"file": (name, f, "application/pdf")}, data=data)


def test_batches_are_team_scoped(client, db, make_user, make_project):
    owner, other = make_user(), make_user()
    teammate = make_user(team=owner["team"])
    bid = _batch(client, owner, "  Rossi   family ")
    p = make_project(owner, pages=3)
    p.batch_id = bid
    make_project(owner, status=ProjectStatus.FAILED, pages=1).batch_id = bid
    db.commit()

    listed = client.get("/batches", headers=teammate["headers"]).json()
    assert [(b["name"], b["documents"], b["pages"], b["completed"], b["failed"]) for b in listed] == [("Rossi family", 2, 4, 1, 1)]
    body = client.get(f"/batches/{bid}", headers=owner["headers"]).json()
    assert len(body["projects"]) == 2 and body["projects"][0]["review_status"] == "DRAFT"

    assert client.get("/batches", headers=other["headers"]).json() == []
    assert client.get(f"/batches/{bid}", headers=other["headers"]).status_code == 404
    assert client.post(f"/batches/{bid}/review-status", headers=other["headers"], json={"status": "CERTIFIED"}).status_code == 404
    assert client.get(f"/batches/{bid}/export.zip", headers=other["headers"]).status_code == 404


def test_upload_into_batch_and_foreign_batch_rejected(client, db, make_user, tmp_path):
    owner, other = make_user(credits=10), make_user(credits=10)
    bid = _batch(client, owner)
    r = _upload(client, owner, tmp_path, batch_id=bid, pages=2)
    assert r.status_code == 200, r.text
    assert r.json()["batch_id"] == bid
    listed = client.get("/projects/", headers=owner["headers"]).json()
    assert listed[0]["batch"] == {"id": bid, "name": "Rossi family"}

    foreign = _upload(client, other, tmp_path, batch_id=bid, pages=2)
    assert foreign.status_code == 404
    db.expire_all()
    assert db.query(TranslationProject).filter(TranslationProject.team_id == other["team"].id).count() == 0
    assert db.execute(text("SELECT count(*) FROM translation_jobs")).scalar() == 1


def test_batch_jobs_wait_for_the_first_document_then_run_in_parallel(client, db, make_user, tmp_path):
    from app.workers import sqs_worker

    owner = make_user(credits=20)
    bid = _batch(client, owner)
    first = _upload(client, owner, tmp_path, batch_id=bid).json()["project_id"]
    second = _upload(client, owner, tmp_path, batch_id=bid).json()["project_id"]
    third = _upload(client, owner, tmp_path, batch_id=bid).json()["project_id"]
    loose = _upload(client, owner, tmp_path).json()["project_id"]

    assert sqs_worker._claim_next_job()["project_id"] == first
    # The other batch documents wait; unrelated work is not blocked behind them.
    assert sqs_worker._claim_next_job()["project_id"] == loose
    assert sqs_worker._claim_next_job() is None

    db.query(Batch).filter(Batch.id == bid).update({Batch.terms_ready_at: text("now()")}, synchronize_session=False)
    db.commit()
    assert sqs_worker._claim_next_job()["project_id"] == second
    assert sqs_worker._claim_next_job()["project_id"] == third


def test_concurrent_claims_never_start_two_documents_of_a_new_batch(client, db, make_user, tmp_path):
    import threading
    import time

    from app.database import SessionLocal
    from app.workers import sqs_worker

    owner = make_user(credits=20)
    bid = _batch(client, owner)
    for _ in range(3):
        _upload(client, owner, tmp_path, batch_id=bid)

    first = SessionLocal()
    cand = sqs_worker._pick_job(first, [])
    first.execute(text("UPDATE translation_jobs SET status = 'processing' WHERE id = :id"), {"id": cand.id})
    result = {}
    t = threading.Thread(target=lambda: result.update(job=sqs_worker._claim_next_job()))
    t.start()
    time.sleep(0.5)
    # The rival saw no processing job in its snapshot and is now waiting on the batch lock.
    assert t.is_alive()
    first.commit()
    first.close()
    t.join(timeout=10)
    assert result == {"job": None}


def test_next_batch_job_runs_when_first_finishes_without_terms(client, db, make_user, tmp_path):
    from app.workers import sqs_worker

    owner = make_user(credits=20)
    bid = _batch(client, owner)
    _upload(client, owner, tmp_path, batch_id=bid)
    second = _upload(client, owner, tmp_path, batch_id=bid).json()["project_id"]
    job = sqs_worker._claim_next_job()
    assert sqs_worker._claim_next_job() is None
    sqs_worker._mark_job(job["id"], "completed")
    assert sqs_worker._claim_next_job()["project_id"] == second


def _batch_projects(db, make_project, owner, bid, n=2):
    projects = []
    for i in range(n):
        p = make_project(owner, segments=[s for s, _ in PAIRS] if i == 0 else ["Università di Bologna — MARIO ROSSI", "Certificato degli esami"])
        p.batch_id = bid
        projects.append(p)
    db.commit()
    return projects


def test_terms_extracted_once_and_injected_into_later_documents(client, db, make_user, make_project, fake_claude, monkeypatch):  # noqa: F811
    from app.services import ai_translation_service as ats

    owner = make_user()
    bid = _batch(client, owner)
    first, second = _batch_projects(db, make_project, owner, bid)
    fake = fake_claude(TERMS)

    assert batch_terms.record_from_segments(db, first, PAIRS) == 3
    prompt = fake.requests[0]["messages"][0]["content"]
    assert fake.requests[0]["model"] == "claude-haiku-4-5-20251001"
    assert "SOURCE: Università di Bologna\nTRANSLATION: University of Bologna" in prompt
    assert fake.requests[0]["output_config"]["format"]["type"] == "json_schema"
    rows = {t.source_term: (t.target_term, t.kind) for t in db.query(BatchTerm).all()}
    # Invented source terms and target renderings not in the translation are dropped.
    assert rows == {
        "Università di Bologna": ("University of Bologna", "institution"),
        "ROSSI Mario": ("ROSSI Mario", "person"),
        "Laurea Magistrale in Ingegneria": ("Master's Degree in Engineering", "degree"),
    }
    db.refresh(db.query(Batch).one())
    assert db.query(Batch).one().terms_ready_at is not None

    seen = {}
    monkeypatch.setattr(ats, "_call_model", lambda **kw: seen.update(kw) or "x<<<SEG>>>y")
    ats.translate_batch(["Università di Bologna — MARIO ROSSI", "Certificato degli esami"], "Italian", "English", db=db, project=second)
    assert batch_terms.HEADING in seen["cache_prefix"]
    assert "Università di Bologna → University of Bologna" in seen["cache_prefix"]
    assert "ROSSI Mario → ROSSI Mario" in seen["cache_prefix"]
    assert "Laurea Magistrale" not in seen["cache_prefix"]

    block = learning.team_terminology(db, second)
    assert block.startswith(batch_terms.HEADING) and "University of Bologna" in block
    # A document never sees its own terms as coming from "other documents".
    assert batch_terms.HEADING not in learning.team_terminology(db, first)

    fake_claude({"terms": [{"source_term": "Università di Bologna", "target_term": "Bologna University", "kind": "institution"}]})
    batch_terms.record_from_segments(db, second, [("Università di Bologna", "Bologna University")])
    assert db.query(BatchTerm).filter(BatchTerm.source_term == "Università di Bologna").one().target_term == "University of Bologna"


def test_extraction_failure_still_opens_the_batch(client, db, make_user, make_project, fake_claude):  # noqa: F811
    owner = make_user()
    bid = _batch(client, owner)
    first, _ = _batch_projects(db, make_project, owner, bid)
    fake_claude(RuntimeError("overloaded"))
    assert batch_terms.record_from_segments(db, first, PAIRS) == 0
    assert db.query(Batch).one().terms_ready_at is not None


def test_chat_edit_prompt_includes_batch_terms(client, db, make_user, doc_project, fake_claude):  # noqa: F811
    owner, project = doc_project()
    bid = _batch(client, owner)
    project.batch_id = bid
    db.add(BatchTerm(batch_id=bid, target_language="en", source_term="BIANCHI LUCA", source_key="bianchi luca",
                     target_term="BIANCHI Luca", kind="person"))
    db.commit()
    v = int(client.get(f"/projects/{project.id}/document", headers=owner["headers"]).headers["X-Document-Version"])
    fake = fake_claude({"reply": "No change.", "operations": []})
    client.post(f"/projects/{project.id}/document/chat", headers=owner["headers"], json={"version": v, "message": "check"})
    joined = "\n".join(b.get("text", "") for b in fake.requests[0]["messages"][0]["content"])
    assert batch_terms.HEADING in joined and "BIANCHI LUCA → BIANCHI Luca" in joined


def test_worker_records_terms_after_segment_translation(client, db, storage, make_user, make_project, fake_claude, monkeypatch, tmp_path):  # noqa: F811
    from app.services import translation_processor as tp

    owner = make_user()
    bid = _batch(client, owner)
    first, _ = _batch_projects(db, make_project, owner, bid)
    first.status = ProjectStatus.PENDING
    db.commit()
    order = []
    monkeypatch.setattr(tp, "download_file_from_s3", lambda key, dest: Path(dest).write_bytes(b"x"))
    monkeypatch.setattr(tp, "extract_segments", lambda path: ("DOCX", [SimpleNamespace(text=s, layout={}) for s, _ in PAIRS]))
    monkeypatch.setattr(tp.learning, "profile_project", lambda *a, **kw: None)
    monkeypatch.setattr(tp, "translate_batch", lambda texts, *a, **kw: order.append("translate") or [dict(PAIRS)[t] for t in texts])
    monkeypatch.setattr(tp, "store_tm_entry", lambda **kw: None)

    def rebuild(**kw):
        order.append("rebuild")
        Path(kw["output_path"]).write_bytes(b"docx")
        return kw["output_path"]

    monkeypatch.setattr(tp, "rebuild_output", rebuild)
    monkeypatch.setattr(tp, "upload_file_to_s3", lambda path: "uploads/out.docx")
    real = batch_terms.record_from_segments
    monkeypatch.setattr(batch_terms, "record_from_segments", lambda *a: order.append("terms") or real(*a))
    fake_claude(TERMS)

    tp.process_translation_job(str(first.id))
    assert order == ["translate", "terms", "rebuild"]
    assert db.query(BatchTerm).count() == 3


def test_zip_export_has_one_file_per_finished_document(client, db, make_user, make_project, monkeypatch):
    import app.routers.export as export_router

    monkeypatch.setattr(export_router, "generate_docx", lambda segs, email, project=None, user=None: io.BytesIO(f"docx:{project.id}".encode()))
    monkeypatch.setattr(export_router, "generate_pdf", lambda segs, email, project=None, user=None: io.BytesIO(b"%PDF"))
    owner = make_user()
    bid = _batch(client, owner)
    done = [make_project(owner), make_project(owner)]
    pending = make_project(owner, status=ProjectStatus.PROCESSING)
    for p in done + [pending]:
        p.batch_id = bid
    done[1].file_name = "diploma.pdf"
    db.commit()

    r = client.get(f"/batches/{bid}/export.zip?format=docx", headers=owner["headers"])
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(zf.namelist()) == ["diploma.docx", "source.docx"]
    assert zf.read("diploma.docx") == f"docx:{done[1].id}".encode()

    pdf = zipfile.ZipFile(io.BytesIO(client.get(f"/batches/{bid}/export.zip?format=pdf", headers=owner["headers"]).content))
    assert sorted(pdf.namelist()) == ["diploma.pdf", "source.pdf"]
    assert client.get(f"/batches/{bid}/export.zip?format=txt", headers=owner["headers"]).status_code == 422


def test_zip_export_respects_download_plan(client, db, make_user, make_project):
    trial = make_user(plan="TRIAL")
    bid = _batch(client, trial)
    make_project(trial).batch_id = bid
    db.commit()
    assert client.get(f"/batches/{bid}/export.zip", headers=trial["headers"]).status_code == 403


def test_bulk_review_status_updates_finished_documents(client, db, make_user, make_project, monkeypatch):
    import app.routers.batches as batches_router

    captured = []
    monkeypatch.setattr(batches_router, "capture_template_in_background", lambda pid, uid: captured.append(pid))
    owner = make_user()
    bid = _batch(client, owner)
    done = [make_project(owner), make_project(owner)]
    running = make_project(owner, status=ProjectStatus.PROCESSING)
    for p in done + [running]:
        p.batch_id = bid
    db.commit()

    assert client.post(f"/batches/{bid}/review-status", headers=owner["headers"], json={"status": "SHIPPED"}).status_code == 400
    r = client.post(f"/batches/{bid}/review-status", headers=owner["headers"], json={"status": "certified"})
    assert r.status_code == 200 and r.json() == {"updated": 2, "skipped": 1, "review_status": "CERTIFIED"}
    db.expire_all()
    assert [p.review_status for p in db.query(TranslationProject).order_by(TranslationProject.created_at)] == ["CERTIFIED", "CERTIFIED", "DRAFT"]
    assert sorted(captured) == sorted(p.id for p in done)
