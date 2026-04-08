"""add resolved to segment comments (clean)

Revision ID: f398cbd7a314
Revises: 64f6e357d117
Create Date: 2026-04-08
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'f398cbd7a314'
down_revision = '64f6e357d117'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'segment_comments',
        sa.Column('resolved', sa.Boolean(), nullable=True)
    )


def downgrade():
    op.drop_column('segment_comments', 'resolved')