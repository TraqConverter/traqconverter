"use client"

import * as React from "react"

// ============================================================
// ICONS USED ACROSS THE EDITOR
// ============================================================

export const IconBell = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
    <path d="M10 21a2 2 0 0 0 4 0" />
  </svg>
)

export const IconExport = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 4v12" />
    <path d="m7 15 5 5 5-5" />
    <path d="M4 20h16" />
  </svg>
)

export const IconCertify = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3 4 6v6c0 5 3.4 8.4 8 9 4.6-.6 8-4 8-9V6Z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
)

export const IconKeyboard = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2.5" y="6" width="19" height="12" rx="2" />
    <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8" />
  </svg>
)

export const IconCheck = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4a8a3a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="m5 12 5 5 10-10" />
  </svg>
)

export const IconWarn = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#b06a2a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3 2 20h20Z" />
    <path d="M12 10v5M12 18h.01" />
  </svg>
)

export const IconComment = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12Z" />
  </svg>
)

export const IconDB = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <ellipse cx="12" cy="6" rx="8" ry="3" />
    <path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
    <path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
  </svg>
)

export const IconBolt = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="#b06a2a" stroke="#b06a2a" strokeWidth="1" strokeLinejoin="round">
    <path d="M13 3 4 14h6l-1 7 9-11h-6Z" />
  </svg>
)

export function LangChip({ code, active }: { code: string; active?: boolean }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-mono"
      style={{
        background: active ? "#e1efec" : "#f3ecdb",
        color: active ? "#0a5e58" : "#6b6558",
        border: `1px solid ${active ? "#cfe6e2" : "#e7ddc5"}`,
      }}
    >
      {active && (
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: "#0a7870" }}
        />
      )}
      {code}
    </span>
  )
}

function hashHue(s: string) {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h % 360
}

export function Avatar({
  initials,
  size = 28,
}: {
  initials: string
  size?: number
}) {
  const hue = hashHue(initials)
  return (
    <div
      className="rounded-full flex items-center justify-center font-semibold"
      style={{
        width: size,
        height: size,
        background: `hsl(${hue} 40% 82%)`,
        color: `hsl(${hue} 45% 28%)`,
        fontSize: size * 0.38,
        border: "2px solid #fff",
      }}
    >
      {initials}
    </div>
  )
}
