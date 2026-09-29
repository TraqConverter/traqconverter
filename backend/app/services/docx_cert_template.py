"""A translator's own Word certification as the certification page: fields become content controls, layout is kept."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from lxml import etree

from app.services import cert_fields, docx_blocks as blocks, docx_images as images
from app.services.docx_blocks import A_NS, PIC_NS, PKG_REL_NS, R_NS, DocxEditError, _Doc, w

MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
HYPERLINK_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
STYLE_PREFIX = "TQTpl"
_DOCUMENT = "word/document.xml"
_STYLES = "word/styles.xml"
_REL = f"{{{PKG_REL_NS}}}Relationship"
_EMBED = f"{{{R_NS}}}embed"
_LINK = f"{{{R_NS}}}link"
_RID = f"{{{R_NS}}}id"
TOKEN_RE = re.compile(r"\{\{\s*([^{}\s][^{}]*?)\s*\}\}")
_MERGE_RE = re.compile(r'^\s*MERGEFIELD\s+(?:"([^"]*)"|(\S+))(.*)$', re.I | re.S)
_SWITCH_RE = re.compile(r'\\([bf])\s+(?:"([^"]*)"|(\S+))', re.I)
_FIELD_KIND_RE = re.compile(r"^\s*([A-Za-z]+)")
_IMAGE_FORMATS = ("PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF")
_IMAGE_MAX_BYTES = 20 * 1024 * 1024
_TEXT_RUN_CHILDREN = {w("rPr"), w("t"), w("tab"), w("br"), w("cr")}

_REMOVE = {
    w(t)
    for t in (
        "bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd", "proofErr", "permStart", "permEnd",
        "lastRenderedPageBreak", "del", "moveFrom", "moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart",
        "moveToRangeEnd", "customXmlInsRangeStart", "customXmlInsRangeEnd", "customXmlDelRangeStart",
        "customXmlDelRangeEnd", "sectPr", "rPrChange", "pPrChange", "tblPrChange", "tblPrExChange", "trPrChange",
        "tcPrChange", "sectPrChange", "tblGridChange", "numberingChange", "cellIns", "cellDel", "cellMerge",
        "dataBinding", "placeholder",
    )
}
_UNWRAP = {w(t) for t in ("ins", "moveTo", "smartTag", "customXml", "dir", "bdo")}
_DROPPED = {
    w("pict"): "Shapes, WordArt and watermarks",
    f"{{{MC_NS}}}AlternateContent": "Text boxes and shapes",
    w("object"): "Embedded objects",
    w("control"): "Form controls",
    w("altChunk"): "Embedded documents",
    w("subDoc"): "Embedded documents",
}

# Schema order of pPr / rPr children, needed when merging document defaults into a style.
_PPR_ORDER = [w(t) for t in (
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr", "suppressLineNumbers",
    "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct", "topLinePunct",
    "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing",
    "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl",
    "divId", "cnfStyle", "rPr", "sectPr", "pPrChange",
)]
_RPR_ORDER = [w(t) for t in (
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline", "shadow",
    "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing", "w", "kern", "position",
    "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
    "eastAsianLayout", "specVanish", "oMath",
)]
_THEME_ATTRS = {"asciiTheme": "ascii", "hAnsiTheme": "hAnsi", "eastAsiaTheme": "eastAsia", "cstheme": "cs"}


@dataclass
class TemplateReport:
    fields: list[dict] = field(default_factory=list)
    unknown: list[dict] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def found(self, name: str, kind: str, canonical: str) -> None:
        if not any(f["name"] == name and f["kind"] == kind for f in self.fields):
            self.fields.append({"name": name, "kind": kind, "field": canonical})

    def missing(self, name: str, kind: str) -> None:
        if not any(f["name"] == name and f["kind"] == kind for f in self.unknown):
            self.unknown.append({"name": name, "kind": kind})

    def drop(self, what: str, count: int = 1) -> None:
        self.dropped[what] = self.dropped.get(what, 0) + count

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)


def _unwrap(el) -> None:
    parent = el.getparent()
    index = parent.index(el)
    for child in list(el):
        parent.insert(index, child)
        index += 1
    parent.remove(el)


def _remove_run_of(el) -> None:
    run = el
    while run is not None and run.tag != w("r"):
        run = run.getparent()
    target = run if run is not None else el
    if target.getparent() is not None:
        target.getparent().remove(target)


def _plain_run(el) -> bool:
    return el.tag == w("r") and all(
        c.tag in _TEXT_RUN_CHILDREN and not (c.tag == w("br") and c.get(w("type")) not in (None, "textWrapping"))
        for c in el
    )


def _run_text(r) -> str:
    out = []
    for c in r:
        if c.tag == w("t"):
            out.append(c.text or "")
        elif c.tag == w("tab"):
            out.append("\t")
        elif c.tag in (w("br"), w("cr")):
            out.append("\n")
    return "".join(out)


def _rpr_of(r):
    rpr = r.find(w("rPr")) if r is not None else None
    return copy.deepcopy(rpr) if rpr is not None else None


def _sort_children(el, order: list[str]) -> None:
    rank = {tag: i for i, tag in enumerate(order)}
    children = sorted(el, key=lambda c: rank.get(c.tag, len(order)))
    for c in children:
        el.append(c)


def _has_content(unit) -> bool:
    return bool(blocks.paragraph_text(unit).strip()) or any(
        True for _ in unit.iter(w("drawing"), w("sdt"), w("tbl"))
    )


class _Importer:
    def __init__(self, doc: _Doc, src: _Doc, content, report: TemplateReport, merge_only: bool = False):
        from app.services import docx_certification

        self.doc, self.src, self.content, self.report = doc, src, content, report
        self.cert = docx_certification
        # merge_only: plain-text values, other fields untouched (legacy export path).
        self.merge_only = merge_only
        self.fonts = self._theme_fonts()
        self.flattened: set[str] = set()

    # --- source parts -------------------------------------------------------

    def _theme_fonts(self) -> dict[str, dict[str, str]]:
        name = next((n for n in self.src.files if re.match(r"^word/theme/theme\d*\.xml$", n)), None)
        fonts: dict[str, dict[str, str]] = {"major": {}, "minor": {}}
        if not name:
            return fonts
        try:
            theme = etree.fromstring(self.src.files[name], blocks._PARSER)
        except etree.XMLSyntaxError:
            return fonts
        for kind in ("major", "minor"):
            scheme = next(theme.iter(f"{{{A_NS}}}{kind}Font"), None)
            if scheme is None:
                continue
            for script in ("latin", "ea", "cs"):
                el = scheme.find(f"{{{A_NS}}}{script}")
                if el is not None and el.get("typeface"):
                    fonts[kind][script] = el.get("typeface")
        return fonts

    def _part_for(self, reference: str) -> str | None:
        body = self.src.trees[_DOCUMENT].find(w("body"))
        sect = body.find(w("sectPr")) if body is not None else None
        if sect is None:
            return None
        refs = {r.get(w("type")) or "default": r.get(_RID) for r in sect.findall(w(reference))}
        first = sect.find(w("titlePg")) is not None and refs.get("first")
        rid = first or refs.get("default")
        rel = next((r for r in self.src.rels(_DOCUMENT) if r.get("Id") == rid), None)
        if rel is None:
            return None
        part = images._media_path(_DOCUMENT, rel.get("Target") or "")
        return part if part in self.src.trees else None

    def _source_units(self, part: str) -> list:
        root = self.src.trees[part]
        container = root.find(w("body")) if part == _DOCUMENT else root
        out = []
        for child in container if container is not None else []:
            if child.tag in (w("p"), w("tbl")):
                out.append(child)
            elif child.tag == w("sdt") and child.find(w("sdtContent")) is not None:
                out.extend(c for c in child.find(w("sdtContent")) if c.tag in (w("p"), w("tbl")))
        return out

    # --- cleaning -----------------------------------------------------------

    def _clean(self, unit) -> None:
        blocks._strip_rsids(unit)
        for el in list(unit.iter(*_DROPPED)):
            if el.getparent() is not None:
                self.report.drop(_DROPPED[el.tag])
                el.getparent().remove(el)
        for el in list(unit.iter(w("commentReference"), w("annotationRef"))):
            _remove_run_of(el)
        for el in list(unit.iter(w("footnoteReference"), w("endnoteReference"))):
            self.report.drop("Footnotes and endnotes")
            _remove_run_of(el)
        for el in list(unit.iter(*_REMOVE)):
            if el.getparent() is not None:
                el.getparent().remove(el)
        for el in list(unit.iter(*_UNWRAP)):
            if el.getparent() is not None:
                _unwrap(el)
        for num in list(unit.iter(w("numPr"))):
            num_id = num.find(w("numId"))
            if num_id is None or num_id.get(w("val")) != "0":
                self.report.drop("List numbering and bullets")
            num.getparent().remove(num)

    # --- fields and tokens --------------------------------------------------

    def _value_sdt(self, name: str, rpr):
        if self.merge_only:
            return self.cert._run(self.content.values.get(name, ""), rpr)
        day = self.content.day.isoformat() if name == "date" else None
        return self.cert._sdt(name, self.content.values.get(name, ""), rpr, self.content.lang, day)

    def _field_elements(self, instr: str, result_runs: list, fallback_rpr) -> list | None:
        rpr = next((_rpr_of(r) for r in result_runs if r.tag == w("r") and r.find(w("rPr")) is not None), None)
        rpr = rpr if rpr is not None else fallback_rpr
        m = _MERGE_RE.match(instr or "")
        if m:
            name = (m.group(1) if m.group(1) is not None else m.group(2) or "").strip()
            canonical = cert_fields.resolve(name)
            if not canonical:
                self.report.missing(name, "merge")
                return [self.cert._run(f"«{name}»", rpr)]
            self.report.found(name, "merge", canonical)
            switches = {s.group(1).lower(): s.group(2) if s.group(2) is not None else s.group(3) for s in _SWITCH_RE.finditer(m.group(3))}
            has_value = bool(self.content.values.get(canonical))
            out = []
            if has_value and switches.get("b"):
                out.append(self.cert._run(switches["b"], rpr))
            out.append(self._value_sdt(canonical, rpr))
            if has_value and switches.get("f"):
                out.append(self.cert._run(switches["f"], rpr))
            return out
        if self.merge_only:
            return None
        kind = (_FIELD_KIND_RE.match(instr or "") or [None, ""])[1].upper()
        if kind == "DATE":
            self.report.found("DATE", "field", "date")
            return [self._value_sdt("date", rpr)]
        if kind:
            self.flattened.add(kind)
        kept = []
        for r in result_runs:
            if any(True for _ in r.iter(w("fldChar"), w("instrText"))):
                continue
            kept.append(copy.deepcopy(r))
        return kept

    def _complex_fields(self, container) -> None:
        children = list(container)
        i = 0
        while i < len(children):
            begin = children[i]
            chars = list(begin.iter(w("fldChar"))) if begin.tag == w("r") else []
            if not chars or chars[0].get(w("fldCharType")) != "begin":
                i += 1
                continue
            depth, sep, end = 0, None, None
            for j in range(i, len(children)):
                for fc in children[j].iter(w("fldChar")):
                    kind = fc.get(w("fldCharType"))
                    if kind == "begin":
                        depth += 1
                    elif kind == "separate" and depth == 1 and sep is None:
                        sep = j
                    elif kind == "end":
                        depth -= 1
                        if depth == 0:
                            end = j
                            break
                if end is not None:
                    break
            if end is None:
                return
            instr = "".join(t.text or "" for r in children[i:(sep if sep is not None else end) + 1] for t in r.iter(w("instrText")))
            results = children[sep + 1:end] if sep is not None else []
            replacement = self._field_elements(instr, results, _rpr_of(begin))
            if replacement is None:
                i = end + 1
                continue
            for el in replacement:
                begin.addprevious(el)
            for el in children[i:end + 1]:
                container.remove(el)
            i = end + 1

    def _simple_fields(self, unit) -> None:
        for fld in list(unit.iter(w("fldSimple"))):
            if fld.getparent() is None:
                continue
            prev = fld.getprevious()
            fallback = _rpr_of(prev) if prev is not None and prev.tag == w("r") else None
            results = [r for r in fld if r.tag == w("r")]
            replacement = self._field_elements(fld.get(w("instr")) or "", results, fallback)
            if replacement is None:
                continue
            for el in replacement:
                fld.addprevious(el)
            fld.getparent().remove(fld)

    def _tokens_in(self, container, seq: list) -> None:
        texts = [_run_text(r) for r in seq]
        full = "".join(texts)
        if not TOKEN_RE.search(full):
            return
        starts, pos = [], 0
        for t in texts:
            starts.append(pos)
            pos += len(t)

        def run_at(offset: int) -> int:
            idx = 0
            for k, s in enumerate(starts):
                if s <= offset and texts[k]:
                    idx = k
            return idx

        out: list = []

        def literal(a: int, b: int) -> None:
            while a < b:
                k = run_at(a)
                stop = min(b, starts[k] + len(texts[k]))
                out.append(self.cert._run(full[a:stop], _rpr_of(seq[k])))
                a = stop

        pos = 0
        for m in TOKEN_RE.finditer(full):
            token = m.group(1)
            canonical = cert_fields.resolve(token)
            if canonical and canonical not in self.content.values and token in self.content.extra_tokens:
                canonical = None
            if canonical:
                literal(pos, m.start())
                self.report.found(token, "token", canonical)
                out.append(self._value_sdt(canonical, _rpr_of(seq[run_at(m.start())])))
            elif token in self.content.extra_tokens:
                literal(pos, m.start())
                self.report.found(token, "token", token)
                out.append(self.cert._run(self.content.extra_tokens[token], _rpr_of(seq[run_at(m.start())])))
            else:
                self.report.missing(token, "token")
                literal(pos, m.end())
            pos = m.end()
        literal(pos, len(full))
        for el in out:
            seq[0].addprevious(el)
        for r in seq:
            container.remove(r)

    def _tokens(self, unit) -> None:
        containers = []
        for r in unit.iter(w("r")):
            parent = r.getparent()
            if parent is not None and parent not in containers:
                containers.append(parent)
        for container in containers:
            children = list(container)
            i = 0
            while i < len(children):
                if not _plain_run(children[i]):
                    i += 1
                    continue
                j = i
                while j < len(children) and _plain_run(children[j]):
                    j += 1
                self._tokens_in(container, children[i:j])
                i = j

    def _fields(self, unit) -> None:
        containers = []
        for fc in unit.iter(w("fldChar")):
            run = fc.getparent()
            parent = run.getparent() if run is not None else None
            if parent is not None and parent not in containers:
                containers.append(parent)
        for container in containers:
            self._complex_fields(container)
        self._simple_fields(unit)
        self._tokens(unit)

    # --- relationships ------------------------------------------------------

    def _add_rel(self, rel_type: str, target: str, external: bool) -> str:
        rels = self.doc.rels(_DOCUMENT)
        taken = {r.get("Id") for r in rels}
        n = len(taken) + 1
        while f"rId{n}" in taken:
            n += 1
        rel = etree.SubElement(rels, _REL)
        rel.set("Id", f"rId{n}")
        rel.set("Type", rel_type)
        rel.set("Target", target)
        if external:
            rel.set("TargetMode", "External")
        return f"rId{n}"

    def _links(self, unit, part: str) -> set:
        rels = {r.get("Id"): r for r in self.src.rels(part)}
        kept = set()
        for link in list(unit.iter(w("hyperlink"))):
            rid = link.get(_RID)
            if rid is None:
                kept.add(link)
                continue
            rel = rels.get(rid)
            if rel is None or rel.get("Type") != HYPERLINK_REL or rel.get("TargetMode") != "External":
                _unwrap(link)
                continue
            link.set(_RID, self._add_rel(HYPERLINK_REL, rel.get("Target") or "", True))
            kept.add(link)
        return kept

    def _pictures(self, unit, part: str) -> None:
        rels = {r.get("Id"): r for r in self.src.rels(part)}
        for drawing in list(unit.iter(w("drawing"))):
            if drawing.getparent() is None:
                continue
            uris = {g.get("uri") for g in drawing.iter(f"{{{A_NS}}}graphicData")}
            if uris != {PIC_NS}:
                self.report.drop("Charts, SmartArt and drawn shapes")
                _remove_run_of(drawing)
                continue
            ok = True
            for blip in drawing.iter(f"{{{A_NS}}}blip"):
                if blip.get(_LINK) and not blip.get(_EMBED):
                    self.report.drop("Linked (not embedded) pictures")
                    ok = False
                    break
                rel = rels.get(blip.get(_EMBED) or "")
                raw = self.src.files.get(images._media_path(part, rel.get("Target") or "")) if rel is not None else None
                try:
                    prepared = images.prepare_image(raw or b"", max_bytes=_IMAGE_MAX_BYTES, formats=_IMAGE_FORMATS)
                except Exception:
                    self.report.drop("Pictures in a format the editor can't show (EMF, WMF, SVG)")
                    ok = False
                    break
                blip.set(_EMBED, images.add_image_part(self.doc, prepared))
                if _LINK in blip.attrib:
                    del blip.attrib[_LINK]
                for ext in list(blip.iter(f"{{{A_NS}}}ext")):
                    if any(etree.QName(a).namespace == R_NS for el in ext.iter() for a in el.attrib):
                        ext.getparent().remove(ext)
            if not ok:
                _remove_run_of(drawing)

    def _sweep(self, unit, kept_links: set) -> None:
        for el in list(unit.iter()):
            if not isinstance(el.tag, str) or el.getparent() is None:
                continue
            if el.tag == f"{{{A_NS}}}blip" or el in kept_links:
                continue
            if any(etree.QName(a).namespace == R_NS for a in el.attrib):
                self.report.drop("Other linked content")
                el.getparent().remove(el)

    def _fonts_in(self, root) -> None:
        for rf in root.iter(w("rFonts")):
            for attr, plain in _THEME_ATTRS.items():
                theme = rf.get(w(attr))
                if not theme:
                    continue
                script = "cs" if theme.endswith("Bidi") else "ea" if theme.endswith("EastAsia") else "latin"
                face = self.fonts["major" if theme.startswith("major") else "minor"].get(script)
                if face:
                    rf.set(w(plain), face)
                    del rf.attrib[w(attr)]

    def convert(self, unit, part: str):
        unit = copy.deepcopy(unit)
        self._clean(unit)
        self._fields(unit)
        kept = self._links(unit, part)
        self._pictures(unit, part)
        self._sweep(unit, kept)
        self._fonts_in(unit)
        return unit

    # --- styles -------------------------------------------------------------

    def _merged_defaults(self, src_styles, style) -> None:
        defaults = src_styles.find(w("docDefaults"))
        for kind, order, fallback in (
            ("pPr", _PPR_ORDER, [("spacing", {"after": "0", "line": "240", "lineRule": "auto"})]),
            ("rPr", _RPR_ORDER, [("sz", {"val": "20"}), ("szCs", {"val": "20"}), ("rFonts", {"ascii": "Times New Roman", "hAnsi": "Times New Roman", "cs": "Times New Roman"})]),
        ):
            base = defaults.find(f"{w(kind + 'Default')}/{w(kind)}") if defaults is not None else None
            own = style.find(w(kind))
            if own is None:
                own = etree.SubElement(style, w(kind))
            have = {c.tag for c in own}
            for child in base if base is not None else []:
                if child.tag not in have and child.tag != w("numPr"):
                    own.append(copy.deepcopy(child))
                    have.add(child.tag)
            for tag, attrs in fallback:
                if w(tag) not in have:
                    el = etree.SubElement(own, w(tag))
                    for k, v in attrs.items():
                        el.set(w(k), v)
            _sort_children(own, order)
        # tblPr / pPr / rPr must follow the header elements of a style.
        for tag in ("pPr", "rPr", "tblPr", "trPr", "tcPr"):
            for el in style.findall(w(tag)):
                style.append(el)
        for el in style.findall(w("tblStylePr")):
            style.append(el)

    def import_styles(self, units: list) -> None:
        raw, dst_raw = self.src.files.get(_STYLES), self.doc.files.get(_STYLES)
        refs = [el for u in units for el in u.iter(w("pStyle"), w("rStyle"), w("tblStyle"))]
        if not raw or not dst_raw:
            for el in refs:
                el.getparent().remove(el)
            return
        src_styles = etree.fromstring(raw, blocks._PARSER)
        dst_styles = etree.fromstring(dst_raw, blocks._PARSER)
        by_id = {s.get(w("styleId")): s for s in src_styles.findall(w("style"))}
        default_para = next(
            (s.get(w("styleId")) for s in by_id.values() if s.get(w("type")) == "paragraph" and s.get(w("default")) in ("1", "true", "on")),
            None,
        )
        if default_para:
            for u in units:
                for p in u.iter(w("p")):
                    ppr = p.find(w("pPr"))
                    if ppr is None:
                        ppr = etree.Element(w("pPr"))
                        p.insert(0, ppr)
                    if ppr.find(w("pStyle")) is None:
                        ps = etree.Element(w("pStyle"))
                        ps.set(w("val"), default_para)
                        ppr.insert(0, ps)
                        refs.append(ps)
        needed: list[str] = []
        queue = [el.get(w("val")) for el in refs]
        while queue:
            sid = queue.pop()
            if sid in by_id and sid not in needed:
                needed.append(sid)
                based = by_id[sid].find(w("basedOn"))
                if based is not None:
                    queue.append(based.get(w("val")))
        mapping = {sid: STYLE_PREFIX + re.sub(r"[^A-Za-z0-9]", "", sid) + str(i) for i, sid in enumerate(needed)}
        for existing in dst_styles.findall(w("style")):
            if (existing.get(w("styleId")) or "").startswith(STYLE_PREFIX):
                dst_styles.remove(existing)
        for sid in needed:
            style = copy.deepcopy(by_id[sid])
            style.set(w("styleId"), mapping[sid])
            style.set(w("customStyle"), "1")
            if w("default") in style.attrib:
                del style.attrib[w("default")]
            for tag in ("aliases", "next", "link", "rsid", "autoRedefine", "personal", "personalCompose", "personalReply"):
                for el in style.findall(w(tag)):
                    style.remove(el)
            name = style.find(w("name"))
            if name is None:
                name = etree.Element(w("name"))
                style.insert(0, name)
            name.set(w("val"), f"Certification template {name.get(w('val')) or sid}")
            based = style.find(w("basedOn"))
            if based is not None and based.get(w("val")) in mapping:
                based.set(w("val"), mapping[based.get(w("val"))])
            elif based is not None:
                style.remove(based)
                based = None
            for num in list(style.iter(w("numPr"))):
                num.getparent().remove(num)
                self.report.drop("List numbering and bullets")
            if based is None and style.get(w("type")) == "paragraph":
                self._merged_defaults(src_styles, style)
            self._fonts_in(style)
            dst_styles.append(style)
        for el in refs:
            new = mapping.get(el.get(w("val")))
            if new:
                el.set(w("val"), new)
            elif el.getparent() is not None:
                el.getparent().remove(el)
        self.doc.files[_STYLES] = etree.tostring(dst_styles, xml_declaration=True, encoding="UTF-8", standalone=True)

    # --- whole template -----------------------------------------------------

    def run(self) -> tuple[list, object | None]:
        body = [self.convert(u, _DOCUMENT) for u in self._source_units(_DOCUMENT)]
        while body and body[-1].tag == w("p") and not _has_content(body[-1]):
            body.pop()
        if not body:
            raise DocxEditError("The certification template is empty")
        header_part = self._part_for("headerReference")
        footer_part = self._part_for("footerReference")
        header = [self.convert(u, header_part) for u in self._source_units(header_part)] if header_part else []
        footer = [self.convert(u, footer_part) for u in self._source_units(footer_part)] if footer_part else []
        header = [u for u in header if _has_content(u)]
        footer = [u for u in footer if _has_content(u)]
        if header or footer:
            self.report.note("The template's header and footer are placed at the top and bottom of the certification page.")
        if self.flattened:
            self.report.note(f"Other Word fields are kept as plain text: {', '.join(sorted(self.flattened))}.")
        signature = next(
            (u for u in reversed(body) if u.tag == w("p") and "_____" in blocks.paragraph_text(u)),
            next((u for u in reversed(body) if u.tag == w("p") and blocks.paragraph_text(u).strip()), None),
        )
        # Room between the signature (and the stamp over it) and the footer lines.
        units = header + body + ([self.cert._paragraph(after=720)] if footer else []) + footer
        self.import_styles(units)
        return units, signature


def import_template(doc: _Doc, template: bytes, content, report: TemplateReport | None = None) -> tuple[list, object | None]:
    """Body (plus header and footer) of an uploaded Word certification, ready to sit in the translation."""
    try:
        src = _Doc.load(template)
    except Exception as e:
        raise DocxEditError("The certification template couldn't be read") from e
    return _Importer(doc, src, content, report or TemplateReport()).run()


def flatten_merge_fields(data: bytes, values: dict[str, str]) -> bytes:
    """Merge fields as plain text (legacy export path); unknown ones become «Name», other fields stay."""
    from types import SimpleNamespace

    doc = _Doc.load(data)
    content = SimpleNamespace(values=values, lang="en", day=None, extra_tokens={})
    importer = _Importer(doc, doc, content, TemplateReport(), merge_only=True)
    changed = False
    for name in list(doc.trees):
        tree = doc.trees[name]
        if not blocks.PART_RE.match(name) or not any(True for _ in tree.iter(w("fldChar"), w("fldSimple"))):
            continue
        containers = []
        for fc in tree.iter(w("fldChar")):
            run = fc.getparent()
            parent = run.getparent() if run is not None else None
            if parent is not None and parent not in containers:
                containers.append(parent)
        for container in containers:
            importer._complex_fields(container)
        importer._simple_fields(tree)
        changed = True
    return doc.dump() if changed else data
