"use client"

import { useState, type FormEvent } from "react"
import Link from "next/link"
import { api, apiErrorDetail } from "@/lib/api"
import AuthCard, { AuthButton, AuthField, Notice, inputClass } from "@/components/auth/AuthCard"

const SENT = "If an account exists for that email, we've sent a reset link."

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("")
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!email.trim()) {
      setError("Enter the email you sign in with.")
      return
    }
    try {
      setLoading(true)
      await api.post("/auth/forgot-password", { email: email.trim() })
      setSent(true)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 429) {
        setError("Too many requests. Wait a while and try again.")
      } else if (status === 422) {
        setError("That doesn't look like a valid email address.")
      } else {
        setError(apiErrorDetail(err, "Couldn't send the reset link. Try again."))
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthCard
      title="Forgot your password?"
      subtitle={sent ? undefined : "Enter your email and we'll send you a link to set a new one."}
    >
      {sent ? (
        <>
          <Notice tone="ok">{SENT}</Notice>
          <p className="text-sm mb-6" style={{ color: "#4a4638" }}>
            Check your inbox and spam folder. The link expires in 60 minutes.
          </p>
        </>
      ) : (
        <form onSubmit={submit} noValidate>
          {error && <Notice tone="error">{error}</Notice>}
          <AuthField label="EMAIL">
            <input
              type="email"
              autoComplete="email"
              autoFocus
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
              style={{ color: "#1f2a2e" }}
            />
          </AuthField>
          <div className="mt-6">
            <AuthButton loading={loading} label="Send reset link" loadingLabel="Sending…" />
          </div>
        </form>
      )}
      <div className="text-center mt-5 text-sm" style={{ color: "#8a8270" }}>
        <Link href="/login" className="font-medium hover:underline" style={{ color: "#0a7870" }}>
          Back to sign in
        </Link>
      </div>
    </AuthCard>
  )
}
