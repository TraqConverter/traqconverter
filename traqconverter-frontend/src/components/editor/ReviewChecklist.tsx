"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import type { CheckItem, Checks, Severity } from "./useReview"

const GROUPS: { severity: Severity; label: string; dot: string }[] = [
  { severity: "error", label: "Must fix", dot: "#b14a3a" },
  { severity: "warning", label: "Check", dot: "#c88a1a" },
  { severity: "info", label: "Notes", dot: "#9a9178" },
]

export function checksLabel(checks: Checks | null, checking: boolean) {
  if (!checks) return checking ? "Checking…" : "Checks"
  const issues = checks.counts.error + checks.counts.warning
  if (issues === 0) return "Ready"
  return `${issues} issue${issues === 1 ? "" : "s"}`
}

export function checksTone(checks: Checks | null) {
  if (!checks) return { background: "#ffffff", color: "#6b6558", border: "1px solid #e7ddc5", dot: "#b5ab93" }
  if (checks.counts.error > 0) return { background: "#fbeeea", color: "#8f3a2c", border: "1px solid #efc9c0", dot: "#b14a3a" }
  if (checks.counts.warning > 0) return { background: "#fbf1dc", color: "#7a5a10", border: "1px solid #efd9a8", dot: "#c88a1a" }
  return { background: "#e8f3e6", color: "#2d5a24", border: "1px solid #c9e0c4", dot: "#4a8a3a" }
}

function ago(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 10) return "just now"
  if (s < 60) return `${Math.floor(s)} s ago`
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}

