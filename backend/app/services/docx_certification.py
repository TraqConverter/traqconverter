"""The certification page as part of the editable DOCX: built once, fields kept in Word content controls."""
from __future__ import annotations

import copy
import re
import secrets
from dataclasses import dataclass, field
from datetime import date

from lxml import etree

from app.services import cert_locale, docx_blocks as blocks, docx_images as images
from app.services.docx_blocks import A_NS, PIC_NS, R_NS, DocxEditError, _Doc, w

FIELDS = ("translator", "date", "source_language", "target_language", "document")
TAG_PREFIX = "cert."
START, END = blocks.CERT_MARKERS
PAGE_STYLE_ID = "TQCertificationPage"
LOGO_WIDTH_CM = 3.5
STAMP_WIDTH_CM = 3.8
_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_TOKEN_FIELDS = {
    "translator_name": "translator",
    "date": "date",
    "date_long": "date",
    "source_language": "source_language",
    "target_language": "target_language",
    "document_name": "document",
}
_ALIASES = {
    "translator": "Translator",
    "date": "Date",
    "source_language": "Source language",
    "target_language": "Target language",
    "document": "Document",
}
_DOCUMENT = "word/document.xml"


@dataclass
class CertContent:
    lang: str
    values: dict[str, str]
    day: date
    pages: int = 0
    logo: images.PreparedImage | None = None
    stamp: images.PreparedImage | None = None
    template_docx: bytes | None = None
    statement_override: str | None = None
    extra_tokens: dict[str, str] = field(default_factory=dict)


def _body(doc: _Doc):
    return doc.trees[_DOCUMENT].find(w("body"))


def _marker_units(doc: _Doc) -> list:
    body = _body(doc)
    units = [c for c in body if c.tag != w("sectPr")]
    start = end = None
    for i, unit in enumerate(units):
        names = {bm.get(w("name")) for bm in unit.iter(w("bookmarkStart"))}
        if START in names and start is None:
            start = i
        if END in names and start is not None:
            end = i
    if start is None:
        return []
    return units[start: (end if end is not None else len(units) - 1) + 1]


def has_certification(data: bytes) -> bool:
    return bool(_marker_units(_Doc.load(data)))


def _sdts(root, name: str | None = None):
    for sdt in root.iter(w("sdt")):
        tag = sdt.find(f"{w('sdtPr')}/{w('tag')}")
        val = tag.get(w("val")) if tag is not None else ""
        if val and val.startswith(TAG_PREFIX) and (name is None or val == TAG_PREFIX + name):
            yield val[len(TAG_PREFIX):], sdt


def _sdt_text(sdt) -> str:
    content = sdt.find(w("sdtContent"))
    return blocks.paragraph_text(content) if content is not None else ""


def read_fields(data: bytes) -> dict | None:
    doc = _Doc.load(data)
    units = _marker_units(doc)
    if not units:
        return None
    fields: dict[str, str] = {}
    date_iso = ""
    for unit in units:
        for name, sdt in _sdts(unit):
            if name in FIELDS and name not in fields:
                fields[name] = _sdt_text(sdt)
                picker = sdt.find(f"{w('sdtPr')}/{w('date')}")
                if name == "date" and picker is not None:
                    date_iso = (picker.get(w("fullDate")) or "")[:10]
    fields["date_iso"] = date_iso
    return fields


def _rpr(bold: bool = False, size_half_points: int | None = None):
    rpr = etree.Element(w("rPr"))
    if bold:
        etree.SubElement(rpr, w("b"))
    if size_half_points:
        etree.SubElement(rpr, w("sz")).set(w("val"), str(size_half_points))
        etree.SubElement(rpr, w("szCs")).set(w("val"), str(size_half_points))
    return rpr


def _run(text: str, rpr=None):
    r = etree.Element(w("r"))
    if rpr is not None and len(rpr):
        r.append(copy.deepcopy(rpr))
    for el in blocks._elements_for(text):
        r.append(el)
    return r


