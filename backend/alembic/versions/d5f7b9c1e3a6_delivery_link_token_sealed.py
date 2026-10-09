"""Delivery links keep their token encrypted so the team can copy the link again.

Revision ID: d5f7b9c1e3a6
Revises: c4e6a8b0d2f5
"""
import sqlalchemy as sa
from alembic import op

revision = "d5f7b9c1e3a6"
down_revision = "c4e6a8b0d2f5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("delivery_links", sa.Column("token_sealed", sa.String(), nullable=True))


def downgrade():
    op.drop_column("delivery_links", "token_sealed")
