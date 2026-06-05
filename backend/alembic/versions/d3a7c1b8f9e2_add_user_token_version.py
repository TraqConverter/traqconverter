"""add token_version column to users for JWT revocation

Revision ID: d3a7c1b8f9e2
Revises: c2f8a91e6b35
Create Date: 2026-05-04 12:00:00.000000

Audit CRIT-8 fix. Each user gets a monotonically-increasing
`token_version`. The version is embedded in every JWT we issue and
validated on every request. Bumping the column (e.g. on password change)
instantly invalidates every previously-issued token for that user.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "d3a7c1b8f9e2"
down_revision: Union[str, Sequence[str], None] = "c2f8a91e6b35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "token_version" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "token_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "token_version" in cols:
        op.drop_column("users", "token_version")
