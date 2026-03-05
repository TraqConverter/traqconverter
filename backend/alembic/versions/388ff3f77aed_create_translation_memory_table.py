"""create translation_memory table

Revision ID: 388ff3f77aed
Revises: 61b344e83558
Create Date: 2026-03-05 21:57:36.158273

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '388ff3f77aed'
down_revision: Union[str, Sequence[str], None] = '61b344e83558'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "translation_memory",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),

        sa.PrimaryKeyConstraint("id")
    )


def downgrade() -> None:

    op.drop_table("translation_memory")
