"""stripe connect: each team's own Stripe account, and Stripe payments on protected links

Revision ID: b3f7d1e9c4a6
Revises: e5b9d3f7a2c4
Create Date: 2026-10-01 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f7d1e9c4a6'
down_revision: Union[str, Sequence[str], None] = 'e5b9d3f7a2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('teams', sa.Column('stripe_account_id', sa.String(length=255), nullable=True))
    op.add_column('teams', sa.Column('stripe_account_status', sa.String(length=20), nullable=True))
    op.create_unique_constraint('uq_teams_stripe_account_id', 'teams', ['stripe_account_id'])

    op.add_column('delivery_links', sa.Column('stripe_payment_intent', sa.String(length=255), nullable=True))
    op.add_column('delivery_links', sa.Column('paid_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('delivery_links', 'paid_at')
    op.drop_column('delivery_links', 'stripe_payment_intent')
    op.drop_constraint('uq_teams_stripe_account_id', 'teams', type_='unique')
    op.drop_column('teams', 'stripe_account_status')
    op.drop_column('teams', 'stripe_account_id')
