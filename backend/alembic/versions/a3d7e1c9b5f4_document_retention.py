"""projects record when their retention period starts, so files can be deleted after DOCUMENT_RETENTION_DAYS

Revision ID: a3d7e1c9b5f4
Revises: e9a3c5b7d1f2
Create Date: 2026-10-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3d7e1c9b5f4'
down_revision: Union[str, Sequence[str], None] = 'e9a3c5b7d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('translation_projects', sa.Column('retention_from', sa.DateTime(), nullable=True))
    op.create_index('ix_translation_projects_retention_from', 'translation_projects', ['retention_from'])
    # Grace period: projects that exist before automatic deletion start their 90 days from this deploy.
    op.execute("UPDATE translation_projects SET retention_from = (now() AT TIME ZONE 'utc')")


def downgrade() -> None:
    op.drop_index('ix_translation_projects_retention_from', table_name='translation_projects')
    op.drop_column('translation_projects', 'retention_from')
