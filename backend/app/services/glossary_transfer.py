"""Glossary export (CSV, TBX-Basic) and import (CSV, TBX-Basic 2008 and TBX v3)."""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime
from typing import Iterable, Optional

from lxml import etree
from sqlalchemy.orm import Session

from app.models.glossary import Glossary
from app.services import safe_xml, tm_keys
from app.services.glossary_service import fold_text, lang_key, language_name
from app.services.safe_xml import XML_LANG, XmlError, local
from app.services.tm_transfer import csv_cell, csv_value

MAX_BYTES = safe_xml.MAX_BYTES
MAX_TERMS = 50_000
MAX_TERM_CHARS = 500
MAX_NOTE_CHARS = 2000
CSV_COLUMNS = ["source_language", "target_language", "source_term", "target_term", "notes"]
_ALIASES = {
    "source_language": {"source_language", "source language", "source lang", "src_lang", "from"},
    "target_language": {"target_language", "target language", "target lang", "tgt_lang", "to"},
    "source_term": {"source_term", "source term", "source", "term"},
    "target_term": {"target_term", "target term", "target", "translation"},
    "notes": {"notes", "note", "comment", "comments", "definition", "description"},
}
_KNOWN = set().union(*_ALIASES.values())


class GlossaryFileError(ValueError):
    pass


def export_code(stored: str) -> str:
    """BCP-47 code for a stored language ('Italian' -> 'it', 'English (UK)' -> 'en-GB')."""
    return tm_keys.target_lang(stored) or lang_key(stored) or "und"


def stored_language(value: str) -> str:
    """The display name the glossary keeps ('it-IT' -> 'Italian'), matching terms typed in the app."""
    key = lang_key(value)
    if key == "zh-tw":
        return "Chinese (Traditional)"
    return language_name(key)


def _pair_ok(term: Glossary, source: str, target: str) -> bool:
    return (not source or lang_key(term.source_language) == lang_key(source)) and (
        not target or lang_key(term.target_language) == lang_key(target)
    )


def terms_for_export(db: Session, team_id, source: str = "", target: str = "") -> list[Glossary]:
    rows = (
        db.query(Glossary)
        .filter(Glossary.team_id == team_id, Glossary.origin != "rejected")
        .order_by(Glossary.source_language, Glossary.target_language, Glossary.source_term)
        .all()
    )
    return [t for t in rows if _pair_ok(t, source, target)]


