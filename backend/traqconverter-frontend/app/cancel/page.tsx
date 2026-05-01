"use client"

import { useRouter } from "next/navigation"

// Stripe redirects here when the user closes Checkout without paying.
// We just confirm nothing was charged and offer easy recovery.
export default function CheckoutCancelPage() {
  const router = useRouter()

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
          style={{ background: "#f3ecdb", color: "#9a9178" }}
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
            <circle cx="12" cy="12" r="10" />
            <line x1="15" y1="9" x2="9" y2="15" />
            <line x1="9" y1="9" x2="15" y2="15" />
          </svg>
        </div>

        <div
          className="text-[11px] font-semibold tracking-[0.18em] mb-1"
          style={{ color: "#9a9178" }}
        >
          CHECKOUT CANCELLED
        </div>
        <h1
          className="text-[24px] font-semibold tracking-tight mb-2"
          style={{ color: "#1f2a2e" }}
        >
          No payment was made
        </h1>
        <p
          className="text-sm leading-relaxed mb-6"
          style={{ color: "#6b6558" }}
        >
          You closed the checkout before finishing — your card wasn&apos;t
          charged and your plan stays the same. Pick up where you left off
          whenever you&apos;re ready.
        </p>

        <div className="flex items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => router.push("/billing")}
            className="px-4 py-2 rounded-full text-sm font-semibold"
            style={{ background: "#0a7870", color: "#fff" }}
          >
            Back to billing
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
