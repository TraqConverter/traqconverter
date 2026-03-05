from openai import OpenAI
from app.core.settings import settings

client = OpenAI(api_key=settings.openai_api_key)


def translate_text(text, source_lang="English", target_lang="Spanish"):

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": f"Translate from {source_lang} to {target_lang}. Only return the translation."
            },
            {
                "role": "user",
                "content": text
            }
        ]
    )

    return response.choices[0].message.content.strip()