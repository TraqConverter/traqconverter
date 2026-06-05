from app.models.translation_segment import TranslationSegment
from app.models.translation_memory import TranslationMemory
from app.services.ai_translation_service import translate_text


def store_segments(db, project_id, team_id, source_language, target_language, paragraphs):

    segment_index = 0

    for text in paragraphs:

        # --------------------------------
        # Clean text
        # --------------------------------
        text = text.strip()

        if not text:
            continue

        text = " ".join(text.split())

        # --------------------------------
        # Translation Memory lookup
        # --------------------------------
        tm_match = db.query(TranslationMemory).filter(
            TranslationMemory.team_id == team_id,
            TranslationMemory.source_language == source_language,
            TranslationMemory.target_language == target_language,
            TranslationMemory.source_text == text
        ).first()

        suggested_translation = None

        if tm_match:

            suggested_translation = tm_match.translated_text

        else:

            # --------------------------------
            # AI translation fallback
            # --------------------------------
            try:

                suggested_translation = translate_text(
                    text,
                    source_language,
                    target_language
                )

                # --------------------------------
                # Store new TM entry
                # --------------------------------
                if suggested_translation:

                    existing_tm = db.query(TranslationMemory).filter(
                        TranslationMemory.team_id == team_id,
                        TranslationMemory.source_language == source_language,
                        TranslationMemory.target_language == target_language,
                        TranslationMemory.source_text == text
                    ).first()

                    if not existing_tm:

                        tm_entry = TranslationMemory(
                            team_id=team_id,
                            source_language=source_language,
                            target_language=target_language,
                            source_text=text,
                            translated_text=suggested_translation
                        )

                        db.add(tm_entry)
                        db.flush()

            except Exception:
                suggested_translation = None

        # --------------------------------
        # Create segment
        # --------------------------------
        segment = TranslationSegment(
            project_id=project_id,
            segment_index=segment_index,
            source_text=text,
            translated_text=suggested_translation
        )

        db.add(segment)

        segment_index += 1

    db.commit()