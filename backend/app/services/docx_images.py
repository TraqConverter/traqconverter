"""Pictures in the editable DOCX: insert, move, float, resize and delete, addressed by a stable image id."""
from __future__ import annotations

import hashlib
import io
import posixpath
import secrets
from dataclasses import dataclass

from lxml import etree
from PIL import Image, ImageOps, UnidentifiedImageError

from app.services import docx_blocks as blocks
from app.services.docx_blocks import (
    A_NS,
    IMAGE_ID_RE,
    IMAGE_REL,
    PIC_NS,
    R_NS,
    WP_NS,
    DocxEditError,
    _Doc,
    w,
)

EMU_PER_CM = 360_000
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_SIDE_PX = 2400
MIN_WIDTH_CM, MAX_WIDTH_CM = 0.5, 19.0
DEFAULT_WIDTH_CM = 4.0
POSITIONS = ("before", "after", "inline")
ALIGNS = ("left", "center", "right")
DOCUMENT = "word/document.xml"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_PKG_REL = f"{{{blocks.PKG_REL_NS}}}Relationship"
_ALIGN_JC = {"left": "left", "center": "center", "right": "right"}
_MAX_OFFSET_EMU = 60 * EMU_PER_CM


def wp(tag: str) -> str:
    return f"{{{WP_NS}}}{tag}"


def a(tag: str) -> str:
    return f"{{{A_NS}}}{tag}"


class ImageError(DocxEditError):
    pass


@dataclass
class PreparedImage:
    data: bytes
    ext: str
    width_px: int
    height_px: int


