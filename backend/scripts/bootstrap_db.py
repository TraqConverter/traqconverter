"""Bootstrap a fresh database.

Use case: brand-new (or just-wiped) Postgres where nothing has been
created yet AND `alembic upgrade head` can't run because the initial
baseline migration is just a stamp marker without table-creation SQL.

What this does
--------------
1. Imports every SQLAlchemy model so they register on Base.metadata.
2. Calls `Base.metadata.create_all()` — creates every table the app
   needs based on the current model classes.
3. Creates the `translation_jobs` queue table (it has no SQLAlchemy
   model — it's pure migration SQL).
4. Stamps alembic at HEAD so future migrations (new deltas added
   later) will run cleanly without trying to re-create what already
   exists.

Idempotent: safe to run multiple times. Creates only what's missing.

Usage:
    python -m scripts.bootstrap_db
"""
import logging
import sys
from pathlib import Path

# Make `app...` imports work when run via `python -m scripts.bootstrap_db`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    from sqlalchemy import text

    from app.database import Base, engine

    # Import every model module so SQLAlchemy registers them on
    # Base.metadata. Without these imports `create_all` would only
    # touch the tables already loaded via other imports.
    from app.models import (  # noqa: F401
        user,
        team,
        team_member,
        project,
        translation_segment,
        translation_memory,
        glossary,
        credit,
        stripe_event,
        segment_comment,
        certification,
        job,
    )

    logger.info("Creating tables from SQLAlchemy models …")
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Base.metadata.create_all complete")

    # translation_jobs has no SQLAlchemy model — it's pure migration
    # SQL. Create it here so the bootstrap is one-shot.
    logger.info("Creating translation_jobs queue table …")
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS translation_jobs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    project_id UUID NOT NULL REFERENCES translation_projects(id)
                        ON DELETE CASCADE,
                    s3_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    locked_at TIMESTAMP,
                    locked_by TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_translation_jobs_pending
                    ON translation_jobs(created_at)
                    WHERE status = 'pending';
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_translation_jobs_project
                    ON translation_jobs(project_id, created_at);
                """
            )
        )
        conn.commit()
    logger.info("✅ translation_jobs table ready")

    # Stamp alembic at HEAD so any future migration deltas (added
    # after this bootstrap) will run cleanly without trying to
    # re-create what's already here.
    logger.info("Stamping alembic at HEAD …")
    try:
        import alembic.config
        from alembic import command

        cfg = alembic.config.Config(
            str(Path(__file__).resolve().parent.parent / "alembic.ini")
        )
        command.stamp(cfg, "head")
        logger.info("✅ alembic_version stamped at head")
    except Exception as e:
        logger.warning(
            "Couldn't stamp alembic (you can still run "
            "`python -m alembic stamp head` manually): %s",
            e,
        )

    print()
    print("🎉 Bootstrap complete.")
    print("Next: python -m scripts.create_superuser")
    return 0


if __name__ == "__main__":
    sys.exit(main())
