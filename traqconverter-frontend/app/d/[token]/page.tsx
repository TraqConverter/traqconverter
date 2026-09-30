"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { apiBaseUrl } from "@/lib/api"

type Info = {
  valid: boolean
  status: "active" | "expired" | "revoked"
  company: string
  file_name?: string
  kind?: string
  file_size?: number | null
  expires_at?: string
  detail?: string
}

type State = { phase: "loading" } | { phase: "ready"; info: Info } | { phase: "gone"; info: Info } | { phase: "missing" } | { phase: "error"; message: string }

function formatSize(bytes?: number | null) {
  if (!bytes) return ""
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatExpiry(iso?: string) {
  if (!iso) return ""
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" })
}

// Plain fetch on purpose: this page has no login, so the app's API client (which sends a 401 to /login) is not used.
async function loadInfo(token: string): Promise<State> {
  try {
    const res = await fetch(`${apiBaseUrl()}/public/delivery/${encodeURIComponent(token)}`, {
      credentials: "omit",
      cache: "no-store",
    })
    if (res.status === 404) return { phase: "missing" }
    if (res.status === 429) return { phase: "error", message: "Too many attempts. Wait a minute and reload the page." }
    const info = (await res.json()) as Info
    if (res.status === 410) return { phase: "gone", info }
    if (!res.ok) return { phase: "error", message: "This page couldn't load. Reload to try again." }
    return { phase: "ready", info }
  } catch {
    return { phase: "error", message: "This page couldn't load. Check your connection and reload." }
  }
}

function FileIcon() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6M9 17h4" />
    </svg>
  )
}

export default function DeliveryPage() {
  const params = useParams()
  const token = String(params?.token || "")
  const [state, setState] = useState<State>({ phase: "loading" })

  useEffect(() => {
    let live = true
    void loadInfo(token).then((s) => {
      if (live) setState(s)
    })
    return () => {
      live = false
    }
  }, [token])

  const company = state.phase === "ready" || state.phase === "gone" ? state.info.company : ""

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-10" style={{ background: "#faf5ee" }}>
      <div
        className="w-full max-w-[440px] rounded-2xl p-6 sm:p-8"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5", boxShadow: "0 12px 32px rgba(30,30,20,0.08)" }}
      >
        {state.phase === "loading" && (
          <div className="text-sm text-center py-8" style={{ color: "#8a8270" }}>
            Loading…
          </div>
        )}

        {state.phase === "ready" && (
          <>
            {company && (
              <div className="text-[12px] font-semibold tracking-[0.14em] uppercase mb-5" style={{ color: "#0a7870" }}>
                Prepared by {company}
              </div>
            )}
            <div className="flex items-start gap-3 mb-5">
              <div className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0" style={{ background: "#e1efec", color: "#0a5e58" }}>
                <FileIcon />
              </div>
              <div className="min-w-0">
                <h1 className="text-lg font-semibold break-words" style={{ color: "#1f2a2e" }}>
                  {state.info.file_name}
                </h1>
                <div className="text-[13px]" style={{ color: "#8a8270" }}>
                  {[state.info.kind === "docx" ? "Word document" : "PDF", formatSize(state.info.file_size)].filter(Boolean).join(" · ")}
                </div>
              </div>
            </div>
            <a
              href={`${apiBaseUrl()}/public/delivery/${encodeURIComponent(token)}/file`}
              rel="noreferrer"
              className="flex items-center justify-center gap-2 w-full rounded-full px-5 py-3 text-[15px] font-semibold"
              style={{ background: "#0a7870", color: "#ffffff" }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              Download
            </a>
            <div className="text-[12px] text-center mt-4" style={{ color: "#8a8270" }}>
              Available until {formatExpiry(state.info.expires_at)}
            </div>
          </>
        )}

        {state.phase === "gone" && (
          <div className="text-center py-4">
            <h1 className="text-lg font-semibold mb-2" style={{ color: "#1f2a2e" }}>
              {state.info.status === "revoked" ? "This link was withdrawn" : "This link has expired"}
            </h1>
            <p className="text-sm" style={{ color: "#6b6558" }}>
              {company ? `Ask ${company} to send you a new link.` : "Ask the sender for a new link."}
            </p>
          </div>
        )}

        {state.phase === "missing" && (
          <div className="text-center py-4">
            <h1 className="text-lg font-semibold mb-2" style={{ color: "#1f2a2e" }}>
              Link not found
            </h1>
            <p className="text-sm" style={{ color: "#6b6558" }}>
              Check that you copied the whole link, or ask the sender for a new one.
            </p>
          </div>
        )}

        {state.phase === "error" && (
          <div className="text-sm text-center py-4" style={{ color: "#7a2f24" }}>
            {state.message}
          </div>
        )}
      </div>
      <div className="text-[11px] mt-6" style={{ color: "#b5ab93" }}>
        Delivered with TraqConverter
      </div>
    </main>
  )
}
