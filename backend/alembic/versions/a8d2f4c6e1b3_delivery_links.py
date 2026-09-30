"""delivery links: client download links to a snapshot of an export

Revision ID: a8d2f4c6e1b3
Revises: c5e7a9b1d3f2
Create Date: 2026-09-30 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8d2f4c6e1b3'
down_revision: Union[str, Sequence[str], None] = 'c5e7a9b1d3f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('delivery_links',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('token_prefix', sa.String(length=12), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('file_name', sa.String(), nullable=False),
    sa.Column('file_key', sa.String(), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('download_count', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('last_downloaded_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['translation_projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_delivery_links_project_id'), 'delivery_links', ['project_id'], unique=False)
    op.create_index(op.f('ix_delivery_links_token_hash'), 'delivery_links', ['token_hash'], unique=True)
    op.create_index(op.f('ix_delivery_links_expires_at'), 'delivery_links', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_delivery_links_expires_at'), table_name='delivery_links')
    op.drop_index(op.f('ix_delivery_links_token_hash'), table_name='delivery_links')
    op.drop_index(op.f('ix_delivery_links_project_id'), table_name='delivery_links')
    op.drop_table('delivery_links')
