"""Customer portal, the checkout guard, plan-change webhooks and the Stripe setup script. Stripe is mocked throughout."""
import uuid
from types import SimpleNamespace

import pytest

from app.core.plan_features import SUBSCRIPTION_GRANTS
from app.dependencies import feature_guard
from app.models.credit import CreditTransaction, CreditWallet
from app.models.user import User


@pytest.fixture(autouse=True)
def no_real_stripe(monkeypatch):
    import stripe

    def refuse(*a, **kw):
        raise AssertionError("tests must not call Stripe")

    monkeypatch.setattr(stripe.Subscription, "retrieve", refuse)
    monkeypatch.setattr(stripe.billing_portal.Session, "create", refuse)
    monkeypatch.setattr(stripe.checkout.Session, "create", refuse)


def _wallet(db, owner):
    db.expire_all()
    return db.query(CreditWallet).filter(CreditWallet.team_id == owner["team"].id).one()


def _subscriber(db, make_user, plan="PRO", credits=None, sub_id="sub_live", customer="cus_1"):
    owner = make_user(plan=plan, credits=SUBSCRIPTION_GRANTS[plan] if credits is None else credits)
    user = db.query(User).filter(User.id == owner["user"].id).one()
    user.stripe_subscription_id = sub_id
    user.stripe_customer_id = customer
    db.commit()
    return owner


def _post_event(client, monkeypatch, event):
    import stripe

    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *a, **kw: event)
    return client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1"})


def _sub_event(owner, price, *, event_id=None, previous_price=None, sub_id="sub_live", status="active",
               period_start=1790000000, **extra):
    data = {"object": {
        "id": sub_id,
        "customer": "cus_1",
        "status": status,
        "current_period_start": period_start,
        "current_period_end": period_start + 30 * 86400,
        "metadata": {"user_id": str(owner["user"].id), "team_id": str(owner["team"].id)},
        "items": {"data": [{"price": {"id": price, "lookup_key": None}}]},
        **extra,
    }}
    if previous_price:
        data["previous_attributes"] = {"items": {"data": [{"price": {"id": previous_price}}]}}
    return {"id": event_id or f"evt_{uuid.uuid4().hex}", "type": "customer.subscription.updated", "data": data}


@pytest.fixture()
def prices(monkeypatch):
    from app.routers import stripe as stripe_router

    for plan in ("BASIC", "PRO", "STUDIO", "AGENCY"):
        monkeypatch.setitem(
            stripe_router.PLAN_CONFIG, f"price_{plan.lower()}", {"plan": plan, "credits": SUBSCRIPTION_GRANTS[plan]}
        )


# Portal

def test_portal_returns_a_url_for_the_team_customer(client, db, make_user, monkeypatch):
    import stripe

    from app.routers import subscription

    monkeypatch.setattr(subscription.settings, "STRIPE_PORTAL_CONFIGURATION", "bpc_123")
    monkeypatch.setattr(subscription.settings, "FRONTEND_URL", "https://app.test")
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(url="https://billing.stripe.test/p/session")

    monkeypatch.setattr(stripe.billing_portal.Session, "create", create)
    owner = _subscriber(db, make_user)
    admin = make_user(team=owner["team"], role="ADMIN")

    for who in (owner, admin):
        r = client.post("/subscription/portal", headers=who["headers"])
        assert r.status_code == 200
        assert r.json() == {"portal_url": "https://billing.stripe.test/p/session"}
    assert seen == {"customer": "cus_1", "return_url": "https://app.test/billing", "configuration": "bpc_123"}


@pytest.mark.parametrize("role", ["MEMBER", "PM", "REVIEWER"])
def test_portal_and_plan_change_are_for_the_owner_and_admins(client, db, make_user, monkeypatch, role):
    import stripe

    monkeypatch.setattr(stripe.billing_portal.Session, "create", lambda **kw: pytest.fail("portal opened for a " + role))
    owner = _subscriber(db, make_user, plan="PRO")
    other = make_user(team=owner["team"], role=role)

    r = client.post("/subscription/portal", headers=other["headers"])
    assert r.status_code == 403
    assert r.json()["detail"] == "Only the team owner or an admin can manage the subscription."
    r = client.post("/subscription/create-checkout-session", params={"plan": "BASIC"}, headers=other["headers"])
    assert r.status_code == 403
    assert client.get("/billing/wallet", headers=other["headers"]).json()["can_manage_billing"] is False
    assert client.get("/billing/wallet", headers=owner["headers"]).json()["can_manage_billing"] is True


