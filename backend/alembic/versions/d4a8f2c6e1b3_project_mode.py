"""project mode: translate or dtp (editable same-language copy)

Revision ID: d4a8f2c6e1b3
Revises: c5e7a9b1d3f2
Create Date: 2026-10-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4a8f2c6e1b3'
down_revision: Union[str, Sequence[str], None] = 'c5e7a9b1d3f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'translation_projects',
        sa.Column('mode', sa.String(), nullable=False, server_default='translate'),
    )


def downgrade() -> None:
    op.drop_column('translation_projects', 'mode')
