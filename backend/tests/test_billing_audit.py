"""Renewals, the wallet ledger and spending rules found in the accounts and billing audit. Stripe is mocked."""
import uuid

import pytest

from app.core.plan_features import SUBSCRIPTION_GRANTS
from app.models.credit import CreditTransaction, CreditWallet
from app.models.project import TranslationProject
from app.models.user import User
from tests.conftest import make_pdf


@pytest.fixture(autouse=True)
def no_real_stripe(monkeypatch):
    import stripe

    def refuse(*a, **kw):
        raise AssertionError("tests must not call Stripe")

    monkeypatch.setattr(stripe.Subscription, "retrieve", refuse)
    monkeypatch.setattr(stripe.Price, "retrieve", refuse)
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", refuse)


def _wallet(db, owner):
    db.expire_all()
    return db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).one()


def _post_event(client, monkeypatch, event):
    import stripe

    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *a, **kw: event)
    return client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1"})


def _subscriber(db, make_user, plan="PRO", credits=0):
    owner = make_user(plan=plan, credits=credits)
    user = db.query(User).filter(User.id == owner["user"].id).one()
    user.stripe_subscription_id = "sub_live"
    user.stripe_customer_id = "cus_1"
    db.commit()
    return owner


def _invoice(owner, line, *, user_id=None):
    return {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "id": f"in_{uuid.uuid4().hex[:10]}",
            "subscription": "sub_live",
            "customer": "cus_1",
            "metadata": {"user_id": user_id or str(owner["user"].id), "team_id": str(owner["team"].id)},
            "lines": {"data": [line]},
        }},
    }


def test_renewal_grants_credits_after_the_buyer_deleted_their_account(client, db, make_user, monkeypatch):
    owner = _subscriber(db, make_user, plan="PRO", credits=0)
    gone = str(uuid.uuid4())
    event = _invoice(owner, {"price": {"id": "price_ci_pro"}, "period": {"end": 1893456000}}, user_id=gone)

    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    w = _wallet(db, owner)
    assert (w.plan_type, w.subscription_status, w.subscription_credits) == ("PRO", "ACTIVE", SUBSCRIPTION_GRANTS["PRO"])


def test_renewal_hands_the_subscription_to_the_owner_when_nobody_holds_it(client, db, make_user, monkeypatch):
    owner = make_user(plan="PRO", credits=0)
    event = _invoice(owner, {"price": {"id": "price_ci_pro"}, "period": {"end": 1893456000}}, user_id=str(uuid.uuid4()))

    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    db.expire_all()
    user = db.query(User).filter(User.id == owner["user"].id).one()
    assert (user.stripe_subscription_id, user.stripe_customer_id) == ("sub_live", "cus_1")


def test_renewal_on_a_portal_only_price_maps_by_lookup_key(client, db, make_user, monkeypatch):
    import stripe

    # stripe_setup.py puts every plan in the portal, even ones with no STRIPE_PRICE_* set here.
    monkeypatch.setattr(
        stripe.Price, "retrieve", lambda pid: {"id": pid, "lookup_key": "traq_studio_monthly_eur"}
    )
    owner = _subscriber(db, make_user, plan="STUDIO", credits=4)
    line = {"pricing": {"price_details": {"price": "price_portal_studio"}}, "period": {"end": 1893456000}}

    assert _post_event(client, monkeypatch, _invoice(owner, line)).json() == {"status": "success"}
    w = _wallet(db, owner)
    assert (w.plan_type, w.subscription_credits) == ("STUDIO", SUBSCRIPTION_GRANTS["STUDIO"])


def test_renewal_is_retried_when_stripe_cannot_name_the_price(client, db, make_user, monkeypatch):
    owner = _subscriber(db, make_user, plan="STUDIO", credits=4)
    line = {"pricing": {"price_details": {"price": "price_portal_studio"}}, "period": {"end": 1893456000}}

    assert _post_event(client, monkeypatch, _invoice(owner, line)).status_code == 500
    assert _wallet(db, owner).subscription_credits == 4


def _transactions(client, owner):
    return [(t["type"], t["amount"]) for t in client.get("/billing/transactions", headers=owner["headers"]).json()]


