"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"

// ============================================================
// PROJECTS LIST — ESPRESSO LOOK
// Data: GET /projects/ →
// [{ id, filename, status, progress, source_lang, target_lang,
//    page_count, credits_used, created_at }]
// Click a row → /editor/{id}
// ============================================================

type Assignee = {
  id: string
  email: string
  full_name: string | null
}

type Project = {
  id: string
  filename: string
  status: string
  review_status?: string
  progress: number
  source_lang: string
  target_lang: string
  page_count: number
  credits_used: number
  created_at: string
  assignee_id: string | null
  assignee: Assignee | null
}

// The pill the user sees is derived from BOTH axes: `status` (worker
// progress: PENDING/PROCESSING/COMPLETED/FAILED) and `review_status`
// (human sign-off: DRAFT/IN_REVIEW/CERTIFIED). When the worker is
// done we look at review_status instead so a fresh translation sits
// in "Awaiting review" until a person certifies it.
function effectiveStatus(p: { status?: string; review_status?: string }) {
  const s = (p.status || "").toUpperCase()
  if (s === "FAILED" || s === "PENDING" || s === "PROCESSING") return s
  if (s === "COMPLETED") {
    const r = (p.review_status || "").toUpperCase()
    if (r === "CERTIFIED") return "CERTIFIED"
    if (r === "IN_REVIEW") return "IN_REVIEW"
    // Fall back to "Delivered" for legacy rows whose worker ran
    // before the IN_REVIEW flip was wired up.
    return "COMPLETED"
  }
  return s || "PENDING"
}

type Member = {
  id: string
  email: string
  full_name: string | null
  role: string
  is_owner: boolean
}

type StatusFilter = "all" | "active" | "review" | "delivered"

const STATUS_STYLES: Record<
  string,
  { bg: string; dot: string; text: string; label: string }
> = {
  PENDING:    { bg: "#ede3cc", dot: "#9a9178", text: "#6b6558", label: "Queued" },
  PROCESSING: { bg: "#cfe6e2", dot: "#0a7870", text: "#0a5e58", label: "Translating" },
  IN_REVIEW:  { bg: "#f6e3b8", dot: "#c88a1a", text: "#7a5a10", label: "In review" },
  COMPLETED:  { bg: "#d8ead6", dot: "#4a8a3a", text: "#2d5a24", label: "Delivered" },
  CERTIFIED:  { bg: "#d8ead6", dot: "#4a8a3a", text: "#2d5a24", label: "Certified" },
  FAILED:     { bg: "#f2d4cf", dot: "#b14a3a", text: "#7a2f24", label: "Failed" },
}

function statusStyle(status?: string) {
  const key = (status || "PENDING").toUpperCase()
  return STATUS_STYLES[key] || STATUS_STYLES.PENDING
}

// Map BCP-47-ish language strings → tidy display chip
function langChip(raw?: string) {
  if (!raw) return "—"
  const s = raw.trim()
  // Already short codes
  if (s.length <= 5 && /^[a-z]/i.test(s)) return s.toLowerCase()
  // Known full names → codes
  const map: Record<string, string> = {
    english: "en",
    spanish: "es",
    french: "fr",
    german: "de",
    italian: "it",
    portuguese: "pt",
    dutch: "nl",
    polish: "pl",
    chinese: "zh",
    japanese: "ja",
    arabic: "ar",
  }
  return map[s.toLowerCase()] || s.slice(0, 2).toLowerCase()
}

