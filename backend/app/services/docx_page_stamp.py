"""The team stamp as a visible part of the editable DOCX: one picture in the footer of every section."""
from __future__ import annotations

import posixpath

from lxml import etree

from app.services import docx_blocks as blocks
from app.services import docx_images as images
from app.services.docx_blocks import R_NS, WP_NS, DocxEditError, _Doc, w

# Custom document property: the editor document carries its page stamp itself, so export adds none.
MARKER = "_page_stamp_v1"
STAMP_NAME = "page_stamp"
DEFAULT_WIDTH_CM = 3.0
MIN_WIDTH_CM, MAX_WIDTH_CM = 2.5, 6.0
DOCUMENT = "word/document.xml"
_CUSTOM = "docProps/custom.xml"
_CUSTOM_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
_VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
_CUSTOM_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
_CUSTOM_TYPE = "application/vnd.openxmlformats-officedocument.custom-properties+xml"
_FOOTER_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer"
_FOOTER_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_PKG_REL = f"{{{blocks.PKG_REL_NS}}}Relationship"
_FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"
_SECT_HEAD = (w("headerReference"), w("footerReference"))


def _wp(tag: str) -> str:
    return f"{{{WP_NS}}}{tag}"


def _xml(el) -> bytes:
    return etree.tostring(el, xml_declaration=True, encoding="UTF-8", standalone=True)


def _content_types(doc: _Doc):
    return etree.fromstring(doc.files["[Content_Types].xml"], blocks._PARSER)


def _add_override(doc: _Doc, part: str, content_type: str) -> None:
    ct = _content_types(doc)
    name = "/" + part
    if not any(o.get("PartName") == name for o in ct.findall(f"{{{_CT_NS}}}Override")):
        etree.SubElement(ct, f"{{{_CT_NS}}}Override", PartName=name, ContentType=content_type)
        doc.files["[Content_Types].xml"] = _xml(ct)


def _add_rel(rels, rel_type: str, target: str) -> str:
    taken = {r.get("Id") for r in rels}
    n = len(taken) + 1
    while f"rId{n}" in taken:
        n += 1
    etree.SubElement(rels, _PKG_REL, Id=f"rId{n}", Type=rel_type, Target=target)
    return f"rId{n}"


# --- marker -------------------------------------------------------------------


def _is_marked(doc: _Doc) -> bool:
    raw = doc.files.get(_CUSTOM)
    if not raw:
        return False
    root = etree.fromstring(raw, blocks._PARSER)
    return any(p.get("name") == MARKER for p in root.findall(f"{{{_CUSTOM_NS}}}property"))


def is_marked(data: bytes) -> bool:
    try:
        return _is_marked(_Doc.load(data))
    except Exception:
        return False


def _mark(doc: _Doc) -> None:
    if _is_marked(doc):
        return
    raw = doc.files.get(_CUSTOM)
    if raw:
        root = etree.fromstring(raw, blocks._PARSER)
    else:
        root = etree.Element(f"{{{_CUSTOM_NS}}}Properties", nsmap={None: _CUSTOM_NS, "vt": _VT_NS})
        if "_rels/.rels" not in doc.files:
            raise DocxEditError("Not a Word document")
        rels = etree.fromstring(doc.files["_rels/.rels"], blocks._PARSER)
        if not any(r.get("Type") == _CUSTOM_REL for r in rels):
            _add_rel(rels, _CUSTOM_REL, _CUSTOM)
            doc.files["_rels/.rels"] = _xml(rels)
        _add_override(doc, _CUSTOM, _CUSTOM_TYPE)
    pids = [int(p.get("pid") or 1) for p in root.findall(f"{{{_CUSTOM_NS}}}property")]
    prop = etree.SubElement(root, f"{{{_CUSTOM_NS}}}property", fmtid=_FMTID, pid=str(max(pids, default=1) + 1), name=MARKER)
    etree.SubElement(prop, f"{{{_VT_NS}}}lpwstr").text = "1"
    doc.files[_CUSTOM] = _xml(root)


# --- footers ------------------------------------------------------------------


def _sect_prs(doc: _Doc) -> list:
    found = list(doc.trees[DOCUMENT].iter(w("sectPr")))
    if not found:
        found = [etree.SubElement(doc.trees[DOCUMENT].find(w("body")), w("sectPr"))]
    return found


def _footer_part(doc: _Doc, rid: str) -> str | None:
    for rel in doc.rels(DOCUMENT):
        if rel.get("Id") == rid and rel.get("Type") == _FOOTER_REL:
            return posixpath.normpath(posixpath.join("word", rel.get("Target") or ""))
    return None


def _new_footer(doc: _Doc) -> str:
    n = 1
    while f"word/footer{n}.xml" in doc.files or f"word/footer{n}.xml" in doc.trees:
        n += 1
    part = f"word/footer{n}.xml"
    ftr = etree.Element(w("ftr"), nsmap={"w": blocks.W_NS, "r": R_NS, "wp": WP_NS})
    doc.trees[part] = ftr
    doc.files[part] = _xml(ftr)
    _add_override(doc, part, _FOOTER_TYPE)
    return part


