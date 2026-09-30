"""Translation memory keys: BCP-47 languages, source hashes and the one-off cleanup plan. No app imports: the migration uses it."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Iterable, Optional

ORIGINS = ("machine", "approved", "manual", "import")
MAX_SOURCE_CHARS = 1500

_NAMES = {
    "english": "en", "english (uk)": "en-GB", "british english": "en-GB", "english (us)": "en-US",
    "american english": "en-US", "italian": "it", "italiano": "it", "german": "de", "deutsch": "de",
    "french": "fr", "français": "fr", "francais": "fr", "spanish": "es", "español": "es", "espanol": "es",
    "portuguese": "pt", "portuguese (brazilian)": "pt-BR", "brazilian portuguese": "pt-BR", "dutch": "nl",
    "swedish": "sv", "danish": "da", "norwegian": "no", "finnish": "fi", "polish": "pl", "czech": "cs",
    "romanian": "ro", "hungarian": "hu", "turkish": "tr", "vietnamese": "vi", "indonesian": "id",
    "japanese": "ja", "chinese": "zh", "chinese (simplified)": "zh-CN", "chinese (traditional)": "zh-TW",
    "korean": "ko", "russian": "ru", "ukrainian": "uk", "greek": "el", "arabic": "ar", "hebrew": "he",
    "hindi": "hi", "thai": "th", "albanian": "sq", "bulgarian": "bg", "croatian": "hr", "serbian": "sr",
    "slovak": "sk", "slovenian": "sl", "lithuanian": "lt", "latvian": "lv", "estonian": "et",
    "catalan": "ca", "persian": "fa", "farsi": "fa", "urdu": "ur", "bengali": "bn", "punjabi": "pa",
    "tagalog": "tl", "filipino": "fil", "malay": "ms", "inglese": "en", "tedesco": "de", "francese": "fr",
    "spagnolo": "es", "portoghese": "pt",
}
_TAG_RE = re.compile(r"^([a-z]{2,3})(?:[-_]([a-z]{4}))?(?:[-_]([a-z]{2}|\d{3}))?$", re.I)
_UNKNOWN = {"", "auto", "auto-detect", "autodetect", "detect", "unknown", "und"}
_TRADITIONAL_REGIONS = {"TW", "HK", "MO"}


def _parse(value) -> Optional[tuple[str, str, str]]:
    s = str(value or "").strip()
    if s.lower() in _UNKNOWN:
        return None
    m = _TAG_RE.match(s)
    if m:
        return m.group(1).lower(), (m.group(2) or "").title(), (m.group(3) or "").upper()
    low = s.lower()
    code = _NAMES.get(low) or _NAMES.get(re.sub(r"\s*\(.*\)$", "", low).strip())
    return _parse(code) if code else None


def _traditional_chinese(base: str, script: str, region: str) -> bool:
    return base == "zh" and (script == "Hant" or region in _TRADITIONAL_REGIONS)


def source_lang(value) -> str:
    """Base BCP-47 code for a source language ('Italian', 'it-IT' -> 'it'); '' when unknown or auto."""
    parsed = _parse(value)
    if not parsed:
        return ""
    base, script, region = parsed
    return "zh-Hant" if _traditional_chinese(base, script, region) else base


def target_lang(value) -> str:
    """BCP-47 code for a target language, keeping the region ('English (UK)' -> 'en-GB'); '' when unknown."""
    parsed = _parse(value)
    if not parsed:
        return ""
    return "-".join(p for p in parsed if p)


def family(tag: str) -> str:
    """Languages whose entries can stand in for each other: en-GB and en-US, but not zh-TW and zh-CN."""
    parsed = _parse(tag)
    if not parsed:
        return ""
    base, script, region = parsed
    return "zh-Hant" if _traditional_chinese(base, script, region) else base


def normalise_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text or "").split())


def source_hash(text: str) -> str:
    return hashlib.sha256(normalise_text(text).encode("utf-8")).hexdigest()


def origin_rank(origin: str) -> int:
    return 0 if (origin or "machine") == "machine" else 1


def detected_source(project: dict) -> str:
    """The project's source language, or the detected one when the upload said auto."""
    return source_lang(project.get("source_language")) or source_lang((project.get("doc_profile") or {}).get("source_language"))


def plan_cleanup(rows: Iterable[dict], matches: dict) -> dict:
    """Normalise, resolve and dedupe existing rows.

    rows: id, team_id, source_language, target_language, source_text, translated_text, seq (insertion order).
    matches: row id -> projects of the same team with a segment of that exact source text
    (id, source_language, target_language, doc_profile, created_at).
    Returns {"update": [...], "delete": [ids]}.
    """
    keep: dict[tuple, dict] = {}
    delete: list = []
    for row in rows:
        src_text, tgt_text = row.get("source_text") or "", row.get("translated_text") or ""
        tgt = target_lang(row.get("target_language"))
        if not tgt or not src_text.strip() or not tgt_text.strip() or len(src_text) > MAX_SOURCE_CHARS:
            delete.append(row["id"])
            continue
        projects = sorted(matches.get(row["id"]) or [], key=lambda p: p.get("created_at") or datetime.min, reverse=True)
        same = [p for p in projects if target_lang(p.get("target_language")) == tgt]
        near = [p for p in projects if family(target_lang(p.get("target_language"))) == family(tgt)]
        ordered = same + [p for p in near if p not in same] + [p for p in projects if p not in near]
        src = source_lang(row.get("source_language"))
        if not src:
            src = next((detected_source(p) for p in ordered if detected_source(p)), "")
        if not src:
            delete.append(row["id"])
            continue
        project = next((p for p in ordered if detected_source(p) in ("", src)), None)
        plan = {
            "id": row["id"],
            "source_language": src,
            "target_language": tgt,
            "source_hash": source_hash(src_text),
            "project_id": project["id"] if project else None,
            "_rank": (origin_rank(row.get("origin")), (project or {}).get("created_at") or datetime.min, row.get("seq") or 0),
        }
        key = (row["team_id"], src, tgt, plan["source_hash"])
        held = keep.get(key)
        if held is None or plan["_rank"] > held["_rank"]:
            if held is not None:
                delete.append(held["id"])
            keep[key] = plan
        else:
            delete.append(row["id"])
    updates = [{k: v for k, v in p.items() if k != "_rank"} for p in keep.values()]
    return {"update": updates, "delete": delete}
