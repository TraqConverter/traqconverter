"use client"

import { useEffect, useMemo, useState } from "react"
import { api } from "@/lib/api"
import {
  contactHref,
  euro,
  findPlan,
  pagesLabel,
  planBullets,
  usePlans,
  type Plan,
  type PlanCatalog,
} from "@/lib/plans"

function formatDate(iso?: string | null) {
  if (!iso) return "—"
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(iso)
  return new Date(hasTz ? iso : iso + "Z").toLocaleDateString()
}

type Wallet = {
  total_credits: number
  subscription_credits: number
  purchased_credits: number
  plan_type: string
  subscription_status: string
  subscription_expires_at: string | null

  tier?: string
  trial_days_left?: number | null
  features?: Record<string, boolean>
  // Plan changes, card, invoices and cancelling go through the Stripe portal.
  has_subscription?: boolean
}

type Transaction = {
  id: string
  type: string
  amount: number
  reference_id: string | null
  created_at: string
}

export default function BillingPage() {
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const catalog = usePlans()

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

  const openPortal = async (busyKey = "portal") => {
    setError(null)
    try {
      setBusy(busyKey)
      const res = await api.post("/subscription/portal")
      if (res.data?.portal_url) {
        window.location.href = res.data.portal_url
      } else {
        throw new Error("No portal URL returned")
      }
    } catch (err: any) {
      console.error("PORTAL ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't open the billing portal. Please try again."
      )
      setBusy(null)
    }
  }

  const handleSubscribe = async (plan: string) => {
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
      // Already subscribed: a second checkout would bill twice, so change plan in the portal.
      if (err?.response?.status === 409 && err?.response?.data?.portal) {
        await openPortal(`plan:${plan}`)
        return
      }
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
      !!findPlan(catalog, tier),
    [wallet, tier, catalog]
  )
  const onTrial = tier === "TRIAL"
  const trialExpired = tier === "EXPIRED"
  const currentPlan = (wallet?.plan_type || "TRIAL").toUpperCase()
  const trialDaysLeft = wallet?.trial_days_left ?? null
  const subscribed = !!wallet?.has_subscription

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
      {}
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span> Account{" "}
        <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <span style={{ color: "#1f2a2e" }}>Billing</span>
      </div>

      {}
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
            Billing &amp; Credits
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            Manage your subscription, buy more credits, and review usage.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill
            active={planActive}
            label={`${currentPlan} · ${planActive ? "Active" : onTrial ? "Trial" : "Inactive"}`}
          />
          {subscribed && (
            <button
              type="button"
              onClick={() => openPortal()}
              disabled={busy !== null}
              className="px-4 py-2 rounded-full text-sm font-semibold transition"
              style={{
                background: "#ffffff",
                color: "#1f2a2e",
                border: "1px solid #e7ddc5",
                cursor: busy !== null ? "not-allowed" : "pointer",
              }}
              onMouseEnter={(e) => {
                if (busy === null) e.currentTarget.style.background = "#faf5ee"
              }}
              onMouseLeave={(e) => (e.currentTarget.style.background = "#ffffff")}
            >
              {busy === "portal" ? "Opening…" : "Manage subscription"}
            </button>
          )}
        </div>
      </div>

      {}
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
              {catalog
                ? `Your trial includes ${pagesLabel(catalog.trial.credits)} to test with. `
                : ""}
              Downloading the result is locked until you subscribe to a plan.
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
              Subscribe to a plan to continue translating and download your
              work.
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

      {}
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
          value={formatDate(wallet.subscription_expires_at)}
          sub={planActive ? "Next billing date" : "No active plan"}
        />
      </div>

      {}
      <section>
        <SectionHeader
          eyebrow="SUBSCRIPTION"
          title={subscribed ? "Your plan" : "Choose a plan"}
          subtitle={
            subscribed
              ? "Change plan, update your card, download invoices or cancel in the billing portal. An upgrade adds the extra pages straight away; a downgrade keeps the pages you already have."
              : "One credit is one page. Cancel anytime. Your wallet updates within seconds of payment."
          }
        />
        {catalog === undefined ? (
          <div className="text-sm" style={{ color: "#8a8270" }}>Loading plans…</div>
        ) : catalog === null ? (
          <div className="text-sm" style={{ color: "#7a2f24" }}>
            Couldn&apos;t load the plans. Refresh the page to try again.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {catalog.plans.map((p) => (
              <PlanCard
                key={p.code}
                plan={p}
                catalog={catalog}
                isCurrent={tier === p.code}
                subscribed={subscribed}
                busy={busy === `plan:${p.code}`}
                disabled={busy !== null}
                onSubscribe={() =>
                  subscribed ? openPortal(`plan:${p.code}`) : handleSubscribe(p.code)
                }
              />
            ))}
          </div>
        )}
      </section>

      {}
      <section>
        <SectionHeader
          eyebrow="ONE-TIME"
          title="Buy more credits"
          subtitle="Top up at any time — purchased credits stack on top of your subscription and never expire."
        />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          {(catalog?.credit_packs || []).map((pack, i) => (
            <CreditPackCard
              key={pack.credits}
              credits={pack.credits}
              label={pack.name}
              note={`${pack.note} · ${euro(pack.price_eur)}`}
              featured={i === 1}
              busy={busy === `credits:${pack.credits}`}
              disabled={busy !== null}
              onBuy={() => handleBuyCredits(pack.credits)}
            />
          ))}
        </div>
      </section>

      {}
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
                  {t.type.toLowerCase().replace(/_/g, " ")}
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
                  {formatDate(t.created_at)}
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  )
}

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
  catalog,
  isCurrent,
  subscribed,
  busy,
  disabled,
  onSubscribe,
}: {
  plan: Plan
  catalog: PlanCatalog
  isCurrent: boolean
  subscribed: boolean
  busy: boolean
  disabled: boolean
  onSubscribe: () => void
}) {
  const featured = plan.code === "PRO"
  // Subscribers open the portal from every card, their own plan included; others can't re-buy the current one.
  const locked = isCurrent && !subscribed
  const muted = isCurrent
  const label = busy
    ? subscribed
      ? "Opening…"
      : "Redirecting to Stripe…"
    : isCurrent
      ? "Current plan"
      : subscribed
        ? "Change plan"
        : `Subscribe to ${plan.name}`
  const bullets = planBullets(catalog, plan)
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
          {euro(plan.price_eur)}
        </div>
        <div className="text-sm" style={{ color: "#8a8270" }}>
          /month
        </div>
      </div>
      <p className="text-sm mb-4" style={{ color: "#4a4638" }}>
        {plan.blurb}
      </p>
      <ul className="space-y-2 mb-6 flex-1">
        {bullets.map((b) => (
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
      {!plan.available && !isCurrent ? (
        <a
          href={contactHref(catalog, plan)}
          className="w-full py-3 rounded-full text-[14px] font-semibold text-center"
          style={{ background: "#1f2a2e", color: "#fff" }}
          title={catalog.contact_email}
        >
          Contact us
        </a>
      ) : (
      <button
        type="button"
        onClick={onSubscribe}
        disabled={disabled || locked}
        className="w-full py-3 rounded-full text-[14px] font-semibold transition"
        style={{
          background: muted ? "#f3ecdb" : disabled ? "#9bc9c5" : "#0a7870",
          color: muted ? "#8a8270" : "#fff",
          cursor: locked || disabled ? "not-allowed" : "pointer",
          border: muted ? "1px solid #e7ddc5" : "none",
        }}
        onMouseEnter={(e) => {
          if (locked || disabled) return
          e.currentTarget.style.background = muted ? "#ece2c8" : "#0a645d"
        }}
        onMouseLeave={(e) => {
          if (locked || disabled) return
          e.currentTarget.style.background = muted ? "#f3ecdb" : "#0a7870"
        }}
        title={subscribed ? "Opens the billing portal" : undefined}
      >
        {label}
      </button>
      )}
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
