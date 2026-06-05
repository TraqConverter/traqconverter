"""add subscription_plan to users

Revision ID: aa8244316aec
Revises: 4cb9ce58d139
Create Date: 2026-02-21 12:00:47.542073
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'aa8244316aec'
down_revision: Union[str, Sequence[str], None] = '4cb9ce58d139'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add subscription_plan column with DB-level default
    op.add_column(
        "users",
        sa.Column(
            "subscription_plan",
            sa.String(),
            nullable=False,
            server_default="BASIC"
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "subscription_plan")