export default function ReviewChecklist({
  checks,
  checking,
  error,
  activeId,
  onPick,
  onDismiss,
  onRecheck,
  onClose,
}: {
  checks: Checks | null
  checking: boolean
  error: string
  activeId: string | null
  onPick: (item: CheckItem) => void
  onDismiss: (item: CheckItem, on: boolean) => void
  onRecheck: () => void
  onClose: () => void
}) {
  const [showDismissed, setShowDismissed] = useState(false)
  const listRef = useRef<HTMLDivElement | null>(null)
  const open = useMemo(() => (checks?.items ?? []).filter((i) => !i.dismissed), [checks])
  const dismissed = useMemo(() => (checks?.items ?? []).filter((i) => i.dismissed), [checks])

  useEffect(() => {
    if (!activeId) return
    listRef.current?.querySelector(`[data-item="${activeId}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [activeId])

  const ready = checks?.ready
  return (
    <div
      className="absolute right-4 top-full mt-1 w-[380px] max-w-[calc(100%-2rem)] rounded-xl z-30 tq-pop text-[12px] font-normal tracking-normal flex flex-col"
      style={{ background: "#ffffff", border: "1px solid #e7ddc5", boxShadow: "0 12px 32px rgba(30,30,20,0.14)", color: "#1f2a2e", maxHeight: "min(70vh, 560px)" }}
      role="dialog"
      aria-label="Ready to certify"
    >
      <div className="px-3 pt-3 pb-2 flex items-start justify-between gap-2" style={{ borderBottom: "1px solid #f1e8d1" }}>
        <div>
          <div className="text-[10px] font-semibold tracking-[0.14em]" style={{ color: "#9a9178" }}>
            READY TO CERTIFY
          </div>
          <div className="text-[13px] font-semibold mt-0.5" style={{ color: ready ? "#2d5a24" : "#1f2a2e" }}>
            {!checks
              ? checking
                ? "Comparing with the original…"
                : error || "Not checked yet"
              : ready
                ? "No open issues"
                : `${checks.counts.error} to fix, ${checks.counts.warning} to check`}
          </div>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="w-6 h-6 rounded-md flex items-center justify-center hover:bg-[#faf5ee]" style={{ color: "#6b6558" }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
            <path d="M6 6l12 12M18 6 6 18" />
          </svg>
        </button>
      </div>

      <div ref={listRef} className="flex-1 overflow-auto px-1.5 py-1.5" style={{ minHeight: 0 }}>
        {checks?.pending && (
          <div className="mx-1.5 my-1 px-2.5 py-2 rounded-lg text-[11px] flex items-center gap-2" style={{ background: "#e3f1ee", color: "#0a5e58" }}>
            <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: "#0a7870" }} />
            Reading the original for hard-to-read areas…
          </div>
        )}
        {checks && open.length === 0 && (
          <div className="px-3 py-6 text-center text-[12px]" style={{ color: "#6b6558" }}>
            Numbers, names, notes and terms match the original.
          </div>
        )}
        {GROUPS.map((g) => {
          const items = open.filter((i) => i.severity === g.severity)
          if (!items.length) return null
          return (
            <section key={g.severity} className="mb-1">
              <div className="px-2.5 pt-2 pb-1 text-[10px] font-semibold tracking-[0.12em] flex items-center gap-1.5" style={{ color: "#9a9178" }}>
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: g.dot }} />
                {g.label.toUpperCase()} · {items.length}
              </div>
              {items.map((item) => (
                <Row key={item.id} item={item} active={item.id === activeId} dot={g.dot} onPick={onPick} onDismiss={onDismiss} />
              ))}
            </section>
          )
        })}
        {dismissed.length > 0 && (
          <div className="px-1 pt-1">
            <button type="button" onClick={() => setShowDismissed((v) => !v)} className="px-1.5 py-1 text-[11px] hover:underline" style={{ color: "#8a8270" }}>
              {showDismissed ? "Hide" : "Show"} {dismissed.length} dismissed
            </button>
            {showDismissed &&
              dismissed.map((item) => (
                <Row key={item.id} item={item} active={item.id === activeId} dot="#cfc6ad" onPick={onPick} onDismiss={onDismiss} />
              ))}
          </div>
        )}
      </div>

      <div className="px-3 py-2 flex items-center justify-between gap-2" style={{ borderTop: "1px solid #f1e8d1" }}>
        <span className="text-[10px]" style={{ color: "#9a9178" }}>
          {checks ? `Checked ${ago(checks.checked_at)} · v${checks.document_version}` : ""}
          <span className="ml-2 hidden sm:inline">[ ] to step through</span>
        </span>
        <button
          type="button"
          onClick={onRecheck}
          disabled={checking}
          className="text-[11px] font-semibold px-2.5 py-1 rounded-md disabled:opacity-50"
          style={{ background: "#0a7870", color: "#ffffff" }}
        >
          {checking ? "Checking…" : "Check again"}
        </button>
      </div>
    </div>
  )
}

function Row({
  item,
  active,
  dot,
  onPick,
  onDismiss,
}: {
  item: CheckItem
  active: boolean
  dot: string
  onPick: (item: CheckItem) => void
  onDismiss: (item: CheckItem, on: boolean) => void
}) {
  const clickable = !!(item.block_id || item.source)
  return (
    <div
      data-item={item.id}
      className="group flex items-start gap-2 rounded-lg px-2.5 py-2 transition-colors"
      style={{ background: active ? "#e3f1ee" : undefined }}
      onMouseEnter={(e) => !active && (e.currentTarget.style.background = "#faf5ee")}
      onMouseLeave={(e) => !active && (e.currentTarget.style.background = "")}
    >
      <span className="w-1.5 h-1.5 rounded-full mt-[5px] shrink-0" style={{ background: dot }} />
      <button
        type="button"
        onClick={() => onPick(item)}
        className="flex-1 min-w-0 text-left leading-snug"
        style={{ color: item.dismissed ? "#9a9178" : "#1f2a2e", cursor: clickable ? "pointer" : "default" }}
      >
        {item.message}
      </button>
      <button
        type="button"
        onClick={() => onDismiss(item, !item.dismissed)}
        className="shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded-md opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
        style={{ color: "#6b6558", border: "1px solid #e7ddc5", background: "#ffffff" }}
        title={item.dismissed ? "Show this issue again" : "Dismiss for this document"}
      >
        {item.dismissed ? "Restore" : "Dismiss"}
      </button>
    </div>
  )
}
