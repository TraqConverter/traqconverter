"""create translation_segments table

Revision ID: 61b344e83558
Revises: 1d9b898d3c60
Create Date: 2026-03-05 21:39:01.378470

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '61b344e83558'
down_revision: Union[str, Sequence[str], None] = '1d9b898d3c60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "translation_segments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),

        sa.ForeignKeyConstraint(
            ["project_id"],
            ["translation_projects.id"],
        ),

        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:

    op.drop_table("translation_segments")