def test_pack_purchase_shows_in_the_wallet_history(client, db, make_user, monkeypatch):
    owner = make_user(plan="PRO", credits=0)
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_pack_1", "payment_status": "paid", "mode": "payment",
            "metadata": {"type": "credit_purchase", "credits": "25",
                         "user_id": str(owner["user"].id), "team_id": str(owner["team"].id)},
        }},
    }
    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    assert _wallet(db, owner).purchased_credits == 25
    assert ("PURCHASE", 25) in _transactions(client, owner)


def test_subscription_checkout_and_renewal_show_in_the_wallet_history(client, db, make_user, monkeypatch):
    owner = make_user(plan="TRIAL", credits=1)
    checkout = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_sub_1", "payment_status": "paid", "mode": "subscription", "subscription": "sub_live",
            "metadata": {"user_id": str(owner["user"].id), "team_id": str(owner["team"].id), "plan": "PRO"},
        }},
    }
    assert _post_event(client, monkeypatch, checkout).json() == {"status": "success"}
    renewal = _invoice(owner, {"price": {"id": "price_ci_pro"}, "period": {"end": 1893456000}})
    assert _post_event(client, monkeypatch, renewal).json() == {"status": "success"}
    grants = [t for t in _transactions(client, owner) if t[0] == "SUBSCRIPTION_GRANT"]
    assert grants == [("SUBSCRIPTION_GRANT", SUBSCRIPTION_GRANTS["PRO"])] * 2


def test_first_invoice_after_checkout_adds_no_second_grant_row(client, db, make_user, monkeypatch):
    owner = make_user(plan="TRIAL", credits=1)
    checkout = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_sub_2", "payment_status": "paid", "mode": "subscription", "subscription": "sub_live",
            "metadata": {"user_id": str(owner["user"].id), "team_id": str(owner["team"].id), "plan": "BASIC"},
        }},
    }
    assert _post_event(client, monkeypatch, checkout).json() == {"status": "success"}
    first = _invoice(owner, {"price": {"id": "price_ci_basic"}, "period": {"end": 1893456000}})
    first["data"]["object"]["billing_reason"] = "subscription_create"
    assert _post_event(client, monkeypatch, first).json() == {"status": "success"}
    grants = [t for t in _transactions(client, owner) if t[0] == "SUBSCRIPTION_GRANT"]
    assert grants == [("SUBSCRIPTION_GRANT", SUBSCRIPTION_GRANTS["BASIC"])]
    assert _wallet(db, owner).subscription_credits == SUBSCRIPTION_GRANTS["BASIC"]


def test_sync_session_pack_purchase_records_the_ledger_once(client, db, make_user, monkeypatch):
    import stripe

    owner = make_user(plan="PRO", credits=0)
    session = {
        "id": "cs_pack_2", "payment_status": "paid", "mode": "payment",
        "metadata": {"type": "credit_purchase", "credits": "10",
                     "user_id": str(owner["user"].id), "team_id": str(owner["team"].id)},
    }
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", lambda sid: session)
    for _ in range(2):
        r = client.post("/subscription/sync-session", params={"session_id": "cs_pack_2"}, headers=owner["headers"])
        assert r.status_code == 200
    assert _wallet(db, owner).purchased_credits == 10
    assert _transactions(client, owner).count(("PURCHASE", 10)) == 1


def test_lapsed_subscription_credits_cannot_be_spent(client, db, make_user, tmp_path):
    owner = make_user(plan="PRO", credits=29)
    w = _wallet(db, owner)
    w.subscription_status = "INACTIVE"
    w.purchased_credits = 1
    db.commit()

    pdf = make_pdf(tmp_path / "doc.pdf", pages=3)
    with open(pdf, "rb") as f:
        r = client.post("/projects/upload", headers=owner["headers"], files={"file": ("doc.pdf", f, "application/pdf")})
    assert r.status_code == 400
    assert r.json()["detail"] == "Insufficient credits"
    assert db.query(TranslationProject).count() == 0
    w = _wallet(db, owner)
    assert (w.subscription_credits, w.purchased_credits) == (29, 1)
    assert db.query(CreditTransaction).filter(CreditTransaction.type == "USAGE").count() == 0
