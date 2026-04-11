from sqlalchemy.orm import Session
from app.models.glossary import Glossary


# ============================================================
# 🔥 FIXED: USE user_id INSTEAD OF team_id
# ============================================================

def get_glossary(
    db: Session,
    user_id,
    source_language,
    target_language,
):
    return db.query(Glossary).filter(
        Glossary.user_id == user_id,
        Glossary.source_language == source_language,
        Glossary.target_language == target_language
    ).all()


# ============================================================
# 🔥 IMPROVED PROMPT (STRONGER ENFORCEMENT)
# ============================================================

def build_glossary_prompt(glossary_entries):
    if not glossary_entries:
        return ""

    prompt = "\n\nMANDATORY GLOSSARY (DO NOT CHANGE THESE TERMS):\n"

    for g in glossary_entries:
        prompt += f"{g.source_term} → {g.target_term}\n"

    prompt += "\nYou MUST use these exact translations when matches occur.\n"

    return prompt