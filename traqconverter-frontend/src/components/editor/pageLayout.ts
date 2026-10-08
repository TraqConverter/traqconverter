// Lay the editor's pages out as LibreOffice (the PDF export) does, and show where the PDF starts a new page.

const W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

// The Office fonts AI-built documents use, and the same-width builds LibreOffice renders them with.
const STAND_INS = [
  { family: "Calibri", file: "carlito" },
  { family: "Cambria", file: "caladea" },
]
const FACES = [
  { style: "normal", weight: 400, name: "", file: "regular" },
  { style: "italic", weight: 400, name: " Italic", file: "italic" },
  { style: "normal", weight: 700, name: " Bold", file: "bold" },
  { style: "italic", weight: 700, name: " Bold Italic", file: "bolditalic" },
]

// A computer without Calibri/Cambria gets Carlito/Caladea, so lines break where they do in the PDF.
export function officeFontFaces(base: string): string {
  return STAND_INS.flatMap((font) =>
    FACES.map(
      (face) =>
        `@font-face{font-family:"${font.family}";font-style:${face.style};font-weight:${face.weight};font-display:block;` +
        `src:local("${font.family}${face.name}"),url(${base}/${font.file}-${face.file}.woff2) format("woff2")}`,
    ),
  ).join("\n")
}

function wChild(el: Element, name: string): Element | null {
  return Array.from(el.children).find((c) => c.namespaceURI === W_NS && c.localName === name) ?? null
}

// docx-preview gives unstyled paragraphs' runs the defaults, not Normal's font and size; Word uses Normal's.
export async function withNormalRunDefaults(docx: ArrayBuffer): Promise<ArrayBuffer> {
  const { default: JSZip } = await import("jszip")
  const zip = await JSZip.loadAsync(docx)
  const xml = await zip.file("word/styles.xml")?.async("string")
  if (!xml) return docx
  const doc = new DOMParser().parseFromString(xml, "application/xml")
  const root = doc.documentElement
  const normal = Array.from(root.children).find(
    (s) => s.localName === "style" && s.getAttributeNS(W_NS, "type") === "paragraph" && ["1", "true", "on"].includes(s.getAttributeNS(W_NS, "default") ?? ""),
  )
  const normalRpr = normal ? wChild(normal, "rPr") : null
  if (!normalRpr || normalRpr.children.length === 0) return docx
  const make = (parent: Element, name: string, first = false) => {
    const existing = wChild(parent, name)
    if (existing) return existing
    const el = doc.createElementNS(W_NS, `w:${name}`)
    if (first) parent.insertBefore(el, parent.firstChild)
    else parent.appendChild(el)
    return el
  }
  const defaults = make(root, "docDefaults", true)
  const rpr = make(make(defaults, "rPrDefault", true), "rPr")
  for (const prop of Array.from(normalRpr.children)) {
    wChild(rpr, prop.localName)?.remove()
    rpr.appendChild(prop.cloneNode(true))
  }
  zip.file("word/styles.xml", new XMLSerializer().serializeToString(doc))
  return zip.generateAsync({ type: "arraybuffer" })
}

// Line height / font size of single spacing in Word and LibreOffice (ascent + descent + line gap).
const KNOWN_RATIOS: Record<string, number> = {
  "times new roman": 1.149,
  "liberation serif": 1.149,
  tinos: 1.149,
  arial: 1.149,
  "liberation sans": 1.149,
  arimo: 1.149,
  calibri: 1.2207,
  carlito: 1.2207,
  cambria: 1.1724,
  caladea: 1.1724,
  "courier new": 1.1328,
  "liberation mono": 1.1328,
  cousine: 1.1328,
}

const lineRatios = new Map<string, number>()

