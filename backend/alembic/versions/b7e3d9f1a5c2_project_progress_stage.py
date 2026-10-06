"""projects record which stage of the job is running, for honest progress

Revision ID: b7e3d9f1a5c2
Revises: d5f1b3c7e9a2
Create Date: 2026-10-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e3d9f1a5c2'
down_revision: Union[str, Sequence[str], None] = 'd5f1b3c7e9a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('translation_projects', sa.Column('progress_stage', sa.String(length=20), nullable=True))
    op.add_column('translation_projects', sa.Column('progress_detail', sa.String(length=120), nullable=True))
    op.add_column('translation_projects', sa.Column('stage_started_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('translation_projects', 'stage_started_at')
    op.drop_column('translation_projects', 'progress_detail')
    op.drop_column('translation_projects', 'progress_stage')
