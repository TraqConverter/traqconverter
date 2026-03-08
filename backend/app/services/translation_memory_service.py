from app.models.translation_memory import TranslationMemory


def store_translation(
    db,
    team_id,
    source_language,
    target_language,
    source_text,
    translated_text
):

    # Check if translation already exists
    existing = db.query(TranslationMemory).filter(
        TranslationMemory.team_id == team_id,
        TranslationMemory.source_language == source_language,
        TranslationMemory.target_language == target_language,
        TranslationMemory.source_text == source_text
    ).first()

    if existing:
        return existing

    tm = TranslationMemory(
        team_id=team_id,
        source_language=source_language,
        target_language=target_language,
        source_text=source_text,
        translated_text=translated_text
    )

    db.add(tm)
    db.commit()

    return tm