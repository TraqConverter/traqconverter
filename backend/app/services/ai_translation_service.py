from openai import OpenAI
from sqlalchemy import update
from app.config import settings
import re

from app.services.translation_memory_service import get_tm_entries
from app.services.glossary_service import build_glossary_prompt, get_glossary
from app.models.glossary import Glossary

client = OpenAI(api_key=settings.OPENAI_API_KEY)

BATCH_SIZE = 20


# ============================================================
# GLOSSARY PRE-REPLACEMENT (HARD ENFORCEMENT)
# Counts matches per glossary entry id and returns the updated text
# alongside a {entry_id: matches_in_this_text} dict.
# ============================================================
def apply_glossary_pre_replace(text, glossary_map):
    """Backwards-compatible string-only replacement.

    glossary_map is a {source_term: target_term} dict. Returns the rewritten
    text. Used by call sites that don't track usage counts.
    """
    for src, tgt in glossary_map.items():
        text = re.sub(rf"\b{re.escape(src)}\b", tgt, text)
    return text


def apply_glossary_with_counts(text: str, glossary_entries):
    """Run glossary substitution and return (text, {term_id: match_count}).

    glossary_entries is a list of Glossary ORM objects. Replacement is the
    same word-boundary regex as apply_glossary_pre_replace; the only addition
    is counting how many substitutions happened per entry id.
    """
    counts: dict[str, int] = {}
    for g in glossary_entries:
        if not g.source_term or not g.target_term:
            continue
        text, n = re.subn(
            rf"\b{re.escape(g.source_term)}\b",
            g.target_term,
            text,
        )
        if n > 0:
            counts[str(g.id)] = counts.get(str(g.id), 0) + n
    return text, counts


def flush_glossary_usage(db, counts: dict[str, int]) -> None:
    """Increment usage_count on each glossary row by the number of matches.

    Called once per batch so we don't issue a query per replacement. Errors
    are swallowed because counter drift is preferable to a translation
    failure rolling back over a metric write.
    """
    if not counts or db is None:
        return
    try:
        for term_id, n in counts.items():
            db.execute(
                update(Glossary)
                .where(Glossary.id == term_id)
                .values(usage_count=Glossary.usage_count + n)
            )
        db.commit()
    except Exception as e:
        print("GLOSSARY USAGE WRITE ERROR:", e)
        try:
            db.rollback()
        except Exception:
            pass


# ============================================================
# SAFE TEAM RESOLUTION
# ============================================================
def get_project_scope(project):
    """
    Standardize glossary + TM scope.
    Always prefer team_id (canonical).
    """
    if hasattr(project, "team_id") and project.team_id:
        return project.team_id

    # fallback (should never happen ideally)
    return getattr(project, "user_id", None)


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
            scope_id = get_project_scope(project)

            glossary_entries = get_glossary(
                db,
                scope_id,  # ✅ FIXED
                source_lang,
                target_lang
            )

            glossary_prompt = build_glossary_prompt(glossary_entries)

            glossary_map = {
                g.source_term: g.target_term
                for g in glossary_entries
            }

            # Replace + count matches so usage_count auto-updates.
            text, usage_counts = apply_glossary_with_counts(text, glossary_entries)
            flush_glossary_usage(db, usage_counts)

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
# BATCH TRANSLATION (FIXED)
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

    # 🔧 STANDARDIZED SCOPE
    scope_id = get_project_scope(project) if project else None

    # ========================================================
    # LOAD TM (TEAM SCOPED)
    # ========================================================
    if db and project and scope_id:
        try:
            tm_entries = []

            for t in texts:
                entries = get_tm_entries(
                    db=db,
                    team_id=scope_id,  # ✅ FIXED
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
    # LOAD GLOSSARY (TEAM SCOPED)
    # ========================================================
    if db and project and scope_id:
        try:
            glossary_entries = get_glossary(
                db,
                scope_id,  # ✅ FIXED
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
    # APPLY GLOSSARY BEFORE AI (and roll up usage counts)
    # ========================================================
    if glossary_map:
        # Use the counting variant so we can credit the underlying glossary
        # rows. Sum counts across the whole batch and write once at the end.
        glossary_entries = locals().get("glossary_entries", [])
        batch_counts: dict[str, int] = {}
        rewritten: list[str] = []
        for t in texts:
            new_t, counts = apply_glossary_with_counts(t, glossary_entries)
            rewritten.append(new_t)
            for k, v in counts.items():
                batch_counts[k] = batch_counts.get(k, 0) + v
        texts = rewritten
        flush_glossary_usage(db, batch_counts)

    # ========================================================
    # PROMPT — uses an unambiguous delimiter so segments containing
    # newlines (PDF blocks, multi-line OCR) align correctly with the
    # model's response.
    # ========================================================
    DELIM = "<<<SEG>>>"

    rules = f"""You are a professional human translator producing certified translations.

Task: Translate every input segment from {source_lang} to {target_lang}.

ABSOLUTE RULES — these are non-negotiable for legal and identity documents:
- Preserve all proper nouns, personal names, place names and organisation names exactly as written.
- Preserve all dates, numbers, codes, ID numbers, passport numbers, IBAN/SWIFT codes, postal codes and reference numbers verbatim — do NOT reformat or localise them.
- Preserve currency symbols and amounts exactly.
- Preserve internal line breaks inside a segment. If the input segment has 3 lines, the output must have 3 lines.
- Do NOT add commentary, do NOT add or remove punctuation, do NOT renumber or reorder.
- If a segment is already in {target_lang} (already translated, or untranslatable like an ID number), return it unchanged.
- Translate idiomatically and accurately — no calques, no machine artefacts.
"""

    if glossary_prompt:
        rules += (
            "\nMANDATORY GLOSSARY (these mappings override any other choice):\n"
            f"{glossary_prompt}\n"
        )

    if tm_context:
        rules += (
            "\nREFERENCE TRANSLATIONS (use these verbatim if the segment matches):\n"
            f"{tm_context}\n"
        )

    rules += (
        f"\nINPUT FORMAT: Segments are separated by the literal delimiter `{DELIM}`."
        f"\nOUTPUT FORMAT: Return only the translated segments separated by the same `{DELIM}` delimiter, in the same order."
        " No numbering, no labels, no commentary. The number of segments in your output must match the input exactly.\n"
    )

    prompt = rules + "\nINPUT:\n" + ("\n" + DELIM + "\n").join(texts)

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    output = response.choices[0].message.content or ""

    raw = [chunk.strip("\n").strip() for chunk in output.split(DELIM)]
    translations = [chunk for chunk in raw if chunk]

    if len(translations) != len(texts):
        fallback = [
            re.sub(r"^\d+\.\s*", "", line.strip())
            for line in output.split("\n")
            if line.strip()
        ]
        if len(fallback) == len(texts):
            translations = fallback

    return translations
