"""onboarding_emails: which onboarding emails each trial sign-up has had.

Every user who exists now gets a row with every email marked sent, so the
deploy sends nobody a backlog.

Revision ID: b2d4f6a8c1e3
Revises: f7b9d1e3a5c8
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b2d4f6a8c1e3"
down_revision = "f7b9d1e3a5c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboarding_emails",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("signed_up_at", sa.DateTime(), nullable=False),
        sa.Column("welcome_sent_at", sa.DateTime(), nullable=True),
        sa.Column("nudge_sent_at", sa.DateTime(), nullable=True),
        sa.Column("last_chance_sent_at", sa.DateTime(), nullable=True),
        sa.Column("trial_ended_sent_at", sa.DateTime(), nullable=True),
        sa.Column("unsubscribed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_onboarding_emails_signed_up_at", "onboarding_emails", ["signed_up_at"])
    op.execute(
        """
        INSERT INTO onboarding_emails (
            user_id, signed_up_at, welcome_sent_at, nudge_sent_at, last_chance_sent_at, trial_ended_sent_at
        )
        SELECT id, COALESCE(terms_accepted_at, now() AT TIME ZONE 'utc'),
               now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc',
               now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc'
        FROM users
        """
    )


def downgrade() -> None:
    op.drop_index("ix_onboarding_emails_signed_up_at", table_name="onboarding_emails")
    op.drop_table("onboarding_emails")
