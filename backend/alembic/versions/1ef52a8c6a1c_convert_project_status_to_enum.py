from alembic import op
import sqlalchemy as sa


revision = "8f3c1d2e7abc"  # keep the generated revision id
down_revision = "222add5ba6b6"  # this must match your latest migration
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE TYPE project_status_enum AS ENUM ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')"
    )

    op.execute(
        """
        ALTER TABLE translation_projects
        ALTER COLUMN status
        TYPE project_status_enum
        USING status::project_status_enum
        """
    )


def downgrade():
    op.execute(
        """
        ALTER TABLE translation_projects
        ALTER COLUMN status
        TYPE VARCHAR
        """
    )

    op.execute("DROP TYPE project_status_enum")