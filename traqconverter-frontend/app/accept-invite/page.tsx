"use client"

import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { api, apiErrorDetail } from "@/lib/api"

type InviteInfo = { team_name: string | null; role: string; invited_by: string | null }

const ROLE_LABEL: Record<string, string> = {
  MEMBER: "Member",
  ADMIN: "Admin",
  PM: "Project manager",
  REVIEWER: "Reviewer",
}

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
  const [invite, setInvite] = useState<InviteInfo | null>(null)
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [busy, setBusy] = useState<"accept" | "decline" | null>(null)
  const [joined, setJoined] = useState(false)

  useEffect(() => {
    if (!token) return
    let cancelled = false
    api
      .get<InviteInfo>("/members/invites/lookup", { params: { token } })
      .then((res) => {
        if (!cancelled) setInvite(res.data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setResult({ ok: false, message: apiErrorDetail(err, "Couldn't open this invite.") })
      })
    return () => {
      cancelled = true
    }
  }, [token])

  const respond = async (answer: "accept" | "decline") => {
    if (!token) return
    setBusy(answer)
    try {
      await api.post(`/members/invites/${answer}`, { token })
      if (answer === "accept") {
        setJoined(true)
        setResult({ ok: true, message: "You've joined the team. Taking you to your dashboard…" })
        window.dispatchEvent(new Event("sidebar:refresh"))
        setTimeout(() => router.replace("/dashboard"), 1500)
      } else {
        setResult({ ok: true, message: "Invite declined. You won't be added to the team." })
      }
    } catch (err: unknown) {
      setResult({ ok: false, message: apiErrorDetail(err, `Couldn't ${answer} this invite.`) })
    } finally {
      setBusy(null)
    }
  }

  const message = !token ? { ok: false, message: "This invite link is missing its token." } : result

  return (
    <div className="max-w-md mx-auto py-20 text-center">
      <h1 className="text-xl font-semibold mb-3" style={{ color: "#1f2a2e" }}>
        Team invite
      </h1>
      {message ? (
        <p
          className="text-sm rounded-lg px-3 py-2 mb-6"
          style={message.ok ? { background: "#d8ead6", color: "#2d5a24" } : { background: "#f2d4cf", color: "#7a2f24" }}
        >
          {message.message}
        </p>
      ) : !invite ? (
        <p className="text-sm mb-6" style={{ color: "#8a8270" }}>
          Loading the invite…
        </p>
      ) : (
        <>
          <p className="text-sm mb-6" style={{ color: "#4a4638" }}>
            {invite.invited_by ? `${invite.invited_by} invited you` : "You've been invited"} to join{" "}
            <strong>{invite.team_name || "a team"}</strong> as{" "}
            <strong>{ROLE_LABEL[invite.role] || invite.role}</strong>. You join only if you accept.
          </p>
          <div className="flex gap-2 justify-center">
            <button
              type="button"
              onClick={() => void respond("decline")}
              disabled={busy !== null}
              className="px-4 py-2 rounded-full text-sm font-semibold"
              style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
            >
              {busy === "decline" ? "Declining…" : "Decline"}
            </button>
            <button
              type="button"
              onClick={() => void respond("accept")}
              disabled={busy !== null}
              className="px-4 py-2 rounded-full text-sm font-semibold"
              style={{ background: "#0a7870", color: "#fff", opacity: busy === "accept" ? 0.7 : 1 }}
            >
              {busy === "accept" ? "Joining…" : "Accept and join"}
            </button>
          </div>
        </>
      )}
      {message && !joined && (
        <button
          type="button"
          onClick={() => router.replace("/dashboard")}
          className="mt-2 px-4 py-2 rounded-full text-sm font-semibold"
          style={{ background: "#0a7870", color: "#fff" }}
        >
          Go to dashboard
        </button>
      )}
    </div>
  )
}
