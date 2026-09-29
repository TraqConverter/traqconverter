"use client"

import { useCallback, useEffect, useImperativeHandle, useRef, useState, type ReactNode, type Ref } from "react"
import { api, apiErrorDetail } from "@/lib/api"
import {
  BLOCK_ATTR,
  CERT_START_ID,
  EMU_PER_PX,
  IMAGE_ATTR,
  alignFloatingToColumn,
  anchorParagraphAt,
  blockParagraphOf,
  blocksInRange,
  columnLeft,
  findImages,
  isAtParagraphEnd,
  isAtParagraphStart,
  pageScale,
  paragraphText,
  selectionText,
  tagBlocks,
  widthCm,
  type DocImage,
} from "./docBlocks"

type ChatTurn = { role: "user" | "assistant"; content: string }
type Target = { blockIds: string[]; text: string }
type AskAnchor = Target & { top: number; left: number }
type SaveState = "idle" | "pending" | "saving" | "saved" | "error"
type Busy = null | "chat" | "undo" | "image" | "cert"
type Align = "left" | "center" | "right"
type Selected = { id: string; floating: boolean; top: number; left: number; below: boolean }
type Assets = { logo: { available: boolean; url: string | null }; stamp: { available: boolean; url: string | null } }
type CertFields = {
  translator: string
  date: string
  date_iso: string
  source_language: string
  target_language: string
  document: string
}
type CertState = { present: boolean; fields: CertFields | null }

export type DocumentEditorHandle = {
  ensureCertification: () => Promise<boolean>
}

const SAVE_DELAY_MS = 1200
const HISTORY_TURNS = 10
const HIGHLIGHT_MS = 3200
const DRAG_THRESHOLD_PX = 4
const MAX_IMAGE_BYTES = 5 * 1024 * 1024
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"]
const QUICK_PROMPTS = [
  "Match the source layout here",
  "Make this a two-column table",
  "Move this next to the signature",
]
const EMPTY_FIELDS: CertFields = {
  translator: "",
  date: "",
  date_iso: "",
  source_language: "",
  target_language: "",
  document: "",
}

const BACKWARD_DELETES = new Set([
  "deleteContentBackward",
  "deleteWordBackward",
  "deleteSoftLineBackward",
  "deleteHardLineBackward",
])
const FORWARD_DELETES = new Set([
  "deleteContentForward",
  "deleteWordForward",
  "deleteSoftLineForward",
  "deleteHardLineForward",
])

const IFRAME_HTML = `<!doctype html><html><head><meta charset="utf-8"><style>
html, body { margin: 0; padding: 0; background: transparent; color: #111; font-family: 'Times New Roman', Times, serif; overflow-x: hidden; }
body { zoom: var(--docx-zoom, 0.65); }
.docx-wrapper { padding: 0 !important; background: transparent !important; }
section.docx, .docx { margin: 0 auto 16px !important; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.10); }
section.docx:focus { outline: none; }
table, thead, tbody, tfoot, tr, td, th { border-color: transparent !important; }
p.tq-target { outline: 2px dashed rgba(10, 120, 112, 0.55); outline-offset: 2px; border-radius: 2px; }
p.tq-changed { animation: tq-flash ${HIGHLIGHT_MS}ms ease-out forwards; border-radius: 2px; }
p.tq-anchor { box-shadow: -6px 0 0 -3px rgba(10, 120, 112, 0.7); background: rgba(10, 120, 112, 0.05); }
img[${IMAGE_ATTR}] { cursor: grab; outline: 2px solid transparent; outline-offset: 2px; transition: outline-color 120ms ease, opacity 120ms ease; user-select: none; -webkit-user-drag: none; }
img[${IMAGE_ATTR}]:hover { outline-color: rgba(10, 120, 112, 0.35); }
img.tq-img-selected { outline-color: #0a7870 !important; }
img.tq-img-dragging { cursor: grabbing; opacity: 0.85; }
body.tq-dragging, body.tq-dragging * { cursor: grabbing !important; user-select: none !important; }
body.tq-dropping section.docx { box-shadow: 0 0 0 3px rgba(10, 120, 112, 0.45), 0 2px 8px rgba(0, 0, 0, 0.10); }
@keyframes tq-flash {
  0%, 45% { background: rgba(10, 120, 112, 0.14); box-shadow: 0 0 0 2px rgba(10, 120, 112, 0.45); }
  100% { background: transparent; box-shadow: 0 0 0 2px rgba(10, 120, 112, 0); }
}
</style></head><body></body></html>`

const RENDER_OPTIONS = {
  inWrapper: true,
  ignoreWidth: false,
  ignoreHeight: false,
  ignoreFonts: false,
  breakPages: true,
  ignoreLastRenderedPageBreak: true,
  experimental: true,
  trimXmlDeclaration: true,
  useBase64URL: true,
  renderHeaders: true,
  renderFooters: true,
  renderFootnotes: true,
  renderEndnotes: true,
}

const BTN = "text-[10px] font-semibold tracking-[0.08em] px-2 py-1 rounded-md transition-colors disabled:opacity-50"
const BTN_STYLE = { background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }

function statusOf(err: unknown): number | undefined {
  return (err as { response?: { status?: number } })?.response?.status
}

function bufferErrorDetail(err: unknown, fallback: string): string {
  const body = (err as { response?: { data?: unknown } })?.response?.data
  if (body instanceof ArrayBuffer) {
    const text = new TextDecoder().decode(body)
    try {
      const detail = JSON.parse(text)?.detail
      if (typeof detail === "string" && detail) return detail
    } catch {}
    return text || fallback
  }
  return apiErrorDetail(err, fallback)
}

// Read the unzoomed width from the page's own style; measured rects depend on how the browser applies CSS zoom.
function pageWidthPx(page: HTMLElement | null): number {
  const m = page?.style.width.match(/^([\d.]+)(pt|px)$/)
  if (!m) return 794
  const n = parseFloat(m[1])
  const px = m[2] === "pt" ? (n * 96) / 72 : n
  return px > 100 ? px : 794
}

function blockSelector(id: string) {
  return `p[${BLOCK_ATTR}="${CSS.escape(id)}"]`
}

function isMac() {
  return typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform)
}

