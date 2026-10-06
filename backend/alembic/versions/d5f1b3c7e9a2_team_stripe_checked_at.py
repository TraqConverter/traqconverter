"""teams record when Stripe was last asked for their Connect account's status

Revision ID: d5f1b3c7e9a2
Revises: c2e6a8f0b4d1
Create Date: 2026-10-06 14:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5f1b3c7e9a2'
down_revision: Union[str, Sequence[str], None] = 'c2e6a8f0b4d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('teams', sa.Column('stripe_account_checked_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('teams', 'stripe_account_checked_at')
