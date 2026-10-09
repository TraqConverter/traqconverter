"use client"

import { useEffect, useState, useSyncExternalStore } from "react"
import { useParams } from "next/navigation"
import { apiBaseUrl } from "@/lib/api"
import { BrandMark } from "@/components/brand/Logo"

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
  paid_claimed?: boolean
  preview_pages?: number
  original_pages?: number
  paypal_url?: string | null
  card_payment?: boolean
}

type State = { phase: "loading" } | { phase: "ready"; info: Info } | { phase: "gone"; info: Info } | { phase: "missing" } | { phase: "error"; message: string }

// While the client waits for the unlock, the page checks back this often.
const UNLOCK_POLL_MS = 30_000
// Back from Stripe Checkout, the webhook usually lands within seconds.
const PAID_POLL_MS = 3_000
const PAID_POLL_TRIES = 20

const noSubscription = () => () => {}

function returnedFromCheckout() {
  return new URLSearchParams(window.location.search).get("paid") === "1"
}

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

type Confirming = "no" | "checking" | "slow"

function LockedPreview({
  token,
  info,
  confirming,
  onClaimed,
}: {
  token: string
  info: Info
  confirming: Confirming
  onClaimed: () => void
}) {
  const [claiming, setClaiming] = useState(false)
  const [claimError, setClaimError] = useState("")
  const [paying, setPaying] = useState(false)
  const [payError, setPayError] = useState("")
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

  const pay = async () => {
    setPaying(true)
    setPayError("")
    try {
      const res = await fetch(publicUrl(token, "/checkout"), { method: "POST", credentials: "omit", cache: "no-store" })
      if (res.ok) {
        const { checkout_url } = (await res.json()) as { checkout_url: string }
        window.location.href = checkout_url
        return
      }
      setPayError(
        res.status === 429
          ? "Too many attempts. Try again in a few minutes."
          : res.status === 409
          ? "Online payment isn't available for this link any more. Reload the page."
          : "Payment couldn't start. Try again in a moment.",
      )
    } catch {
      setPayError("Payment couldn't start. Check your connection and try again.")
    }
    setPaying(false)
  }

  const card = !!info.card_payment
  const showClaim = !!info.paypal_url || !card

  return (
    <>
      <FileHeading info={info} subtitle={amount ? `Amount due: ${amount}` : ""} />

      <p className="text-[13px] mb-4" style={{ color: "#6b6558" }}>
        This is a protected preview. The complete, unwatermarked document becomes available here once payment is confirmed.
      </p>

      {confirming !== "no" ? (
        <div className="rounded-xl px-4 py-3 text-sm text-center" style={{ background: "#e1efec", color: "#0a5e58" }}>
          {confirming === "checking"
            ? "Payment received, unlocking…"
            : "Payment received. Stripe is still confirming it; this page updates by itself when it's done."}
        </div>
      ) : info.paid_claimed ? (
        <div className="rounded-xl px-4 py-3 text-sm text-center" style={{ background: "#e1efec", color: "#0a5e58" }}>
          Thanks — the translator will unlock your document shortly.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {card && (
            <>
              <button
                type="button"
                onClick={() => void pay()}
                disabled={paying}
                className="flex items-center justify-center w-full rounded-full px-5 py-3 text-[15px] font-semibold"
                style={{ background: "#0a7870", color: "#ffffff", opacity: paying ? 0.7 : 1 }}
              >
                {paying ? "Opening secure payment…" : `Pay ${amount}`}
              </button>
              <div className="text-[12px] text-center" style={{ color: "#8a8270" }}>
                Card, Apple Pay, Google Pay and more, on Stripe. The document unlocks as soon as the payment goes through.
              </div>
            </>
          )}
          {payError && (
            <div className="text-[13px] text-center" style={{ color: "#7a2f24" }}>
              {payError}
            </div>
          )}
          {info.paypal_url ? (
            <>
            <a
              href={info.paypal_url}
              target="_blank"
              rel="noopener noreferrer"
              className={`flex items-center justify-center w-full rounded-full px-5 font-semibold ${card ? "py-2.5 text-sm mt-1" : "py-3 text-[15px]"}`}
              style={card ? { background: "#ffffff", color: "#0a5e58", border: "1px solid #0a7870" } : { background: "#0a7870", color: "#ffffff" }}
            >
              {card ? "Or pay with PayPal.me" : `Pay ${amount} with PayPal`}
            </a>
            <div className="text-[13px] text-center" style={{ color: "#6b6558" }}>
              If PayPal asks for the amount, enter {amount}.
            </div>
            </>
          ) : (
            !card && (
              <div className="text-sm text-center" style={{ color: "#6b6558" }}>
                {info.company ? `Contact ${info.company} to pay ${amount}.` : `Contact the translator to pay ${amount}.`}
              </div>
            )
          )}
          {showClaim && (
            <button
              type="button"
              onClick={() => void claim()}
              disabled={claiming}
              className="w-full rounded-full px-5 py-2.5 text-sm font-semibold"
              style={{ background: "#ffffff", color: "#0a5e58", border: "1px solid #0a7870", opacity: claiming ? 0.7 : 1 }}
            >
              {claiming ? "Sending…" : card ? "I've paid on PayPal" : "I've paid"}
            </button>
          )}
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
            <PreviewPage key={n} src={publicUrl(token, `/preview/${n}`)} n={n} total={pages.length} />
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

  const paidReturn = useSyncExternalStore(noSubscription, returnedFromCheckout, () => false)
  const [paidPollDone, setPaidPollDone] = useState(false)
  const locked = state.phase === "ready" && !!state.info.locked

  // Back from Stripe: check every few seconds until the webhook unlocks the link, then drop ?paid=1.
  useEffect(() => {
    if (!paidReturn) return
    if (state.phase === "ready" && !locked) {
      window.history.replaceState(null, "", window.location.pathname)
      return
    }
    if (!locked || paidPollDone) return
    let tries = 0
    const timer = window.setInterval(() => {
      tries += 1
      if (tries >= PAID_POLL_TRIES) {
        window.clearInterval(timer)
        setPaidPollDone(true)
      }
      void loadInfo(token).then((s) => {
        if (s.phase === "ready" || s.phase === "gone") setState(s)
      })
    }, PAID_POLL_MS)
    return () => window.clearInterval(timer)
  }, [paidReturn, paidPollDone, locked, state.phase, token])

  const confirming: Confirming = paidReturn && locked ? (paidPollDone ? "slow" : "checking") : "no"
  const waitingForUnlock = locked && ((state.phase === "ready" && !!state.info.paid_claimed) || confirming === "slow")

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
                confirming={confirming}
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
      <div className="text-[11px] mt-6 flex items-center gap-2" style={{ color: "#b5ab93" }}>
        <BrandMark size={16} />
        Delivered with OnlineDocTranslator
      </div>
    </main>
  )
}

// A page-sized placeholder with a spinner until the image arrives; the first view can take a few seconds to render.
function PreviewPage({ src, n, total }: { src: string; n: number; total: number }) {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")
  const [attempt, setAttempt] = useState(0)
  return (
    <div
      className="relative w-full rounded-lg overflow-hidden"
      style={{ border: "1px solid #e7ddc5", background: "#ffffff", aspectRatio: status === "ready" ? undefined : "1 / 1.414" }}
    >
      {status !== "ready" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center" style={{ background: "#faf5ee" }}>
          {status === "loading" ? (
            <>
              <span
                className="inline-block h-8 w-8 rounded-full animate-spin"
                style={{ border: "3px solid #d9ecea", borderTopColor: "#0a7870" }}
                aria-hidden
              />
              <div className="text-sm font-semibold" style={{ color: "#0a5e58" }}>
                Preparing your preview…
              </div>
              <div className="text-[12px]" style={{ color: "#8a8270" }}>
                Page {n} of {total}. This can take a few seconds.
              </div>
            </>
          ) : (
            <>
              <div className="text-sm" style={{ color: "#7a2f24" }}>
                Page {n} didn&apos;t load.
              </div>
              <button
                type="button"
                onClick={() => {
                  setStatus("loading")
                  setAttempt((a) => a + 1)
                }}
                className="rounded-full px-4 py-1.5 text-sm font-semibold"
                style={{ background: "#ffffff", color: "#0a5e58", border: "1px solid #0a7870" }}
              >
                Try again
              </button>
            </>
          )}
        </div>
      )}
      {status !== "error" && (
        // eslint-disable-next-line @next/next/no-img-element -- served by the API with no-store; next/image would cache it.
        <img
          key={attempt}
          src={attempt ? `${src}${src.includes("?") ? "&" : "?"}r=${attempt}` : src}
          alt={`Preview of page ${n}`}
          loading="eager"
          draggable={false}
          onContextMenu={(e) => e.preventDefault()}
          onLoad={() => setStatus("ready")}
          onError={() => setStatus("error")}
          className="w-full h-auto block"
          style={{ opacity: status === "ready" ? 1 : 0 }}
        />
      )}
    </div>
  )
}
