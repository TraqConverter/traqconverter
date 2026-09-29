"""ai usage metering and per-document AI edit allowance

Revision ID: e3a1c5f7b9d2
Revises: c7e2a9d4f1b8
Create Date: 2026-09-29 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3a1c5f7b9d2'
down_revision: Union[str, Sequence[str], None] = 'c7e2a9d4f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('ai_usage',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=True),
    sa.Column('project_id', sa.UUID(), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('model', sa.String(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cache_read_tokens', sa.Integer(), nullable=False),
    sa.Column('cache_write_tokens', sa.Integer(), nullable=False),
    sa.Column('usd', sa.Numeric(12, 6), nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['translation_projects.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ai_usage_created_at', 'ai_usage', ['created_at'], unique=False)
    op.create_index('ix_ai_usage_team_created', 'ai_usage', ['team_id', 'created_at'], unique=False)
    op.create_index('ix_ai_usage_project_id', 'ai_usage', ['project_id'], unique=False)
    op.create_index('ix_ai_usage_action_created', 'ai_usage', ['action', 'created_at'], unique=False)

    op.add_column('translation_projects', sa.Column('ai_edits_used', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('translation_projects', 'ai_edits_used')
    op.drop_index('ix_ai_usage_action_created', table_name='ai_usage')
    op.drop_index('ix_ai_usage_project_id', table_name='ai_usage')
    op.drop_index('ix_ai_usage_team_created', table_name='ai_usage')
    op.drop_index('ix_ai_usage_created_at', table_name='ai_usage')
    op.drop_table('ai_usage')
