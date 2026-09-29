"""merge review states

Revision ID: 2c7e9a1f4b6d
Revises: 9b1d4f6a2c8e, a5c3e7b9d1f4
Create Date: 2026-09-29 13:59:49.028712

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c7e9a1f4b6d'
down_revision: Union[str, Sequence[str], None] = ('9b1d4f6a2c8e', 'a5c3e7b9d1f4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