def test_portal_recovers_the_customer_from_a_stored_subscription(client, db, make_user, monkeypatch):
    import stripe

    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda sid: {"id": sid, "customer": "cus_old"})
    monkeypatch.setattr(
        stripe.billing_portal.Session, "create", lambda **kw: SimpleNamespace(url=f"https://p.test/{kw['customer']}")
    )
    owner = _subscriber(db, make_user, customer=None)
    r = client.post("/subscription/portal", headers=owner["headers"])
    assert r.json()["portal_url"] == "https://p.test/cus_old"
    db.expire_all()
    assert db.query(User).filter(User.id == owner["user"].id).one().stripe_customer_id == "cus_old"


def test_portal_is_404_without_a_stripe_customer(client, make_user):
    owner = make_user(plan="TRIAL")
    r = client.post("/subscription/portal", headers=owner["headers"])
    assert r.status_code == 404


# Checkout guard

def test_checkout_is_409_for_an_active_subscriber(client, db, make_user):
    owner = _subscriber(db, make_user, plan="PRO")
    admin = make_user(team=owner["team"], role="ADMIN")
    for who in (owner, admin):
        r = client.post("/subscription/create-checkout-session", params={"plan": "BASIC"}, headers=who["headers"])
        assert r.status_code == 409
        assert r.json()["portal"] is True
        assert r.json()["detail"]


def test_wallet_reports_the_subscription(client, db, make_user):
    owner = _subscriber(db, make_user)
    assert client.get("/billing/wallet", headers=owner["headers"]).json()["has_subscription"] is True
    trial = make_user(plan="TRIAL")
    assert client.get("/billing/wallet", headers=trial["headers"]).json()["has_subscription"] is False


def test_lapsed_customer_checks_out_again_as_the_same_customer(client, db, make_user, monkeypatch):
    import stripe

    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(url="https://checkout.test/s")

    monkeypatch.setattr(stripe.checkout.Session, "create", create)
    owner = _subscriber(db, make_user, sub_id=None)
    wallet = _wallet(db, owner)
    wallet.plan_type, wallet.subscription_status = "EXPIRED", "INACTIVE"
    db.commit()
    r = client.post("/subscription/create-checkout-session", params={"plan": "PRO"}, headers=owner["headers"])
    assert r.status_code == 200
    assert seen["customer"] == "cus_1"


def test_plan_granted_without_stripe_can_still_check_out(client, make_user, monkeypatch):
    import stripe

    monkeypatch.setattr(stripe.checkout.Session, "create", lambda **kw: SimpleNamespace(url="https://checkout.test/s"))
    owner = make_user(plan="PRO")
    r = client.post("/subscription/create-checkout-session", params={"plan": "PRO"}, headers=owner["headers"])
    assert r.status_code == 200


# customer.subscription.updated

def _grants(db, owner):
    wallet = _wallet(db, owner)
    return db.query(CreditTransaction).filter(
        CreditTransaction.wallet_id == wallet.id, CreditTransaction.type == "SUBSCRIPTION_GRANT"
    ).all()


def test_upgrade_changes_plan_and_tops_up_the_difference_once(client, db, make_user, monkeypatch, prices):
    owner = _subscriber(db, make_user, plan="PRO", credits=5)
    event = _sub_event(owner, "price_studio", previous_price="price_pro")

    assert _post_event(client, monkeypatch, event).json() == {"status": "upgraded"}
    w = _wallet(db, owner)
    top_up = SUBSCRIPTION_GRANTS["STUDIO"] - SUBSCRIPTION_GRANTS["PRO"]
    assert (w.plan_type, w.subscription_status, w.subscription_credits) == ("STUDIO", "ACTIVE", 5 + top_up)
    assert feature_guard.effective_plan(db, owner["user"]) == "STUDIO"
    assert [g.amount for g in _grants(db, owner)] == [top_up]

    # Stripe resending the same event, and a second event for the same change, grant nothing more.
    assert _post_event(client, monkeypatch, event).json() == {"status": "already_processed"}
    again = _sub_event(owner, "price_studio", previous_price="price_pro")
    assert _post_event(client, monkeypatch, again).json() == {"status": "upgraded"}
    assert _wallet(db, owner).subscription_credits == 5 + top_up
    assert len(_grants(db, owner)) == 1


