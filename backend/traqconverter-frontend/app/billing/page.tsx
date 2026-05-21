"use client"

import { useEffect, useMemo, useState } from "react"
import { api } from "@/lib/api"

// ============================================================
// BILLING — ESPRESSO LOOK
// Wired to:
//   GET  /billing/wallet
//   GET  /billing/transactions
//   POST /subscription/create-checkout-session?plan=BASIC|PRO
//   POST /subscription/purchase-credits?amount=N
// Webhook handler is at backend POST /stripe/webhook
// ============================================================

type Wallet = {
  total_credits: number
  subscription_credits: number
  purchased_credits: number
  plan_type: string
  subscription_status: string
  subscription_expires_at: string | null
  // Resolved tier the backend tells us to gate on:
  //   "TRIAL" | "BASIC" | "PRO" | "EXPIRED"
  tier?: string
  trial_days_left?: number | null
  features?: Record<string, boolean>
}

type Transaction = {
  id: string
  type: string
  amount: number
  reference_id: string | null
  created_at: string
}

const PLANS = [
  {
    code: "BASIC",
    name: "Basic",
    price: "€19",
    cadence: "/month",
    blurb: "For freelancers running individual certified translations.",
    bullets: [
      "19 credits each month",
      "Download finished translations (DOCX & PDF)",
      "Team collaboration",
      "Email support",
    ],
  },
  {
    code: "PRO",
    name: "Pro",
    price: "€29",
    cadence: "/month",
    blurb: "For agencies that need TM, glossaries and certified delivery.",
    bullets: [
      "29 credits each month",
      "Everything in Basic",
      "Translation Memory across projects",
      "Custom Glossary enforcement",
      "Certifications library (ISO 17100, affidavits)",
      "Priority support",
    ],
    featured: true,
  },
]

const CREDIT_PACKS = [
  { credits: 10, label: "Starter pack", note: "Top up a small project" },
  { credits: 25, label: "Studio pack", note: "Most teams pick this", featured: true },
  { credits: 50, label: "Scale pack", note: "Best €/credit value" },
]

