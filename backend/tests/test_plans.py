"""Studio and Agency plans, seat limits, queue priority and the 3-page trial."""
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.plan_features import PLAN_FEATURES, SEAT_LIMITS, SUBSCRIPTION_GRANTS, TRIAL_CREDITS
from app.dependencies import feature_guard
from app.models.credit import CreditTransaction, CreditWallet
from app.models.team_member import TeamInvite, TeamMember
from app.models.user import User
from app.services.credit_service import top_up_trial_wallets
from tests.test_billing_and_queue import _upload


def _wallet(db, owner):
    db.expire_all()
    return db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).one()


# Plans endpoint

def test_plans_endpoint_is_public_and_lists_every_paid_plan(client):
    r = client.get("/billing/plans")
    assert r.status_code == 200
    body = r.json()
    plans = {p["code"]: p for p in body["plans"]}
    assert list(plans) == ["BASIC", "PRO", "STUDIO", "AGENCY"]
    assert (plans["STUDIO"]["price_eur"], plans["STUDIO"]["credits"], plans["STUDIO"]["seats"]) == (79, 100, 5)
    assert (plans["AGENCY"]["price_eur"], plans["AGENCY"]["credits"], plans["AGENCY"]["seats"]) == (249, 400, 20)
    assert plans["STUDIO"]["price_per_page_eur"] == 0.79
    assert plans["AGENCY"]["price_per_page_eur"] == 0.62
    assert plans["AGENCY"]["priority"] and not plans["STUDIO"]["priority"]
    # CI sets prices for Basic and Pro only.
    assert plans["PRO"]["available"] and not plans["STUDIO"]["available"] and not plans["AGENCY"]["available"]
    assert body["trial"]["credits"] == 3 and body["trial"]["days"] == 7
    assert body["trial"]["features"]["download_translation"] is False
    assert body["contact_email"] == "info@lumaxdigital.co.uk"
    assert [p["credits"] for p in body["credit_packs"]] == [10, 25, 50]


# Checkout

def test_checkout_without_a_stripe_price_is_503(client, make_user):
    owner = make_user(plan="TRIAL")
    for plan in ("STUDIO", "AGENCY"):
        r = client.post("/subscription/create-checkout-session", params={"plan": plan}, headers=owner["headers"])
        assert r.status_code == 503
        assert "isn't available yet" in r.json()["detail"]
    r = client.post("/subscription/create-checkout-session", params={"plan": "PLATINUM"}, headers=owner["headers"])
    assert r.status_code == 400


def test_checkout_uses_the_configured_price(client, make_user, monkeypatch):
    import stripe

    from app.routers import subscription

    monkeypatch.setitem(subscription.PLAN_PRICE_MAP, "AGENCY", "price_agency")
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(url="https://checkout.test/s")

    monkeypatch.setattr(stripe.checkout.Session, "create", create)
    owner = make_user(plan="TRIAL")
    r = client.post("/subscription/create-checkout-session", params={"plan": "agency"}, headers=owner["headers"])
    assert r.status_code == 200
    assert seen["line_items"] == [{"price": "price_agency", "quantity": 1}]
    assert seen["metadata"]["plan"] == "AGENCY"


# Webhook

def _post_event(client, monkeypatch, event):
    import stripe

    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *a, **kw: event)
    return client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1"})


def test_webhook_maps_new_prices_to_plans(monkeypatch):
    from app.routers import stripe as stripe_router

    monkeypatch.setattr(stripe_router.settings, "STRIPE_PRICE_STUDIO", "price_studio")
    monkeypatch.setattr(stripe_router.settings, "STRIPE_PRICE_AGENCY", "price_agency")
    cfg = stripe_router._build_plan_config()
    assert cfg["price_studio"] == {"plan": "STUDIO", "credits": 100}
    assert cfg["price_agency"] == {"plan": "AGENCY", "credits": 400}
    assert cfg["price_ci_pro"] == {"plan": "PRO", "credits": 29}


@pytest.mark.parametrize("plan,price", [("STUDIO", "price_studio"), ("AGENCY", "price_agency")])
def test_invoice_paid_activates_new_plan(client, db, make_user, monkeypatch, plan, price):
    from app.routers import stripe as stripe_router

    monkeypatch.setitem(stripe_router.PLAN_CONFIG, price, {"plan": plan, "credits": SUBSCRIPTION_GRANTS[plan]})
    owner = make_user(plan="TRIAL", credits=1)
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "subscription": "sub_1",
            "metadata": {"user_id": str(owner["user"].id), "team_id": str(owner["team"].id)},
            "lines": {"data": [{"price": {"id": price}, "period": {"end": 1893456000}}]},
        }},
    }
    r = _post_event(client, monkeypatch, event)
    assert r.json() == {"status": "success"}
    w = _wallet(db, owner)
    assert (w.plan_type, w.subscription_status, w.subscription_credits) == (plan, "ACTIVE", SUBSCRIPTION_GRANTS[plan])
    assert feature_guard.effective_plan(db, owner["user"]) == plan


