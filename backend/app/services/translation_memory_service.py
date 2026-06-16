from sqlalchemy.orm import Session
from app.models.translation_memory import TranslationMemory





def get_tm_entries(
    db: Session,
    team_id,
    source_language: str,
    target_language: str,
    source_text: str | None = None,
):
    query = db.query(TranslationMemory).filter(
        TranslationMemory.team_id == team_id,
        TranslationMemory.source_language == source_language,
        TranslationMemory.target_language == target_language
    )


    if source_text:
        query = query.filter(
            TranslationMemory.source_text == source_text
        )

    return query.all()





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







_TM_MAX_SOURCE_LEN = 1500





def store_tm_entry(
    db: Session,
    team_id,
    source_language: str,
    target_language: str,
    source_text: str,
    translated_text: str
):
    """Persist a translation pair to the TM table.

    Returns None when the entry was skipped (too long for the btree
    index, or empty). Rolls back the session on any other failure so
    the caller's outer transaction can keep going — TM is best-effort
    metadata and must never crash the parent translation job.
    """
    if not source_text or not translated_text:
        return None
    if len(source_text) > _TM_MAX_SOURCE_LEN:

        return None

    entry = TranslationMemory(
        team_id=team_id,
        source_language=source_language,
        target_language=target_language,
        source_text=source_text,
        translated_text=translated_text,
    )

    try:
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry
    except Exception:



        try:
            db.rollback()
        except Exception:
            pass
        raise