function relativeTime(iso?: string) {
  if (!iso) return "—"
  // The backend stores created_at as a naive UTC datetime, so the
  // serialised string can come through without a timezone marker
  // (e.g. "2026-05-25T12:45:43.627"). new Date() of that interprets
  // it as LOCAL time, which made everything appear hours older than
  // it really is. If the string has no Z and no ±offset, append Z
  // so it's parsed as UTC.
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

export default function JobsPage() {
  const router = useRouter()

  const [projects, setProjects] = useState<Project[]>([])
  const [members, setMembers] = useState<Member[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<StatusFilter>("all")
  const [query, setQuery] = useState("")
  const [assigningId, setAssigningId] = useState<string | null>(null)
  const [assignBusy, setAssignBusy] = useState<string | null>(null)

  useEffect(() => {
    fetchJobs()
    fetchMembers()
  }, [])

  // Close the assign popover on outside click
  useEffect(() => {
    if (!assigningId) return
    const onClick = () => setAssigningId(null)
    window.addEventListener("click", onClick)
    return () => window.removeEventListener("click", onClick)
  }, [assigningId])

  const fetchJobs = async () => {
    try {
      setLoading(true)
      // Trailing slash matters — backend has /projects/ to avoid 307
      const res = await api.get("/projects/")
      setProjects(res.data || [])
    } catch (err: any) {
      console.error("PROJECTS ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't load your projects — try refreshing in a moment."
      )
    } finally {
      setLoading(false)
    }
  }

  const fetchMembers = async () => {
    try {
      const res = await api.get("/members")
      setMembers(res.data?.members || [])
    } catch {
      // Non-critical — assign popover just won't show options.
      setMembers([])
    }
  }

  const assignProject = async (projectId: string, assigneeId: string | null) => {
    try {
      setAssignBusy(projectId)
      const res = await api.patch(`/projects/${projectId}/assign`, {
        assignee_id: assigneeId,
      })
      const newId: string | null = res.data?.assignee_id ?? null
      const newAssignee = newId
        ? members.find((m) => m.id === newId) || null
        : null
      setProjects((ps) =>
        ps.map((p) =>
          p.id === projectId
            ? {
                ...p,
                assignee_id: newId,
                assignee: newAssignee
                  ? {
                      id: newAssignee.id,
                      email: newAssignee.email,
                      full_name: newAssignee.full_name,
                    }
                  : null,
              }
            : p
        )
      )
      setAssigningId(null)
    } catch (err: any) {
      console.error("ASSIGN ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't update the assignee. Please try again."
      )
    } finally {
      setAssignBusy(null)
    }
  }

  const counts = useMemo(() => {
    const c = { all: projects.length, active: 0, review: 0, delivered: 0 }
    for (const p of projects) {
      const s = effectiveStatus(p)
      if (s === "PROCESSING" || s === "PENDING") c.active++
      else if (s === "IN_REVIEW") c.review++
      else if (s === "COMPLETED" || s === "CERTIFIED") c.delivered++
    }
    return c
  }, [projects])

  const visible = useMemo(() => {
    let list = projects
    if (tab === "active") {
      list = list.filter((p) => {
        const s = effectiveStatus(p)
        return s === "PROCESSING" || s === "PENDING"
      })
    } else if (tab === "review") {
      list = list.filter((p) => effectiveStatus(p) === "IN_REVIEW")
    } else if (tab === "delivered") {
      list = list.filter((p) => {
        const s = effectiveStatus(p)
        return s === "COMPLETED" || s === "CERTIFIED"
      })
    }
    if (query.trim()) {
      const q = query.toLowerCase()
      list = list.filter((p) =>
        (p.filename || "").toLowerCase().includes(q) ||
        (p.source_lang || "").toLowerCase().includes(q) ||
        (p.target_lang || "").toLowerCase().includes(q)
      )
    }
    return list
  }, [projects, tab, query])

  return (
    <div className="space-y-6 pb-16">
      {/* BREADCRUMB */}
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <span style={{ color: "#1f2a2e" }}>Projects</span>
      </div>

      {/* HEADER */}
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h1
            className="text-[28px] font-semibold tracking-tight"
            style={{ color: "#1f2a2e" }}
          >
            Projects
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            All your translation jobs, sorted by most recent.
          </p>
        </div>
        <button
          type="button"
          onClick={() => router.push("/new-translation")}
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
            <path d="M12 5v14M5 12h14" />
          </svg>
          New project
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

      {/* TOOLBAR: tabs + search */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div
          className="flex items-center gap-1 p-1 rounded-full"
          style={{ background: "#f3ecdb", border: "1px solid #e7ddc5" }}
        >
          <TabButton
            label="All"
            count={counts.all}
            active={tab === "all"}
            onClick={() => setTab("all")}
          />
          <TabButton
            label="In progress"
            count={counts.active}
            active={tab === "active"}
            onClick={() => setTab("active")}
          />
          <TabButton
            label="Awaiting review"
            count={counts.review}
            active={tab === "review"}
            onClick={() => setTab("review")}
          />
          <TabButton
            label="Delivered"
            count={counts.delivered}
            active={tab === "delivered"}
            onClick={() => setTab("delivered")}
          />
        </div>

        <div
          className="flex items-center gap-2 px-4 py-2 rounded-full w-72"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#9a9178"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            placeholder="Search by file or language…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 bg-transparent outline-none text-sm"
            style={{ color: "#1f2a2e" }}
          />
        </div>
      </div>

      {/* TABLE */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
      >
        <div
          className="grid items-center text-[11px] font-semibold tracking-[0.14em] px-5 py-3"
          style={{
            gridTemplateColumns:
              "minmax(260px,2.2fr) 1fr 1fr 1.3fr 1.1fr 0.8fr 0.9fr 40px",
            background: "#faf5ee",
            borderBottom: "1px solid #f1e8d1",
            color: "#9a9178",
          }}
        >
          <div>PROJECT</div>
          <div>LANGUAGES</div>
          <div>STATUS</div>
          <div>PROGRESS</div>
          <div>ASSIGNEE</div>
          <div className="text-right">PAGES</div>
          <div className="text-right">CREATED</div>
          <div />
        </div>

        {loading ? (
          <div
            className="px-5 py-12 text-center text-sm"
            style={{ color: "#8a8270" }}
          >
            Loading projects…
          </div>
        ) : visible.length === 0 ? (
          <EmptyState
            isFiltered={tab !== "all" || query.trim().length > 0}
            onCreate={() => router.push("/new-translation")}
            onReset={() => {
              setTab("all")
              setQuery("")
            }}
          />
        ) : (
          visible.map((p) => {
            const st = statusStyle(effectiveStatus(p))
            const progress = Math.max(0, Math.min(100, p.progress || 0))
            return (
              <div
                key={p.id}
                role="button"
                tabIndex={0}
                onClick={() => router.push(`/editor/${p.id}`)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") router.push(`/editor/${p.id}`)
                }}
                className="w-full text-left grid items-center px-5 py-4 transition cursor-pointer"
                style={{
                  gridTemplateColumns:
                    "minmax(260px,2.2fr) 1fr 1fr 1.3fr 1.1fr 0.8fr 0.9fr 40px",
                  borderBottom: "1px solid #f4ecd6",
                  color: "#1f2a2e",
                  background: "#ffffff",
                }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.background = "#fbf6ea")
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.background = "#ffffff")
                }
              >
                {/* PROJECT */}
                <div className="flex items-center gap-3 min-w-0">
                  <div
                    className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                    style={{ background: "#f3ecdb", color: "#6b6558" }}
                  >
                    <svg
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
                      <path d="M14 2v6h6" />
                      <path d="M9 13h6M9 17h6M9 9h2" />
                    </svg>
                  </div>
                  <div className="min-w-0">
                    <div
                      className="font-semibold truncate"
                      style={{ color: "#1f2a2e" }}
                    >
                      {p.filename || "Untitled document"}
                    </div>
                    <div
                      className="text-xs truncate"
                      style={{ color: "#8a8270" }}
                    >
                      {p.credits_used
                        ? `${p.credits_used} credit${p.credits_used === 1 ? "" : "s"}`
                        : "—"}{" "}
                      ·{" "}
                      <span className="font-mono" title={p.id}>
                        {p.id.slice(0, 8)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* LANGUAGES */}
                <div className="flex items-center gap-1.5">
                  <LangChip text={langChip(p.source_lang)} />
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="#9a9178"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                  <LangChip text={langChip(p.target_lang)} />
                </div>

                {/* STATUS */}
                <div>
                  <span
                    className="inline-flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.04em] px-2.5 py-1 rounded-full"
                    style={{ background: st.bg, color: st.text }}
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: st.dot }}
                    />
                    {st.label}
                  </span>
                </div>

                {/* PROGRESS */}
                <div className="flex items-center gap-3">
                  <div
                    className="flex-1 h-1.5 rounded-full overflow-hidden"
                    style={{ background: "#f1e8d1" }}
                  >
                    <div
                      className="h-full transition-all"
                      style={{
                        width: `${progress}%`,
                        background:
                          progress >= 100
                            ? "#4a8a3a"
                            : progress > 0
                            ? "#0a7870"
                            : "#cfc6ad",
                      }}
                    />
                  </div>
                  <div
                    className="text-xs tabular-nums w-10 text-right"
                    style={{ color: "#6b6558" }}
                  >
                    {progress}%
                  </div>
                </div>

                {/* ASSIGNEE */}
                <div
                  className="relative"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      setAssigningId(assigningId === p.id ? null : p.id)
                    }}
                    className="flex items-center gap-2 max-w-full text-left transition"
                    style={{ color: "#1f2a2e" }}
                  >
                    {p.assignee ? (
                      <>
                        <div
                          className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold shrink-0"
                          style={{ background: "#cfe6e2", color: "#0a7870" }}
                        >
                          {(() => {
                            const name = (p.assignee.full_name || "").trim()
                            if (name) {
                              const parts = name.split(/\s+/).filter(Boolean)
                              return parts.length >= 2
                                ? (parts[0][0] + parts[1][0]).toUpperCase()
                                : parts[0].slice(0, 2).toUpperCase()
                            }
                            return p.assignee.email.slice(0, 2).toUpperCase()
                          })()}
                        </div>
                        <span
                          className="text-xs truncate"
                          style={{ color: "#4a4638" }}
                        >
                          {p.assignee.full_name ||
                            p.assignee.email.split("@")[0]}
                        </span>
                      </>
                    ) : (
                      <span
                        className="text-xs font-medium px-2 py-0.5 rounded-full"
                        style={{
                          background: "#f3ecdb",
                          color: "#8a8270",
                          border: "1px solid #e7ddc5",
                        }}
                      >
                        + Assign
                      </span>
                    )}
                  </button>

                  {assigningId === p.id && (
                    <div
                      onClick={(e) => e.stopPropagation()}
                      className="absolute z-20 mt-2 left-0 w-64 rounded-xl py-2 max-h-64 overflow-y-auto"
                      style={{
                        background: "#ffffff",
                        border: "1px solid #e7ddc5",
                        boxShadow: "0 8px 24px rgba(30,30,20,0.12)",
                      }}
                    >
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          assignProject(p.id, null)
                        }}
                        disabled={assignBusy === p.id}
                        className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition"
                        style={{ color: "#8a8270" }}
                        onMouseEnter={(e) =>
                          (e.currentTarget.style.background = "#faf5ee")
                        }
                        onMouseLeave={(e) =>
                          (e.currentTarget.style.background = "transparent")
                        }
                      >
                        <span
                          className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold"
                          style={{
                            background: "#f3ecdb",
                            color: "#9a9178",
                          }}
                        >
                          —
                        </span>
                        Unassigned
                      </button>
                      {members.length === 0 ? (
                        <div
                          className="px-3 py-3 text-xs"
                          style={{ color: "#8a8270" }}
                        >
                          No team members yet — invite teammates from the
                          Members page.
                        </div>
                      ) : (
                        members.map((m) => {
                          const initials = (() => {
                            const n = (m.full_name || "").trim()
                            if (n) {
                              const parts = n.split(/\s+/).filter(Boolean)
                              return parts.length >= 2
                                ? (parts[0][0] + parts[1][0]).toUpperCase()
                                : parts[0].slice(0, 2).toUpperCase()
                            }
                            return m.email.slice(0, 2).toUpperCase()
                          })()
                          const isCurrent = p.assignee_id === m.id
                          return (
                            <button
                              key={m.id}
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                assignProject(p.id, m.id)
                              }}
                              disabled={assignBusy === p.id}
                              className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition"
                              style={{
                                color: "#1f2a2e",
                                background: isCurrent ? "#f3ecdb" : "transparent",
                              }}
                              onMouseEnter={(e) =>
                                (e.currentTarget.style.background = "#faf5ee")
                              }
                              onMouseLeave={(e) =>
                                (e.currentTarget.style.background = isCurrent
                                  ? "#f3ecdb"
                                  : "transparent")
                              }
                            >
                              <span
                                className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold"
                                style={{
                                  background: "#cfe6e2",
                                  color: "#0a7870",
                                }}
                              >
                                {initials}
                              </span>
                              <span className="flex-1 truncate">
                                {m.full_name || m.email.split("@")[0]}
                              </span>
                              {isCurrent && (
                                <svg
                                  width="14"
                                  height="14"
                                  viewBox="0 0 24 24"
                                  fill="none"
                                  stroke="#0a7870"
                                  strokeWidth="2.4"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                >
                                  <path d="m5 12 5 5 10-10" />
                                </svg>
                              )}
                            </button>
                          )
                        })
                      )}
                    </div>
                  )}
                </div>

                {/* PAGES */}
                <div
                  className="text-right tabular-nums text-sm"
                  style={{ color: "#4a4638" }}
                >
                  {p.page_count?.toLocaleString() ?? "—"}
                </div>

                {/* CREATED */}
                <div
                  className="text-right text-sm"
                  style={{ color: "#6b6558" }}
                  title={p.created_at}
                >
                  {relativeTime(p.created_at)}
                </div>

                {/* CHEVRON */}
                <div className="flex justify-end" style={{ color: "#9a9178" }}>
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="m9 6 6 6-6 6" />
                  </svg>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