def test_checkout_completed_activates_agency(client, db, make_user, monkeypatch):
    owner = make_user(plan="TRIAL", credits=1)
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_test_1", "payment_status": "paid", "mode": "subscription", "subscription": "sub_1",
            "metadata": {"user_id": str(owner["user"].id), "team_id": str(owner["team"].id), "plan": "AGENCY"},
        }},
    }
    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    w = _wallet(db, owner)
    assert (w.plan_type, w.subscription_credits) == ("AGENCY", 400)


# Plan resolution and features

@pytest.mark.parametrize("plan", ["STUDIO", "AGENCY"])
def test_new_plans_resolve_and_match_pro_features(db, make_user, plan):
    owner = make_user(plan=plan)
    assert feature_guard.effective_plan(db, owner["user"]) == plan
    assert feature_guard.team_plan(db, owner["team"].id) == plan
    assert PLAN_FEATURES[plan] == PLAN_FEATURES["PRO"]
    for feature in PLAN_FEATURES["PRO"]:
        assert feature_guard.user_has_feature(db, owner["user"], feature)


@pytest.mark.parametrize("plan", ["STUDIO", "AGENCY"])
def test_inactive_new_plan_is_expired(db, make_user, plan):
    owner = make_user(plan=plan)
    db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).update({"subscription_status": "INACTIVE"})
    db.commit()
    assert feature_guard.effective_plan(db, owner["user"]) == "EXPIRED"


def test_pro_features_reachable_on_studio(client, make_user):
    owner = make_user(plan="STUDIO")
    assert client.get("/glossary", headers=owner["headers"]).status_code == 200
    assert client.get("/certifications", headers=owner["headers"]).status_code == 200


# Seats

def _invite(client, owner, email=None):
    return client.post(
        "/members/invite",
        headers=owner["headers"],
        json={"email": email or f"{uuid.uuid4().hex[:8]}@traqtest.io", "role": "MEMBER"},
    )


@pytest.mark.parametrize("plan,limit", [("BASIC", 2), ("PRO", 3), ("STUDIO", 5), ("AGENCY", 20)])
def test_invite_stops_at_the_plan_seat_limit(client, make_user, plan, limit):
    assert SEAT_LIMITS[plan] == limit
    owner = make_user(plan=plan)
    for _ in range(limit - 1):
        assert _invite(client, owner).status_code == 200
    r = _invite(client, owner)
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert f"up to {limit} team members" in detail
    if plan == "AGENCY":
        assert "info@lumaxdigital.co.uk" in detail
    else:
        assert "Upgrade to" in detail


def test_seat_message_names_the_next_plan(client, make_user):
    owner = make_user(plan="BASIC")
    _invite(client, owner)
    assert "Upgrade to Pro for up to 3" in _invite(client, owner).json()["detail"]


def test_existing_user_and_pending_invites_use_seats(client, db, make_user):
    owner = make_user(plan="BASIC")
    other = make_user()
    r = _invite(client, owner, other["user"].email)
    assert r.json()["added"] is True
    assert _invite(client, owner).status_code == 403
    listing = client.get("/members", headers=owner["headers"]).json()
    assert listing["seats"] == {"used": 2, "limit": 2}


def test_reinviting_a_pending_email_and_cancelling_frees_nothing_twice(client, db, make_user):
    owner = make_user(plan="BASIC")
    first = _invite(client, owner, "a@traqtest.io").json()["invite"]
    assert _invite(client, owner, "a@traqtest.io").status_code == 200
    assert _invite(client, owner, "b@traqtest.io").status_code == 403
    assert client.delete(f"/members/invites/{first['id']}", headers=owner["headers"]).status_code == 200
    assert _invite(client, owner, "b@traqtest.io").status_code == 200


def test_trial_cannot_invite(client, make_user):
    owner = make_user(plan="TRIAL")
    assert _invite(client, owner).status_code == 403


def test_admin_has_no_seat_limit(client, db, make_user):
    owner = make_user(plan="BASIC")
    db.query(User).filter(User.id == owner["user"].id).update({"role": "ADMIN"})
    db.commit()
    for _ in range(3):
        assert _invite(client, owner).status_code == 200


# Queue priority

