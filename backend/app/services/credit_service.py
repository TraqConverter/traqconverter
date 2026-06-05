from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime

from app.models.credit import CreditWallet, CreditTransaction


# ============================================================
# DOMAIN EXCEPTIONS (NO HTTP HERE)
# ============================================================

class WalletNotFoundError(Exception):
    pass


class InsufficientCreditsError(Exception):
    pass


class DuplicateTransactionError(Exception):
    pass


# ============================================================
# CREDIT SERVICE (DUAL BUCKET)
# ============================================================

class CreditService:

    @staticmethod
    def deduct_credits(
        db: Session,
        team_id: str,
        amount: int,
        reference_id: str | None = None,
    ) -> int:
        """
         FIXED:

        - Single source of truth
        - Subscription expiry handled here
        - Idempotency via reference_id
        - Row-level locking
        - No commit inside service

        Returns remaining total credits.
        """

        wallet = (
            db.query(CreditWallet)
            .filter(CreditWallet.team_id == team_id)
            .with_for_update()
            .first()
        )

        if not wallet:
            raise WalletNotFoundError("Credit wallet not found")

        # ====================================================
        # HANDLE SUBSCRIPTION EXPIRY (MOVED HERE)
        # ====================================================
        now = datetime.utcnow()

        if (
            wallet.subscription_status == "ACTIVE"
            and wallet.subscription_expires_at
            and wallet.subscription_expires_at < now
        ):
            wallet.subscription_status = "EXPIRED"
            wallet.subscription_credits = 0

        # ====================================================
        # IDEMPOTENCY CHECK
        # ====================================================
        if reference_id:
            existing = (
                db.query(CreditTransaction)
                .filter(CreditTransaction.reference_id == reference_id)
                .first()
            )

            if existing:
                raise DuplicateTransactionError("Duplicate credit transaction")

        # ====================================================
        # CHECK BALANCE
        # ====================================================
        total_available = wallet.subscription_credits + wallet.purchased_credits

        if total_available < amount:
            raise InsufficientCreditsError("Insufficient credits")

        remaining = amount

        # ====================================================
        # DEDUCT SUBSCRIPTION FIRST (ACTIVE *or* TRIAL).
        # The expiry handler above already zeroes subscription_credits
        # for expired subs, so any positive balance here is spendable.
        # Previously this only matched "ACTIVE", which crashed TRIAL
        # users with "Credit integrity violation" because the deduction
        # fell through to purchased_credits (which is 0).
        # ====================================================
        if wallet.subscription_status in ("ACTIVE", "TRIAL"):
            if wallet.subscription_credits >= remaining:
                wallet.subscription_credits -= remaining
                remaining = 0
            else:
                remaining -= wallet.subscription_credits
                wallet.subscription_credits = 0

        # ====================================================
        # DEDUCT PURCHASED
        # ====================================================
        if remaining > 0:
            wallet.purchased_credits -= remaining

        # ====================================================
        # SAFETY CHECK
        # ====================================================
        if wallet.subscription_credits < 0 or wallet.purchased_credits < 0:
            raise Exception("Credit integrity violation")

        # ====================================================
        # 🧾 LOG TRANSACTION
        # ====================================================
        transaction = CreditTransaction(
            wallet_id=wallet.id,
            type="USAGE",
            amount=-amount,
            reference_id=reference_id,
        )

        db.add(transaction)

        return wallet.subscription_credits + wallet.purchased_credits

    # ========================================================
    # MONTHLY GRANT
    # ========================================================

    @staticmethod
    def grant_subscription_credits(
        db: Session,
        team_id: str,
        amount: int,
    ) -> None:

        wallet = (
            db.query(CreditWallet)
            .filter(CreditWallet.team_id == team_id)
            .with_for_update()
            .first()
        )

        if not wallet:
            raise WalletNotFoundError("Credit wallet not found")

        wallet.subscription_credits = amount

        transaction = CreditTransaction(
            wallet_id=wallet.id,
            type="SUBSCRIPTION_GRANT",
            amount=amount,
        )

        db.add(transaction)

    # ========================================================
    # ONE-TIME PURCHASE
    # ========================================================

    @staticmethod
    def grant_purchased_credits(
        db: Session,
        team_id: str,
        amount: int,
    ) -> None:

        wallet = (
            db.query(CreditWallet)
            .filter(CreditWallet.team_id == team_id)
            .with_for_update()
            .first()
        )

        if not wallet:
            raise WalletNotFoundError("Credit wallet not found")

        wallet.purchased_credits += amount

        transaction = CreditTransaction(
            wallet_id=wallet.id,
            type="PURCHASE",
            amount=amount,
        )

        db.add(transaction)