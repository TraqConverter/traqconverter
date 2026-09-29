import re
import unicodedata

from sqlalchemy.orm import Session

from app.models.glossary import Glossary

MAX_PROMPT_TERMS = 80
_CODE_RE = re.compile(r"^([a-z]{2,3})(?:[-_]([a-z0-9]{2,4}))?$", re.I)
_NAME_TO_CODE: dict[str, str] = {}


def _names() -> dict[str, str]:
    if not _NAME_TO_CODE:
        from app.services.ai_translation_service import LANGUAGE_NAMES

        for code, name in LANGUAGE_NAMES.items():
            if code == "auto":
                continue
            base = _code_key(code)
            _NAME_TO_CODE.setdefault(name.lower(), base)
            _NAME_TO_CODE.setdefault(re.sub(r"\s*\(.*\)$", "", name).strip().lower(), base)
    return _NAME_TO_CODE


def _code_key(code: str) -> str:
    m = _CODE_RE.match(code.strip())
    base, region = m.group(1).lower(), (m.group(2) or "").lower()
    # Traditional Chinese is a different written language, not a regional variant.
    return "zh-tw" if base == "zh" and region in ("tw", "hk", "hant") else base


def lang_key(value) -> str:
    """Comparable language key: 'it-IT', 'it' and 'Italian' all become 'it'; unknown or auto becomes ''."""
    s = (value or "").strip()
    if not s or s.lower() in ("auto", "auto-detect"):
        return ""
    if _CODE_RE.match(s):
        return _code_key(s)
    names = _names()
    low = s.lower()
    return names.get(low) or names.get(re.sub(r"\s*\(.*\)$", "", low).strip()) or low


def language_name(key: str) -> str:
    from app.services.ai_translation_service import LANGUAGE_NAMES

    return LANGUAGE_NAMES.get(key) or LANGUAGE_NAMES.get(key.split("-")[0]) or key


def project_source_language(project) -> str:
    """The project's source language, or the one the document profile detected when the upload said auto."""
    if lang_key(getattr(project, "source_language", "")):
        return project.source_language
    profile = getattr(project, "doc_profile", None) or {}
    return profile.get("source_language") or ""


def get_glossary(
    db: Session,
    team_id,
    source_language,
    target_language,
):
    src, tgt = lang_key(source_language), lang_key(target_language)
    if not src or not tgt:
        return []
    rows = (
        db.query(Glossary)
        .filter(Glossary.team_id == team_id, Glossary.origin != "rejected")
        .all()
    )
    return [g for g in rows if lang_key(g.source_language) == src and lang_key(g.target_language) == tgt]


def fold_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").casefold()


def term_in_text(term: str, folded_text: str) -> bool:
    t = fold_text(term).strip()
    if not t:
        return False
    return re.search(rf"(?<!\w){re.escape(t)}(?!\w)", folded_text) is not None


def relevant_terms(entries, source_text: str, cap: int = MAX_PROMPT_TERMS):
    """Only the entries whose source term occurs in the text, most-used first."""
    folded = fold_text(source_text)
    hits = [g for g in entries if g.source_term and g.target_term and term_in_text(g.source_term, folded)]
    hits.sort(key=lambda g: (g.origin == "learned", -(g.usage_count or 0), -len(g.source_term)))
    return hits[:cap]


def terminology_block(entries) -> str:
    if not entries:
        return ""
    lines = "\n".join(f"- {g.source_term} → {g.target_term}" for g in entries)
    return (
        "TEAM TERMINOLOGY — use exactly these translations (the team's approved choices):\n"
        f"{lines}\n"
    )


def build_glossary_prompt(glossary_entries):
    if not glossary_entries:
        return ""

    prompt = "\n\nMANDATORY GLOSSARY (DO NOT CHANGE THESE TERMS):\n"

    for g in glossary_entries:
        prompt += f"{g.source_term} → {g.target_term}\n"

    prompt += "\nYou MUST use these exact translations when matches occur.\n"
    return prompt
