"""add notes and usage_count to glossary

Revision ID: 7c1e9d2f4a31
Revises: ba6bff38981e
Create Date: 2026-04-29 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "7c1e9d2f4a31"
down_revision: Union[str, Sequence[str], None] = "ba6bff38981e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add notes (free-form text) and usage_count (auto-incremented when the
    term is matched in a translation) to the glossary table."""
    conn = op.get_bind()
    inspector = inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("glossary")}

    if "notes" not in existing:
        op.add_column(
            "glossary",
            sa.Column("notes", sa.Text(), nullable=True),
        )

    if "usage_count" not in existing:
        op.add_column(
            "glossary",
            sa.Column(
                "usage_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
        # Drop the server_default after the column is populated so future
        # inserts go through the model's default instead of the DB default.
        op.alter_column("glossary", "usage_count", server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("glossary")}

    if "usage_count" in existing:
        op.drop_column("glossary", "usage_count")

    if "notes" in existing:
        op.drop_column("glossary", "notes")
