"use client"

import { useEffect, useMemo, useState, useCallback, useRef } from "react"
import { useParams, useRouter } from "next/navigation"
import { api, apiErrorDetail, fetchObjectUrl } from "@/lib/api"
import DocumentEditor from "@/components/editor/DocumentEditor"

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

  model?: string | null
  stats: {
    total_segments: number
    translated_segments: number
    approved_segments: number
    tm_average_pct: number
  }
  assignee: Assignee | null
  uploader: Assignee | null
  failure_reason?: string | null
  rebuild_status?: "running" | "done" | "failed" | null
  rebuild_error?: string | null
  revision_count?: number
  free_revisions_left?: number
}

type ConfirmState = {
  title: string
  body: string
  confirmLabel: string
  onConfirm: () => void
}

function revisionCostText(freeLeft: number | undefined) {
  if (freeLeft && freeLeft > 0) {
    return `${freeLeft} free revision${freeLeft === 1 ? "" : "s"} left on this project, so this one is free.`
  }
  return "No free revisions left on this project. This will cost credits equal to the document's page count."
}

type Tab = "glossary" | "status"

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

export default function EditorPage() {
  const router = useRouter()
  const params = useParams()
  const id = params?.id as string

  const [project, setProject] = useState<ProjectInfo | null>(null)
  const [segments, setSegments] = useState<Segment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null)
  const [tab, setTab] = useState<Tab>("status")
  const [compareReloadKey, setCompareReloadKey] = useState(0)

  const [busy, setBusy] = useState<string | null>(null)
  const [glossaryCount, setGlossaryCount] = useState<number>(0)
  const [showStatusMenu, setShowStatusMenu] = useState(false)
  const [showApproveAllConfirm, setShowApproveAllConfirm] =
    useState<boolean>(false)
  const [approveAllProgress, setApproveAllProgress] = useState<{
    done: number
    total: number
  } | null>(null)

  const [chatOpen, setChatOpen] = useState(false)
  const [sourcePreview, setSourcePreview] = useState<{
    url: string
    kind: "pdf" | "image" | "other"
    filename: string
  } | null>(null)
  const [compareLoading, setCompareLoading] = useState(false)
  const sourceObjectUrlRef = useRef<string | null>(null)

  const replaceSourcePreview = (next: typeof sourcePreview) => {
    if (sourceObjectUrlRef.current) URL.revokeObjectURL(sourceObjectUrlRef.current)
    sourceObjectUrlRef.current = next?.url ?? null
    setSourcePreview(next)
  }

  useEffect(() => {
    return () => {
      if (sourceObjectUrlRef.current) URL.revokeObjectURL(sourceObjectUrlRef.current)
    }
  }, [])

  const loadCompare = async () => {
    setCompareLoading(true)
    try {
      const { url, type } = await fetchObjectUrl(`/projects/${id}/preview/source`)
      const kind =
        type === "application/pdf" ? "pdf" : type.startsWith("image/") ? "image" : "other"
      replaceSourcePreview({ url, kind, filename: project?.file_name || "source" })
    } catch {
      replaceSourcePreview(null)
    } finally {
      setCompareLoading(false)
    }
  }

  const [compareActionBusy, setCompareActionBusy] = useState<
    null | "revise" | "rerun"
  >(null)
  const [showRerunPicker, setShowRerunPicker] = useState(false)
  const [translationModels, setTranslationModels] = useState<
    { id: string; label: string; provider: string }[]
  >([])

  useEffect(() => {

    api
      .get("/projects/translation-models")
      .then((res) => setTranslationModels(res.data?.models || []))
      .catch(() => setTranslationModels([]))
  }, [])

  const [revisionModal, setRevisionModal] = useState<{
    open: boolean
    instructions: string
    model: string
  }>({ open: false, instructions: "", model: "" })

  const openRevisionModal = () => {
    setRevisionModal({
      open: true,
      instructions: "",
      model:
        project?.model || translationModels[0]?.id || "claude-sonnet-4-6",
    })
  }

  const markRebuildRunning = (revisionCount?: number) => {
    setProject((p) =>
      p
        ? {
            ...p,
            rebuild_status: "running",
            rebuild_error: null,
            revision_count: revisionCount ?? p.revision_count,
          }
        : p,
    )
  }

  const submitRevision = async () => {
    try {
      setCompareActionBusy("revise")
      setError(null)
      setRevisionModal((m) => ({ ...m, open: false }))
      const res = await api.post(`/projects/${id}/revise`, {
        instructions: revisionModal.instructions.trim() || null,
        model: revisionModal.model || null,
      })
      markRebuildRunning(res.data?.revision_count)
      setNotice(
        "Revision started. The preview updates here when it finishes, usually in 1-5 minutes.",
      )
    } catch (err: unknown) {
      setError(apiErrorDetail(err, "Revision request failed."))
    } finally {
      setCompareActionBusy(null)
    }
  }

  const startRegenerate = () => {
    setConfirmState({
      title: "Regenerate the translation",
      body:
        "The whole translation is redone from the original, replacing your edits (you can undo it). It runs in the background and usually takes 1-3 minutes.\n\n" +
        revisionCostText(project?.free_revisions_left),
      confirmLabel: "Regenerate",
      onConfirm: async () => {
        try {
          setCompareActionBusy("rerun")
          setError(null)
          const res = await api.post(`/projects/${id}/rebuild-with-claude`)
          markRebuildRunning(res.data?.revision_count)
          setNotice(
            "Regenerating. The document updates here when it finishes.",
          )
        } catch (err: unknown) {
          setError(apiErrorDetail(err, "Couldn't start regenerating."))
        } finally {
          setCompareActionBusy(null)
        }
      },
    })
  }

  const requestRevision = openRevisionModal

  const [glossaryDraft, setGlossaryDraft] = useState<{
    open: boolean
    sourceTerm: string
    targetTerm: string
    notes: string
    busy: boolean
  }>({ open: false, sourceTerm: "", targetTerm: "", notes: "", busy: false })

  const openGlossaryFromSegment = (seg: Segment) => {
    setGlossaryDraft({
      open: true,
      sourceTerm: seg.source_text || "",
      targetTerm: seg.translated_text || "",
      notes: "",
      busy: false,
    })
  }

  const saveGlossaryDraft = async () => {
    const src = glossaryDraft.sourceTerm.trim()
    const tgt = glossaryDraft.targetTerm.trim()
    if (!src || !tgt) {
      setError("Source term and target term are both required.")
      return
    }
    try {
      setGlossaryDraft((g) => ({ ...g, busy: true }))
      await api.post("/glossary", {
        source_language: project?.source_language || "auto",
        target_language: project?.target_language || "en-GB",
        source_term: src,
        target_term: tgt,
        notes: glossaryDraft.notes.trim() || null,
      })
      setGlossaryDraft({
        open: false,
        sourceTerm: "",
        targetTerm: "",
        notes: "",
        busy: false,
      })
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          "Couldn't add that term to the glossary.",
      )
      setGlossaryDraft((g) => ({ ...g, busy: false }))
    }
  }

  const [glossarySuggestions, setGlossarySuggestions] = useState<{
    open: boolean
    loading: boolean
    proposals: { source_term: string; target_term: string; frequency: number; context: string }[]
    saving: Set<number>
  }>({
    open: false,
    loading: false,
    proposals: [],
    saving: new Set<number>(),
  })

  const suggestGlossary = async () => {
    try {
      setGlossarySuggestions({
        open: true,
        loading: true,
        proposals: [],
        saving: new Set(),
      })
      const res = await api.post(`/projects/${id}/suggest-glossary`)
      setGlossarySuggestions({
        open: true,
        loading: false,
        proposals: res.data?.proposals || [],
        saving: new Set(),
      })
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          "Couldn't get glossary suggestions.",
      )
      setGlossarySuggestions({
        open: false,
        loading: false,
        proposals: [],
        saving: new Set(),
      })
    }
  }

  const acceptGlossarySuggestion = async (
    idx: number,
    p: { source_term: string; target_term: string },
  ) => {
    setGlossarySuggestions((s) => ({
      ...s,
      saving: new Set(s.saving).add(idx),
    }))
    try {
      await api.post("/glossary", {
        source_language: project?.source_language || "auto",
        target_language: project?.target_language || "en-GB",
        source_term: p.source_term,
        target_term: p.target_term,
        notes: null,
      })

      setGlossarySuggestions((s) => ({
        ...s,
        proposals: s.proposals.filter((_, i) => i !== idx),
        saving: new Set(
          [...s.saving].filter((i) => i !== idx),
        ),
      }))
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || "Couldn't add that term.",
      )
      setGlossarySuggestions((s) => {
        const nset = new Set(s.saving)
        nset.delete(idx)
        return { ...s, saving: nset }
      })
    }
  }

  const rerunTranslation = (modelOverride?: string | null) => {
    setShowRerunPicker(false)
    setConfirmState({
      title: "Re-run translation",
      body:
        "This re-translates the whole document and replaces every existing translation. Approval flags are cleared.\n\n" +
        "It is charged like a new upload: credits equal to the document's page count.",
      confirmLabel: "Re-run and charge credits",
      onConfirm: async () => {
        try {
          setCompareActionBusy("rerun")
          setError(null)
          const res = await api.post(`/projects/${id}/rerun`, {
            model: modelOverride || null,
          })
          setProject((p) =>
            p
              ? {
                  ...p,
                  status: res.data?.status || "PENDING",
                  progress_percent: 0,
                  failure_reason: null,
                }
              : p,
          )
        } catch (err: unknown) {
          setError(apiErrorDetail(err, "Re-run failed."))
        } finally {
          setCompareActionBusy(null)
        }
      },
    })
  }

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

  useEffect(() => {
    if (project && !sourcePreview) {
      loadCompare()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project])

  useEffect(() => {
    if (!project) return
    if (project.status === "COMPLETED" || project.status === "FAILED") return
    const t = setInterval(fetchProject, 3000)
    return () => clearInterval(t)
  }, [project, fetchProject])

  const rebuildRunning = project?.rebuild_status === "running"

  useEffect(() => {
    if (!rebuildRunning) return
    let cancelled = false
    const t = setInterval(async () => {
      try {
        const res = await api.get(`/projects/${id}`)
        if (cancelled) return
        const next = res.data as ProjectInfo
        if (next.rebuild_status === "done") {
          await fetchProject()
          if (cancelled) return
          setCompareReloadKey((k) => k + 1)
          setNotice("Rebuild finished. The preview has been updated.")
        } else if (next.rebuild_status === "failed") {
          setProject(next)
          setNotice(null)
          setError(next.rebuild_error || "The rebuild failed.")
        } else {
          setProject(next)
        }
      } catch {
        // Transient poll failure; the next tick retries.
      }
    }, 5000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [rebuildRunning, id, fetchProject])

  useEffect(() => {
    api
      .get("/glossary")
      .then((res) => setGlossaryCount((res.data || []).length))
      .catch(() => setGlossaryCount(0))
  }, [])

  const approveAllTranslated = async () => {

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
      {}
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
          {}
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

          {}
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

      {project.status === "FAILED" && (
        <div
          className="text-sm rounded-lg px-3 py-2 mb-4"
          style={{ background: "#f2d4cf", color: "#7a2f24" }}
        >
          Translation failed{project.failure_reason ? `: ${project.failure_reason}` : "."}
        </div>
      )}

      {notice && (
        <div
          className="text-sm rounded-lg px-3 py-2 mb-4 flex items-start justify-between gap-3"
          style={{ background: "#d8ead6", color: "#2d5a24" }}
        >
          <span>
            {rebuildRunning && "↻ "}
            {notice}
          </span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Dismiss"
            className="text-xs font-semibold"
          >
            ✕
          </button>
        </div>
      )}

      {}
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

        {}
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

        {}
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

      <div>
        <div className="flex flex-col">
            <div
              className="flex items-center justify-between gap-3 mb-3 px-4 py-3 rounded-2xl"
              style={{
                background: "#ffffff",
                border: "1px solid #e7ddc5",
              }}
            >
              <div className="text-[12px]" style={{ color: "#8a8270" }}>
                Type in the translation to edit it. Select text and use Ask AI for bigger changes.
              </div>
              <div
                className="flex items-center gap-2 relative"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  onClick={() => startRegenerate()}
                  disabled={compareActionBusy !== null || rebuildRunning}
                  className="inline-flex items-center gap-1.5 text-[12px] font-semibold tracking-[0.04em] px-3 py-1.5 rounded-full transition"
                  style={{
                    background: "#ffffff",
                    color: "#1f2a2e",
                    border: "1px solid #e7ddc5",
                    cursor:
                      compareActionBusy !== null ? "not-allowed" : "pointer",
                  }}
                  title="Redo the whole translation from the original, replacing your edits"
                >
                  {rebuildRunning ? "Regenerating…" : "↻ Regenerate"}
                </button>
              </div>
            </div>

            <div
              className="grid"
              style={{
                gridTemplateColumns: chatOpen
                  ? "minmax(0, 0.75fr) minmax(0, 1.6fr)"
                  : "minmax(0, 1fr) minmax(0, 1fr)",
                gap: 12,
                height: "calc(100vh - 32px)",
                minHeight: 560,
              }}
            >
              <ComparePane
                label="ORIGINAL"
                data={sourcePreview}
                loading={compareLoading}
                emptyHint="The source file isn't available."
              />
              <DocumentEditor
                projectId={String(id)}
                reloadKey={compareReloadKey}
                onChatOpenChange={setChatOpen}
              />
            </div>
          </div>
      </div>

      <aside
        className="rounded-2xl overflow-hidden flex flex-col mt-4"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
      >
        <div
          className="grid grid-cols-2"
          style={{ borderBottom: "1px solid #f1e8d1" }}
        >
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

        <div className="p-5">
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

      {}
      {glossarySuggestions.open && (
        <div
          onClick={() =>
            setGlossarySuggestions((s) => ({ ...s, open: false }))
          }
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
            className="rounded-2xl p-6 w-full max-w-2xl"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 24px 60px rgba(30,30,20,0.18)",
              maxHeight: "80vh",
              overflowY: "auto",
            }}
          >
            <div
              className="text-[11px] font-semibold tracking-[0.18em] mb-1"
              style={{ color: "#9a9178" }}
            >
              AI GLOSSARY SUGGESTIONS
            </div>
            <h3
              className="text-[18px] font-semibold tracking-tight mb-4"
              style={{ color: "#1f2a2e" }}
            >
              Recurring terms found in this project
            </h3>
            {glossarySuggestions.loading && (
              <div className="text-sm" style={{ color: "#8a8270" }}>
                Scanning translated segments for recurring terms…
              </div>
            )}
            {!glossarySuggestions.loading &&
              glossarySuggestions.proposals.length === 0 && (
                <div className="text-sm" style={{ color: "#8a8270" }}>
                  No recurring terms surfaced. The AI looks for proper
                  nouns, technical terms, and recurring phrases — short
                  or very simple projects often have nothing worth
                  pinning.
                </div>
              )}
            <div className="space-y-2 mt-2">
              {glossarySuggestions.proposals.map((p, idx) => {
                const saving = glossarySuggestions.saving.has(idx)
                return (
                  <div
                    key={idx}
                    className="rounded-xl p-3 flex items-center gap-3"
                    style={{
                      background: "#faf5ee",
                      border: "1px solid #e7ddc5",
                    }}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span
                          className="font-mono text-[13px] font-semibold"
                          style={{ color: "#1f2a2e" }}
                        >
                          {p.source_term}
                        </span>
                        <span style={{ color: "#cfc6ad" }}>→</span>
                        <span
                          className="font-mono text-[13px] font-semibold"
                          style={{ color: "#0a7870" }}
                        >
                          {p.target_term}
                        </span>
                        <span
                          className="text-[10px] tabular-nums px-1.5 py-0.5 rounded-full"
                          style={{
                            background: "#cfe6e2",
                            color: "#0a5e58",
                          }}
                        >
                          ×{p.frequency}
                        </span>
                      </div>
                      {p.context && (
                        <div
                          className="text-[11px] truncate"
                          style={{ color: "#8a8270" }}
                          title={p.context}
                        >
                          {p.context}
                        </div>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => acceptGlossarySuggestion(idx, p)}
                      disabled={saving}
                      className="px-3 py-1.5 rounded-full text-[12px] font-semibold transition shrink-0"
                      style={{
                        background: saving ? "#9bc9c5" : "#0a7870",
                        color: "#fff",
                        cursor: saving ? "not-allowed" : "pointer",
                      }}
                    >
                      {saving ? "Saving…" : "Add"}
                    </button>
                  </div>
                )
              })}
            </div>
            <div className="flex items-center justify-end mt-5">
              <button
                type="button"
                onClick={() =>
                  setGlossarySuggestions((s) => ({ ...s, open: false }))
                }
                className="px-4 py-2 rounded-full text-sm font-semibold"
                style={{
                  background: "#ffffff",
                  color: "#1f2a2e",
                  border: "1px solid #e7ddc5",
                }}
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {}
      {}
      {revisionModal.open && (
        <div
          onClick={() =>
            setRevisionModal((m) => ({ ...m, open: false }))
          }
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(31,42,46,0.45)",
            backdropFilter: "blur(2px)",
            zIndex: 100,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 520,
              maxWidth: "92vw",
              background: "#fbf6ea",
              borderRadius: 18,
              boxShadow: "0 18px 40px rgba(0,0,0,0.25)",
              padding: 24,
              border: "1px solid #e7ddc5",
            }}
          >
            <div
              className="text-[11px] font-semibold tracking-[0.16em]"
              style={{ color: "#8a8270", marginBottom: 6 }}
            >
              REQUEST REVISION
            </div>
            <div
              className="text-[16px] font-semibold"
              style={{ color: "#1f2a2e", marginBottom: 16 }}
            >
              Have an AI reviewer improve the whole translation
            </div>
            <div style={{ marginBottom: 14 }}>
              <label
                className="text-[11px] font-semibold tracking-[0.08em]"
                style={{ color: "#6b6558", display: "block", marginBottom: 6 }}
              >
                AI ENGINE
              </label>
              <select
                value={revisionModal.model}
                onChange={(e) =>
                  setRevisionModal((m) => ({ ...m, model: e.target.value }))
                }
                className="w-full text-[13px] px-3 py-2 rounded-lg outline-none"
                style={{
                  background: "#ffffff",
                  border: "1px solid #e7ddc5",
                  color: "#1f2a2e",
                }}
              >
                {translationModels.length === 0 ? (
                  <option value="">Default</option>
                ) : (
                  translationModels.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label} {m.provider ? `· ${m.provider}` : ""}
                    </option>
                  ))
                )}
              </select>
            </div>
            <div style={{ marginBottom: 16 }}>
              <label
                className="text-[11px] font-semibold tracking-[0.08em]"
                style={{ color: "#6b6558", display: "block", marginBottom: 6 }}
              >
                INSTRUCTIONS (OPTIONAL)
              </label>
              <textarea
                value={revisionModal.instructions}
                onChange={(e) =>
                  setRevisionModal((m) => ({
                    ...m,
                    instructions: e.target.value,
                  }))
                }
                rows={4}
                placeholder="e.g. 'use more formal language', 'prefer Municipality over City', 'British spelling'…"
                className="w-full text-[13px] px-3 py-2 rounded-lg outline-none resize-none"
                style={{
                  background: "#ffffff",
                  border: "1px solid #e7ddc5",
                  color: "#1f2a2e",
                  fontFamily: "inherit",
                }}
              />
            </div>
            <div
              className="text-[12px] rounded-lg px-3 py-2"
              style={{ background: "#f3ecdb", color: "#4a4638", marginBottom: 16 }}
            >
              {revisionCostText(project.free_revisions_left)}
            </div>
            <div
              style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}
            >
              <button
                type="button"
                onClick={() =>
                  setRevisionModal((m) => ({ ...m, open: false }))
                }
                className="text-[13px] font-semibold px-4 py-2 rounded-full transition"
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
                onClick={submitRevision}
                className="text-[13px] font-semibold px-4 py-2 rounded-full transition"
                style={{
                  background: "#0a7870",
                  color: "#ffffff",
                  border: "1px solid #0a7870",
                }}
              >
                Run revision
              </button>
            </div>
          </div>
        </div>
      )}

      {glossaryDraft.open && (
        <div
          onClick={() =>
            !glossaryDraft.busy &&
            setGlossaryDraft((g) => ({ ...g, open: false }))
          }
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
            className="rounded-2xl p-6 w-full max-w-lg"
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
              ADD TO GLOSSARY
            </div>
            <h3
              className="text-[18px] font-semibold tracking-tight mb-4"
              style={{ color: "#1f2a2e" }}
            >
              Pin this term across the project
            </h3>
            <div className="space-y-3">
              <div>
                <div
                  className="text-[11px] font-semibold tracking-[0.12em] mb-1.5"
                  style={{ color: "#9a9178" }}
                >
                  SOURCE TERM
                </div>
                <input
                  value={glossaryDraft.sourceTerm}
                  onChange={(e) =>
                    setGlossaryDraft((g) => ({
                      ...g,
                      sourceTerm: e.target.value,
                    }))
                  }
                  className="w-full text-sm outline-none px-3 py-2.5 rounded-xl"
                  style={{
                    background: "#faf5ee",
                    border: "1px solid #e7ddc5",
                    color: "#1f2a2e",
                  }}
                />
              </div>
              <div>
                <div
                  className="text-[11px] font-semibold tracking-[0.12em] mb-1.5"
                  style={{ color: "#9a9178" }}
                >
                  TARGET TERM
                </div>
                <input
                  value={glossaryDraft.targetTerm}
                  onChange={(e) =>
                    setGlossaryDraft((g) => ({
                      ...g,
                      targetTerm: e.target.value,
                    }))
                  }
                  className="w-full text-sm outline-none px-3 py-2.5 rounded-xl"
                  style={{
                    background: "#faf5ee",
                    border: "1px solid #e7ddc5",
                    color: "#1f2a2e",
                  }}
                />
              </div>
              <div>
                <div
                  className="text-[11px] font-semibold tracking-[0.12em] mb-1.5"
                  style={{ color: "#9a9178" }}
                >
                  NOTES (OPTIONAL)
                </div>
                <input
                  value={glossaryDraft.notes}
                  onChange={(e) =>
                    setGlossaryDraft((g) => ({
                      ...g,
                      notes: e.target.value,
                    }))
                  }
                  placeholder="When to use this term…"
                  className="w-full text-sm outline-none px-3 py-2.5 rounded-xl"
                  style={{
                    background: "#faf5ee",
                    border: "1px solid #e7ddc5",
                    color: "#1f2a2e",
                  }}
                />
              </div>
            </div>
            <p className="text-xs mt-3" style={{ color: "#8a8270" }}>
              The glossary is team-scoped. Once saved, every project on
              your team enforces this mapping during translation.
            </p>
            <div className="flex items-center justify-end gap-2 mt-5">
              <button
                type="button"
                onClick={() =>
                  setGlossaryDraft((g) => ({ ...g, open: false }))
                }
                disabled={glossaryDraft.busy}
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
                onClick={saveGlossaryDraft}
                disabled={
                  glossaryDraft.busy ||
                  !glossaryDraft.sourceTerm.trim() ||
                  !glossaryDraft.targetTerm.trim()
                }
                className="px-4 py-2 rounded-full text-sm font-semibold"
                style={{
                  background:
                    glossaryDraft.busy ||
                    !glossaryDraft.sourceTerm.trim() ||
                    !glossaryDraft.targetTerm.trim()
                      ? "#9bc9c5"
                      : "#0a7870",
                  color: "#fff",
                  cursor:
                    glossaryDraft.busy ||
                    !glossaryDraft.sourceTerm.trim() ||
                    !glossaryDraft.targetTerm.trim()
                      ? "not-allowed"
                      : "pointer",
                }}
              >
                {glossaryDraft.busy ? "Saving…" : "Add term"}
              </button>
            </div>
          </div>
        </div>
      )}

      {}
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

      {}
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

      {confirmState && (
        <ConfirmDialog
          state={confirmState}
          onClose={() => setConfirmState(null)}
        />
      )}
    </div>
  )
}