// ============================================================
// SUBCOMPONENTS
// ============================================================

function TabButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-3.5 py-1.5 rounded-full text-sm font-medium transition flex items-center gap-1.5"
      style={{
        background: active ? "#ffffff" : "transparent",
        color: active ? "#1f2a2e" : "#6b6558",
        boxShadow: active ? "0 1px 2px rgba(30,30,20,0.06)" : "none",
        border: active ? "1px solid #e7ddc5" : "1px solid transparent",
      }}
    >
      {label}
      <span
        className="text-[10px] font-semibold tabular-nums px-1.5 py-0.5 rounded-full"
        style={{
          background: active ? "#f3ecdb" : "#ffffff",
          color: "#8a8270",
          border: "1px solid #e7ddc5",
        }}
      >
        {count}
      </span>
    </button>
  )
}

function LangChip({ text }: { text: string }) {
  return (
    <span
      className="inline-flex items-center text-[11px] font-semibold tracking-[0.04em] px-2 py-0.5 rounded-md uppercase"
      style={{
        background: "#cfe6e2",
        color: "#0a5e58",
        border: "1px solid #b7dad4",
      }}
    >
      {text}
    </span>
  )
}

function EmptyState({
  isFiltered,
  onCreate,
  onReset,
}: {
  isFiltered: boolean
  onCreate: () => void
  onReset: () => void
}) {
  return (
    <div className="px-5 py-16 flex flex-col items-center text-center">
      <div
        className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4"
        style={{ background: "#f3ecdb", color: "#9a9178" }}
      >
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
        </svg>
      </div>
      <div
        className="text-[16px] font-semibold mb-1"
        style={{ color: "#1f2a2e" }}
      >
        {isFiltered ? "No projects match this filter" : "No projects yet"}
      </div>
      <div className="text-sm mb-5" style={{ color: "#8a8270" }}>
        {isFiltered
          ? "Try clearing the filter or search to see everything."
          : "Upload a document to start translating with TM and glossary support."}
      </div>
      {isFiltered ? (
        <button
          type="button"
          onClick={onReset}
          className="px-4 py-2 rounded-full text-sm font-semibold transition"
          style={{
            background: "#ffffff",
            color: "#1f2a2e",
            border: "1px solid #e7ddc5",
          }}
        >
          Clear filters
        </button>
      ) : (
        <button
          type="button"
          onClick={onCreate}
          className="px-4 py-2.5 rounded-full text-sm font-semibold transition"
          style={{ background: "#0a7870", color: "#fff" }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "#0a645d")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "#0a7870")}
        >
          Start a new project
        </button>
      )}
    </div>
  )
}
