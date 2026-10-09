"use client"

import { useState } from "react"
import { dayMonth, money, paymentLabel, type ProjectPayment } from "@/lib/payment"

const OPEN = {
  awaiting: { background: "#e1efec", color: "#0a5e58", border: "#cfe6e2", dot: "#0a7870" },
  claimed: { background: "#fbe3a6", color: "#6b4a06", border: "#e0a92e", dot: "#c88a1a" },
}

const PAID = { background: "#d8ead6", color: "#2d5a24", border: "#bcd9b7", dot: "#4a8a3a" }

// The project's payment link at a glance, from the same deciding link as Projects. Paid links show only
// right after they were paid in this session (`justPaid`); otherwise the bar is gone.
export default function PaymentBar({
  payment,
  justPaid,
  onMarkPaid,
  onManage,
}: {
  payment: ProjectPayment | null
  justPaid: boolean
  onMarkPaid: () => void
  onManage: () => void
}) {
  const [copied, setCopied] = useState(false)
  if (!payment) return null
  const paid = payment.state === "paid_card" || payment.state === "marked_paid"
  if (paid && !justPaid) return null

  const amount = money(payment.amount, payment.currency)

  if (paid) {
    return (
      <div
        role="status"
        data-testid="payment-bar"
        data-state={payment.state}
        className="flex items-center gap-2 rounded-xl px-3 py-2 mb-4 text-[13px] font-semibold"
        style={{ background: PAID.background, color: PAID.color, border: `1px solid ${PAID.border}` }}
      >
        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: PAID.dot }} />
        <span className="min-w-0">
          {[paymentLabel(payment.state, payment.marked_by), amount].filter(Boolean).join(" · ")}
        </span>
      </div>
    )
  }

  const claimed = payment.state === "claimed"
  const st = claimed ? OPEN.claimed : OPEN.awaiting
  const text = claimed
    ? `Your client says they've paid${amount ? ` · ${amount}` : ""} — check the money has arrived`
    : ["Waiting for payment", amount, payment.sent_at ? `link sent ${dayMonth(payment.sent_at)}` : ""]
        .filter(Boolean)
        .join(" · ")

  const copy = async () => {
    if (!payment.url) return
    try {
      await navigator.clipboard.writeText(payment.url)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  const pill = "text-[12px] font-semibold px-3 py-1 rounded-full whitespace-nowrap transition"

  return (
    <div
      role="status"
      data-testid="payment-bar"
      data-state={payment.state}
      className={`flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl px-3 mb-4 ${claimed ? "py-2.5" : "py-2"}`}
      style={{ background: st.background, color: st.color, border: `1px solid ${st.border}` }}
    >
      <div className="flex items-center gap-2 min-w-0 flex-1 basis-[220px]">
        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: st.dot }} />
        <span className={`min-w-0 [overflow-wrap:anywhere] ${claimed ? "text-[14px] font-bold" : "text-[13px] font-semibold"}`}>
          {text}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {payment.can_mark_paid && (
          <button type="button" onClick={onMarkPaid} className={pill} style={{ background: "#0a7870", color: "#ffffff" }}>
            Mark as paid
          </button>
        )}
        {payment.url && (
          <button
            type="button"
            onClick={() => void copy()}
            className={pill}
            style={
              copied
                ? { background: PAID.background, color: PAID.color, border: `1px solid ${PAID.border}` }
                : { background: "#ffffff", color: "#0a5e58", border: "1px solid #cfe6e2" }
            }
          >
            {copied ? "Copied" : "Copy link"}
          </button>
        )}
        <button
          type="button"
          onClick={onManage}
          className={pill}
          style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
        >
          Manage
        </button>
      </div>
    </div>
  )
}
