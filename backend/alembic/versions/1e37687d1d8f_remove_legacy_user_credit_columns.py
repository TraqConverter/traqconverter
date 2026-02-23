from alembic import op
import sqlalchemy as sa

revision = "<1e37687d1d8f>"
down_revision = "<4ac85e6ca546>"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("users", "monthly_credits")
    op.drop_column("users", "extra_credits")


def downgrade():
    op.add_column("users", sa.Column("monthly_credits", sa.Integer(), default=0))
    op.add_column("users", sa.Column("extra_credits", sa.Integer(), default=0))