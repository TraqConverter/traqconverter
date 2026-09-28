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