def test_upgrade_in_a_new_period_tops_up_again(client, db, make_user, monkeypatch, prices):
    owner = _subscriber(db, make_user, plan="PRO", credits=0)
    _post_event(client, monkeypatch, _sub_event(owner, "price_studio", previous_price="price_pro"))
    _post_event(client, monkeypatch, _sub_event(owner, "price_pro", previous_price="price_studio"))
    later = _sub_event(owner, "price_studio", previous_price="price_pro", period_start=1795000000)
    _post_event(client, monkeypatch, later)
    assert len(_grants(db, owner)) == 2


def test_downgrade_changes_plan_and_keeps_credits(client, db, make_user, monkeypatch, prices):
    owner = _subscriber(db, make_user, plan="AGENCY", credits=250)
    r = _post_event(client, monkeypatch, _sub_event(owner, "price_basic", previous_price="price_agency"))
    assert r.json() == {"status": "downgraded"}
    w = _wallet(db, owner)
    assert (w.plan_type, w.subscription_status, w.subscription_credits) == ("BASIC", "ACTIVE", 250)
    assert _grants(db, owner) == []


def test_scheduled_downgrade_waits_for_the_renewal(client, db, make_user, monkeypatch, prices):
    owner = _subscriber(db, make_user, plan="STUDIO", credits=80)
    # The portal scheduling a change sends an update whose price is still the current one.
    r = _post_event(client, monkeypatch, _sub_event(owner, "price_studio", schedule="sub_sched_1"))
    assert r.json() == {"status": "success"}
    assert (_wallet(db, owner).plan_type, _wallet(db, owner).subscription_credits) == ("STUDIO", 80)


def test_cancel_at_period_end_keeps_the_plan_until_then(client, db, make_user, monkeypatch, prices):
    owner = _subscriber(db, make_user, plan="PRO")
    event = _sub_event(owner, "price_pro", cancel_at_period_end=True)
    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    w = _wallet(db, owner)
    assert (w.plan_type, w.subscription_status) == ("PRO", "ACTIVE")
    assert w.subscription_expires_at is not None
    assert feature_guard.effective_plan(db, owner["user"]) == "PRO"


def test_update_found_by_customer_without_metadata(client, db, make_user, monkeypatch, prices):
    owner = _subscriber(db, make_user, plan="BASIC")
    event = _sub_event(owner, "price_pro", previous_price="price_basic")
    event["data"]["object"]["metadata"] = {}
    assert _post_event(client, monkeypatch, event).json() == {"status": "upgraded"}
    assert _wallet(db, owner).plan_type == "PRO"


def test_update_to_a_setup_script_price_maps_by_lookup_key(client, db, make_user, monkeypatch, prices):
    owner = _subscriber(db, make_user, plan="PRO")
    event = _sub_event(owner, "price_unconfigured")
    event["data"]["object"]["items"]["data"][0]["price"]["lookup_key"] = "traq_agency_monthly_eur"
    assert _post_event(client, monkeypatch, event).json() == {"status": "upgraded"}
    assert _wallet(db, owner).plan_type == "AGENCY"


def test_update_for_another_subscription_is_ignored(client, db, make_user, monkeypatch, prices):
    owner = _subscriber(db, make_user, plan="PRO", credits=10)
    event = _sub_event(owner, "price_agency", sub_id="sub_duplicate")
    assert _post_event(client, monkeypatch, event).json() == {"status": "ignored"}
    assert (_wallet(db, owner).plan_type, _wallet(db, owner).subscription_credits) == ("PRO", 10)


