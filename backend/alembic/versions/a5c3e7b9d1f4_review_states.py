"""review: source map, pre-delivery checks and dismissals per project

Revision ID: a5c3e7b9d1f4
Revises: c7e2a9d4f1b8
Create Date: 2026-09-29 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a5c3e7b9d1f4'
down_revision: Union[str, Sequence[str], None] = 'c7e2a9d4f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('review_states',
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('source_key', sa.String(), nullable=True),
    sa.Column('source_map', sa.JSON(), nullable=True),
    sa.Column('map_revision', sa.Integer(), server_default='0', nullable=False),
    sa.Column('names', sa.JSON(), nullable=True),
    sa.Column('untranslated', sa.JSON(), nullable=True),
    sa.Column('checks', sa.JSON(), nullable=True),
    sa.Column('dismissed', sa.JSON(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['translation_projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('project_id')
    )


def downgrade() -> None:
    op.drop_table('review_states')
