"""A client can leave an email on "I've paid" to hear when the document is ready; cleared once used.

Revision ID: e6a8c0d2f4b7
Revises: d5f7b9c1e3a6
"""
import sqlalchemy as sa
from alembic import op

revision = "e6a8c0d2f4b7"
down_revision = "d5f7b9c1e3a6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("delivery_links", sa.Column("client_email", sa.String(320), nullable=True))


def downgrade():
    op.drop_column("delivery_links", "client_email")
