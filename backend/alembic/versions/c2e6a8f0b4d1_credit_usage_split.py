"""usage charges record how many credits came from the subscription and how many were purchased

Revision ID: c2e6a8f0b4d1
Revises: a2d6f8b0c4e7
Create Date: 2026-10-06 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c2e6a8f0b4d1'
down_revision: Union[str, Sequence[str], None] = 'a2d6f8b0c4e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('credit_transactions', sa.Column('from_subscription', sa.Integer(), nullable=True))
    op.add_column('credit_transactions', sa.Column('from_purchased', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('credit_transactions', 'from_purchased')
    op.drop_column('credit_transactions', 'from_subscription')
