"""team library of saved instructions for the AI

Revision ID: f6c2a8d4e0b7
Revises: d4a8f2c6e1b3
Create Date: 2026-10-01 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f6c2a8d4e0b7'
down_revision: Union[str, Sequence[str], None] = 'd4a8f2c6e1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'saved_instructions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_saved_instructions_team_id', 'saved_instructions', ['team_id'])
    op.create_index(
        'uq_saved_instruction_team_name', 'saved_instructions', ['team_id', sa.text('lower(name)')], unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_saved_instruction_team_name', table_name='saved_instructions')
    op.drop_index('ix_saved_instructions_team_id', table_name='saved_instructions')
    op.drop_table('saved_instructions')
