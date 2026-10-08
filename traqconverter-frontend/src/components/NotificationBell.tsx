"use client"

import { KeyboardEvent as ReactKeyboardEvent, ReactNode, useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"

type Kind =
  | "assigned"
  | "translation_done"
  | "translation_failed"
  | "client_paid"
  | "client_claimed_paid"
  | "client_downloaded"
  | "files_expiring"

type Notification = {
  id: string
  kind: Kind
  title: string
  body: string
  link: string | null
  created_at: string
  read_at: string | null
}

const POLL_MS = 60_000

const svg = (children: ReactNode) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
)

const KIND_STYLE: Record<Kind, { icon: ReactNode; bg: string; fg: string }> = {
  assigned: {
    icon: svg(<><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.5-3.5 3.3-5.5 6.5-5.5s6 2 6.5 5.5" /><path d="M19 8v6M16 11h6" /></>),
    bg: "#e6f2f0",
    fg: "#0a7870",
  },
  translation_done: {
    icon: svg(<path d="m5 12.5 4.5 4.5L19 7.5" />),
    bg: "#e6f2f0",
    fg: "#0a7870",
  },
  translation_failed: {
    icon: svg(<><circle cx="12" cy="12" r="9" /><path d="M12 7.5v5.5M12 16.5h.01" /></>),
    bg: "#fbe9e4",
    fg: "#b4432f",
  },
  client_paid: {
    icon: svg(<><circle cx="12" cy="12" r="9" /><path d="M15.5 8.5a4 4 0 1 0 0 7M7 11h6M7 13.5h6" /></>),
    bg: "#e5f3e8",
    fg: "#2f7d46",
  },
  client_claimed_paid: {
    icon: svg(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>),
    bg: "#fbf0dc",
    fg: "#a86f0e",
  },
  client_downloaded: {
    icon: svg(<><path d="M12 4v11M7 10.5l5 5 5-5" /><path d="M5 20h14" /></>),
    bg: "#eaeef7",
    fg: "#3c5a99",
  },
  files_expiring: {
    icon: svg(<><path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13" /></>),
    bg: "#fbf0dc",
    fg: "#a86f0e",
  },
}

export function relativeTime(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (s < 60) return "just now"
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} h ago`
  const d = Math.round(h / 24)
  if (d === 1) return "yesterday"
  if (d < 7) return `${d} days ago`
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" })
}

export default function NotificationBell() {
  const router = useRouter()
  const [items, setItems] = useState<Notification[]>([])
  const [unread, setUnread] = useState(0)
  const [loaded, setLoaded] = useState(false)
  const [open, setOpen] = useState(false)
  const [now, setNow] = useState(0)
  const wrapRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    try {
      const res = await api.get("/notifications", { params: { limit: 20 } })
      setItems(Array.isArray(res.data?.items) ? res.data.items : [])
      setUnread(Number(res.data?.unread_count) || 0)
      setNow(Date.now())
      setLoaded(true)
    } catch {
      // Keep what's shown; the next poll tries again.
    }
  }, [])

  useEffect(() => {
    const visible = () => document.visibilityState === "visible"
    const tick = () => {
      if (visible()) load()
    }
    tick()
    const timer = window.setInterval(tick, POLL_MS)
    window.addEventListener("focus", tick)
    document.addEventListener("visibilitychange", tick)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener("focus", tick)
      document.removeEventListener("visibilitychange", tick)
    }
  }, [load])

  const close = useCallback((refocus: boolean) => {
    setOpen(false)
    if (refocus) buttonRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) close(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation()
        close(true)
      }
    }
    document.addEventListener("pointerdown", onPointer)
    document.addEventListener("keydown", onKey)
    panelRef.current?.focus()
    return () => {
      document.removeEventListener("pointerdown", onPointer)
      document.removeEventListener("keydown", onKey)
    }
  }, [open, close])

  const toggle = () => {
    if (open) {
      close(false)
      return
    }
    setNow(Date.now())
    setOpen(true)
    load()
  }

  const markRead = (n: Notification) => {
    if (n.read_at) return
    const stamp = new Date().toISOString()
    setItems((list) => list.map((x) => (x.id === n.id ? { ...x, read_at: stamp } : x)))
    setUnread((c) => Math.max(0, c - 1))
    api.post(`/notifications/${n.id}/read`).catch(() => load())
  }

  const openItem = (n: Notification) => {
    markRead(n)
    setOpen(false)
    if (n.link && n.link.startsWith("/")) router.push(n.link)
  }

  const markAll = () => {
    const stamp = new Date().toISOString()
    setItems((list) => list.map((x) => (x.read_at ? x : { ...x, read_at: stamp })))
    setUnread(0)
    api.post("/notifications/read-all").catch(() => load())
  }

  const onListKey = (e: ReactKeyboardEvent<HTMLUListElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return
    const buttons = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>("button[data-item]"))
    if (!buttons.length) return
    e.preventDefault()
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement)
    const next = e.key === "ArrowDown" ? (at + 1) % buttons.length : (at - 1 + buttons.length) % buttons.length
    buttons[at === -1 && e.key === "ArrowUp" ? buttons.length - 1 : next].focus()
  }

  const badge = unread > 9 ? "9+" : String(unread)

  return (
    <div ref={wrapRef} className="sm:relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={toggle}
        className="relative w-10 h-10 rounded-full flex items-center justify-center transition"
        style={{
          background: open ? "#f3ecdb" : "#ffffff",
          border: "1px solid #e7ddc5",
          color: open ? "#0a7870" : "#6b6558",
        }}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="notification-panel"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10 21a2 2 0 0 0 4 0"/></svg>
        {unread > 0 && (
          <span
            className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-semibold leading-[18px] text-center"
            style={{ background: "#d2412f", color: "#ffffff", boxShadow: "0 0 0 2px #faf5ee" }}
            aria-hidden="true"
          >
            {badge}
          </span>
        )}
      </button>

      {open && (
        <div
          id="notification-panel"
          ref={panelRef}
          role="dialog"
          aria-label="Notifications"
          tabIndex={-1}
          className="fixed left-0 right-0 top-[64px] z-50 mx-2 sm:mx-0 sm:absolute sm:left-auto sm:right-0 sm:top-12 sm:w-[360px] rounded-2xl overflow-hidden outline-none"
          style={{
            background: "#ffffff",
            border: "1px solid #e7ddc5",
            boxShadow: "0 12px 32px rgba(31, 42, 46, 0.14)",
          }}
        >
          <div
            className="flex items-center justify-between px-4 py-3"
            style={{ borderBottom: "1px solid #efe6d2" }}
          >
            <div className="text-sm font-semibold" style={{ color: "#1f2a2e" }}>
              Notifications
            </div>
            <button
              type="button"
              onClick={markAll}
              disabled={unread === 0}
              className="text-[12px] font-medium rounded-full px-2.5 py-1 transition disabled:opacity-40 disabled:cursor-default hover:bg-[#e6f2f0] focus-visible:outline-2 focus-visible:outline-[#0a7870]"
              style={{ color: "#0a7870" }}
            >
              Mark all as read
            </button>
          </div>

          {loaded && items.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <div
                className="mx-auto mb-3 w-10 h-10 rounded-full flex items-center justify-center"
                style={{ background: "#e6f2f0", color: "#0a7870" }}
              >
                {KIND_STYLE.translation_done.icon}
              </div>
              <div className="text-sm font-medium" style={{ color: "#1f2a2e" }}>
                You&apos;re all caught up
              </div>
            </div>
          ) : (
            <ul className="max-h-[min(70vh,440px)] overflow-y-auto py-1" onKeyDown={onListKey}>
              {items.map((n) => {
                const style = KIND_STYLE[n.kind] ?? KIND_STYLE.translation_done
                const isUnread = !n.read_at
                return (
                  <li key={n.id}>
                    <button
                      type="button"
                      data-item
                      onClick={() => openItem(n)}
                      className="w-full flex items-start gap-3 px-4 py-3 text-left transition hover:bg-[#f7f1e4] focus-visible:bg-[#f7f1e4] outline-none"
                      style={{ background: isUnread ? "#f2f8f6" : undefined }}
                    >
                      <span
                        className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center"
                        style={{ background: style.bg, color: style.fg }}
                      >
                        {style.icon}
                      </span>
                      <span className="flex-1 min-w-0">
                        <span
                          className="block text-[13px] leading-snug"
                          style={{ color: "#1f2a2e", fontWeight: isUnread ? 600 : 500 }}
                        >
                          {n.title}
                        </span>
                        {n.body && (
                          <span className="block text-[12px] truncate mt-0.5" style={{ color: "#6b6558" }}>
                            {n.body}
                          </span>
                        )}
                        <span className="block text-[11px] mt-1" style={{ color: "#9a9178" }}>
                          {relativeTime(n.created_at, now)}
                        </span>
                      </span>
                      {isUnread && (
                        <span
                          className="shrink-0 mt-1.5 w-2 h-2 rounded-full"
                          style={{ background: "#0a7870" }}
                        >
                          <span className="sr-only">Unread</span>
                        </span>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
