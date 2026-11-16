"""Onboarding emails to trial sign-ups: welcome, 48h nudge, last chance, trial ended. Email is mocked."""
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.company import SUPPORT_EMAIL
from app.models.credit import CreditTransaction, CreditWallet
from app.models.onboarding_email import OnboardingEmail
from app.models.team_member import TeamInvite
from app.models.user import User
from app.services import onboarding_emails

NOW = datetime(2026, 11, 16, 12, 0)


def _register(client, email="maria@traqtest.io", name="Maria Rossi", token=None):
    body = {"email": email, "password": "correct horse battery", "full_name": name, "accept_terms": True}
    if token:
        body["invite_token"] = token
    return client.post("/auth/register", json=body)


def _to(emails, address):
    return [m for m in emails if m["to"] == address]


def _trial(db, make_user, *, signed_up_ago, ends_in, email=None, **kw):
    """A trial sign-up that joined `signed_up_ago` before NOW and whose trial ends `ends_in` after NOW."""
    owner = make_user(email=email, plan="TRIAL", credits=3, **kw)
    wallet = db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).one()
    wallet.subscription_expires_at = NOW + ends_in
    db.add(OnboardingEmail(user_id=owner["user"].id, signed_up_at=NOW - signed_up_ago, welcome_sent_at=NOW - signed_up_ago))
    db.commit()
    owner["wallet"] = wallet
    return owner


def _row(db, user):
    db.expire_all()
    return db.query(OnboardingEmail).filter(OnboardingEmail.user_id == user.id).one()


def _subjects(emails):
    return [m["subject"] for m in emails]


# Welcome

def test_a_trial_sign_up_gets_the_welcome_from_danilo(client, db, emails):
    assert _register(client).status_code == 200

    mine = _to(emails, "maria@traqtest.io")
    assert _subjects(mine) == ["Your first document on OnlineDocTranslator"]
    mail = mine[0]
    assert mail["from_email"] == "Danilo from OnlineDocTranslator <notifications@onlinedoctranslator.ai>"
    assert mail["reply_to"] == SUPPORT_EMAIL
    assert "Hi Maria," in mail["text_fallback"]
    assert "Upload your first document: http://localhost:3000/new-translation" in mail["text_fallback"]
    for line in ("3 free pages", "keeps the layout", "with a watermark", "language pair"):
        assert line in mail["text_fallback"]
    assert "Don't send me tips" in mail["html"]
    assert "Sent by OnlineDocTranslator" in mail["html"]
    assert mail["headers"]["List-Unsubscribe"].startswith("<http://localhost:3000/unsubscribe?token=")
    # The owner notice still goes to the business inbox.
    assert _subjects(_to(emails, SUPPORT_EMAIL)) == ["New sign-up: Maria Rossi (trial)"]


def test_the_welcome_goes_once(client, db, emails):
    assert _register(client).status_code == 200
    user = db.query(User).filter(User.email == "maria@traqtest.io").one()

    onboarding_emails.send_due(db, datetime.utcnow())
    onboarding_emails.send_welcome(user.id)

    assert len(_to(emails, "maria@traqtest.io")) == 1
    assert _row(db, user).welcome_sent_at is not None


def test_a_failed_welcome_is_retried_by_the_next_pass(client, db, monkeypatch):
    import app.services.email_service as email_service

    monkeypatch.setattr(email_service, "send_email", lambda **kw: False)
    assert _register(client).status_code == 200
    user = db.query(User).filter(User.email == "maria@traqtest.io").one()
    assert _row(db, user).welcome_sent_at is None

    sent = []
    monkeypatch.setattr(email_service, "send_email", lambda **kw: sent.append(kw) or True)
    assert onboarding_emails.send_due(db, datetime.utcnow()) == 1
    assert _subjects(sent) == ["Your first document on OnlineDocTranslator"]


def test_names_are_escaped_in_the_html(client, emails):
    assert _register(client, name="<b>Evil</b>").status_code == 200
    mail = _to(emails, "maria@traqtest.io")[0]
    assert "<b>Evil" not in mail["html"]
    assert "&lt;b&gt;Evil" in mail["html"]


def test_invited_members_get_no_onboarding_email(client, db, make_user, emails):
    owner = make_user()
    invite = TeamInvite(team_id=owner["team"].id, email="luca@traqtest.io", role="MEMBER", invited_by=owner["user"].id)
    db.add(invite)
    db.commit()

    assert _register(client, "luca@traqtest.io", "Luca Bianchi", invite.token).status_code == 200
    luca = db.query(User).filter(User.email == "luca@traqtest.io").one()

    assert _to(emails, "luca@traqtest.io") == []
    assert db.query(OnboardingEmail).filter(OnboardingEmail.user_id == luca.id).first() is None
    for days in (0, 3, 6, 8):
        onboarding_emails.send_due(db, datetime.utcnow() + timedelta(days=days))
    assert _to(emails, "luca@traqtest.io") == []


