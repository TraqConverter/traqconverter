// How a protected client link's payment is shown to the team. No client details: we don't store any.

export type ProjectPaymentState = "paid_card" | "marked_paid" | "claimed" | "awaiting"

export type ProjectPayment = {
  state: ProjectPaymentState
  link_id: string
  amount: number | null
  currency: string
  sent_at: string | null
  expires_at: string | null
  claimed_at: string | null
  paid_at: string | null
  unlocked_at: string | null
  marked_by: string | null
  // Owner, admin or PM, and only while the link is still waiting.
  can_mark_paid: boolean
}

// 45 -> "45", 45.5 -> "45.50": the form a paypal.me link takes.
export function amountText(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

export function money(value: number | null, currency: string) {
  if (value == null) return ""
  return currency === "EUR" ? `€${amountText(value)}` : `${amountText(value)} ${currency}`
}

export function shortDate(iso: string | null) {
  if (!iso) return ""
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })
}

export const PAYMENT_STYLE: Record<ProjectPaymentState, { background: string; color: string; border: string; dot: string }> = {
  paid_card: { background: "#d8ead6", color: "#2d5a24", border: "#bcd9b7", dot: "#4a8a3a" },
  marked_paid: { background: "#d8ead6", color: "#2d5a24", border: "#bcd9b7", dot: "#4a8a3a" },
  claimed: { background: "#fbe3a6", color: "#6b4a06", border: "#e0a92e", dot: "#c88a1a" },
  awaiting: { background: "#f3ecdb", color: "#6b6558", border: "#e7ddc5", dot: "#9a9178" },
}

export function paymentLabel(state: ProjectPaymentState, markedBy: string | null) {
  if (state === "paid_card") return "Paid by card via Stripe"
  if (state === "marked_paid") return markedBy ? `Marked paid by ${markedBy}` : "Marked paid"
  if (state === "claimed") return "Client says paid"
  return "Awaiting payment"
}

// The line after the badge: amount, and the date that matters for this state.
export function paymentDetail(p: ProjectPayment) {
  const amount = money(p.amount, p.currency)
  const when =
    p.state === "paid_card"
      ? shortDate(p.paid_at)
      : p.state === "marked_paid"
      ? shortDate(p.unlocked_at)
      : p.state === "claimed"
      ? shortDate(p.claimed_at)
      : `sent ${shortDate(p.sent_at)}`
  return [amount, when].filter(Boolean).join(" · ")
}
