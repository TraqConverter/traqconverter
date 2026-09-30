"""translation_jobs.priority: Agency teams' jobs are claimed first

Revision ID: a7c3e9f1b5d2
Revises: c5e7a9b1d3f2
Create Date: 2026-10-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c3e9f1b5d2'
down_revision: Union[str, Sequence[str], None] = 'c5e7a9b1d3f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'translation_jobs',
        sa.Column('priority', sa.SmallInteger(), nullable=False, server_default=sa.text('0')),
    )
    op.drop_index('idx_translation_jobs_pending', table_name='translation_jobs')
    op.create_index(
        'idx_translation_jobs_pending',
        'translation_jobs',
        [sa.text('priority DESC'), 'created_at'],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index('idx_translation_jobs_pending', table_name='translation_jobs')
    op.create_index(
        'idx_translation_jobs_pending', 'translation_jobs', ['created_at'],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_column('translation_jobs', 'priority')