def test_no_welcome_when_the_setting_is_off(client, db, emails, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ONBOARDING_EMAILS_ENABLED", False)
    assert _register(client).status_code == 200
    assert _to(emails, "maria@traqtest.io") == []
    assert onboarding_emails.run(datetime.utcnow()) == 0
    assert _to(emails, "maria@traqtest.io") == []


def test_a_mail_failure_does_not_break_sign_up(client, db, monkeypatch):
    import app.services.email_service as email_service

    def boom(**kw):
        raise RuntimeError("mail server down")

    monkeypatch.setattr(email_service, "send_email", boom)
    assert _register(client).status_code == 200


# Nudge, 48 hours in

def test_the_nudge_goes_48_hours_in_when_nothing_was_uploaded(db, make_user, emails):
    owner = _trial(db, make_user, signed_up_ago=timedelta(hours=49), ends_in=timedelta(days=5))

    assert onboarding_emails.send_due(db, NOW) == 1
    assert onboarding_emails.send_due(db, NOW + timedelta(hours=2)) == 0

    assert _subjects(emails) == ["Did something stop you?"]
    text = emails[0]["text_fallback"]
    assert "certificate or a diploma" in text
    assert "reply and tell me what it was" in text
    assert "http://localhost:3000/new-translation" in text
    assert emails[0]["to"] == owner["user"].email


def test_no_nudge_before_48_hours(db, make_user, emails):
    _trial(db, make_user, signed_up_ago=timedelta(hours=47), ends_in=timedelta(days=5))
    assert onboarding_emails.send_due(db, NOW) == 0


def test_no_nudge_after_an_upload(db, make_user, make_project, emails):
    owner = _trial(db, make_user, signed_up_ago=timedelta(hours=49), ends_in=timedelta(days=5))
    make_project(owner)
    assert onboarding_emails.send_due(db, NOW) == 0


def test_an_upload_later_deleted_still_counts(db, make_user, emails):
    owner = _trial(db, make_user, signed_up_ago=timedelta(hours=49), ends_in=timedelta(days=5))
    db.add(CreditTransaction(wallet_id=owner["wallet"].id, type="USAGE", amount=-1))
    db.commit()
    assert onboarding_emails.send_due(db, NOW) == 0


def test_no_nudge_once_they_subscribed(db, make_user, emails):
    owner = _trial(db, make_user, signed_up_ago=timedelta(hours=49), ends_in=timedelta(days=5))
    owner["wallet"].plan_type = "PRO"
    db.commit()
    assert onboarding_emails.send_due(db, NOW) == 0


# Last chance, a day before the trial ends

def test_last_chance_goes_the_day_before_the_trial_ends_after_an_upload(db, make_user, make_project, emails):
    owner = _trial(db, make_user, signed_up_ago=timedelta(days=6, hours=2), ends_in=timedelta(hours=22))
    make_project(owner)

    assert onboarding_emails.send_due(db, NOW) == 1
    assert onboarding_emails.send_due(db, NOW + timedelta(hours=1)) == 0

    assert _subjects(emails) == ["Your trial ends tomorrow"]
    text = emails[0]["text_fallback"]
    assert "with the trial watermark" in text
    assert "See plans and page packs: http://localhost:3000/billing" in text
    assert "from €19/month" in text
    assert "10 pages for €15" in text


def test_no_last_chance_without_an_upload(db, make_user, emails):
    _trial(db, make_user, signed_up_ago=timedelta(days=6, hours=2), ends_in=timedelta(hours=22))
    assert onboarding_emails.send_due(db, NOW) == 0


def test_no_last_chance_after_buying_a_pack(db, make_user, make_project, emails):
    owner = _trial(db, make_user, signed_up_ago=timedelta(days=6, hours=2), ends_in=timedelta(hours=22))
    make_project(owner)
    db.add(CreditTransaction(wallet_id=owner["wallet"].id, type="PURCHASE", amount=10, reference_id="cs_1"))
    db.commit()
    assert onboarding_emails.send_due(db, NOW) == 0


def test_no_last_chance_earlier_than_a_day_before(db, make_user, make_project, emails):
    owner = _trial(db, make_user, signed_up_ago=timedelta(days=4), ends_in=timedelta(days=3))
    make_project(owner)
    assert onboarding_emails.send_due(db, NOW) == 0


# Trial ended, the day after

def test_trial_ended_goes_the_day_after_when_nothing_was_uploaded(db, make_user, emails):
    _trial(db, make_user, signed_up_ago=timedelta(days=8, hours=2), ends_in=-timedelta(hours=26))

    assert onboarding_emails.send_due(db, NOW) == 1
    for hours in (1, 24, 72):
        assert onboarding_emails.send_due(db, NOW + timedelta(hours=hours)) == 0

    assert _subjects(emails) == ["Your trial ended"]
    assert "reply to this email and I'll reopen it" in emails[0]["text_fallback"]


def test_no_trial_ended_email_after_an_upload(db, make_user, make_project, emails):
    owner = _trial(db, make_user, signed_up_ago=timedelta(days=8, hours=2), ends_in=-timedelta(hours=26))
    make_project(owner)
    assert onboarding_emails.send_due(db, NOW) == 0


def test_no_trial_ended_email_on_the_day_it_ends_or_long_after(db, make_user, emails):
    _trial(db, make_user, signed_up_ago=timedelta(days=7, hours=2), ends_in=-timedelta(hours=2))
    assert onboarding_emails.send_due(db, NOW) == 0
    assert onboarding_emails.send_due(db, NOW + timedelta(days=4)) == 0


# Who never gets them

@pytest.mark.parametrize("kind", ["staff", "inactive", "test_address"])
def test_staff_inactive_and_test_accounts_are_skipped(db, make_user, emails, kind):
    email = "funnel-check+42@traqtest.io" if kind == "test_address" else None
    owner = _trial(db, make_user, signed_up_ago=timedelta(hours=49), ends_in=timedelta(days=5), email=email)
    if kind == "staff":
        owner["user"].role = "SUPERUSER"
    if kind == "inactive":
        owner["user"].is_active = False
    db.commit()
    assert onboarding_emails.send_due(db, NOW) == 0
    assert emails == []


def test_test_addresses_get_no_welcome_either(client, db, emails):
    assert _register(client, email="funnel-check+7@traqtest.io").status_code == 200
    assert _to(emails, "funnel-check+7@traqtest.io") == []


def test_users_from_before_the_deploy_get_no_backlog(db, migrated_db):
    """The migration marks every existing user's emails as sent."""
    import alembic.config
    from alembic import command
    from sqlalchemy import text

    from app.database import engine

    # No ini file: alembic's env.py would run fileConfig on it, disabling the app's loggers for later tests.
    config = alembic.config.Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    db.close()
    command.downgrade(config, "f7b9d1e3a5c8")
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO users (id, email, password_hash, is_active, subscription_status, subscription_plan, role, token_version, failed_login_count, terms_accepted_at) "
                "VALUES (gen_random_uuid(), 'old@traqtest.io', 'x', true, 'TRIAL', 'TRIAL', 'USER', 0, 0, now() - interval '50 hours')"
            ))
    finally:
        command.upgrade(config, "head")

    row = db.query(OnboardingEmail).one()
    assert row.welcome_sent_at and row.nudge_sent_at and row.last_chance_sent_at and row.trial_ended_sent_at
    assert onboarding_emails.due(db, row, datetime.utcnow()) is None


