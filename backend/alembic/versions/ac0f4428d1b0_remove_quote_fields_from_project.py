"""remove quote fields from project

Revision ID: ac0f4428d1b0
Revises: 114fa455ba74
Create Date: 2026-02-22 13:12:00.386195

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ac0f4428d1b0'
down_revision: Union[str, Sequence[str], None] = '114fa455ba74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
