"""add stripe event log table

Revision ID: 222add5ba6b6
Revises: <1e37687d1d8f>
Create Date: 2026-02-24 22:13:50.796554

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '222add5ba6b6'
down_revision: Union[str, Sequence[str], None] = '1e37687d1d8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

def downgrade():
    op.drop_table("stripe_events")