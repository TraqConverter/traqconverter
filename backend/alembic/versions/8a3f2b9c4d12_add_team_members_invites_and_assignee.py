"""add team_members, team_invites tables and assignee_id on translation_projects

Revision ID: 8a3f2b9c4d12
Revises: 7c1e9d2f4a31
Create Date: 2026-04-29 12:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "8a3f2b9c4d12"
down_revision: Union[str, Sequence[str], None] = "7c1e9d2f4a31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    existing_tables = set(inspector.get_table_names())

    # ============================================================
    # team_members — links users to teams with a role
    # ============================================================
    if "team_members" not in existing_tables:
        op.create_table(
            "team_members",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column(
                "team_id",
                sa.UUID(),
                sa.ForeignKey("teams.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.UUID(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(), nullable=False, server_default="MEMBER"),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("team_id", "user_id", name="uq_team_member"),
        )

    # ============================================================
    # team_invites — pending email invitations
    # ============================================================
    if "team_invites" not in existing_tables:
        op.create_table(
            "team_invites",
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column(
                "team_id",
                sa.UUID(),
                sa.ForeignKey("teams.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("email", sa.String(), nullable=False, index=True),
            sa.Column("role", sa.String(), nullable=False, server_default="MEMBER"),
            sa.Column(
                "status",
                sa.String(),
                nullable=False,
                server_default="PENDING",
            ),
            sa.Column(
                "invited_by",
                sa.UUID(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "idx_team_invites_email_status",
            "team_invites",
            ["email", "status"],
        )

    # ============================================================
    # translation_projects.assignee_id
    # ============================================================
    project_cols = {c["name"] for c in inspector.get_columns("translation_projects")}
    if "assignee_id" not in project_cols:
        op.add_column(
            "translation_projects",
            sa.Column(
                "assignee_id",
                sa.UUID(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    project_cols = {c["name"] for c in inspector.get_columns("translation_projects")}
    if "assignee_id" in project_cols:
        op.drop_column("translation_projects", "assignee_id")

    if "team_invites" in inspector.get_table_names():
        op.drop_index("idx_team_invites_email_status", table_name="team_invites")
        op.drop_table("team_invites")

    if "team_members" in inspector.get_table_names():
        op.drop_table("team_members")
