"""merge metering and batches

Revision ID: 9b1d4f6a2c8e
Revises: e3a1c5f7b9d2, f4b2d6a8c0e3
Create Date: 2026-09-29 13:43:12.686735

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b1d4f6a2c8e'
down_revision: Union[str, Sequence[str], None] = ('e3a1c5f7b9d2', 'f4b2d6a8c0e3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
