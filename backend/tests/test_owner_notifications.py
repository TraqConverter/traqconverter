"""Business-inbox emails: sign-ups, subscriptions, plan changes, credit packs, cancellations. Stripe and email are mocked."""
import uuid
from datetime import datetime

import pytest

from app.core.company import SUPPORT_EMAIL
from app.core.plan_features import SUBSCRIPTION_GRANTS
from app.models.credit import CreditWallet
from app.models.stripe_event import StripeEvent
from app.models.team_member import TeamInvite
from app.models.user import User

PERIOD_START = 1790000000
PERIOD_END = PERIOD_START + 30 * 86400


@pytest.fixture(autouse=True)
def no_real_stripe(monkeypatch):
    import stripe

    def refuse(*a, **kw):
        raise AssertionError("tests must not call Stripe")

    monkeypatch.setattr(stripe.Subscription, "retrieve", refuse)
    monkeypatch.setattr(stripe.Price, "retrieve", refuse)


@pytest.fixture()
def prices(monkeypatch):
    from app.routers import stripe as stripe_router

    for plan in SUBSCRIPTION_GRANTS:
        monkeypatch.setitem(
            stripe_router.PLAN_CONFIG, f"price_{plan.lower()}", {"plan": plan, "credits": SUBSCRIPTION_GRANTS[plan]}
        )


@pytest.fixture()
def notify_off(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "OWNER_NOTIFY_EMAIL", "")


@pytest.fixture()
def broken_mail(monkeypatch):
    import app.services.email_service as email_service

    def boom(**kw):
        raise RuntimeError("mail server down")

    monkeypatch.setattr(email_service, "send_email", boom)


def _register(client, email="maria@traqtest.io", name="Maria Rossi", token=None):
    body = {"email": email, "password": "correct horse battery", "full_name": name, "accept_terms": True}
    if token:
        body["invite_token"] = token
    return client.post("/auth/register", json=body)


def _post_event(client, monkeypatch, event):
    import stripe

    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *a, **kw: event)
    return client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1"})


def _subscriber(db, make_user, plan="PRO", sub_id="sub_live"):
    owner = make_user(plan=plan, credits=SUBSCRIPTION_GRANTS[plan])
    user = db.query(User).filter(User.id == owner["user"].id).one()
    user.stripe_subscription_id = sub_id
    user.stripe_customer_id = "cus_1"
    db.commit()
    return owner


def _checkout_event(owner, *, event_id=None, session_id="cs_test_1", **metadata):
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": session_id,
            "payment_status": "paid",
            "mode": "payment" if metadata.get("type") == "credit_purchase" else "subscription",
            "subscription": None if metadata.get("type") == "credit_purchase" else "sub_new",
            "customer": "cus_1",
            "amount_total": metadata.pop("amount_total", 2900),
            "currency": "eur",
            "metadata": {"user_id": str(owner["user"].id), "team_id": str(owner["team"].id), **metadata},
        }},
    }


def _sub_event(owner, price, *, event_type="customer.subscription.updated", event_id=None, previous=None,
               sub_id="sub_live", **extra):
    data = {"object": {
        "id": sub_id,
        "customer": "cus_1",
        "status": "active",
        "current_period_start": PERIOD_START,
        "current_period_end": PERIOD_END,
        "metadata": {"user_id": str(owner["user"].id), "team_id": str(owner["team"].id)},
        "items": {"data": [{"price": {"id": price, "lookup_key": None}}]},
        **extra,
    }}
    if previous is not None:
        data["previous_attributes"] = previous
    return {"id": event_id or f"evt_{uuid.uuid4().hex}", "type": event_type, "data": data}


def _day(ts):
    d = datetime.utcfromtimestamp(ts)
    return f"{d.day} {d:%b}"


# Sign-ups

def test_trial_sign_up_emails_the_business_inbox_once(client, db, emails):
    assert _register(client).status_code == 200

    assert len(emails) == 1
    mail = emails[0]
    assert mail["to"] == SUPPORT_EMAIL
    assert mail["subject"] == "New sign-up: Maria Rossi (trial)"
    for expected in ("maria@traqtest.io", "Maria Rossi's Team", "Started a free trial", "UTC"):
        assert expected in mail["text_fallback"]
    assert "Sent by OnlineDocTranslator" in mail["html"]


def test_invited_sign_up_says_which_team_they_joined(client, db, make_user, emails):
    owner = make_user()
    owner["team"].name = "Studio X"
    invite = TeamInvite(team_id=owner["team"].id, email="luca@traqtest.io", role="MEMBER", invited_by=owner["user"].id)
    db.add(invite)
    db.commit()

    assert _register(client, "luca@traqtest.io", "Luca Bianchi", invite.token).status_code == 200

    assert [m["subject"] for m in emails] == ["New sign-up: Luca Bianchi (joined Studio X)"]
    assert "Joined Studio X by invite" in emails[0]["text_fallback"]
    assert "trial" not in emails[0]["text_fallback"].lower()


