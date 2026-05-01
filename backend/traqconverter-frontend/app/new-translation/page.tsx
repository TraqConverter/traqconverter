"use client"

import { useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"

// ============================================================
// NEW PROJECT — ESPRESSO LOOK
// ============================================================

type LangOption = {
  code: string
  flag: string
  name: string
}

const LANGUAGES: LangOption[] = [
  { code: "en-GB", flag: "GB", name: "English (UK)" },
  { code: "en-US", flag: "US", name: "English (US)" },
  { code: "it-IT", flag: "IT", name: "Italian" },
  { code: "fr-FR", flag: "FR", name: "French" },
  { code: "de-DE", flag: "DE", name: "German" },
  { code: "es-ES", flag: "ES", name: "Spanish" },
  { code: "ja-JP", flag: "JP", name: "Japanese" },
  { code: "sv-SE", flag: "SE", name: "Swedish" },
  { code: "pt-PT", flag: "PT", name: "Portuguese" },
  { code: "nl-NL", flag: "NL", name: "Dutch" },
]

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
}: {
  value: string
  onChange: (v: string) => void
  label: string
}) {
  const [open, setOpen] = useState(false)
  const current = LANGUAGES.find((l) => l.code === value) || LANGUAGES[0]
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
            {LANGUAGES.map((l) => (
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

  const [file, setFile] = useState<File | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [loading, setLoading] = useState(false)

  const [source, setSource] = useState("en-GB")
  const [target, setTarget] = useState("it-IT")

  const [useTM, setUseTM] = useState(true)
  const [applyGlossary, setApplyGlossary] = useState(true)
  const [requestCert, setRequestCert] = useState(false)

  const handlePickFile = () => fileInputRef.current?.click()

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files?.[0]
    if (f) setFile(f)
  }

  const swap = () => {
    setSource(target)
    setTarget(source)
  }

  const handleStart = async () => {
    if (!file) return alert("Please select a file first")

    try {
      setLoading(true)

      const formData = new FormData()
      formData.append("file", file)
      formData.append("source_language", source)
      formData.append("target_language", target)
      formData.append("use_tm", String(useTM))
      formData.append("apply_glossary", String(applyGlossary))
      formData.append("request_certification", String(requestCert))

      const res = await api.post("/projects/upload", formData)
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
    setFile(sample)
  }

  return (
    <div className="max-w-[1200px] mx-auto">
      {/* BREADCRUMB */}
      <div className="mb-3">
        <div className="text-sm" style={{ color: "#8a8270" }}>
          <span>Espresso</span>
          <span className="mx-2">›</span>
          <span>Projects</span>
          <span className="mx-2">›</span>
          <span>New</span>
        </div>
      </div>

      {/* TITLE */}
      <h1
        className="text-[34px] font-semibold tracking-tight mb-1"
        style={{ color: "#1f2a2e" }}
      >
        New project
      </h1>

      {/* BACK LINK */}
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
        {/* LEFT — DROPZONE */}
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
                {file ? file.name : "Drop your document here"}
              </div>
              <div className="text-sm mb-8" style={{ color: "#8a8270" }}>
                or click to browse · PDF, DOCX, PPTX · up to 200 MB
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

                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    trySample()
                  }}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-medium transition"
                  style={{
                    background: "#ffffff",
                    border: "1px solid #e7ddc5",
                    color: "#4a4638",
                  }}
                >
                  <IconFile />
                  Try a sample
                </button>
              </div>

              <div className="flex items-center gap-5 mt-8 text-xs" style={{ color: "#8a8270" }}>
                <span>✓ Encrypted at rest</span>
                <span>✓ SOC 2 compliant</span>
                <span>✓ 14-day free revisions</span>
              </div>
            </div>

            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept=".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </div>
        </div>

        {/* RIGHT — SETTINGS */}
        <div className="space-y-6">
          {/* LANGUAGES */}
          <div
            className="rounded-2xl p-6"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              boxShadow: "0 1px 2px rgba(30,30,20,0.03)",
            }}
          >
            <LangSelect value={source} onChange={setSource} label="SOURCE LANGUAGE" />

            <div className="flex justify-center my-3">
              <button
                onClick={swap}
                className="w-9 h-9 rounded-full flex items-center justify-center transition"
                style={{ background: "#e1efec", border: "1px solid #cfe6e2" }}
                aria-label="Swap languages"
              >
                <IconSwap />
              </button>
            </div>

            <LangSelect value={target} onChange={setTarget} label="TARGET LANGUAGE" />
          </div>

          {/* OPTIONS */}
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
              subtitle="ISO 17100 · signed affidavit"
              checked={requestCert}
              onChange={setRequestCert}
              last
            />
          </div>

          {/* START CTA */}
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
              {loading ? "Uploading..." : "Start OCR & translation"}
              {!loading && <IconArrowRight />}
            </button>
            <div className="text-xs text-center mt-3" style={{ color: "#8a8270" }}>
              Quote within 1 hour · twice proofread · 14-day free revisions
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
