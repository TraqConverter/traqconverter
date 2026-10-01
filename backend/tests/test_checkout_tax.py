"""Stripe Tax on Checkout: VAT added on top, VAT IDs collected, billing address required. Stripe is mocked."""
from types import SimpleNamespace

import pytest

from app.models.user import User

TAX_ON = {
    "automatic_tax": {"enabled": True},
    "tax_id_collection": {"enabled": True},
    "billing_address_collection": "required",
}


@pytest.fixture()
def checkout(monkeypatch):
    import stripe

    from app.routers import subscription

    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(url="https://checkout.test/s")

    monkeypatch.setattr(stripe.checkout.Session, "create", create)
    monkeypatch.setitem(subscription.PLAN_PRICE_MAP, "PRO", "price_pro")
    monkeypatch.setitem(subscription.CREDIT_PACKS, 10, "price_c10")
    monkeypatch.setattr(subscription.settings, "STRIPE_AUTOMATIC_TAX", True)
    return calls


def _with_customer(db, who, customer="cus_tax"):
    user = db.query(User).filter(User.id == who["user"].id).one()
    user.stripe_customer_id = customer
    db.commit()


def _plan(client, who):
    return client.post("/subscription/create-checkout-session", params={"plan": "PRO"}, headers=who["headers"])


def _pack(client, who):
    return client.post("/subscription/purchase-credits", params={"amount": 10}, headers=who["headers"])


@pytest.mark.parametrize("start", [_plan, _pack])
def test_checkout_adds_tax_for_a_new_customer(client, make_user, checkout, start):
    who = make_user(plan="BASIC")
    assert start(client, who).status_code == 200
    kw = checkout[-1]
    assert {k: kw.get(k) for k in TAX_ON} == TAX_ON
    assert "customer" not in kw and "customer_update" not in kw


def test_new_customer_in_payment_mode_is_created_for_the_vat_id(client, make_user, checkout):
    who = make_user(plan="BASIC")
    _pack(client, who)
    assert checkout[-1]["mode"] == "payment"
    assert checkout[-1]["customer_creation"] == "always"
    _plan(client, who)
    assert checkout[-1]["mode"] == "subscription"
    assert "customer_creation" not in checkout[-1]


@pytest.mark.parametrize("start", [_plan, _pack])
def test_existing_customer_gets_address_and_name_saved(client, db, make_user, checkout, start):
    who = make_user(plan="BASIC")
    _with_customer(db, who)
    assert start(client, who).status_code == 200
    kw = checkout[-1]
    assert kw["customer"] == "cus_tax"
    assert kw["customer_update"] == {"address": "auto", "name": "auto"}
    assert {k: kw.get(k) for k in TAX_ON} == TAX_ON
    assert "customer_creation" not in kw


@pytest.mark.parametrize("start", [_plan, _pack])
def test_env_flag_turns_tax_off(client, db, make_user, checkout, monkeypatch, start):
    from app.routers import subscription

    monkeypatch.setattr(subscription.settings, "STRIPE_AUTOMATIC_TAX", False)
    who = make_user(plan="BASIC")
    _with_customer(db, who)
    assert start(client, who).status_code == 200
    kw = checkout[-1]
    for key in (*TAX_ON, "customer_update", "customer_creation"):
        assert key not in kw
    assert kw["customer"] == "cus_tax"


def test_setting_defaults_on():
    from app.config import Settings

    assert Settings.model_fields["STRIPE_AUTOMATIC_TAX"].default is True
