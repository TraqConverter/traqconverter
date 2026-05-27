import logging
import time

import anthropic
from openai import OpenAI
from sqlalchemy import update
from app.config import settings
import re

from app.services.translation_memory_service import get_tm_entries
from app.services.glossary_service import build_glossary_prompt, get_glossary
from app.models.glossary import Glossary

logger = logging.getLogger(__name__)

# ============================================================
# MODEL CATALOG
# ============================================================
# Each entry maps a logical model id (the value stored on the
# project) to (provider, real_model_name, marketing_label). The
# frontend new-project page lists these so users pick by speed /
# quality / cost. Add new entries here when supporting a new model —
# nothing else in the pipeline needs to change.
MODEL_OPTIONS: dict[str, dict] = {
    # Fastest + cheapest GPT — good default for everyday docs.
    "gpt-4.1-mini": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "label": "GPT-4.1 Mini (fast, balanced)",
    },
    # Higher-quality GPT for tricky / legal / medical docs.
    "gpt-4.1": {
        "provider": "openai",
        "model": "gpt-4.1",
        "label": "GPT-4.1 (highest quality, slower)",
    },
    # Claude Sonnet — Anthropic's quality tier, same model as our
    # Vision OCR so terminology stays consistent across stages.
    "claude-sonnet-4-6": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "label": "Claude Sonnet 4.6 (premium quality)",
    },
    # Claude Haiku — Anthropic's speed tier.
    "claude-haiku-4-5": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "label": "Claude Haiku 4.5 (fast, low cost)",
    },
    # Legacy alias used by older projects ("balanced" was the default
    # field value before per-model selection landed).
    "balanced": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "label": "Balanced (default)",
    },
}


def _resolve_model(model_key: str | None) -> dict:
    """Return the catalog entry for the given key, falling back to
    'balanced' (gpt-4.1-mini) when the key is unknown / empty."""
    key = (model_key or "balanced").strip()
    return MODEL_OPTIONS.get(key, MODEL_OPTIONS["balanced"])


# Lazy clients — only instantiated when their provider is first used.
_openai_client: OpenAI | None = None
_anthropic_client: anthropic.Anthropic | None = None


def _get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=60.0,
            max_retries=3,
        )
    return _openai_client


def _get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=60.0,
            max_retries=3,
        )
    return _anthropic_client


BATCH_SIZE = 20


def _call_model(
    *,
    model_key: str | None,
    system: str,
    user: str,
    max_tokens: int = 8192,
) -> str:
    """Route a translation call to the right provider+model.

    Returns the generated text. Both providers honour the same
    system+user message split — for OpenAI we map system→system
    role, for Anthropic we use the `system` parameter and a single
    user message.
    """
    cfg = _resolve_model(model_key)
    provider = cfg["provider"]
    model = cfg["model"]

    if provider == "openai":
        resp = _get_openai().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()

    if provider == "anthropic":
        resp = _get_anthropic().messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts: list[str] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "".join(parts).strip()

    raise ValueError(f"Unknown model provider: {provider}")


# ============================================================
# LANGUAGE CODE → HUMAN-READABLE NAME
# ----------------------------------------------------------------
# The frontend sends BCP-47 codes (de-DE, it-IT, en-GB). Passing those
# raw to the LLM produced inconsistent output — the model would
# sometimes ignore them. Mapping to plain names ("German", "Italian")
# makes the prompt unambiguous and dramatically improves accuracy.
# ============================================================
LANGUAGE_NAMES = {
    "auto": "the document's source language (auto-detect)",
    # Latin-script
    "en": "English",
    "en-GB": "English (UK)",
    "en-US": "English (US)",
    "de": "German", "de-DE": "German",
    "fr": "French", "fr-FR": "French",
    "it": "Italian", "it-IT": "Italian",
    "es": "Spanish", "es-ES": "Spanish",
    "pt": "Portuguese", "pt-PT": "Portuguese",
    "pt-BR": "Portuguese (Brazilian)",
    "nl": "Dutch", "nl-NL": "Dutch",
    "sv": "Swedish", "sv-SE": "Swedish",
    "da": "Danish", "da-DK": "Danish",
    "no": "Norwegian", "no-NO": "Norwegian",
    "fi": "Finnish", "fi-FI": "Finnish",
    "pl": "Polish", "pl-PL": "Polish",
    "cs": "Czech", "cs-CZ": "Czech",
    "ro": "Romanian", "ro-RO": "Romanian",
    "hu": "Hungarian", "hu-HU": "Hungarian",
    "tr": "Turkish", "tr-TR": "Turkish",
    "vi": "Vietnamese", "vi-VN": "Vietnamese",
    "id": "Indonesian", "id-ID": "Indonesian",
    # Other scripts
    "ja": "Japanese", "ja-JP": "Japanese",
    "zh": "Chinese (Simplified)",
    "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "ko": "Korean", "ko-KR": "Korean",
    "ru": "Russian", "ru-RU": "Russian",
    "uk": "Ukrainian", "uk-UA": "Ukrainian",
    "el": "Greek", "el-GR": "Greek",
    "ar": "Arabic", "ar-SA": "Arabic",
    "he": "Hebrew", "he-IL": "Hebrew",
    "hi": "Hindi", "hi-IN": "Hindi",
    "th": "Thai", "th-TH": "Thai",
}


