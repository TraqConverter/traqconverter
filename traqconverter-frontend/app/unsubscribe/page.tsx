"use client"

import { Suspense, useState } from "react"
import { useSearchParams } from "next/navigation"
import { api } from "@/lib/api"
import AuthCard, { Notice } from "@/components/auth/AuthCard"

type State = "ask" | "working" | "done" | "invalid" | "error"

export default function UnsubscribePage() {
  return (
    <Suspense fallback={null}>
      <Unsubscribe />
    </Suspense>
  )
}

function Unsubscribe() {
  const token = useSearchParams().get("token")
  const [state, setState] = useState<State>(token ? "ask" : "invalid")

  // Needs a click: mail scanners open links on their own and would unsubscribe people by accident.
  const unsubscribe = () => {
    if (!token) return
    setState("working")
    api
      .post("/auth/onboarding-emails/unsubscribe", { token })
      .then(() => setState("done"))
      .catch((err: unknown) => {
        const status = (err as { response?: { status?: number } })?.response?.status
        setState(status === 400 ? "invalid" : "error")
      })
  }

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
        <Notice tone="error">Couldn&apos;t save that. Try again in a minute.</Notice>
      </AuthCard>
    )
  }
  return (
    <AuthCard title="Stop onboarding tips?" subtitle="You won't get any more tips about getting started. Emails about your account, like password resets, still arrive.">
      <button
        type="button"
        onClick={unsubscribe}
        disabled={state === "working"}
        className="w-full rounded-full px-5 py-3 text-[15px] font-semibold"
        style={{ background: "#0a7870", color: "#ffffff", opacity: state === "working" ? 0.7 : 1 }}
      >
        {state === "working" ? "Saving…" : "Stop sending me tips"}
      </button>
    </AuthCard>
  )
}
