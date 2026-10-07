"""teams keep stamps, logos and signatures in a media library, picked by target language

Revision ID: e9a3c5b7d1f2
Revises: b7e3d9f1a5c2
Create Date: 2026-10-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e9a3c5b7d1f2'
down_revision: Union[str, Sequence[str], None] = 'b7e3d9f1a5c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'media_assets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('uploaded_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('language', sa.String(length=8), nullable=True),
        sa.Column('s3_key', sa.String(), nullable=False),
        sa.Column('mime_type', sa.String(length=40), nullable=True),
        sa.Column('width_px', sa.Integer(), nullable=True),
        sa.Column('height_px', sa.Integer(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('auto_use', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('stamp', 'logo', 'signature', 'other')", name='ck_media_assets_kind'),
    )
    op.create_index('ix_media_assets_team_id', 'media_assets', ['team_id'])
    op.execute(
        "CREATE UNIQUE INDEX uq_media_assets_auto_use ON media_assets (team_id, kind, coalesce(language, ''))"
        " WHERE auto_use"
    )

    from app.services.media_library import backfill_from_settings

    backfill_from_settings(op.get_bind())


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_media_assets_auto_use")
    op.drop_index('ix_media_assets_team_id', table_name='media_assets')
    op.drop_table('media_assets')