export default function BillingPage() {
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchBilling()
  }, [])

  const fetchBilling = async () => {
    try {
      setLoading(true)
      const [walletRes, txRes] = await Promise.all([
        api.get("/billing/wallet"),
        api.get("/billing/transactions"),
      ])
      setWallet(walletRes.data)
      setTransactions(txRes.data || [])
    } catch (err: any) {
      console.error("BILLING ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't load billing — try refreshing in a moment."
      )
    } finally {
      setLoading(false)
    }
  }

  const handleSubscribe = async (plan: "BASIC" | "PRO") => {
    setError(null)
    try {
      setBusy(`plan:${plan}`)
      const res = await api.post(
        "/subscription/create-checkout-session",
        null,
        { params: { plan } }
      )
      if (res.data?.checkout_url) {
        window.location.href = res.data.checkout_url
      } else {
        throw new Error("No checkout URL returned")
      }
    } catch (err: any) {
      console.error("SUBSCRIBE ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't start checkout. Please try again."
      )
    } finally {
      setBusy(null)
    }
  }

  const handleBuyCredits = async (amount: number) => {
    setError(null)
    if (!Number.isFinite(amount) || amount <= 0) {
      setError("Enter a positive number of credits.")
      return
    }
    try {
      setBusy(`credits:${amount}`)
      const res = await api.post(
        "/subscription/purchase-credits",
        null,
        { params: { amount } }
      )
      if (res.data?.checkout_url) {
        window.location.href = res.data.checkout_url
      } else {
        throw new Error("No checkout URL returned")
      }
    } catch (err: any) {
      console.error("PURCHASE ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't start checkout. Please try again."
      )
    } finally {
      setBusy(null)
    }
  }

  const tier = (wallet?.tier || "").toUpperCase()
  const planActive = useMemo(
    () =>
      (wallet?.subscription_status || "").toUpperCase() === "ACTIVE" ||
      tier === "PRO" ||
      tier === "BASIC",
    [wallet, tier]
  )
  const onTrial = tier === "TRIAL"
  const trialExpired = tier === "EXPIRED"
  const currentPlan = (wallet?.plan_type || "TRIAL").toUpperCase()
  const trialDaysLeft = wallet?.trial_days_left ?? null

  if (loading) {
    return (
      <div className="px-2 py-10" style={{ color: "#6b6558" }}>
        Loading billing…
      </div>
    )
  }

  if (!wallet) {
    return (
      <div
        className="rounded-xl px-4 py-3 text-sm"
        style={{ background: "#f2d4cf", color: "#7a2f24" }}
      >
        {error || "Failed to load billing."}
      </div>
    )
  }

  return (
    <div className="space-y-8 pb-16">
      {/* BREADCRUMB */}
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span> Account{" "}
        <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <span style={{ color: "#1f2a2e" }}>Billing</span>
      </div>

      {/* HEADER */}
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
            Billing &amp; Credits
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            Manage your subscription, buy more credits, and review usage.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusPill
            active={planActive}
            label={`${currentPlan} · ${planActive ? "Active" : onTrial ? "Trial" : "Inactive"}`}
          />
        </div>
      </div>

      {/* TRIAL / EXPIRED BANNER */}
      {onTrial && (
        <div
          className="rounded-2xl p-5 flex flex-wrap items-center justify-between gap-4"
          style={{
            background: "#fbf4e0",
            border: "1px solid #f1e2b8",
            color: "#5a4310",
          }}
        >
          <div>
            <div
              className="text-[11px] font-semibold tracking-[0.18em] mb-1"
              style={{ color: "#a07a14" }}
            >
              FREE TRIAL
            </div>
            <div className="text-[15px] font-semibold mb-0.5" style={{ color: "#1f2a2e" }}>
              {trialDaysLeft != null && trialDaysLeft > 0
                ? `${trialDaysLeft} day${trialDaysLeft === 1 ? "" : "s"} left in your trial`
                : "Your trial is ending today"}
            </div>
            <p className="text-sm" style={{ color: "#6b5818" }}>
              You can run one test translation, but downloading the result is
              locked until you subscribe to Basic or Pro.
            </p>
          </div>
          <button
            type="button"
            onClick={() => handleSubscribe("PRO")}
            disabled={busy !== null}
            className="px-4 py-2.5 rounded-full text-sm font-semibold transition"
            style={{ background: "#0a7870", color: "#fff" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "#0a645d")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "#0a7870")}
          >
            Upgrade to Pro
          </button>
        </div>
      )}

      {trialExpired && (
        <div
          className="rounded-2xl p-5 flex flex-wrap items-center justify-between gap-4"
          style={{
            background: "#f2d4cf",
            border: "1px solid #e7b8b0",
            color: "#7a2f24",
          }}
        >
          <div>
            <div className="text-[15px] font-semibold mb-0.5" style={{ color: "#7a2f24" }}>
              Your trial has ended
            </div>
            <p className="text-sm" style={{ color: "#7a2f24" }}>
              Subscribe to Basic or Pro to continue translating and download
              your work.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => handleSubscribe("BASIC")}
              disabled={busy !== null}
              className="px-4 py-2 rounded-full text-sm font-semibold"
              style={{
                background: "#ffffff",
                color: "#1f2a2e",
                border: "1px solid #e7ddc5",
              }}
            >
              Subscribe to Basic
            </button>
            <button
              type="button"
              onClick={() => handleSubscribe("PRO")}
              disabled={busy !== null}
              className="px-4 py-2 rounded-full text-sm font-semibold"
              style={{ background: "#0a7870", color: "#fff" }}
            >
              Subscribe to Pro
            </button>
          </div>
        </div>
      )}

      {error && (
        <div
          className="text-sm rounded-lg px-3 py-2"
          style={{ background: "#f2d4cf", color: "#7a2f24" }}
        >
          {error}
        </div>
      )}

      {/* WALLET KPI CARDS */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <KpiCard
          label="Total credits"
          value={wallet.total_credits.toLocaleString()}
          accent
        />
        <KpiCard
          label="Subscription credits"
          value={wallet.subscription_credits.toLocaleString()}
          sub="Reset each cycle"
        />
        <KpiCard
          label="Purchased credits"
          value={wallet.purchased_credits.toLocaleString()}
          sub="Never expire"
        />
        <KpiCard
          label="Renews"
          value={
            wallet.subscription_expires_at
              ? new Date(wallet.subscription_expires_at).toLocaleDateString()
              : "—"
          }
          sub={planActive ? "Next billing date" : "No active plan"}
        />
      </div>

      {/* PLAN TIERS */}
      <section>
        <SectionHeader
          eyebrow="SUBSCRIPTION"
          title="Choose a plan"
          subtitle="Cancel anytime. Webhooks update your wallet within seconds of payment."
        />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {PLANS.map((p) => {
            // The card is "current" only when the resolved tier matches it.
            // TRIAL/EXPIRED never show CURRENT — they see Subscribe CTAs.
            const isCurrent = tier === p.code
            return (
              <PlanCard
                key={p.code}
                plan={p}
                isCurrent={isCurrent}
                busy={busy === `plan:${p.code}`}
                disabled={busy !== null}
                onSubscribe={() => handleSubscribe(p.code as "BASIC" | "PRO")}
              />
            )
          })}
        </div>
      </section>

      {/* CREDIT PACKS */}
      <section>
        <SectionHeader
          eyebrow="ONE-TIME"
          title="Buy more credits"
          subtitle="Top up at any time — purchased credits stack on top of your subscription and never expire."
        />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          {CREDIT_PACKS.map((pack) => (
            <CreditPackCard
              key={pack.credits}
              credits={pack.credits}
              label={pack.label}
              note={pack.note}
              featured={!!pack.featured}
              busy={busy === `credits:${pack.credits}`}
              disabled={busy !== null}
              onBuy={() => handleBuyCredits(pack.credits)}
            />
          ))}
        </div>
      </section>

      {/* TRANSACTIONS */}
      <section>
        <SectionHeader
          eyebrow="HISTORY"
          title="Recent transactions"
          subtitle="Last 100 credit movements on your wallet."
        />
        <div
          className="rounded-2xl overflow-hidden"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
        >
          <div
            className="grid text-[11px] font-semibold tracking-[0.14em] px-5 py-3"
            style={{
              gridTemplateColumns: "1.2fr 1fr 2fr 1fr",
              background: "#faf5ee",
              borderBottom: "1px solid #f1e8d1",
              color: "#9a9178",
            }}
          >
            <div>TYPE</div>
            <div>AMOUNT</div>
            <div>REFERENCE</div>
            <div className="text-right">DATE</div>
          </div>
          {transactions.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm" style={{ color: "#8a8270" }}>
              No transactions yet — your wallet movements will appear here.
            </div>
          ) : (
            transactions.map((t) => (
              <div
                key={t.id}
                className="grid items-center px-5 py-3 text-sm"
                style={{
                  gridTemplateColumns: "1.2fr 1fr 2fr 1fr",
                  borderBottom: "1px solid #f4ecd6",
                  color: "#1f2a2e",
                }}
              >
                <div className="capitalize" style={{ color: "#4a4638" }}>
                  {t.type.toLowerCase()}
                </div>
                <div
                  className="font-semibold tabular-nums"
                  style={{ color: t.amount > 0 ? "#2d5a24" : "#7a2f24" }}
                >
                  {t.amount > 0 ? "+" : ""}
                  {t.amount.toLocaleString()}
                </div>
                <div
                  className="font-mono text-[12px] truncate"
                  style={{ color: "#8a8270" }}
                  title={t.reference_id || ""}
                >
                  {t.reference_id || "—"}
                </div>
                <div className="text-right tabular-nums" style={{ color: "#6b6558" }}>
                  {new Date(t.created_at).toLocaleDateString()}
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  )
}

// ============================================================
// SUBCOMPONENTS
// ============================================================

function StatusPill({ active, label }: { active: boolean; label: string }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.08em] px-2.5 py-1 rounded-full"
      style={{
        background: active ? "#d8ead6" : "#f3ecdb",
        color: active ? "#2d5a24" : "#8a8270",
        border: `1px solid ${active ? "#bcdab8" : "#e7ddc5"}`,
      }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: active ? "#2d5a24" : "#9a9178" }}
      />
      {label}
    </span>
  )
}

function KpiCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub?: string
  accent?: boolean
}) {
  return (
    <div
      className="rounded-2xl p-5"
      style={{
        background: accent ? "#0a7870" : "#ffffff",
        border: accent ? "1px solid #0a645d" : "1px solid #e7ddc5",
        color: accent ? "#fff" : "#1f2a2e",
        boxShadow: "0 1px 2px rgba(30,30,20,0.04)",
      }}
    >
      <div
        className="text-[11px] font-semibold tracking-[0.14em] mb-2"
        style={{ color: accent ? "#cfe6e2" : "#9a9178" }}
      >
        {label.toUpperCase()}
      </div>
      <div className="text-[28px] font-semibold tracking-tight tabular-nums">{value}</div>
      {sub && (
        <div className="text-xs mt-1" style={{ color: accent ? "#cfe6e2" : "#8a8270" }}>
          {sub}
        </div>
      )}
    </div>
  )
}

function SectionHeader({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string
  title: string
  subtitle?: string
}) {
  return (
    <div className="mb-4">
      <div className="text-[11px] font-semibold tracking-[0.18em] mb-1" style={{ color: "#9a9178" }}>
        {eyebrow}
      </div>
      <h2 className="text-[20px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
        {title}
      </h2>
      {subtitle && (
        <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
          {subtitle}
        </p>
      )}
    </div>
  )
}

