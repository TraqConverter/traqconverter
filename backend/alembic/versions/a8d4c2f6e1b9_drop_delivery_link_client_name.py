"""drop delivery_links.client_name: we don't store translators' clients' names

Revision ID: a8d4c2f6e1b9
Revises: b3f7d1e9c4a6
Create Date: 2026-10-01 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8d4c2f6e1b9'
down_revision: Union[str, Sequence[str], None] = 'b3f7d1e9c4a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('delivery_links', 'client_name')


def downgrade() -> None:
    op.add_column('delivery_links', sa.Column('client_name', sa.String(length=120), nullable=True))
