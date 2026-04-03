"""add model field

Revision ID: e98f8ca75e5c
Revises: add_segment_comments
Create Date: 2026-04-03 09:06:07.619704

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e98f8ca75e5c'
down_revision: Union[str, Sequence[str], None] = 'add_segment_comments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column(
        'translation_projects',
        sa.Column('model', sa.String(), nullable=False, server_default='balanced')
    )

def downgrade():
    op.drop_column('translation_projects', 'model')