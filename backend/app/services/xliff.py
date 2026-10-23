"""XLIFF 1.2 and 2.0 export of translation memory, and import of confirmed segments (XLIFF 1.2, 2.0, Trados sdlxliff)."""
from __future__ import annotations

from typing import Callable, Iterable

from lxml import etree

from app.services import safe_xml
from app.services.safe_xml import XmlError, local
from app.services.tmx import Parsed, check_units

NS12 = "urn:oasis:names:tc:xliff:document:1.2"
NS20 = "urn:oasis:names:tc:xliff:document:2.0"
SDL = "http://sdl.com/FileTypes/SdlXliff/1.0"
MQ = "MQXliff"
_DROP12 = frozenset({"ph", "bpt", "ept", "it", "x", "bx", "ex"})
_DROP20 = frozenset({"ph", "sc", "ec", "cp"})
_CONFIRMED_STATES = {"translated", "signed-off", "final", "reviewed"}
_SDL_CONFIRMED = {"Translated", "ApprovedTranslation", "ApprovedSignOff"}
_MQ_CONFIRMED = {"ManuallyConfirmed", "Proofread", "Reviewer1Confirmed", "Reviewer2Confirmed"}


def build_12(entries: Iterable, source: str, target: str, code: Callable[[str], str] = lambda c: c) -> bytes:
    """One <file> for one language pair; every entry is final and approved."""
    root = etree.Element(f"{{{NS12}}}xliff", nsmap={None: NS12}, version="1.2")
    f = etree.SubElement(
        root, f"{{{NS12}}}file", original="translation-memory", datatype="plaintext",
        attrib={"source-language": code(source), "target-language": code(target), "tool-id": "OnlineDocTranslator"},
    )
    header = etree.SubElement(f, f"{{{NS12}}}header")
    etree.SubElement(header, f"{{{NS12}}}tool", attrib={"tool-id": "OnlineDocTranslator", "tool-name": "OnlineDocTranslator"})
    body = etree.SubElement(f, f"{{{NS12}}}body")
    for e in entries:
        tu = etree.SubElement(body, f"{{{NS12}}}trans-unit", id=str(e.id), approved="yes")
        etree.SubElement(tu, f"{{{NS12}}}source").text = safe_xml.clean(e.source_text)
        etree.SubElement(tu, f"{{{NS12}}}target", state="final").text = safe_xml.clean(e.translated_text)
    return safe_xml.to_bytes(root)


def build_20(entries: Iterable, source: str, target: str, code: Callable[[str], str] = lambda c: c) -> bytes:
    root = etree.Element(
        f"{{{NS20}}}xliff", nsmap={None: NS20}, version="2.0", srcLang=code(source), trgLang=code(target),
    )
    f = etree.SubElement(root, f"{{{NS20}}}file", id="f1", original="translation-memory")
    for i, e in enumerate(entries, 1):
        unit = etree.SubElement(f, f"{{{NS20}}}unit", id=f"u{i}", name=str(e.id))
        seg = etree.SubElement(unit, f"{{{NS20}}}segment", state="final")
        etree.SubElement(seg, f"{{{NS20}}}source").text = safe_xml.clean(e.source_text)
        etree.SubElement(seg, f"{{{NS20}}}target").text = safe_xml.clean(e.translated_text)
    return safe_xml.to_bytes(root)


def _add(out: Parsed, src: str, tgt: str, source: str, target: str) -> None:
    if src and tgt and source and target:
        out.pairs.append({"source_language": src, "target_language": tgt, "source_text": source, "translated_text": target})
    else:
        out.invalid += 1


def _unit_confirmed(tu, target) -> bool:
    if (tu.get("approved") or "").lower() == "yes":
        return True
    if target is not None and (target.get("state") or "").lower() in _CONFIRMED_STATES:
        return True
    return (tu.get(f"{{{MQ}}}status") or "") in _MQ_CONFIRMED


def _segments(container) -> dict:
    """mid -> <mrk mtype="seg"> inside a seg-source or target."""
    if container is None:
        return {}
    return {m.get("mid"): m for m in container.iter() if local(m.tag) == "mrk" and m.get("mtype") == "seg"}


def _parse_12(root) -> Parsed:
    out = Parsed()
    for f in safe_xml.children(root, "file"):
        src, tgt = f.get("source-language") or "", f.get("target-language") or ""
        for tu in f.iter():
            if local(tu.tag) != "trans-unit" or (tu.get("translate") or "").lower() == "no":
                continue
            target = safe_xml.child(tu, "target")
            sdl_defs = {s.get("id"): s for s in tu.iter(f"{{{SDL}}}seg")}
            src_segs = _segments(safe_xml.child(tu, "seg-source"))
            if src_segs:
                tgt_segs = _segments(target)
                for mid, mrk in src_segs.items():
                    out.units += 1
                    check_units(out.units)
                    conf = sdl_defs[mid].get("conf") if mid in sdl_defs else None
                    ok = conf in _SDL_CONFIRMED if sdl_defs else _unit_confirmed(tu, target)
                    if not ok:
                        out.unconfirmed += 1
                        continue
                    tmrk = tgt_segs.get(mid)
                    _add(out, src, tgt, safe_xml.flat_text(mrk, _DROP12),
                         safe_xml.flat_text(tmrk, _DROP12) if tmrk is not None else "")
                continue
            out.units += 1
            check_units(out.units)
            if not _unit_confirmed(tu, target):
                out.unconfirmed += 1
                continue
            source = safe_xml.child(tu, "source")
            _add(out, src, tgt, safe_xml.flat_text(source, _DROP12) if source is not None else "",
                 safe_xml.flat_text(target, _DROP12))
    return out


def _parse_20(root) -> Parsed:
    out = Parsed()
    src, tgt = root.get("srcLang") or "", root.get("trgLang") or ""
    for seg in root.iter():
        if local(seg.tag) != "segment":
            continue
        out.units += 1
        check_units(out.units)
        if (seg.get("state") or "initial") not in _CONFIRMED_STATES:
            out.unconfirmed += 1
            continue
        source, target = safe_xml.child(seg, "source"), safe_xml.child(seg, "target")
        _add(out, src, tgt, safe_xml.flat_text(source, _DROP20) if source is not None else "",
             safe_xml.flat_text(target, _DROP20) if target is not None else "")
    return out


def parse_root(root) -> Parsed:
    if local(root.tag) != "xliff":
        raise XmlError("Not an XLIFF file")
    if (root.get("version") or "").startswith("2") or root.tag.startswith(f"{{{NS20}}}"):
        return _parse_20(root)
    return _parse_12(root)
