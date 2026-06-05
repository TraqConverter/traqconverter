"""add per-user logo_s3_key

Revision ID: c427fe1382bd
Revises: b91f02d7c4e8
Create Date: 2026-05-18 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c427fe1382bd"
down_revision: Union[str, Sequence[str], None] = "b91f02d7c4e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("logo_s3_key", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "logo_s3_key")
