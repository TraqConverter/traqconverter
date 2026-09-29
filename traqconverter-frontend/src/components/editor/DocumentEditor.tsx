"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { api, apiErrorDetail } from "@/lib/api"
import {
  BLOCK_ATTR,
  blockParagraphOf,
  blocksInRange,
  isAtParagraphEnd,
  isAtParagraphStart,
  paragraphText,
  selectionText,
  tagBlocks,
} from "./docBlocks"

type ChatTurn = { role: "user" | "assistant"; content: string }
type Target = { blockIds: string[]; text: string }
type AskAnchor = Target & { top: number; left: number }
type SaveState = "idle" | "pending" | "saving" | "saved" | "error"
type Busy = null | "chat" | "undo"

const SAVE_DELAY_MS = 1200
const HISTORY_TURNS = 10
const HIGHLIGHT_MS = 3200
const QUICK_PROMPTS = [
  "Match the source layout here",
  "Make this a two-column table",
  "Move this next to the signature",
]

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

export default function DocumentEditor({
  projectId,
  reloadKey,
  onChatOpenChange,
}: {
  projectId: string
  reloadKey?: number
  onChatOpenChange?: (open: boolean) => void
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

  const hostRef = useRef<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const frameBoxRef = useRef<HTMLDivElement | null>(null)
  const iframeRef = useRef<HTMLIFrameElement | null>(null)
  const docRef = useRef<Document | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const messagesRef = useRef<HTMLDivElement | null>(null)

  const versionRef = useRef(0)
  const loadSeqRef = useRef(0)
  const dirtyRef = useRef(new Map<string, HTMLElement>())
  const saveTimerRef = useRef<number | null>(null)
  const savingRef = useRef<Promise<boolean> | null>(null)
  const editableRef = useRef(true)
  const afterRenderRef = useRef<((doc: Document) => void) | null>(null)
  const editTargetsRef = useRef<HTMLElement[]>([])

  const loadDocument = useCallback(async () => {
    const seq = ++loadSeqRef.current
    setError("")
    try {
      const res = await api.get<ArrayBuffer>(`/projects/${projectId}/document`, {
        responseType: "arraybuffer",
      })
      if (seq !== loadSeqRef.current) return
      const v = Number(res.headers["x-document-version"])
      if (Number.isFinite(v)) versionRef.current = v
      setDocxBuffer(res.data)
    } catch (err) {
      if (seq !== loadSeqRef.current) return
      afterRenderRef.current = null
      setError(bufferErrorDetail(err, "Couldn't load the document."))
      setLoading(false)
    }
  }, [projectId])

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
        versionRef.current = res.data.version
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
  }, [projectId, reloadDocument])

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
    const f = iframe.getBoundingClientRect()
    const b = box.getBoundingClientRect()
    const top = f.top + r.bottom - b.top + 8
    if (top < 0 || top > b.height - 36) {
      setAsk(null)
      return
    }
    const left = Math.min(Math.max(f.left + r.left + r.width / 2 - b.left, 64), b.width - 64)
    setAsk({
      top,
      left,
      text,
      blockIds: blocks.map((p) => p.getAttribute(BLOCK_ATTR) as string),
    })
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
        if (type.startsWith("format")) {
          e.preventDefault()
          return
        }
        const startP = blockParagraphOf(range.startContainer)
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
        const text = (e.clipboardData?.getData("text/plain") ?? "").replace(/\s*\r?\n\s*/g, " ")
        if (text) idoc.execCommand("insertText", false, text)
      })
      idoc.addEventListener("dragstart", (e) => e.preventDefault())
      idoc.addEventListener("drop", (e) => e.preventDefault())

      idoc.addEventListener("selectionchange", updateAsk)
      idoc.addEventListener("keydown", (e: KeyboardEvent) => {
        if (e.key === "Escape") setChatOpen(false)
      })
    },
    [scheduleSave, updateAsk],
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

        observer = new ResizeObserver(() => {
          applyZoom()
          fitHeight()
        })
        observer.observe(host)
        mutations = new MutationObserver(fitHeight)
        mutations.observe(idoc.body, { childList: true, subtree: true, characterData: true })

        iframeRef.current = iframe
        docRef.current = idoc
        setAsk(null)
        setLoading(false)
        setRenderTick((t) => t + 1)
        const after = afterRenderRef.current
        afterRenderRef.current = null
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
  }, [docxBuffer, wireDocument])

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
      versionRef.current = res.data.version
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
      versionRef.current = res.data.version
      await reloadDocument()
    } catch (err) {
      setNotice(statusOf(err) === 404 ? "Nothing to undo." : apiErrorDetail(err, "Couldn't undo."))
    } finally {
      setBusy(null)
      setEditable(true)
    }
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

  return (
    <div className="flex gap-3 h-full" style={{ minHeight: 0 }}>
      <div
        className="rounded-2xl overflow-hidden flex flex-col flex-1 min-w-0"
        style={{ background: "#e8dfc7", border: "1px solid #e7ddc5", minHeight: 0 }}
      >
        <div
          className="px-4 py-2 flex items-center justify-between gap-2 text-[11px] font-semibold tracking-[0.14em]"
          style={{ color: "#9a9178", background: "#faf5ee", borderBottom: "1px solid #f1e8d1" }}
        >
          <span>TRANSLATION</span>
          <div className="flex items-center gap-2">
            {saveLabel && (
              <span
                role="status"
                className="text-[10px] font-medium tracking-[0.06em] truncate max-w-[220px]"
                style={{ color: saveState === "error" ? "#a14e2e" : saveState === "saved" ? "#2d6a4f" : "#0a7870" }}
              >
                {saveLabel}
              </span>
            )}
            {saveState === "error" && (
              <button
                type="button"
                onClick={() => void flushEdits()}
                className="text-[10px] font-semibold tracking-[0.06em] px-2 py-1 rounded-md"
                style={{ background: "#ffffff", color: "#a14e2e", border: "1px solid #f2d4cf" }}
              >
                Retry
              </button>
            )}
            <button
              type="button"
              onClick={() => void undo()}
              disabled={busy !== null || !hasDocument}
              aria-label="Undo last change"
              title="Undo last change"
              className="text-[10px] font-semibold tracking-[0.08em] px-2 py-1 rounded-md transition disabled:opacity-50"
              style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
            >
              {busy === "undo" ? "Undoing…" : "Undo"}
            </button>
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => openChat(ask ? { blockIds: ask.blockIds, text: ask.text } : null)}
              disabled={!hasDocument}
              aria-label={ask ? "Ask AI about the selection" : "Ask AI about the whole document"}
              className="text-[10px] font-semibold tracking-[0.08em] px-2 py-1 rounded-md transition disabled:opacity-50"
              style={{ background: "#0a7870", color: "#ffffff", border: "1px solid #0a7870" }}
            >
              Ask AI
            </button>
          </div>
        </div>

        <div ref={frameBoxRef} className="relative flex-1" style={{ minHeight: 0 }}>
          <div
            ref={scrollRef}
            onScroll={updateAsk}
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
            <div ref={hostRef} className="relative" style={{ width: "100%" }} />
          </div>

          {notice && (
            <div
              role="status"
              className="absolute left-1/2 top-3 -translate-x-1/2 text-[12px] rounded-full px-3 py-1.5 shadow-sm"
              style={{ background: "#1f2a2e", color: "#ffffff", maxWidth: "90%" }}
            >
              {notice}
            </div>
          )}

          {busy && (
            <div
              className="absolute right-3 bottom-3 text-[11px] rounded-full px-3 py-1.5"
              style={{ background: "#ffffff", color: "#0a5e58", border: "1px solid #cfe6e2" }}
            >
              {busy === "chat" ? "Editing…" : "Undoing…"}
            </div>
          )}

          {ask && !busy && (
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => openChat({ blockIds: ask.blockIds, text: ask.text })}
              className="absolute -translate-x-1/2 text-[12px] font-semibold px-3 py-1.5 rounded-full shadow-md"
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
          className="rounded-2xl overflow-hidden flex flex-col shrink-0"
          style={{ width: 360, background: "#ffffff", border: "1px solid #e7ddc5", minHeight: 0 }}
        >
          <div
            className="px-4 py-2 flex items-center justify-between text-[11px] font-semibold tracking-[0.14em]"
            style={{ color: "#9a9178", background: "#faf5ee", borderBottom: "1px solid #f1e8d1" }}
          >
            <span>CLAUDE</span>
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
    </div>
  )
}
