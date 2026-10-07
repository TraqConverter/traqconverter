"""Checkout tax params: off by default (seller not VAT-registered), Stripe Tax when the flag is on. Stripe is mocked."""
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
def test_tax_off_sends_no_tax_but_still_requires_the_billing_address(client, db, make_user, checkout, monkeypatch, start):
    from app.routers import subscription

    monkeypatch.setattr(subscription.settings, "STRIPE_AUTOMATIC_TAX", False)
    who = make_user(plan="BASIC")
    _with_customer(db, who)
    assert start(client, who).status_code == 200
    kw = checkout[-1]
    for key in ("automatic_tax", "tax_id_collection", "customer_creation"):
        assert key not in kw
    assert kw["billing_address_collection"] == "required"
    assert kw["customer"] == "cus_tax"
    assert kw["customer_update"] == {"address": "auto", "name": "auto"}


@pytest.mark.parametrize("start", [_plan, _pack])
def test_tax_off_new_customer_gets_no_customer_update(client, make_user, checkout, monkeypatch, start):
    from app.routers import subscription

    monkeypatch.setattr(subscription.settings, "STRIPE_AUTOMATIC_TAX", False)
    who = make_user(plan="BASIC")
    assert start(client, who).status_code == 200
    kw = checkout[-1]
    for key in ("automatic_tax", "tax_id_collection", "customer_creation", "customer", "customer_update"):
        assert key not in kw
    assert kw["billing_address_collection"] == "required"


def test_setting_defaults_off():
    from app.config import Settings

    assert Settings.model_fields["STRIPE_AUTOMATIC_TAX"].default is False
