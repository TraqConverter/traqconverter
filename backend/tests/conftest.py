import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
os.environ.setdefault("RUN_WORKER_INLINE", "0")


def _db_name(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


@pytest.fixture(scope="session")
def migrated_db():
    from app.config import settings

    # These tests truncate every table; never let them near a real database.
    if not _db_name(settings.database_url).endswith("_test"):
        pytest.skip("database_url must point at a *_test database to run DB tests")

    import alembic.config
    from alembic import command

    os.environ["DATABASE_URL"] = settings.database_url
    command.upgrade(alembic.config.Config(str(BACKEND / "alembic.ini")), "head")
    return settings.database_url


@pytest.fixture()
def db(migrated_db):
    from sqlalchemy import text

    from app.database import SessionLocal, engine
    from app.dependencies import rate_limit

    with engine.begin() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")
            )
        ]
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    rate_limit._buckets.clear()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def storage(monkeypatch):
    """In-memory stand-in for S3/Supabase storage."""
    objects: dict[str, bytes] = {}
    deleted: list[str] = []

    def upload(path, prefix="uploads"):
        key = f"{prefix}/{uuid.uuid4()}_{Path(path).name}"
        objects[key] = Path(path).read_bytes()
        return key

    def download(key, destination):
        Path(destination).write_bytes(objects[key])

    def delete(keys):
        deleted.extend(k for k in keys if k)

    import app.routers.project as project_router
    import app.services.s3_service as s3

    monkeypatch.setattr(s3, "upload_file_to_s3", upload)
    monkeypatch.setattr(s3, "download_file_from_s3", download)
    monkeypatch.setattr(s3, "delete_objects_from_s3", delete)
    monkeypatch.setattr(s3, "generate_presigned_download_url", lambda key, **kw: f"https://storage.test/{key}")
    monkeypatch.setattr(project_router, "upload_file_to_s3", upload)
    monkeypatch.setattr(project_router, "generate_presigned_download_url", lambda key, **kw: f"https://storage.test/{key}")
    return {"objects": objects, "deleted": deleted}


@pytest.fixture()
def client(db, storage):
    from fastapi.testclient import TestClient

    from app.main import app

    # Not used as a context manager, so startup hooks (watchdog loop, inline worker) don't run.
    return TestClient(app)


@pytest.fixture()
def make_user(db):
    from app.core.security import create_access_token, hash_password
    from app.models.credit import CreditWallet
    from app.models.team import Team
    from app.models.team_member import TeamMember
    from app.models.user import User

    def _make(
        email=None,
        plan="PRO",
        credits=100,
        team=None,
        role="MEMBER",
        expires_in_days=30,
    ):
        user = User(
            email=email or f"{uuid.uuid4().hex[:8]}@traqtest.io",
            password_hash=hash_password("correct horse battery"),
            full_name="Test User",
        )
        db.add(user)
        db.flush()
        if team is None:
            team = Team(name="Team", owner_id=user.id)
            db.add(team)
            db.flush()
            db.add(CreditWallet(
                team_id=team.id,
                subscription_credits=credits,
                purchased_credits=0,
                plan_type=plan,
                subscription_status="TRIAL" if plan == "TRIAL" else "ACTIVE",
                subscription_expires_at=datetime.utcnow() + timedelta(days=expires_in_days),
            ))
        else:
            db.add(TeamMember(team_id=team.id, user_id=user.id, role=role))
        db.commit()
        token = create_access_token({"sub": str(user.id)}, token_version=0)
        return {
            "user": user,
            "team": team,
            "headers": {"Authorization": f"Bearer {token}"},
        }

    return _make


@pytest.fixture()
def make_project(db, storage):
    from app.models.project import ProjectStatus, TranslationProject
    from app.models.translation_segment import TranslationSegment

    def _make(owner, status=ProjectStatus.COMPLETED, pages=2, segments=("Hello world", "Second line"), source_kind="PDF"):
        key = f"uploads/{uuid.uuid4()}_source.pdf"
        storage["objects"][key] = b"%PDF-1.4 test"
        project = TranslationProject(
            user_id=owner["user"].id,
            team_id=owner["team"].id,
            file_name="source.pdf",
            file_path=key,
            output_file=f"uploads/{uuid.uuid4()}_out.docx",
            page_count=pages,
            credits_used=pages,
            status=status,
            source_kind=source_kind,
            source_language="Italian",
            target_language="English",
            model="claude-sonnet-4-6",
        )
        db.add(project)
        db.flush()
        for i, text in enumerate(segments):
            db.add(TranslationSegment(
                project_id=project.id,
                segment_index=i,
                source_text=text,
                translated_text=f"[en] {text}",
            ))
        db.commit()
        return project

    return _make


def make_pdf(path: Path, pages: int = 1, user_password: str | None = None) -> Path:
    import fitz

    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Pagina {i + 1} del documento")
    if user_password:
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=user_password, owner_pw="owner")
    else:
        doc.save(str(path))
    doc.close()
    return path
