"use client"

import { useEffect, useMemo, useState, useCallback } from "react"
import { useParams, useRouter } from "next/navigation"
import { api } from "@/lib/api"

// ============================================================
// EDITOR — wired to real backend, no demo data.
//
// Endpoints used:
//   GET    /projects/{id}                            project + stats + assignee
//   GET    /projects/{id}/segments                   segments (id, source, target, approved, tm_pct)
//   GET    /segments/{seg_id}/comments               comments per segment
//   POST   /segments/{seg_id}/comments               add comment
//   PATCH  /segments/{comment_id}/resolve            mark comment resolved
//   PATCH  /projects/{id}/segments/{seg_id}/approve  toggle approve
//   PATCH  /projects/{id}/review-status              DRAFT / IN_REVIEW / CERTIFIED
//   POST   /projects/{id}/certify                    certify (Pro-only)
//   GET    /projects/{id}/export                     DOCX (Basic+Pro)
//   GET    /projects/{id}/export/pdf                 PDF  (Basic+Pro)
//   GET    /glossary                                 list, used to count terms
// ============================================================

type Segment = {
  id: string
  segment_index: number
  source_text: string
  translated_text: string
  approved: boolean
  tm_pct: number | null
}

type Assignee = {
  id: string
  email: string
  full_name: string | null
}

type ProjectInfo = {
  id: string
  status: string
  review_status: string
  progress_percent: number
  file_name: string
  source_language: string
  target_language: string
  stats: {
    total_segments: number
    translated_segments: number
    approved_segments: number
    tm_average_pct: number
  }
  assignee: Assignee | null
  uploader: Assignee | null
}

type Comment = {
  id: string
  text: string
  created_at: string
  resolved: boolean
  user: { id: string | null; email: string }
}

type Tab = "tm" | "glossary" | "comments" | "status"

const REVIEW_STATUSES = [
  { value: "DRAFT", label: "Draft", bg: "#ede3cc", dot: "#9a9178", text: "#6b6558" },
  { value: "IN_REVIEW", label: "In review", bg: "#f6e3b8", dot: "#c88a1a", text: "#7a5a10" },
  { value: "CERTIFIED", label: "Certified", bg: "#d8ead6", dot: "#4a8a3a", text: "#2d5a24" },
]

function statusStyle(status?: string) {
  return (
    REVIEW_STATUSES.find((s) => s.value === (status || "").toUpperCase()) ||
    REVIEW_STATUSES[0]
  )
}

