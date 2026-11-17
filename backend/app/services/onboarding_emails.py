"""Emails from Danilo to trial sign-ups: welcome, a 48h nudge, the day before the trial ends, the day after."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timedelta
from email.utils import formataddr, parseaddr
from html import escape
from typing import Optional

from sqlalchemy import or_, text, update
from sqlalchemy.orm import Session

from app.config import settings
from app.core.company import SUPPORT_EMAIL
from app.core.plan_features import CREDIT_PACKS, PLANS, TRIAL_CREDITS, payg_price_cents
from app.core.roles import is_staff
from app.models.credit import CreditTransaction, CreditWallet
from app.models.onboarding_email import OnboardingEmail
from app.models.project import TranslationProject
from app.models.team import Team
from app.models.user import User
from app.services import email_service

logger = logging.getLogger(__name__)

KINDS = ("welcome", "nudge", "last_chance", "trial_ended")
SENDER_NAME = "Danilo from OnlineDocTranslator"
TEST_EMAIL_PREFIX = "funnel-check+"

WELCOME_WITHIN = timedelta(hours=24)
NUDGE_AFTER = timedelta(hours=48)
# Past this, "a couple of days ago" stops being true and the nudge stays unsent.
NUDGE_UNTIL = timedelta(hours=96)
LAST_CHANCE_BEFORE = timedelta(hours=24)
TRIAL_ENDED_AFTER = timedelta(hours=24)
# Past this, a missed trial-ended email is stale and stays unsent.
TRIAL_ENDED_UNTIL = timedelta(hours=72)
WINDOW = timedelta(days=30)

RUN_EVERY = timedelta(hours=1)
BATCH = 200
# Any constant works; it only has to differ from other advisory locks taken on this database.
LOCK_KEY = 7_340_921_091

_last_run: Optional[datetime] = None


def enabled() -> bool:
    return bool(settings.ONBOARDING_EMAILS_ENABLED)


def start(db: Session, user: User) -> None:
    """Enrol a new trial sign-up; the caller commits."""
    db.add(OnboardingEmail(user_id=user.id, signed_up_at=datetime.utcnow()))


def _sign(user_hex: str) -> str:
    mac = hmac.new(settings.secret_key.encode(), f"onboarding-unsubscribe:{user_hex}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")


def unsubscribe_token(user_id) -> str:
    user_hex = uuid.UUID(str(user_id)).hex
    return f"{user_hex}.{_sign(user_hex)}"


def user_id_from_token(token: str) -> Optional[uuid.UUID]:
    user_hex, _, sig = (token or "").partition(".")
    try:
        user_id = uuid.UUID(hex=user_hex)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sign(user_id.hex)):
        return None
    return user_id


def unsubscribe(db: Session, user_id: uuid.UUID) -> bool:
    if db.query(User.id).filter(User.id == user_id).first() is None:
        return False
    row = db.query(OnboardingEmail).filter(OnboardingEmail.user_id == user_id).with_for_update().first()
    now = datetime.utcnow()
    if row is None:
        row = OnboardingEmail(user_id=user_id, signed_up_at=now)
        db.add(row)
    if row.unsubscribed_at is None:
        row.unsubscribed_at = now
    db.commit()
    return True


def _frontend(path: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}"


def _sender() -> Optional[str]:
    _, address = parseaddr(settings.RESEND_FROM_EMAIL or "")
    return formataddr((SENDER_NAME, address)) if address else None


def _euros(cents: int) -> str:
    return f"€{cents // 100}" if cents % 100 == 0 else f"€{cents / 100:.2f}"


def _first_name(user: User) -> Optional[str]:
    parts = (user.full_name or "").split()
    return parts[0] if parts else None


def _content(kind: str) -> tuple[str, list]:
    """Subject and body blocks: a str is a paragraph, a list is bullets, a tuple is a (label, url) button."""
    upload = ("Upload your first document", _frontend("/new-translation"))
    if kind == "welcome":
        return "Your first document on OnlineDocTranslator", [
            "I'm Danilo, I built OnlineDocTranslator. Thanks for signing up.",
            "The quickest way to see if it fits your work is to upload one real document.",
            upload,
            [
                f"Your trial includes {TRIAL_CREDITS} free pages.",
                "The translation keeps the layout of the original.",
                "You can download the result during the trial, with a watermark.",
            ],
            "Which language pair do you work in, and what kind of documents? Reply and tell me. I read every reply.",
        ]
    if kind == "nudge":
        return "Did something stop you?", [
            "You signed up a couple of days ago but haven't uploaded a document yet.",
            "Most translators start with a certificate or a diploma: one or two pages, and you see straight away whether the layout holds.",
            upload,
            "If something stopped you, reply and tell me what it was.",
        ]
    if kind == "last_chance":
        plan_from = min(p["price_eur"] for p in PLANS)
        pack = min(CREDIT_PACKS, key=lambda p: p["credits"])
        return "Your trial ends tomorrow", [
            "Your OnlineDocTranslator trial ends tomorrow.",
            "Your translation is in your projects, and you can download it now, with the trial watermark.",
            f"To keep going without the watermark, pick a plan (from €{plan_from}/month), "
            f"or buy a page pack and pay as you go, no subscription ({pack['credits']} pages for {_euros(payg_price_cents(pack))}).",
            ("See plans and page packs", _frontend("/billing")),
            "Questions? Reply to this email.",
        ]
    if kind == "trial_ended":
        return "Your trial ended", [
            "Your OnlineDocTranslator trial ended before you could try it.",
            "If you still want to see what it does with one of your documents, reply to this email and I'll reopen it.",
            "This is the last email I'll send you about it.",
        ]
    raise ValueError(kind)


_P = '<p style="margin:0 0 14px;">'


def unsubscribe_url(user_id) -> str:
    return _frontend(f"/unsubscribe?token={unsubscribe_token(user_id)}")


def render(kind: str, user: User) -> tuple[str, str, str]:
    """(subject, html, text) for one onboarding email."""
    subject, blocks = _content(kind)
    name = _first_name(user)
    stop = unsubscribe_url(user.id)

    text_parts = [f"Hi {name}," if name else "Hi,"]
    html_parts = [f"{_P}{escape(text_parts[0])}</p>"]
    for block in blocks:
        if isinstance(block, tuple):
            label, url = block
            text_parts.append(f"{label}: {url}")
            html_parts.append(
                f'<p style="margin:22px 0;"><a href="{escape(url, quote=True)}" '
                'style="display:inline-block;background:#0a7870;color:#ffffff;padding:11px 22px;'
                f'border-radius:999px;font-weight:600;font-size:14px;text-decoration:none;">{escape(label)}</a></p>'
            )
        elif isinstance(block, list):
            text_parts.append("\n".join(f"- {item}" for item in block))
            html_parts.append(
                '<ul style="padding-left:20px;margin:0 0 14px;">'
                + "".join(f'<li style="margin:0 0 4px;">{escape(item)}</li>' for item in block)
                + "</ul>"
            )
        else:
            text_parts.append(block)
            html_parts.append(f"{_P}{escape(block)}</p>")
    text_parts.append("Danilo")
    html_parts.append(f"{_P}Danilo</p>")
    text_parts.append(f"Don't send me tips: {stop}")

    body = "\n".join(html_parts)
    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1f2a2e;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 12px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;">
        <tr><td style="font-size:15px;line-height:1.55;color:#1f2a2e;">
          {body}
          <p style="font-size:12px;color:#8a8270;margin:24px 0 0;">
            <a href="{escape(stop, quote=True)}" style="color:#8a8270;">Don't send me tips</a>
          </p>
        </td></tr>
      </table>
      {email_service._FOOTER}
    </td></tr>
  </table>
</body>
</html>
"""
    return subject, html, "\n\n".join(text_parts)


