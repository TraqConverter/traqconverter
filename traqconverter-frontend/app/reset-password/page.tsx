"use client"

import { Suspense, useState, type FormEvent } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { api, apiErrorDetail } from "@/lib/api"
import { clearToken } from "@/lib/auth"
import AuthCard, { AuthButton, AuthField, Notice, inputClass } from "@/components/auth/AuthCard"

const INVALID = "This reset link is invalid or has expired."

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPassword />
    </Suspense>
  )
}

function ResetPassword() {
  const router = useRouter()
  const token = useSearchParams().get("token")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [show, setShow] = useState(false)
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [linkDead, setLinkDead] = useState(!token)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password.length < 8) {
      setError("Use at least 8 characters.")
      return
    }
    if (!password.trim()) {
      setError("The password can't be only spaces.")
      return
    }
    if (password !== confirm) {
      setError("The two passwords don't match.")
      return
    }
    try {
      setLoading(true)
      await api.post("/auth/reset-password", { token, new_password: password })
      // Every session was signed out by the reset, this one included.
      clearToken()
      setDone(true)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 400) {
        setLinkDead(true)
      } else if (status === 429) {
        setError("Too many attempts. Wait a few minutes and try again.")
      } else if (status === 422) {
        setError("Use 8 to 128 characters, not only spaces.")
      } else {
        setError(apiErrorDetail(err, "Couldn't update the password. Try again."))
      }
    } finally {
      setLoading(false)
    }
  }

  if (done) {
    return (
      <AuthCard title="Password updated" subtitle="You can now sign in with your new password.">
        <button
          type="button"
          onClick={() => router.push("/login")}
          className="w-full py-3 rounded-full text-[15px] font-semibold transition hover:brightness-95"
          style={{ background: "#0a7870", color: "#fff" }}
        >
          Go to sign in
        </button>
      </AuthCard>
    )
  }

  if (linkDead) {
    return (
      <AuthCard title="Link not valid">
        <Notice tone="error">{INVALID}</Notice>
        <Link
          href="/forgot-password"
          className="block w-full text-center py-3 rounded-full text-[15px] font-semibold hover:brightness-95"
          style={{ background: "#0a7870", color: "#fff" }}
        >
          Request a new link
        </Link>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Set a new password" subtitle="Choose a password with at least 8 characters.">
      <form onSubmit={submit} noValidate>
        {error && <Notice tone="error">{error}</Notice>}
        <AuthField label="NEW PASSWORD">
          <input
            type={show ? "text" : "password"}
            autoComplete="new-password"
            autoFocus
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
            style={{ color: "#1f2a2e" }}
          />
        </AuthField>
        <AuthField label="CONFIRM PASSWORD">
          <input
            type={show ? "text" : "password"}
            autoComplete="new-password"
            minLength={8}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className={inputClass}
            style={{ color: "#1f2a2e" }}
          />
        </AuthField>
        <label className="flex items-center gap-2 mb-6 text-sm cursor-pointer select-none" style={{ color: "#4a4638" }}>
          <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} style={{ accentColor: "#0a7870" }} />
          Show passwords
        </label>
        <AuthButton loading={loading} label="Set new password" loadingLabel="Saving…" />
      </form>
    </AuthCard>
  )
}