def _looks_like_paper(img: Image.Image) -> bool:
    rgb = img.convert("RGB")
    w_, h_ = rgb.size
    border = [rgb.getpixel((x, y)) for x in range(0, w_, max(1, w_ // 40)) for y in (0, h_ - 1)]
    border += [rgb.getpixel((x, y)) for y in range(0, h_, max(1, h_ // 40)) for x in (0, w_ - 1)]
    light = sum(1 for px in border if min(px) >= 200)
    return light >= 0.8 * len(border)


def _clear_background(img: Image.Image) -> Image.Image:
    """Turn near-white paper transparent with a soft edge, so a scanned stamp overlays text like ink."""
    rgba = img.convert("RGBA")
    px = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, alpha = px[x, y]
            lightness = min(r, g, b)
            if lightness >= 235:
                px[x, y] = (r, g, b, 0)
            elif lightness >= 190:
                px[x, y] = (r, g, b, int(alpha * (235 - lightness) / 45))
    return rgba


def prepare_image(
    raw: bytes,
    remove_background: bool = False,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
    formats: tuple[str, ...] = ("PNG", "JPEG", "WEBP"),
) -> PreparedImage:
    """Validate an upload and re-encode it (drops EXIF/metadata, honours rotation, caps size)."""
    if len(raw) > max_bytes:
        raise ImageError(f"Images must be {max_bytes // (1024 * 1024)} MB or smaller")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        probe = Image.open(io.BytesIO(raw))
        fmt = probe.format
        probe.verify()
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as e:
        raise ImageError("That file isn't a readable PNG, JPG or WebP image") from e
    if fmt not in formats:
        raise ImageError("Use a PNG, JPG or WebP image")
    img = ImageOps.exif_transpose(img)
    if max(img.size) > MAX_SIDE_PX:
        img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX), Image.LANCZOS)
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    if remove_background and not has_alpha and _looks_like_paper(img):
        img = _clear_background(img)
        has_alpha = True
    out = io.BytesIO()
    if has_alpha or fmt != "JPEG":
        img = img.convert("RGBA" if has_alpha else "RGB")
        img.save(out, "PNG", optimize=True)
        ext = "png"
    else:
        img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
        ext = "jpeg"
    return PreparedImage(out.getvalue(), ext, img.width, img.height)


def _content_types(doc: _Doc) -> etree._Element:
    return etree.fromstring(doc.files["[Content_Types].xml"], blocks._PARSER)


def _ensure_default_type(doc: _Doc, ext: str) -> None:
    ct = _content_types(doc)
    if any((d.get("Extension") or "").lower() == ext for d in ct.findall(f"{{{_CT_NS}}}Default")):
        return
    el = etree.SubElement(ct, f"{{{_CT_NS}}}Default")
    el.set("Extension", ext)
    el.set("ContentType", "image/png" if ext == "png" else "image/jpeg")
    ct.insert(0, el)
    doc.files["[Content_Types].xml"] = etree.tostring(ct, xml_declaration=True, encoding="UTF-8", standalone=True)


def _media_path(part: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(part), target))


def add_image_part(doc: _Doc, image: PreparedImage, part: str = DOCUMENT) -> str:
    """Relationship id for the image bytes, reusing an identical picture already in the part."""
    rels = doc.rels(part)
    digest = hashlib.sha256(image.data).hexdigest()
    for rel in rels:
        if rel.get("Type") == IMAGE_REL and (rel.get("TargetMode") or "Internal") != "External":
            existing = doc.files.get(_media_path(part, rel.get("Target") or ""))
            if existing and hashlib.sha256(existing).hexdigest() == digest:
                return rel.get("Id")
    name = f"media/tq_{digest[:12]}.{image.ext}"
    doc.files[_media_path(part, name)] = image.data
    _ensure_default_type(doc, image.ext)
    taken = {r.get("Id") for r in rels}
    n = len(taken) + 1
    while f"rId{n}" in taken:
        n += 1
    rel = etree.SubElement(rels, _PKG_REL)
    rel.set("Id", f"rId{n}")
    rel.set("Type", IMAGE_REL)
    rel.set("Target", name)
    return f"rId{n}"


def _prune_unused_media(doc: _Doc, part: str = DOCUMENT) -> None:
    tree = doc.trees[part]
    embed = f"{{{R_NS}}}embed"
    used = {el.get(embed) for el in tree.iter() if el.get(embed)}
    rels = doc.rels(part)
    for rel in list(rels):
        if rel.get("Type") != IMAGE_REL or rel.get("Id") in used or (rel.get("TargetMode") or "") == "External":
            continue
        target = _media_path(part, rel.get("Target") or "")
        rels.remove(rel)
        still_used = any(_media_path(part, r.get("Target") or "") == target for r in rels)
        if not still_used:
            doc.files.pop(target, None)


def _next_docpr_id(doc: _Doc) -> int:
    ids = [0]
    for el in doc.trees[DOCUMENT].iter(wp("docPr")):
        try:
            ids.append(int(el.get("id", "0")))
        except ValueError:
            pass
    return max(ids) + 1


def _graphic(rid: str, image_id: str, cx: int, cy: int):
    graphic = etree.Element(a("graphic"), nsmap={"a": A_NS})
    data = etree.SubElement(graphic, a("graphicData"), uri=PIC_NS)
    pic = etree.SubElement(data, f"{{{PIC_NS}}}pic", nsmap={"pic": PIC_NS})
    nv = etree.SubElement(pic, f"{{{PIC_NS}}}nvPicPr")
    etree.SubElement(nv, f"{{{PIC_NS}}}cNvPr", id="0", name=f"{image_id}.png")
    etree.SubElement(nv, f"{{{PIC_NS}}}cNvPicPr")
    fill = etree.SubElement(pic, f"{{{PIC_NS}}}blipFill")
    blip = etree.SubElement(fill, a("blip"), nsmap={"r": R_NS})
    blip.set(f"{{{R_NS}}}embed", rid)
    etree.SubElement(etree.SubElement(fill, a("stretch")), a("fillRect"))
    sp = etree.SubElement(pic, f"{{{PIC_NS}}}spPr")
    xfrm = etree.SubElement(sp, a("xfrm"))
    etree.SubElement(xfrm, a("off"), x="0", y="0")
    etree.SubElement(xfrm, a("ext"), cx=str(cx), cy=str(cy))
    geom = etree.SubElement(sp, a("prstGeom"), prst="rect")
    etree.SubElement(geom, a("avLst"))
    return graphic


def _build_inline(image_id: str, docpr_id: int, cx: int, cy: int, graphic):
    inline = etree.Element(wp("inline"), nsmap={"wp": WP_NS}, distT="0", distB="0", distL="0", distR="0")
    etree.SubElement(inline, wp("extent"), cx=str(cx), cy=str(cy))
    etree.SubElement(inline, wp("effectExtent"), l="0", t="0", r="0", b="0")
    etree.SubElement(inline, wp("docPr"), id=str(docpr_id), name=image_id)
    frame = etree.SubElement(inline, wp("cNvGraphicFramePr"))
    etree.SubElement(frame, a("graphicFrameLocks"), nsmap={"a": A_NS}, noChangeAspect="1")
    inline.append(graphic)
    return inline


def _build_anchor(image_id: str, docpr_id: int, cx: int, cy: int, graphic, x: int, y: int):
    anchor = etree.Element(
        wp("anchor"),
        nsmap={"wp": WP_NS},
        distT="0", distB="0", distL="0", distR="0",
        simplePos="0", relativeHeight="251659264", behindDoc="0", locked="0", layoutInCell="1", allowOverlap="1",
    )
    etree.SubElement(anchor, wp("simplePos"), x="0", y="0")
    h = etree.SubElement(anchor, wp("positionH"), relativeFrom="column")
    etree.SubElement(h, wp("posOffset")).text = str(x)
    v = etree.SubElement(anchor, wp("positionV"), relativeFrom="paragraph")
    etree.SubElement(v, wp("posOffset")).text = str(y)
    etree.SubElement(anchor, wp("extent"), cx=str(cx), cy=str(cy))
    etree.SubElement(anchor, wp("effectExtent"), l="0", t="0", r="0", b="0")
    etree.SubElement(anchor, wp("wrapNone"))
    etree.SubElement(anchor, wp("docPr"), id=str(docpr_id), name=image_id)
    frame = etree.SubElement(anchor, wp("cNvGraphicFramePr"))
    etree.SubElement(frame, a("graphicFrameLocks"), nsmap={"a": A_NS}, noChangeAspect="1")
    anchor.append(graphic)
    return anchor


def _new_run(frame):
    run = etree.Element(w("r"))
    drawing = etree.SubElement(run, w("drawing"))
    drawing.append(frame)
    return run


def _block_paragraph(doc: _Doc, block_id: str):
    p = doc.find_block(block_id)
    if p is None or p.tag != w("p") or doc.part_of(p) != DOCUMENT:
        raise DocxEditError(f"Unknown paragraph {block_id}")
    return p


def _find_image(doc: _Doc, image_id: str):
    """(drawing, frame, run) for an image id."""
    if not IMAGE_ID_RE.match(image_id or ""):
        raise DocxEditError("Unknown image")
    for docpr in doc.trees[DOCUMENT].iter(wp("docPr")):
        if docpr.get("name") == image_id:
            frame = docpr.getparent()
            drawing = frame.getparent()
            run = blocks.drawing_run(drawing)
            if drawing.tag == w("drawing") and run is not None:
                return drawing, frame, run
    raise DocxEditError("Unknown image")


def _insertion_index(p) -> int:
    """First position after pPr and the leading bookmarks, where a floating picture renders at the paragraph's top-left."""
    i = 0
    for i, child in enumerate(p):
        if child.tag not in (w("pPr"), w("bookmarkStart"), w("bookmarkEnd")):
            return i
    return len(p)


def _set_align(p, align: str | None) -> None:
    if not align:
        return
    ppr = p.find(w("pPr"))
    if ppr is None:
        ppr = etree.Element(w("pPr"))
        p.insert(0, ppr)
    jc = ppr.find(w("jc"))
    if jc is None:
        jc = etree.SubElement(ppr, w("jc"))
        # Schema order: jc comes before rPr / sectPr inside pPr.
        for tail in (w("rPr"), w("sectPr"), w("pPrChange")):
            other = ppr.find(tail)
            if other is not None:
                other.addprevious(jc)
                break
    jc.set(w("val"), _ALIGN_JC[align])


def _image_paragraph(align: str | None):
    p = etree.Element(w("p"))
    ppr = etree.SubElement(p, w("pPr"))
    spacing = etree.SubElement(ppr, w("spacing"))
    spacing.set(w("before"), "0")
    spacing.set(w("after"), "0")
    _set_align(p, align or "left")
    return p


def _place_inline(doc: _Doc, run, target_block_id: str, position: str, align: str | None) -> None:
    target = _block_paragraph(doc, target_block_id)
    if position == "inline":
        target.append(run)
        _set_align(target, align)
        return
    p = _image_paragraph(align)
    p.append(run)
    if position == "before":
        target.addprevious(p)
    else:
        target.addnext(p)


def _detach(doc: _Doc, run, keep=None) -> None:
    """Remove the picture run; drop its paragraph when nothing else is left in it, unless it is `keep`."""
    p = run.getparent()
    prev = run.getprevious()
    if prev is not None and prev.tag == w("bookmarkEnd"):
        start = prev.getprevious()
        if start is not None and start.tag == w("bookmarkStart") and (start.get(w("name")) or "").startswith("_img_"):
            p.remove(start)
            p.remove(prev)
    p.remove(run)
    while p is not None and p.tag != w("p"):
        p = p.getparent()
    if p is None or p is keep or blocks.paragraph_text(p).strip() or next(p.iter(w("drawing")), None) is not None:
        return
    if p.find(f"{w('pPr')}/{w('sectPr')}") is not None:
        return
    if any(bm.get(w("name")) in blocks.CERT_MARKERS for bm in p.iter(w("bookmarkStart"))):
        return
    container = p.getparent()
    if container is None or container.tag not in (w("body"), w("tc")):
        return
    siblings = [c for c in container if c.tag == w("p")]
    if len(siblings) > 1 and any(c.tag == w("p") for c in p.itersiblings()):
        container.remove(p)


def _size(frame) -> tuple[int, int]:
    ext = frame.find(wp("extent"))
    return int(ext.get("cx")), int(ext.get("cy"))


def _rebuild_frame(doc: _Doc, drawing, frame, *, floating: bool, x: int = 0, y: int = 0, cx: int | None = None, cy: int | None = None):
    old_cx, old_cy = _size(frame)
    cx, cy = cx or old_cx, cy or old_cy
    docpr = frame.find(wp("docPr"))
    graphic = frame.find(a("graphic"))
    for ext in graphic.iter(a("ext")):
        ext.set("cx", str(cx))
        ext.set("cy", str(cy))
    image_id, docpr_id = docpr.get("name"), int(docpr.get("id", "1"))
    new = (
        _build_anchor(image_id, docpr_id, cx, cy, graphic, x, y)
        if floating
        else _build_inline(image_id, docpr_id, cx, cy, graphic)
    )
    drawing.replace(frame, new)
    return new


def _finish(doc: _Doc) -> bytes:
    blocks._tag(doc)
    out = doc.dump()
    blocks._check_opens(out)
    return out


def _clamp_width(width_cm: float) -> float:
    return min(max(float(width_cm), MIN_WIDTH_CM), MAX_WIDTH_CM)


def insert_image(
    data: bytes,
    image: PreparedImage,
    block_id: str,
    position: str = "after",
    width_cm: float | None = None,
    align: str | None = "left",
) -> tuple[bytes, str]:
    if position not in POSITIONS:
        raise DocxEditError("position must be before, after or inline")
    if align is not None and align not in ALIGNS:
        raise DocxEditError("align must be left, center or right")
    doc = _Doc.load(data)
    _block_paragraph(doc, block_id)
    rid = add_image_part(doc, image)
    cx = int(_clamp_width(width_cm or DEFAULT_WIDTH_CM) * EMU_PER_CM)
    cy = max(1, int(cx * image.height_px / max(1, image.width_px)))
    image_id = "img_" + secrets.token_hex(4)
    frame = _build_inline(image_id, _next_docpr_id(doc), cx, cy, _graphic(rid, image_id, cx, cy))
    _place_inline(doc, _new_run(frame), block_id, position, align)
    return _finish(doc), image_id


def move_image(data: bytes, image_id: str, target_block_id: str, position: str = "after", align: str | None = None) -> bytes:
    if position not in POSITIONS:
        raise DocxEditError("position must be before, after or inline")
    if align is not None and align not in ALIGNS:
        raise DocxEditError("align must be left, center or right")
    doc = _Doc.load(data)
    target = _block_paragraph(doc, target_block_id)
    drawing, frame, run = _find_image(doc, image_id)
    if frame.tag == wp("anchor"):
        _rebuild_frame(doc, drawing, frame, floating=False)
    _detach(doc, run, keep=target)
    _place_inline(doc, run, target_block_id, position, align)
    return _finish(doc)


def align_image(data: bytes, image_id: str, align: str) -> bytes:
    if align not in ALIGNS:
        raise DocxEditError("align must be left, center or right")
    doc = _Doc.load(data)
    drawing, frame, run = _find_image(doc, image_id)
    if frame.tag == wp("anchor"):
        _rebuild_frame(doc, drawing, frame, floating=False)
    p = run.getparent()
    while p is not None and p.tag != w("p"):
        p = p.getparent()
    if p is not None:
        _set_align(p, align)
    return _finish(doc)


def float_image(data: bytes, image_id: str, target_block_id: str, x_emu: int, y_emu: int) -> bytes:
    """Anchor the picture to a paragraph at an offset (x from the column's left, y from the paragraph's top)."""
    x = max(-_MAX_OFFSET_EMU, min(_MAX_OFFSET_EMU, int(x_emu)))
    y = max(-_MAX_OFFSET_EMU, min(_MAX_OFFSET_EMU, int(y_emu)))
    doc = _Doc.load(data)
    target = _block_paragraph(doc, target_block_id)
    drawing, frame, run = _find_image(doc, image_id)
    _rebuild_frame(doc, drawing, frame, floating=True, x=x, y=y)
    # Dropping a picture onto its own empty paragraph must not delete the paragraph it goes back into.
    _detach(doc, run, keep=target)
    target.insert(_insertion_index(target), run)
    return _finish(doc)


def resize_image(data: bytes, image_id: str, width_cm: float) -> bytes:
    doc = _Doc.load(data)
    drawing, frame, _ = _find_image(doc, image_id)
    old_cx, old_cy = _size(frame)
    cx = int(_clamp_width(width_cm) * EMU_PER_CM)
    cy = max(1, int(cx * old_cy / max(1, old_cx)))
    frame.find(wp("extent")).set("cx", str(cx))
    frame.find(wp("extent")).set("cy", str(cy))
    for ext in frame.find(a("graphic")).iter(a("ext")):
        ext.set("cx", str(cx))
        ext.set("cy", str(cy))
    return _finish(doc)


def delete_image(data: bytes, image_id: str) -> bytes:
    doc = _Doc.load(data)
    _, _, run = _find_image(doc, image_id)
    _detach(doc, run)
    _prune_unused_media(doc)
    return _finish(doc)


def list_images(data: bytes) -> list[dict]:
    doc = _Doc.load(data)
    out = []
    for docpr in doc.trees[DOCUMENT].iter(wp("docPr")):
        name = docpr.get("name") or ""
        frame = docpr.getparent()
        if not IMAGE_ID_RE.match(name):
            continue
        p = frame
        while p is not None and p.tag != w("p"):
            p = p.getparent()
        cx, cy = _size(frame)
        entry = {
            "id": name,
            "block_id": blocks._block_id_of(p) if p is not None else None,
            "floating": frame.tag == wp("anchor"),
            "width_cm": round(cx / EMU_PER_CM, 2),
            "height_cm": round(cy / EMU_PER_CM, 2),
        }
        if entry["floating"]:
            entry["x_emu"] = int(frame.findtext(f"{wp('positionH')}/{wp('posOffset')}") or 0)
            entry["y_emu"] = int(frame.findtext(f"{wp('positionV')}/{wp('posOffset')}") or 0)
        out.append(entry)
    return out
