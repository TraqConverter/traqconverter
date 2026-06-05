"""add use_tm and apply_glossary toggles to translation_projects

Revision ID: b91f02d7c4e8
Revises: e5f9d2a18b34
Create Date: 2026-05-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b91f02d7c4e8"
down_revision: Union[str, Sequence[str], None] = "e5f9d2a18b34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add two boolean columns matching the New project page toggles.
    # Existing rows default to True so behaviour stays the same for
    # projects uploaded before this migration ran.
    op.add_column(
        "translation_projects",
        sa.Column(
            "use_tm",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "translation_projects",
        sa.Column(
            "apply_glossary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("translation_projects", "apply_glossary")
    op.drop_column("translation_projects", "use_tm")
