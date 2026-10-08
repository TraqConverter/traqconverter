"""per-account login lockout: failed attempts in the current window, and how long the account is refused

Revision ID: c4e6a8b0d2f5
Revises: a3d7e1c9b5f4
Create Date: 2026-10-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4e6a8b0d2f5'
down_revision: Union[str, Sequence[str], None] = 'a3d7e1c9b5f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('failed_login_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('failed_login_window_start', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('login_locked_until', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'login_locked_until')
    op.drop_column('users', 'failed_login_window_start')
    op.drop_column('users', 'failed_login_count')
