"""add team_id to translation_projects

Revision ID: 1d9b898d3c60
Revises: 74eeb32a869f
Create Date: 2026-03-05 20:41:20.963605
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = "1d9b898d3c60"
down_revision: Union[str, Sequence[str], None] = "74eeb32a869f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Add column as nullable to avoid failing on existing rows
    op.add_column(
        "translation_projects",
        sa.Column("team_id", sa.UUID(), nullable=True),
    )

    # Add foreign key constraint
    op.create_foreign_key(
        "fk_translation_projects_team",
        "translation_projects",
        "teams",
        ["team_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_constraint(
        "fk_translation_projects_team",
        "translation_projects",
        type_="foreignkey",
    )

    op.drop_column("translation_projects", "team_id")