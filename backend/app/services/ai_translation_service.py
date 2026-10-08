import logging
import time

import anthropic
from openai import OpenAI
from sqlalchemy import update
from app.config import settings
import re

from app.services import claude_params

from app.services.translation_memory_service import lookup, project_pair
from app.services.glossary_service import (
    build_glossary_prompt,
    get_glossary,
    project_source_language,
    relevant_terms,
)
from app.models.glossary import Glossary

logger = logging.getLogger(__name__)









MODEL_OPTIONS: dict[str, dict] = {

    "claude-opus-4-6": {
        "provider": "anthropic",
        "model": "claude-opus-4-6",
        "label": "Claude Opus 4.6 (highest quality)",
    },

    "claude-sonnet-4-6": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "label": "Claude Sonnet 4.6 (premium quality)",
    },

    "claude-haiku-4-5": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "label": "Claude Haiku 4.5 (fast, low cost)",
    },

    "gpt-4.1": {
        "provider": "openai",
        "model": "gpt-4.1",
        "label": "GPT-4.1 (OpenAI, high quality)",
    },

    "gpt-4.1-mini": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "label": "GPT-4.1 Mini (OpenAI, fast)",
    },



    "balanced": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "label": "Balanced (default)",
    },
}


def _resolve_model(model_key: str | None) -> dict:
    """Return the catalog entry for the given key, falling back to
    'balanced' (Claude Sonnet 4.6) when the key is unknown / empty."""
    key = (model_key or "balanced").strip()
    return MODEL_OPTIONS.get(key, MODEL_OPTIONS["balanced"])



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
    cache_prefix: str = "",
) -> str:
    """Route a translation call to the right provider+model.

    Returns the generated text. `cache_prefix` is stable instruction text
    placed before `user`; on Anthropic it gets a prompt-cache breakpoint
    when it is long enough to be cached.
    """
    cfg = _resolve_model(model_key)
    provider = cfg["provider"]
    model = cfg["model"]

    if provider == "openai":
        resp = _get_openai().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": cache_prefix + user},
            ],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()

    if provider == "anthropic":
        if cache_prefix and claude_params.worth_caching(model, system + cache_prefix):
            content = [
                claude_params.cached_text_block(cache_prefix),
                {"type": "text", "text": user},
            ]
        else:
            content = cache_prefix + user
        resp = _get_anthropic().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            **claude_params.request_params(model, max_tokens=max_tokens, temperature=0),
        )
        claude_params.log_usage("Translation", resp)
        parts: list[str] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "".join(parts).strip()

    raise ValueError(f"Unknown model provider: {provider}")










LANGUAGE_NAMES = {
    "auto": "the document's source language (auto-detect)",

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
        logger.warning("Glossary usage write failed: %s", type(e).__name__)
        try:
            db.rollback()
        except Exception:
            pass





def get_project_scope(project):
    """
    Standardize glossary + TM scope.
    Always prefer team_id (canonical).
    """
    if hasattr(project, "team_id") and project.team_id:
        return project.team_id


    return getattr(project, "user_id", None)





def _plan_has(db, project, feature: str) -> bool:
    from app.dependencies.feature_guard import project_has_feature

    return project_has_feature(db, project, feature)


def _batch_terms_prompt(db, project, text: str) -> str:
    if not db or not getattr(project, "batch_id", None):
        return ""
    from app.services.batch_terms import terminology_block

    block = terminology_block(db, project, text)
    return f"\n{block}" if block else ""


def _instructions_prompt(project) -> str:
    from app.services.project_instructions import prompt_block

    block = prompt_block(getattr(project, "ai_instructions", None))
    return f"\n{block}" if block else ""


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

    if db and project and project_apply_glossary and _plan_has(db, project, "glossaries"):
        try:
            scope_id = get_project_scope(project)

            glossary_entries = relevant_terms(
                get_glossary(db, scope_id, project_source_language(project) or source_lang, target_lang),
                text,
            )

            glossary_prompt = build_glossary_prompt(glossary_entries)

            glossary_map = {
                g.source_term: g.target_term
                for g in glossary_entries
            }


            text, usage_counts = apply_glossary_with_counts(text, glossary_entries)
            flush_glossary_usage(db, usage_counts)

        except Exception as e:
            logger.warning("Glossary lookup failed: %s", type(e).__name__)

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
{_batch_terms_prompt(db, project, text)}{_instructions_prompt(project)}
Return ONLY the translated text — no preamble, no quotes, no commentary."""

    return _call_model(
        model_key=getattr(project, "model", None) if project else None,
        system=system_prompt,
        user=text,
        max_tokens=2048,
    )





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


    scope_id = get_project_scope(project) if project else None


    project_use_tm = bool(getattr(project, "use_tm", True)) if project else True
    project_apply_glossary = (
        bool(getattr(project, "apply_glossary", True)) if project else True
    )




    if db and project and scope_id and project_use_tm and _plan_has(db, project, "terminology_memory"):
        try:
            src, tgt = project_pair(project)
            found = lookup(db, scope_id, src, tgt, texts)
            if found:
                tm_context = "\n".join(f"{r.source_text} → {r.translated_text}" for r in found.values())
        except Exception:
            logger.exception("TM lookup for segment translation failed")




    if db and project and scope_id and project_apply_glossary and _plan_has(db, project, "glossaries"):
        try:
            glossary_entries = relevant_terms(
                get_glossary(db, scope_id, project_source_language(project) or source_lang, target_lang),
                "\n".join(texts),
            )

            glossary_prompt = build_glossary_prompt(glossary_entries)

            glossary_map = {
                g.source_term: g.target_term
                for g in glossary_entries
            }

        except Exception as e:
            logger.warning("Glossary lookup failed: %s", type(e).__name__)




    if glossary_map:


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
    rules += _batch_terms_prompt(db, project, "\n".join(texts))

    rules += (
        f"\nINPUT FORMAT: Segments are separated by the literal delimiter `{DELIM}`."
        f"\nOUTPUT FORMAT: Return only the translated segments separated by the same `{DELIM}` delimiter, in the same order."
        " No numbering, no labels, no commentary. The number of segments in your output must match the input exactly.\n"
    )

    # Per-project text stays out of the cached rules.
    prompt = _instructions_prompt(project)
    if tm_context:
        prompt += (
            "\nREFERENCE TRANSLATIONS (use these verbatim if the segment matches):\n"
            f"{tm_context}\n"
        )
    prompt += "\nINPUT:\n" + ("\n" + DELIM + "\n").join(texts)

    output = _call_model(
        model_key=getattr(project, "model", None) if project else None,
        system="You translate certified-quality documents. Return ONLY the translated segments separated by the configured delimiter — no commentary.",
        user=prompt,
        max_tokens=8192,
        cache_prefix=rules,
    )

    raw = [chunk.strip("\n").strip() for chunk in output.split(DELIM)]
    translations = [chunk for chunk in raw if chunk]

    # One line per segment only lines up when no segment spans lines; otherwise a dropped segment shifts the rest.
    if len(translations) != len(texts) and not any("\n" in t.strip() for t in texts):
        fallback = [
            re.sub(r"^\d+\.\s*", "", line.strip())
            for line in output.split("\n")
            if line.strip()
        ]
        if len(fallback) == len(texts):
            translations = fallback

    return translations
