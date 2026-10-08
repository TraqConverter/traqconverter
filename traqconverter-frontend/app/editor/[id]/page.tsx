"use client"

import { useEffect, useMemo, useState, useCallback, useRef } from "react"
import { useParams, useRouter } from "next/navigation"
import { api, apiErrorDetail, fetchObjectUrl } from "@/lib/api"
import LearningPanel from "@/components/learning/LearningPanel"
import { useFeature } from "@/lib/plan"
import { stageText } from "@/lib/jobProgress"
import { deletionNotice } from "@/lib/retention"
import { SavedInstructionPicker, useSavedInstructions } from "@/components/SavedInstructions"
import DocumentEditor, {
  STANDARD_PAGE,
  templateLabel,
  type CertChoice,
  type DocumentEditorHandle,
} from "@/components/editor/DocumentEditor"
import SourceViewer from "@/components/editor/SourceViewer"
import ExportMenu, { type ExportKind } from "@/components/editor/ExportMenu"
import ShareWithClient from "@/components/editor/ShareWithClient"
import { blocking, useReview, type CheckItem, type SourceRef } from "@/components/editor/useReview"

type Assignee = {
  id: string
  email: string
  full_name: string | null
}

const REGENERABLE_KINDS = ["PDF", "IMAGE"]

type ProjectInfo = {
  id: string
  status: string
  review_status: string
  progress_percent: number
  progress_stage?: string | null
  progress_detail?: string | null
  page_count?: number | null
  file_name: string
  source_language: string
  target_language: string
  mode?: "translate" | "dtp"
  source_kind?: string | null
  ai_instructions?: string | null
  deletes_on?: string | null

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
  failure_code?: "same_language" | null
  rebuild_status?: "running" | "done" | "failed" | null
  rebuild_error?: string | null
  revision_count?: number
  free_revisions_left?: number
  regenerations_left?: number
  next_regenerate_cost_credits?: number
}

type DocStatus = {
  version: number
  updated_at: string | null
  certification: boolean
  images: number
  pages: number
}

type ConfirmState = {
  title: string
  body: string
  confirmLabel: string
  onConfirm: () => void
}

function credits(n: number) {
  return `${n} credit${n === 1 ? "" : "s"}`
}

function revisionCostText(left: number | undefined, cost: number | undefined, used: number) {
  if (left === undefined || cost === undefined)
    return "The first regenerate of a document is free. Later ones cost one credit per page."
  if (left <= 0) return "You've used all the regenerations for this document. Use Ask AI for further changes."
  if (cost > 0) return `This regenerate costs ${credits(cost)} (one per page) · ${left} left`
  return `${used === 0 ? "First regenerate is free" : "This regenerate is free"} · ${left} left`
}

const MAX_INSTRUCTIONS = 1000

type Tab = "learning" | "status"

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

function languageName(raw?: string) {
  const s = (raw || "").trim()
  if (!s || s.toLowerCase() === "auto") return "Auto-detected"
  const code = langCode(s).split("-")[0]
  try {
    const name = new Intl.DisplayNames(["en"], { type: "language" }).of(code)
    if (name && s.length <= 5) return name
  } catch {}
  return s
}

