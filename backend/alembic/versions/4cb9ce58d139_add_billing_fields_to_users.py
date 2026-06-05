"""add billing fields to users

Revision ID: 4cb9ce58d139
Revises: b34ab420b451
Create Date: 2026-02-20 21:20:04.490087

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4cb9ce58d139'
down_revision: Union[str, Sequence[str], None] = 'b34ab420b451'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('subscription_status', sa.String(), nullable=True))
    op.add_column('users', sa.Column('stripe_customer_id', sa.String(), nullable=True))
    op.add_column('users', sa.Column('stripe_subscription_id', sa.String(), nullable=True))
    op.add_column('users', sa.Column('monthly_credits', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('extra_credits', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('subscription_current_period_end', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'subscription_current_period_end')
    op.drop_column('users', 'extra_credits')
    op.drop_column('users', 'monthly_credits')
    op.drop_column('users', 'stripe_subscription_id')
    op.drop_column('users', 'stripe_customer_id')
    op.drop_column('users', 'subscription_status')