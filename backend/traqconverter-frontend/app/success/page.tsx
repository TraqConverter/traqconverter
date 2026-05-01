"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"

// ============================================================
// Stripe redirects here after a successful checkout. We poll the
// wallet for the new tier (the webhook lands a few seconds after
// payment confirmation) and bounce the user to /billing once we see it.
// ============================================================

const POLL_INTERVAL_MS = 1500
const MAX_POLLS = 20 // ~30s total before we stop polling

export default function CheckoutSuccessPage() {
  const router = useRouter()
  const [tier, setTier] = useState<string | null>(null)
  const [tries, setTries] = useState(0)
  const [stillWaiting, setStillWaiting] = useState(false)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const poll = async () => {
      try {
        const res = await api.get("/billing/wallet")
        if (cancelled) return
        const t = (res.data?.tier || "").toUpperCase()
        setTier(t)

        if (t === "PRO" || t === "BASIC") {
          // Webhook applied. Send them to billing so they see the new state.
          setTimeout(() => router.push("/billing"), 800)
          return
        }

        setTries((n) => n + 1)
      } catch {
        // Ignore — try again. The interceptor handles auth.
      }

      if (!cancelled) {
        timer = setTimeout(poll, POLL_INTERVAL_MS)
      }
    }

    poll()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [router])

  useEffect(() => {
    if (tries >= MAX_POLLS) setStillWaiting(true)
  }, [tries])

  const upgraded = tier === "PRO" || tier === "BASIC"

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
            : "Thanks for your payment"}
        </h1>
        <p
          className="text-sm leading-relaxed mb-6"
          style={{ color: "#6b6558" }}
        >
          {upgraded
            ? "Your credits are loaded and your features are unlocked. Redirecting you to billing…"
            : stillWaiting
            ? "Stripe usually confirms payments within a few seconds. If your plan still doesn't update, refresh this page or check your Stripe dashboard."
            : "We're confirming your subscription with Stripe — this normally takes 5–10 seconds."}
        </p>

        {!upgraded && !stillWaiting && (
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