function ConfirmDialog({
  state,
  onClose,
}: {
  state: ConfirmState
  onClose: () => void
}) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(31,42,46,0.45)",
        backdropFilter: "blur(2px)",
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 480,
          maxWidth: "92vw",
          background: "#fbf6ea",
          borderRadius: 18,
          boxShadow: "0 18px 40px rgba(0,0,0,0.25)",
          padding: 24,
          border: "1px solid #e7ddc5",
        }}
      >
        <div
          className="text-[16px] font-semibold"
          style={{ color: "#1f2a2e", marginBottom: 12 }}
        >
          {state.title}
        </div>
        <div
          className="text-[13px] leading-relaxed"
          style={{ color: "#4a4638", marginBottom: 20, whiteSpace: "pre-line" }}
        >
          {state.body}
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button
            type="button"
            onClick={onClose}
            className="text-[13px] font-semibold px-4 py-2 rounded-full transition"
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
            onClick={() => {
              onClose()
              state.onConfirm()
            }}
            className="text-[13px] font-semibold px-4 py-2 rounded-full transition"
            style={{
              background: "#0a7870",
              color: "#ffffff",
              border: "1px solid #0a7870",
            }}
          >
            {state.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

function ComparePane({
  label,
  data,
  loading,
  emptyHint,
}: {
  label: string
  data: { url: string; kind: "pdf" | "image" | "other"; filename: string } | null
  loading: boolean
  emptyHint: string
}) {

  const PDF_VIEWER_HASH = "#toolbar=0&navpanes=0&view=FitH"
  const iframeSrc = data?.kind === "pdf" ? data.url + PDF_VIEWER_HASH : null

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
        {data?.kind === "other" && (
          <div className="px-4 py-8 text-sm text-center" style={{ color: "#8a8270" }}>
            This file type can&apos;t be previewed inline.{" "}
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
