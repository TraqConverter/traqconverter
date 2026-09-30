"""Plan tier definitions used by feature_guard to gate routes.

Tiers
-----
TRIAL  — Given automatically on registration. 7 days, 1 credit, can run a
         single translation but cannot download the result. No Translation
         Memory, Glossary, Templates or Certifications, in the UI or in
         background work.
BASIC  — €19 / 19 credits / month. Full download access, team
         collaboration and templates, but no Translation Memory, Glossary
         or Certifications library.
PRO    — €29 / 29 credits / month. Everything in Basic plus Translation
         Memory, Glossary and Certifications.
"""

PLAN_FEATURES = {
    "TRIAL": {


        "download_translation": False,
        "team_collaboration": False,
        "terminology_memory": False,
        "glossaries": False,
        "certifications": False,
        "template_upload": False,
        "templates": False,
    },
    "BASIC": {
        "download_translation": True,
        "team_collaboration": True,
        "terminology_memory": False,
        "glossaries": False,
        "certifications": False,
        "template_upload": True,
        "templates": True,
    },
    "PRO": {
        "download_translation": True,
        "team_collaboration": True,
        "terminology_memory": True,
        "glossaries": True,
        "certifications": True,
        "template_upload": True,
        "templates": True,
    },
}




SUBSCRIPTION_GRANTS = {
    "BASIC": 19,
    "PRO": 29,
}



TRIAL_DAYS = 7
TRIAL_CREDITS = 1
