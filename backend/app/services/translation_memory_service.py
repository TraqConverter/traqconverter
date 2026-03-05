from sqlalchemy.orm import Session
from app.models.translation_memory import TranslationMemory


def find_translation(db: Session, source_text: str):

    match = db.query(TranslationMemory).filter(
        TranslationMemory.source_text == source_text
    ).first()

    if match:
        return match.translated_text

    return None


def store_translation(db: Session, source_text: str, translated_text: str):

    existing = db.query(TranslationMemory).filter(
        TranslationMemory.source_text == source_text
    ).first()

    if existing:
        return

    tm = TranslationMemory(
        source_text=source_text,
        translated_text=translated_text
    )

    db.add(tm)
    db.commit()