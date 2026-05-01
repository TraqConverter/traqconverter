"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { setToken, getRemembered } from "@/lib/auth"

// ============================================================
// LOGIN — ESPRESSO LOOK
// ============================================================

function IconMail() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </svg>
  )
}

function IconLock() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="11" width="16" height="10" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  )
}

function IconEye({ open }: { open: boolean }) {
  return open ? (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ) : (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m3 3 18 18" />
      <path d="M10.6 6.1a10.5 10.5 0 0 1 1.4-.1c6.5 0 10 7 10 7a16.6 16.6 0 0 1-3.3 4.1" />
      <path d="M6.6 6.6A16.4 16.4 0 0 0 2 12s3.5 7 10 7c1.6 0 3-.3 4.3-.9" />
    </svg>
  )
}

function Check({ checked }: { checked: boolean }) {
  return (
    <span
      className="inline-flex items-center justify-center transition"
      style={{
        width: 18,
        height: 18,
        borderRadius: 5,
        background: checked ? "#0a7870" : "#ffffff",
        border: `1.5px solid ${checked ? "#0a7870" : "#cfc6ad"}`,
      }}
    >
      {checked && (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <path d="m5 12 5 5 10-10" />
        </svg>
      )}
    </span>
  )
}

export default function LoginPage() {
  const router = useRouter()

  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [remember, setRemember] = useState(true)
  const [showPwd, setShowPwd] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setRemember(getRemembered())
  }, [])

  const handleLogin = async () => {
    setError(null)
    if (!email || !password) {
      setError("Please enter your email and password.")
      return
    }
    try {
      setLoading(true)
      const res = await api.post("/auth/login", { email, password })
      const { access_token } = res.data
      if (!access_token) throw new Error("No token returned")
      setToken(access_token, remember)
      router.push("/dashboard")
    } catch (err: any) {
      console.error("LOGIN ERROR:", err)
      const message = err?.response?.data?.detail || "Invalid email or password."
      setError(typeof message === "string" ? message : "Invalid credentials.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex" style={{ background: "#faf5ee", color: "#1f2a2e" }}>
      {/* LEFT — BRAND PANEL */}
      <div
        className="hidden md:flex flex-col justify-between p-10 flex-1 max-w-[520px]"
        style={{ background: "#f3ecdb", borderRight: "1px solid #e7ddc5" }}
      >
        <div>
          <div className="flex items-center gap-3 mb-12">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center text-white font-bold text-lg" style={{ background: "#0a7870" }}>T</div>
            <div className="leading-tight">
              <div className="font-semibold text-[17px]">TraqConverter</div>
              <div className="text-[10px] tracking-[0.18em]" style={{ color: "#8a8270" }}>WORKSPACE</div>
            </div>
          </div>
          <div className="text-[11px] font-semibold tracking-[0.18em] mb-4" style={{ color: "#9a9178" }}>CERTIFIED TRANSLATION · CAT WORKBENCH</div>
          <h2 className="text-[34px] font-semibold leading-tight tracking-tight mb-5" style={{ color: "#1f2a2e" }}>
            Translate, review and certify documents in one place.
          </h2>
          <p className="text-[15px]" style={{ color: "#4a4638" }}>
            OCR, translation memory, glossary control and signed delivery.
          </p>
        </div>
        <div className="space-y-3">
          <Bullet text="ISO 17100 · SOC 2 · 14-day free revisions" />
          <Bullet text="Tab-to-apply matches, keyboard-first editor" />
        </div>
      </div>

      {/* RIGHT — FORM */}
      <div className="flex-1 flex items-center justify-center p-6">
        <div
          className="w-full max-w-md rounded-2xl p-8"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5", boxShadow: "0 1px 2px rgba(30,30,20,0.04)" }}
        >
          <div className="md:hidden flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center text-white font-bold text-lg" style={{ background: "#0a7870" }}>T</div>
            <div className="leading-tight">
              <div className="font-semibold text-[17px]">TraqConverter</div>
              <div className="text-[10px] tracking-[0.18em]" style={{ color: "#8a8270" }}>WORKSPACE</div>
            </div>
          </div>
          <h1 className="text-[26px] font-semibold tracking-tight mb-1" style={{ color: "#1f2a2e" }}>Welcome back</h1>
          <p className="text-sm mb-6" style={{ color: "#8a8270" }}>Sign in to continue to your workspace.</p>

          {error && (
            <div className="text-sm rounded-lg px-3 py-2 mb-4" style={{ background: "#f2d4cf", color: "#7a2f24" }}>{error}</div>
          )}

          <Field label="EMAIL" icon={<IconMail />}>
            <input
              type="email"
              autoComplete="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleLogin()}
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: "#1f2a2e" }}
            />
          </Field>

          <Field
            label="PASSWORD"
            icon={<IconLock />}
            trailing={
              <button type="button" onClick={() => setShowPwd((v) => !v)} aria-label={showPwd ? "Hide password" : "Show password"} className="p-1 -mr-1">
                <IconEye open={showPwd} />
              </button>
            }
          >
            <input
              type={showPwd ? "text" : "password"}
              autoComplete="current-password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleLogin()}
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: "#1f2a2e" }}
            />
          </Field>

          <div className="flex items-center justify-between mb-6">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="sr-only" />
              <Check checked={remember} />
              <span className="text-sm" style={{ color: "#4a4638" }}>Remember me</span>
            </label>
            <button
              type="button"
              className="text-sm hover:underline"
              style={{ color: "#0a7870" }}
              onClick={() => alert("Password reset is not configured yet — ping your admin.")}
            >
              Forgot password?
            </button>
          </div>

          <button
            onClick={handleLogin}
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-full text-[15px] font-semibold transition"
            style={{
              background: loading ? "#9bc9c5" : "#0a7870",
              color: "#fff",
              cursor: loading ? "not-allowed" : "pointer",
            }}
            onMouseEnter={(e) => { if (!loading) e.currentTarget.style.background = "#0a645d" }}
            onMouseLeave={(e) => { if (!loading) e.currentTarget.style.background = "#0a7870" }}
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>

          <div className="text-center mt-5 text-sm" style={{ color: "#8a8270" }}>
            Don&apos;t have an account?{" "}
            <button type="button" onClick={() => router.push("/register")} className="font-medium hover:underline" style={{ color: "#0a7870" }}>
              Create one
            </button>
          </div>

          <div className="text-[11px] text-center mt-8" style={{ color: "#9a9178" }}>
            Encrypted at rest · SOC 2 compliant
          </div>
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  icon,
  trailing,
  children,
}: {
  label: string
  icon: React.ReactNode
  trailing?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="mb-4">
      <div className="text-[11px] font-semibold tracking-[0.14em] mb-2" style={{ color: "#9a9178" }}>{label}</div>
      <div
        className="flex items-center gap-2 px-4 py-2.5 rounded-xl transition"
        style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
      >
        {icon}
        {children}
        {trailing}
      </div>
    </div>
  )
}

function Bullet({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 w-5 h-5 rounded-full flex items-center justify-center shrink-0" style={{ background: "#cfe6e2", color: "#0a7870" }}>
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <path d="m5 12 5 5 10-10" />
        </svg>
      </span>
      <span className="text-sm" style={{ color: "#4a4638" }}>{text}</span>
    </div>
  )
}
