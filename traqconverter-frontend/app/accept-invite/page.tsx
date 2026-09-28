"use client"

import { Suspense, useEffect, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { api, apiErrorDetail } from "@/lib/api"

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={null}>
      <AcceptInvite />
    </Suspense>
  )
}

function AcceptInvite() {
  const router = useRouter()
  const token = useSearchParams().get("token")
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)
  // Strict Mode runs effects twice in dev; a second POST would fail on a spent token.
  const started = useRef(false)

  useEffect(() => {
    if (!token || started.current) return
    started.current = true
    api
      .post("/members/invites/accept", { token })
      .then(() => {
        setResult({ ok: true, message: "You've joined the team. Taking you to your dashboard…" })
        window.dispatchEvent(new Event("sidebar:refresh"))
        setTimeout(() => router.replace("/dashboard"), 1500)
      })
      .catch((err: unknown) => {
        setResult({ ok: false, message: apiErrorDetail(err, "Couldn't accept this invite.") })
      })
  }, [token, router])

  const message = !token
    ? { ok: false, message: "This invite link is missing its token." }
    : result

  return (
    <div className="max-w-md mx-auto py-20 text-center">
      <h1 className="text-xl font-semibold mb-3" style={{ color: "#1f2a2e" }}>
        Team invite
      </h1>
      <p
        className="text-sm rounded-lg px-3 py-2 mb-6"
        style={
          !message
            ? { color: "#8a8270" }
            : message.ok
              ? { background: "#d8ead6", color: "#2d5a24" }
              : { background: "#f2d4cf", color: "#7a2f24" }
        }
      >
        {message ? message.message : "Accepting invite…"}
      </p>
      {message && !message.ok && (
        <button
          type="button"
          onClick={() => router.replace("/dashboard")}
          className="px-4 py-2 rounded-full text-sm font-semibold"
          style={{ background: "#0a7870", color: "#fff" }}
        >
          Go to dashboard
        </button>
      )}
    </div>
  )
}
