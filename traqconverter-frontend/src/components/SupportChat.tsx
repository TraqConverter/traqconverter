"use client"

import { FormEvent, KeyboardEvent as ReactKeyboardEvent, useEffect, useRef, useState } from "react"
import { apiBaseUrl } from "@/lib/api"
import { getToken } from "@/lib/auth"
import { COMPANY } from "@/lib/company"

// Dispatch on window to open the panel from anywhere (Settings has a button for it).
export const OPEN_SUPPORT_CHAT = "support:open"

type Turn = { role: "user" | "assistant"; content: string }

// Must match MAX_MESSAGES and MAX_QUESTION_CHARS in backend/app/routers/support.py.
const MAX_MESSAGES = 20
const MAX_QUESTION_CHARS = 1500

const SUGGESTIONS = [
  "How do I get paid before my client can download?",
  "How do I put my stamp on every page?",
  "What does one credit cover?",
  "How do I add my own certification page?",
]

const HelpIcon = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.4" />
    <path d="M12 17h.01" />
  </svg>
)

function errorText(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown })?.detail
  if (typeof detail === "string" && detail) return detail
  if (Array.isArray(detail)) {
    const msg = (detail[0] as { msg?: unknown })?.msg
    if (typeof msg === "string") return msg.replace(/^Value error, /, "")
  }
  if (status === 401) return "Your session has ended. Sign in again to use the Help chat."
  if (status === 429) return "You've asked a lot of questions this hour. Try again later."
  return "The Help chat couldn't answer just now. Please try again."
}

