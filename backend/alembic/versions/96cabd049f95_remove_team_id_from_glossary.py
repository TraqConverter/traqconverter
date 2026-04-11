"""remove team_id from glossary

Revision ID: 96cabd049f95
Revises: 84606b9e4c17
Create Date: 2026-04-11 17:13:04.978006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '96cabd049f95'
down_revision: Union[str, Sequence[str], None] = '84606b9e4c17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.drop_column("glossary", "team_id")

def downgrade():
    pass