def _sdt(name: str, value: str, rpr, lang: str, date_iso: str | None = None):
    sdt = etree.Element(w("sdt"))
    pr = etree.SubElement(sdt, w("sdtPr"))
    if rpr is not None and len(rpr):
        pr.append(copy.deepcopy(rpr))
    etree.SubElement(pr, w("alias")).set(w("val"), _ALIASES[name])
    etree.SubElement(pr, w("tag")).set(w("val"), TAG_PREFIX + name)
    etree.SubElement(pr, w("id")).set(w("val"), str(secrets.randbelow(2**31 - 1) + 1))
    if name == "date":
        picker = etree.SubElement(pr, w("date"))
        if date_iso:
            picker.set(w("fullDate"), f"{date_iso}T00:00:00Z")
        etree.SubElement(picker, w("dateFormat")).set(w("val"), cert_locale.DATE_PATTERNS[lang])
        etree.SubElement(picker, w("lid")).set(w("val"), cert_locale.LOCALE_IDS[lang])
        etree.SubElement(picker, w("storeMappedDataAs")).set(w("val"), "dateTime")
        etree.SubElement(picker, w("calendar")).set(w("val"), "gregorian")
    else:
        etree.SubElement(pr, w("text"))
    content = etree.SubElement(sdt, w("sdtContent"))
    content.append(_run(value, rpr))
    return sdt


def _paragraph(align: str | None = None, after: int = 120, keep_next: bool = False):
    p = etree.Element(w("p"))
    ppr = etree.SubElement(p, w("pPr"))
    if keep_next:
        etree.SubElement(ppr, w("keepNext"))
    spacing = etree.SubElement(ppr, w("spacing"))
    spacing.set(w("before"), "0")
    spacing.set(w("after"), str(after))
    if align:
        etree.SubElement(ppr, w("jc")).set(w("val"), align)
    return p


def _fill_with_tokens(p, text: str, content: CertContent, rpr) -> None:
    """Append `text` to p, turning known {{tokens}} into content controls and others into their values."""
    pos = 0
    for m in _TOKEN_RE.finditer(text):
        if m.start() > pos:
            p.append(_run(text[pos:m.start()], rpr))
        token = m.group(1)
        name = _TOKEN_FIELDS.get(token)
        if name:
            p.append(_sdt(name, content.values.get(name, ""), rpr, content.lang, content.day.isoformat() if name == "date" else None))
        elif token in content.extra_tokens:
            p.append(_run(content.extra_tokens[token], rpr))
        else:
            p.append(_run(m.group(0), rpr))
        pos = m.end()
    if pos < len(text):
        p.append(_run(text[pos:], rpr))


def _labelled(label: str, name: str | None, content: CertContent, value: str = ""):
    p = _paragraph(after=80)
    p.append(_run(f"{label}: ", _rpr(bold=True)))
    if name:
        p.append(_sdt(name, content.values.get(name, ""), None, content.lang, content.day.isoformat() if name == "date" else None))
    else:
        p.append(_run(value))
    return p


def _default_units(content: CertContent) -> tuple[list, object]:
    t = cert_locale.TEXT[content.lang]
    units = []
    title = _paragraph("center", after=360)
    title.append(_run(t["title"], _rpr(bold=True, size_half_points=32)))
    units.append(title)
    statement_lines = (content.statement_override or "").strip().splitlines() or [
        t["statement"].replace("{translator}", "{{translator_name}}")
    ]
    for line in statement_lines:
        p = _paragraph("both", after=240)
        _fill_with_tokens(p, line, content, None)
        units.append(p)
    units.append(_labelled(t["document"], "document", content))
    units.append(_labelled(t["source_language"], "source_language", content))
    units.append(_labelled(t["target_language"], "target_language", content))
    if content.pages:
        units.append(_labelled(t["pages"], None, content, str(content.pages)))
    units.append(_labelled(t["date"], "date", content))
    units.append(_paragraph(after=480))
    signature = _paragraph(after=60, keep_next=True)
    signature.append(_run(f"{t['signature']}: ______________________________"))
    units.append(signature)
    name = _paragraph(after=0)
    name.append(_sdt("translator", content.values.get("translator", ""), None, content.lang))
    units.append(name)
    return units, signature