// Single line spacing in Word and LibreOffice is the font's own line height; CSS "line-height: 1" is just the font size.
function naturalLineRatio(idoc: Document, family: string): number {
  const name = family.split(",")[0].trim().replace(/^["']|["']$/g, "").toLowerCase()
  if (KNOWN_RATIOS[name]) return KNOWN_RATIOS[name]
  const known = lineRatios.get(family)
  if (known) return known
  const probe = (lineHeight: string) => {
    const span = idoc.createElement("span")
    span.textContent = "Hg"
    span.style.cssText = `position:absolute;visibility:hidden;display:inline-block;font-size:1000px;line-height:${lineHeight};font-family:${family}`
    idoc.body.appendChild(span)
    const h = span.getBoundingClientRect().height
    span.remove()
    return h
  }
  const unit = probe("1")
  const ratio = unit > 0 ? probe("normal") / unit : 1.15
  const value = Number.isFinite(ratio) && ratio > 0.8 && ratio < 2 ? ratio : 1.15
  lineRatios.set(family, value)
  return value
}

// The line-height docx-preview gave this paragraph (inline from its own spacing, else the last matching style rule).
function specifiedLineHeight(p: HTMLElement, rules: CSSStyleRule[]): string {
  if (p.style.lineHeight) return p.style.lineHeight
  let found = ""
  for (const rule of rules) {
    if (!rule.style.lineHeight) continue
    try {
      if (p.matches(rule.selectorText)) found = rule.style.lineHeight
    } catch {}
  }
  return found
}

function styleRules(idoc: Document): CSSStyleRule[] {
  const out: CSSStyleRule[] = []
  for (const sheet of Array.from(idoc.styleSheets)) {
    let rules: CSSRuleList
    try {
      rules = sheet.cssRules
    } catch {
      continue
    }
    // The iframe has its own CSSStyleRule class, so instanceof would always fail here.
    for (const rule of Array.from(rules)) if ((rule as CSSStyleRule).selectorText !== undefined) out.push(rule as CSSStyleRule)
  }
  return out
}

// The run a paragraph's lines are measured by: its first text, else an empty run styled as its runs would be.
function runStyle(p: HTMLElement): { fontSize: string; fontFamily: string } {
  const walker = p.ownerDocument.createTreeWalker(p, NodeFilter.SHOW_TEXT)
  for (let t = walker.nextNode(); t; t = walker.nextNode()) {
    const el = t.parentElement
    if (t.textContent?.trim() && el && el.closest("p") === p) {
      const { fontSize, fontFamily } = getComputedStyle(el)
      return { fontSize, fontFamily }
    }
  }
  const probe = p.ownerDocument.createElement("span")
  p.appendChild(probe)
  const { fontSize, fontFamily } = getComputedStyle(probe)
  probe.remove()
  return { fontSize, fontFamily }
}

const DONE = "tqLh"

// Line heights as Word and LibreOffice compute them, from the run's font rather than the page's.
export function matchWordLineHeights(root: ParentNode) {
  const paragraphs = Array.from(root.querySelectorAll<HTMLElement>("section.docx p")).filter((p) => !p.dataset[DONE])
  if (paragraphs.length === 0) return
  const idoc = paragraphs[0].ownerDocument
  const rules = styleRules(idoc)
  for (const p of paragraphs) {
    const run = runStyle(p)
    const spec = specifiedLineHeight(p, rules)
    p.style.fontSize = run.fontSize
    p.style.fontFamily = run.fontFamily
    const ratio = naturalLineRatio(idoc, run.fontFamily)
    const factor = /^\d+(\.\d+)?$/.test(spec) ? parseFloat(spec) : spec === "" || spec === "normal" ? 1 : null
    const atLeast = spec.match(/^calc\(100% \+ ([\d.]+)pt\)$/)
    if (factor !== null) {
      const lh = (factor * ratio).toFixed(4)
      p.style.lineHeight = lh
      p.style.minHeight = `${lh}em`
    } else if (atLeast) {
      p.style.lineHeight = `max(${ratio.toFixed(4)}em, ${atLeast[1]}pt)`
    }
    p.dataset[DONE] = "1"
  }
}

export const BREAK_LAYER_CLASS = "tq-pdf-breaks"

// `need` includes the paragraph's space-after, which LibreOffice also fits on the page; table lines get no index.
type Line = { top: number; bottom: number; need: number; index?: number; count?: number }

function mergeLines(boxes: Line[]): Line[] {
  boxes.sort((a, b) => a.top - b.top)
  // Runs of one line come back as separate rects; keep one box per line.
  const lines: Line[] = []
  for (const b of boxes) {
    const last = lines[lines.length - 1]
    if (last && b.top < last.bottom - 1) {
      last.bottom = Math.max(last.bottom, b.bottom)
      last.need = Math.max(last.need, b.need)
      if (last.index !== b.index || last.count !== b.count) last.index = last.count = undefined
    } else lines.push({ ...b })
  }
  return lines
}

// Line boxes of one paragraph, in screen pixels.
function paragraphLines(p: HTMLElement): Line[] {
  const boxes: Line[] = []
  const idoc = p.ownerDocument
  const walker = idoc.createTreeWalker(p, NodeFilter.SHOW_TEXT)
  const range = idoc.createRange()
  for (let t = walker.nextNode(); t; t = walker.nextNode()) {
    if (!t.textContent?.trim()) continue
    range.selectNodeContents(t)
    for (const r of Array.from(range.getClientRects())) if (r.height > 0) boxes.push({ top: r.top, bottom: r.bottom, need: r.bottom })
  }
  p.querySelectorAll("img").forEach((img) => {
    const frame = img.parentElement
    if (frame && getComputedStyle(frame).position === "absolute") return
    const r = img.getBoundingClientRect()
    if (r.height > 0) boxes.push({ top: r.top, bottom: r.bottom, need: r.bottom })
  })
  const r = p.getBoundingClientRect()
  if (boxes.length === 0 && r.height > 0) boxes.push({ top: r.top, bottom: r.bottom, need: r.bottom })
  const lines = mergeLines(boxes)
  const last = lines[lines.length - 1]
  if (last) {
    const scale = p.offsetHeight > 0 ? r.height / p.offsetHeight : 1
    last.need = Math.max(last.need, last.bottom + (parseFloat(getComputedStyle(p).marginBottom) || 0) * scale)
  }
  if (!p.closest("td")) lines.forEach((line, i) => Object.assign(line, { index: i, count: lines.length }))
  return lines
}

// Line boxes of a page's body text, top to bottom.
function lineBoxes(article: Element): Line[] {
  const boxes: Line[] = []
  article.querySelectorAll<HTMLElement>("p").forEach((p) => boxes.push(...paragraphLines(p)))
  return mergeLines(boxes)
}

// LibreOffice keeps at least two lines of a paragraph on each page (widow and orphan control).
function pageStart(lines: Line[], i: number, floor: number): number {
  const { index, count } = lines[i]
  if (index === undefined || count === undefined || index === 0) return i
  let at = i
  if (count - index === 1) at = index >= 3 ? i - 1 : i - index
  else if (index === 1) at = i - 1
  return at > floor ? at : i
}

export type PdfBreak = { page: HTMLElement; y: number }

// docx-preview grows a page that doesn't fit; LibreOffice moves the rest to a new page. Find where.
export function findPdfBreaks(root: ParentNode): { breaks: PdfBreak[]; pdfPages: number } {
  const breaks: PdfBreak[] = []
  let pdfPage = 0
  for (const page of Array.from(root.querySelectorAll<HTMLElement>("section.docx"))) {
    pdfPage++
    const rect = page.getBoundingClientRect()
    const scale = page.offsetHeight > 0 ? rect.height / page.offsetHeight : 1
    const pageHeight = parseFloat(getComputedStyle(page).minHeight) * scale
    if (!(pageHeight > 0) || rect.height <= pageHeight + 2 * scale) continue
    const articles = Array.from(page.querySelectorAll<HTMLElement>(":scope > article"))
    if (articles.length === 0) continue
    const top = articles[0].getBoundingClientRect().top
    const bottomReserve = rect.bottom - articles[articles.length - 1].getBoundingClientRect().bottom
    const usable = pageHeight - (top - rect.top) - bottomReserve
    if (usable <= 20 * scale) continue
    let limit = top + usable
    let floor = 0
    const lines = articles.flatMap(lineBoxes)
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].need <= limit + 0.5 * scale) continue
      i = floor = pageStart(lines, i, floor)
      pdfPage++
      breaks.push({ page, y: (lines[i].top - rect.top) / scale })
      limit = lines[i].top + usable
    }
  }
  return { breaks, pdfPages: pdfPage }
}

