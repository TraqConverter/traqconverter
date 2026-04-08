from openai import OpenAI
from app.config import settings
import re

client = OpenAI(api_key=settings.OPENAI_API_KEY)

BATCH_SIZE = 20


# ============================================================
# SINGLE TRANSLATION
# ============================================================

def translate_text(text: str, source_lang: str, target_lang: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": f"Translate the following text from {source_lang} to {target_lang}. Only return the translated text. Do not include numbering or extra formatting."
            },
            {
                "role": "user",
                "content": text
            }
        ]
    )

    return response.choices[0].message.content.strip()


# ============================================================
# BATCH TRANSLATION (FIXED)
# ============================================================

def translate_batch(texts: list[str], source_lang: str, target_lang: str):

    # 🔥 CLEAN PROMPT (NO NUMBERING)
    prompt = f"""
Translate the following {source_lang} text into {target_lang}.
Return ONLY the translated lines in the SAME ORDER.
Do NOT include numbering, bullets, or extra text.
"""

    for t in texts:
        prompt += f"\n{t}"

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    output = response.choices[0].message.content

    # 🔥 CLEAN OUTPUT (REMOVE NUMBERING IF MODEL ADDS IT)
    translations = []

    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Remove numbering like "1. ", "2. "
        line = re.sub(r"^\d+\.\s*", "", line)

        translations.append(line)

    return translations