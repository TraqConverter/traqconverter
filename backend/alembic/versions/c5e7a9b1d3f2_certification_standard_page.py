"""project can ask for the standard certification page over the team default

Revision ID: c5e7a9b1d3f2
Revises: e8b2c4f6a1d3
Create Date: 2026-09-30 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5e7a9b1d3f2'
down_revision: Union[str, Sequence[str], None] = 'e8b2c4f6a1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'translation_projects',
        sa.Column('certification_standard', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('translation_projects', 'certification_standard')
