from openai import OpenAI
from app.config import settings

client = OpenAI(api_key=settings.OPENAI_API_KEY)

BATCH_SIZE = 20


def translate_text(text: str, source_lang: str, target_lang: str) -> str:

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": f"Translate the following text from {source_lang} to {target_lang}. Only return the translated text."
            },
            {
                "role": "user",
                "content": text
            }
        ]
    )

    return response.choices[0].message.content.strip()


# ============================================================
# BATCH TRANSLATION (Used by Worker)
# ============================================================

def translate_batch(texts: list[str], source_lang: str, target_lang: str):

    prompt = f"""
Translate the following {source_lang} text into {target_lang}.
Return ONLY the translated lines in the same order.
"""

    for i, t in enumerate(texts, 1):
        prompt += f"\n{i}. {t}"

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    output = response.choices[0].message.content

    translations = [
        line.strip()
        for line in output.split("\n")
        if line.strip()
    ]

    return translations