def _unwrap(el) -> None:
    parent = el.getparent()
    index = parent.index(el)
    for child in list(el):
        parent.insert(index, child)
        index += 1
    parent.remove(el)


def _import_template(doc: _Doc, template: bytes, content: CertContent) -> tuple[list, object | None]:
    """Body of an uploaded certification template, made safe for the editor, with tokens as content controls."""
    try:
        src = _Doc.load(template)
    except Exception as e:
        raise DocxEditError("The certification template couldn't be read") from e
    src_body = src.trees[_DOCUMENT].find(w("body"))
    src_rels = {r.get("Id"): r for r in src.rels(_DOCUMENT)}
    embed = f"{{{R_NS}}}embed"
    units = []
    for child in src_body:
        if child.tag not in (w("p"), w("tbl")):
            continue
        unit = copy.deepcopy(child)
        blocks._strip_rsids(unit)
        for el in list(unit.iter(w("bookmarkStart"), w("bookmarkEnd"), w("sectPr"), w("pict"), w("object"), w("fldSimple"))):
            el.getparent().remove(el)
        for el in list(unit.iter(w("hyperlink"), w("smartTag"))):
            _unwrap(el)
        for drawing in list(unit.iter(w("drawing"))):
            run = blocks.drawing_run(drawing)
            blips = list(drawing.iter(f"{{{A_NS}}}blip"))
            ok = bool(blips) and next(drawing.iter(f"{{{PIC_NS}}}pic"), None) is not None
            for blip in blips:
                rel = src_rels.get(blip.get(embed) or "")
                raw = src.files.get(images._media_path(_DOCUMENT, rel.get("Target") or "")) if rel is not None else None
                try:
                    blip.set(embed, images.add_image_part(doc, images.prepare_image(raw or b"")))
                except DocxEditError:
                    ok = False
                for attr in [x for x in blip.attrib if x != embed and etree.QName(x).namespace == R_NS]:
                    del blip.attrib[attr]
            if not ok and run is not None and run.getparent() is not None:
                run.getparent().remove(run)
        for el in list(unit.iter()):
            if isinstance(el.tag, str) and el.getparent() is not None and el.tag != f"{{{A_NS}}}blip":
                if any(etree.QName(x).namespace == R_NS for x in el.attrib):
                    el.getparent().remove(el)
        for p in unit.iter(w("p")) if unit.tag == w("tbl") else [unit]:
            text = blocks.paragraph_text(p)
            if "{{" not in text:
                continue
            first = next((r for r in p.iter(w("r")) if r.find(w("t")) is not None), None)
            rpr = copy.deepcopy(first.find(w("rPr"))) if first is not None and first.find(w("rPr")) is not None else None
            for r in [r for r in p if r.tag == w("r") and r.find(w("drawing")) is None]:
                p.remove(r)
            _fill_with_tokens(p, text, content, rpr)
        units.append(unit)
    if not units:
        raise DocxEditError("The certification template is empty")
    signature = next(
        (u for u in reversed(units) if u.tag == w("p") and "_____" in blocks.paragraph_text(u)),
        next((u for u in reversed(units) if u.tag == w("p") and blocks.paragraph_text(u).strip()), None),
    )
    return units, signature


def _ensure_page_style(doc: _Doc) -> None:
    raw = doc.files.get("word/styles.xml")
    if not raw:
        return
    styles = etree.fromstring(raw, blocks._PARSER)
    if any(s.get(w("styleId")) == PAGE_STYLE_ID for s in styles.findall(w("style"))):
        return
    style = etree.SubElement(styles, w("style"))
    style.set(w("type"), "paragraph")
    style.set(w("customStyle"), "1")
    style.set(w("styleId"), PAGE_STYLE_ID)
    etree.SubElement(style, w("name")).set(w("val"), "Certification page")
    etree.SubElement(style, w("basedOn")).set(w("val"), "Normal")
    etree.SubElement(style, w("qFormat"))
    etree.SubElement(etree.SubElement(style, w("pPr")), w("pageBreakBefore"))
    doc.files["word/styles.xml"] = etree.tostring(styles, xml_declaration=True, encoding="UTF-8", standalone=True)


