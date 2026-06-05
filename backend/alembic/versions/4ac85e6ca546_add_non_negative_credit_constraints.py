from alembic import op
import sqlalchemy as sa

revision = "4ac85e6ca546"
down_revision = "4f778f2bdc59"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "check_subscription_credits_non_negative",
        "credit_wallets",
        "subscription_credits >= 0"
    )

    op.create_check_constraint(
        "check_purchased_credits_non_negative",
        "credit_wallets",
        "purchased_credits >= 0"
    )


def downgrade():
    op.drop_constraint(
        "check_subscription_credits_non_negative",
        "credit_wallets",
        type_="check"
    )

    op.drop_constraint(
        "check_purchased_credits_non_negative",
        "credit_wallets",
        type_="check"
    )