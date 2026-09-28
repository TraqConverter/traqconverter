from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.models.credit import CreditTransaction, CreditWallet
from app.models.project import ProjectStatus, TranslationProject
from tests.conftest import make_pdf


def _wallet(db, owner):
    db.expire_all()
    return db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).one()


def _jobs(db, project_id=None):
    sql = "SELECT id, status, attempts FROM translation_jobs"
    params = {}
    if project_id:
        sql += " WHERE project_id = :pid"
        params["pid"] = str(project_id)
    return db.execute(text(sql), params).fetchall()


def _upload(client, owner, tmp_path, pages=3, **form):
    pdf = make_pdf(tmp_path / "doc.pdf", pages=pages)
    with open(pdf, "rb") as f:
        return client.post(
            "/projects/upload",
            headers=owner["headers"],
            files={"file": ("doc.pdf", f, "application/pdf")},
            data={"source_language": "Italian", "target_language": "English", **form},
        )


def test_upload_charges_pages_and_enqueues_atomically(client, db, make_user, tmp_path):
    owner = make_user(credits=10)
    r = _upload(client, owner, tmp_path, pages=3)
    assert r.status_code == 200, r.text
    assert r.json()["credits_used"] == 3
    assert _wallet(db, owner).subscription_credits == 7
    assert len(_jobs(db, r.json()["project_id"])) == 1


def test_upload_without_credits_creates_nothing(client, db, make_user, tmp_path):
    owner = make_user(credits=2)
    r = _upload(client, owner, tmp_path, pages=3)
    assert r.status_code == 400
    assert db.query(TranslationProject).count() == 0
    assert _jobs(db) == []
    assert _wallet(db, owner).subscription_credits == 2


def test_password_protected_pdf_rejected_not_charged_as_one_page(client, db, make_user, tmp_path):
    owner = make_user(credits=10)
    pdf = make_pdf(tmp_path / "locked.pdf", pages=5, user_password="secret")
    with open(pdf, "rb") as f:
        r = client.post("/projects/upload", headers=owner["headers"], files={"file": ("locked.pdf", f, "application/pdf")})
    assert r.status_code == 400
    assert _wallet(db, owner).subscription_credits == 10


def test_unknown_model_rejected(client, make_user, tmp_path):
    owner = make_user()
    assert _upload(client, owner, tmp_path, model="gpt-9-ultra").status_code == 400


def test_expired_trial_cannot_spend_credits(client, db, make_user, tmp_path):
    trial = make_user(plan="TRIAL", credits=1, expires_in_days=-1)
    r = _upload(client, trial, tmp_path, pages=1)
    assert r.status_code == 400
    assert db.query(TranslationProject).count() == 0


def test_idempotency_key_is_scoped_to_user(client, db, make_user, tmp_path):
    alice, bob = make_user(), make_user()
    r1 = _upload(client, alice, tmp_path, pages=1)
    pid = r1.json()["project_id"]
    bob["headers"]["Idempotency-Key"] = "shared-key"
    alice["headers"]["Idempotency-Key"] = "shared-key"
    first = _upload(client, alice, tmp_path, pages=1).json()["project_id"]
    replay = _upload(client, alice, tmp_path, pages=1).json()["project_id"]
    assert replay == first != pid
    bob_resp = _upload(client, bob, tmp_path, pages=1)
    assert bob_resp.json().get("project_id") != first


@pytest.fixture()
def no_background_ai(monkeypatch):
    import app.routers.project as project_router
    from app.services import ai_actions

    calls = []
    monkeypatch.setattr(project_router, "_revise_background", lambda *a: calls.append(("revise", a)))
    monkeypatch.setattr(ai_actions, "run_rebuild", lambda *a: calls.append(("rebuild", a)))
    return calls


def test_revisions_free_then_charged(client, db, make_user, make_project, no_background_ai):
    owner = make_user(credits=5)
    project = make_project(owner, pages=2)
    url = f"/projects/{project.id}/rebuild-with-claude"

    for expected_charge in (False, False, True):
        r = client.post(url, headers=owner["headers"])
        assert r.status_code == 200, r.text
        assert r.json()["charged"] is expected_charge
        db.query(TranslationProject).filter(TranslationProject.id == project.id).update({"rebuild_status": "done"})
        db.commit()
    assert _wallet(db, owner).subscription_credits == 3


def test_revision_without_credits_is_402(client, db, make_user, make_project, no_background_ai):
    owner = make_user(credits=0)
    project = make_project(owner, pages=2)
    project.revision_count = 2
    db.commit()
    r = client.post(f"/projects/{project.id}/rebuild-with-claude", headers=owner["headers"])
    assert r.status_code == 402