def _skipped(user: Optional[User]) -> bool:
    return (
        user is None
        or user.is_active is False
        or is_staff(user)
        or (user.email or "").lower().startswith(TEST_EMAIL_PREFIX)
    )


def _team_and_wallet(db: Session, user_id):
    team = db.query(Team).filter(Team.owner_id == user_id).first()
    if team is None:
        return None, None
    return team, db.query(CreditWallet).filter(CreditWallet.team_id == team.id).first()


def _has_uploaded(db: Session, team: Team, wallet: CreditWallet) -> bool:
    if db.query(TranslationProject.id).filter(TranslationProject.team_id == team.id).first():
        return True
    # A deleted project still leaves its usage behind.
    return db.query(CreditTransaction.id).filter(
        CreditTransaction.wallet_id == wallet.id, CreditTransaction.type == "USAGE"
    ).first() is not None


def _has_bought(db: Session, wallet: CreditWallet) -> bool:
    if (wallet.plan_type or "").upper() != "TRIAL" or (wallet.purchased_credits or 0) > 0:
        return True
    return db.query(CreditTransaction.id).filter(
        CreditTransaction.wallet_id == wallet.id,
        CreditTransaction.type.in_(("PURCHASE", "SUBSCRIPTION_GRANT")),
    ).first() is not None


