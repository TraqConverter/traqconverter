"""remove quote fields from translation project

Revision ID: 7d4fb1844c08
Revises: ac0f4428d1b0
Create Date: 2026-02-22 13:15:22.843611
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '7d4fb1844c08'
down_revision: Union[str, Sequence[str], None] = 'ac0f4428d1b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1️⃣ Drop quote column
    op.drop_column('translation_projects', 'is_quote_request')

    # 2️⃣ Normalize old statuses
    op.execute(
        text(
            "UPDATE translation_projects "
            "SET status = 'PROCESSING' "
            "WHERE status IN ('QUOTE_REQUESTED', 'IN_PROGRESS', 'DRAFT')"
        )
    )


def downgrade() -> None:
    op.add_column(
        'translation_projects',
        sa.Column('is_quote_request', sa.Boolean(), nullable=True)
    )