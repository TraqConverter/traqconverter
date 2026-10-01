"use client"

import { useEffect, useState } from "react"
import { api, apiErrorDetail } from "@/lib/api"

type Payments = { paypal_me: string | null; paypal_url: string | null; can_edit: boolean }

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

export default function PaymentsSection() {
  const [data, setData] = useState<Payments | null>(null)
  const [value, setValue] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api
      .get<Payments>("/settings/payments")
      .then((res) => {
        setData(res.data)
        setValue(res.data.paypal_me || "")
        // Linked from the share dialog; the section renders after the page's own data, so scroll once it's here.
        if (window.location.hash === "#payments") {
          requestAnimationFrame(() => document.getElementById("payments")?.scrollIntoView({ behavior: "smooth" }))
        }
      })
      .catch(() => setData(null))
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
          Protected client links show a watermarked preview and a PayPal button until you unlock them.
        </p>
      </div>

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
          : "No PayPal.me name yet: protected links can't be created until you add one."}
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
        Clients pay you directly on PayPal. We never see or store payment details.
      </p>
    </section>
  )
}
