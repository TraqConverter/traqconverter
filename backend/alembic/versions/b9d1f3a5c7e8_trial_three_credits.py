"""running trials get the new 3-credit allowance, with a ledger row

Revision ID: b9d1f3a5c7e8
Revises: a7c3e9f1b5d2
Create Date: 2026-10-01 10:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b9d1f3a5c7e8'
down_revision: Union[str, Sequence[str], None] = 'a7c3e9f1b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Fixed here, not TRIAL_CREDITS, so a later change to the trial doesn't rewrite this step.
TARGET = 3


def upgrade() -> None:
    from app.services.credit_service import top_up_trial_wallets

    top_up_trial_wallets(op.get_bind(), TARGET)


def downgrade() -> None:
    # Credits already granted (and possibly spent) are left alone.
    pass
