"""add layout_meta json on segments and source_kind on projects

Revision ID: c2f8a91e6b35
Revises: b4f7e1c8d29a
Create Date: 2026-04-29 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import inspect


revision: str = "c2f8a91e6b35"
down_revision: Union[str, Sequence[str], None] = "b4f7e1c8d29a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    seg_cols = {c["name"] for c in inspector.get_columns("translation_segments")}
    if "layout_meta" not in seg_cols:
        op.add_column(
            "translation_segments",
            sa.Column("layout_meta", JSONB(), nullable=True),
        )

    proj_cols = {c["name"] for c in inspector.get_columns("translation_projects")}
    if "source_kind" not in proj_cols:
        # PDF / DOCX / IMAGE / TXT — drives which rebuild path runs.
        op.add_column(
            "translation_projects",
            sa.Column("source_kind", sa.String(), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    proj_cols = {c["name"] for c in inspector.get_columns("translation_projects")}
    if "source_kind" in proj_cols:
        op.drop_column("translation_projects", "source_kind")

    seg_cols = {c["name"] for c in inspector.get_columns("translation_segments")}
    if "layout_meta" in seg_cols:
        op.drop_column("translation_segments", "layout_meta")
