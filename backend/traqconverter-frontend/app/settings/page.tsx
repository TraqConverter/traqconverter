"use client"

import { useEffect, useMemo, useState } from "react"
import { api } from "@/lib/api"

// ============================================================
// MEMBERS — ESPRESSO LOOK
// Wired to real backend:
//   GET    /members                  → { team_id, team_name, members[], pending_invites[] }
//   POST   /members/invite { email, role }
//   PATCH  /members/{user_id} { role }
//   DELETE /members/{user_id}
//   DELETE /members/invites/{invite_id}
//
// If the invitee already has an account they are added immediately; otherwise
// a pending invite is stored and auto-accepted on their next register/login.
// ============================================================

type Member = {
  id: string
  email: string
  full_name: string | null
  role: string
  is_owner: boolean
}

type Invite = {
  id: string
  email: string
  role: string
  status: string
  created_at: string | null
}

type Snapshot = {
  team_id: string
  team_name: string
  members: Member[]
  pending_invites: Invite[]
}

const ROLES = [
  { value: "MEMBER", label: "Member" },
  { value: "REVIEWER", label: "Reviewer" },
  { value: "PM", label: "Project manager" },
  { value: "ADMIN", label: "Admin" },
]

const ROLE_LABEL: Record<string, string> = {
  OWNER: "Owner",
  ADMIN: "Admin",
  MEMBER: "Member",
  REVIEWER: "Reviewer",
  PM: "Project manager",
}

function initialsFor(m: { full_name: string | null; email: string }) {
  const n = (m.full_name || "").trim()
  if (n) {
    const parts = n.split(/\s+/).filter(Boolean)
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
    return parts[0].slice(0, 2).toUpperCase()
  }
  return m.email.slice(0, 2).toUpperCase()
}

function relativeTime(iso?: string | null) {
  if (!iso) return "—"
  // Backend returns naive UTC ISO strings without timezone markers.
  // Without this, the browser parses them as local time and rows
  // appear hours older than they actually are.
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(iso)
  const safe = hasTz ? iso : iso + "Z"
  const t = new Date(safe).getTime()
  if (!Number.isFinite(t)) return "—"
  const diff = Date.now() - t
  const m = 60_000, h = 3_600_000, d = 86_400_000
  if (diff < 0) return "just now"
  if (diff < m) return "just now"
  if (diff < h) return `${Math.floor(diff / m)}m ago`
  if (diff < d) return `${Math.floor(diff / h)}h ago`
  if (diff < 7 * d) return `${Math.floor(diff / d)}d ago`
  return new Date(safe).toLocaleDateString()
}

