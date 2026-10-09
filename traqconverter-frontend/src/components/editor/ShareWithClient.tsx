"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { api, apiErrorDetail } from "@/lib/api"
import { PAYMENT_STYLE, amountText, money, paymentLabel, shortDate, type ProjectPaymentState } from "@/lib/payment"

type LinkKind = "delivery_pdf" | "pdf" | "docx"

type PaymentStatus = "awaiting" | "claimed" | "unlocked" | "paid"

type DeliveryLink = {
  id: string
  kind: LinkKind
  file_name: string
  token_prefix: string
  // Full link to copy again; null for links made before links were kept, and for revoked ones.
  url: string | null
  status: "active" | "expired" | "revoked"
  expires_at: string
  created_at: string
  download_count: number
  last_downloaded_at: string | null
  protected: boolean
  amount: number | null
  currency: string
  payment_status: PaymentStatus | null
  paid_claimed_at: string | null
  unlocked_at: string | null
  // Owner, admin or PM only.
  can_unlock?: boolean
  paid_at: string | null
  // The team member who marked it as paid by hand.
  marked_paid_by: string | null
}

type Payments = { paypal_me: string | null; stripe_status?: string | null }

const KINDS: { value: LinkKind; label: string }[] = [
  { value: "delivery_pdf", label: "Delivery PDF (translation + certification + original)" },
  { value: "pdf", label: "PDF (translation + certification)" },
  { value: "docx", label: "DOCX" },
]

const EXPIRY = [1, 7, 30] as const

const KIND_SHORT: Record<LinkKind, string> = { delivery_pdf: "Delivery PDF", pdf: "PDF", docx: "DOCX" }

const MAX_AMOUNT = 100000

const STATE: Record<PaymentStatus, ProjectPaymentState> = {
  awaiting: "awaiting",
  claimed: "claimed",
  unlocked: "marked_paid",
  paid: "paid_card",
}

function paymentWhen(l: DeliveryLink) {
  if (l.payment_status === "paid") return shortDate(l.paid_at)
  if (l.payment_status === "unlocked") return shortDate(l.unlocked_at)
  if (l.payment_status === "claimed") return shortDate(l.paid_claimed_at)
  return `Created ${shortDate(l.created_at)}`
}

