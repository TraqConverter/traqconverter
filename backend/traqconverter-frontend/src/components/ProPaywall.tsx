"use client"

import { useRouter } from "next/navigation"

// ============================================================
// Pro paywall — shown on Translation Memory, Glossary and
// Certifications pages when the backend returns 403 because the
// caller's plan doesn't include the feature.
// ============================================================

type Props = {
  feature: "Translation Memory" | "Glossary" | "Certifications"
  description: string
}

export default function ProPaywall({ feature, description }: Props) {
  const router = useRouter()

  return (
    <div className="space-y-6 pb-16">
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span> Assets{" "}
        <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <span style={{ color: "#1f2a2e" }}>{feature}</span>
      </div>

      <div
        className="rounded-2xl p-10 flex flex-col items-center text-center"
        style={{
          background: "#ffffff",
          border: "1px solid #e7ddc5",
          boxShadow: "0 1px 2px rgba(30,30,20,0.04)",
        }}
      >
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center mb-5"
          style={{ background: "#cfe6e2", color: "#0a7870" }}
        >
          <svg
            width="26"
            height="26"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="3" y="11" width="18" height="11" rx="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        </div>

        <div
          className="text-[11px] font-semibold tracking-[0.18em] mb-2"
          style={{ color: "#0a7870" }}
        >
          PRO FEATURE
        </div>
        <h1
          className="text-[26px] font-semibold tracking-tight mb-2"
          style={{ color: "#1f2a2e" }}
        >
          {feature} is available on Pro
        </h1>
        <p
          className="text-sm max-w-md mb-6 leading-relaxed"
          style={{ color: "#6b6558" }}
        >
          {description}
        </p>

        <ul className="text-sm mb-7 space-y-2 max-w-md text-left">
          {[
            "29 credits each month",
            "Translation Memory across projects",
            "Custom Glossary enforcement",
            "Certifications library (ISO 17100, affidavits)",
            "Everything in Basic",
          ].map((b) => (
            <li key={b} className="flex items-start gap-2">
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

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => router.push("/billing")}
            className="px-5 py-2.5 rounded-full text-sm font-semibold transition"
            style={{ background: "#0a7870", color: "#fff" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "#0a645d")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "#0a7870")}
          >
            Upgrade to Pro · €29/mo
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
            Back to dashboard
          </button>
        </div>
      </div>
    </div>
  )
}