def test_agency_jobs_are_claimed_first(client, db, make_user, tmp_path):
    from app.workers import sqs_worker

    pro = make_user(plan="PRO", credits=20)
    agency = make_user(plan="AGENCY", credits=20)
    first = _upload(client, pro, tmp_path).json()["project_id"]
    second = _upload(client, pro, tmp_path).json()["project_id"]
    urgent = _upload(client, agency, tmp_path).json()["project_id"]
    priorities = dict(db.execute(text("SELECT project_id::text, priority FROM translation_jobs")).fetchall())
    assert priorities == {first: 0, second: 0, urgent: 1}

    assert sqs_worker._claim_next_job()["project_id"] == urgent
    assert sqs_worker._claim_next_job()["project_id"] == first
    assert sqs_worker._claim_next_job()["project_id"] == second


def test_pending_queue_index_leads_with_priority(db):
    indexdef = db.execute(text(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_translation_jobs_pending'"
    )).scalar()
    assert "priority DESC, created_at" in indexdef and "pending" in indexdef


# Trial

def test_registration_grants_three_trial_credits(client, db):
    r = client.post("/auth/register", json={
        "email": "fresh@traqtest.io", "password": "correct horse battery", "full_name": "Fresh", "accept_terms": True,
    })
    assert r.status_code == 200
    user = db.query(User).filter(User.email == "fresh@traqtest.io").one()
    team_id = feature_guard._resolve_team_id(db, user)
    wallet = db.query(CreditWallet).filter(CreditWallet.team_id == team_id).one()
    assert TRIAL_CREDITS == 3
    assert (wallet.plan_type, wallet.subscription_credits) == ("TRIAL", 3)
    grants = db.query(CreditTransaction).filter(CreditTransaction.wallet_id == wallet.id).all()
    assert [(t.type, t.amount) for t in grants] == [("TRIAL_GRANT", 3)]
    assert PLAN_FEATURES["TRIAL"]["download_translation"] is False


def test_trial_top_up_raises_running_trials_once(db, make_user):
    low = make_user(plan="TRIAL", credits=1)
    spent = make_user(plan="TRIAL", credits=0)
    full = make_user(plan="TRIAL", credits=3)
    ended = make_user(plan="TRIAL", credits=0, expires_in_days=-1)
    paid = make_user(plan="BASIC", credits=0)

    assert top_up_trial_wallets(db, 3) == 2
    db.commit()
    assert _wallet(db, low).subscription_credits == 3
    assert _wallet(db, spent).subscription_credits == 3
    assert _wallet(db, full).subscription_credits == 3
    assert _wallet(db, ended).subscription_credits == 0
    assert _wallet(db, paid).subscription_credits == 0

    rows = db.query(CreditTransaction).filter(CreditTransaction.type == "TRIAL_GRANT").all()
    by_wallet = {r.wallet_id: r for r in rows}
    assert by_wallet[_wallet(db, low).id].amount == 2
    assert by_wallet[_wallet(db, spent).id].amount == 3
    assert {r.reference_id for r in rows} == {"trial_topup:3"}

    # Running it again, even after the credits are spent, grants nothing more.
    db.query(CreditWallet).filter(CreditWallet.team_id == low["team"].id).update({"subscription_credits": 0})
    db.commit()
    assert top_up_trial_wallets(db, 3) == 0
    db.commit()
    assert _wallet(db, low).subscription_credits == 0
    assert db.query(CreditTransaction).filter(CreditTransaction.type == "TRIAL_GRANT").count() == 2


def test_trial_without_expiry_date_is_topped_up(db, make_user):
    owner = make_user(plan="TRIAL", credits=1)
    db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).update({"subscription_expires_at": None})
    db.commit()
    assert top_up_trial_wallets(db, 3) == 1


def test_ended_trial_marked_by_date_is_not_topped_up(db, make_user):
    owner = make_user(plan="TRIAL", credits=0)
    db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).update(
        {"subscription_expires_at": datetime.utcnow() - timedelta(minutes=1)}
    )
    db.commit()
    assert top_up_trial_wallets(db, 3) == 0


def test_members_listing_reports_seats(client, db, make_user):
    owner = make_user(plan="STUDIO")
    make_user(team=owner["team"])
    db.add(TeamInvite(team_id=owner["team"].id, email="p@traqtest.io", role="MEMBER", invited_by=owner["user"].id))
    db.commit()
    assert db.query(TeamMember).filter(TeamMember.team_id == owner["team"].id).count() == 1
    assert client.get("/members", headers=owner["headers"]).json()["seats"] == {"used": 3, "limit": 5}
