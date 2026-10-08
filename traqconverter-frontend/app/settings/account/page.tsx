"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { api } from "@/lib/api"
import { clearToken, setToken, getRemembered } from "@/lib/auth"
import { resetWallet } from "@/lib/plan"
import SavedInstructionsSection from "@/components/settings/SavedInstructionsSection"
import PaymentsSection from "@/components/settings/PaymentsSection"
import { OPEN_SUPPORT_CHAT } from "@/components/SupportChat"
import { COMPANY } from "@/lib/company"

type Me = {
  id: string
  email: string
  full_name: string | null
  role: string
  subscription_plan?: string
  subscription_status?: string
}

function initialsFor(p: { full_name: string | null; email: string }) {
  const name = (p.full_name || "").trim()
  if (name) {
    const parts = name.split(/\s+/).filter(Boolean)
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
    return parts[0].slice(0, 2).toUpperCase()
  }
  return p.email.slice(0, 2).toUpperCase()
}

export default function AccountSettingsPage() {
  const router = useRouter()

  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const [fullName, setFullName] = useState("")

  const [currentPwd, setCurrentPwd] = useState("")
  const [newPwd, setNewPwd] = useState("")
  const [confirmPwd, setConfirmPwd] = useState("")
  const [showPwd, setShowPwd] = useState(false)

  const [showDelete, setShowDelete] = useState(false)
  const [deletePwd, setDeletePwd] = useState("")
  const [deleteConfirm, setDeleteConfirm] = useState("")

  useEffect(() => {
    fetchMe()
  }, [])

  const fetchMe = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await api.get("/auth/me")
      setMe(res.data)
      setFullName(res.data?.full_name || "")
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          "Couldn't load your profile — try refreshing."
      )
      setMe(null)
    } finally {
      setLoading(false)
    }
  }

  const flashSuccess = (msg: string) => {
    setFlash(msg)
    setTimeout(() => setFlash(null), 4000)
  }

  const saveProfile = async () => {
    try {
      setBusy("profile")
      setError(null)
      const res = await api.patch("/auth/me", {
        full_name: fullName.trim() || null,
      })
      setMe((m) => (m ? { ...m, full_name: res.data?.full_name ?? null } : m))
      flashSuccess("Profile updated.")
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't update your profile.")
    } finally {
      setBusy(null)
    }
  }

  const changePassword = async () => {
    setError(null)
    if (!currentPwd || !newPwd) {
      setError("Fill in both your current and new password.")
      return
    }

    if (newPwd.length < 8) {
      setError("New password must be at least 8 characters.")
      return
    }
    if (newPwd === currentPwd) {
      setError("New password must be different from the current one.")
      return
    }
    if (newPwd !== confirmPwd) {
      setError("New password and confirmation don't match.")
      return
    }
    try {
      setBusy("password")
      const res = await api.post("/auth/change-password", {
        current_password: currentPwd,
        new_password: newPwd,
      })

      const fresh = res.data?.access_token
      if (fresh) setToken(fresh, getRemembered())
      setCurrentPwd("")
      setNewPwd("")
      setConfirmPwd("")
      flashSuccess("Password updated. Other devices have been signed out.")
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || "Couldn't update your password."
      )
    } finally {
      setBusy(null)
    }
  }

  const handleSignOut = async () => {
    if (!confirm("Sign out of OnlineDocTranslator?")) return
    // Same as the sidebar: revoke the token server-side and drop the cached plan.
    try {
      await api.post("/auth/logout")
    } catch {}
    clearToken()
    resetWallet()
    router.replace("/login")
  }

  const handleDelete = async () => {
    setError(null)
    if (deleteConfirm.trim().toUpperCase() !== "DELETE") {
      setError('Type "DELETE" exactly to confirm.')
      return
    }
    if (!deletePwd) {
      setError("Enter your password to delete the account.")
      return
    }
    try {
      setBusy("delete")
      await api.post("/auth/delete-account", {
        password: deletePwd,
        confirm: "DELETE",
      })
      clearToken()
      router.replace("/login")
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          "Couldn't delete the account. Check the password."
      )
    } finally {
      setBusy(null)
    }
  }

  if (loading) {
    return (
      <div className="px-2 py-10" style={{ color: "#6b6558" }}>
        Loading settings…
      </div>
    )
  }

  if (!me) {
    return (
      <div
        className="rounded-xl px-4 py-3 text-sm"
        style={{ background: "#f2d4cf", color: "#7a2f24" }}
      >
        {error || "Failed to load your profile."}
      </div>
    )
  }

  return (
    <div className="space-y-8 pb-16 max-w-3xl">
      {}
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        OnlineDocTranslator <span style={{ color: "#cfc6ad" }}>›</span> Account{" "}
        <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <span style={{ color: "#1f2a2e" }}>Settings</span>
      </div>

      {}
      <div>
        <div
          className="text-[11px] font-semibold tracking-[0.18em] mb-1"
          style={{ color: "#9a9178" }}
        >
          ACCOUNT SETTINGS
        </div>
        <h1
          className="text-[28px] font-semibold tracking-tight"
          style={{ color: "#1f2a2e" }}
        >
          Your account
        </h1>
        <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
          Update your profile, change your password, or close your account.
        </p>
      </div>

      {error && (
        <div
          className="text-sm rounded-lg px-3 py-2"
          style={{ background: "#f2d4cf", color: "#7a2f24" }}
        >
          {error}
        </div>
      )}
      {flash && (
        <div
          className="text-sm rounded-lg px-3 py-2"
          style={{ background: "#d8ead6", color: "#2d5a24" }}
        >
          {flash}
        </div>
      )}

      {}
      <section
        className="rounded-2xl p-6"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
      >
        <SectionHeader
          eyebrow="PROFILE"
          title="Public details"
          subtitle="Your name shows up in comments, member lists, and exported certificates."
        />

        <div className="flex items-center gap-4 mb-6">
          <div
            className="w-16 h-16 rounded-full flex items-center justify-center text-lg font-semibold"
            style={{ background: "#cfe6e2", color: "#0a7870" }}
          >
            {initialsFor({ full_name: fullName, email: me.email })}
          </div>
          <div>
            <div className="text-sm font-semibold" style={{ color: "#1f2a2e" }}>
              {fullName || me.email.split("@")[0]}
            </div>
            <div className="text-xs" style={{ color: "#8a8270" }}>
              {me.role || "USER"}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
          <FieldGroup label="FULL NAME">
            <input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Niki Lawrence"
              className="bg-transparent outline-none text-sm w-full"
              style={{ color: "#1f2a2e" }}
            />
          </FieldGroup>
          <FieldGroup label="EMAIL">
            <input
              value={me.email}
              disabled
              className="bg-transparent outline-none text-sm w-full"
              style={{ color: "#8a8270" }}
              title="Email can't be changed yet"
            />
          </FieldGroup>
        </div>

        <div className="flex justify-end">
          <button
            type="button"
            onClick={saveProfile}
            disabled={
              busy === "profile" ||
              (fullName.trim() || "") === (me.full_name || "")
            }
            className="px-4 py-2 rounded-full text-sm font-semibold transition"
            style={{
              background:
                busy === "profile" ||
                (fullName.trim() || "") === (me.full_name || "")
                  ? "#9bc9c5"
                  : "#0a7870",
              color: "#fff",
              cursor:
                busy === "profile" ||
                (fullName.trim() || "") === (me.full_name || "")
                  ? "not-allowed"
                  : "pointer",
            }}
          >
            {busy === "profile" ? "Saving…" : "Save changes"}
          </button>
        </div>
      </section>

      <SavedInstructionsSection />

      <PaymentsSection />

      <section
        className="rounded-2xl px-6 py-4 flex flex-wrap items-center justify-between gap-3"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
      >
        <div className="text-sm" style={{ color: "#4a4638" }}>
          Logos and stamps now live in Media, one per language if you need them.
        </div>
        <Link
          href="/media"
          className="text-sm font-semibold px-4 py-2 rounded-full transition hover:bg-[#cfe6e2]"
          style={{ border: "1px solid #b7dad4", color: "#0a5e58" }}
        >
          Open Media
        </Link>
      </section>

      <section
        className="rounded-2xl px-6 py-4 flex flex-wrap items-center justify-between gap-3"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
      >
        <div className="text-sm" style={{ color: "#4a4638" }}>
          <span className="font-semibold" style={{ color: "#1f2a2e" }}>
            Help &amp; support:
          </span>{" "}
          email {COMPANY.email}{" "}
          <a href={`mailto:${COMPANY.email}`} className="font-medium hover:underline" style={{ color: "#0a7870" }}>
            (write to us)
          </a>
        </div>
        <button
          type="button"
          onClick={() => window.dispatchEvent(new Event(OPEN_SUPPORT_CHAT))}
          className="text-sm font-semibold px-4 py-2 rounded-full transition hover:bg-[#cfe6e2]"
          style={{ border: "1px solid #b7dad4", color: "#0a5e58" }}
        >
          Ask the Help chat
        </button>
      </section>

      {}
      <section
        className="rounded-2xl p-6"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
      >
        <SectionHeader
          eyebrow="SECURITY"
          title="Change password"
          subtitle="Use at least 8 characters. For your security, other signed-in devices will be signed out."
        />

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <FieldGroup label="CURRENT PASSWORD">
            <input
              type={showPwd ? "text" : "password"}
              value={currentPwd}
              onChange={(e) => setCurrentPwd(e.target.value)}
              autoComplete="current-password"
              className="bg-transparent outline-none text-sm w-full"
              style={{ color: "#1f2a2e" }}
            />
          </FieldGroup>
          <FieldGroup label="NEW PASSWORD">
            <input
              type={showPwd ? "text" : "password"}
              value={newPwd}
              onChange={(e) => setNewPwd(e.target.value)}
              autoComplete="new-password"
              className="bg-transparent outline-none text-sm w-full"
              style={{ color: "#1f2a2e" }}
            />
          </FieldGroup>
          <FieldGroup label="CONFIRM NEW PASSWORD">
            <input
              type={showPwd ? "text" : "password"}
              value={confirmPwd}
              onChange={(e) => setConfirmPwd(e.target.value)}
              autoComplete="new-password"
              className="bg-transparent outline-none text-sm w-full"
              style={{ color: "#1f2a2e" }}
            />
          </FieldGroup>
        </div>

        <div className="flex items-center justify-between mt-4">
          <label className="flex items-center gap-2 text-xs" style={{ color: "#6b6558" }}>
            <input
              type="checkbox"
              checked={showPwd}
              onChange={(e) => setShowPwd(e.target.checked)}
            />
            Show passwords while typing
          </label>
          <button
            type="button"
            onClick={changePassword}
            disabled={busy === "password" || !currentPwd || !newPwd}
            className="px-4 py-2 rounded-full text-sm font-semibold transition"
            style={{
              background:
                busy === "password" || !currentPwd || !newPwd
                  ? "#9bc9c5"
                  : "#0a7870",
              color: "#fff",
              cursor:
                busy === "password" || !currentPwd || !newPwd
                  ? "not-allowed"
                  : "pointer",
            }}
          >
            {busy === "password" ? "Updating…" : "Update password"}
          </button>
        </div>
      </section>

      {}
      <section
        className="rounded-2xl p-6 flex items-center justify-between flex-wrap gap-4"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
      >
        <div>
          <div
            className="text-[11px] font-semibold tracking-[0.18em] mb-1"
            style={{ color: "#9a9178" }}
          >
            SESSION
          </div>
          <div className="text-sm font-semibold" style={{ color: "#1f2a2e" }}>
            Sign out of this browser
          </div>
          <p className="text-xs mt-0.5" style={{ color: "#8a8270" }}>
            Clears your access token. You can sign back in any time.
          </p>
        </div>
        <button
          type="button"
          onClick={handleSignOut}
          className="px-4 py-2 rounded-full text-sm font-semibold transition"
          style={{
            background: "#ffffff",
            color: "#1f2a2e",
            border: "1px solid #e7ddc5",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "#f3ecdb")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "#ffffff")}
        >
          Sign out
        </button>
      </section>

      {}
      <section
        className="rounded-2xl p-6"
        style={{
          background: "#ffffff",
          border: "1px solid #e7b8b0",
          boxShadow: "0 0 0 4px rgba(177,74,58,0.04) inset",
        }}
      >
        <div
          className="text-[11px] font-semibold tracking-[0.18em] mb-1"
          style={{ color: "#b14a3a" }}
        >
          DANGER ZONE
        </div>
        <div className="text-sm font-semibold" style={{ color: "#1f2a2e" }}>
          Delete your account
        </div>
        <p className="text-xs mb-4" style={{ color: "#8a8270" }}>
          Removes your profile, your team, your wallet, and every project you
          own. This action cannot be undone.
        </p>

        {!showDelete ? (
          <button
            type="button"
            onClick={() => setShowDelete(true)}
            className="px-4 py-2 rounded-full text-sm font-semibold transition"
            style={{
              background: "#ffffff",
              color: "#7a2f24",
              border: "1px solid #e7b8b0",
            }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.background = "#f9efe9")
            }
            onMouseLeave={(e) => (e.currentTarget.style.background = "#ffffff")}
          >
            Delete my account
          </button>
        ) : (
          <div
            className="rounded-xl p-4"
            style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
          >
            <div
              className="text-sm font-semibold mb-3"
              style={{ color: "#7a2f24" }}
            >
              This will permanently remove your account, your team and every
              project you own.
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
              <FieldGroup label="PASSWORD">
                <input
                  type="password"
                  value={deletePwd}
                  onChange={(e) => setDeletePwd(e.target.value)}
                  autoComplete="current-password"
                  className="bg-transparent outline-none text-sm w-full"
                  style={{ color: "#1f2a2e" }}
                />
              </FieldGroup>
              <FieldGroup label='TYPE "DELETE" TO CONFIRM'>
                <input
                  value={deleteConfirm}
                  onChange={(e) => setDeleteConfirm(e.target.value)}
                  placeholder="DELETE"
                  className="bg-transparent outline-none text-sm w-full"
                  style={{ color: "#1f2a2e" }}
                />
              </FieldGroup>
            </div>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowDelete(false)
                  setDeletePwd("")
                  setDeleteConfirm("")
                }}
                className="px-4 py-2 rounded-full text-sm font-semibold"
                style={{
                  background: "#ffffff",
                  color: "#1f2a2e",
                  border: "1px solid #e7ddc5",
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={
                  busy === "delete" ||
                  deleteConfirm.trim().toUpperCase() !== "DELETE" ||
                  !deletePwd
                }
                className="px-4 py-2 rounded-full text-sm font-semibold transition"
                style={{
                  background:
                    busy === "delete" ||
                    deleteConfirm.trim().toUpperCase() !== "DELETE" ||
                    !deletePwd
                      ? "#e7b8b0"
                      : "#b14a3a",
                  color: "#fff",
                  cursor:
                    busy === "delete" ||
                    deleteConfirm.trim().toUpperCase() !== "DELETE" ||
                    !deletePwd
                      ? "not-allowed"
                      : "pointer",
                }}
              >
                {busy === "delete" ? "Deleting…" : "Permanently delete"}
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

function SectionHeader({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string
  title: string
  subtitle?: string
}) {
  return (
    <div className="mb-5">
      <div
        className="text-[11px] font-semibold tracking-[0.18em] mb-1"
        style={{ color: "#9a9178" }}
      >
        {eyebrow}
      </div>
      <h2
        className="text-[18px] font-semibold tracking-tight"
        style={{ color: "#1f2a2e" }}
      >
        {title}
      </h2>
      {subtitle && (
        <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
          {subtitle}
        </p>
      )}
    </div>
  )
}

function FieldGroup({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div
        className="text-[11px] font-semibold tracking-[0.14em] mb-2"
        style={{ color: "#9a9178" }}
      >
        {label}
      </div>
      <div
        className="flex items-center gap-2 px-4 py-2.5 rounded-xl"
        style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
      >
        {children}
      </div>
    </div>
  )
}
