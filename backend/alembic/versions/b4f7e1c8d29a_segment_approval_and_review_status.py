"""add segment approval, tm_pct and project review_status

Revision ID: b4f7e1c8d29a
Revises: 9d2e8c3b5a47
Create Date: 2026-04-29 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "b4f7e1c8d29a"
down_revision: Union[str, Sequence[str], None] = "9d2e8c3b5a47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    # ---- translation_segments: approval + tm match percentage ----
    seg_cols = {c["name"] for c in inspector.get_columns("translation_segments")}

    if "approved" not in seg_cols:
        op.add_column(
            "translation_segments",
            sa.Column(
                "approved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    if "tm_pct" not in seg_cols:
        op.add_column(
            "translation_segments",
            sa.Column("tm_pct", sa.Integer(), nullable=True),
        )

    # ---- translation_projects: review status (DRAFT/IN_REVIEW/CERTIFIED) ----
    proj_cols = {c["name"] for c in inspector.get_columns("translation_projects")}

    if "review_status" not in proj_cols:
        op.add_column(
            "translation_projects",
            sa.Column(
                "review_status",
                sa.String(),
                nullable=False,
                server_default="DRAFT",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    proj_cols = {c["name"] for c in inspector.get_columns("translation_projects")}
    if "review_status" in proj_cols:
        op.drop_column("translation_projects", "review_status")

    seg_cols = {c["name"] for c in inspector.get_columns("translation_segments")}
    if "tm_pct" in seg_cols:
        op.drop_column("translation_segments", "tm_pct")
    if "approved" in seg_cols:
        op.drop_column("translation_segments", "approved")