def due(db: Session, row: OnboardingEmail, now: datetime) -> Optional[str]:
    """The onboarding email this sign-up should get now, if any."""
    if row.unsubscribed_at is not None:
        return None
    if row.welcome_sent_at is None and now - row.signed_up_at < WELCOME_WITHIN:
        return "welcome"
    team, wallet = _team_and_wallet(db, row.user_id)
    if wallet is None or wallet.subscription_expires_at is None or _has_bought(db, wallet):
        return None
    ends = wallet.subscription_expires_at
    if row.nudge_sent_at is None and NUDGE_AFTER <= now - row.signed_up_at < NUDGE_UNTIL and now < ends:
        if not _has_uploaded(db, team, wallet):
            return "nudge"
    if row.last_chance_sent_at is None and now < ends <= now + LAST_CHANCE_BEFORE:
        if _has_uploaded(db, team, wallet):
            return "last_chance"
    if row.trial_ended_sent_at is None and now - TRIAL_ENDED_UNTIL < ends <= now - TRIAL_ENDED_AFTER:
        if not _has_uploaded(db, team, wallet):
            return "trial_ended"
    return None


def deliver(db: Session, user: User, kind: str, now: Optional[datetime] = None) -> bool:
    """Claim the email, then send it; a failed send releases the claim so a later pass retries."""
    column = getattr(OnboardingEmail, f"{kind}_sent_at")
    now = now or datetime.utcnow()
    claimed = db.execute(
        update(OnboardingEmail)
        .where(
            OnboardingEmail.user_id == user.id,
            column.is_(None),
            OnboardingEmail.unsubscribed_at.is_(None),
        )
        .values({column.key: now})
        .returning(OnboardingEmail.user_id)
    ).first()
    db.commit()
    if claimed is None:
        return False
    sent = False
    try:
        subject, html, plain = render(kind, user)
        stop = unsubscribe_url(user.id)
        sent = email_service.send_email(
            to=user.email,
            subject=subject,
            html=html,
            text_fallback=plain,
            from_email=_sender(),
            reply_to=SUPPORT_EMAIL,
            headers={"List-Unsubscribe": f"<{stop}>"},
        )
    except Exception as e:
        logger.warning("Onboarding email (%s) failed: %s", kind, type(e).__name__)
    if not sent:
        logger.warning("Onboarding email (%s) not sent", kind)
        db.execute(update(OnboardingEmail).where(OnboardingEmail.user_id == user.id).values({column.key: None}))
        db.commit()
    return bool(sent)


def send_welcome(user_id) -> None:
    """Background task after registration; never raises."""
    if not enabled():
        return
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        row = db.query(OnboardingEmail).filter(OnboardingEmail.user_id == user_id).first()
        if row is None or _skipped(user) or due(db, row, datetime.utcnow()) != "welcome":
            return
        deliver(db, user, "welcome")
    except Exception as e:
        db.rollback()
        logger.warning("Welcome email failed: %s", type(e).__name__)
    finally:
        db.close()


def send_due(db: Session, now: Optional[datetime] = None) -> int:
    now = now or datetime.utcnow()
    pending = or_(*(getattr(OnboardingEmail, f"{k}_sent_at").is_(None) for k in KINDS))
    rows = (
        db.query(OnboardingEmail, User)
        .join(User, User.id == OnboardingEmail.user_id)
        .filter(
            OnboardingEmail.unsubscribed_at.is_(None),
            OnboardingEmail.signed_up_at > now - WINDOW,
            pending,
        )
        .order_by(OnboardingEmail.signed_up_at)
        .all()
    )
    sent = 0
    for row, user in rows:
        if sent >= BATCH:
            break
        if _skipped(user):
            continue
        kind = due(db, row, now)
        if kind and deliver(db, user, kind, now):
            sent += 1
    return sent


def run(now: Optional[datetime] = None) -> int:
    """One pass, on whichever instance takes the advisory lock first; the others skip."""
    if not enabled():
        return 0
    from app.database import SessionLocal, engine

    with engine.connect() as conn:
        if not conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar():
            return 0
        try:
            db = SessionLocal()
            try:
                return send_due(db, now)
            except Exception as e:
                db.rollback()
                logger.warning("Onboarding email pass failed: %s", type(e).__name__)
                return 0
            finally:
                db.close()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            conn.commit()


def run_if_due(now: Optional[datetime] = None) -> int:
    global _last_run
    now = now or datetime.utcnow()
    if _last_run and now - _last_run < RUN_EVERY:
        return 0
    _last_run = now
    return run(now)
