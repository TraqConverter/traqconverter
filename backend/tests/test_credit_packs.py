"""Credit packs: sold to active subscribers only, cheaper per page as they grow. Stripe is mocked."""
from types import SimpleNamespace

import pytest

from app.core.plan_features import CREDIT_PACKS
from app.models.credit import CreditWallet
from app.models.user import User

NEED_A_PLAN = "Extra page packs are for subscribers. Choose a plan first."


@pytest.fixture()
def checkout(monkeypatch):
    import stripe

    from app.routers import subscription

    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(url="https://checkout.test/pack")

    monkeypatch.setattr(stripe.checkout.Session, "create", create)
    for credits in (10, 25, 50):
        monkeypatch.setitem(subscription.CREDIT_PACKS, credits, f"price_c{credits}")
    return calls


def _buy(client, who, amount=25):
    return client.post("/subscription/purchase-credits", params={"amount": amount}, headers=who["headers"])


def test_trial_cannot_buy_a_pack(client, make_user, checkout):
    r = _buy(client, make_user(plan="TRIAL"))
    assert r.status_code == 403
    assert r.json()["detail"] == NEED_A_PLAN
    assert checkout == []


def test_ended_trial_cannot_buy_a_pack(client, make_user, checkout):
    r = _buy(client, make_user(plan="TRIAL", expires_in_days=-1))
    assert r.status_code == 403
    assert r.json()["detail"] == NEED_A_PLAN
    assert checkout == []


def test_lapsed_subscription_cannot_buy_a_pack(client, db, make_user, checkout):
    who = make_user(plan="PRO")
    db.query(CreditWallet).filter(CreditWallet.team_id == who["team"].id).update({"subscription_status": "CANCELED"})
    db.commit()
    r = _buy(client, who)
    assert r.status_code == 403
    assert r.json()["detail"] == NEED_A_PLAN


@pytest.mark.parametrize("plan", ["BASIC", "PRO", "STUDIO", "AGENCY"])
def test_subscriber_can_buy_a_pack(client, make_user, checkout, plan):
    who = make_user(plan=plan)
    r = _buy(client, who, 25)
    assert r.status_code == 200
    assert r.json() == {"checkout_url": "https://checkout.test/pack"}
    kw = checkout[-1]
    assert kw["mode"] == "payment"
    assert kw["line_items"] == [{"price": "price_c25", "quantity": 1}]
    assert kw["metadata"]["credits"] == "25"
    assert kw["metadata"]["team_id"] == str(who["team"].id)


def test_team_member_of_a_subscriber_can_buy_a_pack(client, make_user, checkout):
    owner = make_user(plan="BASIC")
    member = make_user(team=owner["team"])
    assert _buy(client, member).status_code == 200


def test_admin_on_a_trial_can_buy_a_pack(client, db, make_user, checkout):
    who = make_user(plan="TRIAL")
    db.query(User).filter(User.id == who["user"].id).update({"role": "ADMIN"})
    db.commit()
    assert _buy(client, who).status_code == 200


def test_unknown_pack_size_is_still_400(client, make_user, checkout):
    assert _buy(client, make_user(plan="BASIC"), 30).status_code == 400


def test_plans_endpoint_lists_the_new_pack_prices(client):
    packs = client.get("/billing/plans").json()["credit_packs"]
    got = [(p["credits"], p["price_cents"], p["price_eur"], p["price_per_page_eur"], p["save_percent"]) for p in packs]
    assert got == [
        (10, 1000, 10.0, 1.0, 0),
        (25, 2250, 22.5, 0.9, 10),
        (50, 4000, 40.0, 0.8, 20),
    ]


def test_bigger_packs_never_cost_more_per_page():
    per_page = [p["price_cents"] / p["credits"] for p in CREDIT_PACKS]
    assert per_page == sorted(per_page, reverse=True)


def _stripe_with(prices):
    from tests.test_stripe_portal import FakeStripe

    return FakeStripe(
        prices={
            "price_basic": {"id": "price_basic", "product": "prod_basic", "unit_amount": 1900, "currency": "eur"},
            "price_pro": {"id": "price_pro", "product": "prod_pro", "unit_amount": 2900, "currency": "eur"},
            **prices,
        },
        portals=[{"id": "bpc_existing", "metadata": {"traq_portal": "subscription"}}],
    )


def test_setup_script_checks_packs_against_the_new_cents():
    from scripts import stripe_setup

    env = {
        "STRIPE_SECRET_KEY": "sk_test_x",
        "STRIPE_PRICE_BASIC": "price_basic",
        "STRIPE_PRICE_PRO": "price_pro",
        "STRIPE_PRICE_CREDITS_10": "price_c10",
        "STRIPE_PRICE_CREDITS_25": "price_c25",
        "STRIPE_PRICE_CREDITS_50": "price_c50",
    }
    fake = _stripe_with({
        "price_c10": {"id": "price_c10", "product": "prod_c", "unit_amount": 1000, "currency": "eur"},
        "price_c25": {"id": "price_c25", "product": "prod_c", "unit_amount": 2250, "currency": "eur"},
        "price_c50": {"id": "price_c50", "product": "prod_c", "unit_amount": 5000, "currency": "eur"},
    })
    out = []
    stripe_setup.run(fake, env, dry_run=True, say=out.append)
    lines = {line.strip().split(":")[0]: line for line in out if "STRIPE_PRICE_CREDITS_" in line}
    assert "MISMATCH" not in lines["STRIPE_PRICE_CREDITS_10"]
    assert "MISMATCH" not in lines["STRIPE_PRICE_CREDITS_25"]
    assert lines["STRIPE_PRICE_CREDITS_50"].endswith("price_c50 = 5000 eur  <-- MISMATCH: expected 4000 eur")
