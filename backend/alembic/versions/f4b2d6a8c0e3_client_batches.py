"""client batches and batch terms

Revision ID: f4b2d6a8c0e3
Revises: c7e2a9d4f1b8
Create Date: 2026-09-29 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4b2d6a8c0e3'
down_revision: Union[str, Sequence[str], None] = 'c7e2a9d4f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('batches',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('terms_ready_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_batches_team_id'), 'batches', ['team_id'], unique=False)

    op.create_table('batch_terms',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('batch_id', sa.UUID(), nullable=False),
    sa.Column('target_language', sa.String(), nullable=False),
    sa.Column('source_term', sa.String(), nullable=False),
    sa.Column('source_key', sa.String(), nullable=False),
    sa.Column('target_term', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('first_project_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['first_project_id'], ['translation_projects.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('batch_id', 'target_language', 'source_key', name='uq_batch_term')
    )
    op.create_index(op.f('ix_batch_terms_batch_id'), 'batch_terms', ['batch_id'], unique=False)

    op.add_column('translation_projects', sa.Column('batch_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_translation_projects_batch_id'), 'translation_projects', ['batch_id'], unique=False)
    op.create_foreign_key(
        'fk_translation_projects_batch_id', 'translation_projects', 'batches',
        ['batch_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_translation_projects_batch_id', 'translation_projects', type_='foreignkey')
    op.drop_index(op.f('ix_translation_projects_batch_id'), table_name='translation_projects')
    op.drop_column('translation_projects', 'batch_id')
    op.drop_index(op.f('ix_batch_terms_batch_id'), table_name='batch_terms')
    op.drop_table('batch_terms')
    op.drop_index(op.f('ix_batches_team_id'), table_name='batches')
    op.drop_table('batches')
