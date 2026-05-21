"use client"

import { useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { api } from "@/lib/api"

// ============================================================
// Stripe redirects here after a successful checkout. Flow:
//
// 1. Read ?session_id=... from the URL (added to success_url server-side).
// 2. POST /subscription/sync-session — applies the upgrade directly so
//    we don't have to wait for the Stripe webhook. Idempotent.
// 3. Poll /billing/wallet a few times in case the user is on a slow
//    network and the sync hasn't propagated yet.
// 4. Once tier === BASIC or PRO, route them to /billing.
// ============================================================

const POLL_INTERVAL_MS = 1500
const MAX_POLLS = 20 // ~30s total

export default function CheckoutSuccessPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const sessionId = searchParams?.get("session_id")

  const [tier, setTier] = useState<string | null>(null)
  const [tries, setTries] = useState(0)
  const [stillWaiting, setStillWaiting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const settle = (t: string) => {
      if (cancelled) return
      setTier(t)
      if (t === "PRO" || t === "BASIC") {
        setTimeout(() => router.push("/billing"), 800)
      }
    }

    const apply = async () => {
      // Step 1 — sync the session with the backend (fast path, no webhook).
      // Two purchase shapes come back:
      //   - { status: "success", tier: "PRO"|"BASIC" }     (subscription)
      //   - { status: "success", kind: "credits",          (credit pack)
      //       credits_added: N, purchased_credits: total }
      // Either is a success — route to /billing.
      if (sessionId) {
        try {
          const res = await api.post(
            "/subscription/sync-session",
            null,
            { params: { session_id: sessionId } }
          )
          const data = res.data || {}
          const t = (data.tier || "").toUpperCase()
          if (t === "PRO" || t === "BASIC") {
            settle(t)
            return
          }
          if (data.kind === "credits" || data.status === "success") {
            // Credit pack landed — show a credit-flavoured confirmation.
            setTier("CREDITS")
            setTimeout(() => router.push("/billing"), 800)
            return
          }
        } catch (err: any) {
          console.warn("sync-session failed:", err?.response?.data?.detail)
        }
      }

      // Step 2 — poll the wallet for either tier upgrade OR an
      // increase in total credits compared to the initial reading.
      let initialCredits: number | null = null
      const poll = async () => {
        try {
          const res = await api.get("/billing/wallet")
          if (cancelled) return
          const t = (res.data?.tier || "").toUpperCase()
          setTier(t)
          if (t === "PRO" || t === "BASIC") {
            setTimeout(() => router.push("/billing"), 800)
            return
          }
          // Credit-pack detection: total_credits jumped after we landed
          // on /success → assume the webhook processed the purchase.
          const tot = Number(res.data?.total_credits ?? 0)
          if (initialCredits === null) {
            initialCredits = tot
          } else if (tot > initialCredits) {
            setTier("CREDITS")
            setTimeout(() => router.push("/billing"), 800)
            return
          }
          setTries((n) => n + 1)
        } catch {
          /* try again */
        }
        if (!cancelled) {
          timer = setTimeout(poll, POLL_INTERVAL_MS)
        }
      }
      poll()
    }

    apply()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [router, sessionId])

  useEffect(() => {
    if (tries >= MAX_POLLS) setStillWaiting(true)
  }, [tries])

  const upgraded = tier === "PRO" || tier === "BASIC"
  const creditsLanded = tier === "CREDITS"
  const settled = upgraded || creditsLanded

  return (
    <div className="min-h-[70vh] flex items-center justify-center px-4">
      <div
        className="w-full max-w-md rounded-2xl p-8 text-center"
        style={{
          background: "#ffffff",
          border: "1px solid #e7ddc5",
          boxShadow: "0 1px 2px rgba(30,30,20,0.04)",
        }}
      >
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5"
          style={{ background: "#cfe6e2", color: "#0a7870" }}
        >
          <svg
            width="28"
            height="28"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
            <polyline points="22 4 12 14.01 9 11.01" />
          </svg>
        </div>

        <div
          className="text-[11px] font-semibold tracking-[0.18em] mb-1"
          style={{ color: "#0a7870" }}
        >
          PAYMENT CONFIRMED
        </div>
        <h1
          className="text-[24px] font-semibold tracking-tight mb-2"
          style={{ color: "#1f2a2e" }}
        >
          {upgraded
            ? `You're on the ${tier === "PRO" ? "Pro" : "Basic"} plan!`
            : creditsLanded
            ? "Credits added to your wallet"
            : "Thanks for your payment"}
        </h1>
        <p
          className="text-sm leading-relaxed mb-6"
          style={{ color: "#6b6558" }}
        >
          {upgraded
            ? "Your credits are loaded and your features are unlocked. Redirecting you to billing…"
            : creditsLanded
            ? "Your top-up has landed. Redirecting you to billing…"
            : stillWaiting
            ? "Stripe usually confirms within a few seconds. If your plan still doesn't update, refresh this page or check your Stripe dashboard."
            : "We're confirming your payment with Stripe — this normally takes 5–10 seconds."}
        </p>

        {error && (
          <div
            className="text-sm rounded-lg px-3 py-2 mb-4 text-left"
            style={{ background: "#f2d4cf", color: "#7a2f24" }}
          >
            {error}
          </div>
        )}

        {!settled && !stillWaiting && (
          <div className="flex items-center justify-center gap-2">
            <span
              className="inline-block w-2 h-2 rounded-full animate-pulse"
              style={{ background: "#0a7870" }}
            />
            <span
              className="inline-block w-2 h-2 rounded-full animate-pulse"
              style={{ background: "#0a7870", animationDelay: "0.15s" }}
            />
            <span
              className="inline-block w-2 h-2 rounded-full animate-pulse"
              style={{ background: "#0a7870", animationDelay: "0.3s" }}
            />
          </div>
        )}

        <div className="flex items-center justify-center gap-2 mt-6">
          <button
            type="button"
            onClick={() => router.push("/billing")}
            className="px-4 py-2 rounded-full text-sm font-semibold"
            style={{ background: "#0a7870", color: "#fff" }}
          >
            Go to billing
          </button>
          <button
            type="button"
            onClick={() => router.push("/dashboard")}
            className="px-4 py-2 rounded-full text-sm font-semibold"
            style={{
              background: "#ffffff",
              color: "#1f2a2e",
              border: "1px solid #e7ddc5",
            }}
          >
            Open dashboard
          </button>
        </div>
      </div>
    </div>
  )
}
