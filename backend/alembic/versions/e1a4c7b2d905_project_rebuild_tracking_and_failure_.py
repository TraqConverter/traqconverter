"""project rebuild tracking and failure reason

Revision ID: e1a4c7b2d905
Revises: d39e8a51bcaf
Create Date: 2026-09-25 16:26:02.445919

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a4c7b2d905'
down_revision: Union[str, Sequence[str], None] = 'd39e8a51bcaf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('translation_projects', sa.Column('revision_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('translation_projects', sa.Column('rebuild_status', sa.String(), nullable=True))
    op.add_column('translation_projects', sa.Column('rebuild_error', sa.String(), nullable=True))
    op.add_column('translation_projects', sa.Column('rebuild_started_at', sa.DateTime(), nullable=True))
    op.add_column('translation_projects', sa.Column('failure_reason', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('translation_projects', 'failure_reason')
    op.drop_column('translation_projects', 'rebuild_started_at')
    op.drop_column('translation_projects', 'rebuild_error')
    op.drop_column('translation_projects', 'rebuild_status')
    op.drop_column('translation_projects', 'revision_count')