export default function DocumentEditor({
  projectId,
  reloadKey,
  onChatOpenChange,
  onVersionChange,
  ref,
}: {
  projectId: string
  reloadKey?: number
  onChatOpenChange?: (open: boolean) => void
  onVersionChange?: (version: number) => void
  ref?: Ref<DocumentEditorHandle>
}) {
  const [docxBuffer, setDocxBuffer] = useState<ArrayBuffer | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [saveState, setSaveState] = useState<SaveState>("idle")
  const [saveError, setSaveError] = useState("")
  const [renderTick, setRenderTick] = useState(0)
  const [busy, setBusy] = useState<Busy>(null)

  const [chatOpen, setChatOpen] = useState(false)
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [draft, setDraft] = useState("")
  const [chatError, setChatError] = useState("")
  const [target, setTarget] = useState<Target | null>(null)
  const [ask, setAsk] = useState<AskAnchor | null>(null)

  const [selected, setSelected] = useState<Selected | null>(null)
  const [imageMenuOpen, setImageMenuOpen] = useState(false)
  const [assets, setAssets] = useState<Assets | null>(null)
  const [certOpen, setCertOpen] = useState(false)
  const [cert, setCert] = useState<CertState | null>(null)
  const [certDraft, setCertDraft] = useState<CertFields>(EMPTY_FIELDS)
  const [certError, setCertError] = useState("")
  const [confirmRemove, setConfirmRemove] = useState(false)

  const hostRef = useRef<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const frameBoxRef = useRef<HTMLDivElement | null>(null)
  const iframeRef = useRef<HTMLIFrameElement | null>(null)
  const docRef = useRef<Document | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const messagesRef = useRef<HTMLDivElement | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const uploadModeRef = useRef<"image" | "stamp">("image")

  const versionRef = useRef(0)
  const loadSeqRef = useRef(0)
  const dirtyRef = useRef(new Map<string, HTMLElement>())
  const saveTimerRef = useRef<number | null>(null)
  const savingRef = useRef<Promise<boolean> | null>(null)
  const editableRef = useRef(true)
  const afterRenderRef = useRef<((doc: Document) => void) | null>(null)
  const editTargetsRef = useRef<HTMLElement[]>([])
  const imagesRef = useRef<DocImage[]>([])
  const selectedIdRef = useRef<string | null>(null)
  const caretBlockRef = useRef<string | null>(null)
  const typedSinceRenderRef = useRef(false)
  const imageCountRef = useRef<{ p: HTMLElement; count: number } | null>(null)
  const actionsRef = useRef<{
    openChat: () => void
    undo: () => void
    deleteSelected: () => void
    insertFiles: (files: File[], blockId: string | null) => void
    placeImage: (id: string, blockId: string, x: number, y: number) => void
  } | null>(null)
  const onVersionChangeRef = useRef(onVersionChange)

  useEffect(() => {
    onVersionChangeRef.current = onVersionChange
  }, [onVersionChange])

  const setVersion = useCallback((v: number) => {
    versionRef.current = v
    onVersionChangeRef.current?.(v)
  }, [])

  const loadDocument = useCallback(async () => {
    const seq = ++loadSeqRef.current
    setError("")
    try {
      const res = await api.get<ArrayBuffer>(`/projects/${projectId}/document`, {
        responseType: "arraybuffer",
      })
      if (seq !== loadSeqRef.current) return
      const v = Number(res.headers["x-document-version"])
      if (Number.isFinite(v)) setVersion(v)
      setDocxBuffer(res.data)
    } catch (err) {
      if (seq !== loadSeqRef.current) return
      afterRenderRef.current = null
      setError(bufferErrorDetail(err, "Couldn't load the document."))
      setLoading(false)
    }
  }, [projectId, setVersion])

  const reloadDocument = useCallback(
    (after?: (doc: Document) => void) => {
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
      dirtyRef.current.clear()
      setSaveState("idle")
      afterRenderRef.current = after ?? null
      return loadDocument()
    },
    [loadDocument],
  )

  useEffect(() => {
    if (!projectId) return
    let active = true
    Promise.resolve().then(() => {
      if (active) void reloadDocument()
    })
    return () => {
      active = false
    }
  }, [projectId, reloadKey, reloadDocument])

  const flushEdits = useCallback(async (): Promise<boolean> => {
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = null
    while (savingRef.current) await savingRef.current
    const dirty = dirtyRef.current
    if (dirty.size === 0) return true
    const batch = Array.from(dirty.entries())
    dirty.clear()
    setSaveState("saving")
    setSaveError("")
    const run = (async () => {
      try {
        const res = await api.post<{ version: number }>(
          `/projects/${projectId}/document/edits`,
          {
            version: versionRef.current,
            edits: batch.map(([block_id, p]) => ({ block_id, text: paragraphText(p) })),
          },
        )
        setVersion(res.data.version)
        setSaveState(dirtyRef.current.size ? "pending" : "saved")
        return true
      } catch (err) {
        if (statusOf(err) === 409) {
          setNotice("The document changed elsewhere. Reloaded the latest version; your last edit wasn't saved.")
          void reloadDocument()
          return false
        }
        for (const [id, p] of batch) if (!dirty.has(id)) dirty.set(id, p)
        setSaveState("error")
        setSaveError(apiErrorDetail(err, "Couldn't save."))
        return false
      }
    })()
    savingRef.current = run
    try {
      return await run
    } finally {
      savingRef.current = null
    }
  }, [projectId, reloadDocument, setVersion])

  const scheduleSave = useCallback(() => {
    setSaveState("pending")
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null
      void flushEdits()
    }, SAVE_DELAY_MS)
  }, [flushEdits])

  const setEditable = useCallback((on: boolean) => {
    editableRef.current = on
    docRef.current
      ?.querySelectorAll<HTMLElement>("section.docx")
      .forEach((el) => (el.contentEditable = on ? "true" : "false"))
  }, [])

  const toFrameBox = useCallback((r: DOMRect) => {
    const f = iframeRef.current!.getBoundingClientRect()
    const b = frameBoxRef.current!.getBoundingClientRect()
    return { top: f.top + r.top - b.top, bottom: f.top + r.bottom - b.top, left: f.left + r.left - b.left, height: b.height, width: b.width }
  }, [])

  const updateAsk = useCallback(() => {
    const idoc = docRef.current
    const iframe = iframeRef.current
    const box = frameBoxRef.current
    const sel = idoc?.getSelection()
    if (!idoc || !iframe || !box || !sel || sel.rangeCount === 0 || sel.isCollapsed) {
      setAsk(null)
      return
    }
    const range = sel.getRangeAt(0)
    const text = selectionText(idoc.body, range)
    const blocks = blocksInRange(idoc.body, range)
    if (!text || blocks.length === 0) {
      setAsk(null)
      return
    }
    const r = range.getBoundingClientRect()
    const pos = toFrameBox(r)
    const top = pos.bottom + 8
    if (top < 0 || top > pos.height - 36) {
      setAsk(null)
      return
    }
    const left = Math.min(Math.max(pos.left + r.width / 2, 64), pos.width - 64)
    setAsk({
      top,
      left,
      text,
      blockIds: blocks.map((p) => p.getAttribute(BLOCK_ATTR) as string),
    })
  }, [toFrameBox])

  const updateImageBar = useCallback(() => {
    const id = selectedIdRef.current
    const image = id ? imagesRef.current.find((i) => i.id === id) : null
    if (!image || !image.img.isConnected || !iframeRef.current || !frameBoxRef.current) {
      setSelected(null)
      return
    }
    const pos = toFrameBox(image.img.getBoundingClientRect())
    const below = pos.top < 52
    const top = below ? pos.bottom + 10 : pos.top - 44
    const rect = image.img.getBoundingClientRect()
    const left = Math.min(Math.max(pos.left + rect.width / 2, 150), pos.width - 150)
    setSelected({ id: image.id, floating: image.floating, top, left, below })
  }, [toFrameBox])

  const selectImage = useCallback(
    (id: string | null) => {
      selectedIdRef.current = id
      for (const image of imagesRef.current) image.img.classList.toggle("tq-img-selected", image.id === id)
      updateImageBar()
    },
    [updateImageBar],
  )

  const currentScale = useCallback(() => {
    const page = docRef.current?.querySelector<HTMLElement>("section.docx")
    return page ? pageScale(page, pageWidthPx(page)) : 1
  }, [])

  // Blocks the picture would be inserted next to: the caret's paragraph, else the one in the middle of the view.
  const insertionBlock = useCallback((): string | null => {
    const idoc = docRef.current
    if (!idoc) return null
    const caret = caretBlockRef.current
    if (caret && idoc.querySelector(blockSelector(caret))) return caret
    const box = scrollRef.current?.getBoundingClientRect()
    const f = iframeRef.current?.getBoundingClientRect()
    if (!box || !f) return null
    const p = anchorParagraphAt(idoc.body, box.top + box.height / 2 - f.top)
    return p?.getAttribute(BLOCK_ATTR) ?? null
  }, [])

  const wireDocument = useCallback(
    (idoc: Document) => {
      const selectionBlock = () => {
        const sel = idoc.getSelection()
        return sel && sel.rangeCount ? blockParagraphOf(sel.getRangeAt(0).startContainer) : null
      }

      idoc.addEventListener("beforeinput", (e: InputEvent) => {
        if (!editableRef.current) {
          e.preventDefault()
          return
        }
        const sel = idoc.getSelection()
        if (!sel || sel.rangeCount === 0) return
        const range = sel.getRangeAt(0)
        const type = e.inputType
        if (type.startsWith("format") || type === "insertFromDrop") {
          e.preventDefault()
          return
        }
        const startP = blockParagraphOf(range.startContainer)
        if (type.startsWith("delete") && !range.collapsed) {
          const frag = range.cloneContents()
          if (frag.querySelector("img")) {
            e.preventDefault()
            setNotice("Select the picture and press Delete to remove it.")
            return
          }
        }
        if (startP) imageCountRef.current = { p: startP, count: startP.querySelectorAll("img").length }
        if (range.collapsed) {
          if (!startP) {
            e.preventDefault()
            return
          }
          if (
            (BACKWARD_DELETES.has(type) &&
              isAtParagraphStart(startP, range.startContainer, range.startOffset)) ||
            (FORWARD_DELETES.has(type) &&
              isAtParagraphEnd(startP, range.startContainer, range.startOffset))
          ) {
            e.preventDefault()
            return
          }
          editTargetsRef.current = [startP]
          if (type === "insertParagraph") {
            e.preventDefault()
            idoc.execCommand("insertLineBreak")
          }
          return
        }
        const blocks = blocksInRange(idoc.body, range)
        if (blocks.length !== 1) {
          e.preventDefault()
          if (blocks.length > 1) {
            setNotice("Edit one paragraph at a time. For bigger changes, use Ask AI.")
          }
          return
        }
        const p = blocks[0]
        editTargetsRef.current = [p]
        const endP = blockParagraphOf(range.endContainer)
        if (startP === p && endP === p && type !== "insertParagraph") return
        // Clamp a range that touches a neighbouring paragraph so the browser can't merge the two.
        e.preventDefault()
        const clamped = range.cloneRange()
        if (startP !== p) clamped.setStart(p, 0)
        if (endP !== p) clamped.setEnd(p, p.childNodes.length)
        sel.removeAllRanges()
        sel.addRange(clamped)
        if (type === "insertText" || type === "insertReplacementText") {
          idoc.execCommand("insertText", false, e.data ?? "")
        } else if (type === "insertParagraph" || type === "insertLineBreak") {
          idoc.execCommand("insertLineBreak")
        } else if (type.startsWith("delete")) {
          idoc.execCommand("delete")
        }
      })

      idoc.addEventListener("input", () => {
        typedSinceRenderRef.current = true
        const before = imageCountRef.current
        imageCountRef.current = null
        if (before && before.p.querySelectorAll("img").length < before.count) {
          // A backspace swallowed a picture; the file still has it, so re-render instead of saving a lie.
          setNotice("Select the picture and press Delete to remove it.")
          void flushEdits().then(() => reloadDocument())
          return
        }
        const targets = [...editTargetsRef.current]
        const current = selectionBlock()
        if (current) targets.push(current)
        editTargetsRef.current = []
        let changed = false
        for (const p of targets) {
          const id = p.getAttribute(BLOCK_ATTR)
          if (id && p.isConnected) {
            dirtyRef.current.set(id, p)
            changed = true
          }
        }
        if (changed) scheduleSave()
      })

      idoc.addEventListener("paste", (e: ClipboardEvent) => {
        e.preventDefault()
        const files = Array.from(e.clipboardData?.files ?? []).filter((f) => IMAGE_TYPES.includes(f.type))
        if (files.length) {
          actionsRef.current?.insertFiles(files, selectionBlock()?.getAttribute(BLOCK_ATTR) ?? null)
          return
        }
        const text = (e.clipboardData?.getData("text/plain") ?? "").replace(/\s*\r?\n\s*/g, " ")
        if (text) idoc.execCommand("insertText", false, text)
      })

      idoc.addEventListener("dragstart", (e) => e.preventDefault())
      idoc.addEventListener("dragover", (e: DragEvent) => {
        if (!e.dataTransfer?.types.includes("Files")) return
        e.preventDefault()
        idoc.body.classList.add("tq-dropping")
      })
      idoc.addEventListener("dragleave", () => idoc.body.classList.remove("tq-dropping"))
      idoc.addEventListener("drop", (e: DragEvent) => {
        e.preventDefault()
        idoc.body.classList.remove("tq-dropping")
        const files = Array.from(e.dataTransfer?.files ?? []).filter((f) => IMAGE_TYPES.includes(f.type))
        if (!files.length) return
        const p = anchorParagraphAt(idoc.body, e.clientY)
        actionsRef.current?.insertFiles(files, p?.getAttribute(BLOCK_ATTR) ?? null)
      })

      idoc.addEventListener("selectionchange", () => {
        const p = selectionBlock()
        if (p && !p.closest("header, footer")) caretBlockRef.current = p.getAttribute(BLOCK_ATTR)
        updateAsk()
      })

      let drag: {
        image: DocImage
        x: number
        y: number
        rect: DOMRect
        moved: boolean
        anchor: HTMLElement | null
        pointerId: number
      } | null = null

      const clearAnchor = () => idoc.querySelectorAll("p.tq-anchor").forEach((p) => p.classList.remove("tq-anchor"))

      idoc.addEventListener("pointerdown", (e: PointerEvent) => {
        const img = (e.target as Element | null)?.closest?.(`img[${IMAGE_ATTR}]`) as HTMLImageElement | null
        if (!img) {
          if (selectedIdRef.current) selectImage(null)
          return
        }
        if (e.button !== 0) return
        e.preventDefault()
        const image = imagesRef.current.find((i) => i.img === img)
        if (!image) return
        selectImage(image.id)
        if (!editableRef.current) return
        drag = { image, x: e.clientX, y: e.clientY, rect: img.getBoundingClientRect(), moved: false, anchor: null, pointerId: e.pointerId }
        img.setPointerCapture(e.pointerId)
      })

      idoc.addEventListener("pointermove", (e: PointerEvent) => {
        if (!drag || e.pointerId !== drag.pointerId) return
        const dx = e.clientX - drag.x
        const dy = e.clientY - drag.y
        if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return
        if (!drag.moved) {
          drag.moved = true
          drag.image.img.classList.add("tq-img-dragging")
          idoc.body.classList.add("tq-dragging")
          setSelected(null)
        }
        const scale = pageScale(
          (drag.image.img.closest("section.docx") as HTMLElement) ?? idoc.body,
          pageWidthPx(drag.image.img.closest("section.docx") as HTMLElement | null),
        )
        drag.image.frame.style.transform = `translate(${dx / scale}px, ${dy / scale}px)`
        const anchor = anchorParagraphAt(idoc.body, drag.rect.top + dy)
        if (anchor !== drag.anchor) {
          clearAnchor()
          anchor?.classList.add("tq-anchor")
          drag.anchor = anchor
        }
        const scroller = scrollRef.current
        const f = iframeRef.current?.getBoundingClientRect()
        if (scroller && f) {
          const box = scroller.getBoundingClientRect()
          const y = f.top + e.clientY
          if (y > box.bottom - 48) scroller.scrollTop += 14
          else if (y < box.top + 48) scroller.scrollTop -= 14
        }
      })

      const endDrag = (e: PointerEvent, cancelled: boolean) => {
        if (!drag || e.pointerId !== drag.pointerId) return
        const current = drag
        drag = null
        clearAnchor()
        idoc.body.classList.remove("tq-dragging")
        current.image.img.classList.remove("tq-img-dragging")
        if (!current.moved) return
        const anchor = current.anchor
        if (cancelled || !anchor) {
          current.image.frame.style.transform = ""
          selectImage(current.image.id)
          return
        }
        const section = (anchor.closest("section.docx") as HTMLElement) ?? idoc.body
        const scale = pageScale(section, pageWidthPx(section))
        const left = current.rect.left + (e.clientX - current.x)
        const top = current.rect.top + (e.clientY - current.y)
        const x = Math.round(((left - columnLeft(anchor, scale)) / scale) * EMU_PER_PX)
        const y = Math.round(((top - anchor.getBoundingClientRect().top) / scale) * EMU_PER_PX)
        actionsRef.current?.placeImage(current.image.id, anchor.getAttribute(BLOCK_ATTR) as string, x, y)
      }
      idoc.addEventListener("pointerup", (e) => endDrag(e, false))
      idoc.addEventListener("pointercancel", (e) => endDrag(e, true))

      idoc.addEventListener("keydown", (e: KeyboardEvent) => {
        const mod = isMac() ? e.metaKey : e.ctrlKey
        if (e.key === "Escape") {
          if (selectedIdRef.current) selectImage(null)
          else setChatOpen(false)
          return
        }
        if (mod && e.key.toLowerCase() === "k") {
          e.preventDefault()
          actionsRef.current?.openChat()
          return
        }
        if (mod && !e.shiftKey && e.key.toLowerCase() === "z" && !typedSinceRenderRef.current) {
          e.preventDefault()
          actionsRef.current?.undo()
          return
        }
        if (selectedIdRef.current && (e.key === "Delete" || e.key === "Backspace")) {
          e.preventDefault()
          actionsRef.current?.deleteSelected()
        }
      })
    },
    [flushEdits, reloadDocument, scheduleSave, selectImage, updateAsk],
  )

  useEffect(() => {
    if (!docxBuffer) return
    const host = hostRef.current
    if (!host) return
    let cancelled = false
    let observer: ResizeObserver | null = null
    let mutations: MutationObserver | null = null

    ;(async () => {
      try {
        const { renderAsync } = await import("docx-preview")
        if (cancelled) return
        const previous = host.querySelector("iframe")
        const iframe = document.createElement("iframe")
        iframe.title = "Translated document"
        Object.assign(iframe.style, {
          width: "100%",
          border: "0",
          background: "transparent",
          display: "block",
        })
        if (previous) {
          Object.assign(iframe.style, { position: "absolute", top: "0", left: "0", visibility: "hidden" })
        }
        await new Promise<void>((resolve) => {
          iframe.addEventListener("load", () => resolve(), { once: true })
          host.appendChild(iframe)
          if (iframe.contentDocument?.readyState === "complete") resolve()
        })
        if (cancelled) {
          iframe.remove()
          return
        }

        const idoc = iframe.contentDocument
        if (!idoc) throw new Error("Iframe document inaccessible")
        idoc.open()
        idoc.write(IFRAME_HTML)
        idoc.close()

        await renderAsync(docxBuffer, idoc.body, undefined, RENDER_OPTIONS)
        if (cancelled) {
          iframe.remove()
          return
        }

        tagBlocks(idoc.body)
        const images = findImages(idoc.body)
        idoc.querySelectorAll<HTMLElement>("section.docx").forEach((el) => {
          el.contentEditable = editableRef.current ? "true" : "false"
          el.spellcheck = true
        })
        wireDocument(idoc)

        const applyZoom = () => {
          const page = idoc.querySelector<HTMLElement>("section.docx")
          const z = Math.min(1, (host.clientWidth - 24) / pageWidthPx(page))
          if (Number.isFinite(z) && z > 0) {
            idoc.documentElement.style.setProperty("--docx-zoom", String(z))
          }
        }
        const fitHeight = () => {
          const h = Math.max(
            idoc.body.scrollHeight,
            idoc.body.offsetHeight,
            idoc.documentElement.scrollHeight,
            idoc.documentElement.offsetHeight,
          )
          iframe.style.height = `${h + 24}px`
        }

        const scrollTop = scrollRef.current?.scrollTop ?? 0
        previous?.remove()
        Object.assign(iframe.style, { position: "", top: "", left: "", visibility: "" })
        applyZoom()
        fitHeight()
        if (scrollRef.current) scrollRef.current.scrollTop = scrollTop
        const page = idoc.querySelector<HTMLElement>("section.docx")
        const scale = page ? pageScale(page, pageWidthPx(page)) : 1
        for (const image of images) alignFloatingToColumn(image, scale)

        observer = new ResizeObserver(() => {
          applyZoom()
          fitHeight()
          if (selectedIdRef.current) updateImageBar()
        })
        observer.observe(host)
        mutations = new MutationObserver(fitHeight)
        mutations.observe(idoc.body, { childList: true, subtree: true, characterData: true })

        iframeRef.current = iframe
        docRef.current = idoc
        imagesRef.current = images
        typedSinceRenderRef.current = false
        setAsk(null)
        setLoading(false)
        setRenderTick((t) => t + 1)
        const keep = selectedIdRef.current
        selectedIdRef.current = null
        const after = afterRenderRef.current
        afterRenderRef.current = null
        if (keep && images.some((i) => i.id === keep)) selectImage(keep)
        else setSelected(null)
        after?.(idoc)
      } catch (e) {
        if (cancelled) return
        setError(e instanceof Error ? `Couldn't render the document: ${e.message}` : "Couldn't render the document.")
        setLoading(false)
      }
    })()

    return () => {
      cancelled = true
      observer?.disconnect()
      mutations?.disconnect()
    }
  }, [docxBuffer, wireDocument, selectImage, updateImageBar])

  useEffect(() => {
    const idoc = docRef.current
    if (!idoc) return
    idoc.querySelectorAll("p.tq-target").forEach((p) => p.classList.remove("tq-target"))
    if (!chatOpen || !target) return
    for (const id of target.blockIds) idoc.querySelector(blockSelector(id))?.classList.add("tq-target")
  }, [chatOpen, target, renderTick])

  useEffect(() => {
    onChatOpenChange?.(chatOpen)
    if (!chatOpen) return
    textareaRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setChatOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [chatOpen, onChatOpenChange])

  useEffect(() => {
    const el = messagesRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [turns, busy])

  useEffect(() => {
    if (!notice) return
    const t = window.setTimeout(() => setNotice(""), 5000)
    return () => window.clearTimeout(t)
  }, [notice])

  useEffect(() => {
    const dirty = dirtyRef.current
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty.size || savingRef.current) e.preventDefault()
    }
    window.addEventListener("beforeunload", warn)
    return () => {
      window.removeEventListener("beforeunload", warn)
      if (dirty.size) void flushEdits()
    }
  }, [flushEdits])

  const highlightBlocks = useCallback((ids: string[]) => {
    return (idoc: Document) => {
      const ps = ids
        .map((id) => idoc.querySelector<HTMLElement>(blockSelector(id)))
        .filter((p): p is HTMLElement => !!p)
      for (const p of ps) {
        p.classList.add("tq-changed")
        window.setTimeout(() => p.classList.remove("tq-changed"), HIGHLIGHT_MS)
      }
      ps[0]?.scrollIntoView({ block: "center", behavior: "smooth" })
    }
  }, [])

  const openChat = (next: Target | null) => {
    setTarget(next)
    setAsk(null)
    setChatError("")
    setChatOpen(true)
    textareaRef.current?.focus()
  }

  const send = async (text?: string) => {
    const message = (text ?? draft).trim()
    if (!message || busy) return
    const history = turns.slice(-HISTORY_TURNS)
    setBusy("chat")
    setChatError("")
    setDraft("")
    setTurns((t) => [...t, { role: "user", content: message }])
    setEditable(false)
    try {
      if (!(await flushEdits())) throw new Error("unsaved")
      const res = await api.post<{ version: number; reply: string; changed_block_ids: string[] }>(
        `/projects/${projectId}/document/chat`,
        {
          version: versionRef.current,
          block_ids: target?.blockIds ?? [],
          selected_text: target?.text ?? "",
          message,
          history,
        },
      )
      setVersion(res.data.version)
      setTurns((t) => [...t, { role: "assistant", content: res.data.reply }])
      await reloadDocument(highlightBlocks(res.data.changed_block_ids ?? []))
    } catch (err) {
      setTurns((t) => t.slice(0, -1))
      setDraft(message)
      const status = statusOf(err)
      if (err instanceof Error && err.message === "unsaved") {
        setChatError("Your last edit didn't save. Try again.")
      } else if (status === 409) {
        setChatError("The document changed elsewhere. Reloaded it; send again.")
        void reloadDocument()
      } else if (status === 429) {
        setChatError(apiErrorDetail(err, "Too many requests. Wait a moment and try again."))
      } else if (status === 502) {
        setChatError(apiErrorDetail(err, "The assistant couldn't make that change. Try again."))
      } else {
        setChatError(apiErrorDetail(err, "Something went wrong. Try again."))
      }
    } finally {
      setBusy(null)
      setEditable(true)
    }
  }

  const undo = async () => {
    if (busy) return
    setBusy("undo")
    setEditable(false)
    try {
      if (!(await flushEdits())) return
      const res = await api.post<{ version: number }>(`/projects/${projectId}/document/undo`, {})
      setVersion(res.data.version)
      await reloadDocument()
    } catch (err) {
      setNotice(statusOf(err) === 404 ? "Nothing to undo." : apiErrorDetail(err, "Couldn't undo."))
    } finally {
      setBusy(null)
      setEditable(true)
    }
  }

  // Runs one versioned document change: saves typing first, blocks editing meanwhile, re-renders in place.
  const runChange = async (
    kind: "image" | "cert",
    call: (version: number) => Promise<{ version: number }>,
    after?: (idoc: Document) => void,
    failure = "Couldn't update the document.",
  ): Promise<boolean> => {
    if (busy) return false
    setBusy(kind)
    setEditable(false)
    try {
      if (!(await flushEdits())) return false
      const res = await call(versionRef.current)
      setVersion(res.version)
      await reloadDocument(after)
      return true
    } catch (err) {
      const status = statusOf(err)
      if (status === 409) {
        setNotice("The document changed. Reloaded the latest version; try again.")
        void reloadDocument()
      } else if (status === 403) {
        setNotice(apiErrorDetail(err, "This is a Pro feature. Upgrade in Billing to unlock it."))
      } else {
        setNotice(apiErrorDetail(err, failure))
      }
      return false
    } finally {
      setBusy(null)
      setEditable(true)
    }
  }

  const selectAfterRender = (id: string) => (idoc: Document) => {
    const image = imagesRef.current.find((i) => i.id === id)
    if (!image) return
    selectImage(id)
    const r = image.img.getBoundingClientRect()
    const scroller = scrollRef.current
    const f = iframeRef.current?.getBoundingClientRect()
    if (scroller && f && idoc) {
      const box = scroller.getBoundingClientRect()
      const y = f.top + r.top
      if (y < box.top || y + r.height > box.bottom) {
        scroller.scrollTo({ top: scroller.scrollTop + y - box.top - box.height / 3, behavior: "smooth" })
      }
    }
  }

  const insertFiles = async (files: File[], blockId: string | null, mode: "image" | "stamp" = "image") => {
    const file = files[0]
    if (!file) return
    if (!IMAGE_TYPES.includes(file.type)) {
      setNotice("Use a PNG, JPG or WebP image.")
      return
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setNotice("Images must be 5 MB or smaller.")
      return
    }
    const block = blockId ?? insertionBlock()
    if (!block) {
      setNotice("Click in the document where the picture should go.")
      return
    }
    let newId = ""
    await runChange(
      "image",
      async (version) => {
        const form = new FormData()
        form.append("file", file)
        form.append("version", String(version))
        form.append("block_id", block)
        form.append("position", "after")
        form.append("align", mode === "stamp" ? "right" : "left")
        if (mode === "stamp") {
          form.append("remove_background", "true")
          form.append("width_cm", "3.8")
        }
        const res = await api.post<{ version: number; image_id: string }>(
          `/projects/${projectId}/document/images`,
          form,
        )
        newId = res.data.image_id
        return res.data
      },
      (idoc) => selectAfterRender(newId)(idoc),
      "Couldn't add the picture.",
    )
  }

  const insertAsset = async (asset: "logo" | "stamp") => {
    setImageMenuOpen(false)
    const block = insertionBlock()
    if (!block) {
      setNotice("Click in the document where it should go.")
      return
    }
    let newId = ""
    await runChange(
      "image",
      async (version) => {
        const res = await api.post<{ version: number; image_id: string }>(
          `/projects/${projectId}/document/assets/${asset}`,
          { version, block_id: block, position: "after", align: asset === "stamp" ? "right" : "center" },
        )
        newId = res.data.image_id
        return res.data
      },
      (idoc) => selectAfterRender(newId)(idoc),
      `Couldn't insert your ${asset}.`,
    )
  }

  const imageAction = (id: string, path: string, body: Record<string, unknown>) =>
    runChange(
      "image",
      async (version) =>
        (await api.post<{ version: number }>(`/projects/${projectId}/document/images/${id}/${path}`, { version, ...body })).data,
      selectAfterRender(id),
    )

  const resizeSelected = (factor: number) => {
    const id = selectedIdRef.current
    const image = id ? imagesRef.current.find((i) => i.id === id) : null
    if (!image) return
    const width = Math.min(19, Math.max(0.5, widthCm(image.img, currentScale()) * factor))
    void imageAction(image.id, "resize", { width_cm: Math.round(width * 10) / 10 })
  }

  const alignSelected = (align: Align) => {
    const id = selectedIdRef.current
    if (id) void imageAction(id, "align", { align })
  }

  const deleteSelected = async () => {
    const id = selectedIdRef.current
    if (!id) return
    selectImage(null)
    await runChange(
      "image",
      async (version) =>
        (await api.delete<{ version: number }>(`/projects/${projectId}/document/images/${id}`, { params: { version } })).data,
      undefined,
      "Couldn't delete the picture.",
    )
  }

  const placeImage = (id: string, blockId: string, x: number, y: number) => {
    void imageAction(id, "position", { target_block_id: blockId, x_emu: x, y_emu: y }).then((ok) => {
      if (!ok) {
        const image = imagesRef.current.find((i) => i.id === id)
        if (image) image.frame.style.transform = ""
      }
    })
  }

  const scrollToCertification = (idoc: Document) => {
    const start = idoc.getElementById(CERT_START_ID)
    const p = start?.closest("p") as HTMLElement | null
    if (!p) return
    const scroller = scrollRef.current
    const f = iframeRef.current?.getBoundingClientRect()
    if (!scroller || !f) return
    const box = scroller.getBoundingClientRect()
    const section = (p.closest("section.docx") as HTMLElement | null) ?? p
    const y = f.top + section.getBoundingClientRect().top
    scroller.scrollTo({ top: scroller.scrollTop + y - box.top - 12, behavior: "smooth" })
  }

  const loadCertification = async (): Promise<CertState | null> => {
    try {
      const res = await api.get<{ present: boolean; fields: CertFields }>(`/projects/${projectId}/document/certification`)
      const state = { present: res.data.present, fields: res.data.present ? { ...EMPTY_FIELDS, ...res.data.fields } : null }
      setCert(state)
      if (state.fields) setCertDraft(state.fields)
      return state
    } catch (err) {
      setNotice(
        statusOf(err) === 403
          ? "The certification page is a Pro feature. Upgrade in Billing to unlock it."
          : apiErrorDetail(err, "Couldn't load the certification page."),
      )
      return null
    }
  }

  const addCertification = async (): Promise<boolean> => {
    let fields: CertFields | null = null
    const ok = await runChange(
      "cert",
      async (version) => {
        const res = await api.post<{ version: number; fields: CertFields }>(
          `/projects/${projectId}/document/certification`,
          { version },
        )
        fields = { ...EMPTY_FIELDS, ...res.data.fields }
        return res.data
      },
      scrollToCertification,
      "Couldn't add the certification page.",
    )
    if (ok && fields) {
      setCert({ present: true, fields })
      setCertDraft(fields)
      setCertOpen(true)
    }
    return ok
  }

  const toggleCertification = async () => {
    setImageMenuOpen(false)
    if (certOpen) {
      setCertOpen(false)
      return
    }
    const state = await loadCertification()
    if (!state) return
    if (!state.present) {
      await addCertification()
      return
    }
    setCertError("")
    setConfirmRemove(false)
    setCertOpen(true)
    const idoc = docRef.current
    if (idoc) scrollToCertification(idoc)
  }

  const saveCertification = async () => {
    setCertError("")
    const { date_iso, translator, source_language, target_language, document: doc } = certDraft
    let fields: CertFields | null = null
    const ok = await runChange(
      "cert",
      async (version) => {
        const res = await api.put<{ version: number; fields: CertFields }>(
          `/projects/${projectId}/document/certification`,
          {
            version,
            fields: { date: date_iso || undefined, translator, source_language, target_language, document: doc },
          },
        )
        fields = { ...EMPTY_FIELDS, ...res.data.fields }
        return res.data
      },
      scrollToCertification,
      "Couldn't update the certification page.",
    )
    if (ok && fields) {
      setCert({ present: true, fields })
      setCertDraft(fields)
      setNotice("Certification page updated.")
    }
  }

  const removeCertification = async () => {
    const ok = await runChange(
      "cert",
      async (version) =>
        (await api.delete<{ version: number }>(`/projects/${projectId}/document/certification`, { params: { version } })).data,
      undefined,
      "Couldn't remove the certification page.",
    )
    if (ok) {
      setCert({ present: false, fields: null })
      setCertOpen(false)
      setConfirmRemove(false)
    }
  }

  const ensureCertification = async (): Promise<boolean> => {
    const state = await loadCertification()
    if (!state) return false
    if (state.present) {
      const idoc = docRef.current
      if (idoc) scrollToCertification(idoc)
      return true
    }
    return addCertification()
  }

  useImperativeHandle(ref, () => ({ ensureCertification }))

  useEffect(() => {
    actionsRef.current = {
      openChat: () => openChat(ask ? { blockIds: ask.blockIds, text: ask.text } : null),
      undo: () => void undo(),
      deleteSelected: () => void deleteSelected(),
      insertFiles: (files, blockId) => void insertFiles(files, blockId),
      placeImage,
    }
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = isMac() ? e.metaKey : e.ctrlKey
      if (mod && e.key.toLowerCase() === "k" && renderTick > 0) {
        e.preventDefault()
        actionsRef.current?.openChat()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [renderTick])

  const openImageMenu = async () => {
    setCertOpen(false)
    const next = !imageMenuOpen
    setImageMenuOpen(next)
    if (next && !assets) {
      try {
        setAssets((await api.get<Assets>(`/projects/${projectId}/document/assets`)).data)
      } catch {
        setAssets({ logo: { available: false, url: null }, stamp: { available: false, url: null } })
      }
    }
  }

  const pickFile = (mode: "image" | "stamp") => {
    uploadModeRef.current = mode
    setImageMenuOpen(false)
    fileRef.current?.click()
  }

  const saveLabel =
    saveState === "pending" || saveState === "saving"
      ? "Saving…"
      : saveState === "saved"
        ? "Saved"
        : saveState === "error"
          ? saveError || "Couldn't save."
          : ""

  const hasDocument = renderTick > 0
  const modKey = isMac() ? "⌘" : "Ctrl+"
  const busyLabel =
    busy === "chat" ? "Editing…" : busy === "undo" ? "Undoing…" : busy === "cert" ? "Updating certification…" : "Updating…"

  return (
    <div className="flex gap-3 h-full" style={{ minHeight: 0 }}>
      <div
        className="rounded-2xl overflow-hidden flex flex-col flex-1 min-w-0"
        style={{ background: "#e8dfc7", border: "1px solid #e7ddc5", minHeight: 0 }}
      >
        <div
          className="relative px-4 py-2 flex items-center justify-between gap-2 text-[11px] font-semibold tracking-[0.14em]"
          style={{ color: "#9a9178", background: "#faf5ee", borderBottom: "1px solid #f1e8d1" }}
        >
          <span>TRANSLATION</span>
          <div className="flex items-center gap-1.5">
            {saveLabel && (
              <span
                role="status"
                className="text-[10px] font-medium tracking-[0.06em] truncate max-w-[180px] mr-1"
                style={{ color: saveState === "error" ? "#a14e2e" : saveState === "saved" ? "#2d6a4f" : "#0a7870" }}
              >
                {saveLabel}
              </span>
            )}
            {saveState === "error" && (
              <button
                type="button"
                onClick={() => void flushEdits()}
                className={BTN}
                style={{ background: "#ffffff", color: "#a14e2e", border: "1px solid #f2d4cf" }}
              >
                Retry
              </button>
            )}
            <button
              type="button"
              onClick={() => void openImageMenu()}
              disabled={busy !== null || !hasDocument}
              aria-haspopup="menu"
              aria-expanded={imageMenuOpen}
              className={BTN}
              style={BTN_STYLE}
            >
              Image
            </button>
            <button
              type="button"
              onClick={() => void toggleCertification()}
              disabled={busy !== null || !hasDocument}
              aria-expanded={certOpen}
              title="Add or edit the certification page"
              className={BTN}
              style={certOpen ? { ...BTN_STYLE, background: "#e3f1ee", color: "#0a5e58", border: "1px solid #cfe6e2" } : BTN_STYLE}
            >
              Certification
            </button>
            <button
              type="button"
              onClick={() => void undo()}
              disabled={busy !== null || !hasDocument}
              aria-label="Undo last change"
              title={`Undo last change (${modKey}Z)`}
              className={BTN}
              style={BTN_STYLE}
            >
              {busy === "undo" ? "Undoing…" : "Undo"}
            </button>
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => openChat(ask ? { blockIds: ask.blockIds, text: ask.text } : null)}
              disabled={!hasDocument}
              aria-label={ask ? "Ask AI about the selection" : "Ask AI about the whole document"}
              title={`Ask AI (${modKey}K)`}
              className={BTN}
              style={{ background: "#0a7870", color: "#ffffff", border: "1px solid #0a7870" }}
            >
              Ask AI
            </button>
          </div>

          {imageMenuOpen && (
            <div
              role="menu"
              className="absolute right-4 top-full mt-1 w-60 rounded-xl py-1.5 z-30 tq-pop"
              style={{ background: "#ffffff", border: "1px solid #e7ddc5", boxShadow: "0 12px 32px rgba(30,30,20,0.14)" }}
            >
              <MenuItem label="Upload image…" hint="PNG, JPG or WebP" onClick={() => pickFile("image")} />
              <MenuItem label="Upload stamp or signature…" hint="White paper becomes transparent" onClick={() => pickFile("stamp")} />
              {assets?.stamp.available && (
                <MenuItem label="Insert my stamp" thumb={assets.stamp.url} onClick={() => void insertAsset("stamp")} />
              )}
              {assets?.logo.available && (
                <MenuItem label="Insert my logo" thumb={assets.logo.url} onClick={() => void insertAsset("logo")} />
              )}
              <div className="px-3 pt-1.5 pb-1 text-[10px] font-normal tracking-normal" style={{ color: "#9a9178" }}>
                Goes after the paragraph you clicked. Drag it anywhere afterwards, or drop and paste pictures straight onto the page.
              </div>
            </div>
          )}

          {certOpen && cert?.present && (
            <div
              className="absolute right-4 top-full mt-1 w-80 rounded-xl p-3 z-30 tq-pop text-[12px] font-normal tracking-normal"
              style={{ background: "#ffffff", border: "1px solid #e7ddc5", boxShadow: "0 12px 32px rgba(30,30,20,0.14)", color: "#1f2a2e" }}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-semibold tracking-[0.14em]" style={{ color: "#9a9178" }}>
                  CERTIFICATION PAGE
                </span>
                <button
                  type="button"
                  onClick={() => docRef.current && scrollToCertification(docRef.current)}
                  className="text-[11px] font-semibold hover:underline"
                  style={{ color: "#0a7870" }}
                >
                  Go to page
                </button>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  void saveCertification()
                }}
                className="space-y-2"
              >
                <Field label="Date">
                  <input
                    type="date"
                    value={certDraft.date_iso}
                    onChange={(e) => setCertDraft((d) => ({ ...d, date_iso: e.target.value }))}
                    className="tq-input"
                  />
                </Field>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Source language">
                    <input
                      value={certDraft.source_language}
                      onChange={(e) => setCertDraft((d) => ({ ...d, source_language: e.target.value }))}
                      className="tq-input"
                    />
                  </Field>
                  <Field label="Target language">
                    <input
                      value={certDraft.target_language}
                      onChange={(e) => setCertDraft((d) => ({ ...d, target_language: e.target.value }))}
                      className="tq-input"
                    />
                  </Field>
                </div>
                <Field label="Translator">
                  <input
                    value={certDraft.translator}
                    onChange={(e) => setCertDraft((d) => ({ ...d, translator: e.target.value }))}
                    className="tq-input"
                  />
                </Field>
                <Field label="Document">
                  <input
                    value={certDraft.document}
                    onChange={(e) => setCertDraft((d) => ({ ...d, document: e.target.value }))}
                    className="tq-input"
                  />
                </Field>
                {certError && (
                  <div role="alert" style={{ color: "#a14e2e" }}>
                    {certError}
                  </div>
                )}
                <div className="flex items-center justify-between pt-1">
                  {confirmRemove ? (
                    <span className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => void removeCertification()}
                        disabled={busy !== null}
                        className="text-[11px] font-semibold px-2 py-1 rounded-md"
                        style={{ background: "#b14a3a", color: "#ffffff" }}
                      >
                        Remove page
                      </button>
                      <button type="button" onClick={() => setConfirmRemove(false)} className="text-[11px]" style={{ color: "#6b6558" }}>
                        Keep
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmRemove(true)}
                      className="text-[11px] font-semibold hover:underline"
                      style={{ color: "#b14a3a" }}
                    >
                      Remove
                    </button>
                  )}
                  <span className="flex items-center gap-2">
                    <button type="button" onClick={() => setCertOpen(false)} className="text-[11px]" style={{ color: "#6b6558" }}>
                      Close
                    </button>
                    <button
                      type="submit"
                      disabled={busy !== null}
                      className="text-[11px] font-semibold px-3 py-1 rounded-md disabled:opacity-50"
                      style={{ background: "#0a7870", color: "#ffffff" }}
                    >
                      {busy === "cert" ? "Saving…" : "Save"}
                    </button>
                  </span>
                </div>
              </form>
              <p className="mt-2 text-[11px] leading-snug" style={{ color: "#9a9178" }}>
                These fields update in place. Anything else on the page you can type over directly.
              </p>
            </div>
          )}
        </div>

        <input
          ref={fileRef}
          type="file"
          accept={IMAGE_TYPES.join(",")}
          className="hidden"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? [])
            e.target.value = ""
            void insertFiles(files, null, uploadModeRef.current)
          }}
        />

        <div ref={frameBoxRef} className="relative flex-1" style={{ minHeight: 0 }}>
          <div
            ref={scrollRef}
            onScroll={() => {
              updateAsk()
              if (selectedIdRef.current) updateImageBar()
            }}
            className="absolute inset-0 overflow-auto"
            style={{ padding: "24px 0" }}
          >
            {error && (
              <div
                className="mx-4 mb-4 text-sm rounded-lg px-3 py-2"
                style={{ background: "#f2d4cf", color: "#7a2f24" }}
              >
                {error}
              </div>
            )}
            {loading && !hasDocument && (
              <div className="text-center text-sm py-20" style={{ color: "#8a8270" }}>
                Loading document…
              </div>
            )}
            <div
              ref={hostRef}
              className="relative transition-opacity duration-150"
              style={{ width: "100%", opacity: busy && busy !== "chat" ? 0.85 : 1 }}
            />
          </div>

          {notice && (
            <div
              role="status"
              className="absolute left-1/2 top-3 -translate-x-1/2 text-[12px] rounded-full px-3 py-1.5 shadow-sm tq-pop"
              style={{ background: "#1f2a2e", color: "#ffffff", maxWidth: "90%", zIndex: 20 }}
            >
              {notice}
            </div>
          )}

          {busy && (
            <div
              className="absolute right-3 bottom-3 text-[11px] rounded-full px-3 py-1.5 tq-pop"
              style={{ background: "#ffffff", color: "#0a5e58", border: "1px solid #cfe6e2" }}
            >
              {busyLabel}
            </div>
          )}

          {selected && !busy && (
            <div
              role="toolbar"
              aria-label="Picture"
              className="absolute -translate-x-1/2 flex items-center gap-0.5 rounded-full px-1.5 py-1 shadow-md tq-pop"
              style={{ top: selected.top, left: selected.left, background: "#1f2a2e", zIndex: 6 }}
              onMouseDown={(e) => e.preventDefault()}
            >
              <BarButton label="Smaller" onClick={() => resizeSelected(0.8)}>
                <path d="M5 12h14" />
              </BarButton>
              <BarButton label="Larger" onClick={() => resizeSelected(1.25)}>
                <path d="M12 5v14M5 12h14" />
              </BarButton>
              <span className="w-px h-4 mx-1" style={{ background: "#4a5559" }} />
              <BarButton label={selected.floating ? "Back in line, left" : "Align left"} onClick={() => alignSelected("left")}>
                <path d="M4 6h16M4 12h10M4 18h13" />
              </BarButton>
              <BarButton label={selected.floating ? "Back in line, centred" : "Centre"} onClick={() => alignSelected("center")}>
                <path d="M4 6h16M7 12h10M5.5 18h13" />
              </BarButton>
              <BarButton label={selected.floating ? "Back in line, right" : "Align right"} onClick={() => alignSelected("right")}>
                <path d="M4 6h16M10 12h10M7 18h13" />
              </BarButton>
              <span className="w-px h-4 mx-1" style={{ background: "#4a5559" }} />
              <BarButton label="Delete" onClick={() => void deleteSelected()}>
                <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
              </BarButton>
              <span className="pl-1.5 pr-2 text-[10px] whitespace-nowrap" style={{ color: "#aab4b6" }}>
                {selected.floating ? "Free" : "In line"} · drag to place
              </span>
            </div>
          )}

          {ask && !busy && !selected && (
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => openChat({ blockIds: ask.blockIds, text: ask.text })}
              className="absolute -translate-x-1/2 text-[12px] font-semibold px-3 py-1.5 rounded-full shadow-md tq-pop"
              style={{ top: ask.top, left: ask.left, background: "#0a7870", color: "#ffffff", zIndex: 5 }}
            >
              Ask AI
            </button>
          )}
        </div>
      </div>

      {chatOpen && (
        <aside
          aria-label="AI assistant"
          className="rounded-2xl overflow-hidden flex flex-col shrink-0 tq-pop"
          style={{ width: 360, background: "#ffffff", border: "1px solid #e7ddc5", minHeight: 0 }}
        >
          <div
            className="px-4 py-2 flex items-center justify-between text-[11px] font-semibold tracking-[0.14em]"
            style={{ color: "#9a9178", background: "#faf5ee", borderBottom: "1px solid #f1e8d1" }}
          >
            <span>ASSISTANT</span>
            <button
              type="button"
              onClick={() => setChatOpen(false)}
              aria-label="Close chat"
              className="w-6 h-6 rounded-md flex items-center justify-center"
              style={{ color: "#6b6558" }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </button>
          </div>

          <div ref={messagesRef} className="flex-1 overflow-auto px-4 py-4 space-y-3" style={{ minHeight: 0 }}>
            {turns.length === 0 && !busy && (
              <div>
                <p className="text-[13px] leading-relaxed mb-3" style={{ color: "#6b6558" }}>
                  Select text in the document to point at it, or ask about the whole document.
                </p>
                <div className="flex flex-col items-start gap-2">
                  {QUICK_PROMPTS.map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => void send(q)}
                      className="text-[12px] px-3 py-1.5 rounded-full text-left"
                      style={{ background: "#faf5ee", color: "#0a5e58", border: "1px solid #e7ddc5" }}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {turns.map((t, i) => (
              <div key={i} className={t.role === "user" ? "flex justify-end" : "flex justify-start"}>
                <div
                  className="text-[13px] leading-relaxed px-3 py-2 rounded-2xl whitespace-pre-wrap max-w-[85%]"
                  style={
                    t.role === "user"
                      ? { background: "#0a7870", color: "#ffffff", borderBottomRightRadius: 6 }
                      : { background: "#f3ecdb", color: "#1f2a2e", borderBottomLeftRadius: 6 }
                  }
                >
                  {t.content}
                </div>
              </div>
            ))}
            {busy === "chat" && (
              <div className="flex justify-start" aria-label="Assistant is typing">
                <div className="px-3 py-2.5 rounded-2xl flex gap-1" style={{ background: "#f3ecdb", borderBottomLeftRadius: 6 }}>
                  {[0, 1, 2].map((d) => (
                    <span
                      key={d}
                      className="w-1.5 h-1.5 rounded-full animate-bounce"
                      style={{ background: "#9a9178", animationDelay: `${d * 150}ms` }}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="px-3 pb-3 pt-2" style={{ borderTop: "1px solid #f1e8d1" }}>
            {chatError && (
              <div role="alert" className="text-[12px] mb-2" style={{ color: "#a14e2e" }}>
                {chatError}
              </div>
            )}
            <div className="mb-2 flex items-center gap-1.5 min-w-0">
              {target ? (
                <span
                  className="inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-md min-w-0 max-w-full"
                  style={{ background: "#e3f1ee", color: "#0a5e58", border: "1px solid #cfe6e2" }}
                >
                  <span className="truncate">&ldquo;{target.text}&rdquo;</span>
                  <button
                    type="button"
                    onClick={() => setTarget(null)}
                    aria-label="Remove selection"
                    className="shrink-0 font-semibold"
                  >
                    ×
                  </button>
                </span>
              ) : (
                <span className="text-[11px]" style={{ color: "#9a9178" }}>
                  Whole document
                </span>
              )}
            </div>
            <div
              className="rounded-xl flex items-end gap-2 px-3 py-2"
              style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
            >
              <textarea
                ref={textareaRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault()
                    void send()
                  }
                }}
                rows={2}
                aria-label="Message the assistant"
                placeholder="Describe the change…"
                className="flex-1 bg-transparent outline-none resize-none text-[13px] leading-relaxed"
                style={{ color: "#1f2a2e", maxHeight: 160 }}
              />
              <button
                type="button"
                onClick={() => void send()}
                disabled={busy !== null || !draft.trim()}
                aria-label="Send"
                className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 disabled:opacity-40"
                style={{ background: "#0a7870", color: "#ffffff" }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 19V5M5 12l7-7 7 7" />
                </svg>
              </button>
            </div>
          </div>
        </aside>
      )}
      <style>{`
        .tq-pop { animation: tq-pop 140ms ease-out; }
        @keyframes tq-pop { from { opacity: 0; transform: translateY(-2px) scale(0.98); } to { opacity: 1; transform: none; } }
        .tq-input { width: 100%; font-size: 12px; padding: 6px 8px; border-radius: 8px; background: #faf5ee; border: 1px solid #e7ddc5; color: #1f2a2e; outline: none; transition: border-color 120ms ease; }
        .tq-input:focus { border-color: #0a7870; }
      `}</style>
    </div>
  )
}

function MenuItem({ label, hint, thumb, onClick }: { label: string; hint?: string; thumb?: string | null; onClick: () => void }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="w-full text-left px-3 py-1.5 flex items-center gap-2.5 transition-colors hover:bg-[#faf5ee] text-[12px] font-medium tracking-normal"
      style={{ color: "#1f2a2e" }}
    >
      {thumb ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={thumb} alt="" className="w-6 h-6 object-contain rounded" style={{ background: "#faf5ee" }} />
      ) : (
        <span className="w-6 h-6 rounded flex items-center justify-center" style={{ background: "#e3f1ee", color: "#0a5e58" }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 16V4M6 10l6-6 6 6M4 20h16" />
          </svg>
        </span>
      )}
      <span className="flex flex-col">
        <span>{label}</span>
        {hint && <span className="text-[10px] font-normal" style={{ color: "#9a9178" }}>{hint}</span>}
      </span>
    </button>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[10px] font-semibold tracking-[0.08em] mb-1" style={{ color: "#6b6558" }}>
        {label}
      </span>
      {children}
    </label>
  )
}

function BarButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:bg-[#34424a]"
      style={{ color: "#ffffff" }}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        {children}
      </svg>
    </button>
  )
}