def build_csv(terms: Iterable[Glossary]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for t in terms:
        w.writerow([export_code(t.source_language), export_code(t.target_language),
                    csv_cell(t.source_term), csv_cell(t.target_term), csv_cell(t.notes or "")])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def build_tbx(terms: Iterable[Glossary]) -> bytes:
    """TBX-Basic (ISO 30042:2008 martif): one termEntry per source/target pair, notes on the entry."""
    root = etree.Element("martif", type="TBX-Basic")
    root.set(XML_LANG, "en")
    header = etree.SubElement(root, "martifHeader")
    fdesc = etree.SubElement(header, "fileDesc")
    etree.SubElement(etree.SubElement(fdesc, "titleStmt"), "title").text = "OnlineDocTranslator glossary"
    etree.SubElement(etree.SubElement(fdesc, "sourceDesc"), "p").text = (
        f"Exported by OnlineDocTranslator on {datetime.utcnow():%Y-%m-%d}"
    )
    etree.SubElement(etree.SubElement(header, "encodingDesc"), "p", type="XCSURI").text = "TBXBasicXCSV02.xcs"
    body = etree.SubElement(etree.SubElement(root, "text"), "body")
    for t in terms:
        entry = etree.SubElement(body, "termEntry", id=f"c{t.id}")
        if t.notes:
            etree.SubElement(entry, "note").text = safe_xml.clean(t.notes)
        for lang, text in ((t.source_language, t.source_term), (t.target_language, t.target_term)):
            ls = etree.SubElement(entry, "langSet")
            ls.set(XML_LANG, export_code(lang))
            etree.SubElement(etree.SubElement(ls, "tig"), "term").text = safe_xml.clean(text)
    return safe_xml.to_bytes(root)


def _entry_note(entry) -> str:
    notes = []
    for el in entry:
        name = local(el.tag)
        if name == "note" or (name == "descrip" and (el.get("type") or "") in ("definition", "context")):
            text = safe_xml.flat_text(el)
            if text:
                notes.append(text)
    return " | ".join(notes)


def _first_term(lang_el) -> str:
    for el in lang_el.iter():
        if local(el.tag) == "term":
            text = safe_xml.flat_text(el)
            if text:
                return text
    return ""


def parse_tbx(data: bytes, source: str = "") -> tuple[list[dict], int]:
    """Pairs from a TBX file, and the number of invalid entries. The source is `source` or each entry's first language."""
    root = safe_xml.parse(data, "TBX", MAX_BYTES)
    if local(root.tag) not in ("martif", "tbx"):
        raise XmlError("Not a TBX file")
    pairs, invalid, entries = [], 0, 0
    src_key = lang_key(source) if source else ""
    for entry in root.iter():
        if local(entry.tag) not in ("termEntry", "conceptEntry"):
            continue
        entries += 1
        if entries > MAX_TERMS:
            raise GlossaryFileError(f"The file has more than {MAX_TERMS:,} entries")
        langs = [(safe_xml.lang_of(ls), _first_term(ls)) for ls in entry if local(ls.tag) in ("langSet", "langSec")]
        langs = [(lang, term) for lang, term in langs if lang and term]
        if src_key:
            head = next((x for x in langs if lang_key(x[0]) == src_key), None)
        else:
            head = langs[0] if langs else None
        others = [x for x in langs if head and x is not head and lang_key(x[0]) != lang_key(head[0])]
        if not head or not others:
            invalid += 1
            continue
        note = _entry_note(entry)
        for lang, term in others:
            pairs.append({"source_language": head[0], "target_language": lang, "source_term": head[1],
                          "target_term": term, "notes": note})
    return pairs, invalid


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _dialect(text: str):
    first = text.split("\n", 1)[0]
    delimiter = max((";", "\t", ","), key=first.count)
    return delimiter if first.count(delimiter) else ","


def _field(header: list[str], name: str) -> Optional[int]:
    return next((i for i, h in enumerate(header) if h in _ALIASES[name]), None)


def parse_csv(data: bytes, source: str = "") -> tuple[list[dict], int]:
    """Our own columns (source_language, target_language, source_term, target_term, notes), or one column per
    language with the language as the header ('it-IT', 'English'); the source is `source` or the first one."""
    text = _decode(data)
    rows = list(csv.reader(io.StringIO(text), delimiter=_dialect(text)))
    if not rows:
        return [], 0
    if len(rows) > MAX_TERMS + 1:
        raise GlossaryFileError(f"The file has more than {MAX_TERMS:,} rows")
    header = [h.strip().lower() for h in rows[0]]
    raw_header = [h.strip() for h in rows[0]]
    body = [r for r in rows[1:] if any(c.strip() for c in r)]
    note_i = _field(header, "notes")

    def cell(r, i):
        return csv_value(r[i]) if i is not None and i < len(r) else ""

    pairs, invalid = [], 0
    st, tt = _field(header, "source_term"), _field(header, "target_term")
    if st is not None and tt is not None:
        sl, tl = _field(header, "source_language"), _field(header, "target_language")
        if sl is None or tl is None:
            raise GlossaryFileError("The CSV needs source_language and target_language columns, or one column per language")
        for r in body:
            pairs.append({"source_language": cell(r, sl), "target_language": cell(r, tl), "source_term": cell(r, st),
                          "target_term": cell(r, tt), "notes": cell(r, note_i)})
        return pairs, invalid

    lang_cols = [i for i, h in enumerate(header) if h not in _KNOWN and tm_keys.supported(raw_header[i])]
    if len(lang_cols) < 2:
        raise GlossaryFileError(
            "Couldn't find the languages. Use the columns source_language, target_language, source_term, target_term, "
            "notes, or put a language in each column header (for example it-IT and en-GB)"
        )
    src_key = lang_key(source) if source else ""
    head = next((i for i in lang_cols if lang_key(raw_header[i]) == src_key), None) if src_key else lang_cols[0]
    if head is None:
        raise GlossaryFileError("The file has no column for the source language you picked")
    for r in body:
        src_term = cell(r, head)
        found = False
        for i in lang_cols:
            if i == head or not cell(r, i) or not src_term:
                continue
            found = True
            pairs.append({"source_language": raw_header[head], "target_language": raw_header[i], "source_term": src_term,
                          "target_term": cell(r, i), "notes": cell(r, note_i)})
        if not found:
            invalid += 1
    return pairs, invalid


def read_upload(data: bytes, source: str = "") -> tuple[str, list[dict], int]:
    if len(data) > MAX_BYTES:
        raise GlossaryFileError(f"The file is larger than {safe_xml.size_label(MAX_BYTES)}")
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n")
    xml = head.startswith(b"<") or (data.startswith((b"\xff\xfe", b"\xfe\xff")) and b"<\x00" in data[:8])
    if xml:
        pairs, invalid = parse_tbx(data, source)
        return "tbx", pairs, invalid
    pairs, invalid = parse_csv(data, source)
    return "csv", pairs, invalid


def import_terms(db: Session, team_id, pairs: Iterable[dict], *, replace: bool = False) -> dict:
    """Add terms as origin 'import'. The same source and target term is a duplicate; a different translation of a
    term the team typed or imported is kept unless `replace`; a learned term gives way."""
    counts = {"imported": 0, "updated": 0, "duplicates": 0, "conflicts": 0, "unsupported_language": 0, "invalid": 0}
    existing: dict[tuple, list[Glossary]] = defaultdict(list)
    for row in db.query(Glossary).filter(Glossary.team_id == team_id):
        existing[(lang_key(row.source_language), lang_key(row.target_language), fold_text(row.source_term.strip()))].append(row)
    for p in pairs:
        if not tm_keys.supported(p.get("source_language")) or not tm_keys.supported(p.get("target_language")):
            counts["unsupported_language"] += 1
            continue
        src, tgt = (p.get("source_term") or "").strip(), (p.get("target_term") or "").strip()
        notes = (p.get("notes") or "").strip()[:MAX_NOTE_CHARS] or None
        if not src or not tgt or len(src) > MAX_TERM_CHARS or len(tgt) > MAX_TERM_CHARS:
            counts["invalid"] += 1
            continue
        key = (lang_key(p["source_language"]), lang_key(p["target_language"]), fold_text(src))
        if key[0] == key[1]:
            counts["invalid"] += 1
            continue
        held = existing.get(key) or []
        same = next((r for r in held if fold_text(r.target_term.strip()) == fold_text(tgt)), None)
        if same is not None:
            if same.origin == "rejected":
                same.origin, same.notes = "import", notes or same.notes
                counts["updated"] += 1
            else:
                counts["duplicates"] += 1
            continue
        live = [r for r in held if r.origin != "rejected"]
        if live:
            row = live[0]
            if not replace and row.origin != "learned":
                counts["conflicts"] += 1
                continue
            row.target_term, row.origin, row.confidence = tgt, "import", None
            row.notes = notes or row.notes
            counts["updated"] += 1
            continue
        row = Glossary(
            team_id=team_id,
            source_language=stored_language(p["source_language"]),
            target_language=stored_language(p["target_language"]),
            source_term=src,
            target_term=tgt,
            notes=notes,
            usage_count=0,
            origin="import",
        )
        db.add(row)
        existing[key].append(row)
        counts["imported"] += 1
    db.commit()
    return counts
