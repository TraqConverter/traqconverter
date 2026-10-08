"""Plan tier definitions used by feature_guard to gate routes.

Tiers
-----
TRIAL  — Given automatically on registration. 7 days, 3 credits, can run
         test translations but cannot download the result. No Translation
         Memory, Glossary, Templates, Media or Certifications, in the UI or
         in background work.
BASIC  — €19 / 19 credits / month. Full download access, team
         collaboration, templates and the media library, but no Translation Memory, Glossary
         or Certifications library.
PRO    — €29 / 29 credits / month. Everything in Basic plus Translation
         Memory, Glossary and Certifications.
STUDIO — €79 / 100 credits / month. Everything in Pro, 5 team members.
AGENCY — €249 / 400 credits / month. Everything in Pro, 20 team members,
         and its jobs are claimed first by the worker.

Display prices, page counts and seat limits live in PLANS below; every
other table here is derived from it, and the frontend reads it through
GET /billing/plans.
"""

SALES_EMAIL = "info@lumaxdigital.co.uk"

TRIAL_DAYS = 7
TRIAL_CREDITS = 3

_PRO_FEATURES = {
    "download_translation": True,
    "team_collaboration": True,
    "terminology_memory": True,
    "glossaries": True,
    "certifications": True,
    "template_upload": True,
    "templates": True,
    "media": True,
}

PLAN_FEATURES = {
    "TRIAL": {
        "download_translation": False,
        "team_collaboration": False,
        "terminology_memory": False,
        "glossaries": False,
        "certifications": False,
        "template_upload": False,
        "templates": False,
        "media": False,
    },
    "BASIC": {
        "download_translation": True,
        "team_collaboration": True,
        "terminology_memory": False,
        "glossaries": False,
        "certifications": False,
        "template_upload": True,
        "templates": True,
        "media": True,
    },
    "PRO": dict(_PRO_FEATURES),
    "STUDIO": dict(_PRO_FEATURES),
    "AGENCY": dict(_PRO_FEATURES),
}

# Paid plans, cheapest first. price_eur and credits are what customers see; Stripe must match.
PLANS = [
    {
        "code": "BASIC",
        "name": "Basic",
        "price_eur": 19,
        "credits": 19,
        "seats": 2,
        "priority": False,
        "blurb": "For freelancers translating a few documents a month.",
    },
    {
        "code": "PRO",
        "name": "Pro",
        "price_eur": 29,
        "credits": 29,
        "seats": 3,
        "priority": False,
        "blurb": "Translation memory, glossary and your certification page.",
    },
    {
        "code": "STUDIO",
        "name": "Studio",
        "price_eur": 79,
        "credits": 100,
        "seats": 5,
        "priority": False,
        "blurb": "For busy translators and small studios.",
    },
    {
        "code": "AGENCY",
        "name": "Agency",
        "price_eur": 249,
        "credits": 400,
        "seats": 20,
        "priority": True,
        "blurb": "For agencies with a steady flow of certified work.",
    },
]

PAID_PLANS = tuple(p["code"] for p in PLANS)

SUBSCRIPTION_GRANTS = {p["code"]: p["credits"] for p in PLANS}


def price_lookup_key(plan: str) -> str:
    """The lookup_key scripts/stripe_setup.py gives a plan's monthly EUR price."""
    return f"traq_{plan.lower()}_monthly_eur"

# Team size including the owner.
SEAT_LIMITS = {"TRIAL": 1, **{p["code"]: p["seats"] for p in PLANS}}

# Higher is claimed first by the job queue.
JOB_PRIORITY = {p["code"]: 1 for p in PLANS if p["priority"]}

TRIAL_PLAN = {
    "code": "TRIAL",
    "name": "Free trial",
    "price_eur": 0,
    "credits": TRIAL_CREDITS,
    "days": TRIAL_DAYS,
    "seats": SEAT_LIMITS["TRIAL"],
}

# Sold to active subscribers only. price_cents is what Stripe's unit_amount must be.
CREDIT_PACKS = [
    {"credits": 10, "price_cents": 1000, "name": "Starter pack", "note": "Top up a small project"},
    {"credits": 25, "price_cents": 2250, "name": "Standard pack", "note": "For a few documents"},
    {"credits": 50, "price_cents": 4000, "name": "Scale pack", "note": "For a busy month"},
]


def credit_pack_prices(pack: dict) -> dict:
    """Euro price, price per page, and the per-page saving against the smallest pack."""
    base = CREDIT_PACKS[0]["price_cents"] / CREDIT_PACKS[0]["credits"]
    per_page = pack["price_cents"] / pack["credits"]
    return {
        "price_eur": pack["price_cents"] / 100,
        "price_per_page_eur": round(per_page / 100, 2),
        "save_percent": round((1 - per_page / base) * 100),
    }


def next_plan_with_more_seats(plan: str):
    """The cheapest paid plan with more seats than `plan`, or None."""
    current = SEAT_LIMITS.get(plan, 0)
    return next((p for p in PLANS if p["seats"] > current), None)
