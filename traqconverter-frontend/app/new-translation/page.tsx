"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { api } from "@/lib/api"

type LangOption = {
  code: string
  flag: string
  name: string
}

const SOURCE_LANGUAGES: LangOption[] = [
  { code: "auto", flag: "AUTO", name: "Auto-detect" },

  { code: "en-GB", flag: "GB", name: "English (UK)" },
  { code: "en-US", flag: "US", name: "English (US)" },
  { code: "fr-FR", flag: "FR", name: "French" },
  { code: "es-ES", flag: "ES", name: "Spanish" },
  { code: "pt-PT", flag: "PT", name: "Portuguese" },
  { code: "pt-BR", flag: "BR", name: "Portuguese (Brazil)" },
  { code: "it-IT", flag: "IT", name: "Italian" },
  { code: "de-DE", flag: "DE", name: "German" },
  { code: "nl-NL", flag: "NL", name: "Dutch" },
  { code: "sv-SE", flag: "SE", name: "Swedish" },
  { code: "da-DK", flag: "DK", name: "Danish" },
  { code: "no-NO", flag: "NO", name: "Norwegian" },
  { code: "fi-FI", flag: "FI", name: "Finnish" },
  { code: "pl-PL", flag: "PL", name: "Polish" },
  { code: "cs-CZ", flag: "CZ", name: "Czech" },
  { code: "ro-RO", flag: "RO", name: "Romanian" },
  { code: "hu-HU", flag: "HU", name: "Hungarian" },
  { code: "tr-TR", flag: "TR", name: "Turkish" },
  { code: "vi-VN", flag: "VN", name: "Vietnamese" },
  { code: "id-ID", flag: "ID", name: "Indonesian" },

  { code: "ja-JP", flag: "JP", name: "Japanese" },
  { code: "zh-CN", flag: "CN", name: "Chinese (Simplified)" },
  { code: "zh-TW", flag: "TW", name: "Chinese (Traditional)" },
  { code: "ko-KR", flag: "KR", name: "Korean" },
  { code: "ru-RU", flag: "RU", name: "Russian" },
  { code: "uk-UA", flag: "UA", name: "Ukrainian" },
  { code: "el-GR", flag: "GR", name: "Greek" },
  { code: "ar-SA", flag: "SA", name: "Arabic" },
  { code: "he-IL", flag: "IL", name: "Hebrew" },
  { code: "hi-IN", flag: "IN", name: "Hindi" },
  { code: "th-TH", flag: "TH", name: "Thai" },
]

const TARGET_LANGUAGES: LangOption[] = SOURCE_LANGUAGES.filter(
  (l) => l.code !== "auto"
)

const LANGUAGES: LangOption[] = SOURCE_LANGUAGES

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

function defaultBatchName() {
  const d = new Date()
  return `Batch ${d.getDate()} ${MONTHS[d.getMonth()]}`
}

function fileKey(f: File) {
  return `${f.name}|${f.size}|${f.lastModified}`
}

async function countPages(f: File): Promise<number | null> {
  const name = f.name.toLowerCase()
  if (/\.(png|jpe?g)$/.test(name)) return 1
  if (!name.endsWith(".pdf")) return null
  try {
    const text = new TextDecoder("latin1").decode(await f.arrayBuffer())
    const n = (text.match(/\/Type\s*\/Page(?![a-z])/g) || []).length
    return n > 0 ? n : null
  } catch {
    return null
  }
}

type UploadState = {
  state: "uploading" | "done" | "failed" | "skipped"
  pct?: number
  error?: string
  pages?: number
}

function errorDetail(err: unknown): { status?: number; detail: string } {
  const e = err as { response?: { status?: number; data?: { detail?: unknown } } }
  const raw = e?.response?.data?.detail
  const detail = typeof raw === "string" ? raw : e?.response ? "Upload failed" : "Network error"
  return { status: e?.response?.status, detail }
}

function IconUpload() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#0a7870" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 4v12" />
      <path d="m7 9 5-5 5 5" />
      <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
    </svg>
  )
}

function IconFile() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v4h4" />
    </svg>
  )
}

function IconSwap() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0a7870" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 7h13" />
      <path d="m17 4 3 3-3 3" />
      <path d="M17 17H4" />
      <path d="m7 20-3-3 3-3" />
    </svg>
  )
}

function IconDB() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0a7870" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="6" rx="8" ry="3" />
      <path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
      <path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
    </svg>
  )
}

function IconBook() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0a7870" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22.5Z" />
      <path d="M4 4.5v18" />
    </svg>
  )
}

