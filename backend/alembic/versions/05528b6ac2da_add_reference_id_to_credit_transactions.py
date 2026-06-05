"""add reference_id and created_at to credit_transactions"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '05528b6ac2da'
down_revision: Union[str, Sequence[str], None] = '67cdf998ac83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'credit_transactions',
        sa.Column('reference_id', sa.String(), nullable=True)
    )

    op.add_column(
        'credit_transactions',
        sa.Column('created_at', sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('credit_transactions', 'created_at')
    op.drop_column('credit_transactions', 'reference_id')