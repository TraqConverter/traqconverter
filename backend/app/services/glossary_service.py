from sqlalchemy.orm import Session
from app.models.glossary import Glossary


# ============================================================
# Fetch glossary by team (audit HIGH-2: column was misnamed
# `user_id` while actually FK'ing teams.id).
# Callers may still pass a positional `team_id` value.
# ============================================================

def get_glossary(
    db: Session,
    team_id,
    source_language,
    target_language,
):
    return (
        db.query(Glossary)
        .filter(
            Glossary.team_id == team_id,
            Glossary.source_language == source_language,
            Glossary.target_language == target_language,
        )
        .all()
    )


def build_glossary_prompt(glossary_entries):
    if not glossary_entries:
        return ""

    prompt = "\n\nMANDATORY GLOSSARY (DO NOT CHANGE THESE TERMS):\n"

    for g in glossary_entries:
        prompt += f"{g.source_term} → {g.target_term}\n"

    prompt += "\nYou MUST use these exact translations when matches occur.\n"
    return prompt
