"""team invite token

Revision ID: f2b8d3e6a117
Revises: e1a4c7b2d905
Create Date: 2026-09-25 16:33:21.004121

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b8d3e6a117'
down_revision: Union[str, Sequence[str], None] = 'e1a4c7b2d905'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('team_invites', sa.Column('token', sa.String(), nullable=True))
    op.create_index(op.f('ix_team_invites_token'), 'team_invites', ['token'], unique=True)
    op.execute("UPDATE team_invites SET token = replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', '') WHERE token IS NULL")


def downgrade() -> None:
    op.drop_index(op.f('ix_team_invites_token'), table_name='team_invites')
    op.drop_column('team_invites', 'token')
