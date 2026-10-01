"use client"

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { api } from "@/lib/api"
import { type BatchRef } from "@/components/BatchBadge"
import BatchGroup, { type BatchDetail, type BatchDoc, type BatchSummary } from "./BatchGroup"

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
  mode?: "translate" | "dtp"
  page_count: number
  credits_used: number
  created_at: string
  assignee_id: string | null
  assignee: Assignee | null
  batch?: BatchRef | null
  partial?: boolean
  failure_reason?: string | null
  failure_code?: string | null
}

function effectiveStatus(p: { status?: string; review_status?: string }) {
  const s = (p.status || "").toUpperCase()
  if (s === "FAILED" || s === "PENDING" || s === "PROCESSING") return s
  if (s === "COMPLETED") {
    const r = (p.review_status || "").toUpperCase()
    if (r === "CERTIFIED") return "CERTIFIED"
    if (r === "IN_REVIEW") return "IN_REVIEW"

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

function langChip(raw?: string) {
  if (!raw) return "—"
  const s = raw.trim()

  if (s.length <= 5 && /^[a-z]/i.test(s)) return s.toLowerCase()

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
  return (
    <Suspense fallback={null}>
      <Jobs />
    </Suspense>
  )
}

type Entry =
  | { kind: "doc"; project: Project }
  | { kind: "group"; id: string; name: string; docs: Project[]; all: Project[] }

const POLL_MS = 5000

const ROW_GRID =
  "md:grid-cols-[minmax(0,2fr)_128px_112px_minmax(0,1fr)_72px] xl:grid-cols-[minmax(0,2.4fr)_128px_112px_minmax(0,1.2fr)_minmax(0,1.1fr)_56px_84px_72px]"

function isActive(p: { status?: string }) {
  const s = (p.status || "").toUpperCase()
  return s === "PENDING" || s === "PROCESSING"
}

function fromBatchDoc(d: BatchDoc, batch: BatchRef): Project {
  return {
    id: d.id,
    filename: d.filename,
    status: d.status,
    review_status: d.review_status,
    progress: d.progress,
    source_lang: d.source_lang,
    target_lang: d.target_lang,
    mode: d.mode,
    page_count: d.page_count,
    credits_used: d.page_count,
    created_at: d.created_at || "",
    assignee_id: null,
    assignee: null,
    batch,
    partial: true,
    failure_reason: d.failure_reason,
    failure_code: d.failure_code,
  }
}

function initialsOf(fullName: string | null, email: string) {
  const name = (fullName || "").trim()
  if (name) {
    const parts = name.split(/\s+/).filter(Boolean)
    return parts.length >= 2 ? (parts[0][0] + parts[1][0]).toUpperCase() : parts[0].slice(0, 2).toUpperCase()
  }
  return email.slice(0, 2).toUpperCase()
}

function Jobs() {
  const router = useRouter()
  const highlight = useSearchParams().get("batch")

  const [projects, setProjects] = useState<Project[]>([])
  const [summaries, setSummaries] = useState<Record<string, BatchSummary>>({})
  const [details, setDetails] = useState<Record<string, BatchDetail>>({})
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(highlight ? [highlight] : []))
  const [members, setMembers] = useState<Member[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<StatusFilter>("all")
  const [query, setQuery] = useState("")
  const [assigningId, setAssigningId] = useState<string | null>(null)
  const [assignBusy, setAssignBusy] = useState<string | null>(null)

  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState<string>("")
  const [renameBusy, setRenameBusy] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)

  const highlightRef = useRef<HTMLDivElement | null>(null)
  const scrolledTo = useRef<string | null>(null)

  const closeRename = () => {
    setRenamingId(null)
    setRenameDraft("")
  }
  const closeDelete = () => setDeletingId(null)

  const submitRename = async () => {
    if (!renamingId) return
    const name = renameDraft.trim()
    if (!name) {
      setError("Project name can't be empty.")
      return
    }
    try {
      setRenameBusy(true)
      setError(null)
      const res = await api.patch(`/projects/${renamingId}`, {
        file_name: name,
      })
      const newName: string = res.data?.file_name || name
      setProjects((ps) =>
        ps.map((p) =>
          p.id === renamingId ? { ...p, filename: newName } : p
        )
      )
      closeRename()
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          "Couldn't rename the project — please try again."
      )
    } finally {
      setRenameBusy(false)
    }
  }

  const submitDelete = async () => {
    if (!deletingId) return
    try {
      setDeleteBusy(true)
      setError(null)
      await api.delete(`/projects/${deletingId}`)
      setProjects((ps) => ps.filter((p) => p.id !== deletingId))
      closeDelete()
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          "Couldn't delete the project — please try again."
      )
    } finally {
      setDeleteBusy(false)
    }
  }

  const fetchJobs = useCallback(async () => {
    try {
      const res = await api.get("/projects/")
      setProjects(res.data || [])
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          "Couldn't load your projects — try refreshing in a moment."
      )
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchSummaries = useCallback(async () => {
    try {
      const res = await api.get("/batches")
      const list: BatchSummary[] = res.data || []
      setSummaries(Object.fromEntries(list.map((b) => [b.id, b])))
    } catch {
      setSummaries({})
    }
  }, [])

  const loadDetail = useCallback(async (id: string) => {
    try {
      const res = await api.get(`/batches/${id}`)
      setDetails((d) => ({ ...d, [id]: res.data }))
    } catch {
      // Group still renders from the projects list and the summary.
    }
  }, [])

  useEffect(() => {
    fetchJobs()
    fetchSummaries()
    api
      .get("/members")
      .then((res) => setMembers(res.data?.members || []))
      .catch(() => setMembers([]))
  }, [fetchJobs, fetchSummaries])

  const requested = useRef<Set<string>>(new Set())
  useEffect(() => {
    for (const id of expanded) {
      if (details[id] || requested.current.has(id)) continue
      requested.current.add(id)
      loadDetail(id)
    }
  }, [expanded, details, loadDetail])

  const anyActive =
    projects.some(isActive) || Object.values(details).some((d) => d.projects.some(isActive))
  useEffect(() => {
    if (!anyActive) return
    const t = window.setInterval(() => {
      fetchJobs()
      fetchSummaries()
      for (const id of Object.keys(details)) loadDetail(id)
    }, POLL_MS)
    return () => window.clearInterval(t)
  }, [anyActive, details, fetchJobs, fetchSummaries, loadDetail])

  useEffect(() => {
    if (!assigningId) return
    const onClick = () => setAssigningId(null)
    window.addEventListener("click", onClick)
    return () => window.removeEventListener("click", onClick)
  }, [assigningId])

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

  const entries = useMemo<Entry[]>(() => {
    const q = query.trim().toLowerCase()
    const tabOk = (p: Project) => {
      const s = effectiveStatus(p)
      if (tab === "active") return s === "PROCESSING" || s === "PENDING"
      if (tab === "review") return s === "IN_REVIEW"
      if (tab === "delivered") return s === "COMPLETED" || s === "CERTIFIED"
      return true
    }
    const queryOk = (p: Project) =>
      !q ||
      (p.filename || "").toLowerCase().includes(q) ||
      (p.source_lang || "").toLowerCase().includes(q) ||
      (p.target_lang || "").toLowerCase().includes(q)

    const byBatch = new Map<string, Project[]>()
    const known = new Set(projects.map((p) => p.id))
    for (const p of projects) {
      if (p.batch) byBatch.set(p.batch.id, [...(byBatch.get(p.batch.id) || []), p])
    }
    // GET /projects/ is capped, so a batch can have documents only its detail knows about.
    for (const d of Object.values(details)) {
      const ref = { id: d.id, name: d.name }
      const extra = d.projects.filter((x) => !known.has(x.id)).map((x) => fromBatchDoc(x, ref))
      if (extra.length) byBatch.set(d.id, [...(byBatch.get(d.id) || []), ...extra])
    }

    const out: Entry[] = []
    const seen = new Set<string>()
    const addGroup = (id: string, name: string) => {
      seen.add(id)
      const all = byBatch.get(id) || []
      const nameHit = !!q && name.toLowerCase().includes(q)
      const docs = all.filter((p) => tabOk(p) && (nameHit || queryOk(p)))
      if (docs.length || id === highlight || (nameHit && tab === "all")) {
        out.push({ kind: "group", id, name, docs, all })
      }
    }

    if (highlight && !projects.some((p) => p.batch?.id === highlight)) {
      const h = details[highlight] || summaries[highlight]
      if (h) addGroup(highlight, h.name)
    }
    for (const p of projects) {
      if (p.batch) {
        if (!seen.has(p.batch.id)) {
          addGroup(p.batch.id, p.batch.name || summaries[p.batch.id]?.name || "")
        }
      } else if (tabOk(p) && queryOk(p)) {
        out.push({ kind: "doc", project: p })
      }
    }
    return out
  }, [projects, details, summaries, tab, query, highlight])

  useEffect(() => {
    if (!highlight || scrolledTo.current === highlight || !highlightRef.current) return
    scrolledTo.current = highlight
    highlightRef.current.scrollIntoView({ block: "center" })
  }, [highlight, entries])

  const toggleGroup = (id: string) =>
    setExpanded((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const refreshBatch = (id: string) => {
    fetchJobs()
    fetchSummaries()
    loadDetail(id)
  }

  const groupSummary = (id: string, all: Project[]) => {
    const s = summaries[id] || details[id]
    if (s) return s
    const completed = all.filter((p) => (p.status || "").toUpperCase() === "COMPLETED").length
    const failed = all.filter((p) => (p.status || "").toUpperCase() === "FAILED").length
    return {
      documents: all.length,
      pages: all.reduce((n, p) => n + (p.page_count || 0), 0),
      completed,
      failed,
      in_progress: all.length - completed - failed,
      terms: 0,
    }
  }

  const renderAssignee = (p: Project) => {
    if (p.partial) {
      return (
        <span className="text-xs" style={{ color: "#9a9178" }}>
          —
        </span>
      )
    }
    return (
      <div className="relative" onClick={(e) => e.stopPropagation()}>
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
                {initialsOf(p.assignee.full_name, p.assignee.email)}
              </div>
              <span className="text-xs truncate" style={{ color: "#4a4638" }}>
                {p.assignee.full_name || p.assignee.email.split("@")[0]}
              </span>
            </>
          ) : (
            <span
              className="text-xs font-medium px-2 py-0.5 rounded-full whitespace-nowrap"
              style={{ background: "#f3ecdb", color: "#8a8270", border: "1px solid #e7ddc5" }}
            >
              + Assign
            </span>
          )}
        </button>

        {assigningId === p.id && (
          <div
            onClick={(e) => e.stopPropagation()}
            className="absolute z-20 mt-2 right-0 xl:right-auto xl:left-0 w-64 max-w-[80vw] rounded-xl py-2 max-h-64 overflow-y-auto"
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
              className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition hover:bg-[#faf5ee]"
              style={{ color: "#8a8270" }}
            >
              <span
                className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold"
                style={{ background: "#f3ecdb", color: "#9a9178" }}
              >
                —
              </span>
              Unassigned
            </button>
            {members.length === 0 ? (
              <div className="px-3 py-3 text-xs" style={{ color: "#8a8270" }}>
                No team members yet — invite teammates from the Members page.
              </div>
            ) : (
              members.map((m) => {
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
                    className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition hover:bg-[#faf5ee]"
                    style={{ color: "#1f2a2e", background: isCurrent ? "#f3ecdb" : undefined }}
                  >
                    <span
                      className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold"
                      style={{ background: "#cfe6e2", color: "#0a7870" }}
                    >
                      {initialsOf(m.full_name, m.email)}
                    </span>
                    <span className="flex-1 truncate">{m.full_name || m.email.split("@")[0]}</span>
                    {isCurrent && (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#0a7870" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
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
    )
  }

  const renderActions = (p: Project) =>
    p.partial ? null : (
      <div className="flex justify-end items-center gap-1" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          title="Rename project"
          aria-label="Rename project"
          onClick={(e) => {
            e.stopPropagation()
            setRenamingId(p.id)
            setRenameDraft(p.filename || "")
          }}
          className="w-8 h-8 rounded-md flex items-center justify-center transition hover:bg-[#f3ecdb]"
          style={{ color: "#6b6558" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4Z" />
          </svg>
        </button>
        <button
          type="button"
          title="Delete project"
          aria-label="Delete project"
          onClick={(e) => {
            e.stopPropagation()
            setDeletingId(p.id)
          }}
          className="w-8 h-8 rounded-md flex items-center justify-center transition hover:bg-[#f9efe9]"
          style={{ color: "#b14a3a" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 6h18" />
            <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            <path d="M19 6 18 21H6L5 6" />
          </svg>
        </button>
      </div>
    )

  const renderRow = (p: Project, inGroup: boolean) => {
    const st = statusStyle(effectiveStatus(p))
    const progress = Math.max(0, Math.min(100, p.progress || 0))
    const open = () => router.push(`/editor/${p.id}`)
    const statusChip = (
      <span
        className="inline-flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.04em] px-2.5 py-1 rounded-full whitespace-nowrap"
        style={{ background: st.bg, color: st.text }}
      >
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: st.dot }} />
        {st.label}
      </span>
    )
    const langs =
      p.mode === "dtp" ? (
        <div className="flex items-center gap-1.5">
          <LangChip text={langChip(p.target_lang)} />
          <span
            className="inline-flex items-center text-[10px] font-semibold px-2 py-0.5 rounded-full whitespace-nowrap"
            style={{ background: "#f3ecdb", color: "#6b6558", border: "1px solid #e7ddc5" }}
            title="Same-language editable copy, not a translation"
          >
            Editable copy
          </span>
        </div>
      ) : (
        <div className="flex items-center gap-1.5">
          <LangChip text={langChip(p.source_lang)} />
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
          <LangChip text={langChip(p.target_lang)} />
        </div>
      )
    const fileIcon = (
      <div
        className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
        style={{ background: inGroup ? "#ffffff" : "#f3ecdb", color: "#6b6558", border: inGroup ? "1px solid #ede3cc" : "none" }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
          <path d="M14 2v6h6" />
          <path d="M9 13h6M9 17h6M9 9h2" />
        </svg>
      </div>
    )
    const meta = (
      <>
        {p.page_count ? `${p.page_count} page${p.page_count === 1 ? "" : "s"}` : "—"} ·{" "}
        <span className="font-mono" title={p.id}>
          {p.id.slice(0, 8)}
        </span>
      </>
    )

    return (
      <div
        key={p.id}
        role="button"
        tabIndex={0}
        onClick={open}
        onKeyDown={(e) => {
          if (e.key === "Enter") open()
        }}
        className={`w-full text-left px-4 sm:px-5 py-3.5 md:py-4 transition cursor-pointer hover:bg-[#fbf6ea] md:grid md:items-center md:gap-3 ${ROW_GRID}`}
        style={{
          borderBottom: "1px solid #f4ecd6",
          color: "#1f2a2e",
          background: inGroup ? "#fffdf9" : undefined,
          boxShadow: inGroup ? "inset 3px 0 0 #cfe6e2" : undefined,
        }}
      >
        <div className={`flex items-center gap-3 min-w-0 ${inGroup ? "md:pl-5" : ""}`}>
          {fileIcon}
          <div className="min-w-0 flex-1">
            <div className="font-semibold truncate">{p.filename || "Untitled document"}</div>
            <div className="text-xs truncate" style={{ color: "#8a8270" }}>
              {meta}
              <span className="md:hidden"> · {relativeTime(p.created_at)}</span>
            </div>
            {p.failure_code === "same_language" && p.failure_reason && (
              <div className="text-xs" style={{ color: "#7a2f24" }}>
                {p.failure_reason}
              </div>
            )}
          </div>
          <div className="md:hidden shrink-0">{renderActions(p)}</div>
        </div>

        <div className="md:hidden flex flex-wrap items-center gap-2 mt-2.5 pl-12">
          {statusChip}
          {langs}
        </div>

        <div className="hidden md:block">{langs}</div>
        <div className="hidden md:block">{statusChip}</div>

        <div className="hidden xl:flex items-center gap-3">
          <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "#f1e8d1" }}>
            <div
              className="h-full transition-all"
              style={{
                width: `${progress}%`,
                background: progress >= 100 ? "#4a8a3a" : progress > 0 ? "#0a7870" : "#cfc6ad",
              }}
            />
          </div>
          <div className="text-xs tabular-nums w-9 text-right" style={{ color: "#6b6558" }}>
            {progress}%
          </div>
        </div>

        <div className="hidden md:block min-w-0">{renderAssignee(p)}</div>

        <div className="hidden xl:block text-right tabular-nums text-sm" style={{ color: "#4a4638" }}>
          {p.page_count?.toLocaleString() ?? "—"}
        </div>
        <div className="hidden xl:block text-right text-sm" style={{ color: "#6b6558" }} title={p.created_at}>
          {relativeTime(p.created_at)}
        </div>

        <div className="hidden md:block">{renderActions(p)}</div>
      </div>
    )
  }

  const isFiltered = tab !== "all" || query.trim().length > 0

  return (
    <div className="space-y-6 pb-16">
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <span style={{ color: "#1f2a2e" }}>Projects</span>
      </div>

      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
            Projects
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            Most recent first. Documents uploaded together are grouped as a batch.
          </p>
        </div>
        <button
          type="button"
          onClick={() => router.push("/new-translation")}
          className="px-4 py-2.5 rounded-full text-sm font-semibold transition flex items-center gap-2 hover:bg-[#0a645d]"
          style={{ background: "#0a7870", color: "#fff" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New project
        </button>
      </div>

      {error && (
        <div className="text-sm rounded-lg px-3 py-2" style={{ background: "#f2d4cf", color: "#7a2f24" }}>
          {error}
        </div>
      )}

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="max-w-full overflow-x-auto">
          <div
            className="inline-flex items-center gap-1 p-1 rounded-full"
            style={{ background: "#f3ecdb", border: "1px solid #e7ddc5" }}
          >
            <TabButton label="All" count={counts.all} active={tab === "all"} onClick={() => setTab("all")} />
            <TabButton label="In progress" count={counts.active} active={tab === "active"} onClick={() => setTab("active")} />
            <TabButton label="Awaiting review" count={counts.review} active={tab === "review"} onClick={() => setTab("review")} />
            <TabButton label="Delivered" count={counts.delivered} active={tab === "delivered"} onClick={() => setTab("delivered")} />
          </div>
        </div>

        <div
          className="flex items-center gap-2 px-4 py-2 rounded-full w-full sm:w-72"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            placeholder="Search file, batch or language…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 min-w-0 bg-transparent outline-none text-sm"
            style={{ color: "#1f2a2e" }}
          />
        </div>
      </div>

      <div className="rounded-2xl" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
        <div
          className={`hidden md:grid md:gap-3 items-center text-[11px] font-semibold tracking-[0.14em] px-5 py-3 rounded-t-2xl ${ROW_GRID}`}
          style={{ background: "#faf5ee", borderBottom: "1px solid #f1e8d1", color: "#9a9178" }}
        >
          <div>PROJECT</div>
          <div>LANGUAGES</div>
          <div>STATUS</div>
          <div className="hidden xl:block">PROGRESS</div>
          <div>ASSIGNEE</div>
          <div className="hidden xl:block text-right">PAGES</div>
          <div className="hidden xl:block text-right">CREATED</div>
          <div />
        </div>

        {loading ? (
          <div className="px-5 py-12 text-center text-sm" style={{ color: "#8a8270" }}>
            Loading projects…
          </div>
        ) : entries.length === 0 ? (
          <EmptyState
            isFiltered={isFiltered}
            onCreate={() => router.push("/new-translation")}
            onReset={() => {
              setTab("all")
              setQuery("")
            }}
          />
        ) : (
          entries.map((e) => {
            if (e.kind === "doc") return renderRow(e.project, false)
            const open = expanded.has(e.id) || query.trim().length > 0
            return (
              <BatchGroup
                key={`batch:${e.id}`}
                ref={e.id === highlight ? highlightRef : undefined}
                id={e.id}
                name={e.name}
                summary={groupSummary(e.id, e.all)}
                detail={details[e.id] || null}
                expanded={open}
                highlighted={e.id === highlight}
                onToggle={() => toggleGroup(e.id)}
                onNeedDetail={() => loadDetail(e.id)}
                onChanged={() => refreshBatch(e.id)}
              >
                {e.docs.length ? (
                  e.docs.map((p) => renderRow(p, true))
                ) : (
                  <div className="px-5 py-4 text-sm" style={{ color: "#8a8270", borderBottom: "1px solid #f4ecd6" }}>
                    {details[e.id] ? "No documents match this filter." : "Loading documents…"}
                  </div>
                )}
              </BatchGroup>
            )
          })
        )}
      </div>

      {}
      {renamingId && (
        <ModalOverlay onClose={closeRename}>
          <div
            className="rounded-2xl p-6 w-full max-w-md"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 24px 60px rgba(30,30,20,0.18)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="text-[11px] font-semibold tracking-[0.18em] mb-1"
              style={{ color: "#9a9178" }}
            >
              RENAME PROJECT
            </div>
            <h3
              className="text-[18px] font-semibold tracking-tight mb-4"
              style={{ color: "#1f2a2e" }}
            >
              Pick a clearer name
            </h3>
            <input
              autoFocus
              value={renameDraft}
              onChange={(e) => setRenameDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitRename()
                if (e.key === "Escape") closeRename()
              }}
              placeholder="e.g. Birth certificate · ITA→EN"
              className="w-full text-sm outline-none px-4 py-2.5 rounded-xl"
              style={{
                background: "#faf5ee",
                border: "1px solid #e7ddc5",
                color: "#1f2a2e",
              }}
            />
            <p className="text-xs mt-3" style={{ color: "#8a8270" }}>
              Renaming only changes how the project appears in the dashboard
              and on exports. The original source file is unchanged.
            </p>
            <div className="flex items-center justify-end gap-2 mt-5">
              <button
                type="button"
                onClick={closeRename}
                disabled={renameBusy}
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
                onClick={submitRename}
                disabled={renameBusy || !renameDraft.trim()}
                className="px-4 py-2 rounded-full text-sm font-semibold"
                style={{
                  background:
                    renameBusy || !renameDraft.trim() ? "#9bc9c5" : "#0a7870",
                  color: "#fff",
                  cursor:
                    renameBusy || !renameDraft.trim()
                      ? "not-allowed"
                      : "pointer",
                }}
              >
                {renameBusy ? "Saving…" : "Save name"}
              </button>
            </div>
          </div>
        </ModalOverlay>
      )}

      {}
      {deletingId && (
        <ModalOverlay onClose={closeDelete}>
          <div
            className="rounded-2xl p-6 w-full max-w-md"
            style={{
              background: "#ffffff",
              border: "1px solid #e7b8b0",
              boxShadow: "0 24px 60px rgba(177,74,58,0.20)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="text-[11px] font-semibold tracking-[0.18em] mb-1"
              style={{ color: "#b14a3a" }}
            >
              DELETE PROJECT
            </div>
            <h3
              className="text-[18px] font-semibold tracking-tight mb-3"
              style={{ color: "#1f2a2e" }}
            >
              Permanently remove this project?
            </h3>
            <p className="text-sm mb-5" style={{ color: "#6b6558" }}>
              This deletes the project, its segments, comments, and the
              uploaded source file. This action cannot be undone.
            </p>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={closeDelete}
                disabled={deleteBusy}
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
                onClick={submitDelete}
                disabled={deleteBusy}
                className="px-4 py-2 rounded-full text-sm font-semibold"
                style={{
                  background: deleteBusy ? "#e7b8b0" : "#b14a3a",
                  color: "#fff",
                  cursor: deleteBusy ? "not-allowed" : "pointer",
                }}
              >
                {deleteBusy ? "Deleting…" : "Delete project"}
              </button>
            </div>
          </div>
        </ModalOverlay>
      )}
    </div>
  )
}

function ModalOverlay({
  onClose,
  children,
}: {
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(31, 42, 46, 0.45)",
        backdropFilter: "blur(2px)",
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      {children}
    </div>
  )
}

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
      className="px-3.5 py-1.5 rounded-full text-sm font-medium transition flex items-center gap-1.5 whitespace-nowrap"
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
      className="inline-flex items-center text-[11px] font-semibold tracking-[0.04em] px-2 py-0.5 rounded-md uppercase whitespace-nowrap"
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
