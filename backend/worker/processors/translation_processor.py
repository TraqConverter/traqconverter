import logging
from openai import OpenAI

from worker.services.db_service import get_db
from app.models.translation_segment import TranslationSegment

logger = logging.getLogger(__name__)

client = OpenAI()

BATCH_SIZE = 20


def translate_batch(source_texts, source_lang, target_lang):

    prompt = f"""
Translate the following {source_lang} text into {target_lang}.

Return ONLY the translated lines in the same order.
Do not add numbering or explanations.

Texts:
"""

    for i, text in enumerate(source_texts, 1):
        prompt += f"\n{i}. {text}"

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

        for i in range(0, len(segments), BATCH_SIZE):

            batch = segments[i:i+BATCH_SIZE]

            source_texts = [s.source_text for s in batch]

            translations = translate_batch(
                source_texts,
                source_lang,
                target_lang
            )

            for segment, translated in zip(batch, translations):

                segment.translated_text = translated

            db.commit()

            logger.info(f"Translated batch of {len(batch)} segments")

    finally:

        db.close()