def humanize_lang(code: str | None) -> str:
    """Return a human-readable language name for a BCP-47 code.

    Falls back to the bare language part (e.g. "fr" from "fr-CA") then to
    the literal value, so unknown codes still produce something sensible.
    """
    if not code:
        return "the source language"
    if code in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[code]
    base = code.split("-", 1)[0].lower()
    if base in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[base]
    return code


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

    project_apply_glossary = (
        bool(getattr(project, "apply_glossary", True)) if project else True
    )

    if db and project and project_apply_glossary:
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

    src_name = humanize_lang(source_lang)
    tgt_name = humanize_lang(target_lang)

    system_prompt = f"""You are a professional translator.

Translate from {src_name} to {tgt_name}.
The output MUST be written in {tgt_name}.

STRICT RULES:
- You MUST follow glossary mappings exactly
- Do NOT change glossary terms
- Do NOT re-translate already translated terms
- The entire output must be in {tgt_name}.

{glossary_prompt}

Return ONLY the translated text — no preamble, no quotes, no commentary."""

    return _call_model(
        model_key=getattr(project, "model", None) if project else None,
        system=system_prompt,
        user=text,
        max_tokens=2048,
    )


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

    # Per-project opt-out flags from the new-project page toggles.
    project_use_tm = bool(getattr(project, "use_tm", True)) if project else True
    project_apply_glossary = (
        bool(getattr(project, "apply_glossary", True)) if project else True
    )

    # ========================================================
    # LOAD TM (TEAM SCOPED) — skipped when project opted out.
    # ========================================================
    if db and project and scope_id and project_use_tm:
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
    # LOAD GLOSSARY (TEAM SCOPED) — skipped when project opted out.
    # ========================================================
    if db and project and scope_id and project_apply_glossary:
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

    src_name = humanize_lang(source_lang)
    tgt_name = humanize_lang(target_lang)

    rules = f"""You are a professional human translator producing certified translations.

Task: Translate every input segment from {src_name} to {tgt_name}. The output MUST be written entirely in {tgt_name}.

ABSOLUTE RULES — these are non-negotiable for legal and identity documents:
- Preserve all proper nouns, personal names, place names and organisation names exactly as written.
- Preserve all dates, numbers, codes, ID numbers, passport numbers, IBAN/SWIFT codes, postal codes and reference numbers verbatim — do NOT reformat or localise them.
- Preserve currency symbols and amounts exactly.
- Preserve internal line breaks inside a segment. If the input segment has 3 lines, the output must have 3 lines.
- Do NOT add commentary, do NOT add or remove punctuation, do NOT renumber or reorder.
- If a segment is already in {tgt_name} (already translated, or untranslatable like an ID number), return it unchanged.
- Translate idiomatically and accurately into {tgt_name} — no calques, no machine artefacts. Do not output any other language.
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

    # Pull the chosen model off the project; falls back to 'balanced'
    # (gpt-4.1-mini) when the project has no preference.
    output = _call_model(
        model_key=getattr(project, "model", None) if project else None,
        system="You translate certified-quality documents. Return ONLY the translated segments separated by the configured delimiter — no commentary.",
        user=prompt,
        max_tokens=8192,
    )

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