function langCode(raw?: string) {
  if (!raw) return "—"
  const s = raw.trim()
  if (s.length <= 5 && /^[a-z]/i.test(s)) return s.toLowerCase()
  const map: Record<string, string> = {
    english: "en", spanish: "es", french: "fr", german: "de", italian: "it",
    portuguese: "pt", dutch: "nl", polish: "pl", chinese: "zh", japanese: "ja",
    arabic: "ar", swedish: "sv",
  }
  return map[s.toLowerCase()] || s.slice(0, 2).toLowerCase()
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

function relativeTime(iso: string) {
  // Backend returns naive UTC ISO strings without timezone markers.
  // Without this, the browser parses them as local time and comments
  // appear hours older than they actually are.
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(iso)
  const safe = hasTz ? iso : iso + "Z"
  const t = new Date(safe).getTime()
  if (!Number.isFinite(t)) return ""
  const diff = Date.now() - t
  const m = 60_000, h = 3_600_000, d = 86_400_000
  if (diff < 0) return "just now"
  if (diff < m) return "just now"
  if (diff < h) return `${Math.floor(diff / m)}m ago`
  if (diff < d) return `${Math.floor(diff / h)}h ago`
  if (diff < 7 * d) return `${Math.floor(diff / d)}d ago`
  return new Date(safe).toLocaleDateString()
}

export default function EditorPage() {
  const router = useRouter()
  const params = useParams()
  const id = params?.id as string

  const [project, setProject] = useState<ProjectInfo | null>(null)
  const [segments, setSegments] = useState<Segment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeIdx, setActiveIdx] = useState(0)
  const [tab, setTab] = useState<Tab>("comments")

  // Comments per segment (cache so flipping segments doesn't refetch instantly)
  const [comments, setComments] = useState<Record<string, Comment[]>>({})
  const [newComment, setNewComment] = useState("")
  const [busy, setBusy] = useState<string | null>(null)
  const [glossaryCount, setGlossaryCount] = useState<number>(0)
  const [showStatusMenu, setShowStatusMenu] = useState(false)
  const [showApproveAllConfirm, setShowApproveAllConfirm] =
    useState<boolean>(false)
  const [approveAllProgress, setApproveAllProgress] = useState<{
    done: number
    total: number
  } | null>(null)

  // COMPARE MODE — shows the original document next to the rebuilt
  // output PDF so a reviewer can verify the rebuild visually. When
  // active, the segments table is replaced with these two panes
  // (the right-side sidebar stays).
  const [compareMode, setCompareMode] = useState(false)
  const [sourcePreview, setSourcePreview] = useState<{
    url: string
    kind: "pdf" | "image" | "other"
    filename: string
  } | null>(null)
  const [rebuildPreview, setRebuildPreview] = useState<{
    url: string | null
    kind: "pdf" | "image" | "docx" | "other" | "none"
    filename: string | null
  } | null>(null)
  const [compareLoading, setCompareLoading] = useState(false)

  const loadCompare = async () => {
    setCompareLoading(true)
    // Independent calls so one failure doesn't blank the other.
    // SOURCE — should always succeed if the project has a file_path.
    try {
      const srcRes = await api.get(`/projects/${id}/source-url`)
      setSourcePreview({
        url: srcRes.data.url,
        kind: srcRes.data.kind,
        filename: srcRes.data.filename,
      })
    } catch (err: any) {
      console.error("COMPARE SOURCE ERROR:", err)
      setSourcePreview(null)
    }
    // REBUILD — build a fresh DOCX. If the build endpoint errors
    // (no approved segments, planner timeout, etc.), fall back to
    // the cached output_file so the user at least sees the last
    // export. Final fallback is an explanatory empty hint.
    try {
      const rebRes = await api.post(`/projects/${id}/build-rebuild-docx`)
      setRebuildPreview({
        url: rebRes.data.url,
        kind: rebRes.data.kind,
        filename: rebRes.data.filename,
      })
    } catch (err: any) {
      console.error("COMPARE REBUILD BUILD ERROR:", err)
      try {
        const rebRes = await api.get(`/projects/${id}/rebuild-url`)
        setRebuildPreview({
          url: rebRes.data.url,
          kind: rebRes.data.kind,
          filename: rebRes.data.filename,
        })
      } catch {
        setRebuildPreview({ url: null, kind: "none", filename: null })
      }
    }
    setCompareLoading(false)
  }

  const toggleCompareMode = () => {
    const next = !compareMode
    setCompareMode(next)
    // Always re-build on open so the user gets the freshest rebuild
    // (in case they've edited segments since the last Compare).
    if (next) {
      setRebuildPreview(null)
      loadCompare()
    }
  }

  // Rename + delete state for the title chrome.
  const [renameOpen, setRenameOpen] = useState(false)
  const [renamingDraft, setRenamingDraft] = useState("")
  const [renameBusy, setRenameBusy] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteBusy, setDeleteBusy] = useState(false)

  const submitRename = async () => {
    const name = renamingDraft.trim()
    if (!name) return
    try {
      setRenameBusy(true)
      const res = await api.patch(`/projects/${id}`, { file_name: name })
      const newName: string = res.data?.file_name || name
      setProject((p) => (p ? { ...p, file_name: newName } : p))
      setRenameOpen(false)
    } catch (err: any) {
      console.error("RENAME ERROR:", err)
      alert(
        err?.response?.data?.detail ||
          "Couldn't rename the project — please try again."
      )
    } finally {
      setRenameBusy(false)
    }
  }

  const submitDelete = async () => {
    try {
      setDeleteBusy(true)
      await api.delete(`/projects/${id}`)
      router.replace("/jobs")
    } catch (err: any) {
      console.error("DELETE ERROR:", err)
      alert(
        err?.response?.data?.detail ||
          "Couldn't delete the project — please try again."
      )
      setDeleteBusy(false)
    }
  }

  const fetchProject = useCallback(async () => {
    try {
      const [projRes, segRes] = await Promise.all([
        api.get(`/projects/${id}`),
        api.get(`/projects/${id}/segments`),
      ])
      setProject(projRes.data)
      const segs = (segRes.data || []) as Segment[]
      // Defensive sort by index in case the backend ever changes ordering.
      segs.sort((a, b) => a.segment_index - b.segment_index)
      setSegments(segs)
    } catch (err: any) {
      console.error("EDITOR ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't load this project — it may have been deleted or you don't have access."
      )
      setSegments([])
      setProject(null)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    if (!id) return
    fetchProject()
  }, [id, fetchProject])

  // Poll for translation completion when the project is still processing.
  useEffect(() => {
    if (!project) return
    if (project.status === "COMPLETED" || project.status === "FAILED") return
    const t = setInterval(fetchProject, 3000)
    return () => clearInterval(t)
  }, [project, fetchProject])

  // Glossary count for the side-panel tab badge. Silently 0 on Trial/Basic
  // (the route is gated and 403s — the editor doesn't need the actual data).
  useEffect(() => {
    api
      .get("/glossary")
      .then((res) => setGlossaryCount((res.data || []).length))
      .catch(() => setGlossaryCount(0))
  }, [])

  const activeSegment = segments[activeIdx]

  // Fetch comments when the active segment changes
  useEffect(() => {
    if (!activeSegment) return
    if (comments[activeSegment.id]) return
    api
      .get(`/segments/${activeSegment.id}/comments`)
      .then((res) =>
        setComments((c) => ({ ...c, [activeSegment.id]: res.data || [] }))
      )
      .catch(() => {
        setComments((c) => ({ ...c, [activeSegment.id]: [] }))
      })
  }, [activeSegment, comments])

  const refreshCommentsForActive = useCallback(async () => {
    if (!activeSegment) return
    try {
      const res = await api.get(`/segments/${activeSegment.id}/comments`)
      setComments((c) => ({ ...c, [activeSegment.id]: res.data || [] }))
    } catch {
      /* ignore */
    }
  }, [activeSegment])

  const addComment = async () => {
    if (!activeSegment || !newComment.trim()) return
    try {
      setBusy("comment")
      await api.post(`/segments/${activeSegment.id}/comments`, {
        text: newComment.trim(),
      })
      setNewComment("")
      await refreshCommentsForActive()
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't add the comment.")
    } finally {
      setBusy(null)
    }
  }

  const resolveComment = async (commentId: string) => {
    try {
      setBusy(`resolve:${commentId}`)
      await api.patch(`/segments/${commentId}/resolve`)
      await refreshCommentsForActive()
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't resolve that comment.")
    } finally {
      setBusy(null)
    }
  }

  const toggleApprove = async (seg: Segment) => {
    try {
      setBusy(`approve:${seg.id}`)
      const res = await api.patch(
        `/projects/${id}/segments/${seg.id}/approve`,
        { approved: !seg.approved }
      )
      const approved = !!res.data?.approved
      setSegments((xs) =>
        xs.map((x) => (x.id === seg.id ? { ...x, approved } : x))
      )
      // Bump approved count on the cached project so the toolbar stat updates
      // without a round-trip.
      setProject((p) =>
        p
          ? {
              ...p,
              stats: {
                ...p.stats,
                approved_segments:
                  p.stats.approved_segments + (approved ? 1 : -1),
              },
            }
          : p
      )
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't update that segment.")
    } finally {
      setBusy(null)
    }
  }

  const approveAllTranslated = async () => {
    // Approve every segment that has translated text and isn't already
    // approved. We hit the existing per-segment endpoint in small
    // concurrent batches so a multi-thousand-segment project doesn't
    // serialise into a multi-minute wall.
    const candidates = segments.filter(
      (s) => !s.approved && s.translated_text && s.translated_text.trim()
    )
    if (candidates.length === 0) {
      setShowApproveAllConfirm(false)
      setError(
        "Nothing to approve — every translated segment is already approved."
      )
      return
    }

    setShowApproveAllConfirm(false)
    setBusy("approve-all")
    setApproveAllProgress({ done: 0, total: candidates.length })

    const CONCURRENCY = 8
    const approvedIds = new Set<string>()
    let cursor = 0
    let done = 0

    const worker = async () => {
      while (true) {
        const i = cursor++
        if (i >= candidates.length) return
        const seg = candidates[i]
        try {
          await api.patch(
            `/projects/${id}/segments/${seg.id}/approve`,
            { approved: true }
          )
          approvedIds.add(seg.id)
        } catch {
          /* skip; user can retry the segment manually */
        }
        done += 1
        setApproveAllProgress({ done, total: candidates.length })
      }
    }

    try {
      await Promise.all(
        Array.from({ length: Math.min(CONCURRENCY, candidates.length) }, worker)
      )
      setSegments((xs) =>
        xs.map((x) => (approvedIds.has(x.id) ? { ...x, approved: true } : x))
      )
      setProject((p) =>
        p
          ? {
              ...p,
              stats: {
                ...p.stats,
                approved_segments: p.stats.approved_segments + approvedIds.size,
              },
            }
          : p
      )
      if (approvedIds.size < candidates.length) {
        setError(
          `Approved ${approvedIds.size} of ${candidates.length} segments — some failed and can be re-approved individually.`
        )
      }
    } finally {
      setApproveAllProgress(null)
      setBusy(null)
    }
  }

  const updateReviewStatus = async (status: string) => {
    try {
      setBusy("status")
      await api.patch(`/projects/${id}/review-status`, { status })
      setProject((p) => (p ? { ...p, review_status: status } : p))
      setShowStatusMenu(false)
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't change the status.")
    } finally {
      setBusy(null)
    }
  }

  const certify = async () => {
    if (!project) return
    if (project.status !== "COMPLETED") {
      setError("The translation must finish before it can be certified.")
      return
    }
    try {
      setBusy("certify")
      await api.post(`/projects/${id}/certify`)
      setProject((p) => (p ? { ...p, review_status: "CERTIFIED" } : p))
    } catch (err: any) {
      // 403 → trial / basic don't have certifications, send to billing.
      if (err?.response?.status === 403) {
        setError("Certification is a Pro feature. Upgrade in Billing to unlock.")
      } else {
        setError(err?.response?.data?.detail || "Couldn't certify the project.")
      }
    } finally {
      setBusy(null)
    }
  }

  const exportFile = async (kind: "docx" | "pdf") => {
    try {
      setBusy(`export:${kind}`)
      const url = kind === "docx" ? `/projects/${id}/export` : `/projects/${id}/export/pdf`
      const res = await api.get(url, { responseType: "blob" })
      const blob = new Blob([res.data])
      const dl = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = dl
      a.download = `${(project?.file_name || "translation").replace(/\.[^.]+$/, "")}.${kind}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(dl)
    } catch (err: any) {
      // When responseType is "blob", axios wraps the JSON error body
      // in a Blob — so err.response.data is a Blob, not the parsed
      // {detail: "..."} object. Read it as text and parse it to surface
      // the backend's real message (e.g. "No approved segments yet.").
      let detail: string | undefined
      const raw = err?.response?.data
      if (raw instanceof Blob) {
        try {
          const txt = await raw.text()
          try {
            detail = JSON.parse(txt)?.detail
          } catch {
            detail = txt || undefined
          }
        } catch {
          /* leave detail undefined */
        }
      } else if (typeof raw === "object" && raw !== null) {
        detail = (raw as { detail?: string }).detail
      }

      if (err?.response?.status === 403) {
        setError(
          detail ||
            "Downloads are locked on the trial. Subscribe to Basic or Pro to export."
        )
      } else if (err?.response?.status === 400) {
        setError(
          detail ||
            "Couldn't export — no approved segments yet. Approve segments in the editor before exporting."
        )
      } else {
        setError(detail || "Couldn't export this project.")
      }
    } finally {
      setBusy(null)
    }
  }

  // Audit HIGH-1 fix: previously this only updated local state, so
  // reviewers' edits were silently thrown away. Now we save with a
  // 700ms debounce per segment via PATCH /segments/{id}; the backend
  // also adds the (source → target) pair to the team's TM.
  const updateTargetText = (segId: string, value: string) => {
    setSegments((xs) =>
      xs.map((x) => (x.id === segId ? { ...x, translated_text: value } : x))
    )
    const w = window as unknown as {
      __segSaveTimers?: Record<string, number>
    }
    if (!w.__segSaveTimers) w.__segSaveTimers = {}
    if (w.__segSaveTimers[segId]) {
      window.clearTimeout(w.__segSaveTimers[segId])
    }
    w.__segSaveTimers[segId] = window.setTimeout(() => {
      api
        .patch(`/segments/${segId}`, { translated_text: value })
        .catch((err: any) => {
          console.error("SEGMENT SAVE ERROR:", err)
          setError(
            err?.response?.data?.detail ||
              "Couldn't save your edit — try again."
          )
        })
    }, 700)
  }

  const stats = useMemo(() => {
    if (!project) {
      return {
        total: segments.length,
        translated: 0,
        approved: 0,
        tmAvg: 0,
      }
    }
    return {
      total: project.stats.total_segments || segments.length,
      translated: project.stats.translated_segments,
      approved: project.stats.approved_segments,
      tmAvg: project.stats.tm_average_pct,
    }
  }, [project, segments])

  const teamAvatars = useMemo(() => {
    const list: Assignee[] = []
    if (project?.assignee) list.push(project.assignee)
    if (
      project?.uploader &&
      (!project.assignee || project.uploader.id !== project.assignee.id)
    )
      list.push(project.uploader)
    return list
  }, [project])

  const activeComments =
    activeSegment && comments[activeSegment.id] ? comments[activeSegment.id] : []
  const commentCount = activeComments.filter((c) => !c.resolved).length

  if (loading) {
    return (
      <div className="py-20 text-center" style={{ color: "#8a8270" }}>
        Loading editor…
      </div>
    )
  }

  if (error && !project) {
    return (
      <div className="py-20 text-center">
        <h2 className="text-xl font-semibold mb-2" style={{ color: "#1f2a2e" }}>
          Couldn&apos;t load this project
        </h2>
        <p className="mb-6" style={{ color: "#8a8270" }}>
          {error}
        </p>
        <button
          onClick={() => router.push("/jobs")}
          className="px-4 py-2 rounded-full text-sm font-semibold"
          style={{ background: "#0a7870", color: "#fff" }}
        >
          Back to Projects
        </button>
      </div>
    )
  }

  if (project && project.status !== "COMPLETED" && project.status !== "FAILED") {
    return (
      <div className="py-20 text-center">
        <h2 className="text-xl font-semibold mb-2" style={{ color: "#1f2a2e" }}>
          Processing your document…
        </h2>
        <p style={{ color: "#8a8270" }}>
          {project.progress_percent || 0}% complete · polling every 3 seconds
        </p>
      </div>
    )
  }

  if (!project) return null

  const stStyle = statusStyle(project.review_status)

  return (
    <div className="max-w-[1400px] mx-auto pb-12" onClick={() => setShowStatusMenu(false)}>
      {/* TOP META ROW */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-start gap-6">
          <button
            onClick={() => router.push("/jobs")}
            className="text-sm mt-2 hover:underline"
            style={{ color: "#0a7870" }}
          >
            ← Projects
          </button>
          <div>
            <div className="text-sm" style={{ color: "#8a8270" }}>
              {project.source_language || "—"}{" "}
              <span className="mx-1" style={{ color: "#cfc6ad" }}>
                →
              </span>{" "}
              {project.target_language || "—"}
            </div>
            <div className="flex items-center gap-2">
              <h1
                className="text-[30px] font-semibold tracking-tight"
                style={{ color: "#1f2a2e" }}
              >
                {project.file_name}
              </h1>
              <button
                type="button"
                onClick={() => {
                  setRenamingDraft(project.file_name || "")
                  setRenameOpen(true)
                }}
                title="Rename project"
                aria-label="Rename project"
                className="w-7 h-7 rounded-md flex items-center justify-center transition"
                style={{ color: "#6b6558" }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.background = "#f3ecdb")
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.background = "transparent")
                }
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M12 20h9" />
                  <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4Z" />
                </svg>
              </button>
            </div>
          </div>
        </div>

        <div
          className="flex items-center gap-3 mt-2"
          onClick={(e) => e.stopPropagation()}
        >
          {/* DELETE — opens the confirm modal. */}
          <button
            type="button"
            onClick={() => setDeleteOpen(true)}
            title="Delete project"
            aria-label="Delete project"
            className="inline-flex items-center gap-2 text-[12px] font-semibold tracking-[0.04em] px-3 py-1.5 rounded-full transition"
            style={{
              background: "#ffffff",
              color: "#b14a3a",
              border: "1px solid #e7b8b0",
            }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.background = "#f9efe9")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.background = "#ffffff")
            }
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 6h18" />
              <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              <path d="M19 6 18 21H6L5 6" />
            </svg>
            Delete
          </button>

          {/* COMPARE — swaps the segments table for a side-by-side
              view of the ORIGINAL document and the REBUILT output
              PDF so a reviewer can visually verify the rebuild. */}
          <button
            type="button"
            onClick={toggleCompareMode}
            className="inline-flex items-center gap-2 text-[12px] font-semibold tracking-[0.04em] px-3 py-1.5 rounded-full transition"
            style={{
              background: compareMode ? "#0a7870" : "#ffffff",
              color: compareMode ? "#ffffff" : "#1f2a2e",
              border: compareMode
                ? "1px solid #0a7870"
                : "1px solid #e7ddc5",
            }}
            title="Compare the original document with the rebuilt output"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="3" y="4" width="8" height="16" rx="1.5" />
              <rect x="13" y="4" width="8" height="16" rx="1.5" />
            </svg>
            {compareMode ? "Hide compare" : "Compare"}
          </button>

          {/* STATUS PILL with dropdown */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowStatusMenu((v) => !v)}
              className="inline-flex items-center gap-1.5 text-[12px] font-semibold tracking-[0.04em] px-3 py-1.5 rounded-full"
              style={{ background: stStyle.bg, color: stStyle.text }}
            >
              <span
                className="w-1.5 h-1.5 rounded-full"
                style={{ background: stStyle.dot }}
              />
              {stStyle.label}
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="m6 9 6 6 6-6" />
              </svg>
            </button>
            {showStatusMenu && (
              <div
                className="absolute right-0 mt-2 w-48 rounded-xl py-1 z-20"
                style={{
                  background: "#ffffff",
                  border: "1px solid #e7ddc5",
                  boxShadow: "0 8px 24px rgba(30,30,20,0.12)",
                }}
              >
                {REVIEW_STATUSES.map((s) => (
                  <button
                    key={s.value}
                    type="button"
                    onClick={() => updateReviewStatus(s.value)}
                    disabled={busy === "status"}
                    className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition"
                    style={{
                      color: "#1f2a2e",
                      background:
                        s.value === project.review_status ? "#faf5ee" : "transparent",
                    }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.background = "#faf5ee")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.background =
                        s.value === project.review_status ? "#faf5ee" : "transparent")
                    }
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: s.dot }}
                    />
                    <span className="flex-1">{s.label}</span>
                    {s.value === project.review_status && (
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
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {error && (
        <div
          className="text-sm rounded-lg px-3 py-2 mb-4"
          style={{ background: "#f2d4cf", color: "#7a2f24" }}
        >
          {error}
        </div>
      )}

      {/* TOOLBAR */}
      <div
        className="flex items-center gap-4 px-5 py-3 rounded-2xl mb-4 flex-wrap"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
      >
        <LangChip text={langCode(project.source_language)} />
        <span style={{ color: "#cfc6ad" }}>→</span>
        <LangChip text={langCode(project.target_language)} />
        <div className="h-6 w-px mx-1" style={{ background: "#f1e8d1" }} />
        <Stat
          label="translated"
          value={`${stats.total === 0 ? 0 : Math.round((stats.translated / stats.total) * 100)}%`}
        />
        <Stat
          label="approved"
          value={`${stats.approved} of ${stats.total}`}
        />
        <Stat label="TM" value={`${stats.tmAvg}%`} accent />
        <div className="flex-1" />

        {/* Team avatars (real assignee + uploader) */}
        <div className="flex items-center -space-x-1">
          {teamAvatars.map((u) => (
            <div
              key={u.id}
              title={u.email}
              className="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-semibold border-2"
              style={{ background: "#cfe6e2", color: "#0a7870", borderColor: "#fff" }}
            >
              {initialsFor(u)}
            </div>
          ))}
        </div>

        {/* Action buttons */}
        <button
          type="button"
          onClick={() => setShowApproveAllConfirm(true)}
          disabled={busy === "approve-all"}
          className="px-3 py-2 rounded-full text-sm font-semibold flex items-center gap-1.5 transition"
          style={{
            background: "#cfe6e2",
            color: "#0a7870",
            border: "1px solid #b8dcd6",
          }}
          title="Mark every translated segment as approved"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>
          {busy === "approve-all" && approveAllProgress
            ? `Approving ${approveAllProgress.done}/${approveAllProgress.total}…`
            : "Approve all translated"}
        </button>
        <button
          type="button"
          onClick={() => exportFile("docx")}
          disabled={busy === "export:docx"}
          className="px-3 py-2 rounded-full text-sm font-semibold flex items-center gap-1.5 transition"
          style={{
            background: "#ffffff",
            color: "#1f2a2e",
            border: "1px solid #e7ddc5",
          }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          {busy === "export:docx" ? "Preparing…" : "Export DOCX"}
        </button>
        <button
          type="button"
          onClick={() => exportFile("pdf")}
          disabled={busy === "export:pdf"}
          className="px-3 py-2 rounded-full text-sm font-semibold flex items-center gap-1.5 transition"
          style={{
            background: "#ffffff",
            color: "#1f2a2e",
            border: "1px solid #e7ddc5",
          }}
        >
          {busy === "export:pdf" ? "Preparing…" : "Export PDF"}
        </button>
        <button
          type="button"
          onClick={certify}
          disabled={busy === "certify" || project.review_status === "CERTIFIED"}
          className="px-4 py-2 rounded-full text-sm font-semibold flex items-center gap-1.5 transition"
          style={{
            background: project.review_status === "CERTIFIED" ? "#9bc9c5" : "#0a7870",
            color: "#fff",
          }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 3 4 6v6c0 5 3.4 8.4 8 9 4.6-.6 8-4 8-9V6Z" />
            <path d="m9 12 2 2 4-4" />
          </svg>
          {project.review_status === "CERTIFIED"
            ? "Certified"
            : busy === "certify"
            ? "Certifying…"
            : "Certify & deliver"}
        </button>
      </div>

      {/* MAIN AREA + SIDEBAR
          When Compare mode is OFF: segments table on the left, side
          panel on the right.
          When Compare mode is ON: the segments table is replaced by
          two side-by-side preview panes — original on the left and
          rebuilt output on the right. */}
      <div
        className="grid grid-cols-1 gap-4"
        style={{ gridTemplateColumns: "minmax(0, 1fr) 360px" }}
      >
        {compareMode ? (
          <div
            className="rounded-2xl overflow-hidden grid"
            style={{
              gridTemplateColumns: "1fr 1fr",
              gap: 12,
              height: "calc(100vh - 240px)",
              minHeight: 560,
            }}
          >
            {/* LEFT — ORIGINAL */}
            <ComparePane
              label="ORIGINAL"
              data={sourcePreview}
              loading={compareLoading}
              emptyHint="The source file isn't available."
            />
            {/* RIGHT — REBUILD */}
            <ComparePane
              label="REBUILT OUTPUT"
              data={
                rebuildPreview && rebuildPreview.url
                  ? {
                      url: rebuildPreview.url,
                      kind:
                        rebuildPreview.kind === "docx"
                          ? "other"
                          : (rebuildPreview.kind as "pdf" | "image" | "other"),
                      filename: rebuildPreview.filename || "",
                    }
                  : null
              }
              loading={compareLoading}
              emptyHint={
                rebuildPreview && !rebuildPreview.url
                  ? "Rebuild not generated yet — export the project as PDF or DOCX first, then come back here to compare."
                  : "Loading rebuild…"
              }
              docxFallback={
                rebuildPreview?.kind === "docx" && rebuildPreview.url
                  ? rebuildPreview.url
                  : null
              }
            />
          </div>
        ) : null}

        {!compareMode && (
        /* SEGMENTS TABLE */
        <div className="contents">
        {/* SEGMENTS TABLE */}
        <div
          className="rounded-2xl overflow-hidden"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
        >
          <div
            className="grid items-center text-[11px] font-semibold tracking-[0.14em] px-5 py-3"
            style={{
              gridTemplateColumns: "60px 1fr 1fr 80px 60px",
              background: "#faf5ee",
              borderBottom: "1px solid #f1e8d1",
              color: "#9a9178",
            }}
          >
            <div>#</div>
            <div>SOURCE · {project.source_language?.toUpperCase() || ""}</div>
            <div>TARGET · {project.target_language?.toUpperCase() || ""}</div>
            <div className="text-right">TM</div>
            <div className="text-right">✓</div>
          </div>

          {segments.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm" style={{ color: "#8a8270" }}>
              This project has no translated segments yet.
            </div>
          ) : (
            segments.map((seg, idx) => {
              const isActive = idx === activeIdx
              return (
                <div
                  key={seg.id}
                  onClick={() => setActiveIdx(idx)}
                  className="grid items-start px-5 py-4 text-sm cursor-pointer transition"
                  style={{
                    gridTemplateColumns: "60px 1fr 1fr 80px 60px",
                    borderBottom: "1px solid #f4ecd6",
                    background: isActive ? "#faf5ee" : "#ffffff",
                    color: "#1f2a2e",
                  }}
                >
                  <div
                    className="font-mono text-[11px] tabular-nums pt-1"
                    style={{ color: "#9a9178" }}
                  >
                    {String(seg.segment_index).padStart(2, "0")}
                  </div>
                  <div
                    className="leading-relaxed pr-3"
                    style={{ color: "#4a4638" }}
                  >
                    {seg.source_text}
                  </div>
                  <textarea
                    value={seg.translated_text}
                    onChange={(e) => updateTargetText(seg.id, e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    rows={Math.max(1, Math.ceil(seg.translated_text.length / 60))}
                    className="bg-transparent outline-none resize-none leading-relaxed font-medium pr-3"
                    style={{ color: "#1f2a2e" }}
                  />
                  <div className="text-right text-xs tabular-nums pt-1">
                    {seg.tm_pct != null ? (
                      <span
                        className="inline-flex items-center px-1.5 py-0.5 rounded-md font-semibold"
                        style={{
                          background:
                            seg.tm_pct >= 95
                              ? "#d8ead6"
                              : seg.tm_pct >= 80
                              ? "#f6e3b8"
                              : "#f3ecdb",
                          color:
                            seg.tm_pct >= 95
                              ? "#2d5a24"
                              : seg.tm_pct >= 80
                              ? "#7a5a10"
                              : "#6b6558",
                        }}
                      >
                        {seg.tm_pct}%
                      </span>
                    ) : (
                      <span style={{ color: "#cfc6ad" }}>—</span>
                    )}
                  </div>
                  <div className="flex justify-end pt-0.5">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        toggleApprove(seg)
                      }}
                      disabled={busy === `approve:${seg.id}`}
                      aria-label={seg.approved ? "Unapprove" : "Approve"}
                      title={seg.approved ? "Unapprove" : "Approve"}
                      className="w-6 h-6 rounded-full flex items-center justify-center transition"
                      style={{
                        background: seg.approved ? "#0a7870" : "#f3ecdb",
                        color: seg.approved ? "#fff" : "#9a9178",
                        border: `1px solid ${
                          seg.approved ? "#0a645d" : "#e7ddc5"
                        }`,
                      }}
                    >
                      <svg
                        width="13"
                        height="13"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="3"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="m5 12 5 5 10-10" />
                      </svg>
                    </button>
                  </div>
                </div>
              )
            })
          )}
        </div>
        </div>
        )}

        {/* SIDEBAR */}
        <aside
          className="rounded-2xl overflow-hidden flex flex-col h-fit sticky top-4"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
        >
          <div
            className="grid grid-cols-3"
            style={{ borderBottom: "1px solid #f1e8d1" }}
          >
            <SideTab
              label="Comments"
              count={commentCount}
              active={tab === "comments"}
              onClick={() => setTab("comments")}
            />
            <SideTab
              label="Glossary"
              count={glossaryCount}
              active={tab === "glossary"}
              onClick={() => setTab("glossary")}
            />
            <SideTab
              label="Status"
              active={tab === "status"}
              onClick={() => setTab("status")}
            />
          </div>

          <div className="p-5 min-h-[260px]">
            {tab === "comments" && activeSegment && (
              <>
                <div
                  className="text-[10px] font-semibold tracking-[0.14em] mb-3"
                  style={{ color: "#9a9178" }}
                >
                  COMMENTS ON SEGMENT #{String(activeSegment.segment_index).padStart(2, "0")}
                </div>

                {activeComments.length === 0 ? (
                  <div
                    className="text-sm text-center py-8"
                    style={{ color: "#8a8270" }}
                  >
                    No comments on this segment yet.
                  </div>
                ) : (
                  <div className="space-y-3 mb-4">
                    {activeComments.map((c) => (
                      <div
                        key={c.id}
                        className="rounded-xl p-3"
                        style={{
                          background: c.resolved ? "#f3ecdb" : "#fbf7ee",
                          border: `1px solid ${c.resolved ? "#e7ddc5" : "#f1e8d1"}`,
                          opacity: c.resolved ? 0.65 : 1,
                        }}
                      >
                        <div className="flex items-center justify-between mb-1.5 gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <div
                              className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold shrink-0"
                              style={{ background: "#cfe6e2", color: "#0a7870" }}
                            >
                              {(c.user.email || "??").slice(0, 2).toUpperCase()}
                            </div>
                            <div
                              className="text-[12px] font-medium truncate"
                              style={{ color: "#1f2a2e" }}
                            >
                              {c.user.email}
                            </div>
                          </div>
                          <div
                            className="text-[10px] shrink-0"
                            style={{ color: "#9a9178" }}
                          >
                            {relativeTime(c.created_at)}
                          </div>
                        </div>
                        <div
                          className="text-sm leading-relaxed mb-2"
                          style={{
                            color: "#1f2a2e",
                            textDecoration: c.resolved ? "line-through" : "none",
                          }}
                        >
                          {c.text}
                        </div>
                        {!c.resolved ? (
                          <button
                            type="button"
                            onClick={() => resolveComment(c.id)}
                            disabled={busy === `resolve:${c.id}`}
                            className="text-[11px] font-semibold tracking-[0.06em] px-2.5 py-1 rounded-full transition"
                            style={{
                              background: "#cfe6e2",
                              color: "#0a5e58",
                              border: "1px solid #b7dad4",
                            }}
                          >
                            {busy === `resolve:${c.id}`
                              ? "Resolving…"
                              : "Mark as revised"}
                          </button>
                        ) : (
                          <span
                            className="text-[11px] font-semibold tracking-[0.06em] px-2.5 py-1 rounded-full inline-flex items-center gap-1"
                            style={{ background: "#d8ead6", color: "#2d5a24" }}
                          >
                            <svg
                              width="11"
                              height="11"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="3"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <path d="m5 12 5 5 10-10" />
                            </svg>
                            Revised
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* New comment box */}
                <div
                  className="rounded-xl p-3"
                  style={{
                    background: "#faf5ee",
                    border: "1px solid #e7ddc5",
                  }}
                >
                  <textarea
                    value={newComment}
                    onChange={(e) => setNewComment(e.target.value)}
                    placeholder="Leave a note for the reviewer…"
                    rows={2}
                    className="bg-transparent outline-none w-full text-sm resize-none leading-relaxed"
                    style={{ color: "#1f2a2e" }}
                  />
                  <div className="flex justify-end mt-2">
                    <button
                      type="button"
                      onClick={addComment}
                      disabled={busy === "comment" || !newComment.trim()}
                      className="px-3 py-1.5 rounded-full text-[12px] font-semibold transition"
                      style={{
                        background:
                          busy === "comment" || !newComment.trim()
                            ? "#9bc9c5"
                            : "#0a7870",
                        color: "#fff",
                        cursor:
                          busy === "comment" || !newComment.trim()
                            ? "not-allowed"
                            : "pointer",
                      }}
                    >
                      {busy === "comment" ? "Posting…" : "Add comment"}
                    </button>
                  </div>
                </div>
              </>
            )}

            {tab === "glossary" && (
              <>
                <div
                  className="text-[10px] font-semibold tracking-[0.14em] mb-3"
                  style={{ color: "#9a9178" }}
                >
                  GLOSSARY
                </div>
                <div
                  className="text-sm text-center py-8"
                  style={{ color: "#8a8270" }}
                >
                  {glossaryCount > 0
                    ? `${glossaryCount} approved term${glossaryCount === 1 ? "" : "s"} available across the team.`
                    : "No glossary terms yet — add them from the Glossary page."}
                </div>
              </>
            )}

            {tab === "status" && (
              <>
                <div
                  className="text-[10px] font-semibold tracking-[0.14em] mb-3"
                  style={{ color: "#9a9178" }}
                >
                  PROJECT STATUS
                </div>
                <div className="space-y-3">
                  <StatusRow label="Translation" value={project.status} />
                  <StatusRow label="Review" value={stStyle.label} />
                  <StatusRow
                    label="Translated"
                    value={`${stats.translated} / ${stats.total} segments`}
                  />
                  <StatusRow
                    label="Approved"
                    value={`${stats.approved} / ${stats.total} segments`}
                  />
                  <StatusRow label="Avg. TM match" value={`${stats.tmAvg}%`} />
                </div>
              </>
            )}
          </div>
        </aside>
      </div>

      {/* APPROVE ALL — confirmation modal */}
      {showApproveAllConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(20, 18, 10, 0.45)" }}
          onClick={() => setShowApproveAllConfirm(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="approve-all-title"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-2xl p-6"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 10px 30px rgba(30,30,20,0.18)",
            }}
          >
            <div className="flex items-start gap-3 mb-4">
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                style={{ background: "#cfe6e2", color: "#0a7870" }}
              >
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
              <div className="flex-1">
                <h2
                  id="approve-all-title"
                  className="text-[18px] font-semibold tracking-tight"
                  style={{ color: "#1f2a2e" }}
                >
                  Approve all translated segments?
                </h2>
                <p
                  className="text-sm mt-1"
                  style={{ color: "#6b6558" }}
                >
                  This will mark every segment that has a translation as
                  approved — {(() => {
                    const n = segments.filter(
                      (s) =>
                        !s.approved &&
                        s.translated_text &&
                        s.translated_text.trim()
                    ).length
                    return `${n} segment${n === 1 ? "" : "s"} pending`
                  })()}.
                  You can still unapprove individual segments afterwards.
                </p>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-2">
              <button
                type="button"
                onClick={() => setShowApproveAllConfirm(false)}
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
                onClick={approveAllTranslated}
                className="px-4 py-2 rounded-full text-sm font-semibold"
                style={{ background: "#0a7870", color: "#fff" }}
              >
                Approve all
              </button>
            </div>
          </div>
        </div>
      )}

      {/* RENAME MODAL */}
      {renameOpen && (
        <div
          onClick={() => !renameBusy && setRenameOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(31,42,46,0.45)",
            backdropFilter: "blur(2px)",
            zIndex: 100,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="rounded-2xl p-6 w-full max-w-md"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 24px 60px rgba(30,30,20,0.18)",
            }}
          >
            <div
              className="text-[11px] font-semibold tracking-[0.18em] mb-1"
              style={{ color: "#9a9178" }}
            >
              RENAME PROJECT
            </div>
            <h3 className="text-[18px] font-semibold tracking-tight mb-4" style={{ color: "#1f2a2e" }}>
              Pick a clearer name
            </h3>
            <input
              autoFocus
              value={renamingDraft}
              onChange={(e) => setRenamingDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitRename()
                if (e.key === "Escape" && !renameBusy) setRenameOpen(false)
              }}
              className="w-full text-sm outline-none px-4 py-2.5 rounded-xl"
              style={{
                background: "#faf5ee",
                border: "1px solid #e7ddc5",
                color: "#1f2a2e",
              }}
            />
            <div className="flex items-center justify-end gap-2 mt-5">
              <button
                type="button"
                onClick={() => setRenameOpen(false)}
                disabled={renameBusy}
                className="px-4 py-2 rounded-full text-sm font-semibold"
                style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitRename}
                disabled={renameBusy || !renamingDraft.trim()}
                className="px-4 py-2 rounded-full text-sm font-semibold"
                style={{
                  background: renameBusy || !renamingDraft.trim() ? "#9bc9c5" : "#0a7870",
                  color: "#fff",
                  cursor: renameBusy || !renamingDraft.trim() ? "not-allowed" : "pointer",
                }}
              >
                {renameBusy ? "Saving…" : "Save name"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* DELETE MODAL */}
      {deleteOpen && (
        <div
          onClick={() => !deleteBusy && setDeleteOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(31,42,46,0.45)",
            backdropFilter: "blur(2px)",
            zIndex: 100,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="rounded-2xl p-6 w-full max-w-md"
            style={{
              background: "#ffffff",
              border: "1px solid #e7b8b0",
              boxShadow: "0 24px 60px rgba(177,74,58,0.20)",
            }}
          >
            <div
              className="text-[11px] font-semibold tracking-[0.18em] mb-1"
              style={{ color: "#b14a3a" }}
            >
              DELETE PROJECT
            </div>
            <h3 className="text-[18px] font-semibold tracking-tight mb-3" style={{ color: "#1f2a2e" }}>
              Permanently remove this project?
            </h3>
            <p className="text-sm mb-5" style={{ color: "#6b6558" }}>
              This deletes the project, its segments, comments, and the uploaded source file. This action cannot be undone.
            </p>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeleteOpen(false)}
                disabled={deleteBusy}
                className="px-4 py-2 rounded-full text-sm font-semibold"
                style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
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
        </div>
      )}
    </div>
  )
}

// ============================================================
// Local subcomponents
// ============================================================

// Microsoft Office Online viewer renders DOCX / XLSX / PPTX inline by
// fetching the signed URL on their servers and returning a rendered
// HTML viewer — so Word files never trigger a browser download.
function officeViewerUrl(srcUrl: string) {
  return `https://view.officeapps.live.com/op/embed.aspx?src=${encodeURIComponent(srcUrl)}`
}

// Google Docs viewer renders PDFs inline by fetching the URL on
// Google's servers. We use this for PDF sources because some object
// stores (Supabase) don't honor the inline content-disposition
// query param, which causes the browser to download instead of
// preview when the PDF URL is loaded directly in an iframe.
function gdocsViewerUrl(srcUrl: string) {
  return `https://docs.google.com/viewer?url=${encodeURIComponent(srcUrl)}&embedded=true`
}

function ComparePane({
  label,
  data,
  loading,
  emptyHint,
  docxFallback,
}: {
  label: string
  data: { url: string; kind: "pdf" | "image" | "other"; filename: string } | null
  loading: boolean
  emptyHint: string
  docxFallback?: string | null
}) {
  // Pick the iframe source URL based on file kind:
  //  - DOCX (kind="other" with docxFallback) → Office Online viewer
  //    so Word files render inline rather than triggering a download.
  //  - PDF → Google Docs viewer. Direct iframe of the signed URL was
  //    triggering a browser download because Supabase Storage doesn't
  //    consistently honor the response-content-disposition=inline
  //    query param. Google fetches the PDF on their side and serves
  //    a renderer iframe, sidestepping the issue entirely.
  //  - Everything else → no iframe; fall through to image/other UI.
  const iframeSrc =
    data?.kind === "other" && docxFallback
      ? officeViewerUrl(docxFallback)
      : data?.kind === "pdf"
      ? gdocsViewerUrl(data.url)
      : null

  return (
    <div
      className="rounded-2xl overflow-hidden flex flex-col"
      style={{
        background: "#ffffff",
        border: "1px solid #e7ddc5",
        minHeight: 0,
      }}
    >
      <div
        className="px-4 py-2.5 flex items-center justify-between text-[11px] font-semibold tracking-[0.14em]"
        style={{
          color: "#9a9178",
          background: "#faf5ee",
          borderBottom: "1px solid #f1e8d1",
        }}
      >
        <span>{label}</span>
        {data && (
          <a
            href={data.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] font-semibold tracking-[0.1em] hover:underline"
            style={{ color: "#0a7870" }}
          >
            OPEN ↗
          </a>
        )}
      </div>
      <div
        className="flex-1 overflow-auto"
        style={{ background: "#fbf6ea", minHeight: 0 }}
      >
        {loading && !data && (
          <div className="px-4 py-8 text-sm text-center" style={{ color: "#8a8270" }}>
            Loading…
          </div>
        )}
        {!loading && !data && (
          <div className="px-4 py-8 text-sm text-center" style={{ color: "#8a8270" }}>
            {emptyHint}
          </div>
        )}
        {iframeSrc && (
          <iframe
            src={iframeSrc}
            title={data?.filename || ""}
            className="w-full h-full"
            style={{ border: 0, background: "#fff", minHeight: 500 }}
            // sandbox is omitted on purpose — Office Online viewer
            // needs to run scripts to render the document.
          />
        )}
        {data?.kind === "image" && (
          <div className="flex items-start justify-center p-3">
            <img
              src={data.url}
              alt={data.filename}
              style={{ maxWidth: "100%", height: "auto" }}
            />
          </div>
        )}
        {data?.kind === "other" && !docxFallback && (
          <div className="px-4 py-8 text-sm text-center" style={{ color: "#8a8270" }}>
            This file type can't be previewed inline.{" "}
            <a
              href={data.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: "#0a7870", textDecoration: "underline" }}
            >
              Open in a new tab
            </a>
            .
          </div>
        )}
      </div>
    </div>
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

function Stat({
  label,
  value,
  accent,
}: {
  label: string
  value: string
  accent?: boolean
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span
        className="text-sm font-semibold tabular-nums"
        style={{ color: accent ? "#b06a2a" : "#1f2a2e" }}
      >
        {value}
      </span>
      <span className="text-[11px]" style={{ color: "#8a8270" }}>
        {label}
      </span>
    </div>
  )
}

function SideTab({
  label,
  count,
  active,
  onClick,
}: {
  label: string
  count?: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="py-3 text-center transition"
      style={{
        borderBottom: active ? "2px solid #0a7870" : "2px solid transparent",
        color: active ? "#0a7870" : "#8a8270",
      }}
    >
      <div className="text-xs font-semibold flex items-center justify-center gap-1">
        {label}
        {typeof count === "number" && (
          <span
            className="text-[10px] tabular-nums px-1 rounded-full"
            style={{ color: "#9a9178" }}
          >
            · {count}
          </span>
        )}
      </div>
    </button>
  )
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="flex items-center justify-between py-2"
      style={{ borderBottom: "1px solid #f1e8d1" }}
    >
      <div className="text-sm" style={{ color: "#6b6558" }}>
        {label}
      </div>
      <div className="text-sm font-semibold" style={{ color: "#1f2a2e" }}>
        {value}
      </div>
    </div>
  )
}
