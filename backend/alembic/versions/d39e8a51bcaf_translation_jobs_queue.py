"""postgres-backed job queue (replaces sqs)

Revision ID: d39e8a51bcaf
Revises: c427fe1382bd
Create Date: 2026-05-18 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d39e8a51bcaf"
down_revision: Union[str, Sequence[str], None] = "c427fe1382bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "translation_jobs",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("translation_projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("s3_key", sa.String(), nullable=False),
        # pending → processing → completed (or failed). Workers atomically
        # flip pending → processing via SELECT … FOR UPDATE SKIP LOCKED.
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("locked_by", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Partial index lets the worker `SELECT … WHERE status='pending'`
    # extremely fast even when there are millions of completed jobs.
    op.create_index(
        "idx_translation_jobs_pending",
        "translation_jobs",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    # Lookups by project_id for the "what's the latest job for this
    # project" status checks.
    op.create_index(
        "idx_translation_jobs_project",
        "translation_jobs",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_translation_jobs_project", table_name="translation_jobs")
    op.drop_index("idx_translation_jobs_pending", table_name="translation_jobs")
    op.drop_table("translation_jobs")
