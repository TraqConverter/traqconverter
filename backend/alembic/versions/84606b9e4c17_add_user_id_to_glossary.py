"""add user_id to glossary

Revision ID: 84606b9e4c17
Revises: a2b0d6e27d71
Create Date: 2026-04-11 17:07:49.814954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84606b9e4c17'
down_revision: Union[str, Sequence[str], None] = 'a2b0d6e27d71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column(
        "glossary",
        sa.Column("user_id", sa.UUID(), nullable=True)
    )


def downgrade():
    op.drop_column("glossary", "user_id")