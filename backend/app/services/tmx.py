"""TMX 1.4b import and export."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, Optional

from lxml import etree

from app.services import safe_xml
from app.services.safe_xml import XML_LANG, XmlError as TmxError, local

MAX_BYTES = safe_xml.MAX_BYTES
MAX_UNITS = 100_000
# Native formatting codes: their content is markup, not text. <hi> and <sub> text stays.
_INLINE_CODES = frozenset({"bpt", "ept", "ph", "it", "ut"})


@dataclass
class Parsed:
    pairs: list[dict] = field(default_factory=list)
    units: int = 0
    invalid: int = 0
    unconfirmed: int = 0


def _seg_text(seg) -> str:
    return safe_xml.flat_text(seg, _INLINE_CODES)


def check_units(units: int) -> None:
    if units > MAX_UNITS:
        raise TmxError(f"The file has more than {MAX_UNITS:,} translation units")


def parse_root(root) -> Parsed:
    if local(root.tag) != "tmx":
        raise TmxError("Not a TMX file")
    header = safe_xml.child(root, "header")
    default_src = (header.get("srclang") if header is not None else "") or ""
    body = safe_xml.child(root, "body")
    out = Parsed()
    if body is None:
        return out
    for tu in safe_xml.children(body, "tu"):
        out.units += 1
        check_units(out.units)
        tuvs = []
        for tuv in safe_xml.children(tu, "tuv"):
            seg = safe_xml.child(tuv, "seg")
            lang = safe_xml.lang_of(tuv)
            if seg is not None and lang:
                tuvs.append((lang, _seg_text(seg)))
        src_lang = tu.get("srclang") or default_src
        source = next(
            (t for t in tuvs if src_lang and src_lang != "*all*" and t[0].lower() == src_lang.lower()),
            tuvs[0] if tuvs else None,
        )
        found = False
        for tuv in tuvs:
            if tuv is source or tuv[0].lower() == source[0].lower():
                continue
            if not source[1] or not tuv[1]:
                continue
            found = True
            out.pairs.append({
                "source_language": source[0],
                "target_language": tuv[0],
                "source_text": source[1],
                "translated_text": tuv[1],
            })
        if not found:
            out.invalid += 1
    return out


def parse(data: bytes) -> Parsed:
    return parse_root(safe_xml.parse(data, "TMX", MAX_BYTES))


def _stamp(value: Optional[datetime]) -> str:
    return (value or datetime.utcnow()).strftime("%Y%m%dT%H%M%SZ")


def build(entries: Iterable, srclang: str = "*all*", code: Callable[[str], str] = lambda c: c) -> bytes:
    """TMX 1.4b document for TranslationMemory rows; `code` maps stored language codes to the exported ones."""
    root = etree.Element("tmx", version="1.4")
    etree.SubElement(
        root,
        "header",
        creationtool="OnlineDocTranslator",
        creationtoolversion="1.0",
        segtype="sentence",
        attrib={"o-tmf": "OnlineDocTranslator"},
        adminlang="en-US",
        srclang=code(srclang) if srclang and srclang != "*all*" else "*all*",
        datatype="plaintext",
        creationdate=_stamp(None),
    )
    body = etree.SubElement(root, "body")
    for e in entries:
        tu = etree.SubElement(
            body, "tu", tuid=str(e.id), creationdate=_stamp(e.created_at), changedate=_stamp(e.updated_at),
        )
        tu.set("srclang", code(e.source_language))
        prop = etree.SubElement(tu, "prop", type="x-origin")
        prop.text = e.origin
        for lang, text in ((e.source_language, e.source_text), (e.target_language, e.translated_text)):
            tuv = etree.SubElement(tu, "tuv")
            tuv.set(XML_LANG, code(lang))
            seg = etree.SubElement(tuv, "seg")
            seg.text = safe_xml.clean(text)
    return safe_xml.to_bytes(root)
