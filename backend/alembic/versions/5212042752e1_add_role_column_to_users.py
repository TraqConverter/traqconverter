from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5212042752e1'
down_revision: Union[str, Sequence[str], None] = 'aa8244316aec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('role', sa.String(), nullable=False, server_default='USER')
    )


def downgrade() -> None:
    op.drop_column('users', 'role')