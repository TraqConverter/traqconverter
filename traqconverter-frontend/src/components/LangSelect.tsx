"use client"

import { useState } from "react"

import { SOURCE_LANGUAGES, TARGET_LANGUAGES, type LangOption } from "@/lib/languages"

export { SOURCE_LANGUAGES, TARGET_LANGUAGES, type LangOption }

const LANGUAGES: LangOption[] = SOURCE_LANGUAGES

function IconChevron() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}

export function LangSelect({
  value,
  onChange,
  label,
  options,
}: {
  value: string
  onChange: (v: string) => void
  label: string
  options?: LangOption[]
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const list = options || LANGUAGES
  const current = list.find((l) => l.code === value) || list[0]
  const q = query.trim().toLowerCase()
  const shown = q ? list.filter((l) => l.name.toLowerCase().includes(q) || l.code.toLowerCase().startsWith(q)) : list
  const pick = (code: string) => {
    onChange(code)
    setOpen(false)
    setQuery("")
  }
  return (
    <div>
      <div
        className="text-[11px] font-semibold tracking-[0.14em] mb-3"
        style={{ color: "#9a9178" }}
      >
        {label}
      </div>
      <div className="relative">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="w-full flex items-center justify-between px-4 py-3 rounded-xl transition"
          style={{
            background: "#ffffff",
            border: "1px solid #e7ddc5",
          }}
        >
          <div className="flex items-center gap-3">
            <span
              className="inline-flex items-center justify-center text-[11px] font-semibold rounded"
              style={{
                background: "#f3ecdb",
                color: "#6b6558",
                width: 28,
                height: 20,
                border: "1px solid #e7ddc5",
              }}
            >
              {current.flag}
            </span>
            <div className="text-left leading-tight">
              <div className="text-sm font-medium" style={{ color: "#1f2a2e" }}>
                {current.name}
              </div>
              <div className="text-xs font-mono" style={{ color: "#8a8270" }}>
                {current.code}
              </div>
            </div>
          </div>
          <IconChevron />
        </button>

        {open && (
          <div
            className="absolute z-10 mt-1 w-full max-h-72 overflow-y-auto rounded-xl"
            style={{
              background: "#fff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 10px 24px rgba(30,30,20,0.08)",
            }}
          >
            <div className="sticky top-0 p-2" style={{ background: "#fff", borderBottom: "1px solid #f0e8d6" }}>
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && shown[0]) {
                    e.preventDefault()
                    pick(shown[0].code)
                  } else if (e.key === "Escape") {
                    setOpen(false)
                    setQuery("")
                  }
                }}
                placeholder="Search languages"
                aria-label="Search languages"
                className="w-full px-3 py-2 text-sm rounded-lg outline-none"
                style={{ background: "#faf5ee", border: "1px solid #e7ddc5", color: "#1f2a2e" }}
              />
            </div>
            {shown.length === 0 && (
              <div className="px-4 py-3 text-sm" style={{ color: "#8a8270" }}>
                No language matches &quot;{query}&quot;
              </div>
            )}
            {shown.map((l) => (
              <button
                key={l.code}
                type="button"
                onClick={() => pick(l.code)}
                className="w-full flex items-center gap-3 px-4 py-2.5 text-left transition"
                onMouseEnter={(e) => (e.currentTarget.style.background = "#faf5ee")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <span
                  className="inline-flex items-center justify-center text-[11px] font-semibold rounded"
                  style={{
                    background: "#f3ecdb",
                    color: "#6b6558",
                    width: 28,
                    height: 20,
                    border: "1px solid #e7ddc5",
                  }}
                >
                  {l.flag}
                </span>
                <div className="leading-tight">
                  <div className="text-sm" style={{ color: "#1f2a2e" }}>
                    {l.name}
                  </div>
                  <div className="text-xs font-mono" style={{ color: "#8a8270" }}>
                    {l.code}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