def _footers_for_stamp(doc: _Doc) -> list[str]:
    """Footer parts showing on every page: each section's default footer, and its first-page one when it has one."""
    parts: list[str] = []
    created: dict[str, str] = {}
    for sect in _sect_prs(doc):
        kinds = ["default"] + (["first"] if sect.find(w("titlePg")) is not None else [])
        for kind in kinds:
            ref = next((r for r in sect.findall(w("footerReference")) if r.get(w("type")) == kind), None)
            part = _footer_part(doc, ref.get(f"{{{R_NS}}}id")) if ref is not None else None
            if part is None or part not in doc.trees:
                if "stamp" not in created:
                    part = _new_footer(doc)
                    created["stamp"] = part
                    created["rid"] = _add_rel(doc.rels(DOCUMENT), _FOOTER_REL, posixpath.relpath(part, "word"))
                part = created["stamp"]
                if ref is None:
                    ref = etree.Element(w("footerReference"))
                    heads = [c for c in sect if c.tag in _SECT_HEAD]
                    if heads:
                        heads[-1].addnext(ref)
                    else:
                        sect.insert(0, ref)
                ref.set(w("type"), kind)
                ref.set(f"{{{R_NS}}}id", created["rid"])
            if part not in parts:
                parts.append(part)
    return parts


def _stamp_frames(doc: _Doc):
    for name, tree in doc.trees.items():
        if not name.startswith("word/footer"):
            continue
        for docpr in tree.iter(_wp("docPr")):
            if docpr.get("name") == STAMP_NAME:
                yield name, docpr.getparent()


def _clamp(width_cm: float) -> float:
    return min(max(float(width_cm), MIN_WIDTH_CM), MAX_WIDTH_CM)


def _add_stamps(doc: _Doc, image: images.PreparedImage, align: str, width_cm: float) -> None:
    cx = int(_clamp(width_cm) * images.EMU_PER_CM)
    cy = max(1, int(cx * image.height_px / max(1, image.width_px)))
    for part in _footers_for_stamp(doc):
        rid = images.add_image_part(doc, image, part)
        frame = images._build_inline(STAMP_NAME, images._next_docpr_id(doc), cx, cy, images._graphic(rid, STAMP_NAME, cx, cy))
        p = images._image_paragraph(align)
        p.append(images._new_run(frame))
        doc.trees[part].append(p)


def _remove_stamps(doc: _Doc) -> None:
    touched = set()
    for part, frame in list(_stamp_frames(doc)):
        run = blocks.drawing_run(frame.getparent())
        p = images._paragraph_of(run)
        run.getparent().remove(run)
        if p is not None and not images._has_content(p) and p.getparent() is not None:
            p.getparent().remove(p)
        touched.add(part)
    for part in touched:
        tree = doc.trees[part]
        if tree.find(w("p")) is None and tree.find(w("tbl")) is None:
            etree.SubElement(tree, w("p"))
        images._prune_unused_media(doc, part)


def _finish(doc: _Doc) -> bytes:
    blocks._tag(doc)
    out = doc.dump()
    blocks._check_opens(out)
    return out


# --- public -------------------------------------------------------------------


def install(data: bytes, image: images.PreparedImage | None, align: str = "right", width_cm: float = DEFAULT_WIDTH_CM) -> bytes:
    """Mark a new editor document and put the team stamp (if any) in its footers."""
    doc = _Doc.load(data)
    _mark(doc)
    if image is not None and next(_stamp_frames(doc), None) is None:
        _add_stamps(doc, image, align if align in images.ALIGNS else "right", width_cm)
    return _finish(doc)


def state(data: bytes) -> dict:
    doc = _Doc.load(data)
    out = {"managed": _is_marked(doc), "enabled": False, "align": "right", "width_cm": DEFAULT_WIDTH_CM}
    frame = next((f for _, f in _stamp_frames(doc)), None)
    if frame is not None:
        cx = int(frame.find(_wp("extent")).get("cx"))
        out.update(
            enabled=True,
            align=images._align_of(images._paragraph_of(frame)),
            width_cm=round(cx / images.EMU_PER_CM, 1),
        )
    return out


def update(
    data: bytes,
    *,
    enabled: bool | None = None,
    align: str | None = None,
    width_cm: float | None = None,
    image: images.PreparedImage | None = None,
) -> bytes:
    if align is not None and align not in images.ALIGNS:
        raise DocxEditError("align must be left, center or right")
    doc = _Doc.load(data)
    if not _is_marked(doc):
        raise DocxEditError("This document's page stamp is added at export")
    current = state(data)
    if enabled is False:
        if not current["enabled"]:
            return data
        _remove_stamps(doc)
        return _finish(doc)
    if not current["enabled"]:
        if not enabled:
            raise DocxEditError("Turn the page stamp on first")
        if image is None:
            raise DocxEditError("No stamp saved in Settings")
        _add_stamps(doc, image, align or current["align"], width_cm or current["width_cm"])
        return _finish(doc)
    for _, frame in _stamp_frames(doc):
        if width_cm is not None:
            old_cx, old_cy = images._size(frame)
            cx = int(_clamp(width_cm) * images.EMU_PER_CM)
            cy = max(1, int(cx * old_cy / max(1, old_cx)))
            frame.find(_wp("extent")).set("cx", str(cx))
            frame.find(_wp("extent")).set("cy", str(cy))
            for ext in frame.iter(images.a("ext")):
                ext.set("cx", str(cx))
                ext.set("cy", str(cy))
        if align is not None:
            images._set_align(images._paragraph_of(frame), align)
    return _finish(doc)


def export_stamp(data: bytes) -> tuple[bytes, str, int] | None:
    """(image bytes, alignment, width in EMU) of the stamp the editor shows, for the export's footer."""
    doc = _Doc.load(data)
    for part, frame in _stamp_frames(doc):
        blip = next(frame.iter(images.a("blip")), None)
        rid = blip.get(f"{{{R_NS}}}embed") if blip is not None else None
        rel = next((r for r in doc.rels(part) if r.get("Id") == rid), None)
        media = doc.files.get(images._media_path(part, rel.get("Target") or "")) if rel is not None else None
        if media:
            align = images._align_of(images._paragraph_of(frame))
            return media, align, images._size(frame)[0]
    return None
