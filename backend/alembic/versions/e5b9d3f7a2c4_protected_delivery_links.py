"""protected client links: pay-to-unlock fields on delivery links, PayPal.me handle on teams

Revision ID: e5b9d3f7a2c4
Revises: c8e4a2f6b1d9
Create Date: 2026-10-01 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e5b9d3f7a2c4'
down_revision: Union[str, Sequence[str], None] = 'c8e4a2f6b1d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('teams', sa.Column('paypal_me', sa.String(length=20), nullable=True))

    op.add_column('delivery_links', sa.Column('protected', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('delivery_links', sa.Column('amount_cents', sa.Integer(), nullable=True))
    op.add_column('delivery_links', sa.Column('currency', sa.String(length=3), server_default='EUR', nullable=False))
    op.add_column('delivery_links', sa.Column('client_name', sa.String(length=120), nullable=True))
    op.add_column('delivery_links', sa.Column('paid_claimed_at', sa.DateTime(), nullable=True))
    op.add_column('delivery_links', sa.Column('unlocked_at', sa.DateTime(), nullable=True))
    op.add_column('delivery_links', sa.Column('unlocked_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_delivery_links_unlocked_by', 'delivery_links', 'users', ['unlocked_by'], ['id'], ondelete='SET NULL'
    )
    op.add_column('delivery_links', sa.Column('preview_pages', sa.Integer(), nullable=True))
    op.add_column('delivery_links', sa.Column('original_pages', sa.Integer(), nullable=True))
    op.add_column('delivery_links', sa.Column('preview_keys', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('delivery_links', 'preview_keys')
    op.drop_column('delivery_links', 'original_pages')
    op.drop_column('delivery_links', 'preview_pages')
    op.drop_constraint('fk_delivery_links_unlocked_by', 'delivery_links', type_='foreignkey')
    op.drop_column('delivery_links', 'unlocked_by')
    op.drop_column('delivery_links', 'unlocked_at')
    op.drop_column('delivery_links', 'paid_claimed_at')
    op.drop_column('delivery_links', 'client_name')
    op.drop_column('delivery_links', 'currency')
    op.drop_column('delivery_links', 'amount_cents')
    op.drop_column('delivery_links', 'protected')
    op.drop_column('teams', 'paypal_me')