def test_unpaid_subscription_loses_access(client, db, make_user, monkeypatch, prices):
    owner = _subscriber(db, make_user, plan="PRO")
    _post_event(client, monkeypatch, _sub_event(owner, "price_pro", status="unpaid"))
    assert feature_guard.effective_plan(db, owner["user"]) == "EXPIRED"


# customer.subscription.deleted

def test_deleted_subscription_expires_the_plan(client, db, make_user, monkeypatch):
    owner = _subscriber(db, make_user, plan="STUDIO")
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "customer.subscription.deleted",
        "data": {"object": {
            "id": "sub_live", "customer": "cus_1", "status": "canceled", "ended_at": 1790000000,
            "metadata": {"user_id": str(owner["user"].id), "team_id": str(owner["team"].id)},
        }},
    }
    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    w = _wallet(db, owner)
    assert (w.plan_type, w.subscription_status, w.subscription_credits) == ("EXPIRED", "INACTIVE", 0)
    assert w.subscription_expires_at is not None
    assert feature_guard.effective_plan(db, owner["user"]) == "EXPIRED"
    user = db.query(User).filter(User.id == owner["user"].id).one()
    assert (user.stripe_subscription_id, user.stripe_customer_id) == (None, "cus_1")
    assert client.get("/billing/wallet", headers=owner["headers"]).json()["has_subscription"] is False


def test_deleting_a_stray_duplicate_keeps_the_live_plan(client, db, make_user, monkeypatch):
    owner = _subscriber(db, make_user, plan="PRO")
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "customer.subscription.deleted",
        "data": {"object": {
            "id": "sub_duplicate", "customer": "cus_1",
            "metadata": {"user_id": str(owner["user"].id), "team_id": str(owner["team"].id)},
        }},
    }
    assert _post_event(client, monkeypatch, event).json() == {"status": "ignored"}
    assert feature_guard.effective_plan(db, owner["user"]) == "PRO"


# Invoices after a plan change

def test_renewal_invoice_uses_the_plan_line_not_the_proration(client, db, make_user, monkeypatch, prices):
    owner = _subscriber(db, make_user, plan="STUDIO", credits=3)
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "subscription": "sub_live",
            "customer": "cus_1",
            "metadata": {"user_id": str(owner["user"].id), "team_id": str(owner["team"].id)},
            "lines": {"data": [
                {"price": {"id": "price_pro"}, "proration": True, "period": {"end": 1790000000}},
                {"price": {"id": "price_studio"}, "proration": False, "period": {"end": 1792592000}},
            ]},
        }},
    }
    assert _post_event(client, monkeypatch, event).json() == {"status": "success"}
    w = _wallet(db, owner)
    assert (w.plan_type, w.subscription_credits) == ("STUDIO", SUBSCRIPTION_GRANTS["STUDIO"])


# scripts/stripe_setup.py

class FakeStripe:
    """Records every write; reads come from the dicts given."""

    def __init__(self, prices=None, lookup=None, products=None, portals=None, webhooks=None):
        self.writes = []
        fake = self
        prices = prices or {}
        lookup = lookup or {}
        products = products or []
        portals = portals or []
        webhooks = webhooks or []

        def listing(items):
            return SimpleNamespace(data=list(items), auto_paging_iter=lambda: iter(items))

        def write(name):
            def _w(*a, **kw):
                fake.writes.append((name, a, kw))
                obj = {"id": f"{name}_new_{len(fake.writes)}"}
                if name == "we":
                    obj["secret"] = f"whsec_secret_{len(fake.writes)}"
                return obj
            return _w

        self.WebhookEndpoint = SimpleNamespace(
            list=lambda **kw: listing(webhooks), create=write("we"), modify=write("we_modify"),
        )

        self.Price = SimpleNamespace(
            retrieve=lambda pid: prices[pid],
            list=lambda lookup_keys, **kw: listing([lookup[k] for k in lookup_keys if k in lookup]),
            create=write("price"),
        )
        self.Product = SimpleNamespace(list=lambda **kw: listing(products), create=write("prod"))
        self.billing_portal = SimpleNamespace(Configuration=SimpleNamespace(
            list=lambda **kw: listing(portals), create=write("bpc"), modify=write("bpc_modify"),
        ))