def test_concurrent_rebuild_is_409(client, db, make_user, make_project, no_background_ai):
    owner = make_user()
    project = make_project(owner)
    assert client.post(f"/projects/{project.id}/rebuild-with-claude", headers=owner["headers"]).status_code == 200
    assert client.post(f"/projects/{project.id}/rebuild-with-claude", headers=owner["headers"]).status_code == 409


def test_rerun_charges_and_requeues(client, db, make_user, make_project):
    owner = make_user(credits=10)
    project = make_project(owner, pages=4)
    r = client.post(f"/projects/{project.id}/rerun", headers=owner["headers"], json={})
    assert r.status_code == 200, r.text
    assert _wallet(db, owner).subscription_credits == 6
    assert len(_jobs(db, project.id)) == 1
    assert client.post(f"/projects/{project.id}/rerun", headers=owner["headers"], json={}).status_code == 409


def test_preview_html_never_starts_a_rebuild(client, db, make_user, make_project, monkeypatch):
    import app.services.claude_authored_rebuild as rebuild

    monkeypatch.setattr(rebuild, "author_rebuild_docx", lambda *a, **k: pytest.fail("preview triggered a Claude rebuild"))
    owner = make_user()
    project = make_project(owner)
    client.get(f"/projects/{project.id}/preview/rebuild-html", headers=owner["headers"])


def _queued_project(client, db, make_user, tmp_path, credits=10, pages=3):
    owner = make_user(credits=credits)
    pid = _upload(client, owner, tmp_path, pages=pages).json()["project_id"]
    return owner, pid


def test_failed_job_retries_then_fails_with_refund(client, db, make_user, tmp_path, monkeypatch):
    from app.workers import sqs_worker

    owner, pid = _queued_project(client, db, make_user, tmp_path)
    assert _wallet(db, owner).subscription_credits == 7

    def boom(project_id):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(sqs_worker, "process_translation_job", boom)
    monkeypatch.setattr(sqs_worker, "HEARTBEAT_SECONDS", 3600)

    for _ in range(sqs_worker.MAX_ATTEMPTS):
        job = sqs_worker._claim_next_job()
        assert job is not None
        sqs_worker.run_job(job)

    db.expire_all()
    project = db.query(TranslationProject).filter(TranslationProject.id == pid).one()
    assert project.status == ProjectStatus.FAILED
    assert "refunded" in project.failure_reason
    assert _wallet(db, owner).subscription_credits == 10
    assert sqs_worker._claim_next_job() is None


def test_refund_is_idempotent(db, make_user, make_project):
    from app.services.credit_service import CreditService

    owner = make_user(credits=5)
    project = make_project(owner, pages=2)
    CreditService.deduct_credits(db, str(owner["team"].id), 2, reference_id=str(project.id))
    db.commit()
    assert CreditService.refund_usage(db, str(project.id)) == 2
    assert CreditService.refund_usage(db, str(project.id)) == 0
    db.commit()
    assert _wallet(db, owner).subscription_credits == 5
    assert db.query(CreditTransaction).filter(CreditTransaction.type == "REFUND").count() == 1


def test_heartbeat_keeps_long_jobs_alive(client, db, make_user, tmp_path):
    from app.services.watchdog import recover_stalled_jobs
    from app.workers import sqs_worker

    _, pid = _queued_project(client, db, make_user, tmp_path)
    job = sqs_worker._claim_next_job()
    db.execute(text("UPDATE translation_jobs SET locked_at = timezone('utc', now()) - INTERVAL '30 minutes'"))
    db.commit()
    sqs_worker._beat(job["id"], pid)
    recover_stalled_jobs()
    assert _jobs(db, pid)[0].status == "processing"


def test_watchdog_requeues_lost_worker_and_fails_orphans(client, db, make_user, tmp_path):
    from app.services.watchdog import recover_stalled_jobs
    from app.workers import sqs_worker

    owner, pid = _queued_project(client, db, make_user, tmp_path)
    sqs_worker._claim_next_job()
    db.execute(text("UPDATE translation_jobs SET locked_at = timezone('utc', now()) - INTERVAL '30 minutes'"))
    db.commit()
    recover_stalled_jobs()
    assert _jobs(db, pid)[0].status == "pending"

    db.execute(text("DELETE FROM translation_jobs"))
    db.query(TranslationProject).filter(TranslationProject.id == pid).update(
        {"created_at": datetime.utcnow() - timedelta(hours=1)}
    )
    db.commit()
    recover_stalled_jobs()
    db.expire_all()
    project = db.query(TranslationProject).filter(TranslationProject.id == pid).one()
    assert project.status == ProjectStatus.FAILED
    assert _wallet(db, owner).subscription_credits == 10