// docked: a header button (the editor has its own floating toolbars); otherwise a floating button, bottom-right.
export default function SupportChat({ docked = false }: { docked?: boolean }) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Turn[]>([])
  const [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const full = messages.length + 1 > MAX_MESSAGES

  useEffect(() => {
    const onOpen = () => setOpen(true)
    window.addEventListener(OPEN_SUPPORT_CHAT, onOpen)
    return () => window.removeEventListener(OPEN_SUPPORT_CHAT, onOpen)
  }, [])

  useEffect(() => {
    if (!open) return
    inputRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open])

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, open, error])

  useEffect(() => () => abortRef.current?.abort(), [])

  const ask = async (question: string) => {
    const q = question.trim()
    if (!q || busy || full) return
    const history: Turn[] = [...messages, { role: "user", content: q }]
    setMessages([...history, { role: "assistant", content: "" }])
    setDraft("")
    setError("")
    setBusy(true)
    const controller = new AbortController()
    abortRef.current = controller
    let answer = ""
    const fail = (message: string) => {
      // Take the question back out, so the history stays question/answer pairs and it can be re-sent.
      setMessages(history.slice(0, -1))
      setDraft(q)
      setError(message)
    }
    try {
      const token = getToken()
      const res = await fetch(`${apiBaseUrl()}/support/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ messages: history }),
        signal: controller.signal,
      })
      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => null)
        fail(errorText(res.status, body))
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        answer += decoder.decode(value, { stream: true })
        const text = answer
        setMessages([...history, { role: "assistant", content: text }])
      }
      answer += decoder.decode()
      if (!answer.trim()) fail(errorText(0, null))
      else setMessages([...history, { role: "assistant", content: answer }])
    } catch (err) {
      if ((err as Error)?.name === "AbortError") return
      if (answer.trim()) setMessages([...history, { role: "assistant", content: answer }])
      else fail("Couldn't reach the Help chat. Check your connection and try again.")
    } finally {
      setBusy(false)
      abortRef.current = null
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void ask(draft)
  }

  const onInputKey = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void ask(draft)
    }
  }

  const restart = () => {
    abortRef.current?.abort()
    setMessages([])
    setError("")
    setDraft("")
    setBusy(false)
  }

  const launcher = docked ? (
    <button
      type="button"
      onClick={() => setOpen((v) => !v)}
      className="w-10 h-10 rounded-full flex items-center justify-center transition shrink-0"
      style={{
        background: open ? "#f3ecdb" : "#ffffff",
        border: "1px solid #e7ddc5",
        color: open ? "#0a7870" : "#6b6558",
      }}
      aria-label="Help"
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-controls="support-chat-panel"
      title="Help"
    >
      {HelpIcon}
    </button>
  ) : (
    <button
      type="button"
      onClick={() => setOpen((v) => !v)}
      className="fixed right-4 bottom-4 sm:right-6 sm:bottom-6 z-40 flex items-center gap-2 pl-3.5 pr-4 h-11 rounded-full text-sm font-semibold transition hover:brightness-110"
      style={{ background: "#0a7870", color: "#ffffff", boxShadow: "0 8px 24px rgba(10, 120, 112, 0.28)" }}
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-controls="support-chat-panel"
    >
      {HelpIcon}
      {open ? "Close" : "Help"}
    </button>
  )

  const panelPosition = docked
    ? "top-[64px] sm:top-[76px] bottom-2 sm:bottom-auto sm:h-[min(560px,calc(100dvh-96px))]"
    : "top-16 bottom-2 sm:top-auto sm:bottom-20 sm:h-[min(560px,calc(100dvh-112px))]"

  return (
    <>
      {launcher}
      {open && (
        <div
          id="support-chat-panel"
          role="dialog"
          aria-label="Help chat"
          className={`fixed z-[60] inset-x-2 sm:inset-x-auto sm:right-6 sm:w-[380px] ${panelPosition} flex flex-col rounded-2xl overflow-hidden`}
          style={{ background: "#ffffff", border: "1px solid #e7ddc5", boxShadow: "0 16px 40px rgba(31, 42, 46, 0.18)" }}
        >
          <div className="flex items-center justify-between px-4 py-3 shrink-0" style={{ background: "#faf5ee", borderBottom: "1px solid #efe6d2" }}>
            <div>
              <div className="text-sm font-semibold" style={{ color: "#1f2a2e" }}>
                Help
              </div>
              <div className="text-[11px]" style={{ color: "#8a8270" }}>
                Answers by AI from our help notes. Can&apos;t see your account.
              </div>
            </div>
            <div className="flex items-center gap-1">
              {messages.length > 0 && (
                <button
                  type="button"
                  onClick={restart}
                  className="text-[12px] font-medium rounded-full px-2.5 py-1 whitespace-nowrap transition hover:bg-[#e6f2f0]"
                  style={{ color: "#0a7870" }}
                >
                  New chat
                </button>
              )}
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="w-8 h-8 rounded-full flex items-center justify-center transition hover:bg-[#f3ecdb]"
                style={{ color: "#6b6558" }}
                aria-label="Close help"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
              </button>
            </div>
          </div>

          <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3" aria-live="polite">
            {messages.length === 0 && (
              <div>
                <p className="text-[13px] leading-relaxed mb-3" style={{ color: "#4a4638" }}>
                  Ask how anything in OnlineDocTranslator works: translating, the editor, certification, client links, credits or your team.
                </p>
                <div className="flex flex-col gap-1.5">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => void ask(s)}
                      className="text-left text-[13px] px-3 py-2 rounded-xl transition hover:bg-[#e6f2f0]"
                      style={{ background: "#faf5ee", border: "1px solid #efe6d2", color: "#0a5e58" }}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
                <div
                  className="max-w-[88%] text-[13px] leading-relaxed px-3 py-2 rounded-2xl whitespace-pre-wrap break-words"
                  style={
                    m.role === "user"
                      ? { background: "#0a7870", color: "#ffffff", borderBottomRightRadius: 6 }
                      : { background: "#faf5ee", color: "#1f2a2e", border: "1px solid #efe6d2", borderBottomLeftRadius: 6 }
                  }
                >
                  {m.content || (busy && i === messages.length - 1 ? <span style={{ color: "#8a8270" }}>Thinking…</span> : "")}
                </div>
              </div>
            ))}
            {error && (
              <div role="alert" className="text-[12px] rounded-lg px-3 py-2" style={{ background: "#f2d4cf", color: "#7a2f24" }}>
                {error}
              </div>
            )}
            {full && (
              <div className="text-[12px] rounded-lg px-3 py-2" style={{ background: "#f3ecdb", color: "#4a4638" }}>
                This chat is full. Start a new chat to ask something else.
              </div>
            )}
          </div>

          <form onSubmit={onSubmit} className="shrink-0 px-3 pt-2 pb-2" style={{ borderTop: "1px solid #efe6d2" }}>
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value.slice(0, MAX_QUESTION_CHARS))}
                onKeyDown={onInputKey}
                rows={2}
                disabled={full}
                placeholder={full ? "Start a new chat" : "Ask a question…"}
                aria-label="Your question"
                className="flex-1 resize-none text-[13px] outline-none px-3 py-2 rounded-xl"
                style={{ background: "#faf5ee", border: "1px solid #e7ddc5", color: "#1f2a2e" }}
              />
              <button
                type="submit"
                disabled={busy || full || !draft.trim()}
                className="h-9 px-4 rounded-full text-[13px] font-semibold transition"
                style={{
                  background: busy || full || !draft.trim() ? "#9bc9c5" : "#0a7870",
                  color: "#ffffff",
                  cursor: busy || full || !draft.trim() ? "not-allowed" : "pointer",
                }}
              >
                {busy ? "…" : "Send"}
              </button>
            </div>
            <div className="mt-2 text-[11px] flex flex-wrap items-center gap-x-1.5" style={{ color: "#8a8270" }}>
              <span>Still stuck? Email {COMPANY.email}</span>
              <a href={`mailto:${COMPANY.email}`} className="font-medium hover:underline" style={{ color: "#0a7870" }}>
                Write to us
              </a>
            </div>
          </form>
        </div>
      )}
    </>
  )
}