function IconShield() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0a7870" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3 4 6v6c0 5 3.4 8.4 8 9 4.6-.6 8-4 8-9V6Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  )
}

function IconChevron() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}

function IconArrowRight() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h14" />
      <path d="m13 5 7 7-7 7" />
    </svg>
  )
}

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <button
      onClick={() => onChange(!checked)}
      aria-pressed={checked}
      className="relative inline-flex items-center transition"
      style={{
        width: 44,
        height: 24,
        borderRadius: 999,
        background: checked ? "#0a7870" : "#e7ddc5",
      }}
    >
      <span
        className="absolute rounded-full transition"
        style={{
          width: 18,
          height: 18,
          background: "#fff",
          left: checked ? 23 : 3,
          top: 3,
          boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
        }}
      />
    </button>
  )
}

function LangSelect({
  value,
  onChange,
  label,
  options,
}: {
  value: string
  onChange: (v: string) => void
  label: string
  options?: LangOption[]
}) {
  const [open, setOpen] = useState(false)
  const list = options || LANGUAGES
  const current = list.find((l) => l.code === value) || list[0]
  return (
    <div>
      <div
        className="text-[11px] font-semibold tracking-[0.14em] mb-3"
        style={{ color: "#9a9178" }}
      >
        {label}
      </div>
      <div className="relative">
        <button
          onClick={() => setOpen((o) => !o)}
          className="w-full flex items-center justify-between px-4 py-3 rounded-xl transition"
          style={{
            background: "#ffffff",
            border: "1px solid #e7ddc5",
          }}
        >
          <div className="flex items-center gap-3">
            <span
              className="inline-flex items-center justify-center text-[11px] font-semibold rounded"
              style={{
                background: "#f3ecdb",
                color: "#6b6558",
                width: 28,
                height: 20,
                border: "1px solid #e7ddc5",
              }}
            >
              {current.flag}
            </span>
            <div className="text-left leading-tight">
              <div className="text-sm font-medium" style={{ color: "#1f2a2e" }}>
                {current.name}
              </div>
              <div className="text-xs font-mono" style={{ color: "#8a8270" }}>
                {current.code}
              </div>
            </div>
          </div>
          <IconChevron />
        </button>

        {open && (
          <div
            className="absolute z-10 mt-1 w-full max-h-64 overflow-y-auto rounded-xl"
            style={{
              background: "#fff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 10px 24px rgba(30,30,20,0.08)",
            }}
          >
            {list.map((l) => (
              <button
                key={l.code}
                onClick={() => {
                  onChange(l.code)
                  setOpen(false)
                }}
                className="w-full flex items-center gap-3 px-4 py-2.5 text-left transition"
                onMouseEnter={(e) => (e.currentTarget.style.background = "#faf5ee")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <span
                  className="inline-flex items-center justify-center text-[11px] font-semibold rounded"
                  style={{
                    background: "#f3ecdb",
                    color: "#6b6558",
                    width: 28,
                    height: 20,
                    border: "1px solid #e7ddc5",
                  }}
                >
                  {l.flag}
                </span>
                <div className="leading-tight">
                  <div className="text-sm" style={{ color: "#1f2a2e" }}>
                    {l.name}
                  </div>
                  <div className="text-xs font-mono" style={{ color: "#8a8270" }}>
                    {l.code}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function NewProjectPage() {
  const router = useRouter()
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const [files, setFiles] = useState<File[]>([])
  const file = files[0] ?? null
  const multi = files.length > 1
  const [pageCounts, setPageCounts] = useState<Record<string, number | null>>({})
  const [batchName, setBatchName] = useState("")
  const [batchId, setBatchId] = useState<string | null>(null)
  const [uploads, setUploads] = useState<Record<string, UploadState>>({})
  const [batchNotice, setBatchNotice] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [loading, setLoading] = useState(false)

  const [source, setSource] = useState("auto")
  const [target, setTarget] = useState("it-IT")

  const [useTM, setUseTM] = useState(false)
  const [applyGlossary, setApplyGlossary] = useState(false)
  const [requestCert, setRequestCert] = useState(false)

  const [showRunOptions, setShowRunOptions] = useState(true)
  const [runMode, setRunMode] = useState<"translate" | "dtp">("translate")

  const [rebuildEngine, setRebuildEngine] = useState<
    "claude-authored" | "segment-pipeline"
  >("claude-authored")
  const [aiModel, setAiModel] = useState<string>("")
  const [models, setModels] = useState<
    { id: string; label: string; provider: string }[]
  >([])
  const [orientation, setOrientation] = useState<"auto" | "portrait" | "landscape">("auto")
  const [certTemplateId, setCertTemplateId] = useState<string>("")
  const [certTemplates, setCertTemplates] = useState<
    { id: string; file_name: string }[]
  >([])
  const [instructions, setInstructions] = useState<string>("")
  const [showInstructionsEditor, setShowInstructionsEditor] = useState(false)

  useEffect(() => {
    api
      .get("/projects/translation-models")
      .then((res) => {
        const list = res.data?.models || []
        setModels(list)

        if (list.length) setAiModel(list[0].id)
      })
      .catch(() => setModels([]))
    api
      .get("/certifications")
      .then((res) => {
        const items =
          res.data?.items ||
          (Array.isArray(res.data) ? res.data : []) ||
          []

        setCertTemplates(
          items.map((c: any) => ({
            id: c.id,
            file_name: c.file_name,
          })),
        )
      })
      .catch(() => setCertTemplates([]))
  }, [])

  const handlePickFile = () => fileInputRef.current?.click()

  const addFiles = (list: FileList | File[] | null | undefined) => {
    const incoming = Array.from(list || [])
    if (!incoming.length || loading) return
    const known = new Set(files.map(fileKey))
    const next = [...files, ...incoming.filter((f) => !known.has(fileKey(f)))]
    setFiles(next)
    if (next.length > 1 && !batchName) setBatchName(defaultBatchName())
    for (const f of incoming) {
      countPages(f).then((n) => setPageCounts((m) => ({ ...m, [fileKey(f)]: n })))
    }
  }

  const removeFile = (f: File) => {
    if (loading || uploads[fileKey(f)]?.state === "done") return
    setFiles((list) => list.filter((x) => fileKey(x) !== fileKey(f)))
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    addFiles(e.dataTransfer.files)
  }

  const swap = () => {
    setSource(target)
    setTarget(source)
  }

  const buildForm = (file: File, batch?: string) => {
    const formData = new FormData()
    formData.append("file", file)
    formData.append("source_language", source)
    formData.append("target_language", target)
    formData.append("use_tm", String(useTM))
    formData.append("apply_glossary", String(applyGlossary))
    formData.append("request_certification", String(requestCert))

    if (runMode === "dtp") {
      formData.append("model", "dtp")
    } else if (rebuildEngine === "claude-authored") {
      formData.append("model", "claude-authored")
    } else if (aiModel) {
      formData.append("model", aiModel)
    }
    if (certTemplateId) {
      formData.append("certification_template_id", certTemplateId)
    }

    if (instructions.trim()) {
      formData.append("notes", instructions.trim())
    }
    if (batch) formData.append("batch_id", batch)
    return formData
  }

  const handleStartBatch = async () => {
    const name = batchName.trim()
    if (!name) {
      setBatchNotice("Name the batch (client or reference) before uploading.")
      return
    }
    setLoading(true)
    setBatchNotice(null)
    let id = batchId
    if (!id) {
      try {
        const res = await api.post("/batches", { name })
        id = res.data.id as string
        setBatchId(id)
      } catch (err) {
        setBatchNotice(`Couldn't create the batch: ${errorDetail(err).detail}`)
        setLoading(false)
        return
      }
    }

    const set = (k: string, u: UploadState) => setUploads((m) => ({ ...m, [k]: u }))
    const pending = files.filter((f) => uploads[fileKey(f)]?.state !== "done")
    let stopReason: string | null = null
    const failed: string[] = []
    const notUploaded: string[] = []
    for (const f of pending) {
      const k = fileKey(f)
      if (stopReason) {
        set(k, { state: "skipped", error: "Not uploaded" })
        notUploaded.push(f.name)
        continue
      }
      set(k, { state: "uploading", pct: 0 })
      try {
        const res = await api.post("/projects/upload", buildForm(f, id), {
          onUploadProgress: (e) => {
            if (e.total) set(k, { state: "uploading", pct: Math.round((e.loaded / e.total) * 100) })
          },
        })
        set(k, { state: "done", pct: 100, pages: res.data?.pages })
      } catch (err) {
        const { status, detail } = errorDetail(err)
        set(k, { state: "failed", error: detail })
        failed.push(f.name)
        // Running out of credits or access applies to every remaining file.
        if (/credit/i.test(detail) || status === 401 || status === 402 || status === 403 || !status) {
          stopReason = detail
        }
      }
    }
    setLoading(false)
    window.dispatchEvent(new Event("sidebar:refresh"))
    if (!failed.length && !notUploaded.length) {
      router.push(`/batches/${id}`)
      return
    }
    const parts = [`${failed.length} failed: ${failed.join(", ")}.`]
    if (notUploaded.length) parts.push(`Stopped (${stopReason}). Not uploaded: ${notUploaded.join(", ")}.`)
    setBatchNotice(parts.join(" "))
  }

  const handleStart = async () => {
    if (!file) return alert("Please select a file first")
    if (multi) return handleStartBatch()

    try {
      setLoading(true)

      const res = await api.post("/projects/upload", buildForm(file))
      const projectId = res.data.project_id

      if (!projectId) throw new Error("Invalid response from server")
      router.push(`/editor/${projectId}`)
    } catch (err: any) {
      console.error(err)
      const message = err?.response?.data?.detail || "Upload failed"
      alert(message)
    } finally {
      setLoading(false)
    }
  }

  const trySample = () => {
    const blob = new Blob(["Sample document for TraqConverter"], {
      type: "text/plain",
    })
    const sample = new File([blob], "Sample-Patient-Consent.pdf", {
      type: "application/pdf",
    })
    setFiles([sample])
  }

  return (
    <div className="max-w-[1200px] mx-auto">
      {}
      <div className="mb-3">
        <div className="text-sm" style={{ color: "#8a8270" }}>
          <span>Espresso</span>
          <span className="mx-2">›</span>
          <span>Projects</span>
          <span className="mx-2">›</span>
          <span>New</span>
        </div>
      </div>

      {}
      <h1
        className="text-[34px] font-semibold tracking-tight mb-1"
        style={{ color: "#1f2a2e" }}
      >
        New project
      </h1>

      {}
      <button
        onClick={() => router.push("/dashboard")}
        className="text-sm mb-5 hover:underline"
        style={{ color: "#0a7870" }}
      >
        ← Back to dashboard
      </button>

      <p className="text-[15px] mb-8" style={{ color: "#4a4638" }}>
        Upload a document and we&apos;ll run OCR, detect the source language, and
        prepare a first-pass draft in your target language — usually in under a
        minute.
      </p>

      <div className="grid grid-cols-3 gap-6">
        {}
        <div className="col-span-2">
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={handlePickFile}
            className="rounded-2xl p-10 cursor-pointer transition"
            style={{
              background: "#ffffff",
              border: `2px dashed ${dragOver ? "#0a7870" : "#e7ddc5"}`,
              minHeight: 480,
            }}
          >
            <div className="flex flex-col items-center justify-center h-full text-center py-10">
              <div
                className="rounded-2xl mb-6 flex items-center justify-center"
                style={{
                  background: "#ffffff",
                  width: 96,
                  height: 96,
                  border: "1px solid #e7ddc5",
                  boxShadow: "0 1px 2px rgba(30,30,20,0.04)",
                }}
              >
                <IconUpload />
              </div>

              <div
                className="text-[22px] font-semibold mb-2"
                style={{ color: "#1f2a2e" }}
              >
                {multi ? `${files.length} documents` : file ? file.name : "Drop your document here"}
              </div>
              <div className="text-sm mb-8" style={{ color: "#8a8270" }}>
                {file
                  ? "Drop or browse to add more documents from the same client"
                  : "or click to browse · PDF, DOCX, PPTX · up to 200 MB · several files make a batch"}
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    handlePickFile()
                  }}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-medium text-white transition"
                  style={{ background: "#0a7870" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "#0a645d")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "#0a7870")}
                >
                  <IconUploadWhite />
                  Browse files
                </button>
              </div>

              <div className="flex items-center gap-5 mt-8 text-xs" style={{ color: "#8a8270" }}>
                <span>✓ PDF, DOCX, JPG, PNG</span>
              </div>
            </div>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              accept=".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg"
              onChange={(e) => {
                addFiles(e.target.files)
                e.target.value = ""
              }}
            />
          </div>

          {multi && (
            <BatchList
              files={files}
              pageCounts={pageCounts}
              uploads={uploads}
              batchName={batchName}
              onBatchName={setBatchName}
              nameLocked={!!batchId}
              onRemove={removeFile}
              busy={loading}
              notice={batchNotice}
              batchId={batchId}
            />
          )}
        </div>

        {}
        <div className="space-y-6">
          {}
          <div
            className="rounded-2xl p-6"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 1px 2px rgba(30,30,20,0.03)",
            }}
          >
            <LangSelect
              value={source}
              onChange={setSource}
              label="SOURCE LANGUAGE"
              options={SOURCE_LANGUAGES}
            />

            <div className="flex justify-center my-3">
              <button
                onClick={swap}
                disabled={source === "auto"}
                className="w-9 h-9 rounded-full flex items-center justify-center transition"
                style={{
                  background: source === "auto" ? "#f3ecdb" : "#e1efec",
                  border: "1px solid #cfe6e2",
                  cursor: source === "auto" ? "not-allowed" : "pointer",
                  opacity: source === "auto" ? 0.5 : 1,
                }}
                aria-label="Swap languages"
                title={source === "auto" ? "Cannot swap when source is auto-detect" : "Swap languages"}
              >
                <IconSwap />
              </button>
            </div>

            <LangSelect
              value={target}
              onChange={setTarget}
              label="TARGET LANGUAGE"
              options={TARGET_LANGUAGES}
            />
          </div>

          {}
          <div
            className="rounded-2xl p-6"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 1px 2px rgba(30,30,20,0.03)",
            }}
          >
            <div
              className="text-[11px] font-semibold tracking-[0.14em] mb-4"
              style={{ color: "#9a9178" }}
            >
              RUN MODE
            </div>
            <div className="grid grid-cols-2 gap-3">
              {(
                [
                  {
                    value: "translate" as const,
                    title: "Translate",
                    sub: "Standard translation workflow into a different language.",
                  },
                  {
                    value: "dtp" as const,
                    title: "DTP",
                    sub: "Editable source output with automatic DOCX rebuild — no AI translation.",
                  },
                ]
              ).map((opt) => {
                const active = runMode === opt.value
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setRunMode(opt.value)}
                    className="rounded-xl p-4 text-left transition"
                    style={{
                      background: active ? "#f6f1e4" : "#ffffff",
                      border: `1px solid ${active ? "#0a7870" : "#e7ddc5"}`,
                      cursor: "pointer",
                    }}
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <div
                        className="w-4 h-4 rounded-full flex items-center justify-center"
                        style={{
                          background: active ? "#0a7870" : "transparent",
                          border: `2px solid ${active ? "#0a7870" : "#cfc6ad"}`,
                        }}
                      >
                        {active && (
                          <div
                            className="w-1.5 h-1.5 rounded-full"
                            style={{ background: "#fff" }}
                          />
                        )}
                      </div>
                      <span
                        className="font-semibold text-[14px]"
                        style={{ color: "#1f2a2e" }}
                      >
                        {opt.title}
                      </span>
                    </div>
                    <div
                      className="text-[12px] leading-snug"
                      style={{ color: "#8a8270" }}
                    >
                      {opt.sub}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {}
          <div
            className="rounded-2xl"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 1px 2px rgba(30,30,20,0.03)",
            }}
          >
            <button
              type="button"
              onClick={() => setShowRunOptions((v) => !v)}
              className="w-full flex items-center justify-between px-6 py-4 text-left"
              style={{
                borderBottom: showRunOptions
                  ? "1px solid #f1e8d1"
                  : "none",
              }}
            >
              <div
                className="text-[14px] font-semibold"
                style={{ color: "#1f2a2e" }}
              >
                Run Options
              </div>
              <div
                className="text-[11px] font-semibold tracking-[0.14em] px-2.5 py-1 rounded-full"
                style={{
                  background: "#cfe6e2",
                  color: "#0a7870",
                  border: "1px solid #b7dad4",
                }}
              >
                {showRunOptions ? "HIDE" : "SHOW"}
              </div>
            </button>

            {showRunOptions && (
              <div className="px-6 py-2">
                {}
                <RunOptionRow label="Rebuild engine">
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)",
                      gap: 6,
                      width: "100%",
                      minWidth: 0,
                    }}
                  >
                    {(
                      [
                        {
                          id: "claude-authored",
                          title: "Layout rebuild",
                          desc: "Best quality",
                        },
                        {
                          id: "segment-pipeline",
                          title: "Segment pipeline",
                          desc: "Fast",
                        },
                      ] as const
                    ).map((opt) => {
                      const active = rebuildEngine === opt.id
                      const disabled = runMode === "dtp"
                      return (
                        <button
                          key={opt.id}
                          type="button"
                          onClick={() => !disabled && setRebuildEngine(opt.id)}
                          disabled={disabled}
                          className="text-left px-3 py-2 rounded-xl transition"
                          style={{
                            background: disabled
                              ? "#f6efe0"
                              : active
                              ? "#ffffff"
                              : "#faf5ee",
                            border: active
                              ? "2px solid #0a7870"
                              : "1px solid #e7ddc5",
                            color: disabled ? "#9a9178" : "#1f2a2e",
                            cursor: disabled ? "not-allowed" : "pointer",
                          }}
                        >
                          <div
                            className="flex items-center gap-1.5 text-[11px] font-semibold"
                            style={{ minWidth: 0 }}
                          >
                            <span
                              style={{
                                width: 12,
                                height: 12,
                                borderRadius: 999,
                                border: active
                                  ? "3.5px solid #0a7870"
                                  : "1px solid #cdb98a",
                                background: "#ffffff",
                                display: "inline-block",
                                flexShrink: 0,
                              }}
                            />
                            {opt.title}
                          </div>
                          <div
                            className="text-[10px] mt-0.5"
                            style={{ color: "#8a8270", marginLeft: 18 }}
                          >
                            {opt.desc}
                          </div>
                        </button>
                      )
                    })}
                  </div>
                </RunOptionRow>

                {}
                {rebuildEngine === "segment-pipeline" && (
                  <RunOptionRow
                    label="AI Model"
                    helper="The translator engine used per segment. Only applies when Rebuild engine is set to Segment pipeline."
                  >
                    <select
                      value={aiModel}
                      onChange={(e) => setAiModel(e.target.value)}
                      disabled={runMode === "dtp"}
                      className="text-sm outline-none rounded-lg px-3 py-2 w-full max-w-[260px]"
                      style={{
                        background:
                          runMode === "dtp" ? "#f6efe0" : "#faf5ee",
                        border: "1px solid #e7ddc5",
                        color: runMode === "dtp" ? "#9a9178" : "#1f2a2e",
                        cursor:
                          runMode === "dtp" ? "not-allowed" : "pointer",
                      }}
                    >
                      {models.length === 0 && (
                        <option value="">Default (balanced)</option>
                      )}
                      {models.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.label}
                        </option>
                      ))}
                    </select>
                  </RunOptionRow>
                )}

                {}
                <RunOptionRow
                  label="Page Orientation"
                  helper="Match source orientation automatically, or force one. The rebuild adopts this per page."
                >
                  <div
                    className="inline-flex p-1 rounded-full"
                    style={{
                      background: "#f3ecdb",
                      border: "1px solid #e7ddc5",
                    }}
                  >
                    {(["auto", "portrait", "landscape"] as const).map(
                      (val) => {
                        const active = orientation === val
                        return (
                          <button
                            key={val}
                            type="button"
                            onClick={() => setOrientation(val)}
                            className="text-[12px] font-semibold tracking-[0.04em] px-3 py-1 rounded-full transition capitalize"
                            style={{
                              background: active ? "#ffffff" : "transparent",
                              color: active ? "#0a7870" : "#6b6558",
                              boxShadow: active
                                ? "0 1px 2px rgba(30,30,20,0.06)"
                                : "none",
                            }}
                          >
                            {val}
                          </button>
                        )
                      },
                    )}
                  </div>
                </RunOptionRow>

                {}
                <RunOptionRow
                  label="Certification template"
                  helper="DOCX template with {{tokens}} from your Certifications library. Auto-filled at export."
                >
                  <select
                    value={certTemplateId}
                    onChange={(e) => setCertTemplateId(e.target.value)}
                    className="text-sm outline-none rounded-lg px-3 py-2 w-full max-w-[260px]"
                    style={{
                      background: "#faf5ee",
                      border: "1px solid #e7ddc5",
                      color: "#1f2a2e",
                    }}
                  >
                    <option value="">None — use the default cert</option>
                    {certTemplates.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.file_name}
                      </option>
                    ))}
                  </select>
                </RunOptionRow>

                {}
                <RunOptionRow
                  label="Instructions"
                  helper="Free-text guidance handed to the AI (e.g. 'formal register', 'prefer Municipality over City')."
                  last
                >
                  <button
                    type="button"
                    onClick={() =>
                      setShowInstructionsEditor((v) => !v)
                    }
                    className="text-[12px] font-semibold tracking-[0.04em] px-3 py-1.5 rounded-full transition"
                    style={{
                      background: instructions
                        ? "#cfe6e2"
                        : "#ffffff",
                      color: instructions ? "#0a5e58" : "#0a7870",
                      border: `1px solid ${
                        instructions ? "#b7dad4" : "#cfe6e2"
                      }`,
                    }}
                  >
                    {instructions ? "Edit instructions" : "+ Add instructions"}
                  </button>
                </RunOptionRow>

                {showInstructionsEditor && (
                  <div className="pb-5">
                    <textarea
                      value={instructions}
                      onChange={(e) => setInstructions(e.target.value)}
                      rows={4}
                      placeholder="E.g. Use formal register. Translate 'Comune' as 'Municipality'. Preserve all dates exactly."
                      className="w-full text-sm outline-none rounded-xl px-3 py-2.5 resize-none"
                      style={{
                        background: "#faf5ee",
                        border: "1px solid #e7ddc5",
                        color: "#1f2a2e",
                      }}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
          {}
          <div
            className="rounded-2xl p-6"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 1px 2px rgba(30,30,20,0.03)",
            }}
          >
            <div
              className="text-[11px] font-semibold tracking-[0.14em] mb-4"
              style={{ color: "#9a9178" }}
            >
              OPTIONS
            </div>

            <OptionRow
              icon={<IconDB />}
              title="Use Translation Memory"
              subtitle="Reuse approved segments from your past projects"
              checked={useTM}
              onChange={setUseTM}
            />

            <OptionRow
              icon={<IconBook />}
              title="Apply Glossary"
              subtitle="Enforce your team's approved terminology"
              checked={applyGlossary}
              onChange={setApplyGlossary}
            />

            <OptionRow
              icon={<IconShield />}
              title="Request certification"
              subtitle="Add a translator's certification statement page"
              checked={requestCert}
              onChange={setRequestCert}
              last
            />
          </div>

          {}
          <div>
            <button
              onClick={handleStart}
              disabled={!file || loading}
              className="w-full flex items-center justify-center gap-2 py-4 rounded-full text-[15px] font-semibold transition"
              style={{
                background: !file || loading ? "#9bc9c5" : "#0a7870",
                color: "#ffffff",
                cursor: !file || loading ? "not-allowed" : "pointer",
              }}
              onMouseEnter={(e) => {
                if (file && !loading) e.currentTarget.style.background = "#0a645d"
              }}
              onMouseLeave={(e) => {
                if (file && !loading) e.currentTarget.style.background = "#0a7870"
              }}
            >
              {loading
                ? "Uploading..."
                : multi
                ? batchId
                  ? "Upload remaining documents"
                  : `Translate ${files.length} documents`
                : "Start OCR & translation"}
              {!loading && <IconArrowRight />}
            </button>
            <div className="text-xs text-center mt-3" style={{ color: "#8a8270" }}>
              {multi
                ? "1 credit per page · same languages and options for every document"
                : "1 credit per page · review every segment before export"}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function IconUploadWhite() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 4v12" />
      <path d="m7 9 5-5 5 5" />
      <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
    </svg>
  )
}

