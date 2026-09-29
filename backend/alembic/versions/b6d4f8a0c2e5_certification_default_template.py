"""team default certification template

Revision ID: b6d4f8a0c2e5
Revises: 2c7e9a1f4b6d
Create Date: 2026-09-29 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b6d4f8a0c2e5'
down_revision: Union[str, Sequence[str], None] = '2c7e9a1f4b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('certifications', sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index(
        'uq_certifications_team_default', 'certifications', ['team_id'], unique=True,
        postgresql_where=sa.text('is_default'),
    )


def downgrade() -> None:
    op.drop_index('uq_certifications_team_default', table_name='certifications')
    op.drop_column('certifications', 'is_default')
