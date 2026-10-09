"use client"

import { useEffect, useState } from "react"
import { api, apiErrorDetail } from "@/lib/api"

type StripeStatus = "pending" | "active" | "restricted"

type Payments = {
  paypal_me: string | null
  paypal_url: string | null
  can_edit: boolean
  stripe_status: StripeStatus | null
  stripe_charges_enabled: boolean
  stripe_details_submitted: boolean
  stripe_requirements_due: number
}

const URL_RE = /^(?:https?:\/\/)?(?:www\.)?(?:paypal\.me|paypal\.com\/paypalme)\/([^/?#\s]+)\/?(?:[?#].*)?$/i
const HANDLE_RE = /^[A-Za-z0-9._-]{1,20}$/

// Mirrors the server's normalisation, for the live preview only; the server has the final say.
export function previewHandle(raw: string): string | null {
  const value = raw.trim()
  if (!value) return null
  const match = value.match(URL_RE)
  const handle = match ? match[1] : value.replace(/^@/, "")
  return HANDLE_RE.test(handle) ? handle : null
}

function StripeCard({ data, onChange }: { data: Payments | null; onChange: (next: Payments) => void }) {
  const [busy, setBusy] = useState<"connect" | "dashboard" | "disconnect" | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState("")
  const status = data?.stripe_status ?? null
  const canEdit = !!data?.can_edit

  const go = async (action: "connect" | "dashboard") => {
    setBusy(action)
    setError("")
    // Opened before the request so the browser doesn't treat the dashboard tab as a popup.
    const tab = action === "dashboard" ? window.open("", "_blank") : null
    try {
      const res = await api.post<{ url: string }>(`/settings/payments/stripe/${action}`)
      if (tab) {
        tab.opener = null
        tab.location.href = res.data.url
      } else {
        window.location.href = res.data.url
      }
    } catch (err) {
      tab?.close()
      setError(apiErrorDetail(err, "Stripe isn't reachable right now. Try again in a minute."))
      setBusy(null)
    } finally {
      if (action === "dashboard") setBusy(null)
    }
  }

  const disconnect = async () => {
    setBusy("disconnect")
    setError("")
    try {
      const res = await api.delete<Payments>("/settings/payments/stripe")
      onChange(res.data)
      setConfirming(false)
    } catch (err) {
      setError(apiErrorDetail(err, "Couldn't disconnect Stripe."))
    } finally {
      setBusy(null)
    }
  }

  const badge =
    status === "active"
      ? { text: "Connected ✓", background: "#d8ead6", color: "#2d5a24" }
      : status === "restricted"
      ? { text: "Stripe needs more information", background: "#f6e3b8", color: "#7a5a10" }
      : status === "pending"
      ? { text: "Setup not finished", background: "#f6e3b8", color: "#7a5a10" }
      : { text: "Not connected", background: "#f3ecdb", color: "#6b6558" }

  const pill = "px-4 py-2 rounded-full text-sm font-semibold transition"

  return (
    <div className="rounded-xl p-4 mb-6" style={{ background: "#faf5ee", border: `1px solid ${status === "active" ? "#0a7870" : "#e7ddc5"}` }}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 mb-1">
        <div className="text-sm font-semibold" style={{ color: "#1f2a2e" }}>
          Stripe (cards, Apple Pay, Google Pay, PayPal)
        </div>
        <span className="inline-flex items-center text-[11px] font-semibold px-2 py-0.5 rounded-full" style={{ background: badge.background, color: badge.color }}>
          {badge.text}
        </span>
      </div>
      <p className="text-[13px] mb-3" style={{ color: "#6b6558" }}>
        {status === "active"
          ? "Clients pay on Stripe and the link unlocks by itself. The money goes to your own Stripe account."
          : status === "restricted"
          ? `Stripe can't take payments on your account yet${
              data && data.stripe_requirements_due > 0
                ? ` (${data.stripe_requirements_due} ${data.stripe_requirements_due === 1 ? "item" : "items"} to complete)`
                : ""
            }.`
          : status === "pending"
          ? "Finish the Stripe setup to start taking payments."
          : "Clients pay by card or wallet and the link unlocks by itself as soon as Stripe confirms. The money goes straight to your own Stripe account."}
      </p>

      <div className="flex flex-wrap gap-2">
        {status !== "active" && (
          <button
            type="button"
            onClick={() => void go("connect")}
            disabled={!canEdit || busy !== null}
            className={pill}
            style={{ background: canEdit ? "#0a7870" : "#9bc9c5", color: "#ffffff", cursor: canEdit ? "pointer" : "not-allowed", opacity: busy === "connect" ? 0.7 : 1 }}
          >
            {busy === "connect" ? "Opening Stripe…" : status ? "Continue on Stripe" : "Connect with Stripe"}
          </button>
        )}
        {status && canEdit && (
          <button
            type="button"
            onClick={() => void go("dashboard")}
            disabled={busy !== null}
            className={pill}
            style={{ background: "#ffffff", color: "#0a5e58", border: "1px solid #0a7870" }}
          >
            {busy === "dashboard" ? "Opening…" : "Open Stripe dashboard"}
          </button>
        )}
        {status && canEdit && !confirming && (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={busy !== null}
            className={pill}
            style={{ background: "#ffffff", color: "#b14a3a", border: "1px solid #ecc9c1" }}
          >
            Disconnect
          </button>
        )}
      </div>

      {confirming && (
        <div className="mt-3 rounded-lg p-3" style={{ background: "#ffffff", border: "1px solid #ecc9c1" }}>
          <div className="text-[13px] mb-2" style={{ color: "#1f2a2e" }}>
            Clients won&apos;t be able to pay by card on your links. Your Stripe account and its money stay yours.
          </div>
          <div className="flex gap-2 justify-end">
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded-full px-3 py-1.5 text-xs font-semibold"
              style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void disconnect()}
              disabled={busy === "disconnect"}
              className="rounded-full px-3 py-1.5 text-xs font-semibold"
              style={{ background: "#b14a3a", color: "#ffffff", opacity: busy === "disconnect" ? 0.7 : 1 }}
            >
              {busy === "disconnect" ? "Disconnecting…" : "Yes, disconnect"}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="text-[13px] mt-2" style={{ color: "#b14a3a" }}>
          {error}
        </div>
      )}
      <p className="text-[12px] mt-3" style={{ color: "#8a8270" }}>
        Turn on PayPal in your Stripe settings to let clients pay with PayPal.
      </p>
    </div>
  )
}

export default function PaymentsSection() {
  const [data, setData] = useState<Payments | null>(null)
  const [value, setValue] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    // Back from Stripe onboarding: ask Stripe now rather than wait out the server's refresh interval.
    const back = new URLSearchParams(window.location.search).get("stripe") === "return"
    api
      .get<Payments>("/settings/payments", { params: back ? { refresh: 1 } : undefined })
      .then((res) => {
        setData(res.data)
        setValue(res.data.paypal_me || "")
        // Linked from the share dialog; the section renders after the page's own data, so scroll once it's here.
        if (window.location.hash === "#payments") {
          requestAnimationFrame(() => document.getElementById("payments")?.scrollIntoView({ behavior: "smooth" }))
        }
      })
      .catch((err) => {
        setData(null)
        setError(apiErrorDetail(err, "Payment settings couldn't be loaded. Refresh the page to try again."))
      })
  }, [])

  const handle = previewHandle(value)
  const dirty = (handle ?? value.trim()) !== (data?.paypal_me || "")
  const invalid = !!value.trim() && !handle
  const canSave = !!data?.can_edit && dirty && !invalid && !busy

  const save = async () => {
    setBusy(true)
    setError("")
    setSaved(false)
    try {
      const res = await api.put<Payments>("/settings/payments", { paypal_me: value.trim() || null })
      setData(res.data)
      setValue(res.data.paypal_me || "")
      setSaved(true)
    } catch (err) {
      setError(apiErrorDetail(err, "Couldn't save the PayPal.me name."))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section id="payments" className="rounded-2xl p-6 scroll-mt-6" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
      <div className="mb-5">
        <div className="text-[11px] font-semibold tracking-[0.18em] mb-1" style={{ color: "#9a9178" }}>
          PAYMENTS
        </div>
        <h2 className="text-[18px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
          Get paid before the client downloads
        </h2>
        <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
          Protected client links show a watermarked preview until the client pays.
        </p>
      </div>

      <StripeCard data={data} onChange={setData} />

      <div className="text-sm font-semibold mb-0.5" style={{ color: "#1f2a2e" }}>
        Manual option: PayPal.me
      </div>
      <p className="text-[13px] mb-3" style={{ color: "#6b6558" }}>
        The client pays on PayPal, then you check and mark the link as paid yourself.
      </p>
      <label htmlFor="paypal-me" className="block text-[11px] font-semibold tracking-[0.14em] mb-2" style={{ color: "#9a9178" }}>
        PAYPAL.ME NAME
      </label>
      <div className="flex flex-col sm:flex-row gap-3 sm:items-center">
        <div
          className="flex flex-1 min-w-0 items-center gap-1 px-4 py-2.5 rounded-xl"
          style={{ background: "#faf5ee", border: `1px solid ${invalid ? "#ecc9c1" : "#e7ddc5"}` }}
        >
          <span className="text-sm shrink-0" style={{ color: "#9a9178" }}>
            paypal.me/
          </span>
          <input
            id="paypal-me"
            value={value}
            onChange={(e) => {
              setValue(e.target.value)
              setSaved(false)
            }}
            onKeyDown={(e) => e.key === "Enter" && canSave && void save()}
            disabled={!data?.can_edit}
            placeholder="YourName"
            autoComplete="off"
            spellCheck={false}
            className="flex-1 min-w-0 bg-transparent outline-none text-sm"
            style={{ color: "#1f2a2e" }}
          />
        </div>
        <button
          type="button"
          onClick={() => void save()}
          disabled={!canSave}
          className="px-4 py-2 rounded-full text-sm font-semibold transition"
          style={{ background: canSave ? "#0a7870" : "#9bc9c5", color: "#ffffff", cursor: canSave ? "pointer" : "not-allowed" }}
        >
          {busy ? "Saving…" : "Save"}
        </button>
      </div>

      <div className="text-[13px] mt-3 break-all" style={{ color: invalid ? "#b14a3a" : "#4a4638" }}>
        {invalid
          ? "Use 1–20 letters, digits, dots, dashes or underscores, or paste your paypal.me link."
          : handle
          ? (
            <>
              Clients pay at <span className="font-semibold">paypal.me/{handle}/45EUR</span> (with each link&apos;s amount)
            </>
          )
          : data?.stripe_status === "active"
          ? "No PayPal.me name: clients pay through Stripe only."
          : "No PayPal.me name yet. Protected links still work: clients pay you directly and you mark them as paid."}
      </div>
      {saved && (
        <div className="text-[13px] mt-1" style={{ color: "#2d5a24" }}>
          Saved.
        </div>
      )}
      {error && (
        <div className="text-[13px] mt-1" style={{ color: "#b14a3a" }}>
          {error}
        </div>
      )}
      {data && !data.can_edit && (
        <div className="text-[12px] mt-2" style={{ color: "#8a8270" }}>
          Only the team owner or an admin can change this.
        </div>
      )}
      <p className="text-[12px] mt-4" style={{ color: "#8a8270" }}>
        Clients pay you directly, on Stripe or PayPal. We never see or store card or bank details.
      </p>
    </section>
  )
}
