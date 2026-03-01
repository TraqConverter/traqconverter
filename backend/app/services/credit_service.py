from sqlalchemy.orm import Session
from app.models.credit import CreditWallet, CreditTransaction


# ============================================================
# DOMAIN EXCEPTIONS (NO HTTP HERE)
# ============================================================

class WalletNotFoundError(Exception):
    pass


class InsufficientCreditsError(Exception):
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
        Atomic dual-bucket deduction.

        - Row-level locking
        - Subscription credits deducted first
        - Purchased credits second
        - No commit inside service
        - Logs transaction
        - Raises domain exceptions

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

        total_available = wallet.subscription_credits + wallet.purchased_credits

        if total_available < amount:
            raise InsufficientCreditsError("Insufficient credits")

        remaining = amount

        # ----------------------------------------------------
        # Deduct subscription credits first
        # ----------------------------------------------------
        if wallet.subscription_credits >= remaining:
            wallet.subscription_credits -= remaining
            remaining = 0
        else:
            remaining -= wallet.subscription_credits
            wallet.subscription_credits = 0

        # ----------------------------------------------------
        # Deduct purchased credits
        # ----------------------------------------------------
        if remaining > 0:
            wallet.purchased_credits -= remaining

        # ----------------------------------------------------
        # Log transaction
        # ----------------------------------------------------
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
        """
        Grants subscription credits.
        Resets subscription bucket.
        """

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
        """
        Adds purchased credits (non-expiring).
        """

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