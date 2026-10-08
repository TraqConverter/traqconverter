"""Automatic deletion after DOCUMENT_RETENTION_DAYS, and replaced files deleted on rerun and regenerate."""
import os
import time
import uuid
from datetime import datetime, timedelta

import pytest

from app.models.delivery_link import DeliveryLink
from app.models.document_version import DocumentVersion
from app.models.glossary import Glossary
from app.models.learning import DocumentTemplate
from app.models.notification import Notification
from app.models.project import ProjectStatus, TranslationProject
from app.models.translation_memory import TranslationMemory
from app.services import document_retention, source_pages
from tests.conftest import make_pdf

NOW = datetime(2026, 10, 8, 12, 0)


@pytest.fixture(autouse=True)
def page_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_PAGE_CACHE", str(tmp_path / "pages"))
    return tmp_path / "pages"


def _aged(db, project, days, field="retention_from"):
    setattr(project, field, NOW - timedelta(days=days))
    if field == "created_at":
        project.retention_from = None
    db.commit()
    return project


def _exists(db, project_id):
    db.expire_all()
    return db.query(TranslationProject).filter(TranslationProject.id == project_id).first() is not None


def test_a_project_is_deleted_90_days_after_it_last_completed(db, storage, make_user, make_project, page_cache):
    owner = make_user()
    old = _aged(db, make_project(owner), 91)
    fresh = _aged(db, make_project(owner), 89)
    old_id, old_keys = old.id, [old.file_path, old.output_file]
    db.add(DocumentVersion(project_id=old.id, version=1, s3_key="uploads/edit-v1.docx"))
    db.add(DeliveryLink(project_id=old.id, token_hash=uuid.uuid4().hex, token_prefix="abcdef", kind="pdf",
                        file_name="out.pdf", file_key="delivery/out.pdf", preview_keys=["delivery/preview/1.pdf"],
                        expires_at=NOW, created_by=owner["user"].id))
    db.commit()
    (page_cache / str(old_id) / "abc").mkdir(parents=True)
    (page_cache / str(old_id) / "abc" / "page-0.png").write_bytes(b"png")

    assert document_retention.run(NOW) == 1

    assert not _exists(db, old_id)
    assert _exists(db, fresh.id)
    for key in (*old_keys, "uploads/edit-v1.docx", "delivery/out.pdf", "delivery/preview/1.pdf"):
        assert key in storage["deleted"]
    assert fresh.file_path not in storage["deleted"]
    assert not (page_cache / str(old_id)).exists()


def test_a_project_that_never_completed_counts_from_its_creation(db, make_user, make_project):
    owner = make_user()
    failed = _aged(db, make_project(owner, status=ProjectStatus.FAILED), 91, field="created_at")
    running = _aged(db, make_project(owner, status=ProjectStatus.PROCESSING), 200, field="created_at")
    failed_id, running_id = failed.id, running.id
    assert document_retention.run(NOW) == 1
    assert not _exists(db, failed_id)
    assert _exists(db, running_id)


def test_existing_projects_start_counting_from_the_migration(db, make_user, make_project):
    from sqlalchemy import text

    owner = make_user()
    project = make_project(owner)
    project.created_at = NOW - timedelta(days=400)
    db.commit()
    # What the migration's backfill does to every project that exists at deploy.
    db.execute(text("UPDATE translation_projects SET retention_from = :now"), {"now": NOW})
    db.commit()
    assert document_retention.run(NOW) == 0
    assert _exists(db, project.id)
    assert document_retention.run(NOW + timedelta(days=90)) == 1


def test_memory_glossary_and_templates_survive(db, make_user, make_project):
    owner = make_user()
    team_id = owner["team"].id
    project = _aged(db, make_project(owner), 120)
    db.add(TranslationMemory(team_id=team_id, project_id=project.id, source_language="it", target_language="en",
                             source_text="Ciao", translated_text="Hello", source_hash="a" * 64))
    db.add(Glossary(team_id=team_id, source_language="it", target_language="en", source_term="atto",
                    target_term="deed", origin="learned", learned_from_project_id=project.id))
    db.add(DocumentTemplate(team_id=team_id, doc_key="birth", target_language="en", title="Birth", s3_key="uploads/template.docx",
                            source_project_id=project.id, source_text="Atto di nascita"))
    db.commit()

    assert document_retention.run(NOW) == 1

    db.expire_all()
    tm = db.query(TranslationMemory).one()
    assert (tm.translated_text, tm.project_id) == ("Hello", None)
    assert db.query(Glossary).one().learned_from_project_id is None
    assert db.query(DocumentTemplate).one().source_project_id is None


def test_manual_delete_still_removes_the_projects_memory(client, db, make_user, make_project):
    owner = make_user()
    project = make_project(owner)
    db.add(TranslationMemory(team_id=owner["team"].id, project_id=project.id, source_language="it",
                             target_language="en", source_text="Ciao", translated_text="Hello", source_hash="b" * 64))
    db.commit()
    assert client.delete(f"/projects/{project.id}", headers=owner["headers"]).status_code == 200
    assert db.query(TranslationMemory).count() == 0


