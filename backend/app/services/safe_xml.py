"""Untrusted XML uploads (TMX, XLIFF, TBX): no entities, no DTD loading, no network."""
from __future__ import annotations

import re

from lxml import etree

MAX_BYTES = 20 * 1024 * 1024
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_ENTITY_DECL = re.compile(rb"<!ENTITY", re.I)
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class XmlError(ValueError):
    pass


def size_label(n: int = MAX_BYTES) -> str:
    return f"{n // (1024 * 1024)} MB"


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


def _probe(data: bytes) -> bytes:
    if data[:4].startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="ignore").encode("utf-8")
    return data


def parse(data: bytes, kind: str = "XML", max_bytes: int = MAX_BYTES):
    """Root element of an uploaded file; any entity declaration is refused before parsing (XXE, billion laughs)."""
    if len(data) > max_bytes:
        raise XmlError(f"The file is larger than {size_label(max_bytes)}")
    if _ENTITY_DECL.search(_probe(data)):
        raise XmlError("Files that declare XML entities are not accepted")
    try:
        root = etree.fromstring(data, _parser())
    except etree.XMLSyntaxError as e:
        raise XmlError(f"Not a valid {kind} file: {e.msg}") from e
    dtd = root.getroottree().docinfo.internalDTD
    if dtd is not None and list(dtd.iterentities()):
        raise XmlError("Files that declare XML entities are not accepted")
    return root


def local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def children(el, name: str):
    return [c for c in el if local(c.tag) == name]


def child(el, name: str):
    return next((c for c in el if local(c.tag) == name), None)


def lang_of(el) -> str:
    return (el.get(XML_LANG) or el.get("lang") or "").strip()


def flat_text(el, drop: frozenset = frozenset()) -> str:
    """Element text with whitespace collapsed; children named in `drop` lose their content but keep their tail."""
    parts = [el.text or ""]
    for c in el:
        if local(c.tag) not in drop:
            parts.append(flat_text(c, drop))
        parts.append(c.tail or "")
    return " ".join("".join(parts).split())


def clean(text: str) -> str:
    return CONTROL.sub("", text or "")


def to_bytes(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
