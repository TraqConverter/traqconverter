"use client"

import { Suspense, useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import { api } from "@/lib/api"
import AuthCard, { Notice } from "@/components/auth/AuthCard"

type State = "working" | "done" | "invalid" | "error"

export default function UnsubscribePage() {
  return (
    <Suspense fallback={null}>
      <Unsubscribe />
    </Suspense>
  )
}

function Unsubscribe() {
  const token = useSearchParams().get("token")
  const [state, setState] = useState<State>(token ? "working" : "invalid")

  useEffect(() => {
    if (!token) return
    api
      .post("/auth/onboarding-emails/unsubscribe", { token })
      .then(() => setState("done"))
      .catch((err: unknown) => {
        const status = (err as { response?: { status?: number } })?.response?.status
        setState(status === 400 ? "invalid" : "error")
      })
  }, [token])

  if (state === "done") {
    return (
      <AuthCard
        title="No more tips"
        subtitle="You won't get any more onboarding emails from us. Emails about your account, like password resets, still arrive."
      >
        {null}
      </AuthCard>
    )
  }
  if (state === "invalid") {
    return (
      <AuthCard title="Link not valid">
        <Notice tone="error">This link is not valid. Reply to any of our emails and we&apos;ll stop them by hand.</Notice>
      </AuthCard>
    )
  }
  if (state === "error") {
    return (
      <AuthCard title="Something went wrong">
        <Notice tone="error">Couldn&apos;t save that. Open the link again in a minute.</Notice>
      </AuthCard>
    )
  }
  return <AuthCard title="One moment…">{null}</AuthCard>
}