def test_users_are_warned_once_a_week_before(db, make_user, make_project):
    owner = make_user()
    soon = _aged(db, make_project(owner), 85)
    _aged(db, make_project(owner), 30)

    assert document_retention.warn_upcoming(db, NOW) == 1
    assert document_retention.warn_upcoming(db, NOW + timedelta(hours=3)) == 0
    note = db.query(Notification).one()
    assert (note.kind, note.project_id) == ("files_expiring", soon.id)
    assert "13 October 2026" in note.title


def test_project_pages_show_the_deletion_date(client, db, make_user, make_project):
    owner = make_user()
    project = make_project(owner)
    project.retention_from = datetime(2026, 10, 1, 9, 30)
    db.commit()
    detail = client.get(f"/projects/{project.id}", headers=owner["headers"]).json()
    assert detail["deletes_on"].startswith("2026-12-30")
    listed = client.get("/projects", headers=owner["headers"]).json()
    rows = listed["items"] if isinstance(listed, dict) else listed
    assert rows[0]["deletes_on"].startswith("2026-12-30")


def test_retention_off_deletes_nothing(db, make_user, make_project, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DOCUMENT_RETENTION_DAYS", 0)
    owner = make_user()
    project = _aged(db, make_project(owner), 500)
    assert document_retention.run(NOW) == 0
    assert _exists(db, project.id)


def test_a_second_instance_skips_while_the_lock_is_held(db, make_user, make_project):
    from sqlalchemy import text

    from app.database import engine

    owner = make_user()
    project = _aged(db, make_project(owner), 100)
    with engine.connect() as other:
        assert other.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": document_retention.LOCK_KEY}).scalar()
        assert document_retention.run(NOW) == 0
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": document_retention.LOCK_KEY})
        other.commit()
    assert _exists(db, project.id)
    assert document_retention.run(NOW) == 1


def test_stale_page_caches_are_removed(page_cache):
    old, recent = page_cache / "old-project", page_cache / "recent-project"
    for folder in (old, recent):
        (folder / "abc").mkdir(parents=True)
        (folder / "abc" / "page-0.png").write_bytes(b"png")
    stale = time.time() - 8 * 86400
    os.utime(old / "abc" / "page-0.png", (stale, stale))
    os.utime(old / "abc", (stale, stale))
    os.utime(old, (stale, stale))
    assert source_pages.purge_stale() == 1
    assert not old.exists() and recent.exists()


def test_a_rerun_deletes_the_files_it_replaced(db, storage, make_user, make_project, monkeypatch, tmp_path):
    from app.services import translation_processor as tp

    owner = make_user()
    project = make_project(owner, status=ProjectStatus.PENDING, segments=())
    old_output = project.output_file
    project.authored_docx_s3_key = "uploads/old_authored.docx"
    kept = "uploads/saved_edit.docx"
    db.add(DocumentVersion(project_id=project.id, version=1, s3_key=kept))
    db.commit()
    pdf = make_pdf(tmp_path / "doc.pdf", pages=1).read_bytes()

    def rebuild(**kw):
        open(kw["output_path"], "wb").write(b"docx")
        return kw["output_path"]

    uploads = iter(f"uploads/new_{i}.docx" for i in range(10))
    monkeypatch.setattr(tp, "download_file_from_s3", lambda key, dest: open(dest, "wb").write(pdf))
    monkeypatch.setattr(tp, "translate_batch", lambda texts, *a, **kw: [f"[en] {t}" for t in texts])
    monkeypatch.setattr(tp, "translate_text", lambda text, *a, **kw: f"[en] {text}")
    monkeypatch.setattr(tp, "rebuild_output", rebuild)
    monkeypatch.setattr(tp, "upload_file_to_s3", lambda path: next(uploads))

    tp.process_translation_job(str(project.id))

    db.expire_all()
    project = db.query(TranslationProject).filter(TranslationProject.id == project.id).one()
    assert project.status == ProjectStatus.COMPLETED
    assert project.retention_from is not None
    assert old_output in storage["deleted"]
    assert "uploads/old_authored.docx" in storage["deleted"]
    assert project.output_file not in storage["deleted"]

    # A saved version still points at it, so the editor's history keeps it.
    project.authored_docx_s3_key = kept
    project.status = ProjectStatus.PENDING
    db.commit()
    tp.process_translation_job(str(project.id))
    assert kept not in storage["deleted"]


def test_a_regenerate_deletes_the_document_it_replaced(db, storage, make_user, make_project, monkeypatch):
    from app.services import ai_actions
    from app.services import claude_authored_rebuild as car

    owner = make_user()
    project = make_project(owner)
    project.mode = "dtp"
    project.target_language = project.source_language
    project.authored_docx_s3_key = "uploads/before_regenerate.docx"
    db.commit()
    monkeypatch.setattr(car, "author_rebuild_docx", lambda **kw: b"docx")

    ai_actions.run_rebuild(str(project.id), None)

    db.expire_all()
    project = db.query(TranslationProject).filter(TranslationProject.id == project.id).one()
    assert project.rebuild_status == "done"
    assert "uploads/before_regenerate.docx" in storage["deleted"]
    assert project.authored_docx_s3_key not in storage["deleted"]
