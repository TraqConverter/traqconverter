"""template uploads: past jobs waiting to be confirmed as templates

Revision ID: e8b2c4f6a1d3
Revises: d7f3a9c1e5b2
Create Date: 2026-09-30 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8b2c4f6a1d3'
down_revision: Union[str, Sequence[str], None] = 'd7f3a9c1e5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('template_uploads',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('original_name', sa.String(), nullable=False),
    sa.Column('original_key', sa.String(), nullable=False),
    sa.Column('translation_key', sa.String(), nullable=False),
    sa.Column('target_language', sa.String(), nullable=False),
    sa.Column('profile', sa.JSON(), nullable=True),
    sa.Column('source_lines', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_template_uploads_team_id'), 'template_uploads', ['team_id'], unique=False)
    op.create_index(op.f('ix_template_uploads_expires_at'), 'template_uploads', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_template_uploads_expires_at'), table_name='template_uploads')
    op.drop_index(op.f('ix_template_uploads_team_id'), table_name='template_uploads')
    op.drop_table('template_uploads')