function editedAgo(iso: string | null) {
  if (!iso) return ""
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return "just now"
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`
  return new Date(iso).toLocaleDateString()
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
  const [docStatus, setDocStatus] = useState<DocStatus | null>(null)
  const editorRef = useRef<DocumentEditorHandle>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null)
  const [regenerateOpen, setRegenerateOpen] = useState(false)
  const [tab, setTab] = useState<Tab>("learning")
  const [compareReloadKey, setCompareReloadKey] = useState(0)

  const [busy, setBusy] = useState<string | null>(null)
  const certLocked = useFeature("certifications") === "locked"
  const [showStatusMenu, setShowStatusMenu] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)

  const [chatOpen, setChatOpen] = useState(false)
  const [sourcePreview, setSourcePreview] = useState<{
    url: string
    kind: "pdf" | "image" | "other"
    filename: string
  } | null>(null)
  const [compareLoading, setCompareLoading] = useState(false)
  const sourceObjectUrlRef = useRef<string | null>(null)
  const [sourceUnavailable, setSourceUnavailable] = useState(false)
  const [docVersion, setDocVersion] = useState(0)
  const [activeBlockId, setActiveBlockId] = useState<string | null>(null)
  const [hoverBlockId, setHoverBlockId] = useState<string | null>(null)
  const [sourceFocus, setSourceFocus] = useState<(SourceRef & { key: number }) | null>(null)
  const [certifyGate, setCertifyGate] = useState<CheckItem[] | null>(null)
  const [templatePick, setTemplatePick] = useState<CertChoice | null>(null)
  const review = useReview(id, docVersion)

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
    null | "rerun"
  >(null)
  const [showRerunPicker, setShowRerunPicker] = useState(false)

  const markRebuildRunning = (started?: {
    revision_count?: number
    regenerations_left?: number
    next_regenerate_cost_credits?: number
  }) => {
    setProject((p) =>
      p
        ? {
            ...p,
            rebuild_status: "running",
            rebuild_error: null,
            revision_count: started?.revision_count ?? p.revision_count,
            free_revisions_left: started?.regenerations_left ?? p.free_revisions_left,
            regenerations_left: started?.regenerations_left ?? p.regenerations_left,
            next_regenerate_cost_credits: started?.next_regenerate_cost_credits ?? p.next_regenerate_cost_credits,
          }
        : p,
    )
  }

  const startRegenerate = () => setRegenerateOpen(true)

  const saveInstructions = async (text: string) => {
    const next = text.trim()
    if (next === (project?.ai_instructions || "")) return
    const res = await api.patch(`/projects/${id}`, { ai_instructions: next })
    const saved = (res.data?.ai_instructions as string | null) ?? null
    setProject((p) => (p ? { ...p, ai_instructions: saved } : p))
  }

  const saveInstructionsOnly = async (text: string) => {
    setRegenerateOpen(false)
    try {
      setError(null)
      await saveInstructions(text)
      setNotice("Instructions saved. Regenerate and Ask AI will follow them.")
    } catch (err: unknown) {
      setError(apiErrorDetail(err, "Couldn't save the instructions."))
    }
  }

  const runRegenerate = async (text: string) => {
    setRegenerateOpen(false)
    try {
      setCompareActionBusy("rerun")
      setError(null)
      await saveInstructions(text)
      const res = await api.post(`/projects/${id}/rebuild-with-claude`)
      markRebuildRunning(res.data)
      const charged = Number(res.data?.credits_charged) || 0
      setNotice(
        charged > 0
          ? `Regenerating for ${credits(charged)}. The document updates here when it finishes; a failed run is refunded.`
          : "Regenerating. The document updates here when it finishes.",
      )
    } catch (err: unknown) {
      setError(apiErrorDetail(err, "Couldn't start regenerating."))
    } finally {
      setCompareActionBusy(null)
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
                  progress_stage: null,
                  progress_detail: null,
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
      setRenameOpen(false)
      setError(apiErrorDetail(err, "Couldn't rename the project. Please try again."))
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
      setDeleteOpen(false)
      setError(apiErrorDetail(err, "Couldn't delete the project. Please try again."))
      setDeleteBusy(false)
    }
  }

  const fetchProject = useCallback(async () => {
    try {
      const projRes = await api.get(`/projects/${id}`)
      setProject(projRes.data)
    } catch (err: any) {
      console.error("EDITOR ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't load this project — it may have been deleted or you don't have access."
      )
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
    if (project && sourceUnavailable && !sourcePreview) {
      loadCompare()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, sourceUnavailable])

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

  const statusSeqRef = useRef(0)
  const refreshDocStatus = useCallback(async () => {
    const seq = ++statusSeqRef.current
    try {
      const res = await api.get<DocStatus>(`/projects/${id}/document/status`)
      if (seq === statusSeqRef.current) setDocStatus(res.data)
    } catch {
      // The strip keeps its last known values; the editor reports real failures.
    }
  }, [id])

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

  const certify = async (force = false) => {
    if (!project) return
    if (certLocked) {
      setError(null)
      setNotice("Certification is part of Pro. Upgrade in Billing to add the certification page and certify.")
      return
    }
    if (project.status !== "COMPLETED") {
      setError("The translation must finish before it can be certified.")
      return
    }
    if (!force && project.review_status !== "CERTIFIED") {
      setBusy("certify")
      const fresh = await review.fetchChecks()
      setBusy(null)
      // Certify adds a missing certification page itself, so that item doesn't hold it back.
      const open = (fresh?.items ?? []).filter((i) => blocking(i) && !(i.kind === "certification" && i.severity === "warning"))
      if (open.length) {
        setCertifyGate(open)
        return
      }
    }
    await deliver()
  }

  // templateId comes from the chooser; without it, a team with 2+ templates is asked first.
  const deliver = async (templateId?: string) => {
    if (!project) return
    try {
      setBusy("certify")
      setError(null)
      if (templateId === undefined) {
        const state = await editorRef.current?.certificationState()
        if (!state) return
        if (!state.present && state.templates.length >= 2) {
          setTemplatePick(state)
          return
        }
      }
      const ready = await editorRef.current?.ensureCertification(templateId)
      if (!ready) return
      if (project.review_status !== "CERTIFIED") {
        await api.post(`/projects/${id}/certify`)
        setProject((p) => (p ? { ...p, review_status: "CERTIFIED" } : p))
      }
      setNotice("Certified. The certification page is at the end of the document; Export it or share it with your client to deliver.")
    } catch (err: unknown) {
      if ((err as { response?: { status?: number } })?.response?.status === 403) {
        setError("Certification is a Pro feature. Upgrade in Billing to unlock.")
      } else {
        setError(apiErrorDetail(err, "Couldn't certify the project."))
      }
    } finally {
      setBusy(null)
    }
  }

  const exportFile = async (kind: ExportKind) => {
    try {
      setBusy(`export:${kind}`)
      const url = {
        docx: `/projects/${id}/export`,
        pdf: `/projects/${id}/export/pdf`,
        delivery: `/projects/${id}/export/delivery.pdf`,
      }[kind]
      const res = await api.get(url, { responseType: "blob" })
      const blob = new Blob([res.data])
      const dl = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = dl
      const stem = (project?.file_name || "translation").replace(/\.[^.]+$/, "")
      a.download = kind === "delivery" ? `${stem} - translation.pdf` : `${stem}.${kind}`
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
          detail || "Couldn't export this project."
        )
      } else {
        setError(detail || "Couldn't export this project.")
      }
    } finally {
      setBusy(null)
    }
  }

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
    const percent = Math.max(0, Math.min(99, project.progress_percent || 0))
    const kind = (project.source_kind || "").toUpperCase()
    const pages = project.page_count || 0
    const showHint = pages > 0 && kind !== "DOCX" && kind !== "TXT"
    return (
      <div className="py-20 px-4 text-center">
        <h2 className="text-xl font-semibold mb-2" style={{ color: "#1f2a2e" }}>
          Processing your document…
        </h2>
        <p style={{ color: "#4a4638" }}>
          {stageText(project)} · {percent}% complete
        </p>
        <div
          className="mx-auto mt-4 h-1.5 w-full max-w-xs rounded-full overflow-hidden"
          style={{ background: "#f1e8d1" }}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
        >
          <div
            className="h-full transition-all"
            style={{ width: `${percent}%`, background: percent > 0 ? "#0a7870" : "#cfc6ad" }}
          />
        </div>
        {showHint && (
          <p className="mt-3 text-sm" style={{ color: "#8a8270" }}>
            {pages} page{pages === 1 ? "" : "s"} · usually 1–2 minutes per page for scans.
          </p>
        )}
      </div>
    )
  }

  if (!project) return null

  const stStyle = statusStyle(project.review_status)
  // An editable copy is never certified.
  const isDtp = project.mode === "dtp"
  // The server only regenerates from page images; a Word source would always be refused.
  const canRegenerate = REGENERABLE_KINDS.includes((project.source_kind || "").toUpperCase())
  const reviewStatuses = isDtp ? REVIEW_STATUSES.filter((s) => s.value !== "CERTIFIED") : REVIEW_STATUSES

  return (
    <div className="max-w-[1400px] mx-auto pb-12" onClick={() => setShowStatusMenu(false)}>
      {}
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div className="flex items-start gap-3 sm:gap-6 min-w-0">
          <button
            onClick={() => router.push("/jobs")}
            className="text-sm mt-2 hover:underline shrink-0"
            style={{ color: "#0a7870" }}
          >
            ← Projects
          </button>
          <div className="min-w-0">
            <div className="text-sm" style={{ color: "#8a8270" }}>
              {isDtp ? (
                `${languageName(project.target_language)} · editable copy`
              ) : (
                <>
                  {project.source_language || "—"}{" "}
                  <span className="mx-1" style={{ color: "#cfc6ad" }}>
                    →
                  </span>{" "}
                  {project.target_language || "—"}
                </>
              )}
            </div>
            <div className="flex items-center gap-2">
              <h1
                className="text-[30px] font-semibold tracking-tight min-w-0 [overflow-wrap:anywhere]"
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
            {deletionNotice(project.deletes_on) && (
              <div className="text-xs mt-0.5" style={{ color: "#8a8270" }}>
                {deletionNotice(project.deletes_on)}
              </div>
            )}
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
                {reviewStatuses.map((s) => (
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

      {project.status === "FAILED" && project.failure_code === "same_language" && (
        <div
          className="text-sm rounded-lg px-3 py-2 mb-4 flex items-center justify-between gap-3 flex-wrap"
          style={{ background: "#f6e7c8", color: "#6b4a12" }}
        >
          <span>{project.failure_reason} Your credits were refunded.</span>
          <button
            type="button"
            onClick={() => router.push("/new-translation")}
            className="text-xs font-semibold px-3 py-1.5 rounded-full"
            style={{ background: "#0a7870", color: "#ffffff" }}
          >
            New project
          </button>
        </div>
      )}

      {project.status === "FAILED" && project.failure_code !== "same_language" && (
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
        {isDtp ? (
          <>
            <LangChip text={langCode(project.target_language)} />
            <span className="text-[12px]" style={{ color: "#6b6558" }}>
              {languageName(project.target_language)} · editable copy
            </span>
          </>
        ) : (
          <>
            <LangChip text={langCode(project.source_language)} />
            <span style={{ color: "#cfc6ad" }}>→</span>
            <LangChip text={langCode(project.target_language)} />
            <span className="text-[12px]" style={{ color: "#6b6558" }}>
              {languageName(project.source_language)} to {languageName(project.target_language)}
            </span>
          </>
        )}
        <div className="h-6 w-px mx-1" style={{ background: "#f1e8d1" }} />
        <Stat label={(docStatus?.pages ?? 0) === 1 ? "page" : "pages"} value={String(docStatus?.pages ?? "—")} />
        {docStatus && docStatus.version > 0 && (
          <Stat
            label={docStatus.updated_at ? `edited ${editedAgo(docStatus.updated_at)}` : "version"}
            value={`v${docStatus.version}`}
          />
        )}
        {!isDtp && (
          <span
            className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-2 py-0.5 rounded-full transition-colors"
            style={
              docStatus?.certification
                ? { background: "#d8ead6", color: "#2d5a24" }
                : { background: "#f3ecdb", color: "#6b6558" }
            }
            title={docStatus?.certification ? "The certification page is part of the document" : "Add it from Certification in the translation toolbar"}
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: docStatus?.certification ? "#4a8a3a" : "#b5ab93" }}
            />
            {docStatus?.certification ? "Certification page added" : "No certification page"}
          </span>
        )}
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

        <ExportMenu
          busy={busy?.startsWith("export:") ? (busy.slice(7) as ExportKind) : null}
          onExport={(kind) => void exportFile(kind)}
          onShare={() => setShareOpen(true)}
        />
        {!isDtp && (
          <button
            type="button"
            onClick={() => void certify()}
            disabled={busy === "certify"}
            title={certLocked ? "Certification is part of Pro" : "Adds the certification page if it's missing, then marks the project certified"}
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
            {certLocked && (
              <span
                className="text-[10px] font-semibold tracking-[0.06em] px-1.5 py-0.5 rounded-full uppercase"
                style={{ background: "rgba(255,255,255,0.22)" }}
              >
                Pro
              </span>
            )}
          </button>
        )}
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
                Type to edit. Drag pictures and stamps anywhere. Select text and press Ask AI for bigger changes.
              </div>
              <div
                className="flex items-center gap-2 relative"
                onClick={(e) => e.stopPropagation()}
              >
                {canRegenerate && (
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
                  title={`Redo the whole ${isDtp ? "editable copy" : "translation"} from the original, replacing your edits`}
                >
                  {rebuildRunning ? "Regenerating…" : "↻ Regenerate"}
                </button>
                )}
              </div>
            </div>

            <div
              className="grid max-md:grid-cols-1! max-md:h-auto! max-md:auto-rows-[80vh]"
              style={{
                gridTemplateColumns: chatOpen
                  ? "minmax(0, 0.75fr) minmax(0, 1.6fr)"
                  : "minmax(0, 1fr) minmax(0, 1fr)",
                gap: 12,
                height: "calc(100vh - 32px)",
                minHeight: 560,
              }}
            >
              {sourceUnavailable ? (
                <ComparePane
                  label="ORIGINAL"
                  data={sourcePreview}
                  loading={compareLoading}
                  emptyHint="The source file isn't available."
                />
              ) : (
                <SourceViewer
                  projectId={String(id)}
                  fileName={project.file_name}
                  map={review.map}
                  activeBlockId={activeBlockId}
                  focus={sourceFocus}
                  hoverBlockId={hoverBlockId}
                  onHoverBlock={setHoverBlockId}
                  onPickBlock={(blockId) => editorRef.current?.focusBlock(blockId)}
                  onUnavailable={() => setSourceUnavailable(true)}
                />
              )}
              <DocumentEditor
                ref={editorRef}
                projectId={String(id)}
                reloadKey={compareReloadKey}
                editableCopy={isDtp}
                onChatOpenChange={setChatOpen}
                onVersionChange={(v) => {
                  setDocVersion(v)
                  void refreshDocStatus()
                }}
                checks={review.checks}
                checking={review.checking}
                checksError={review.error}
                onRecheck={() => void review.fetchChecks(true)}
                onDismissCheck={(itemId, on) => void review.dismiss(itemId, on)}
                onActiveBlockChange={(blockId) => {
                  setActiveBlockId(blockId)
                  if (blockId) setSourceFocus(null)
                }}
                onIssuePick={(item) => {
                  if (item.source && (!item.block_id || !review.map?.blocks[item.block_id])) {
                    setActiveBlockId(null)
                    setSourceFocus({ ...item.source, key: Date.now() })
                  }
                }}
                hoverBlockId={hoverBlockId}
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
            label="Learning"
            active={tab === "learning"}
            onClick={() => setTab("learning")}
          />
          <SideTab
            label="Status"
            active={tab === "status"}
            onClick={() => setTab("status")}
          />
        </div>

        <div className="p-5">
            {tab === "learning" && <LearningPanel projectId={String(id)} />}

            {tab === "status" && (
              <>
                <div
                  className="text-[10px] font-semibold tracking-[0.14em] mb-3"
                  style={{ color: "#9a9178" }}
                >
                  PROJECT STATUS
                </div>
                <div className="space-y-3">
                  <StatusRow label={isDtp ? "Editable copy" : "Translation"} value={project.status} />
                  <StatusRow label="Review" value={stStyle.label} />
                  <StatusRow
                    label="Document version"
                    value={docStatus ? `v${docStatus.version}` : "—"}
                  />
                  {!isDtp && (
                    <StatusRow
                      label="Certification page"
                      value={docStatus?.certification ? "Added" : "Not added"}
                    />
                  )}
                  <StatusRow
                    label="Pictures and stamps"
                    value={String(docStatus?.images ?? 0)}
                  />
                </div>
              </>
            )}
          </div>
      </aside>

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

      {certifyGate && (
        <CertifyGate
          items={certifyGate}
          onReview={() => {
            setCertifyGate(null)
            editorRef.current?.openChecks()
          }}
          onCertify={() => {
            setCertifyGate(null)
            void certify(true)
          }}
          onClose={() => setCertifyGate(null)}
        />
      )}

      {templatePick && (
        <TemplatePicker
          choice={templatePick}
          onPick={(templateId) => {
            setTemplatePick(null)
            void deliver(templateId)
          }}
          onClose={() => setTemplatePick(null)}
        />
      )}

      {regenerateOpen && (
        <RegenerateDialog
          initial={project.ai_instructions || ""}
          editableCopy={isDtp}
          left={project.regenerations_left ?? project.free_revisions_left}
          cost={project.next_regenerate_cost_credits}
          used={project.revision_count ?? 0}
          onClose={() => setRegenerateOpen(false)}
          onSave={(text) => void saveInstructionsOnly(text)}
          onRegenerate={(text) => void runRegenerate(text)}
        />
      )}

      {shareOpen && <ShareWithClient projectId={id}onClose={() => setShareOpen(false)} />}

      {confirmState && (
        <ConfirmDialog
          state={confirmState}
          onClose={() => setConfirmState(null)}
        />
      )}
    </div>
  )
}

function CertifyGate({
  items,
  onReview,
  onCertify,
  onClose,
}: {
  items: CheckItem[]
  onReview: () => void
  onCertify: () => void
  onClose: () => void
}) {
  const errors = items.filter((i) => i.severity === "error").length
  const warnings = items.length - errors
  const summary = [errors ? `${errors} to fix` : "", warnings ? `${warnings} to check` : ""].filter(Boolean).join(", ")
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])
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
        padding: 16,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Issues before certifying"
        onClick={(e) => e.stopPropagation()}
        className="tq-gate"
        style={{
          width: 500,
          maxWidth: "92vw",
          background: "#fbf6ea",
          borderRadius: 18,
          boxShadow: "0 18px 40px rgba(0,0,0,0.25)",
          padding: 24,
          border: "1px solid #e7ddc5",
        }}
      >
        <div className="text-[11px] font-semibold tracking-[0.16em] mb-1" style={{ color: errors ? "#b14a3a" : "#a8741a" }}>
          BEFORE YOU SIGN
        </div>
        <div className="text-[16px] font-semibold mb-3" style={{ color: "#1f2a2e" }}>
          The translation has {summary}
        </div>
        <ul className="space-y-1.5 mb-5 max-h-56 overflow-auto">
          {items.slice(0, 6).map((i) => (
            <li key={i.id} className="flex items-start gap-2 text-[13px]" style={{ color: "#4a4638" }}>
              <span className="w-1.5 h-1.5 rounded-full mt-[7px] shrink-0" style={{ background: i.severity === "error" ? "#b14a3a" : "#c88a1a" }} />
              {i.message}
            </li>
          ))}
          {items.length > 6 && (
            <li className="text-[12px] pl-3.5" style={{ color: "#8a8270" }}>
              and {items.length - 6} more
            </li>
          )}
        </ul>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button
            type="button"
            onClick={onCertify}
            className="text-[13px] font-semibold px-4 py-2 rounded-full transition"
            style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
          >
            Certify anyway
          </button>
          <button
            type="button"
            autoFocus
            onClick={onReview}
            className="text-[13px] font-semibold px-4 py-2 rounded-full transition"
            style={{ background: "#0a7870", color: "#ffffff", border: "1px solid #0a7870" }}
          >
            Review issues
          </button>
        </div>
      </div>
      <style>{`.tq-gate { animation: tq-gate-in 160ms ease-out; } @keyframes tq-gate-in { from { opacity: 0; transform: translateY(4px) scale(0.98); } to { opacity: 1; transform: none; } }`}</style>
    </div>
  )
}

function TemplatePicker({
  choice,
  onPick,
  onClose,
}: {
  choice: CertChoice
  onPick: (templateId: string) => void
  onClose: () => void
}) {
  const options = [
    ...choice.templates.map((t) => ({ id: t.id, label: templateLabel(t), note: t.is_default ? "Team default" : "" })),
    { id: STANDARD_PAGE, label: "Standard page", note: "Built-in wording" },
  ]
  const [picked, setPicked] = useState(
    options.some((o) => o.id === choice.templateId) ? choice.templateId : STANDARD_PAGE,
  )
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])
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
        padding: 16,
      }}
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-label="Choose the certification page"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault()
          onPick(picked)
        }}
        className="tq-gate"
        style={{
          width: 440,
          maxWidth: "92vw",
          background: "#fbf6ea",
          borderRadius: 18,
          boxShadow: "0 18px 40px rgba(0,0,0,0.25)",
          padding: 24,
          border: "1px solid #e7ddc5",
        }}
      >
        <div className="text-[11px] font-semibold tracking-[0.16em] mb-1" style={{ color: "#0a7870" }}>
          CERTIFICATION PAGE
        </div>
        <div className="text-[16px] font-semibold mb-1" style={{ color: "#1f2a2e" }}>
          Which page goes at the end?
        </div>
        <p className="text-[12px] mb-3" style={{ color: "#6b6558" }}>
          You can switch it later from Certification in the toolbar.
        </p>
        <div role="radiogroup" aria-label="Template" className="space-y-1.5 mb-5 max-h-64 overflow-auto">
          {options.map((o) => {
            const on = o.id === picked
            return (
              <button
                key={o.id}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => setPicked(o.id)}
                onDoubleClick={() => onPick(o.id)}
                className="w-full flex items-center gap-3 text-left px-3 py-2.5 rounded-xl transition"
                style={{
                  background: on ? "#e3f1ee" : "#ffffff",
                  border: `1px solid ${on ? "#0a7870" : "#e7ddc5"}`,
                  color: "#1f2a2e",
                }}
              >
                <span
                  className="w-4 h-4 rounded-full shrink-0 flex items-center justify-center"
                  style={{ border: `1.5px solid ${on ? "#0a7870" : "#b5ab93"}` }}
                >
                  {on && <span className="w-2 h-2 rounded-full" style={{ background: "#0a7870" }} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-semibold truncate">{o.label}</span>
                  {o.note && (
                    <span className="block text-[11px]" style={{ color: "#8a8270" }}>
                      {o.note}
                    </span>
                  )}
                </span>
              </button>
            )
          })}
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={onClose}
            className="text-[13px] font-semibold px-4 py-2 rounded-full transition"
            style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
          >
            Cancel
          </button>
          <button
            type="submit"
            autoFocus
            className="text-[13px] font-semibold px-4 py-2 rounded-full transition"
            style={{ background: "#0a7870", color: "#ffffff", border: "1px solid #0a7870" }}
          >
            Add page &amp; certify
          </button>
        </div>
      </form>
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

function RegenerateDialog({
  initial,
  editableCopy,
  left,
  cost,
  used,
  onClose,
  onSave,
  onRegenerate,
}: {
  initial: string
  editableCopy: boolean
  left: number | undefined
  cost: number | undefined
  used: number
  onClose: () => void
  onSave: (text: string) => void
  onRegenerate: (text: string) => void
}) {
  const [text, setText] = useState(initial)
  const saved = useSavedInstructions()
  const changed = text.trim() !== initial.trim()
  const what = editableCopy ? "editable copy" : "translation"
  const outOfRegenerations = left !== undefined && left <= 0
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])
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
        padding: 16,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Regenerate the ${what}`}
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 500,
          maxWidth: "100%",
          maxHeight: "100%",
          overflowY: "auto",
          background: "#fbf6ea",
          borderRadius: 18,
          boxShadow: "0 18px 40px rgba(0,0,0,0.25)",
          padding: 24,
          border: "1px solid #e7ddc5",
        }}
      >
        <div className="text-[16px] font-semibold" style={{ color: "#1f2a2e", marginBottom: 12 }}>
          Regenerate the {what}
        </div>
        <div className="text-[13px] leading-relaxed" style={{ color: "#4a4638", marginBottom: 16 }}>
          The whole {what} is redone from the original, replacing your edits (you can undo it). It runs in the
          background and usually takes 1-3 minutes.
        </div>
        {!editableCopy && (
          <>
            <div className="flex items-baseline justify-between gap-3" style={{ marginBottom: 6 }}>
              <label
                htmlFor="regenerate-instructions"
                className="text-[11px] font-semibold tracking-[0.08em] uppercase"
                style={{ color: "#6b6558" }}
              >
                Instructions for the AI (optional)
              </label>
              <span
                className="text-[11px] tabular-nums shrink-0"
                style={{ color: text.length >= MAX_INSTRUCTIONS ? "#b14a3a" : "#8a8270" }}
              >
                {text.length}/{MAX_INSTRUCTIONS}
              </span>
            </div>
            {saved.enabled && saved.items.length > 0 && (
              <div style={{ marginBottom: 6 }}>
                <SavedInstructionPicker
                  id="regenerate-saved-instructions"
                  items={saved.items}
                  onPick={(picked) => setText(picked.slice(0, MAX_INSTRUCTIONS))}
                />
              </div>
            )}
            <textarea
              id="regenerate-instructions"
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={MAX_INSTRUCTIONS}
              rows={4}
              placeholder="e.g. Keep company names in Italian"
              className="w-full block text-[13px] px-3 py-2 rounded-lg outline-none resize-y"
              style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#1f2a2e", fontFamily: "inherit" }}
            />
            <div className="text-[12px]" style={{ color: "#8a8270", marginTop: 6, marginBottom: 16 }}>
              Saved with this document. Ask AI follows them too.
            </div>
          </>
        )}
        <div
          className="text-[12px] rounded-lg px-3 py-2"
          style={{ background: "#f3ecdb", color: "#4a4638", marginBottom: 16 }}
        >
          {revisionCostText(left, cost, used)}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {changed && (
            <button
              type="button"
              onClick={() => onSave(text)}
              className="text-[13px] font-semibold px-3 py-2 rounded-full transition mr-auto"
              style={{ color: "#0a7870" }}
            >
              Save without regenerating
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="text-[13px] font-semibold px-4 py-2 rounded-full transition"
            style={{ background: "#ffffff", color: "#1f2a2e", border: "1px solid #e7ddc5" }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onRegenerate(text)}
            disabled={outOfRegenerations}
            className="text-[13px] font-semibold px-4 py-2 rounded-full transition"
            style={{
              background: outOfRegenerations ? "#9bc9c5" : "#0a7870",
              color: "#ffffff",
              border: `1px solid ${outOfRegenerations ? "#9bc9c5" : "#0a7870"}`,
              cursor: outOfRegenerations ? "not-allowed" : "pointer",
            }}
          >
            {!outOfRegenerations && cost ? `Regenerate for ${credits(cost)}` : "Regenerate"}
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
