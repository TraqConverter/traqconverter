"""One-off Stripe setup: plan and credit-pack prices, the billing portal, optionally webhooks. Safe to re-run.

    cd backend
    STRIPE_SECRET_KEY=sk_... venv/bin/python scripts/stripe_setup.py --dry-run
    STRIPE_SECRET_KEY=sk_... venv/bin/python scripts/stripe_setup.py
    STRIPE_SECRET_KEY=sk_... venv/bin/python scripts/stripe_setup.py --with-webhooks --secrets-out ~/stripe-secrets.env

Prices already set in STRIPE_PRICE_<PLAN> / STRIPE_PRICE_CREDITS_<N> are used as they are. Missing
ones are found by lookup_key (traq_<plan>_monthly_eur, traq_credits_<n>_eur) or created. The portal
configuration is found by its metadata and webhooks by their URL, so a second run changes nothing
it doesn't need to. Webhook signing secrets go only to the --secrets-out file, never to stdout.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.plan_features import CREDIT_PACKS, PLANS, price_lookup_key  # noqa: E402

PORTAL_METADATA_KEY = "traq_portal"
PORTAL_METADATA_VALUE = "subscription"
PORTAL_HEADLINE = "OnlineDocTranslator subscription"
SITE_URL = "https://www.onlinedoctranslator.ai"
API_URL = "https://api.onlinedoctranslator.ai"
CURRENCY = "eur"
PLANNED = "(to be created)"

# Events handled by routers/stripe.py and routers/stripe_connect.py.
WEBHOOKS = [
    {
        "key": "platform",
        "url": f"{API_URL}/stripe/webhook",
        "connect": False,
        "env": "stripe_webhook_secret",
        "events": [
            "checkout.session.completed",
            "invoice.payment_succeeded",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ],
    },
    {
        "key": "connect",
        "url": f"{API_URL}/stripe/connect/webhook",
        "connect": True,
        "env": "STRIPE_CONNECT_WEBHOOK_SECRET",
        "events": [
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
            "account.updated",
            "account.application.deauthorized",
        ],
    },
]


def credit_lookup_key(credits):
    return f"traq_credits_{credits}_eur"


def credit_product_name(credits):
    return f"OnlineDocTranslator – {credits} pages"


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


def _find_product(stripe, value, key="plan_code"):
    for product in _iterate(stripe.Product.list(active=True, limit=100)):
        if _meta(product).get(key) == value:
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


def _plan_cents(plan):
    return round(plan["price_eur"] * 100)


def _check_amount(label, price, expected_cents, say):
    amount = _get(price, "unit_amount")
    currency = (_get(price, "currency") or "").lower()
    flag = ""
    if amount != expected_cents or currency != CURRENCY:
        flag = f"  <-- MISMATCH: expected {expected_cents} {CURRENCY}"
    say(f"  {label}: {_get(price, 'id')} = {amount} {currency}{flag}")
    tax_behavior = _get(price, "tax_behavior")
    if tax_behavior and tax_behavior != "exclusive":
        say(f"    <-- tax_behavior is {tax_behavior}: set it to exclusive, like every price this script creates")
    return not flag


def _plan_price(stripe, plan, env, dry_run, say):
    """(product_id, price_id, source) for one paid plan."""
    code = plan["code"]
    configured = env.get(f"STRIPE_PRICE_{code}")
    if configured:
        price = stripe.Price.retrieve(configured)
        _check_amount(f"{code} (STRIPE_PRICE_{code})", price, _plan_cents(plan), say)
        return _id(_get(price, "product")), configured, "env"

    lookup_key = price_lookup_key(code)
    existing = _find_price_by_lookup_key(stripe, lookup_key)
    if existing:
        _check_amount(f"{code} (lookup_key {lookup_key})", existing, _plan_cents(plan), say)
        return _id(_get(existing, "product")), _get(existing, "id"), "lookup_key"

    product = _find_product(stripe, code)
    if product:
        product_id = _get(product, "id")
    elif dry_run:
        product_id = PLANNED
        say(f"  {code}: would create product 'OnlineDocTranslator {plan['name']}'")
    else:
        product_id = _get(stripe.Product.create(
            name=f"OnlineDocTranslator {plan['name']}",
            metadata={"plan_code": code},
        ), "id")
        say(f"  {code}: created product {product_id}")

    unit_amount = _plan_cents(plan)
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


def _credit_pack_price(stripe, pack, env, dry_run, say):
    """(price_id, source) for one credit pack: env, then lookup_key, then a new one-time price."""
    credits, cents = pack["credits"], pack["price_cents"]
    name = f"STRIPE_PRICE_CREDITS_{credits}"
    configured = env.get(name)
    if configured:
        _check_amount(name, stripe.Price.retrieve(configured), cents, say)
        return configured, "env"

    lookup_key = credit_lookup_key(credits)
    existing = _find_price_by_lookup_key(stripe, lookup_key)
    if existing:
        _check_amount(f"{name} (lookup_key {lookup_key})", existing, cents, say)
        return _get(existing, "id"), "lookup_key"

    title = credit_product_name(credits)
    product = _find_product(stripe, str(credits), key="credit_pack")
    if product:
        product_id = _get(product, "id")
    elif dry_run:
        product_id = PLANNED
        say(f"  {name}: would create product '{title}'")
    else:
        product_id = _get(stripe.Product.create(name=title, metadata={"credit_pack": str(credits)}), "id")
        say(f"  {name}: created product {product_id}")

    if dry_run:
        say(f"  {name}: would create one-time price {cents} {CURRENCY}, lookup_key {lookup_key}")
        return PLANNED, "planned"
    price = stripe.Price.create(
        product=product_id,
        currency=CURRENCY,
        unit_amount=cents,
        tax_behavior="exclusive",
        lookup_key=lookup_key,
        metadata={"credit_pack": str(credits)},
    )
    say(f"  {name}: created price {_get(price, 'id')}")
    return _get(price, "id"), "created"


def _setup_webhook(stripe, spec, dry_run, say):
    """(endpoint_id, signing_secret or None); a secret only exists for a newly created endpoint."""
    label = f"{spec['key']} webhook {spec['url']}"
    found = None
    for endpoint in _iterate(stripe.WebhookEndpoint.list(limit=100)):
        if _get(endpoint, "url") == spec["url"]:
            found = endpoint
            break
    if found:
        endpoint_id = _get(found, "id")
        events = list(_get(found, "enabled_events", []) or [])
        missing = [e for e in spec["events"] if e not in events and "*" not in events]
        is_connect = bool(_get(found, "application"))
        if is_connect != spec["connect"]:
            say(f"  {label}: {endpoint_id} listens to {'connected accounts' if is_connect else 'your account'}"
                f"  <-- WRONG: delete it in the Dashboard and re-run")
        changes = {}
        if missing:
            changes["enabled_events"] = events + missing
        if _get(found, "status") == "disabled":
            changes["disabled"] = False
        if not changes:
            say(f"  {label}: {endpoint_id} already set up")
        elif dry_run:
            say(f"  {label}: would update {endpoint_id} ({', '.join(sorted(changes))})")
        else:
            stripe.WebhookEndpoint.modify(endpoint_id, **changes)
            say(f"  {label}: updated {endpoint_id} ({', '.join(sorted(changes))})")
        return endpoint_id, None
    if dry_run:
        say(f"  {label}: would create ({len(spec['events'])} events)")
        return PLANNED, None
    params = {"url": spec["url"], "enabled_events": spec["events"]}
    if spec["connect"]:
        params["connect"] = True
    endpoint = stripe.WebhookEndpoint.create(**params)
    say(f"  {label}: created {_get(endpoint, 'id')}")
    return _get(endpoint, "id"), _get(endpoint, "secret")


def write_secrets(path, secrets):
    """Writes NAME=value lines to a file only the owner can read."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(path, 0o600)
    with os.fdopen(fd, "w") as fh:
        for name, value in secrets.items():
            fh.write(f"{name}={value}\n")


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
        # Billing details stay editable for invoices (and for Stripe Tax, if STRIPE_AUTOMATIC_TAX is ever on).
        "customer_update": {"enabled": True, "allowed_updates": ["address", "tax_id", "name", "email"]},
    }


