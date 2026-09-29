export const BLOCK_ATTR = "data-block-id"

const BLOCK_ID_RE = /^_b[0-9a-f]{8}$/i
const TAB_CLASS = "docx-tab-stop"
const EMSP = " "
const NBSP_RE = / /g

export function findBlockId(p: Element): string | null {
  for (const span of Array.from(p.querySelectorAll('span[id^="_b"]'))) {
    if (BLOCK_ID_RE.test(span.id) && span.closest("p") === p) return span.id
  }
  return null
}

// Paragraphs without a block id (e.g. the trial watermark) are made read-only.
export function tagBlocks(root: ParentNode): number {
  let count = 0
  root.querySelectorAll("p").forEach((p) => {
    const id = findBlockId(p)
    if (id) {
      p.setAttribute(BLOCK_ATTR, id)
      count++
    } else {
      ;(p as HTMLElement).contentEditable = "false"
    }
  })
  return count
}

export function blockParagraphOf(node: Node | null): HTMLElement | null {
  if (!node) return null
  const el = node.nodeType === 1 ? (node as Element) : node.parentElement
  return (el?.closest(`p[${BLOCK_ATTR}]`) as HTMLElement | null) ?? null
}

function isTabSpan(el: Element): boolean {
  if (el.tagName !== "SPAN") return false
  if (el.classList.contains(TAB_CLASS)) return true
  return !el.id && !el.className && el.textContent === EMSP
}

function plain(text: string): string {
  return text.replace(NBSP_RE, " ")
}

function walk(node: Node, out: string[]) {
  if (node.nodeType === 3) {
    out.push(plain((node as Text).data))
    return
  }
  if (node.nodeType !== 1) return
  const el = node as Element
  const tag = el.tagName
  if (tag === "BR") {
    out.push("\n")
    return
  }
  if (tag === "STYLE" || tag === "SCRIPT") return
  // docx-preview renders footnote references as a bare <sup> holding the number; that is not paragraph text.
  if (tag === "SUP" && el.children.length === 0) return
  if (isTabSpan(el)) {
    const t = el.textContent ?? ""
    const i = t.indexOf(EMSP)
    // A tab span that lost its em space means the user deleted the tab.
    out.push(i < 0 ? plain(t) : plain(t.slice(0, i)) + "\t" + plain(t.slice(i + 1)))
    return
  }
  el.childNodes.forEach((c) => walk(c, out))
}

export function paragraphText(p: Element): string {
  const out: string[] = []
  p.childNodes.forEach((c) => walk(c, out))
  let text = out.join("")
  // The final <br> of a block is never rendered as a line; browsers add it as a placeholder.
  if (text.endsWith("\n") && lastRenderedIsBr(p)) text = text.slice(0, -1)
  return text
}

function lastRenderedIsBr(p: Element): boolean {
  let node: Node | null = p.lastChild
  while (node) {
    if (node.nodeType === 3 && (node as Text).data.length) return false
    if (node.nodeType === 1) {
      const el = node as Element
      if (el.tagName === "BR") return true
      if (el.lastChild) {
        node = el.lastChild
        continue
      }
    }
    node = previousInBlock(node, p)
  }
  return false
}

function previousInBlock(node: Node, stop: Element): Node | null {
  let cur: Node | null = node
  while (cur && cur !== stop) {
    if (cur.previousSibling) return cur.previousSibling
    cur = cur.parentNode
  }
  return null
}

function intersectionText(p: Element, range: Range): string {
  const doc = p.ownerDocument
  const r = doc.createRange()
  r.selectNodeContents(p)
  if (r.compareBoundaryPoints(Range.START_TO_START, range) < 0) {
    r.setStart(range.startContainer, range.startOffset)
  }
  if (r.compareBoundaryPoints(Range.END_TO_END, range) > 0) {
    r.setEnd(range.endContainer, range.endOffset)
  }
  return r.collapsed ? "" : r.toString()
}

// A triple-click range ends at offset 0 of the next paragraph; that paragraph is not selected.
export function blocksInRange(root: ParentNode, range: Range): HTMLElement[] {
  if (range.collapsed) {
    const p = blockParagraphOf(range.startContainer)
    return p ? [p] : []
  }
  const hits: HTMLElement[] = []
  root.querySelectorAll<HTMLElement>(`p[${BLOCK_ATTR}]`).forEach((p) => {
    if (range.intersectsNode(p) && intersectionText(p, range).length > 0) hits.push(p)
  })
  return hits
}

