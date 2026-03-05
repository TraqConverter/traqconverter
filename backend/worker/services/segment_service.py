from app.models.translation_segment import TranslationSegment


def store_segments(db, project_id, paragraphs):

    for index, text in enumerate(paragraphs):

        segment = TranslationSegment(
            project_id=project_id,
            segment_index=index,
            source_text=text
        )

        db.add(segment)

    db.commit()