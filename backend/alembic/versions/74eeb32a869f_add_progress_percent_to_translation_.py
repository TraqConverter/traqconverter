"""add progress_percent to translation_projects

Revision ID: 74eeb32a869f
Revises: 6e529129d058
Create Date: 2026-03-03 22:02:14.179103

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '74eeb32a869f'
down_revision: Union[str, Sequence[str], None] = '6e529129d058'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'translation_projects',
        sa.Column('progress_percent', sa.Integer(), nullable=False, server_default='0')
    )


def downgrade() -> None:
    op.drop_column('translation_projects', 'progress_percent')