def _price(pid, product, amount, currency="eur"):
    return {"id": pid, "product": product, "unit_amount": amount, "currency": currency}


ENV = {
    "STRIPE_SECRET_KEY": "sk_test_x",
    "STRIPE_PRICE_BASIC": "price_basic",
    "STRIPE_PRICE_PRO": "price_pro",
    "STRIPE_PRICE_CREDITS_10": "price_c10",
    "STRIPE_PRICE_CREDITS_25": "price_c25",
}
EXISTING = {
    "price_basic": _price("price_basic", "prod_basic", 1900),
    "price_pro": _price("price_pro", "prod_pro", 2900),
    "price_c10": _price("price_c10", "prod_c", 1000),
    "price_c25": _price("price_c25", "prod_c", 2500),
}


def test_setup_dry_run_creates_nothing_when_prices_exist():
    from scripts import stripe_setup

    fake = FakeStripe(
        prices=EXISTING,
        lookup={
            "traq_studio_monthly_eur": _price("price_studio", "prod_studio", 7900),
            "traq_agency_monthly_eur": _price("price_agency", "prod_agency", 24900),
            "traq_credits_50_eur": _price("price_c50_lk", "prod_c50", 4000),
        },
        portals=[{"id": "bpc_existing", "metadata": {"traq_portal": "subscription"}}],
    )
    out = []
    result = stripe_setup.run(fake, ENV, dry_run=True, say=out.append)
    assert fake.writes == []
    assert result == {
        "prices": {"BASIC": "price_basic", "PRO": "price_pro", "STUDIO": "price_studio", "AGENCY": "price_agency"},
        "credit_packs": {10: "price_c10", 25: "price_c25", 50: "price_c50_lk"},
        "portal": "bpc_existing",
        "created": [],
    }
    text = "\n".join(out)
    assert "STRIPE_PRICE_STUDIO=price_studio" in text and "STRIPE_PORTAL_CONFIGURATION=bpc_existing" in text
    # The 25-credit pack is still on the old 25 EUR price in Stripe; it now costs 22.50.
    assert "STRIPE_PRICE_CREDITS_25: price_c25 = 2500 eur  <-- MISMATCH: expected 2250 eur" in text
    assert "STRIPE_PRICE_CREDITS_10: price_c10 = 1000 eur\n" in text + "\n"
    assert "STRIPE_PRICE_CREDITS_50 (lookup_key traq_credits_50_eur): price_c50_lk = 4000 eur" in text
    assert "STRIPE_PRICE_CREDITS_50=price_c50_lk" in text


def test_setup_dry_run_plans_missing_prices_without_creating():
    from scripts import stripe_setup

    fake = FakeStripe(prices=EXISTING, products=[{"id": "prod_studio", "metadata": {"plan_code": "STUDIO"}}])
    out = []
    result = stripe_setup.run(fake, ENV, dry_run=True, say=out.append)
    assert fake.writes == []
    assert result["created"] == ["STUDIO", "AGENCY", "CREDITS_50"]
    assert result["portal"] == stripe_setup.PLANNED
    text = "\n".join(out)
    assert "STUDIO: would create price 7900 eur/month, lookup_key traq_studio_monthly_eur" in text
    assert "AGENCY: would create product 'OnlineDocTranslator Agency'" in text
    assert "STUDIO: would create product" not in text
    assert "STRIPE_PRICE_CREDITS_50: would create product 'OnlineDocTranslator – 50 pages'" in text
    assert "STRIPE_PRICE_CREDITS_50: would create one-time price 4000 eur, lookup_key traq_credits_50_eur" in text


def test_portal_allows_plan_switches_but_never_quantity_changes():
    from scripts import stripe_setup

    update = stripe_setup.portal_features(
        {"BASIC": ("prod_basic", "price_basic"), "PRO": ("prod_pro", "price_pro"), "PRO_Y": ("prod_pro", "price_pro_y")}
    )["subscription_update"]
    assert update["default_allowed_updates"] == ["price"]
    assert update["products"] == [
        {"product": "prod_basic", "prices": ["price_basic"], "adjustable_quantity": {"enabled": False}},
        {"product": "prod_pro", "prices": ["price_pro", "price_pro_y"], "adjustable_quantity": {"enabled": False}},
    ]