function RunOptionRow({
  label,
  helper,
  children,
  last,
}: {
  label: string
  helper?: string
  children: React.ReactNode
  last?: boolean
}) {
  return (
    <div
      className="grid items-start gap-4 py-4"
      style={{

        gridTemplateColumns: "160px 1fr",
        borderBottom: last ? "none" : "1px solid #f4ecd6",
      }}
    >
      <div className="min-w-0">
        <div
          className="text-[13px] font-semibold leading-snug"
          style={{ color: "#1f2a2e" }}
        >
          {label}
        </div>
        {helper && (
          <div
            className="text-[11px] mt-1 leading-snug"
            style={{ color: "#8a8270" }}
          >
            {helper}
          </div>
        )}
      </div>
      <div className="flex items-center justify-end min-w-0">
        {children}
      </div>
    </div>
  )
}

function OptionRow({
  icon,
  title,
  subtitle,
  checked,
  onChange,
  last,
}: {
  icon: React.ReactNode
  title: string
  subtitle: string
  checked: boolean
  onChange: (v: boolean) => void
  last?: boolean
}) {
  return (
    <div
      className="flex items-center gap-3 py-3"
      style={{ borderBottom: last ? "none" : "1px solid #f1e8d1" }}
    >
      <div
        className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
        style={{ background: "#e1efec" }}
      >
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold" style={{ color: "#1f2a2e" }}>
          {title}
        </div>
        <div className="text-xs truncate" style={{ color: "#8a8270" }}>
          {subtitle}
        </div>
      </div>
      <Toggle checked={checked} onChange={onChange} />
    </div>
  )
}

