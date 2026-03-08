import logging
from openai import OpenAI

from worker.services.db_service import get_db
from app.models.translation_segment import TranslationSegment
from app.services.translation_memory_service import find_tm_match, store_tm_entry

logger = logging.getLogger(__name__)

client = OpenAI()

BATCH_SIZE = 20


def translate_batch(texts, source_lang, target_lang):

    prompt = f"""
Translate the following {source_lang} text into {target_lang}.
Return ONLY the translated lines in the same order.
"""

    for i, t in enumerate(texts, 1):
        prompt += f"\n{i}. {t}"

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    output = response.choices[0].message.content

    translations = [
        line.strip()
        for line in output.split("\n")
        if line.strip()
    ]

    return translations


def process_translation(file_path):

    db = get_db()

    try:

        segments = db.query(TranslationSegment).filter(
            TranslationSegment.translated_text == None
        ).order_by(
            TranslationSegment.segment_index
        ).all()

        if not segments:
            return

        source_lang = segments[0].source_language
        target_lang = segments[0].target_language
        team_id = segments[0].team_id

        ai_queue = []

        for segment in segments:

            tm_translation = find_tm_match(
                db,
                team_id,
                source_lang,
                target_lang,
                segment.source_text
            )

            if tm_translation:

                segment.translated_text = tm_translation
                logger.info("TM match used")

            else:

                ai_queue.append(segment)

        db.commit()

        # -------------------------
        # Batch translate remaining
        # -------------------------

        for i in range(0, len(ai_queue), BATCH_SIZE):

            batch = ai_queue[i:i+BATCH_SIZE]

            texts = [s.source_text for s in batch]

            translations = translate_batch(
                texts,
                source_lang,
                target_lang
            )

            for segment, translated in zip(batch, translations):

                segment.translated_text = translated

                store_tm_entry(
                    db,
                    team_id,
                    source_lang,
                    target_lang,
                    segment.source_text,
                    translated
                )

            db.commit()

            logger.info(f"Translated {len(batch)} segments via AI")

    finally:

        db.close()