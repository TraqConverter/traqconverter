"""notifications: in-app notices behind the header bell

Revision ID: a2d6f8b0c4e7
Revises: f1c3a5e7b9d2
Create Date: 2026-10-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a2d6f8b0c4e7'
down_revision: Union[str, Sequence[str], None] = 'f1c3a5e7b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('body', sa.String(length=500), nullable=False),
        sa.Column('link', sa.String(length=500), nullable=True),
        sa.Column(
            'project_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('translation_projects.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_notifications_user_read_created', 'notifications', ['user_id', 'read_at', 'created_at'])
    op.create_index('ix_notifications_project_id', 'notifications', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_notifications_project_id', table_name='notifications')
    op.drop_index('ix_notifications_user_read_created', table_name='notifications')
    op.drop_table('notifications')
