"""add segment comments (clean)

Revision ID: 64f6e357d117
Revises: e98f8ca75e5c
Create Date: 2026-04-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '64f6e357d117'
down_revision = 'e98f8ca75e5c'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add column as nullable
    op.add_column(
        'segment_comments',
        sa.Column('text', sa.Text(), nullable=True)
    )

    # 2. Copy old data (if 'comment' column exists)
    op.execute("""
        UPDATE segment_comments
        SET text = comment
        WHERE text IS NULL
    """)

    # 3. Set NOT NULL after data is filled
    op.alter_column(
        'segment_comments',
        'text',
        nullable=False
    )

    # 4. Make user_id nullable
    op.alter_column(
        'segment_comments',
        'user_id',
        existing_type=postgresql.UUID(),
        nullable=True
    )

    # 5. Drop old column
    op.drop_column('segment_comments', 'comment')


def downgrade():
    op.add_column(
        'segment_comments',
        sa.Column('comment', sa.Text(), nullable=False)
    )

    op.alter_column(
        'segment_comments',
        'created_at',
        existing_type=sa.DateTime(),
        type_=postgresql.TIMESTAMP(timezone=True),
        existing_nullable=True
    )

    op.alter_column(
        'segment_comments',
        'user_id',
        existing_type=postgresql.UUID(),
        nullable=False
    )

    op.drop_column('segment_comments', 'text')