def run(stripe, env, dry_run=False, say=print, webhooks=False, secrets_out=None):
    """Set up Stripe; returns prices, credit packs, portal, created items and (with webhooks) endpoint ids."""
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
    pack_prices = {}
    for pack in CREDIT_PACKS:
        price_id, source = _credit_pack_price(stripe, pack, env, dry_run, say)
        pack_prices[pack["credits"]] = price_id
        if source in ("created", "planned"):
            created.append(f"CREDITS_{pack['credits']}")

    endpoints = {}
    if webhooks:
        say("\nWebhooks")
        secrets = {}
        for spec in WEBHOOKS:
            endpoint_id, secret = _setup_webhook(stripe, spec, dry_run, say)
            endpoints[spec["key"]] = endpoint_id
            if secret:
                secrets[spec["env"]] = secret
        if secrets and secrets_out:
            write_secrets(secrets_out, secrets)
            say(f"  signing secrets for {', '.join(secrets)} written to {secrets_out} (mode 600)")
        elif secrets:
            say("  signing secrets NOT saved: no --secrets-out given; roll them in the Dashboard")
        elif not dry_run:
            say("  no new endpoints, so no new signing secrets; existing ones are in the Dashboard")

    say("\nSummary")
    for code, (product_id, price_id) in plan_prices.items():
        say(f"  {code}: price {price_id} (product {product_id})")
    say(f"  portal configuration: {portal_id}")
    for key_name, endpoint_id in endpoints.items():
        say(f"  {key_name} webhook: {endpoint_id}")
    say("\nSet these env vars on the backend:")
    for code in ("STUDIO", "AGENCY"):
        say(f"  STRIPE_PRICE_{code}={plan_prices[code][1]}")
    for credits, price_id in pack_prices.items():
        say(f"  STRIPE_PRICE_CREDITS_{credits}={price_id}")
    say(f"  STRIPE_PORTAL_CONFIGURATION={portal_id}")
    result = {
        "prices": {code: price_id for code, (_, price_id) in plan_prices.items()},
        "credit_packs": pack_prices,
        "portal": portal_id,
        "created": created,
    }
    if webhooks:
        result["webhooks"] = endpoints
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="read from Stripe, change nothing")
    parser.add_argument("--with-webhooks", action="store_true", help="also create or find the two webhook endpoints")
    parser.add_argument("--secrets-out", help="file for new webhook signing secrets (chmod 600); never printed")
    args = parser.parse_args(argv)
    if args.with_webhooks and not args.dry_run and not args.secrets_out:
        parser.error("--with-webhooks needs --secrets-out: a new endpoint's signing secret is shown only once")

    key = os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("stripe_secret_key")
    if not key:
        sys.exit("Set STRIPE_SECRET_KEY (or stripe_secret_key) in the environment.")

    import stripe

    stripe.api_key = key
    run(
        stripe,
        dict(os.environ),
        dry_run=args.dry_run,
        webhooks=args.with_webhooks,
        secrets_out=args.secrets_out and os.path.expanduser(args.secrets_out),
    )


if __name__ == "__main__":
    main()
