"""learning: document profiles, templates, learned terms

Revision ID: c7e2a9d4f1b8
Revises: b5d1f8a2c6e3
Create Date: 2026-09-29 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e2a9d4f1b8'
down_revision: Union[str, Sequence[str], None] = 'b5d1f8a2c6e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('document_templates',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('doc_key', sa.String(), nullable=False),
    sa.Column('target_language', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('doc_profile', sa.JSON(), nullable=True),
    sa.Column('source_project_id', sa.UUID(), nullable=True),
    sa.Column('source_version', sa.Integer(), nullable=True),
    sa.Column('s3_key', sa.String(), nullable=False),
    sa.Column('source_text', sa.Text(), nullable=False),
    sa.Column('use_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['source_project_id'], ['translation_projects.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('team_id', 'doc_key', 'target_language', name='uq_template_team_key_lang')
    )
    op.create_index(op.f('ix_document_templates_doc_key'), 'document_templates', ['doc_key'], unique=False)
    op.create_index(op.f('ix_document_templates_team_id'), 'document_templates', ['team_id'], unique=False)

    op.create_table('pending_learning',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('block_id', sa.String(), nullable=True),
    sa.Column('before_text', sa.Text(), nullable=False),
    sa.Column('after_text', sa.Text(), nullable=False),
    sa.Column('origin', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('claimed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['translation_projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pending_learning_project_id'), 'pending_learning', ['project_id'], unique=False)

    op.add_column('translation_projects', sa.Column('doc_profile', sa.JSON(), nullable=True))
    op.add_column('translation_projects', sa.Column('doc_key', sa.String(), nullable=True))
    op.add_column('translation_projects', sa.Column('template_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_translation_projects_doc_key'), 'translation_projects', ['doc_key'], unique=False)
    op.create_foreign_key(
        'fk_translation_projects_template_id', 'translation_projects', 'document_templates',
        ['template_id'], ['id'], ondelete='SET NULL',
    )

    op.add_column('glossary', sa.Column('origin', sa.String(), server_default='manual', nullable=False))
    op.add_column('glossary', sa.Column('confidence', sa.Float(), nullable=True))
    op.add_column('glossary', sa.Column('learned_from_project_id', sa.UUID(), nullable=True))
    op.add_column('glossary', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.create_foreign_key(
        'fk_glossary_learned_from_project_id', 'glossary', 'translation_projects',
        ['learned_from_project_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_glossary_learned_from_project_id', 'glossary', type_='foreignkey')
    op.drop_column('glossary', 'created_at')
    op.drop_column('glossary', 'learned_from_project_id')
    op.drop_column('glossary', 'confidence')
    op.drop_column('glossary', 'origin')
    op.drop_constraint('fk_translation_projects_template_id', 'translation_projects', type_='foreignkey')
    op.drop_index(op.f('ix_translation_projects_doc_key'), table_name='translation_projects')
    op.drop_column('translation_projects', 'template_id')
    op.drop_column('translation_projects', 'doc_key')
    op.drop_column('translation_projects', 'doc_profile')
    op.drop_index(op.f('ix_pending_learning_project_id'), table_name='pending_learning')
    op.drop_table('pending_learning')
    op.drop_index(op.f('ix_document_templates_team_id'), table_name='document_templates')
    op.drop_index(op.f('ix_document_templates_doc_key'), table_name='document_templates')
    op.drop_table('document_templates')