def _opening_paragraph(doc: _Doc, content: CertContent, with_logo: bool):
    # docx-preview only breaks pages on a style's pageBreakBefore; Word and the export read the direct one.
    p = _paragraph("center", after=240)
    ppr = p.find(w("pPr"))
    style = etree.Element(w("pStyle"))
    style.set(w("val"), PAGE_STYLE_ID)
    ppr.insert(0, style)
    style.addnext(etree.Element(w("pageBreakBefore")))
    if with_logo and content.logo is not None:
        rid = images.add_image_part(doc, content.logo)
        cx = int(LOGO_WIDTH_CM * images.EMU_PER_CM)
        cy = max(1, int(cx * content.logo.height_px / max(1, content.logo.width_px)))
        image_id = "img_" + secrets.token_hex(4)
        frame = images._build_inline(image_id, images._next_docpr_id(doc), cx, cy, images._graphic(rid, image_id, cx, cy))
        p.append(images._new_run(frame))
    return p


def _add_marker(p, name: str, bid: int, at_start: bool) -> None:
    start, end = blocks._marker_pair(bid, name)
    if at_start:
        index = 1 if p.find(w("pPr")) is not None else 0
        p.insert(index, start)
        p.insert(index + 1, end)
    else:
        p.append(start)
        p.append(end)


def _place_stamp(doc: _Doc, signature, stamp: images.PreparedImage) -> None:
    rid = images.add_image_part(doc, stamp)
    cx = int(STAMP_WIDTH_CM * images.EMU_PER_CM)
    cy = max(1, int(cx * stamp.height_px / max(1, stamp.width_px)))
    image_id = "img_" + secrets.token_hex(4)
    # Overlap the signature line the way a hand-applied stamp would.
    frame = images._build_anchor(
        image_id, images._next_docpr_id(doc), cx, cy, images._graphic(rid, image_id, cx, cy),
        int(6.5 * images.EMU_PER_CM), -int(cy * 0.55),
    )
    signature.insert(images._insertion_index(signature), images._new_run(frame))


def _remove_units(doc: _Doc) -> bool:
    units = _marker_units(doc)
    body = _body(doc)
    for unit in units:
        body.remove(unit)
    return bool(units)


def add_certification(data: bytes, content: CertContent) -> bytes:
    """Append the certification page (replacing an existing one) at the end of the document."""
    doc = _Doc.load(data)
    _remove_units(doc)
    if content.template_docx:
        units, signature = _import_template(doc, content.template_docx, content)
        has_own_images = any(next(u.iter(w("drawing")), None) is not None for u in units)
        opening = _opening_paragraph(doc, content, with_logo=not has_own_images)
    else:
        units, signature = _default_units(content)
        opening = _opening_paragraph(doc, content, with_logo=True)
    units.insert(0, opening)
    if units[-1].tag != w("p"):
        units.append(_paragraph(after=0))
    if content.stamp is not None and signature is not None:
        _place_stamp(doc, signature, content.stamp)
    bid = doc.next_bookmark_id()
    _add_marker(units[0], START, bid, at_start=True)
    _add_marker(units[-1], END, bid + 1, at_start=False)
    body = _body(doc)
    sect = body.find(w("sectPr"))
    for unit in units:
        if sect is not None:
            sect.addprevious(unit)
        else:
            body.append(unit)
    _ensure_page_style(doc)
    images._prune_unused_media(doc)
    return images._finish(doc)


def remove_certification(data: bytes) -> bytes:
    doc = _Doc.load(data)
    if not _remove_units(doc):
        raise DocxEditError("There is no certification page")
    body = _body(doc)
    if not any(c.tag in (w("p"), w("tbl")) for c in body):
        body.insert(0, etree.Element(w("p")))
    images._prune_unused_media(doc)
    return images._finish(doc)


