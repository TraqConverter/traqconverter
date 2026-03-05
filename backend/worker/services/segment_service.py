from app.models.translation_segment import TranslationSegment
from app.models.translation_memory import TranslationMemory


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
        # Check Translation Memory
        # --------------------------------
        tm_match = db.query(TranslationMemory).filter(
            TranslationMemory.source_text == text
        ).first()

        suggested_translation = None

        if tm_match:
            suggested_translation = tm_match.translated_text

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