# Unsubscribe

def _token_from(mail):
    return parse_qs(urlparse(mail["headers"]["List-Unsubscribe"].strip("<>")).query)["token"][0]


def test_dont_send_me_tips_stops_onboarding_emails(client, db, emails, monkeypatch):
    from app.config import settings

    assert _register(client).status_code == 200
    user = db.query(User).filter(User.email == "maria@traqtest.io").one()
    token = _token_from(_to(emails, "maria@traqtest.io")[0])

    r = client.post("/auth/onboarding-emails/unsubscribe", json={"token": token})
    assert r.status_code == 200
    assert r.json() == {"status": "unsubscribed"}
    assert client.post("/auth/onboarding-emails/unsubscribe", json={"token": token}).status_code == 200
    assert _row(db, user).unsubscribed_at is not None

    emails.clear()
    for hours in (49, 7 * 24 + 26):
        onboarding_emails.send_due(db, datetime.utcnow() + timedelta(hours=hours))
    assert emails == []

    # Transactional email is unaffected.
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test")
    assert client.post("/auth/forgot-password", json={"email": "maria@traqtest.io"}).status_code == 200
    assert _subjects(emails) == ["Reset your OnlineDocTranslator password"]


def test_a_forged_unsubscribe_token_is_refused(client, db, make_user):
    owner = make_user()
    token = onboarding_emails.unsubscribe_token(owner["user"].id)
    forged = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    for bad in (forged, "nonsense", "", owner["user"].id.hex + "."):
        assert client.post("/auth/onboarding-emails/unsubscribe", json={"token": bad}).status_code == 400


# One instance at a time

def test_a_second_instance_skips_while_the_lock_is_held(db, make_user, emails):
    from sqlalchemy import text

    from app.database import engine

    _trial(db, make_user, signed_up_ago=timedelta(hours=49), ends_in=timedelta(days=5))
    with engine.connect() as other:
        assert other.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": onboarding_emails.LOCK_KEY}).scalar()
        assert onboarding_emails.run(NOW) == 0
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": onboarding_emails.LOCK_KEY})
        other.commit()
    assert emails == []
    assert onboarding_emails.run(NOW) == 1
    assert _subjects(emails) == ["Did something stop you?"]


def test_the_pass_runs_at_most_hourly(monkeypatch):
    calls = []
    monkeypatch.setattr(onboarding_emails, "_last_run", None)
    monkeypatch.setattr(onboarding_emails, "run", lambda now=None: calls.append(now) or 0)
    onboarding_emails.run_if_due(NOW)
    onboarding_emails.run_if_due(NOW + timedelta(minutes=30))
    onboarding_emails.run_if_due(NOW + timedelta(minutes=61))
    assert calls == [NOW, NOW + timedelta(minutes=61)]
