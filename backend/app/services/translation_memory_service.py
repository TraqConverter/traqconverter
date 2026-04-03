from sqlalchemy.orm import Session
from app.models.translation_memory import TranslationMemory


def find_tm_match(
    db: Session,
    team_id: int,
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


def store_tm_entry(
    db: Session,
    team_id: int,
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