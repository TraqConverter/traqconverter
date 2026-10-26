"""Credit packs: sold to everyone, subscribers at the base price and everyone else at PAYG_MARKUP. Stripe is mocked."""
from types import SimpleNamespace

import pytest

from app.core.plan_features import CREDIT_PACKS, PAYG_MARKUP
from app.models.credit import CreditWallet
from app.models.user import User


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
        monkeypatch.setitem(subscription.PAYG_CREDIT_PACKS, credits, f"price_payg_c{credits}")
    return calls


def _buy(client, who, amount=25):
    return client.post("/subscription/purchase-credits", params={"amount": amount}, headers=who["headers"])


def _bought_at(checkout):
    kw = checkout[-1]
    return kw["line_items"][0]["price"], kw["metadata"]["price_lookup_key"], kw["metadata"]["pricing"]


def _lapse(db, who, **values):
    db.query(CreditWallet).filter(CreditWallet.team_id == who["team"].id).update(values)
    db.commit()


def test_trial_buys_a_pack_at_the_payg_price(client, make_user, checkout):
    r = _buy(client, make_user(plan="TRIAL"))
    assert r.status_code == 200
    assert _bought_at(checkout) == ("price_payg_c25", "traq_payg_credits_25_eur", "payg")


def test_ended_trial_buys_a_pack_at_the_payg_price(client, make_user, checkout):
    assert _buy(client, make_user(plan="TRIAL", expires_in_days=-1), 10).status_code == 200
    assert _bought_at(checkout) == ("price_payg_c10", "traq_payg_credits_10_eur", "payg")


def test_expired_account_buys_a_pack_at_the_payg_price(client, db, make_user, checkout):
    who = make_user(plan="PRO")
    _lapse(db, who, plan_type="EXPIRED", subscription_status="INACTIVE", subscription_credits=0)
    assert _buy(client, who, 50).status_code == 200
    assert _bought_at(checkout) == ("price_payg_c50", "traq_payg_credits_50_eur", "payg")


def test_lapsed_subscription_pays_the_payg_price(client, db, make_user, checkout):
    who = make_user(plan="PRO")
    _lapse(db, who, subscription_status="CANCELED")
    assert _buy(client, who).status_code == 200
    assert _bought_at(checkout)[0] == "price_payg_c25"


def test_payg_account_with_credits_left_still_pays_the_payg_price(client, db, make_user, checkout):
    who = make_user(plan="TRIAL", expires_in_days=-1)
    _lapse(db, who, purchased_credits=7)
    assert _buy(client, who).status_code == 200
    assert _bought_at(checkout)[0] == "price_payg_c25"


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
    assert _bought_at(checkout) == ("price_c25", "traq_credits_25_eur", "subscriber")


def test_payg_price_not_configured_is_refused_not_sold_cheap(client, make_user, checkout, monkeypatch):
    from app.routers import subscription

    monkeypatch.setitem(subscription.PAYG_CREDIT_PACKS, 25, None)
    r = _buy(client, make_user(plan="TRIAL"))
    assert r.status_code == 503
    assert checkout == []


def test_team_member_of_a_subscriber_can_buy_a_pack(client, make_user, checkout):
    owner = make_user(plan="BASIC")
    member = make_user(team=owner["team"])
    assert _buy(client, member).status_code == 200
    assert _bought_at(checkout)[0] == "price_c25"


def test_admin_on_a_trial_pays_the_subscriber_price(client, db, make_user, checkout):
    who = make_user(plan="TRIAL")
    db.query(User).filter(User.id == who["user"].id).update({"role": "ADMIN"})
    db.commit()
    assert _buy(client, who).status_code == 200
    assert _bought_at(checkout)[0] == "price_c25"


def test_wallet_says_which_pack_price_applies(client, db, make_user):
    trial, sub = make_user(plan="TRIAL"), make_user(plan="BASIC")
    assert client.get("/billing/wallet", headers=trial["headers"]).json()["pack_pricing"] == "payg"
    assert client.get("/billing/wallet", headers=sub["headers"]).json()["pack_pricing"] == "subscriber"


def test_payg_prices_are_the_markup_over_subscriber_prices(client):
    assert PAYG_MARKUP == 1.5
    packs = client.get("/billing/plans").json()["credit_packs"]
    got = [(p["credits"], p["payg_price_cents"], p["payg_price_per_page_eur"], p["subscriber_saving_eur"]) for p in packs]
    assert got == [(10, 1500, 1.5, 5.0), (25, 3375, 1.35, 11.25), (50, 6000, 1.2, 20.0)]


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


def test_setup_script_plans_the_payg_prices_by_lookup_key():
    from scripts import stripe_setup

    env = {"STRIPE_SECRET_KEY": "sk_test_x", "STRIPE_PRICE_BASIC": "price_basic", "STRIPE_PRICE_PRO": "price_pro"}
    out = []
    result = stripe_setup.run(_stripe_with({}), env, dry_run=True, say=out.append)
    text = "\n".join(out)
    for credits, cents in ((10, 1500), (25, 3375), (50, 6000)):
        assert (
            f"STRIPE_PRICE_PAYG_CREDITS_{credits}: would create one-time price {cents} eur, "
            f"lookup_key traq_payg_credits_{credits}_eur"
        ) in text
        assert f"PAYG_CREDITS_{credits}" in result["created"]


def test_setup_script_reuses_payg_prices_found_by_lookup_key():
    from scripts import stripe_setup
    from tests.test_stripe_portal import FakeStripe

    payg = {
        f"traq_payg_credits_{c}_eur": {"id": f"price_pg{c}", "product": "prod_c", "unit_amount": cents, "currency": "eur"}
        for c, cents in ((10, 1500), (25, 3375), (50, 6000))
    }
    fake = FakeStripe(
        prices={"price_basic": {"id": "price_basic", "product": "prod_basic", "unit_amount": 1900, "currency": "eur"},
                "price_pro": {"id": "price_pro", "product": "prod_pro", "unit_amount": 2900, "currency": "eur"}},
        lookup=payg,
        portals=[{"id": "bpc_existing", "metadata": {"traq_portal": "subscription"}}],
    )
    env = {"STRIPE_SECRET_KEY": "sk_test_x", "STRIPE_PRICE_BASIC": "price_basic", "STRIPE_PRICE_PRO": "price_pro"}
    out = []
    result = stripe_setup.run(fake, env, dry_run=False, say=out.append)
    assert result["payg_credit_packs"] == {10: "price_pg10", 25: "price_pg25", 50: "price_pg50"}
    assert not [c for c in result["created"] if c.startswith("PAYG_")]
    assert "STRIPE_PRICE_PAYG_CREDITS_25=price_pg25" in "\n".join(out)
    assert "MISMATCH" not in "\n".join(line for line in out if "PAYG" in line)