def test_names_are_escaped_in_the_html(client, emails):
    assert _register(client, name="<b>Evil</b>").status_code == 200
    assert "<b>Evil</b>" not in emails[0]["html"]
    assert "&lt;b&gt;Evil&lt;/b&gt;" in emails[0]["html"]


def test_no_sign_up_email_when_the_setting_is_empty(client, db, emails, notify_off):
    assert _register(client).status_code == 200
    assert emails == []


def test_a_mail_failure_does_not_break_sign_up(client, db, broken_mail):
    assert _register(client).status_code == 200
    assert db.query(User).filter(User.email == "maria@traqtest.io").count() == 1


def test_a_failure_preparing_the_email_does_not_break_sign_up(client, db, emails, monkeypatch, caplog):
    from app.services import owner_notifications

    def boom(*a, **kw):
        raise ValueError("maria@traqtest.io")

    monkeypatch.setattr(owner_notifications, "signup", boom)
    assert _register(client).status_code == 200
    assert emails == []
    assert "maria@traqtest.io" not in caplog.text


# New subscription

def test_new_subscription_emails_once_and_retries_do_not_repeat(client, db, make_user, monkeypatch, emails):
    owner = make_user(plan="TRIAL", credits=3)
    owner["team"].name = "Studio X"
    db.commit()
    event = _checkout_event(owner, plan="PRO")

    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    assert _post_event(client, monkeypatch, event).json() == {"status": "already_processed"}

    assert len(emails) == 1
    mail = emails[0]
    assert mail["subject"] == "New subscription: Studio X — Pro €29/month"
    assert owner["user"].email in mail["text_fallback"]
    assert "Paid at checkout: €29.00" in mail["text_fallback"]


def test_new_subscription_is_emailed_even_when_the_success_page_granted_it_first(client, db, make_user, monkeypatch, emails):
    owner = make_user(plan="TRIAL", credits=3)
    db.add(StripeEvent(id="sub_checkout_cs_test_1", event_type="subscription_grant"))
    db.commit()

    r = _post_event(client, monkeypatch, _checkout_event(owner, plan="STUDIO", amount_total=7900))

    assert r.json() == {"status": "duplicate_skipped"}
    assert [m["subject"] for m in emails] == ["New subscription: Team — Studio €79/month"]


def test_the_first_invoice_sends_no_second_subscription_email(client, db, make_user, monkeypatch, emails, prices):
    owner = _subscriber(db, make_user, sub_id="sub_new")
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "id": "in_1",
            "billing_reason": "subscription_create",
            "subscription": "sub_new",
            "customer": "cus_1",
            "metadata": {"user_id": str(owner["user"].id), "team_id": str(owner["team"].id)},
            "lines": {"data": [{"price": {"id": "price_pro"}, "period": {"end": PERIOD_END}}]},
        }},
    }
    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    assert emails == []


def test_no_subscription_email_for_platform_staff(client, db, make_user, monkeypatch, emails):
    owner = make_user(plan="TRIAL", credits=3)
    db.query(User).filter(User.id == owner["user"].id).update({"role": "SUPER_ADMIN"})
    db.commit()
    assert _post_event(client, monkeypatch, _checkout_event(owner, plan="PRO")).json() == {"status": "success"}
    assert emails == []


def test_no_subscription_email_when_the_setting_is_empty(client, make_user, monkeypatch, emails, notify_off):
    owner = make_user(plan="TRIAL", credits=3)
    assert _post_event(client, monkeypatch, _checkout_event(owner, plan="PRO")).json() == {"status": "success"}
    assert emails == []


def test_a_mail_failure_does_not_break_the_webhook(client, db, make_user, monkeypatch, broken_mail):
    owner = make_user(plan="TRIAL", credits=3)
    assert _post_event(client, monkeypatch, _checkout_event(owner, plan="PRO")).json() == {"status": "success"}
    db.expire_all()
    wallet = db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).one()
    assert (wallet.plan_type, wallet.subscription_status) == ("PRO", "ACTIVE")


def test_a_failure_preparing_the_email_does_not_break_the_webhook(client, db, make_user, monkeypatch, emails):
    from app.services import owner_notifications

    def boom(*a, **kw):
        raise ValueError("nope")

    monkeypatch.setattr(owner_notifications, "new_subscription", boom)
    owner = make_user(plan="TRIAL", credits=3)
    assert _post_event(client, monkeypatch, _checkout_event(owner, plan="PRO")).json() == {"status": "success"}
    assert emails == []


# Plan change

def test_a_portal_upgrade_sends_a_short_plan_change_email(client, db, make_user, monkeypatch, emails, prices):
    owner = _subscriber(db, make_user, plan="PRO")
    event = _sub_event(owner, "price_studio", previous={"items": {"data": [{"price": {"id": "price_pro"}}]}})

    assert _post_event(client, monkeypatch, event).json() == {"status": "upgraded"}
    assert _post_event(client, monkeypatch, event).json() == {"status": "already_processed"}

    assert [m["subject"] for m in emails] == ["Plan change: Team — Pro to Studio (upgrade)"]
    assert "From: Pro €29/month" in emails[0]["text_fallback"]
    assert "To: Studio €79/month" in emails[0]["text_fallback"]


