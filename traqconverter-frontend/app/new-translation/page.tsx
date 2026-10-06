"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { snapshotFile, UNREADABLE_FILE } from "@/lib/fileSnapshot"
import { api } from "@/lib/api"
import { useFeature } from "@/lib/plan"
import { LangSelect, SOURCE_LANGUAGES, TARGET_LANGUAGES } from "@/components/LangSelect"
import { SaveForLater, SavedInstructionPicker, useSavedInstructions } from "@/components/SavedInstructions"

const MAX_INSTRUCTIONS = 1000
const LAST_TARGET_KEY = "tq.lastTargetLanguage"

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
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [loading, setLoading] = useState(false)

  const [mode, setMode] = useState<"translate" | "dtp">("translate")
  const dtp = mode === "dtp"
  const [source, setSource] = useState("auto")
  const [target, setTargetState] = useState("en-GB")
  // Most translators work into the same language every day, so the last target is remembered.
  useEffect(() => {
    try {
      const last = localStorage.getItem(LAST_TARGET_KEY)
      if (last && TARGET_LANGUAGES.some((l) => l.code === last)) setTargetState(last)
    } catch {}
  }, [])
  const setTarget = (code: string) => {
    setTargetState(code)
    try {
      localStorage.setItem(LAST_TARGET_KEY, code)
    } catch {}
  }
  const sameLanguage = !dtp && source !== "auto" && source.split("-")[0] === target.split("-")[0]
  const [instructions, setInstructions] = useState("")
  const saved = useSavedInstructions()

  // null until known; stays null on plans without certifications.
  const [certsEnabled, setCertsEnabled] = useState<boolean | null>(null)
  const [certTemplateId, setCertTemplateId] = useState<string>("")
  const [certTemplates, setCertTemplates] = useState<
    { id: string; file_name: string }[]
  >([])

  const certAccess = useFeature("certifications")
  const memoryAccess = useFeature("terminology_memory")

  useEffect(() => {
    if (certAccess !== "allowed") return
    api
      .get("/certifications")
      .then((res) => {
        const items: { id: string; file_name: string; is_template?: boolean; is_default?: boolean }[] =
          res.data?.items || []
        const templates = items.filter((c) => c.is_template ?? c.file_name.toLowerCase().endsWith(".docx"))
        setCertsEnabled(true)
        setCertTemplates(templates.map((c) => ({ id: c.id, file_name: c.file_name })))
        const preferred = templates.find((c) => c.is_default)
        if (preferred) setCertTemplateId(preferred.id)
      })
      .catch(() => {
        setCertsEnabled(false)
        setCertTemplates([])
      })
  }, [certAccess])

  const handlePickFile = () => fileInputRef.current?.click()

  const addFiles = async (list: FileList | File[] | null | undefined) => {
    const picked = Array.from(list || [])
    if (!picked.length || loading) return
    let incoming: File[]
    try {
      incoming = await Promise.all(picked.map(snapshotFile))
    } catch {
      setUploadError(UNREADABLE_FILE)
      return
    }
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
    formData.append("mode", mode)
    formData.append("source_language", source)
    formData.append("target_language", dtp ? source : target)
    formData.append("model", "claude-authored")
    formData.append("use_tm", String(!dtp))
    formData.append("apply_glossary", String(!dtp))
    formData.append("request_certification", String(!dtp && !!certsEnabled))
    if (!dtp && certsEnabled && certTemplateId) {
      formData.append("certification_template_id", certTemplateId)
    }
    if (batch) formData.append("batch_id", batch)
    if (!dtp && instructions.trim()) formData.append("ai_instructions", instructions.trim())
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
      router.push(`/jobs?batch=${id}`)
      return
    }
    const parts = [`${failed.length} failed: ${failed.join(", ")}.`]
    if (notUploaded.length) parts.push(`Stopped (${stopReason}). Not uploaded: ${notUploaded.join(", ")}.`)
    setBatchNotice(parts.join(" "))
  }

  const handleStart = async () => {
    if (!file) return
    if (multi) return handleStartBatch()

    try {
      setLoading(true)
      setUploadError(null)

      const res = await api.post("/projects/upload", buildForm(file))
      const projectId = res.data.project_id

      if (!projectId) throw new Error("Invalid response from server")
      router.push(`/editor/${projectId}`)
    } catch (err: any) {
      console.error(err)
      const detail = err?.response?.data?.detail
      setUploadError(typeof detail === "string" && detail ? detail : "Upload failed. Try again in a minute.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-[1200px] mx-auto">
      {}
      <div className="mb-3">
        <div className="text-sm" style={{ color: "#8a8270" }}>
          <span>OnlineDocTranslator</span>
          <span className="mx-2">›</span>
          <span>Projects</span>
          <span className="mx-2">›</span>
          <span>New</span>
        </div>
      </div>

      {}
      <h1
        className="text-[28px] sm:text-[34px] font-semibold tracking-tight mb-1"
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

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_360px] gap-6">
        {}
        <div className="min-w-0">
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={handlePickFile}
            className="rounded-2xl p-6 sm:p-10 cursor-pointer transition lg:min-h-[480px] flex"
            style={{
              background: "#ffffff",
              border: `2px dashed ${dragOver ? "#0a7870" : "#e7ddc5"}`,
            }}
          >
            <div className="flex-1 min-w-0 flex flex-col items-center justify-center text-center py-4 sm:py-10">
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
                className="text-[20px] sm:text-[22px] font-semibold mb-2 max-w-full break-words"
                style={{ color: "#1f2a2e" }}
              >
                {multi ? `${files.length} documents` : file ? file.name : "Drop your document here"}
              </div>
              <div className="text-sm mb-8" style={{ color: "#8a8270" }}>
                {file
                  ? "Drop or browse to add more documents from the same client"
                  : "or click to browse · PDF, DOCX, JPG, PNG · up to 20 MB · several files make a batch"}
              </div>

              <div className="flex items-center gap-3">
                {/* A native label opens the picker without scripted clicks, which some browsers block. */}
                <label
                  htmlFor="new-project-files"
                  role="button"
                  tabIndex={0}
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault()
                      handlePickFile()
                    }
                  }}
                  aria-disabled={loading}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-medium text-white transition cursor-pointer select-none"
                  style={{ background: "#0a7870", pointerEvents: loading ? "none" : undefined, opacity: loading ? 0.6 : 1 }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "#0a645d")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "#0a7870")}
                >
                  <IconUploadWhite />
                  {file ? "Add more files" : "Browse files"}
                </label>
              </div>

              <div className="flex items-center gap-5 mt-8 text-xs" style={{ color: "#8a8270" }}>
                <span>✓ PDF, DOCX, JPG, PNG</span>
              </div>
            </div>

            <input
              ref={fileInputRef}
              id="new-project-files"
              type="file"
              multiple
              className="hidden"
              accept=".pdf,.docx,.png,.jpg,.jpeg"
              // Its click would bubble to the drop zone and ask for the picker twice; browsers then ignore it.
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => {
                addFiles(e.target.files)
                e.target.value = ""
              }}
            />
          </div>

          {files.length === 1 && file && (
            <div
              className="mt-4 rounded-2xl px-4 py-3 flex items-center gap-3"
              style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate" style={{ color: "#1f2a2e" }}>
                  {file.name}
                </div>
                <div className="text-xs" style={{ color: "#8a8270" }}>
                  {(file.size / (1024 * 1024)).toFixed(1)} MB
                  {pageCounts[fileKey(file)] ? ` · ${pageCounts[fileKey(file)]} page${pageCounts[fileKey(file)] === 1 ? "" : "s"}` : ""}
                </div>
              </div>
              <button
                type="button"
                onClick={() => removeFile(file)}
                disabled={loading}
                className="text-xs font-semibold px-3 py-1.5 rounded-full disabled:opacity-50"
                style={{ color: "#b14a3a", border: "1px solid #ecd5cf", background: "#fdf6f4" }}
                aria-label={`Remove ${file.name}`}
              >
                Remove
              </button>
            </div>
          )}

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

        <div className="space-y-6 min-w-0">
          {}
          <div
            className="rounded-2xl p-6"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 1px 2px rgba(30,30,20,0.03)",
            }}
          >
            <ModeSwitch mode={mode} onChange={setMode} disabled={loading} />

            <LangSelect
              value={source}
              onChange={setSource}
              label={dtp ? "DOCUMENT LANGUAGE" : "SOURCE LANGUAGE"}
              options={SOURCE_LANGUAGES}
            />

            {!dtp && (
              <>
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
                {sameLanguage && (
                  <div role="alert" className="text-xs mt-2" style={{ color: "#b14a3a" }}>
                    Source and target are the same language. For a same-language Word file, choose Editable copy.
                  </div>
                )}
              </>
            )}

            {!dtp && (
              <div className="mt-5">
                <div className="flex items-baseline justify-between gap-3 mb-3">
                  <label
                    htmlFor="ai-instructions"
                    className="text-[11px] font-semibold tracking-[0.14em] uppercase"
                    style={{ color: "#9a9178" }}
                  >
                    Instructions for the AI (optional)
                  </label>
                  <span
                    className="text-[11px] tabular-nums shrink-0"
                    style={{ color: instructions.length >= MAX_INSTRUCTIONS ? "#b14a3a" : "#9a9178" }}
                  >
                    {instructions.length}/{MAX_INSTRUCTIONS}
                  </span>
                </div>
                {saved.enabled && saved.items.length > 0 && (
                  <div className="mb-2">
                    <SavedInstructionPicker
                      items={saved.items}
                      disabled={loading}
                      onPick={(text) => setInstructions(text.slice(0, MAX_INSTRUCTIONS))}
                    />
                  </div>
                )}
                <textarea
                  id="ai-instructions"
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                  maxLength={MAX_INSTRUCTIONS}
                  rows={3}
                  disabled={loading}
                  placeholder="e.g. Use British spelling"
                  className="w-full min-w-0 block text-sm outline-none rounded-xl px-4 py-3 resize-y"
                  style={{ background: "#faf5ee", border: "1px solid #e7ddc5", color: "#1f2a2e", minHeight: 76 }}
                />
                {saved.enabled && (
                  <div className="mt-2">
                    <SaveForLater text={instructions} onSave={saved.create} />
                  </div>
                )}
              </div>
            )}

            {!dtp && certsEnabled && certTemplates.length > 0 && (
              <div className="mt-5 pt-5" style={{ borderTop: "1px solid #f1e8d1" }}>
                <label
                  htmlFor="cert-template"
                  className="block text-[11px] font-semibold tracking-[0.14em] mb-3"
                  style={{ color: "#9a9178" }}
                >
                  CERTIFICATION
                </label>
                <div className="relative">
                  <select
                    id="cert-template"
                    value={certTemplateId}
                    onChange={(e) => setCertTemplateId(e.target.value)}
                    className="w-full min-w-0 appearance-none text-sm outline-none rounded-xl pl-4 pr-10 py-3"
                    style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#1f2a2e" }}
                  >
                    <option value="">Standard statement</option>
                    {certTemplates.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.file_name}
                      </option>
                    ))}
                  </select>
                  <span className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2">
                    <IconChevron />
                  </span>
                </div>
                <div className="text-xs mt-2" style={{ color: "#8a8270" }}>
                  Appended at export with the project details filled in.
                </div>
              </div>
            )}

            <div
              className="mt-5 pt-4 text-xs leading-relaxed"
              style={{ borderTop: "1px solid #f1e8d1", color: "#8a8270" }}
            >
              {dtp
                ? "Nothing is translated; signatures, stamps and unreadable parts are marked in brackets."
                : memoryAccess === "locked"
                ? "Translation memory and glossary come with Pro."
                : "Translation memory and glossary are applied automatically."}{" "}
              Layout and page orientation follow the source.
            </div>
          </div>

          <div>
            <button
              onClick={handleStart}
              disabled={!file || loading || sameLanguage}
              className="w-full flex items-center justify-center gap-2 py-4 rounded-full text-[15px] font-semibold transition"
              style={{
                background: !file || loading || sameLanguage ? "#9bc9c5" : "#0a7870",
                color: "#ffffff",
                cursor: !file || loading || sameLanguage ? "not-allowed" : "pointer",
              }}
              onMouseEnter={(e) => {
                if (file && !loading && !sameLanguage) e.currentTarget.style.background = "#0a645d"
              }}
              onMouseLeave={(e) => {
                if (file && !loading && !sameLanguage) e.currentTarget.style.background = "#0a7870"
              }}
            >
              {loading
                ? "Uploading..."
                : multi
                ? batchId
                  ? "Upload remaining documents"
                  : dtp
                  ? `Create ${files.length} editable copies`
                  : `Translate ${files.length} documents`
                : dtp
                ? "Create editable copy"
                : "Start OCR & translation"}
              {!loading && <IconArrowRight />}
            </button>
            {uploadError && !multi && (
              <div
                role="alert"
                className="text-sm rounded-lg px-3 py-2 mt-3"
                style={{ background: "#f2d4cf", color: "#7a2f24" }}
              >
                {uploadError}
              </div>
            )}
            <div className="text-xs text-center mt-3" style={{ color: "#8a8270" }}>
              {multi
                ? dtp
                  ? "1 credit per page · same settings for every document"
                  : "1 credit per page · same languages and instructions for every document"
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

const MODES = [
  { value: "translate" as const, label: "Translate" },
  { value: "dtp" as const, label: "Editable copy" },
]

function ModeSwitch({
  mode,
  onChange,
  disabled,
}: {
  mode: "translate" | "dtp"
  onChange: (m: "translate" | "dtp") => void
  disabled: boolean
}) {
  return (
    <div className="mb-5">
      <div
        role="radiogroup"
        aria-label="Project type"
        className="grid grid-cols-2 gap-1 p-1 rounded-full"
        style={{ background: "#f3ecdb", border: "1px solid #ede3cc" }}
      >
        {MODES.map((m) => {
          const active = mode === m.value
          return (
            <button
              key={m.value}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={disabled}
              onClick={() => onChange(m.value)}
              className="text-[13px] font-semibold px-3 py-2 rounded-full transition whitespace-nowrap"
              style={{
                background: active ? "#ffffff" : "transparent",
                color: active ? "#0a7870" : "#6b6558",
                boxShadow: active ? "0 1px 2px rgba(30,30,20,0.08)" : "none",
                cursor: disabled ? "not-allowed" : "pointer",
              }}
            >
              {m.label}
            </button>
          )
        })}
      </div>
      {mode === "dtp" && (
        <div className="text-xs mt-2 px-1" style={{ color: "#8a8270" }}>
          Same language, editable Word file for your CAT tool
        </div>
      )}
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
      className="rounded-2xl p-5 sm:p-6 mt-6"
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
                <div className="sm:hidden text-xs truncate" style={{ color }} title={label}>
                  {label}
                </div>
                {u?.state === "uploading" && (
                  <div className="h-1 rounded-full mt-1.5" style={{ background: "#f3ecdb" }}>
                    <div className="h-1 rounded-full" style={{ width: `${u.pct ?? 0}%`, background: "#0a7870" }} />
                  </div>
                )}
              </div>
              <div className="text-xs w-12 sm:w-16 text-right shrink-0" style={{ color: "#6b6558" }}>
                {pages == null ? "—" : `${pages} p.`}
              </div>
              <div className="hidden sm:block text-xs w-40 text-right truncate shrink-0" style={{ color }} title={label}>
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
              <Link href={`/jobs?batch=${batchId}`} className="font-semibold underline" style={{ color: "#0a7870" }}>
                Open in Projects
              </Link>
            </>
          )}
        </div>
      )}
    </div>
  )
}
