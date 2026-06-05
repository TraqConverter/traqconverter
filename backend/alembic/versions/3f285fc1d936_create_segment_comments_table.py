"""create segment comments table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "add_segment_comments"
down_revision = "20d6e44f5a81"
branch_labels = None
depends_on = None


def upgrade():

    op.execute("""
        CREATE TABLE IF NOT EXISTS segment_comments (
            id UUID PRIMARY KEY,
            segment_id UUID NOT NULL REFERENCES translation_segments(id),
            user_id UUID NOT NULL REFERENCES users(id),
            comment TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT now()
        )
    """)


def downgrade():

    op.execute("""
        DROP TABLE IF EXISTS segment_comments
    """)