export default function MembersPage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)

  const [showInvite, setShowInvite] = useState(false)
  const [inviteEmail, setInviteEmail] = useState("")
  const [inviteRole, setInviteRole] = useState("MEMBER")

  useEffect(() => {
    fetchMembers()
  }, [])

  const fetchMembers = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await api.get("/members")
      setSnapshot(res.data)
    } catch (err: any) {
      console.error("MEMBERS ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't load your team — try refreshing in a moment."
      )
      setSnapshot(null)
    } finally {
      setLoading(false)
    }
  }

  const sendInvite = async () => {
    const email = inviteEmail.trim().toLowerCase()
    if (!email || !email.includes("@")) {
      setError("Enter a valid email address.")
      return
    }
    try {
      setBusy("invite")
      setError(null)
      const res = await api.post("/members/invite", {
        email,
        role: inviteRole,
      })
      setInviteEmail("")
      setShowInvite(false)
      if (res.data?.added) {
        setFlash(`${email} was added to your team.`)
      } else {
        setFlash(
          `Invite sent to ${email}. They'll join automatically on their next sign in.`
        )
      }
      setTimeout(() => setFlash(null), 5000)
      await fetchMembers()
    } catch (err: any) {
      console.error("INVITE ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't send the invite. Please try again."
      )
    } finally {
      setBusy(null)
    }
  }

  const cancelInvite = async (id: string) => {
    if (!confirm("Cancel this invite?")) return
    try {
      setBusy(`del-invite:${id}`)
      await api.delete(`/members/invites/${id}`)
      setSnapshot((s) =>
        s ? { ...s, pending_invites: s.pending_invites.filter((i) => i.id !== id) } : s
      )
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || "Couldn't cancel that invite."
      )
    } finally {
      setBusy(null)
    }
  }

  const removeMember = async (id: string, email: string) => {
    if (!confirm(`Remove ${email} from the team?`)) return
    try {
      setBusy(`del:${id}`)
      await api.delete(`/members/${id}`)
      setSnapshot((s) =>
        s ? { ...s, members: s.members.filter((m) => m.id !== id) } : s
      )
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || "Couldn't remove that member."
      )
    } finally {
      setBusy(null)
    }
  }

  const changeRole = async (id: string, role: string) => {
    try {
      setBusy(`role:${id}`)
      await api.patch(`/members/${id}`, { role })
      setSnapshot((s) =>
        s
          ? {
              ...s,
              members: s.members.map((m) =>
                m.id === id ? { ...m, role } : m
              ),
            }
          : s
      )
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || "Couldn't update that role."
      )
    } finally {
      setBusy(null)
    }
  }

  const memberCount = snapshot?.members.length ?? 0
  const inviteCount = snapshot?.pending_invites.length ?? 0
  const teamName = snapshot?.team_name || "Your team"

  const hasRoleVariety = useMemo(() => {
    if (!snapshot) return false
    return new Set(snapshot.members.map((m) => m.role)).size > 1
  }, [snapshot])

  return (
    <div className="space-y-6 pb-16">
      {/* BREADCRUMB */}
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span> Account{" "}
        <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <span style={{ color: "#1f2a2e" }}>Members</span>
      </div>

      {/* HEADER */}
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div
            className="text-[11px] font-semibold tracking-[0.18em] mb-1"
            style={{ color: "#9a9178" }}
          >
            MEMBERS
          </div>
          <h1
            className="text-[28px] font-semibold tracking-tight"
            style={{ color: "#1f2a2e" }}
          >
            {teamName}
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            {memberCount} member{memberCount === 1 ? "" : "s"}
            {inviteCount > 0 &&
              ` · ${inviteCount} pending invite${inviteCount === 1 ? "" : "s"}`}
          </p>
        </div>

        <button
          type="button"
          onClick={() => {
            setShowInvite((v) => !v)
            setError(null)
          }}
          className="px-4 py-2.5 rounded-full text-sm font-semibold transition flex items-center gap-2"
          style={{ background: "#0a7870", color: "#fff" }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "#0a645d")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "#0a7870")}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M19 8v6M22 11h-6" />
          </svg>
          {showInvite ? "Close" : "Invite by email"}
        </button>
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

      {/* INVITE PANEL */}
      {showInvite && (
        <div
          className="rounded-2xl p-5"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
        >
          <div
            className="text-[11px] font-semibold tracking-[0.14em] mb-4"
            style={{ color: "#9a9178" }}
          >
            INVITE A NEW MEMBER
          </div>
          <div className="grid grid-cols-1 md:grid-cols-[2fr_1fr_auto] gap-3 items-end">
            <div>
              <div
                className="text-[11px] font-semibold tracking-[0.14em] mb-2"
                style={{ color: "#9a9178" }}
              >
                EMAIL
              </div>
              <div
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl"
                style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#9a9178"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <rect x="3" y="5" width="18" height="14" rx="2" />
                  <path d="m3 7 9 6 9-6" />
                </svg>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendInvite()}
                  placeholder="teammate@company.com"
                  className="flex-1 bg-transparent outline-none text-sm"
                  style={{ color: "#1f2a2e" }}
                />
              </div>
            </div>
            <div>
              <div
                className="text-[11px] font-semibold tracking-[0.14em] mb-2"
                style={{ color: "#9a9178" }}
              >
                ROLE
              </div>
              <div
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl"
                style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
              >
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="bg-transparent outline-none text-sm w-full"
                  style={{ color: "#1f2a2e" }}
                >
                  {ROLES.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <button
              type="button"
              onClick={sendInvite}
              disabled={busy === "invite" || !inviteEmail.trim()}
              className="px-5 py-2.5 rounded-full text-sm font-semibold transition"
              style={{
                background:
                  busy === "invite" || !inviteEmail.trim() ? "#9bc9c5" : "#0a7870",
                color: "#fff",
                cursor:
                  busy === "invite" || !inviteEmail.trim()
                    ? "not-allowed"
                    : "pointer",
              }}
            >
              {busy === "invite" ? "Sending…" : "Send invite"}
            </button>
          </div>
          <p className="text-xs mt-4" style={{ color: "#8a8270" }}>
            If they already have a TraqConverter account, they&apos;ll be added
            instantly. Otherwise we&apos;ll keep the invite pending and add them
            the moment they sign up with this email.
          </p>
        </div>
      )}

      {/* MEMBERS TABLE */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
      >
        <div
          className="grid items-center text-[11px] font-semibold tracking-[0.14em] px-5 py-3"
          style={{
            gridTemplateColumns: "minmax(260px,2fr) 1.5fr 1.2fr 70px",
            background: "#faf5ee",
            borderBottom: "1px solid #f1e8d1",
            color: "#9a9178",
          }}
        >
          <div>MEMBER</div>
          <div>EMAIL</div>
          <div>ROLE</div>
          <div />
        </div>

        {loading ? (
          <div
            className="px-5 py-12 text-center text-sm"
            style={{ color: "#8a8270" }}
          >
            Loading team…
          </div>
        ) : !snapshot || snapshot.members.length === 0 ? (
          <div className="px-5 py-12 text-center text-sm" style={{ color: "#8a8270" }}>
            Your team is just you so far — invite teammates to start
            allocating projects.
          </div>
        ) : (
          snapshot.members.map((m) => (
            <div
              key={m.id}
              className="grid items-center px-5 py-4 text-sm group"
              style={{
                gridTemplateColumns: "minmax(260px,2fr) 1.5fr 1.2fr 70px",
                borderBottom: "1px solid #f4ecd6",
                color: "#1f2a2e",
              }}
            >
              <div className="flex items-center gap-3 min-w-0">
                <div
                  className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-semibold shrink-0"
                  style={{ background: "#cfe6e2", color: "#0a7870" }}
                >
                  {initialsFor(m)}
                </div>
                <div className="min-w-0">
                  <div
                    className="font-semibold truncate"
                    style={{ color: "#1f2a2e" }}
                  >
                    {m.full_name || m.email.split("@")[0]}
                    {m.is_owner && (
                      <span
                        className="ml-2 text-[10px] font-semibold tracking-[0.14em] px-1.5 py-0.5 rounded-full align-middle"
                        style={{ background: "#f6e3b8", color: "#7a5a10" }}
                      >
                        OWNER
                      </span>
                    )}
                  </div>
                  <div className="text-xs truncate" style={{ color: "#8a8270" }}>
                    {m.full_name ? m.email : "—"}
                  </div>
                </div>
              </div>
              <div className="truncate" style={{ color: "#4a4638" }}>
                {m.email}
              </div>
              <div>
                {m.is_owner ? (
                  <span
                    className="inline-flex items-center text-[12px] font-semibold tracking-[0.04em] px-2.5 py-1 rounded-full"
                    style={{
                      background: "#f3ecdb",
                      color: "#6b6558",
                      border: "1px solid #e7ddc5",
                    }}
                  >
                    {ROLE_LABEL[m.role] || m.role}
                  </span>
                ) : (
                  <select
                    value={m.role}
                    disabled={busy === `role:${m.id}`}
                    onChange={(e) => changeRole(m.id, e.target.value)}
                    className="text-[12px] font-medium px-2.5 py-1 rounded-full outline-none transition cursor-pointer"
                    style={{
                      background: "#faf5ee",
                      border: "1px solid #e7ddc5",
                      color: "#1f2a2e",
                    }}
                  >
                    {ROLES.map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="flex justify-end">
                {m.is_owner ? null : (
                  <button
                    type="button"
                    onClick={() => removeMember(m.id, m.email)}
                    disabled={busy === `del:${m.id}`}
                    aria-label="Remove member"
                    title="Remove member"
                    className="opacity-0 group-hover:opacity-100 transition p-1.5 rounded-full"
                    style={{ color: "#b14a3a", background: "transparent" }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.background = "#f9efe9")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.background = "transparent")
                    }
                  >
                    <svg
                      width="15"
                      height="15"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M3 6h18" />
                      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      <path d="M19 6 18 20a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                    </svg>
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {/* PENDING INVITES */}
      {snapshot && snapshot.pending_invites.length > 0 && (
        <div className="space-y-3">
          <div
            className="text-[11px] font-semibold tracking-[0.18em]"
            style={{ color: "#9a9178" }}
          >
            PENDING INVITES
          </div>
          <div
            className="rounded-2xl overflow-hidden"
            style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
          >
            {snapshot.pending_invites.map((inv) => (
              <div
                key={inv.id}
                className="grid items-center px-5 py-4 text-sm group"
                style={{
                  gridTemplateColumns: "minmax(260px,2fr) 1.5fr 1.2fr 70px",
                  borderBottom: "1px solid #f4ecd6",
                  color: "#1f2a2e",
                }}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div
                    className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-semibold shrink-0"
                    style={{ background: "#f3ecdb", color: "#9a9178" }}
                  >
                    {inv.email.slice(0, 2).toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <div
                      className="font-semibold truncate"
                      style={{ color: "#1f2a2e" }}
                    >
                      {inv.email}
                    </div>
                    <div className="text-xs" style={{ color: "#8a8270" }}>
                      Invited {relativeTime(inv.created_at)}
                    </div>
                  </div>
                </div>
                <div className="text-xs" style={{ color: "#8a8270" }}>
                  Will join on next sign-in
                </div>
                <div>
                  <span
                    className="inline-flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.06em] px-2.5 py-1 rounded-full"
                    style={{ background: "#f6e3b8", color: "#7a5a10" }}
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: "#c88a1a" }}
                    />
                    Pending · {ROLE_LABEL[inv.role] || inv.role}
                  </span>
                </div>
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => cancelInvite(inv.id)}
                    disabled={busy === `del-invite:${inv.id}`}
                    aria-label="Cancel invite"
                    title="Cancel invite"
                    className="opacity-0 group-hover:opacity-100 transition p-1.5 rounded-full"
                    style={{ color: "#b14a3a", background: "transparent" }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.background = "#f9efe9")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.background = "transparent")
                    }
                  >
                    <svg
                      width="15"
                      height="15"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M18 6 6 18M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasRoleVariety && (
        <p className="text-xs" style={{ color: "#8a8270" }}>
          Roles are descriptive today — every team member can work on any project
          they&apos;re assigned to. We&apos;ll add per-role permissions in a
          future update.
        </p>
      )}
    </div>
  )
}
