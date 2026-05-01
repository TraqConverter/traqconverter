"""add certifications library table

Revision ID: 9d2e8c3b5a47
Revises: 8a3f2b9c4d12
Create Date: 2026-04-29 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "9d2e8c3b5a47"
down_revision: Union[str, Sequence[str], None] = "8a3f2b9c4d12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if "certifications" not in inspector.get_table_names():
        op.create_table(
            "certifications",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column(
                "team_id",
                sa.UUID(),
                sa.ForeignKey("teams.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "uploaded_by",
                sa.UUID(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("file_name", sa.String(), nullable=False),
            sa.Column("file_path", sa.String(), nullable=False),
            # AFFIDAVIT / ISO_17100 / SWORN_DECLARATION / OTHER
            sa.Column(
                "kind", sa.String(), nullable=False, server_default="OTHER"
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("file_hash", sa.String(64), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("mime_type", sa.String(), nullable=True),
            sa.Column(
                "uploaded_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "idx_certifications_team", "certifications", ["team_id"]
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if "certifications" in inspector.get_table_names():
        op.drop_index("idx_certifications_team", table_name="certifications")
        op.drop_table("certifications")
