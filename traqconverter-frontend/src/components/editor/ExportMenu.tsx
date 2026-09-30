"use client"

import { useEffect, useRef, useState } from "react"

export type ExportKind = "docx" | "pdf" | "delivery"

const ITEMS: { kind: ExportKind; label: string; hint: string }[] = [
  { kind: "docx", label: "DOCX", hint: "Editable Word file" },
  { kind: "pdf", label: "PDF", hint: "Translation and certification page" },
  { kind: "delivery", label: "Delivery PDF", hint: "Translation + certification + original" },
]

export default function ExportMenu({
  busy,
  onExport,
  onShare,
}: {
  busy: ExportKind | null
  onExport: (kind: ExportKind) => void
  onShare: () => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    window.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDown)
      window.removeEventListener("keydown", onKey)
    }
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={busy !== null}
        aria-haspopup="menu"
        aria-expanded={open}
        className="px-3 py-2 rounded-full text-sm font-semibold flex items-center gap-1.5 transition"
        style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        {busy ? "Preparing…" : "Export"}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-0 sm:left-auto sm:right-0 mt-2 w-64 max-w-[calc(100vw-2rem)] rounded-xl py-1 z-30"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5", boxShadow: "0 8px 24px rgba(30,30,20,0.12)" }}
        >
          {ITEMS.map((item) => (
            <button
              key={item.kind}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false)
                onExport(item.kind)
              }}
              className="w-full text-left px-3 py-2 transition hover:bg-[#faf5ee]"
            >
              <div className="text-sm font-semibold" style={{ color: "#1f2a2e" }}>
                {item.label}
              </div>
              <div className="text-[12px]" style={{ color: "#8a8270" }}>
                {item.hint}
              </div>
            </button>
          ))}
          <div className="my-1 h-px" style={{ background: "#f1e8d1" }} />
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false)
              onShare()
            }}
            className="w-full text-left px-3 py-2 transition hover:bg-[#faf5ee]"
          >
            <div className="text-sm font-semibold" style={{ color: "#0a7870" }}>
              Share with client…
            </div>
            <div className="text-[12px]" style={{ color: "#8a8270" }}>
              A download link, no attachment
            </div>
          </button>
        </div>
      )}
    </div>
  )
}
