"""rename glossary.user_id → team_id (audit HIGH-2)

Revision ID: e5f9d2a18b34
Revises: d3a7c1b8f9e2
Create Date: 2026-05-04 14:00:00.000000

The glossary table had a column literally named `user_id` whose FK
pointed at `teams.id`. The router stored `current_user.id` into it; the
AI worker queried it with a team id. Result: terms a user created were
never reachable by the translator (audit HIGH-2).

This migration adds a properly-named `team_id` column, backfills it from
the team a user owns, then drops the misnamed `user_id` column. Rows
that can't be mapped to a team (e.g. orphan terms) are removed because
they were never reachable in the first place.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "e5f9d2a18b34"
down_revision: Union[str, Sequence[str], None] = "d3a7c1b8f9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = {c["name"] for c in inspector.get_columns("glossary")}

    if "team_id" not in cols:
        op.add_column(
            "glossary",
            sa.Column(
                "team_id",
                sa.UUID(),
                sa.ForeignKey("teams.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )

    # Backfill: copy `user_id` (which actually held team ids in some
    # rows) directly when it matches a real team id; otherwise look up
    # the team owned by that user. We do both passes to be safe.
    if "user_id" in cols:
        op.execute(
            """
            UPDATE glossary g
               SET team_id = g.user_id
             WHERE g.team_id IS NULL
               AND g.user_id IN (SELECT id FROM teams)
            """
        )
        op.execute(
            """
            UPDATE glossary g
               SET team_id = t.id
              FROM teams t
             WHERE g.team_id IS NULL
               AND g.user_id = t.owner_id
            """
        )

        # Drop any row we still couldn't reconcile — it was unreachable
        # anyway because the AI worker filters by team.
        op.execute("DELETE FROM glossary WHERE team_id IS NULL")

        # Now make team_id NOT NULL and remove the misnamed column.
        op.alter_column("glossary", "team_id", nullable=False)
        op.drop_column("glossary", "user_id")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = {c["name"] for c in inspector.get_columns("glossary")}

    if "user_id" not in cols:
        op.add_column(
            "glossary",
            sa.Column(
                "user_id",
                sa.UUID(),
                sa.ForeignKey("teams.id"),
                nullable=True,
            ),
        )
    if "team_id" in cols:
        op.execute("UPDATE glossary SET user_id = team_id")
        op.alter_column("glossary", "user_id", nullable=False)
        op.drop_column("glossary", "team_id")
