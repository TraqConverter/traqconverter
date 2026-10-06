"use client"

import { useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"
import { LangSelect, TARGET_LANGUAGES } from "@/components/LangSelect"
import { snapshotFile, UNREADABLE_FILE } from "@/lib/fileSnapshot"

const MAX_BYTES = 20 * 1024 * 1024
const ORIGINAL_EXT = /\.(pdf|jpe?g|png)$/i
const TRANSLATION_EXT = /\.docx$/i

type Profile = {
  document_type: string
  country: string
  issuing_authority: string
  format_variant: string
  source_language: string
}

type Existing = { id: string; title: string; target_language_name: string } | null

type Analysis = {
  upload_id: string
  target_language: string
  target_language_name: string
  profile: Profile
  title: string
  existing_template: Existing
}

type Saved = {
  memory_lines_added: number
  memory_note: string | null
  replaced: boolean
  template: { title: string }
}

function detail(err: unknown, fallback: string) {
  const raw = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof raw === "string" ? raw : fallback
}

function fileProblem(f: File, ext: RegExp, kind: string) {
  if (!ext.test(f.name)) return `${kind} must be ${kind === "The original" ? "a PDF, JPG or PNG file" : "a Word .docx file"}`
  if (f.size > MAX_BYTES) return `${kind} is larger than 20 MB`
  return null
}

export default function AddFromPastJob({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [step, setStep] = useState<"upload" | "confirm" | "done">("upload")
  const [original, setOriginal] = useState<File | null>(null)
  const [translation, setTranslation] = useState<File | null>(null)
  const [target, setTarget] = useState("en-GB")
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [existing, setExisting] = useState<Existing>(null)
  const [title, setTitle] = useState("")
  const [saved, setSaved] = useState<Saved | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [busy, onClose])

  // The key changes with the edited fields, and with it the template that would be replaced.
  useEffect(() => {
    if (step !== "confirm" || !analysis || !profile) return
    let live = true
    const timer = setTimeout(async () => {
      try {
        const { data } = await api.get("/templates/key-check", {
          params: {
            upload_id: analysis.upload_id,
            target_language: analysis.target_language,
            document_type: profile.document_type,
            country: profile.country,
            issuing_authority: profile.issuing_authority,
            format_variant: profile.format_variant,
          },
        })
        if (live) {
          setExisting(data.existing_template)
          setTitle(data.title)
        }
      } catch {
        // The warning is advisory; saving still works.
      }
    }, 400)
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [step, analysis, profile])

  const pick = async (f: File | null, ext: RegExp, kind: string, set: (f: File | null) => void) => {
    if (!f) return
    const problem = fileProblem(f, ext, kind)
    setError(problem)
    if (problem) return
    try {
      set(await snapshotFile(f))
    } catch {
      setError(UNREADABLE_FILE)
    }
  }

  const analyse = async () => {
    if (!original || !translation) return
    setBusy(true)
    setError(null)
    try {
      const form = new FormData()
      form.append("original", original)
      form.append("translation", translation)
      form.append("target_language", target)
      const { data } = await api.post<Analysis>("/templates/analyze", form)
      setAnalysis(data)
      setProfile(data.profile)
      setExisting(data.existing_template)
      setTitle(data.title)
      setStep("confirm")
    } catch (err) {
      setError(detail(err, "Couldn't analyse the files"))
    } finally {
      setBusy(false)
    }
  }

  const save = async () => {
    if (!analysis || !profile) return
    if (!profile.document_type.trim()) {
      setError("Enter the document type")
      return
    }
    setBusy(true)
    setError(null)
    try {
      const { data } = await api.post<Saved>("/templates/from-upload", {
        upload_id: analysis.upload_id,
        target_language: analysis.target_language,
        ...profile,
      })
      setSaved(data)
      setStep("done")
      onSaved()
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      setError(detail(err, "Couldn't save the template"))
      if (status === 410 || status === 404) {
        setAnalysis(null)
        setStep("upload")
      }
    } finally {
      setBusy(false)
    }
  }

  const restart = () => {
    setStep("upload")
    setOriginal(null)
    setTranslation(null)
    setAnalysis(null)
    setProfile(null)
    setSaved(null)
    setError(null)
  }

  const field = (key: keyof Profile) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    setProfile((p) => (p ? { ...p, [key]: value } : p))
  }

  return (
    <div
      onClick={() => !busy && onClose()}
      className="fixed inset-0 flex items-start sm:items-center justify-center p-4 overflow-y-auto"
      style={{ background: "rgba(31,42,46,0.45)", backdropFilter: "blur(2px)", zIndex: 100 }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Add a template from a past job"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[640px] rounded-2xl p-5 sm:p-6 my-auto"
        style={{ background: "#fbf6ea", border: "1px solid #e7ddc5", boxShadow: "0 18px 40px rgba(0,0,0,0.25)" }}
      >
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <div className="text-[11px] font-semibold tracking-[0.16em] mb-1" style={{ color: "#9a9178" }}>
              {step === "upload" ? "STEP 1 OF 2" : step === "confirm" ? "STEP 2 OF 2" : "DONE"}
            </div>
            <div className="text-[18px] font-semibold" style={{ color: "#1f2a2e" }}>
              Add from a past job
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            disabled={busy}
            className="w-8 h-8 rounded-full flex items-center justify-center transition hover:bg-[#f3ecdb] shrink-0"
            style={{ color: "#6b6558" }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>

        {error && (
          <div className="text-sm rounded-lg px-3 py-2 mb-4" style={{ background: "#f2d4cf", color: "#7a2f24" }}>
            {error}
          </div>
        )}

        {step === "upload" && (
          <div className="space-y-4">
            <p className="text-sm" style={{ color: "#6b6558" }}>
              Upload a document you translated before and your finished translation. It becomes a template for the
              same kind of document, and its sentences go into your translation memory.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <DropZone
                label="Original document (PDF, JPG, PNG)"
                accept=".pdf,.jpg,.jpeg,.png"
                file={original}
                disabled={busy}
                onFile={(f) => pick(f, ORIGINAL_EXT, "The original", setOriginal)}
              />
              <DropZone
                label="Your translation (Word .docx)"
                accept=".docx"
                file={translation}
                disabled={busy}
                onFile={(f) => pick(f, TRANSLATION_EXT, "Your translation", setTranslation)}
              />
            </div>
            <LangSelect value={target} onChange={setTarget} label="LANGUAGE OF YOUR TRANSLATION" options={TARGET_LANGUAGES} />
            <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-3 pt-1">
              <div className="text-xs" style={{ color: "#8a8270" }}>
                {busy ? "Reading the original and identifying the document. This can take up to a minute." : "Up to 20 MB each"}
              </div>
              <button
                type="button"
                onClick={analyse}
                disabled={busy || !original || !translation}
                className="px-5 py-2.5 rounded-full text-sm font-semibold text-white transition"
                style={{ background: "#0a7870", opacity: busy || !original || !translation ? 0.55 : 1 }}
              >
                {busy ? "Analysing…" : "Analyse"}
              </button>
            </div>
          </div>
        )}

        {step === "confirm" && profile && analysis && (
          <div className="space-y-4">
            <p className="text-sm" style={{ color: "#6b6558" }}>
              Check how the document was identified. The next document with the same type and country is built from
              this template.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field label="DOCUMENT TYPE" value={profile.document_type} onChange={field("document_type")} placeholder="e.g. birth certificate" />
              <Field label="COUNTRY" value={profile.country} onChange={field("country")} placeholder="e.g. IT" maxLength={2} />
              <Field label="ISSUER" value={profile.issuing_authority} onChange={field("issuing_authority")} placeholder="e.g. Comune di Bari" />
              <Field label="VARIANT (OPTIONAL)" value={profile.format_variant} onChange={field("format_variant")} placeholder="e.g. multilingual extract" />
              <Field label="SOURCE LANGUAGE" value={profile.source_language} onChange={field("source_language")} placeholder="e.g. Italian" />
              <div>
                <div className="text-[11px] font-semibold tracking-[0.14em] mb-1.5" style={{ color: "#9a9178" }}>
                  TRANSLATION
                </div>
                <div className="px-3 py-2.5 rounded-xl text-sm" style={{ background: "#f3ecdb", border: "1px solid #e7ddc5", color: "#4a4638" }}>
                  {analysis.target_language_name}
                </div>
              </div>
            </div>
            <div className="text-sm" style={{ color: "#4a4638" }}>
              Saved as <span className="font-medium" style={{ color: "#1f2a2e" }}>{title}</span>
            </div>
            {existing && (
              <div className="text-sm rounded-lg px-3 py-2" style={{ background: "#f6e3b8", color: "#6b4a10", border: "1px solid #ecd49a" }}>
                This replaces the existing template for {existing.title} ({existing.target_language_name}).
              </div>
            )}
            <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={restart}
                disabled={busy}
                className="px-4 py-2.5 rounded-full text-sm font-medium transition hover:bg-[#f3ecdb]"
                style={{ border: "1px solid #e7ddc5", color: "#4a4638", background: "#ffffff" }}
              >
                Start over
              </button>
              <button
                type="button"
                onClick={save}
                disabled={busy}
                className="px-5 py-2.5 rounded-full text-sm font-semibold text-white transition"
                style={{ background: "#0a7870", opacity: busy ? 0.55 : 1 }}
              >
                {busy ? "Saving…" : "Save template"}
              </button>
            </div>
          </div>
        )}

        {step === "done" && saved && (
          <div className="space-y-4">
            <div className="rounded-xl px-4 py-4" style={{ background: "#cfe6e2", border: "1px solid #b7dad4", color: "#0a5e58" }}>
              <div className="text-[15px] font-semibold">
                Template saved · {saved.memory_lines_added} {saved.memory_lines_added === 1 ? "line" : "lines"} added to your memory
              </div>
              <div className="text-sm mt-1" style={{ color: "#23665f" }}>
                {saved.template.title}
                {saved.replaced ? " · replaced the previous template" : ""}
              </div>
            </div>
            {saved.memory_note && (
              <div className="text-sm" style={{ color: "#6b6558" }}>
                {saved.memory_note}
              </div>
            )}
            <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
              <button
                type="button"
                onClick={restart}
                className="px-4 py-2.5 rounded-full text-sm font-medium transition hover:bg-[#f3ecdb]"
                style={{ border: "1px solid #e7ddc5", color: "#4a4638", background: "#ffffff" }}
              >
                Add another
              </button>
              <button
                type="button"
                onClick={onClose}
                className="px-5 py-2.5 rounded-full text-sm font-semibold text-white"
                style={{ background: "#0a7870" }}
              >
                Done
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  maxLength,
}: {
  label: string
  value: string
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
  placeholder?: string
  maxLength?: number
}) {
  return (
    <label className="block">
      <div className="text-[11px] font-semibold tracking-[0.14em] mb-1.5" style={{ color: "#9a9178" }}>
        {label}
      </div>
      <input
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        maxLength={maxLength ?? 120}
        className="w-full px-3 py-2.5 rounded-xl text-sm outline-none focus:ring-2 focus:ring-[#cfe6e2]"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#1f2a2e" }}
      />
    </label>
  )
}

function DropZone({
  label,
  accept,
  file,
  disabled,
  onFile,
}: {
  label: string
  accept: string
  file: File | null
  disabled: boolean
  onFile: (f: File | null) => void
}) {
  const input = useRef<HTMLInputElement | null>(null)
  const [over, setOver] = useState(false)
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !disabled) {
          e.preventDefault()
          input.current?.click()
        }
      }}
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        if (!disabled) onFile(e.dataTransfer.files?.[0] ?? null)
      }}
      className="rounded-xl p-4 cursor-pointer transition min-h-[116px] flex flex-col items-center justify-center text-center"
      style={{ background: "#ffffff", border: `2px dashed ${over || file ? "#0a7870" : "#e7ddc5"}`, opacity: disabled ? 0.7 : 1 }}
    >
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0a7870" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        {file ? <path d="m5 12 5 5 9-10" /> : <path d="M12 4v12m-5-7 5-5 5 5M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />}
      </svg>
      <div className="text-[13px] font-semibold mt-2" style={{ color: "#1f2a2e" }}>
        {label}
      </div>
      <div className="text-xs mt-1 max-w-full truncate" style={{ color: file ? "#0a5e58" : "#8a8270" }}>
        {file ? file.name : "Drop here or click to browse"}
      </div>
      <input
        ref={input}
        type="file"
        accept={accept}
        className="hidden"
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => {
          onFile(e.target.files?.[0] ?? null)
          e.target.value = ""
        }}
      />
    </div>
  )
}
