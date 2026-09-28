"""drop unused jobs table

Revision ID: a3c9e5f1b702
Revises: f2b8d3e6a117
Create Date: 2026-09-25 16:34:11.186831

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a3c9e5f1b702'
down_revision: Union[str, Sequence[str], None] = 'f2b8d3e6a117'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('jobs')


def downgrade() -> None:
    op.create_table('jobs',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('team_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_by', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('source_language', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('target_language', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('page_count', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('credits_used', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('status', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.Column('completed_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('jobs_created_by_fkey')),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name=op.f('jobs_team_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('jobs_pkey'))
    )
