"""document versions for editor

Revision ID: b5d1f8a2c6e3
Revises: a3c9e5f1b702
Create Date: 2026-09-28 20:32:45.618902

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5d1f8a2c6e3'
down_revision: Union[str, Sequence[str], None] = 'a3c9e5f1b702'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('document_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('s3_key', sa.String(), nullable=False),
    sa.Column('note', sa.String(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['translation_projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'version', name='uq_document_version')
    )
    op.create_index(op.f('ix_document_versions_project_id'), 'document_versions', ['project_id'], unique=False)
    op.add_column('translation_projects', sa.Column('document_version', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('translation_projects', 'document_version')
    op.drop_index(op.f('ix_document_versions_project_id'), table_name='document_versions')
    op.drop_table('document_versions')
