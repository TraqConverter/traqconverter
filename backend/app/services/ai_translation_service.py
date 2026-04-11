from openai import OpenAI
from app.config import settings
import re

from app.services.translation_memory_service import get_tm_entries
from app.services.glossary_service import build_glossary_prompt, get_glossary

client = OpenAI(api_key=settings.OPENAI_API_KEY)

BATCH_SIZE = 20


# ============================================================
# 🔥 GLOSSARY PRE-REPLACEMENT (HARD ENFORCEMENT)
# ============================================================

def apply_glossary_pre_replace(text, glossary_map):
    for src, tgt in glossary_map.items():
        # exact match replacement (safe)
        text = re.sub(rf"\b{re.escape(src)}\b", tgt, text)
    return text


# ============================================================
# SINGLE TRANSLATION
# ============================================================

def translate_text(
    text: str,
    source_lang: str,
    target_lang: str,
    db=None,
    project=None
) -> str:

    glossary_prompt = ""
    glossary_map = {}

    if db and project:
        try:
            glossary_entries = get_glossary(
                db,
                project.team_id,
                source_lang,
                target_lang
            )

            glossary_prompt = build_glossary_prompt(glossary_entries)

            glossary_map = {
                g.source_term: g.target_term
                for g in glossary_entries
            }

            # 🔥 HARD APPLY BEFORE AI
            text = apply_glossary_pre_replace(text, glossary_map)

        except Exception as e:
            print("GLOSSARY ERROR:", e)

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": f"""
You are a professional translator.

Translate from {source_lang} to {target_lang}.

STRICT RULES:
- You MUST follow glossary mappings exactly
- Do NOT change glossary terms
- Do NOT re-translate already translated terms

{glossary_prompt}

Return ONLY the translated text.
"""
            },
            {
                "role": "user",
                "content": text
            }
        ],
        temperature=0
    )

    return response.choices[0].message.content.strip()


# ============================================================
# BATCH TRANSLATION (FINAL FIXED 🔥)
# ============================================================

def translate_batch(
    texts: list[str],
    source_lang: str,
    target_lang: str,
    db=None,
    project=None
):

    tm_context = ""
    glossary_prompt = ""
    glossary_map = {}

    # ========================================================
    # 🔥 LOAD TM
    # ========================================================
    if db and project:
        try:
            tm_entries = []

            for t in texts:
                entries = get_tm_entries(
                    db=db,
                    team_id=project.team_id,
                    source_language=source_lang,
                    target_language=target_lang,
                    source_text=t
                )
                tm_entries.extend(entries)

            unique_tm = {
                e.source_text: e.translated_text
                for e in tm_entries
            }

            if unique_tm:
                tm_context = "\n".join(
                    [f"{k} → {v}" for k, v in unique_tm.items()]
                )

        except Exception as e:
            print("TM ERROR:", e)

    # ========================================================
    # 🔥 LOAD GLOSSARY
    # ========================================================
    if db and project:
        try:
            glossary_entries = get_glossary(
                db,
                project.user_id,
                source_lang,
                target_lang
            )

            glossary_prompt = build_glossary_prompt(glossary_entries)

            glossary_map = {
                g.source_term: g.target_term
                for g in glossary_entries
            }

        except Exception as e:
            print("GLOSSARY ERROR:", e)

    # ========================================================
    # 🔥 HARD APPLY GLOSSARY BEFORE AI (CRITICAL FIX)
    # ========================================================
    if glossary_map:
        texts = [
            apply_glossary_pre_replace(t, glossary_map)
            for t in texts
        ]

    # ========================================================
    # 🔥 PROMPT (STRICT)
    # ========================================================
    prompt = f"""
You are a professional translator.

Translate from {source_lang} to {target_lang}.

STRICT RULES:
- Glossary terms are FINAL and MUST NOT be changed
- If a term is already translated, DO NOT modify it
- Maintain exact meaning and structure

"""

    if glossary_prompt:
        prompt += f"""
MANDATORY GLOSSARY:
{glossary_prompt}
"""

    if tm_context:
        prompt += f"""
REFERENCE TRANSLATIONS:
{tm_context}
"""

    prompt += """
Return ONLY translated lines in the SAME ORDER.
No numbering. No explanations.
"""

    for t in texts:
        prompt += f"\n{t}"

    # ========================================================
    # 🔥 OPENAI CALL
    # ========================================================
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    output = response.choices[0].message.content

    # ========================================================
    # 🔥 CLEAN OUTPUT
    # ========================================================
    translations = []

    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue

        line = re.sub(r"^\d+\.\s*", "", line)
        translations.append(line)

    return translations