from app.models.translation_segment import TranslationSegment
from app.models.translation_memory import TranslationMemory
from app.services.ai_translation_service import translate_text


def store_segments(db, project_id, paragraphs):

    segment_index = 0

    for text in paragraphs:

        # --------------------------------
        # Clean text
        # --------------------------------
        text = text.strip()

        # Skip empty segments
        if not text:
            continue

        # Normalize whitespace
        text = " ".join(text.split())

        # --------------------------------
        # Translation Memory lookup
        # --------------------------------
        tm_match = db.query(TranslationMemory).filter(
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
                suggested_translation = translate_text(text)
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