function parseAmount(raw: string): number | null {
  const value = Number(raw.trim().replace(",", "."))
  if (!raw.trim() || !Number.isFinite(value) || value <= 0 || value > MAX_AMOUNT) return null
  return Math.round(value * 100) / 100
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export default function ShareWithClient({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const [kind, setKind] = useState<LinkKind>("delivery_pdf")
  const [days, setDays] = useState<(typeof EXPIRY)[number]>(7)
  const [creating, setCreating] = useState(false)
  const [url, setUrl] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [copiedLinkId, setCopiedLinkId] = useState<string | null>(null)
  const [links, setLinks] = useState<DeliveryLink[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [revoking, setRevoking] = useState<string | null>(null)
  const [isProtected, setIsProtected] = useState(false)
  const [amount, setAmount] = useState("")
  const [payments, setPayments] = useState<Payments | null>(null)
  const [confirmUnlock, setConfirmUnlock] = useState<string | null>(null)
  const [unlocking, setUnlocking] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await api.get<DeliveryLink[]>(`/projects/${projectId}/delivery-links`)
      setLinks(res.data)
    } catch {
      setLinks([])
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    api
      .get<Payments>("/settings/payments")
      .then((res) => setPayments(res.data))
      .catch(() => setPayments({ paypal_me: null }))
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  const handle = payments?.paypal_me || null
  const stripeActive = payments?.stripe_status === "active"
  const canTakePayment = stripeActive || !!handle
  const parsedAmount = parseAmount(amount)
  const amountInvalid = !!amount.trim() && parsedAmount == null
  const ready = !isProtected || parsedAmount != null

  const toggleProtected = () => {
    const next = !isProtected
    setIsProtected(next)
    setError(null)
    if (next) {
      // A protected preview is made from the delivery PDF, and the client needs time to pay.
      setKind("delivery_pdf")
      setDays(30)
    }
  }

  const create = async () => {
    setCreating(true)
    setError(null)
    setUrl(null)
    setCopied(false)
    try {
      const res = await api.post<{ url: string }>(`/projects/${projectId}/delivery-links`, {
        kind,
        expires_in_days: days,
        ...(isProtected ? { protected: true, amount: parsedAmount } : {}),
      })
      setUrl(res.data.url)
      setCopied(await copyText(res.data.url))
      void load()
    } catch (err) {
      setError(apiErrorDetail(err, "Couldn't create the link."))
    } finally {
      setCreating(false)
    }
  }

  const unlock = async (id: string) => {
    setUnlocking(id)
    setError(null)
    try {
      await api.post(`/projects/${projectId}/delivery-links/${id}/unlock`)
      setConfirmUnlock(null)
      await load()
    } catch (err) {
      setError(apiErrorDetail(err, "Couldn't mark it as paid."))
    } finally {
      setUnlocking(null)
    }
  }

  const revoke = async (id: string) => {
    setRevoking(id)
    setError(null)
    try {
      await api.delete(`/projects/${projectId}/delivery-links/${id}`)
      await load()
    } catch (err) {
      setError(apiErrorDetail(err, "Couldn't revoke the link."))
    } finally {
      setRevoking(null)
    }
  }

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center sm:p-4"
      style={{ background: "rgba(31,42,46,0.45)", backdropFilter: "blur(2px)" }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Share with client"
        onClick={(e) => e.stopPropagation()}
        className="w-full sm:w-[520px] max-h-[90vh] overflow-y-auto rounded-t-2xl sm:rounded-2xl p-5 sm:p-6"
        style={{ background: "#fbf6ea", border: "1px solid #e7ddc5", boxShadow: "0 18px 40px rgba(0,0,0,0.25)" }}
      >
        <div className="flex items-start justify-between gap-3 mb-1">
          <h2 className="text-lg font-semibold" style={{ color: "#1f2a2e" }}>
            Share with client
          </h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-sm font-semibold px-1" style={{ color: "#6b6558" }}>
            ✕
          </button>
        </div>
        <p className="text-[13px] mb-4" style={{ color: "#6b6558" }}>
          Your client gets a download page, no account needed. The file is saved as it is now; later edits don&apos;t change it.
        </p>

        <label className="block text-[12px] font-semibold mb-1" style={{ color: "#4a4638" }} htmlFor="share-kind">
          File
        </label>
        <select
          id="share-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value as LinkKind)}
          disabled={isProtected}
          className="w-full rounded-lg px-3 py-2 text-sm mb-3"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#1f2a2e", opacity: isProtected ? 0.7 : 1 }}
        >
          {KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>

        <div className="text-[12px] font-semibold mb-1" style={{ color: "#4a4638" }}>
          Expires after
        </div>
        <div className="flex gap-2 mb-4" role="radiogroup" aria-label="Expires after">
          {EXPIRY.map((d) => (
            <button
              key={d}
              type="button"
              role="radio"
              aria-checked={days === d}
              onClick={() => setDays(d)}
              className="flex-1 rounded-lg px-3 py-2 text-sm font-semibold transition"
              style={
                days === d
                  ? { background: "#e1efec", color: "#0a5e58", border: "1px solid #0a7870" }
                  : { background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }
              }
            >
              {d === 1 ? "1 day" : `${d} days`}
            </button>
          ))}
        </div>

        <div
          className="rounded-xl p-3 mb-4"
          style={{ background: "#ffffff", border: `1px solid ${isProtected ? "#0a7870" : "#e7ddc5"}` }}
        >
          <button
            type="button"
            role="switch"
            aria-checked={isProtected}
            onClick={toggleProtected}
            className="flex w-full items-center gap-3 text-left"
          >
            <span
              className="relative inline-block w-9 h-5 rounded-full shrink-0 transition"
              style={{ background: isProtected ? "#0a7870" : "#d9d0ba" }}
            >
              <span
                className="absolute top-0.5 w-4 h-4 rounded-full transition-all"
                style={{ background: "#ffffff", left: isProtected ? "18px" : "2px" }}
              />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold" style={{ color: "#1f2a2e" }}>
                Protected until paid
              </span>
              <span className="block text-[12px]" style={{ color: "#8a8270" }}>
                {stripeActive
                  ? "The client sees a watermarked preview until they pay. The link unlocks by itself once Stripe confirms."
                  : "The client sees a watermarked preview and a PayPal button until you mark the link as paid."}
              </span>
            </span>
          </button>

          {isProtected && (
            <div className="mt-3 pt-3" style={{ borderTop: "1px solid #efe6d0" }}>
              <>
                  <label className="block sm:w-1/2">
                    <span className="block text-[12px] font-semibold mb-1" style={{ color: "#4a4638" }}>
                      Amount (€)
                    </span>
                    <input
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      inputMode="decimal"
                      placeholder="45"
                      className="w-full rounded-lg px-3 py-2 text-sm outline-none"
                      style={{
                        background: "#faf5ee",
                        border: `1px solid ${amountInvalid ? "#ecc9c1" : "#e7ddc5"}`,
                        color: "#1f2a2e",
                      }}
                    />
                  </label>
                  <div className="text-[12px] mt-2 break-all" style={{ color: amountInvalid ? "#b14a3a" : "#8a8270" }}>
                    {amountInvalid
                      ? `Enter an amount above 0 and up to ${MAX_AMOUNT}.`
                      : stripeActive
                      ? `Client pays ${parsedAmount != null ? money(parsedAmount, "EUR") : "the amount"} by card, wallet or PayPal on Stripe${handle ? ", or on PayPal.me" : ""}.`
                      : handle
                      ? `Client pays at paypal.me/${handle}/${parsedAmount != null ? amountText(parsedAmount) : "…"}EUR`
                      : "Client pays you directly, e.g. by bank transfer. Mark the link as paid in this list once the money arrives."}
                  </div>
                  {!canTakePayment && payments !== null && (
                    <div className="text-[12px] mt-1" style={{ color: "#8a8270" }}>
                      To take card or PayPal payments, set them up in{" "}
                      <Link href="/settings/account#payments" className="font-semibold underline" style={{ color: "#0a5e58" }}>
                        Settings → Payments
                      </Link>
                      .
                    </div>
                  )}
              </>
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={() => void create()}
          disabled={creating || !ready}
          className="w-full rounded-full px-4 py-2.5 text-sm font-semibold transition"
          style={{
            background: ready ? "#0a7870" : "#9bc9c5",
            color: "#ffffff",
            opacity: creating ? 0.7 : 1,
            cursor: creating || !ready ? "not-allowed" : "pointer",
          }}
        >
          {creating ? "Preparing the file…" : isProtected ? "Create protected link" : "Create link"}
        </button>

        {url && (
          <div className="mt-3 rounded-xl p-3" style={{ background: "#ffffff", border: "1px solid #cfe6e2" }}>
            <div className="flex items-center gap-2">
              <input
                readOnly
                value={url}
                aria-label="Link for your client"
                onFocus={(e) => e.currentTarget.select()}
                className="flex-1 min-w-0 text-[13px] bg-transparent outline-none"
                style={{ color: "#1f2a2e" }}
              />
              <button
                type="button"
                onClick={async () => setCopied(await copyText(url))}
                className="shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold"
                style={{ background: copied ? "#d8ead6" : "#e1efec", color: copied ? "#2d5a24" : "#0a5e58" }}
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <div className="text-[12px] mt-1.5" style={{ color: "#8a8270" }}>
              The full link is shown only now. Revoke it below if it goes to the wrong person.
            </div>
          </div>
        )}

        {error && (
          <div className="text-sm rounded-lg px-3 py-2 mt-3" style={{ background: "#f2d4cf", color: "#7a2f24" }}>
            {error}
          </div>
        )}

        <div className="mt-5">
          <div className="text-[11px] font-semibold tracking-[0.12em] mb-2" style={{ color: "#8a8270" }}>
            LINKS FOR THIS PROJECT
          </div>
          {links === null ? (
            <div className="text-sm" style={{ color: "#8a8270" }}>
              Loading…
            </div>
          ) : links.length === 0 ? (
            <div className="text-sm" style={{ color: "#8a8270" }}>
              No links yet.
            </div>
          ) : (
            <ul className="flex flex-col gap-2">
              {links.map((l) => {
                const claimed = l.payment_status === "claimed" && l.status === "active"
                const canUnlock = l.can_unlock !== false && l.status === "active" && l.protected && l.payment_status !== "unlocked" && l.payment_status !== "paid"
                return (
                  <li
                    key={l.id}
                    className="rounded-xl px-3 py-2"
                    style={{ background: claimed ? "#fdf3dc" : "#ffffff", border: `1px solid ${claimed ? "#e8c46a" : "#efe6d0"}` }}
                  >
                    <div className="flex items-center gap-2 sm:gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold truncate" style={{ color: "#1f2a2e" }}>
                          {KIND_SHORT[l.kind]} <span style={{ color: "#8a8270", fontWeight: 400 }}>· /d/{l.token_prefix}…</span>
                        </div>
                        <div className="text-[12px]" style={{ color: "#8a8270" }}>
                          {l.status === "active"
                            ? `Expires ${shortDate(l.expires_at)}`
                            : l.status === "revoked"
                            ? "Revoked"
                            : `Expired ${shortDate(l.expires_at)}`}
                          {" · "}
                          {l.download_count === 1 ? "1 download" : `${l.download_count} downloads`}
                        </div>
                        {l.url && l.status === "active" && (
                          <div className="flex flex-wrap items-center gap-2 mt-1">
                            <button
                              type="button"
                              onClick={async () => {
                                if (await copyText(l.url!)) {
                                  setCopiedLinkId(l.id)
                                  window.setTimeout(() => setCopiedLinkId((id) => (id === l.id ? null : id)), 2000)
                                }
                              }}
                              className="text-[12px] font-semibold px-2.5 py-0.5 rounded-full"
                              style={{
                                background: copiedLinkId === l.id ? "#d8ead6" : "#e1efec",
                                color: copiedLinkId === l.id ? "#2d5a24" : "#0a5e58",
                              }}
                            >
                              {copiedLinkId === l.id ? "Copied" : "Copy link"}
                            </button>
                            <a
                              href={l.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[12px] font-semibold underline"
                              style={{ color: "#0a5e58" }}
                            >
                              Open
                            </a>
                          </div>
                        )}
                        {l.protected && l.payment_status && (
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1">
                            <span
                              className="inline-flex items-center text-[11px] font-semibold px-2 py-0.5 rounded-full"
                              style={{
                                background: PAYMENT_STYLE[STATE[l.payment_status]].background,
                                color: PAYMENT_STYLE[STATE[l.payment_status]].color,
                              }}
                            >
                              {paymentLabel(STATE[l.payment_status], l.marked_paid_by)}
                            </span>
                            <span className="text-[12px]" style={{ color: "#8a8270" }}>
                              {[money(l.amount, l.currency), paymentWhen(l)].filter(Boolean).join(" · ")}
                            </span>
                          </div>
                        )}
                      </div>
                      {canUnlock && confirmUnlock !== l.id && (
                        <button
                          type="button"
                          onClick={() => setConfirmUnlock(l.id)}
                          className="shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold"
                          style={{ background: "#0a7870", color: "#ffffff" }}
                        >
                          Mark as paid
                        </button>
                      )}
                      {l.status === "active" && (
                        <button
                          type="button"
                          onClick={() => void revoke(l.id)}
                          disabled={revoking === l.id}
                          className="shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold"
                          style={{ background: "#ffffff", color: "#b14a3a", border: "1px solid #ecc9c1" }}
                        >
                          {revoking === l.id ? "Revoking…" : "Revoke"}
                        </button>
                      )}
                    </div>
                    {confirmUnlock === l.id && (
                      <div className="mt-2 rounded-lg p-2.5" style={{ background: "#e1efec", border: "1px solid #cfe6e2" }}>
                        <div className="text-[13px] mb-2" style={{ color: "#1f2a2e" }}>
                          Check that the money has arrived first. Marking it as paid releases the document: the client can download the clean file from the same link straight away.
                        </div>
                        <div className="flex gap-2 justify-end">
                          <button
                            type="button"
                            onClick={() => setConfirmUnlock(null)}
                            className="rounded-full px-3 py-1.5 text-xs font-semibold"
                            style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
                          >
                            Cancel
                          </button>
                          <button
                            type="button"
                            onClick={() => void unlock(l.id)}
                            disabled={unlocking === l.id}
                            className="rounded-full px-3 py-1.5 text-xs font-semibold"
                            style={{ background: "#0a7870", color: "#ffffff", opacity: unlocking === l.id ? 0.7 : 1 }}
                          >
                            {unlocking === l.id ? "Marking as paid…" : "Yes, mark as paid and release"}
                          </button>
                        </div>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