// Dashed lines across the page where the PDF starts a new page; kept outside the editable pages.
export function drawPdfBreaks(root: ParentNode, breaks: PdfBreak[]) {
  const wrapper = root.querySelector<HTMLElement>(".docx-wrapper")
  if (!wrapper) return
  const idoc = wrapper.ownerDocument
  let layer = wrapper.querySelector<HTMLElement>(`:scope > .${BREAK_LAYER_CLASS}`)
  if (!layer) {
    layer = idoc.createElement("div")
    layer.className = BREAK_LAYER_CLASS
    layer.setAttribute("aria-hidden", "true")
    wrapper.style.position = "relative"
    wrapper.appendChild(layer)
  }
  const wrapperRect = wrapper.getBoundingClientRect()
  const scale = wrapper.offsetWidth > 0 ? wrapperRect.width / wrapper.offsetWidth : 1
  const marks = breaks.map((b) => {
    const r = b.page.getBoundingClientRect()
    const mark = idoc.createElement("div")
    mark.className = "tq-pdf-break"
    mark.style.top = `${(r.top - wrapperRect.top) / scale + b.y}px`
    mark.style.left = `${(r.left - wrapperRect.left) / scale}px`
    mark.style.width = `${r.width / scale}px`
    const label = idoc.createElement("span")
    label.textContent = "New page in the PDF"
    mark.appendChild(label)
    return mark
  })
  layer.replaceChildren(...marks)
}

export const PAGE_LAYOUT_CSS = `
/* Bookmark markers are empty runs; CSS would still give each one a line height of its own. */
section.docx span:empty { line-height: 0; }
/* LibreOffice doesn't kern these documents; kerned text runs narrower and wraps later. */
section.docx { font-kerning: none; }
.${BREAK_LAYER_CLASS} { position: absolute; inset: 0; pointer-events: none; z-index: 5; }
.tq-pdf-break { position: absolute; height: 0; border-top: 2px dashed rgba(200, 120, 20, 0.85); }
.tq-pdf-break > span { position: absolute; right: 4px; top: -8px; font: 600 10px/14px system-ui, sans-serif; padding: 0 5px; border-radius: 7px; background: rgba(255, 244, 224, 0.95); color: #8a5200; border: 1px solid rgba(200, 120, 20, 0.6); white-space: nowrap; }
`
