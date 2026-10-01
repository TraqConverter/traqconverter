"""One-off Stripe setup: plan prices and the billing portal configuration. Safe to re-run.

    cd backend
    STRIPE_SECRET_KEY=sk_... venv/bin/python scripts/stripe_setup.py --dry-run
    STRIPE_SECRET_KEY=sk_... venv/bin/python scripts/stripe_setup.py

Prices already set in STRIPE_PRICE_<PLAN> are used as they are. Missing ones are found by
lookup_key (traq_<plan>_monthly_eur) or created. The portal configuration is found by its
metadata and updated in place, so a second run changes nothing it doesn't need to.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.plan_features import CREDIT_PACKS, PLANS, price_lookup_key  # noqa: E402

PORTAL_METADATA_KEY = "traq_portal"
PORTAL_METADATA_VALUE = "subscription"
PORTAL_HEADLINE = "TraqConverter subscription"
SITE_URL = "https://www.onlinedoctranslator.ai"
CURRENCY = "eur"
PLANNED = "(to be created)"


def _get(obj, key, default=None):
    value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return default if value is None else value


def _id(value):
    return _get(value, "id") if isinstance(value, dict) or hasattr(value, "id") else value


def _meta(obj):
    return _get(obj, "metadata", {}) or {}


def _iterate(listing):
    auto = getattr(listing, "auto_paging_iter", None)
    return auto() if callable(auto) else (_get(listing, "data", []) or [])


def _find_product(stripe, plan_code):
    for product in _iterate(stripe.Product.list(active=True, limit=100)):
        if _meta(product).get("plan_code") == plan_code:
            return product
    return None


def _find_price_by_lookup_key(stripe, lookup_key):
    listing = stripe.Price.list(lookup_keys=[lookup_key], active=True, limit=1)
    data = _get(listing, "data", []) or []
    return data[0] if data else None


def _find_portal_configuration(stripe):
    for cfg in _iterate(stripe.billing_portal.Configuration.list(active=True, limit=100)):
        if _meta(cfg).get(PORTAL_METADATA_KEY) == PORTAL_METADATA_VALUE:
            return cfg
    return None


def _check_amount(label, price, price_eur, say):
    amount = _get(price, "unit_amount")
    currency = (_get(price, "currency") or "").lower()
    expected = int(round(price_eur * 100))
    flag = ""
    if amount != expected or currency != CURRENCY:
        flag = f"  <-- MISMATCH: PLANS says {expected} {CURRENCY}"
    say(f"  {label}: {_get(price, 'id')} = {amount} {currency}{flag}")
    tax_behavior = _get(price, "tax_behavior")
    if tax_behavior and tax_behavior != "exclusive":
        say(f"    <-- tax_behavior is {tax_behavior}: prices exclude VAT, set it to exclusive")
    return not flag


def _plan_price(stripe, plan, env, dry_run, say):
    """(product_id, price_id, source) for one paid plan."""
    code = plan["code"]
    configured = env.get(f"STRIPE_PRICE_{code}")
    if configured:
        price = stripe.Price.retrieve(configured)
        _check_amount(f"{code} (STRIPE_PRICE_{code})", price, plan["price_eur"], say)
        return _id(_get(price, "product")), configured, "env"

    lookup_key = price_lookup_key(code)
    existing = _find_price_by_lookup_key(stripe, lookup_key)
    if existing:
        _check_amount(f"{code} (lookup_key {lookup_key})", existing, plan["price_eur"], say)
        return _id(_get(existing, "product")), _get(existing, "id"), "lookup_key"

    product = _find_product(stripe, code)
    if product:
        product_id = _get(product, "id")
    elif dry_run:
        product_id = PLANNED
        say(f"  {code}: would create product 'TraqConverter {plan['name']}'")
    else:
        product_id = _get(stripe.Product.create(
            name=f"TraqConverter {plan['name']}",
            metadata={"plan_code": code},
        ), "id")
        say(f"  {code}: created product {product_id}")

    unit_amount = int(round(plan["price_eur"] * 100))
    if dry_run:
        say(f"  {code}: would create price {unit_amount} {CURRENCY}/month, lookup_key {lookup_key}")
        return product_id, PLANNED, "planned"
    price = stripe.Price.create(
        product=product_id,
        currency=CURRENCY,
        unit_amount=unit_amount,
        recurring={"interval": "month"},
        tax_behavior="exclusive",
        lookup_key=lookup_key,
        metadata={"plan_code": code},
    )
    say(f"  {code}: created price {_get(price, 'id')}")
    return product_id, _get(price, "id"), "created"


def portal_features(plan_prices):
    """Portal features allowing a switch between every paid plan's price, never a quantity change."""
    products = {}
    for product_id, price_id in plan_prices.values():
        products.setdefault(product_id, []).append(price_id)
    return {
        "subscription_update": {
            "enabled": True,
            "default_allowed_updates": ["price"],
            "proration_behavior": "create_prorations",
            # A subscription grants one plan's credits whatever its quantity.
            "products": [
                {"product": p, "prices": prices, "adjustable_quantity": {"enabled": False}}
                for p, prices in products.items()
            ],
        },
        "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
        "payment_method_update": {"enabled": True},
        "invoice_history": {"enabled": True},
        # Billing address and VAT ID stay editable so Stripe Tax is right on renewals.
        "customer_update": {"enabled": True, "allowed_updates": ["address", "tax_id", "name", "email"]},
    }