def test_setup_creates_missing_prices_and_the_portal():
    from scripts import stripe_setup

    fake = FakeStripe(prices=EXISTING, products=[{"id": "prod_studio", "metadata": {"plan_code": "STUDIO"}}])
    stripe_setup.run(fake, ENV, dry_run=False, say=lambda s: None)
    kinds = [w[0] for w in fake.writes]
    # STUDIO price, AGENCY product + price, portal, then the 50-credit pack (product + price).
    assert kinds == ["price", "prod", "price", "bpc", "prod", "price"]
    studio_price = fake.writes[0][2]
    assert (studio_price["product"], studio_price["unit_amount"], studio_price["currency"]) == ("prod_studio", 7900, "eur")
    assert studio_price["lookup_key"] == "traq_studio_monthly_eur"
    assert studio_price["recurring"] == {"interval": "month"}
    portal = fake.writes[3][2]
    update = portal["features"]["subscription_update"]
    assert update["enabled"] and update["proration_behavior"] == "create_prorations"
    assert {p["product"] for p in update["products"]} == {"prod_basic", "prod_pro", "prod_studio", "prod_new_2"}
    assert update["default_allowed_updates"] == ["price"]
    assert all(p["adjustable_quantity"] == {"enabled": False} for p in update["products"])
    assert portal["features"]["subscription_cancel"] == {"enabled": True, "mode": "at_period_end"}
    assert portal["features"]["payment_method_update"] == {"enabled": True}
    assert portal["features"]["invoice_history"] == {"enabled": True}
    assert portal["features"]["customer_update"] == {
        "enabled": True,
        "allowed_updates": ["address", "tax_id", "name", "email"],
    }
    assert portal["business_profile"] == {
        "headline": "OnlineDocTranslator subscription",
        "privacy_policy_url": "https://www.onlinedoctranslator.ai/privacy",
        "terms_of_service_url": "https://www.onlinedoctranslator.ai/terms",
    }
    assert studio_price["tax_behavior"] == "exclusive"


def test_setup_flags_a_price_that_includes_vat():
    from scripts import stripe_setup

    prices = {**EXISTING, "price_pro": {**EXISTING["price_pro"], "tax_behavior": "inclusive"}}
    fake = FakeStripe(prices=prices)
    out = []
    stripe_setup.run(fake, ENV, dry_run=True, say=out.append)
    text = "\n".join(out)
    assert "tax_behavior is inclusive" in text
    assert text.count("tax_behavior is") == 1


ALL_PACKS_MISSING = {k: v for k, v in ENV.items() if not k.startswith("STRIPE_PRICE_CREDITS_")}


def test_setup_creates_the_three_credit_packs():
    from scripts import stripe_setup

    fake = FakeStripe(prices=EXISTING, portals=[{"id": "bpc_existing", "metadata": {"traq_portal": "subscription"}}])
    out = []
    result = stripe_setup.run(fake, ALL_PACKS_MISSING, dry_run=False, say=out.append)
    pack_writes = [w for w in fake.writes if w[2].get("metadata", {}).get("credit_pack")]
    products = [w[2] for w in pack_writes if w[0] == "prod"]
    prices = [w[2] for w in pack_writes if w[0] == "price"]
    assert [p["name"] for p in products] == [
        "OnlineDocTranslator – 10 pages",
        "OnlineDocTranslator – 25 pages",
        "OnlineDocTranslator – 50 pages",
    ]
    assert [(p["unit_amount"], p["lookup_key"]) for p in prices] == [
        (1000, "traq_credits_10_eur"),
        (2250, "traq_credits_25_eur"),
        (4000, "traq_credits_50_eur"),
    ]
    for p in prices:
        assert p["currency"] == "eur" and p["tax_behavior"] == "exclusive"
        assert "recurring" not in p
    assert result["created"][-3:] == ["CREDITS_10", "CREDITS_25", "CREDITS_50"]
    text = "\n".join(out)
    for credits, price_id in result["credit_packs"].items():
        assert f"STRIPE_PRICE_CREDITS_{credits}={price_id}" in text


