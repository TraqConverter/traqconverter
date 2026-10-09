"""When a client last opened Stripe Checkout on a delivery link.

Revision ID: f7b9d1e3a5c8
Revises: e6a8c0d2f4b7
"""
import sqlalchemy as sa
from alembic import op

revision = "f7b9d1e3a5c8"
down_revision = "e6a8c0d2f4b7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("delivery_links", sa.Column("checkout_started_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("delivery_links", "checkout_started_at")
