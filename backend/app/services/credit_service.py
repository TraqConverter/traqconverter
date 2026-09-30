from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime

from app.models.credit import CreditWallet, CreditTransaction






TRIAL_TOPUP_REFERENCE = "trial_topup:{target}"

_TOP_UP_TRIALS = text("""
    WITH due AS (
        SELECT w.id, :target - COALESCE(w.subscription_credits, 0) AS amount
          FROM credit_wallets w
         WHERE upper(w.plan_type) = 'TRIAL'
           AND (w.subscription_expires_at IS NULL OR w.subscription_expires_at > timezone('utc', now()))
           AND COALESCE(w.subscription_credits, 0) < :target
           AND NOT EXISTS (
               SELECT 1 FROM credit_transactions t WHERE t.wallet_id = w.id AND t.reference_id = :ref)
         FOR UPDATE OF w
    ), bumped AS (
        UPDATE credit_wallets w SET subscription_credits = :target FROM due WHERE w.id = due.id
    )
    INSERT INTO credit_transactions (id, wallet_id, type, amount, reference_id, created_at)
    SELECT gen_random_uuid(), due.id, 'TRIAL_GRANT', due.amount, :ref, timezone('utc', now()) FROM due
    RETURNING wallet_id
""")


def top_up_trial_wallets(bind, target: int) -> int:
    """Raise running trials below `target` credits to it, once per wallet, with a ledger row. Returns wallets topped up."""
    ref = TRIAL_TOPUP_REFERENCE.format(target=target)
    return len(bind.execute(_TOP_UP_TRIALS, {"target": target, "ref": ref}).fetchall())


class WalletNotFoundError(Exception):
    pass


class InsufficientCreditsError(Exception):
    pass


class DuplicateTransactionError(Exception):
    pass






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




        now = datetime.utcnow()

        if (
            wallet.subscription_status in ("ACTIVE", "TRIAL")
            and wallet.subscription_expires_at
            and wallet.subscription_expires_at < now
        ):
            wallet.subscription_status = "EXPIRED"
            wallet.subscription_credits = 0




        if reference_id:
            existing = (
                db.query(CreditTransaction)
                .filter(CreditTransaction.reference_id == reference_id)
                .first()
            )

            if existing:
                raise DuplicateTransactionError("Duplicate credit transaction")




        total_available = wallet.subscription_credits + wallet.purchased_credits

        if total_available < amount:
            raise InsufficientCreditsError("Insufficient credits")

        remaining = amount









        if wallet.subscription_status in ("ACTIVE", "TRIAL"):
            if wallet.subscription_credits >= remaining:
                wallet.subscription_credits -= remaining
                remaining = 0
            else:
                remaining -= wallet.subscription_credits
                wallet.subscription_credits = 0




        if remaining > 0:
            wallet.purchased_credits -= remaining




        if wallet.subscription_credits < 0 or wallet.purchased_credits < 0:
            raise Exception("Credit integrity violation")




        transaction = CreditTransaction(
            wallet_id=wallet.id,
            type="USAGE",
            amount=-amount,
            reference_id=reference_id,
        )

        db.add(transaction)

        return wallet.subscription_credits + wallet.purchased_credits





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

    @staticmethod
    def refund_usage(db: Session, reference_id: str, reason: str = "REFUND") -> int:
        """Reverse the USAGE transaction for reference_id once. Returns credits refunded."""
        usage = (
            db.query(CreditTransaction)
            .filter(
                CreditTransaction.reference_id == reference_id,
                CreditTransaction.type == "USAGE",
            )
            .first()
        )
        if not usage or not usage.amount:
            return 0
        # Lock first so two concurrent refunds serialise on the wallet row before the duplicate check.
        wallet = (
            db.query(CreditWallet)
            .filter(CreditWallet.id == usage.wallet_id)
            .with_for_update()
            .first()
        )
        if not wallet:
            return 0
        refund_ref = f"refund:{reference_id}"
        db.flush()
        if db.query(CreditTransaction).filter(CreditTransaction.reference_id == refund_ref).first():
            return 0
        amount = -usage.amount
        if wallet.subscription_status in ("ACTIVE", "TRIAL"):
            wallet.subscription_credits += amount
        else:
            wallet.purchased_credits += amount
        db.add(CreditTransaction(
            wallet_id=wallet.id,
            type=reason,
            amount=amount,
            reference_id=refund_ref,
        ))
        db.flush()
        return amount