def test_a_portal_downgrade_says_downgrade(client, db, make_user, monkeypatch, emails, prices):
    owner = _subscriber(db, make_user, plan="STUDIO")
    event = _sub_event(owner, "price_basic", previous={"items": {"data": [{"price": {"id": "price_studio"}}]}})
    assert _post_event(client, monkeypatch, event).json() == {"status": "downgraded"}
    assert [m["subject"] for m in emails] == ["Plan change: Team — Studio to Basic (downgrade)"]


def test_an_update_that_keeps_the_plan_sends_nothing(client, db, make_user, monkeypatch, emails, prices):
    owner = _subscriber(db, make_user, plan="PRO")
    assert _post_event(client, monkeypatch, _sub_event(owner, "price_pro")).json() == {"status": "success"}
    assert emails == []


# Credit packs

def test_credit_pack_emails_once(client, db, make_user, monkeypatch, emails):
    owner = make_user(plan="PRO")
    owner["team"].name = "Studio X"
    db.commit()
    event = _checkout_event(owner, type="credit_purchase", credits="25", amount_total=2250)

    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    assert _post_event(client, monkeypatch, event).json() == {"status": "already_processed"}

    assert [m["subject"] for m in emails] == ["Credit pack: Studio X — 25 credits €22.50"]
    text = emails[0]["text_fallback"]
    assert "Pack: Standard pack" in text
    assert owner["user"].email in text


def test_credit_pack_is_emailed_even_when_the_success_page_granted_it_first(client, db, make_user, monkeypatch, emails):
    owner = make_user(plan="PRO")
    db.add(StripeEvent(id="checkout_cs_test_1", event_type="credit_grant"))
    db.commit()
    event = _checkout_event(owner, type="credit_purchase", credits="10", amount_total=1000)
    assert _post_event(client, monkeypatch, event).json() == {"status": "duplicate_skipped"}
    assert [m["subject"] for m in emails] == ["Credit pack: Team — 10 credits €10.00"]


def test_no_credit_pack_email_when_the_setting_is_empty(client, make_user, monkeypatch, emails, notify_off):
    owner = make_user(plan="PRO")
    event = _checkout_event(owner, type="credit_purchase", credits="10", amount_total=1000)
    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    assert emails == []


# Cancellations

def test_scheduled_cancellation_emails_the_end_date_once(client, db, make_user, monkeypatch, emails, prices):
    owner = _subscriber(db, make_user, plan="PRO")
    event = _sub_event(owner, "price_pro", cancel_at_period_end=True, previous={"cancel_at_period_end": False})

    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    assert _post_event(client, monkeypatch, event).json() == {"status": "already_processed"}
    # A later update while the end stays scheduled.
    later = _sub_event(owner, "price_pro", cancel_at_period_end=True, previous={"default_payment_method": None})
    assert _post_event(client, monkeypatch, later).json() == {"status": "success"}

    assert [m["subject"] for m in emails] == [f"Cancellation: Team — Pro, ends {_day(PERIOD_END)}"]
    assert "stays active until the end date" in emails[0]["text_fallback"]


def test_cancellation_scheduled_with_cancel_at(client, db, make_user, monkeypatch, emails, prices):
    owner = _subscriber(db, make_user, plan="STUDIO")
    cancel_at = PERIOD_END - 86400
    event = _sub_event(owner, "price_studio", cancel_at=cancel_at, previous={"cancel_at": None})
    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    assert [m["subject"] for m in emails] == [f"Cancellation: Team — Studio, ends {_day(cancel_at)}"]


def test_deleted_subscription_sends_a_separate_ended_email(client, db, make_user, monkeypatch, emails, prices):
    owner = _subscriber(db, make_user, plan="PRO")
    ended_at = PERIOD_END
    event = _sub_event(owner, "price_pro", event_type="customer.subscription.deleted", status="canceled", ended_at=ended_at)

    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    assert _post_event(client, monkeypatch, event).json() == {"status": "already_processed"}

    assert [m["subject"] for m in emails] == [f"Subscription ended: Team — Pro, ended {_day(ended_at)}"]


def test_no_cancellation_emails_when_the_setting_is_empty(client, db, make_user, monkeypatch, emails, prices, notify_off):
    owner = _subscriber(db, make_user, plan="PRO")
    scheduled = _sub_event(owner, "price_pro", cancel_at_period_end=True, previous={"cancel_at_period_end": False})
    deleted = _sub_event(owner, "price_pro", event_type="customer.subscription.deleted", status="canceled", ended_at=PERIOD_END)
    assert _post_event(client, monkeypatch, scheduled).status_code == 200
    assert _post_event(client, monkeypatch, deleted).status_code == 200
    assert emails == []


def test_a_mail_failure_does_not_break_the_deleted_webhook(client, db, make_user, monkeypatch, prices, broken_mail):
    owner = _subscriber(db, make_user, plan="PRO")
    event = _sub_event(owner, "price_pro", event_type="customer.subscription.deleted", status="canceled", ended_at=PERIOD_END)
    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    db.expire_all()
    assert db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).one().plan_type == "EXPIRED"