def run(stripe, env, dry_run=False, say=print):
    """Set up Stripe; returns {"prices": {plan: price_id}, "portal": config_id, "created": [...]}."""
    say("DRY RUN: nothing will be created or changed." if dry_run else "Applying changes.")
    key = env.get("STRIPE_SECRET_KEY") or env.get("stripe_secret_key") or ""
    say(f"Stripe mode: {'LIVE' if key.startswith(('sk_live', 'rk_live')) else 'test'}")

    say("\nPlan prices")
    plan_prices = {}
    created = []
    for plan in PLANS:
        product_id, price_id, source = _plan_price(stripe, plan, env, dry_run, say)
        plan_prices[plan["code"]] = (product_id, price_id)
        if source in ("created", "planned"):
            created.append(plan["code"])

    say("\nBilling portal")
    features = portal_features(plan_prices)
    params = {
        "features": features,
        "business_profile": {
            "headline": PORTAL_HEADLINE,
            "privacy_policy_url": f"{SITE_URL}/privacy",
            "terms_of_service_url": f"{SITE_URL}/terms",
        },
        "metadata": {PORTAL_METADATA_KEY: PORTAL_METADATA_VALUE},
    }
    existing = _find_portal_configuration(stripe)
    if existing:
        portal_id = _get(existing, "id")
        if dry_run:
            say(f"  would update configuration {portal_id}")
        else:
            stripe.billing_portal.Configuration.modify(portal_id, **params)
            say(f"  updated configuration {portal_id}")
    elif dry_run:
        portal_id = PLANNED
        say("  would create a configuration")
    else:
        portal_id = _get(stripe.billing_portal.Configuration.create(**params), "id")
        say(f"  created configuration {portal_id}")

    say("\nCredit packs")
    for pack in CREDIT_PACKS:
        name = f"STRIPE_PRICE_CREDITS_{pack['credits']}"
        price_id = env.get(name)
        if not price_id:
            say(f"  {name}: not set")
            continue
        _check_amount(name, stripe.Price.retrieve(price_id), pack["price_eur"], say)

    say("\nSummary")
    for code, (product_id, price_id) in plan_prices.items():
        say(f"  {code}: price {price_id} (product {product_id})")
    say(f"  portal configuration: {portal_id}")
    say("\nSet these env vars on the backend:")
    for code in ("STUDIO", "AGENCY"):
        say(f"  STRIPE_PRICE_{code}={plan_prices[code][1]}")
    say(f"  STRIPE_PORTAL_CONFIGURATION={portal_id}")
    return {
        "prices": {code: price_id for code, (_, price_id) in plan_prices.items()},
        "portal": portal_id,
        "created": created,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="read from Stripe, change nothing")
    args = parser.parse_args(argv)

    key = os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("stripe_secret_key")
    if not key:
        sys.exit("Set STRIPE_SECRET_KEY (or stripe_secret_key) in the environment.")

    import stripe

    stripe.api_key = key
    run(stripe, dict(os.environ), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