export function selectionText(root: ParentNode, range: Range): string {
  const parts: string[] = []
  root.querySelectorAll("p").forEach((p) => {
    if (!range.intersectsNode(p)) return
    const t = intersectionText(p, range)
    if (t) parts.push(t)
  })
  const text = parts.length > 1 ? parts.join("\n") : range.toString()
  return plain(text).replace(new RegExp(EMSP, "g"), "\t").trim()
}

export function isAtParagraphStart(p: Element, node: Node, offset: number): boolean {
  const r = p.ownerDocument.createRange()
  r.setStart(p, 0)
  r.setEnd(node, offset)
  return r.toString().length === 0
}

export function isAtParagraphEnd(p: Element, node: Node, offset: number): boolean {
  const r = p.ownerDocument.createRange()
  r.setStart(node, offset)
  r.setEnd(p, p.childNodes.length)
  return r.toString().length === 0
}

export const IMAGE_ATTR = "data-image-id"
export const CERT_START_ID = "_cert_start"
const IMAGE_MARKER_RE = /^_(img_[0-9a-f]{8})$/
const PX_PER_CM = 96 / 2.54
export const EMU_PER_PX = 9525

export type DocImage = {
  id: string
  img: HTMLImageElement
  frame: HTMLElement
  floating: boolean
}

function cssPx(value: string): number {
  const m = value.match(/^(-?[\d.]+)(pt|px)?$/)
  if (!m) return 0
  const n = parseFloat(m[1])
  return m[2] === "pt" ? (n * 96) / 72 : n
}

// Every body picture is preceded by a hidden bookmark `_img_<hex>` the backend keeps in sync.
export function findImages(root: ParentNode): DocImage[] {
  const out: DocImage[] = []
  root.querySelectorAll<HTMLElement>('span[id^="_img_"]').forEach((marker) => {
    const m = marker.id.match(IMAGE_MARKER_RE)
    if (!m) return
    let el = marker.nextElementSibling
    for (let i = 0; el && i < 3; i++, el = el.nextElementSibling) {
      const img = el.tagName === "IMG" ? (el as HTMLImageElement) : el.querySelector("img")
      if (!img) continue
      const frame = (img.parentElement as HTMLElement) ?? img
      img.setAttribute(IMAGE_ATTR, m[1])
      frame.contentEditable = "false"
      img.draggable = false
      out.push({ id: m[1], img, frame, floating: frame.style.width === "0px" && frame.style.display === "block" })
      return
    }
  })
  return out
}

// Rendered width over the page's own width.
export function pageScale(section: HTMLElement, pageWidth: number): number {
  const s = section.getBoundingClientRect().width / pageWidth
  return Number.isFinite(s) && s > 0 ? s : 1
}

// Left edge of the text column a paragraph sits in (a table cell or the page margin), in viewport px.
export function columnLeft(p: HTMLElement, scale: number): number {
  const box = (p.closest("td") as HTMLElement | null) ?? (p.closest("section.docx") as HTMLElement | null) ?? p
  const style = box.ownerDocument.defaultView?.getComputedStyle(box)
  const rect = box.getBoundingClientRect()
  return rect.left + (parseFloat(style?.paddingLeft ?? "0") + parseFloat(style?.borderLeftWidth ?? "0")) * scale
}

// docx-preview offsets a floating picture from its paragraph; Word offsets it from the column. Shift it to match Word.
export function alignFloatingToColumn(image: DocImage, scale: number) {
  const { frame } = image
  if (!image.floating || frame.dataset.columnFixed) return
  const p = frame.closest("p") as HTMLElement | null
  if (!p) return
  const left = cssPx(frame.style.left || "0")
  const origin = frame.getBoundingClientRect().left - left * scale
  const delta = (origin - columnLeft(p, scale)) / scale
  frame.style.left = `${left - delta}px`
  frame.dataset.columnFixed = "1"
}

export function widthCm(img: HTMLImageElement, scale: number): number {
  return img.getBoundingClientRect().width / scale / PX_PER_CM
}

// The body paragraph a picture dropped at viewport y should hang from: the last one starting above it.
export function anchorParagraphAt(root: ParentNode, y: number): HTMLElement | null {
  const candidates = Array.from(root.querySelectorAll<HTMLElement>(`p[${BLOCK_ATTR}]`)).filter(
    (p) => !p.closest("header, footer"),
  )
  let best: HTMLElement | null = null
  for (const p of candidates) {
    const top = p.getBoundingClientRect().top
    if (top <= y) best = p
    else if (!best) return p
  }
  return best
}
