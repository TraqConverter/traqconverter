"""add glossary table

Revision ID: a2b0d6e27d71
Revises: f398cbd7a314
Create Date: 2026-04-11 16:21:37.032431

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b0d6e27d71'
down_revision: Union[str, Sequence[str], None] = 'f398cbd7a314'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "glossary",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("team_id", sa.UUID(), nullable=False),
        sa.Column("source_language", sa.String(), nullable=False),
        sa.Column("target_language", sa.String(), nullable=False),
        sa.Column("source_term", sa.Text(), nullable=False),
        sa.Column("target_term", sa.Text(), nullable=False),
    )

def downgrade():
    op.drop_table("glossary")