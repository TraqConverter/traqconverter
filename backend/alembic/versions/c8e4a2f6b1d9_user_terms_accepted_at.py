"""when a user accepted the Terms of Service at registration

Revision ID: c8e4a2f6b1d9
Revises: f6c2a8d4e0b7
Create Date: 2026-10-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8e4a2f6b1d9'
down_revision: Union[str, Sequence[str], None] = 'f6c2a8d4e0b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: accounts created before the checkbox existed have no record.
    op.add_column('users', sa.Column('terms_accepted_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'terms_accepted_at')