def _set_sdt_text(sdt, value: str) -> None:
    content = sdt.find(w("sdtContent"))
    if content is None:
        content = etree.SubElement(sdt, w("sdtContent"))
    runs = list(content.iter(w("r")))
    for r in runs[1:]:
        r.getparent().remove(r)
    if runs:
        run = runs[0]
        for child in [c for c in run if c.tag != w("rPr")]:
            run.remove(child)
        for el in blocks._elements_for(value):
            run.append(el)
    else:
        rpr = sdt.find(f"{w('sdtPr')}/{w('rPr')}")
        content.append(_run(value, rpr))
    placeholder = sdt.find(f"{w('sdtPr')}/{w('showingPlcHdr')}")
    if placeholder is not None:
        placeholder.getparent().remove(placeholder)


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def update_fields(data: bytes, fields: dict[str, str], lang: str) -> tuple[bytes, list[str]]:
    doc = _Doc.load(data)
    units = _marker_units(doc)
    if not units:
        raise DocxEditError("There is no certification page")
    changed = []
    for name, value in fields.items():
        if name not in FIELDS or value is None:
            continue
        value = value.strip()
        for unit in units:
            for _, sdt in _sdts(unit, name):
                display = value
                if name == "date" and _ISO_DATE.match(value):
                    try:
                        day = date.fromisoformat(value)
                    except ValueError as e:
                        raise DocxEditError("Invalid date") from e
                    picker = sdt.find(f"{w('sdtPr')}/{w('date')}")
                    sdt_lang = lang
                    if picker is not None:
                        picker.set(w("fullDate"), f"{value}T00:00:00Z")
                        lid = picker.find(w("lid"))
                        code = cert_locale.language_code(lid.get(w("val")) if lid is not None else "")
                        sdt_lang = code if code in cert_locale.CERT_LANGS else lang
                    display = cert_locale.format_date(day, sdt_lang)
                if _sdt_text(sdt) != display:
                    _set_sdt_text(sdt, display)
                    if name not in changed:
                        changed.append(name)
    if not changed:
        return data, []
    return images._finish(doc), changed


_ISSUER_WORDS = {
    "republic", "repubblica", "república", "république", "republik", "kingdom", "state", "ministry", "ministero",
    "municipality", "comune", "province", "provincia", "region", "regione", "government", "office", "ufficio",
    "department", "prefecture", "prefettura", "embassy", "consulate", "university", "università",
}


def guess_document_title(data: bytes, fallback: str, doc_type: str = "") -> str:
    """Pick the translation's own title among its opening headings (country and authority lines rank lower)."""
    doc = _Doc.load(data)
    cert = {id(u) for u in _marker_units(doc)}
    type_words = {x for x in re.findall(r"[a-z]{4,}", (doc_type or "").lower())}
    best, best_score = None, 0.0
    seen = 0
    for unit in _body(doc):
        if unit.tag != w("p") or id(unit) in cert:
            continue
        text = " ".join(blocks.paragraph_text(unit).split())
        if not text:
            continue
        seen += 1
        if seen > 12:
            break
        letters = sum(ch.isalpha() for ch in text)
        if not (3 <= len(text) <= 90 and letters >= 0.6 * len(text)) or text.startswith("["):
            continue
        sizes = [int(v) for v in (el.get(w("val")) for el in unit.iter(w("sz"))) if v and v.isdigit()]
        score = max(sizes, default=22) / 2.0
        if any(True for _ in unit.iter(w("b"))):
            score += 2
        if any(el.get(w("val")) == "center" for el in unit.iter(w("jc"))):
            score += 2
        if text.isupper():
            score += 1
        if words_generic := set(re.findall(r"[a-z]{4,}", text.lower())) & _ISSUER_WORDS:
            score -= 6 * len(words_generic)
        # The detected document type ('residence certificate') is the strongest signal when it matches.
        words = set(re.findall(r"[a-z]{4,}", text.lower()))
        if type_words and words & type_words:
            score += 20 * len(words & type_words) / len(type_words)
        if score > best_score:
            best, best_score = text, score
    return best or fallback