function BatchList({
  files,
  pageCounts,
  uploads,
  batchName,
  onBatchName,
  nameLocked,
  onRemove,
  busy,
  notice,
  batchId,
}: {
  files: File[]
  pageCounts: Record<string, number | null>
  uploads: Record<string, UploadState>
  batchName: string
  onBatchName: (v: string) => void
  nameLocked: boolean
  onRemove: (f: File) => void
  busy: boolean
  notice: string | null
  batchId: string | null
}) {
  const pagesOf = (f: File) => uploads[fileKey(f)]?.pages ?? pageCounts[fileKey(f)] ?? null
  const known = files.map(pagesOf)
  const total = known.reduce<number>((sum, n) => sum + (n ?? 0), 0)
  const unknown = known.filter((n) => n == null).length

  return (
    <div
      className="rounded-2xl p-6 mt-6"
      style={{ background: "#ffffff", border: "1px solid #e7ddc5", boxShadow: "0 1px 2px rgba(30,30,20,0.03)" }}
    >
      <label className="block text-[11px] font-semibold tracking-[0.14em] mb-2" style={{ color: "#9a9178" }}>
        CLIENT OR BATCH NAME
      </label>
      <input
        value={batchName}
        onChange={(e) => onBatchName(e.target.value)}
        disabled={nameLocked || busy}
        maxLength={120}
        placeholder="e.g. Rossi family, order 2291"
        className="w-full text-sm outline-none rounded-xl px-3 py-2.5 mb-1"
        style={{ background: nameLocked ? "#f6efe0" : "#faf5ee", border: "1px solid #e7ddc5", color: "#1f2a2e" }}
      />
      <div className="text-xs mb-5" style={{ color: "#8a8270" }}>
        Names, institutions and terms are kept the same across every document in the batch.
      </div>

      <div className="flex items-baseline justify-between mb-2">
        <div className="text-[11px] font-semibold tracking-[0.14em]" style={{ color: "#9a9178" }}>
          DOCUMENTS
        </div>
        <div className="text-xs" style={{ color: "#6b6558" }}>
          {files.length} files · {total} page{total === 1 ? "" : "s"}
          {unknown ? ` + ${unknown} counted after upload` : ""}
        </div>
      </div>

      <div>
        {files.map((f, i) => {
          const k = fileKey(f)
          const u = uploads[k]
          const pages = pagesOf(f)
          const color =
            u?.state === "done" ? "#2d5a24" : u?.state === "failed" ? "#b91c1c" : u?.state === "skipped" ? "#7a5a10" : "#8a8270"
          const label =
            u?.state === "done"
              ? "Uploaded"
              : u?.state === "uploading"
              ? `Uploading ${u.pct ?? 0}%`
              : u?.state === "failed"
              ? u.error || "Failed"
              : u?.state === "skipped"
              ? "Not uploaded"
              : "Ready"
          return (
            <div
              key={k}
              className="flex items-center gap-3 py-2.5"
              style={{ borderTop: i ? "1px solid #f1e8d1" : "none" }}
            >
              <span style={{ color: "#6b6558" }}>
                <IconFile />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-sm truncate" style={{ color: "#1f2a2e" }}>
                  {f.name}
                </div>
                {u?.state === "uploading" && (
                  <div className="h-1 rounded-full mt-1.5" style={{ background: "#f3ecdb" }}>
                    <div className="h-1 rounded-full" style={{ width: `${u.pct ?? 0}%`, background: "#0a7870" }} />
                  </div>
                )}
              </div>
              <div className="text-xs w-16 text-right shrink-0" style={{ color: "#6b6558" }}>
                {pages == null ? "—" : `${pages} p.`}
              </div>
              <div className="text-xs w-40 text-right truncate shrink-0" style={{ color }} title={label}>
                {label}
              </div>
              <button
                type="button"
                onClick={() => onRemove(f)}
                disabled={busy || u?.state === "done"}
                aria-label={`Remove ${f.name}`}
                className="w-6 h-6 rounded-full text-sm shrink-0"
                style={{
                  color: "#9a9178",
                  visibility: busy || u?.state === "done" ? "hidden" : "visible",
                }}
              >
                ×
              </button>
            </div>
          )
        })}
      </div>

      {notice && (
        <div
          className="mt-4 rounded-xl px-4 py-3 text-sm"
          style={{ background: "#fbeeee", border: "1px solid #f0cccc", color: "#7a1f1f" }}
        >
          {notice}
          {batchId && (
            <>
              {" "}
              <Link href={`/batches/${batchId}`} className="font-semibold underline" style={{ color: "#0a7870" }}>
                Open batch
              </Link>
            </>
          )}
        </div>
      )}
    </div>
  )
}
