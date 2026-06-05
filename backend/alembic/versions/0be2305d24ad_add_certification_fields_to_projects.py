"""add certification fields to projects

Revision ID: 0be2305d24ad
Revises: 957adc0f8c39
Create Date: 2026-02-27 21:17:37.927957

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0be2305d24ad'
down_revision: Union[str, Sequence[str], None] = '957adc0f8c39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1. Add column as nullable first
    op.add_column(
        'translation_projects',
        sa.Column('add_certification', sa.Boolean(), nullable=True)
    )

    op.add_column(
        'translation_projects',
        sa.Column('source_language', sa.String(), nullable=True)
    )

    op.add_column(
        'translation_projects',
        sa.Column('target_language', sa.String(), nullable=True)
    )

    op.add_column(
        'translation_projects',
        sa.Column('certification_override_text', sa.String(), nullable=True)
    )

    # 2. Backfill existing rows
    op.execute(
        "UPDATE translation_projects SET add_certification = FALSE WHERE add_certification IS NULL"
    )

    # 3. Enforce NOT NULL
    op.alter_column(
        'translation_projects',
        'add_certification',
        nullable=False
    )


def downgrade():
    op.drop_column('translation_projects', 'certification_override_text')
    op.drop_column('translation_projects', 'target_language')
    op.drop_column('translation_projects', 'source_language')
    op.drop_column('translation_projects', 'add_certification')