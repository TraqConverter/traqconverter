from sqlalchemy.orm import Session
from app.models.translation_memory import TranslationMemory


# =========================================
# GET TM ENTRIES (OPTIONAL FILTER 🔥 FIX)
# =========================================
def get_tm_entries(
    db: Session,
    team_id,
    source_language: str,
    target_language: str,
    source_text: str | None = None,   # ✅ FIX: optional filter
):
    query = db.query(TranslationMemory).filter(
        TranslationMemory.team_id == team_id,
        TranslationMemory.source_language == source_language,
        TranslationMemory.target_language == target_language
    )

    # ✅ OPTIONAL EXACT MATCH FILTER
    if source_text:
        query = query.filter(
            TranslationMemory.source_text == source_text
        )

    return query.all()


# =========================================
# FIND EXACT MATCH
# =========================================
def find_tm_match(
    db: Session,
    team_id,
    source_language: str,
    target_language: str,
    source_text: str
):
    entry = db.query(TranslationMemory).filter(
        TranslationMemory.team_id == team_id,
        TranslationMemory.source_language == source_language,
        TranslationMemory.target_language == target_language,
        TranslationMemory.source_text == source_text
    ).first()

    if entry:
        return entry.translated_text

    return None


# =========================================
# STORE ENTRY
# =========================================
def store_tm_entry(
    db: Session,
    team_id,
    source_language: str,
    target_language: str,
    source_text: str,
    translated_text: str
):
    entry = TranslationMemory(
        team_id=team_id,
        source_language=source_language,
        target_language=target_language,
        source_text=source_text,
        translated_text=translated_text
    )

    db.add(entry)
    db.commit()
    db.refresh(entry)

    return entry