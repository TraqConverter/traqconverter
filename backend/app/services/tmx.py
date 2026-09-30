"""TMX 1.4b import and export. Parsing never resolves entities, loads DTDs or touches the network."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional

from lxml import etree

MAX_BYTES = 10 * 1024 * 1024
MAX_UNITS = 50_000
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_INLINE_CODES = {"bpt", "ept", "ph", "it", "ut"}
_ENTITY_DECL = re.compile(rb"<!ENTITY", re.I)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class TmxError(ValueError):
    pass


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _seg_text(seg) -> str:
    """Segment text without the native formatting codes inside bpt/ept/ph/it/ut."""
    parts = [seg.text or ""]
    for child in seg:
        if _local(child.tag) not in _INLINE_CODES:
            parts.append(_seg_text(child))
        parts.append(child.tail or "")
    return " ".join("".join(parts).split())


def _lang(el) -> str:
    return el.get(XML_LANG) or el.get("lang") or ""


def parse(data: bytes) -> tuple[list[dict], int]:
    """Pairs (source_language, target_language, source_text, translated_text) and the number of units read."""
    if len(data) > MAX_BYTES:
        raise TmxError("The file is larger than 10 MB")
    head = data[:4096]
    utf16 = head.startswith((b"\xff\xfe", b"\xfe\xff"))
    probe = data.decode("utf-16", errors="ignore").encode("utf-8") if utf16 else data
    if _ENTITY_DECL.search(probe):
        raise TmxError("Files that declare XML entities are not accepted")
    try:
        root = etree.fromstring(data, _parser())
    except etree.XMLSyntaxError as e:
        raise TmxError(f"Not a valid TMX file: {e.msg}") from e
    if _local(root.tag) != "tmx":
        raise TmxError("Not a TMX file")
    docinfo = root.getroottree().docinfo
    if docinfo.internalDTD is not None and list(docinfo.internalDTD.iterentities()):
        raise TmxError("Files that declare XML entities are not accepted")
    header = next((el for el in root if _local(el.tag) == "header"), None)
    default_src = (header.get("srclang") if header is not None else "") or ""
    body = next((el for el in root if _local(el.tag) == "body"), None)
    if body is None:
        return [], 0
    pairs, units = [], 0
    for tu in body:
        if _local(tu.tag) != "tu":
            continue
        units += 1
        if units > MAX_UNITS:
            raise TmxError(f"The file has more than {MAX_UNITS:,} translation units")
        tuvs = []
        for tuv in tu:
            if _local(tuv.tag) != "tuv":
                continue
            seg = next((el for el in tuv if _local(el.tag) == "seg"), None)
            if seg is not None and _lang(tuv):
                tuvs.append((_lang(tuv), _seg_text(seg)))
        if len(tuvs) < 2:
            continue
        src_lang = tu.get("srclang") or default_src
        source = next((t for t in tuvs if src_lang and src_lang != "*all*" and t[0].lower() == src_lang.lower()), tuvs[0])
        for tuv in tuvs:
            if tuv is not source and tuv[0].lower() != source[0].lower():
                pairs.append({
                    "source_language": source[0],
                    "target_language": tuv[0],
                    "source_text": source[1],
                    "translated_text": tuv[1],
                })
    return pairs, units


def _stamp(value: Optional[datetime]) -> str:
    return (value or datetime.utcnow()).strftime("%Y%m%dT%H%M%SZ")


def build(entries: Iterable, srclang: str = "*all*") -> bytes:
    """TMX 1.4b document for TranslationMemory rows."""
    root = etree.Element("tmx", version="1.4")
    etree.SubElement(
        root,
        "header",
        creationtool="TraqConverter",
        creationtoolversion="1.0",
        segtype="sentence",
        attrib={"o-tmf": "TraqConverter"},
        adminlang="en",
        srclang=srclang or "*all*",
        datatype="plaintext",
        creationdate=_stamp(None),
    )
    body = etree.SubElement(root, "body")
    for e in entries:
        tu = etree.SubElement(
            body, "tu", tuid=str(e.id), creationdate=_stamp(e.created_at), changedate=_stamp(e.updated_at),
        )
        tu.set("srclang", e.source_language)
        prop = etree.SubElement(tu, "prop", type="x-origin")
        prop.text = e.origin
        for lang, text in ((e.source_language, e.source_text), (e.target_language, e.translated_text)):
            tuv = etree.SubElement(tu, "tuv")
            tuv.set(XML_LANG, lang)
            seg = etree.SubElement(tuv, "seg")
            seg.text = _CONTROL.sub("", text or "")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