def test_setup_reuses_a_pack_product_found_by_metadata():
    from scripts import stripe_setup

    fake = FakeStripe(prices=EXISTING, products=[{"id": "prod_c10", "metadata": {"credit_pack": "10"}}])
    stripe_setup.run(fake, ALL_PACKS_MISSING, dry_run=False, say=lambda s: None)
    c10 = [w[2] for w in fake.writes if w[0] == "price" and w[2].get("lookup_key") == "traq_credits_10_eur"]
    assert c10[0]["product"] == "prod_c10"
    assert not any(w[0] == "prod" and w[2].get("name") == "OnlineDocTranslator – 10 pages" for w in fake.writes)


def test_webhooks_are_created_with_secrets_only_in_the_file(tmp_path):
    from scripts import stripe_setup

    secrets_file = tmp_path / "secrets.env"
    fake = FakeStripe(prices=EXISTING)
    out = []
    result = stripe_setup.run(fake, ENV, dry_run=False, say=out.append, webhooks=True, secrets_out=str(secrets_file))
    created = [w[2] for w in fake.writes if w[0] == "we"]
    assert created == [
        {
            "url": "https://api.onlinedoctranslator.ai/stripe/webhook",
            "enabled_events": [
                "checkout.session.completed",
                "invoice.payment_succeeded",
                "customer.subscription.updated",
                "customer.subscription.deleted",
            ],
        },
        {
            "url": "https://api.onlinedoctranslator.ai/stripe/connect/webhook",
            "enabled_events": [
                "checkout.session.completed",
                "checkout.session.async_payment_succeeded",
                "account.updated",
                "account.application.deauthorized",
            ],
            "connect": True,
        },
    ]
    assert set(result["webhooks"]) == {"platform", "connect"}
    content = secrets_file.read_text()
    assert content.startswith("stripe_webhook_secret=whsec_secret_")
    assert "\nSTRIPE_CONNECT_WEBHOOK_SECRET=whsec_secret_" in content
    assert (secrets_file.stat().st_mode & 0o777) == 0o600
    assert "whsec_" not in "\n".join(out)


def test_webhooks_found_by_url_are_reused_and_missing_events_added(tmp_path):
    from scripts import stripe_setup

    existing = [
        {"id": "we_platform", "url": "https://api.onlinedoctranslator.ai/stripe/webhook",
         "enabled_events": ["checkout.session.completed", "invoice.payment_succeeded"], "status": "enabled"},
        {"id": "we_connect", "url": "https://api.onlinedoctranslator.ai/stripe/connect/webhook", "application": "ca_1",
         "enabled_events": stripe_setup.WEBHOOKS[1]["events"], "status": "enabled"},
    ]
    secrets_file = tmp_path / "secrets.env"
    fake = FakeStripe(prices=EXISTING, webhooks=existing)
    out = []
    result = stripe_setup.run(fake, ENV, dry_run=False, say=out.append, webhooks=True, secrets_out=str(secrets_file))
    assert result["webhooks"] == {"platform": "we_platform", "connect": "we_connect"}
    assert not any(w[0] == "we" for w in fake.writes)
    modified = [w for w in fake.writes if w[0] == "we_modify"]
    assert len(modified) == 1 and modified[0][1] == ("we_platform",)
    assert modified[0][2]["enabled_events"][-2:] == ["customer.subscription.updated", "customer.subscription.deleted"]
    assert not secrets_file.exists()
    assert "WRONG" not in "\n".join(out)


def test_webhooks_dry_run_writes_nothing():
    from scripts import stripe_setup

    fake = FakeStripe(prices=EXISTING)
    out = []
    result = stripe_setup.run(fake, ENV, dry_run=True, say=out.append, webhooks=True)
    assert fake.writes == []
    assert result["webhooks"] == {"platform": stripe_setup.PLANNED, "connect": stripe_setup.PLANNED}
    assert "platform webhook https://api.onlinedoctranslator.ai/stripe/webhook: would create (4 events)" in "\n".join(out)


def test_with_webhooks_needs_a_secrets_file(monkeypatch):
    from scripts import stripe_setup

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    with pytest.raises(SystemExit):
        stripe_setup.main(["--with-webhooks"])
