"use client"

import { useState } from "react"

export type LangOption = {
  code: string
  flag: string
  name: string
}

export const SOURCE_LANGUAGES: LangOption[] = [
  { code: "auto", flag: "AUTO", name: "Auto-detect" },

  { code: "en-GB", flag: "GB", name: "English (UK)" },
  { code: "en-US", flag: "US", name: "English (US)" },
  { code: "fr-FR", flag: "FR", name: "French" },
  { code: "es-ES", flag: "ES", name: "Spanish" },
  { code: "pt-PT", flag: "PT", name: "Portuguese" },
  { code: "pt-BR", flag: "BR", name: "Portuguese (Brazil)" },
  { code: "it-IT", flag: "IT", name: "Italian" },
  { code: "de-DE", flag: "DE", name: "German" },
  { code: "nl-NL", flag: "NL", name: "Dutch" },
  { code: "sv-SE", flag: "SE", name: "Swedish" },
  { code: "da-DK", flag: "DK", name: "Danish" },
  { code: "no-NO", flag: "NO", name: "Norwegian" },
  { code: "fi-FI", flag: "FI", name: "Finnish" },
  { code: "pl-PL", flag: "PL", name: "Polish" },
  { code: "cs-CZ", flag: "CZ", name: "Czech" },
  { code: "ro-RO", flag: "RO", name: "Romanian" },
  { code: "hu-HU", flag: "HU", name: "Hungarian" },
  { code: "tr-TR", flag: "TR", name: "Turkish" },
  { code: "vi-VN", flag: "VN", name: "Vietnamese" },
  { code: "id-ID", flag: "ID", name: "Indonesian" },

  { code: "ja-JP", flag: "JP", name: "Japanese" },
  { code: "zh-CN", flag: "CN", name: "Chinese (Simplified)" },
  { code: "zh-TW", flag: "TW", name: "Chinese (Traditional)" },
  { code: "ko-KR", flag: "KR", name: "Korean" },
  { code: "ru-RU", flag: "RU", name: "Russian" },
  { code: "uk-UA", flag: "UA", name: "Ukrainian" },
  { code: "el-GR", flag: "GR", name: "Greek" },
  { code: "ar-SA", flag: "SA", name: "Arabic" },
  { code: "he-IL", flag: "IL", name: "Hebrew" },
  { code: "hi-IN", flag: "IN", name: "Hindi" },
  { code: "th-TH", flag: "TH", name: "Thai" },
]

export const TARGET_LANGUAGES: LangOption[] = SOURCE_LANGUAGES.filter(
  (l) => l.code !== "auto"
)

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
  const list = options || LANGUAGES
  const current = list.find((l) => l.code === value) || list[0]
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
            className="absolute z-10 mt-1 w-full max-h-64 overflow-y-auto rounded-xl"
            style={{
              background: "#fff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 10px 24px rgba(30,30,20,0.08)",
            }}
          >
            {list.map((l) => (
              <button
                key={l.code}
                onClick={() => {
                  onChange(l.code)
                  setOpen(false)
                }}
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
