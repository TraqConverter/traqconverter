"""tm language pair scope

Revision ID: 20d6e44f5a81
Revises: 85f03c87c60a
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20d6e44f5a81"
down_revision: Union[str, Sequence[str], None] = "85f03c87c60a"
branch_labels = None
depends_on = None


def upgrade():

    # STEP 1 — add columns nullable
    op.add_column(
        "translation_memory",
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True)
    )

    op.add_column(
        "translation_memory",
        sa.Column("source_language", sa.String(), nullable=True)
    )

    op.add_column(
        "translation_memory",
        sa.Column("target_language", sa.String(), nullable=True)
    )

    # STEP 2 — populate existing rows
    op.execute("""
        UPDATE translation_memory
        SET source_language = 'unknown'
        WHERE source_language IS NULL
    """)

    op.execute("""
        UPDATE translation_memory
        SET target_language = 'unknown'
        WHERE target_language IS NULL
    """)

    # STEP 3 — set NOT NULL
    op.alter_column("translation_memory", "source_language", nullable=False)
    op.alter_column("translation_memory", "target_language", nullable=False)

    # Add index
    op.create_index(
        "idx_tm_lookup",
        "translation_memory",
        ["team_id", "source_language", "target_language", "source_text"]
    )


def downgrade():

    op.drop_index("idx_tm_lookup", table_name="translation_memory")

    op.drop_column("translation_memory", "target_language")
    op.drop_column("translation_memory", "source_language")
    op.drop_column("translation_memory", "team_id")