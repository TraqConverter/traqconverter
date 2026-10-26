"""Moving translation memory in and out of CAT tools: TMX, XLIFF, CSV exports and TMX/XLIFF/sdlxliff imports."""
from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from typing import Callable, Iterable

from sqlalchemy.orm import Session

from app.models.translation_memory import TranslationMemory
from app.services import safe_xml, tm_keys, tmx, xliff
from app.services.safe_xml import XmlError, local
from app.services.translation_memory_service import upsert_entries

EXPORT_FORMATS = ("tmx", "xliff", "xliff2", "csv")
MAX_TARGET_CHARS = 10_000
WRITE_CHUNK = 1000
_FORMULA_START = ("=", "+", "@", "\t", "\r")


class ImportWriteError(RuntimeError):
    pass


def csv_cell(value: str) -> str:
    """Stops a spreadsheet running a cell as a formula; csv_value() undoes it."""
    v = value or ""
    if v.startswith(_FORMULA_START) or (v.startswith("-") and len(v) > 1 and not (v[1].isspace() or v[1].isdigit())):
        return "'" + v
    return v


def csv_value(value: str) -> str:
    v = (value or "").strip()
    if v.startswith("'") and len(v) > 1 and (v[1:].startswith(_FORMULA_START) or v[1] == "-"):
        return v[1:]
    return v


def locale_fn(regions: bool) -> Callable[[str], str]:
    return tm_keys.cat_locale if regions else (lambda c: c)


def file_stem(code: Callable[[str], str], source: str = "", target: str = "") -> str:
    parts = [code(x) for x in (source, target) if x]
    return "-".join(["translation-memory", *parts])


def _csv(rows: Iterable[TranslationMemory], code) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["source_language", "target_language", "source_text", "target_text", "origin", "created_at", "updated_at"])
    for r in rows:
        w.writerow([
            code(r.source_language), code(r.target_language), csv_cell(r.source_text), csv_cell(r.translated_text),
            r.origin, r.created_at.isoformat() if r.created_at else "", r.updated_at.isoformat() if r.updated_at else "",
        ])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def export(rows: list[TranslationMemory], fmt: str, regions: bool, source: str = "", target: str = "") -> tuple[bytes, str, str]:
    """(body, filename, media type). XLIFF holds one language pair per file, so several pairs come as a zip."""
    code = locale_fn(regions)
    stem = file_stem(code, source, target)
    if fmt == "tmx":
        return tmx.build(rows, srclang=source or "*all*", code=code), f"{stem}.tmx", "application/x-tmx+xml"
    if fmt == "csv":
        return _csv(rows, code), f"{stem}.csv", "text/csv; charset=utf-8"
    build = xliff.build_12 if fmt == "xliff" else xliff.build_20
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        groups[(r.source_language, r.target_language)].append(r)
    if len(groups) == 1:
        (s, t), items = next(iter(groups.items()))
        return build(items, s, t, code), f"{file_stem(code, s, t)}.xlf", "application/xliff+xml"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for (s, t), items in sorted(groups.items()):
            z.writestr(f"{file_stem(code, s, t)}.xlf", build(items, s, t, code))
    suffix = "-xliff2" if fmt == "xliff2" else "-xliff"
    return buf.getvalue(), f"{stem}{suffix}.zip", "application/zip"


def read_upload(data: bytes) -> tuple[str, tmx.Parsed]:
    """Format name and the pairs of a TMX, XLIFF 1.2/2.0 or sdlxliff file, told apart by the root element."""
    root = safe_xml.parse(data, "TMX or XLIFF", tmx.MAX_BYTES)
    name = local(root.tag)
    if name == "tmx":
        return "tmx", tmx.parse_root(root)
    if name == "xliff":
        sdl = xliff.SDL in (root.nsmap or {}).values()
        return ("sdlxliff" if sdl else "xliff"), xliff.parse_root(root)
    raise XmlError("This isn't a TMX or XLIFF file")


def import_pairs(db: Session, team_id, pairs: Iterable[dict], *, replace: bool = False) -> dict:
    """Write imported pairs as origin 'import'. An identical entry is a duplicate; a different approved
    translation of the same source is kept unless `replace`. AI drafts are always replaced."""
    counts = {"imported": 0, "updated": 0, "duplicates": 0, "conflicts": 0, "unsupported_language": 0, "invalid": 0}
    wanted: dict[tuple, dict] = {}
    for p in pairs:
        src, tgt = tm_keys.source_lang(p.get("source_language")), tm_keys.target_lang(p.get("target_language"))
        if not src or not tgt or not tm_keys.supported(src) or not tm_keys.supported(tgt):
            counts["unsupported_language"] += 1
            continue
        source, target = (p.get("source_text") or "").strip(), (p.get("translated_text") or "").strip()
        if not source or not target or len(source) > tm_keys.MAX_SOURCE_CHARS or len(target) > MAX_TARGET_CHARS:
            counts["invalid"] += 1
            continue
        key = (src, tgt, tm_keys.source_hash(source))
        if key in wanted:
            counts["duplicates"] += 1
            continue
        wanted[key] = {
            "source_language": src, "target_language": tgt, "source_text": source,
            "translated_text": target, "origin": "import",
        }

    by_pair: dict[tuple, list[str]] = defaultdict(list)
    for src, tgt, h in wanted:
        by_pair[(src, tgt)].append(h)
    existing: dict[tuple, tuple] = {}
    for (src, tgt), hashes in by_pair.items():
        for i in range(0, len(hashes), WRITE_CHUNK):
            q = db.query(TranslationMemory.source_hash, TranslationMemory.translated_text, TranslationMemory.origin).filter(
                TranslationMemory.team_id == team_id,
                TranslationMemory.source_language == src,
                TranslationMemory.target_language == tgt,
                TranslationMemory.source_hash.in_(hashes[i:i + WRITE_CHUNK]),
            )
            for h, text, origin in q:
                existing[(src, tgt, h)] = (text, origin)

    writes, new = [], 0
    for key, entry in wanted.items():
        held = existing.get(key)
        if held is None:
            writes.append(entry)
            new += 1
        elif held[1] != "machine" and tm_keys.normalise_text(held[0]) == tm_keys.normalise_text(entry["translated_text"]):
            counts["duplicates"] += 1
        elif held[1] == "machine" or replace:
            writes.append(entry)
            counts["updated"] += 1
        else:
            counts["conflicts"] += 1
    counts["imported"] = new
    for i in range(0, len(writes), WRITE_CHUNK):
        chunk = writes[i:i + WRITE_CHUNK]
        if upsert_entries(db, team_id, chunk) == 0:
            raise ImportWriteError(f"Saved {i:,} of {len(writes):,} entries before a write failed")
    return counts
