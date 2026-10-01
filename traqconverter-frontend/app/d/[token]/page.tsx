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
  protected?: boolean
  locked?: boolean
  amount?: number | null
  currency?: string
  client_name?: string | null
  paid_claimed?: boolean
  preview_pages?: number
  original_pages?: number
  paypal_url?: string | null
}

type State = { phase: "loading" } | { phase: "ready"; info: Info } | { phase: "gone"; info: Info } | { phase: "missing" } | { phase: "error"; message: string }

// While the client waits for the unlock, the page checks back this often.
const UNLOCK_POLL_MS = 30_000

function formatSize(bytes?: number | null) {
  if (!bytes) return ""
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatExpiry(iso?: string) {
  if (!iso) return ""
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" })
}

function formatAmount(amount?: number | null, currency = "EUR") {
  if (amount == null) return ""
  const text = Number.isInteger(amount) ? String(amount) : amount.toFixed(2)
  const symbol = { EUR: "€", GBP: "£", USD: "$" }[currency]
  return symbol ? `${symbol}${text}` : `${text} ${currency}`
}

function publicUrl(token: string, path = "") {
  return `${apiBaseUrl()}/public/delivery/${encodeURIComponent(token)}${path}`
}

// Plain fetch on purpose: this page has no login, so the app's API client (which sends a 401 to /login) is not used.
async function loadInfo(token: string): Promise<State> {
  try {
    const res = await fetch(publicUrl(token), { credentials: "omit", cache: "no-store" })
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

function FileHeading({ info, subtitle }: { info: Info; subtitle: string }) {
  return (
    <div className="flex items-start gap-3 mb-5">
      <div className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0" style={{ background: "#e1efec", color: "#0a5e58" }}>
        <FileIcon />
      </div>
      <div className="min-w-0">
        <h1 className="text-lg font-semibold break-words" style={{ color: "#1f2a2e" }}>
          {info.file_name}
        </h1>
        <div className="text-[13px]" style={{ color: "#8a8270" }}>
          {subtitle}
        </div>
      </div>
    </div>
  )
}

function Download({ token, info }: { token: string; info: Info }) {
  return (
    <>
      <FileHeading info={info} subtitle={[info.kind === "docx" ? "Word document" : "PDF", formatSize(info.file_size)].filter(Boolean).join(" · ")} />
      <a
        href={publicUrl(token, "/file")}
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
        Available until {formatExpiry(info.expires_at)}
      </div>
    </>
  )
}

function LockedPreview({ token, info, onClaimed }: { token: string; info: Info; onClaimed: () => void }) {
  const [claiming, setClaiming] = useState(false)
  const [claimError, setClaimError] = useState("")
  const amount = formatAmount(info.amount, info.currency)
  const pages = Array.from({ length: info.preview_pages || 0 }, (_, i) => i + 1)
  const original = info.original_pages || 0

  const claim = async () => {
    setClaiming(true)
    setClaimError("")
    try {
      const res = await fetch(publicUrl(token, "/paid"), { method: "POST", credentials: "omit", cache: "no-store" })
      if (res.status === 429) setClaimError("Too many attempts. Try again later.")
      else if (!res.ok) setClaimError("That didn't go through. Try again in a moment.")
      else onClaimed()
    } catch {
      setClaimError("That didn't go through. Check your connection and try again.")
    } finally {
      setClaiming(false)
    }
  }

  return (
    <>
      <FileHeading info={info} subtitle={[amount && `Amount due: ${amount}`, info.client_name && `for ${info.client_name}`].filter(Boolean).join(" · ")} />

      <p className="text-[13px] mb-4" style={{ color: "#6b6558" }}>
        This is a protected preview. The complete, unwatermarked document becomes available here once payment is confirmed.
      </p>

      {info.paid_claimed ? (
        <div className="rounded-xl px-4 py-3 text-sm text-center" style={{ background: "#e1efec", color: "#0a5e58" }}>
          Thanks — the translator will unlock your document shortly.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {info.paypal_url ? (
            <a
              href={info.paypal_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center w-full rounded-full px-5 py-3 text-[15px] font-semibold"
              style={{ background: "#0a7870", color: "#ffffff" }}
            >
              Pay {amount} with PayPal
            </a>
          ) : (
            <div className="text-sm text-center" style={{ color: "#6b6558" }}>
              {info.company ? `Ask ${info.company} how to pay.` : "Ask the sender how to pay."}
            </div>
          )}
          <button
            type="button"
            onClick={() => void claim()}
            disabled={claiming}
            className="w-full rounded-full px-5 py-2.5 text-sm font-semibold"
            style={{ background: "#ffffff", color: "#0a5e58", border: "1px solid #0a7870", opacity: claiming ? 0.7 : 1 }}
          >
            {claiming ? "Sending…" : "I've paid"}
          </button>
          {claimError && (
            <div className="text-[13px] text-center" style={{ color: "#7a2f24" }}>
              {claimError}
            </div>
          )}
        </div>
      )}

      {pages.length > 0 && (
        <div className="mt-6 flex flex-col gap-3 select-none" style={{ userSelect: "none", WebkitUserSelect: "none" }}>
          {pages.map((n) => (
            // eslint-disable-next-line @next/next/no-img-element -- served by the API with no-store; next/image would cache it.
            <img
              key={n}
              src={publicUrl(token, `/preview/${n}`)}
              alt={`Preview of page ${n}`}
              loading={n > 2 ? "lazy" : "eager"}
              draggable={false}
              onContextMenu={(e) => e.preventDefault()}
              className="w-full h-auto rounded-lg"
              style={{ border: "1px solid #e7ddc5", background: "#ffffff" }}
            />
          ))}
        </div>
      )}
      {original > 0 && (
        <div className="text-[13px] text-center mt-3" style={{ color: "#8a8270" }}>
          + {original === 1 ? "1 page" : `${original} pages`} of the original, included after payment
        </div>
      )}
      <div className="text-[12px] text-center mt-4" style={{ color: "#8a8270" }}>
        Link valid until {formatExpiry(info.expires_at)}
      </div>
    </>
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

  const waitingForUnlock = state.phase === "ready" && !!state.info.locked && !!state.info.paid_claimed

  useEffect(() => {
    if (!waitingForUnlock) return
    const timer = window.setInterval(() => {
      void loadInfo(token).then((s) => {
        if (s.phase === "ready" || s.phase === "gone") setState(s)
      })
    }, UNLOCK_POLL_MS)
    return () => window.clearInterval(timer)
  }, [waitingForUnlock, token])

  const company = state.phase === "ready" || state.phase === "gone" ? state.info.company : ""
  const locked = state.phase === "ready" && !!state.info.locked

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-10" style={{ background: "#faf5ee" }}>
      <div
        className={`w-full ${locked ? "max-w-[680px]" : "max-w-[440px]"} rounded-2xl p-5 sm:p-8`}
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
            {locked ? (
              <LockedPreview
                token={token}
                info={state.info}
                onClaimed={() => setState({ phase: "ready", info: { ...state.info, paid_claimed: true } })}
              />
            ) : (
              <Download token={token} info={state.info} />
            )}
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
