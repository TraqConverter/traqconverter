"""Plan tier definitions used by feature_guard to gate routes.

Tiers
-----
TRIAL  — Given automatically on registration. 7 days, 1 credit, can run a
         single translation but cannot download the result. No advanced
         features.
BASIC  — €19 / 19 credits / month. Full download access and team
         collaboration, but no Translation Memory, Glossary or
         Certifications library.
PRO    — €29 / 29 credits / month. Everything in Basic plus Translation
         Memory, Glossary and Certifications.
"""

PLAN_FEATURES = {
    "TRIAL": {
        # The trial intentionally blocks delivery so users have to subscribe
        # before they can ship the translated file.
        "download_translation": False,
        "team_collaboration": False,
        "terminology_memory": False,
        "glossaries": False,
        "certifications": False,
    },
    "BASIC": {
        "download_translation": True,
        "team_collaboration": True,
        "terminology_memory": False,
        "glossaries": False,
        "certifications": False,
    },
    "PRO": {
        "download_translation": True,
        "team_collaboration": True,
        "terminology_memory": True,
        "glossaries": True,
        "certifications": True,
    },
}


# What each plan grants on the wallet when the Stripe webhook processes a
# successful subscription invoice. Looked up by plan name.
SUBSCRIPTION_GRANTS = {
    "BASIC": 19,
    "PRO": 29,
}


# Days the registration-time trial lasts.
TRIAL_DAYS = 7
TRIAL_CREDITS = 1