function PlanCard({
  plan,
  isCurrent,
  busy,
  disabled,
  onSubscribe,
}: {
  plan: {
    code: string
    name: string
    price: string
    cadence: string
    blurb: string
    bullets: string[]
    featured?: boolean
  }
  isCurrent: boolean
  busy: boolean
  disabled: boolean
  onSubscribe: () => void
}) {
  const featured = !!plan.featured
  return (
    <div
      className="rounded-2xl p-6 flex flex-col"
      style={{
        background: "#ffffff",
        border: featured ? "1px solid #0a7870" : "1px solid #e7ddc5",
        boxShadow: featured
          ? "0 8px 24px rgba(10,120,112,0.08)"
          : "0 1px 2px rgba(30,30,20,0.04)",
        position: "relative",
      }}
    >
      {featured && (
        <span
          className="absolute -top-2.5 right-5 text-[10px] font-semibold tracking-[0.16em] px-2 py-1 rounded-full"
          style={{ background: "#0a7870", color: "#fff" }}
        >
          POPULAR
        </span>
      )}
      <div className="flex items-baseline justify-between mb-2">
        <div className="text-[20px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
          {plan.name}
        </div>
        {isCurrent && (
          <span
            className="text-[10px] font-semibold tracking-[0.14em] px-2 py-0.5 rounded-full"
            style={{ background: "#cfe6e2", color: "#0a7870" }}
          >
            CURRENT
          </span>
        )}
      </div>
      <div className="flex items-baseline gap-1 mb-3">
        <div className="text-[32px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
          {plan.price}
        </div>
        <div className="text-sm" style={{ color: "#8a8270" }}>
          {plan.cadence}
        </div>
      </div>
      <p className="text-sm mb-4" style={{ color: "#4a4638" }}>
        {plan.blurb}
      </p>
      <ul className="space-y-2 mb-6 flex-1">
        {plan.bullets.map((b) => (
          <li key={b} className="flex items-start gap-2 text-sm">
            <span
              className="mt-0.5 w-4 h-4 rounded-full flex items-center justify-center shrink-0"
              style={{ background: "#cfe6e2", color: "#0a7870" }}
            >
              <svg
                width="9"
                height="9"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="m5 12 5 5 10-10" />
              </svg>
            </span>
            <span style={{ color: "#1f2a2e" }}>{b}</span>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={onSubscribe}
        disabled={disabled || isCurrent}
        className="w-full py-3 rounded-full text-[14px] font-semibold transition"
        style={{
          background: isCurrent ? "#f3ecdb" : disabled ? "#9bc9c5" : "#0a7870",
          color: isCurrent ? "#8a8270" : "#fff",
          cursor: isCurrent || disabled ? "not-allowed" : "pointer",
          border: isCurrent ? "1px solid #e7ddc5" : "none",
        }}
        onMouseEnter={(e) => {
          if (!isCurrent && !disabled) e.currentTarget.style.background = "#0a645d"
        }}
        onMouseLeave={(e) => {
          if (!isCurrent && !disabled) e.currentTarget.style.background = "#0a7870"
        }}
      >
        {isCurrent ? "Current plan" : busy ? "Redirecting to Stripe…" : `Subscribe to ${plan.name}`}
      </button>
    </div>
  )
}

function CreditPackCard({
  credits,
  label,
  note,
  featured,
  busy,
  disabled,
  onBuy,
}: {
  credits: number
  label: string
  note: string
  featured: boolean
  busy: boolean
  disabled: boolean
  onBuy: () => void
}) {
  return (
    <div
      className="rounded-2xl p-5 flex flex-col"
      style={{
        background: "#ffffff",
        border: featured ? "1px solid #0a7870" : "1px solid #e7ddc5",
        boxShadow: featured
          ? "0 6px 18px rgba(10,120,112,0.06)"
          : "0 1px 2px rgba(30,30,20,0.04)",
      }}
    >
      <div className="text-[11px] font-semibold tracking-[0.14em] mb-2" style={{ color: "#9a9178" }}>
        {label.toUpperCase()}
      </div>
      <div
        className="text-[28px] font-semibold tracking-tight tabular-nums mb-1"
        style={{ color: "#1f2a2e" }}
      >
        {credits.toLocaleString()}{" "}
        <span className="text-sm font-normal" style={{ color: "#8a8270" }}>
          credits
        </span>
      </div>
      <div className="text-sm mb-5" style={{ color: "#4a4638" }}>
        {note}
      </div>
      <button
        type="button"
        onClick={onBuy}
        disabled={disabled}
        className="w-full py-2.5 rounded-full text-sm font-semibold transition"
        style={{
          background: disabled ? "#9bc9c5" : featured ? "#0a7870" : "#1f2a2e",
          color: "#fff",
          cursor: disabled ? "not-allowed" : "pointer",
        }}
        onMouseEnter={(e) => {
          if (!disabled) e.currentTarget.style.background = featured ? "#0a645d" : "#0f1518"
        }}
        onMouseLeave={(e) => {
          if (!disabled) e.currentTarget.style.background = featured ? "#0a7870" : "#1f2a2e"
        }}
      >
        {busy ? "Redirecting…" : "Buy now"}
      </button>
    </div>
  )
}
