"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { api } from "@/lib/api"
import ProPaywall from "@/components/ProPaywall"

// ============================================================
// CERTIFICATIONS LIBRARY — ESPRESSO LOOK
// Wired to real backend:
//   GET    /certifications                 → { team_id, items[] }
//   POST   /certifications/upload          (multipart: file, kind, notes)
//   GET    /certifications/{id}/download   (auth-scoped binary stream)
//   DELETE /certifications/{id}
//
// Each upload's bytes are SHA-256 hashed server-side and the digest is
// surfaced here as the "tamper-evident hash" the empty-state copy mentions.
// ============================================================

type Cert = {
  id: string
  file_name: string
  kind: string
  notes: string | null
  file_hash: string
  size_bytes: number
  mime_type: string | null
  uploaded_at: string | null
  uploaded_by: string | null
  uploader_email: string | null
}

type KindFilter = "all" | "AFFIDAVIT" | "ISO_17100" | "SWORN_DECLARATION" | "OTHER"

const KINDS: { value: Exclude<KindFilter, "all">; label: string }[] = [
  { value: "AFFIDAVIT", label: "Signed affidavit" },
  { value: "ISO_17100", label: "ISO 17100 certificate" },
  { value: "SWORN_DECLARATION", label: "Sworn declaration" },
  { value: "OTHER", label: "Other supporting doc" },
]

const KIND_LABEL: Record<string, string> = {
  AFFIDAVIT: "Affidavit",
  ISO_17100: "ISO 17100",
  SWORN_DECLARATION: "Sworn declaration",
  OTHER: "Other",
}

const KIND_BG: Record<string, string> = {
  AFFIDAVIT: "#cfe6e2",
  ISO_17100: "#d8ead6",
  SWORN_DECLARATION: "#f6e3b8",
  OTHER: "#f3ecdb",
}

const KIND_FG: Record<string, string> = {
  AFFIDAVIT: "#0a5e58",
  ISO_17100: "#2d5a24",
  SWORN_DECLARATION: "#7a5a10",
  OTHER: "#6b6558",
}

const ALLOWED_EXT = [".pdf", ".docx", ".jpg", ".jpeg", ".png"]

function formatBytes(n: number) {
  if (!Number.isFinite(n) || n <= 0) return "—"
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function relativeTime(iso?: string | null) {
  if (!iso) return "—"
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return "—"
  const diff = Date.now() - t
  const m = 60_000, h = 3_600_000, d = 86_400_000
  if (diff < m) return "just now"
  if (diff < h) return `${Math.floor(diff / m)}m ago`
  if (diff < d) return `${Math.floor(diff / h)}h ago`
  if (diff < 7 * d) return `${Math.floor(diff / d)}d ago`
  return new Date(iso).toLocaleDateString()
}

export default function CertificationsPage() {
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const [items, setItems] = useState<Cert[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [kindFilter, setKindFilter] = useState<KindFilter>("all")
  const [query, setQuery] = useState("")

  // Upload-form state
  const [showUpload, setShowUpload] = useState(false)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [uploadKind, setUploadKind] = useState<string>("AFFIDAVIT")
  const [uploadNotes, setUploadNotes] = useState("")
  const [dragOver, setDragOver] = useState(false)
  const [gated, setGated] = useState(false)

  useEffect(() => {
    fetchItems()
  }, [])

  const fetchItems = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await api.get("/certifications")
      setItems(res.data?.items || [])
    } catch (err: any) {
      console.error("CERTIFICATIONS ERROR:", err)
      if (err?.response?.status === 403) {
        setGated(true)
        return
      }
      setError(
        err?.response?.data?.detail ||
          "Couldn't load certifications — try refreshing in a moment."
      )
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  const resetUploadForm = () => {
    setPendingFile(null)
    setUploadKind("AFFIDAVIT")
    setUploadNotes("")
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const validateFile = (file: File): string | null => {
    const lower = file.name.toLowerCase()
    if (!ALLOWED_EXT.some((ext) => lower.endsWith(ext))) {
      return `Only ${ALLOWED_EXT.join(", ")} are accepted.`
    }
    if (file.size > 20 * 1024 * 1024) {
      return "File is larger than 20 MB."
    }
    return null
  }

  const onPickFile = (file: File) => {
    setError(null)
    const msg = validateFile(file)
    if (msg) {
      setError(msg)
      return
    }
    setPendingFile(file)
    setShowUpload(true)
  }

  const submitUpload = async () => {
    if (!pendingFile) return
    try {
      setBusy("upload")
      setError(null)
      const fd = new FormData()
      fd.append("file", pendingFile)
      fd.append("kind", uploadKind)
      if (uploadNotes.trim()) fd.append("notes", uploadNotes.trim())
      await api.post("/certifications/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      setFlash(`${pendingFile.name} archived with a tamper-evident hash.`)
      setTimeout(() => setFlash(null), 4500)
      resetUploadForm()
      setShowUpload(false)
      await fetchItems()
    } catch (err: any) {
      console.error("UPLOAD CERT ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't upload that file. Please try again."
      )
    } finally {
      setBusy(null)
    }
  }

  const downloadCert = async (cert: Cert) => {
    try {
      setBusy(`dl:${cert.id}`)
      const res = await api.get(`/certifications/${cert.id}/download`, {
        responseType: "blob",
      })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const a = document.createElement("a")
      a.href = url
      a.download = cert.file_name
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err: any) {
      setError(
        err?.response?.data?.detail || "Couldn't download that file."
      )
    } finally {
      setBusy(null)
    }
  }

  const deleteCert = async (cert: Cert) => {
    if (!confirm(`Permanently delete "${cert.file_name}"?`)) return
    try {
      setBusy(`del:${cert.id}`)
      await api.delete(`/certifications/${cert.id}`)
      setItems((xs) => xs.filter((x) => x.id !== cert.id))
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't delete that file.")
    } finally {
      setBusy(null)
    }
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: items.length }
    for (const k of KINDS) c[k.value] = 0
    for (const it of items) {
      c[it.kind] = (c[it.kind] || 0) + 1
    }
    return c
  }, [items])

  const visible = useMemo(() => {
    let xs = items
    if (kindFilter !== "all") xs = xs.filter((x) => x.kind === kindFilter)
    if (query.trim()) {
      const q = query.toLowerCase()
      xs = xs.filter(
        (x) =>
          x.file_name.toLowerCase().includes(q) ||
          (x.notes || "").toLowerCase().includes(q) ||
          (x.uploader_email || "").toLowerCase().includes(q)
      )
    }
    return xs
  }, [items, kindFilter, query])

  if (gated) {
    return (
      <ProPaywall
        feature="Certifications"
        description="Archive signed affidavits, ISO 17100 certificates and sworn declarations alongside their SHA-256 hashes for tamper-evident delivery. Upgrade to Pro to start your library."
      />
    )
  }

  return (
    <div className="space-y-6 pb-16">
      {/* BREADCRUMB */}
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span> Assets{" "}
        <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <span style={{ color: "#1f2a2e" }}>Certifications</span>
      </div>

      {/* HEADER */}
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div
            className="text-[11px] font-semibold tracking-[0.18em] mb-1"
            style={{ color: "#9a9178" }}
          >
            CERTIFICATIONS
          </div>
          <h1
            className="text-[28px] font-semibold tracking-tight"
            style={{ color: "#1f2a2e" }}
          >
            Certifications library
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            Signed affidavits, ISO 17100 certificates and sworn declarations —
            archived here with tamper-evident SHA-256 hashes.
          </p>
        </div>

        <div className="flex items-center gap-2">
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
              placeholder="Search documents…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: "#1f2a2e" }}
            />
          </div>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
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
            Upload
          </button>
        </div>
      </div>

      {/* Hidden picker — feeds onPickFile */}
      <input
        ref={fileInputRef}
        type="file"
        accept={ALLOWED_EXT.join(",")}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onPickFile(f)
          // Reset so the same file can be re-picked later
          e.target.value = ""
        }}
      />

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

      {/* UPLOAD METADATA PANEL */}
      {showUpload && pendingFile && (
        <div
          className="rounded-2xl p-5"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
        >
          <div
            className="text-[11px] font-semibold tracking-[0.14em] mb-4"
            style={{ color: "#9a9178" }}
          >
            CONFIRM UPLOAD
          </div>
          <div className="flex items-center gap-3 mb-4">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
              style={{ background: "#f3ecdb", color: "#6b6558" }}
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
                <path d="M14 2v6h6" />
              </svg>
            </div>
            <div className="min-w-0">
              <div
                className="font-semibold truncate"
                style={{ color: "#1f2a2e" }}
              >
                {pendingFile.name}
              </div>
              <div className="text-xs" style={{ color: "#8a8270" }}>
                {formatBytes(pendingFile.size)}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
            <div>
              <div
                className="text-[11px] font-semibold tracking-[0.14em] mb-2"
                style={{ color: "#9a9178" }}
              >
                DOCUMENT TYPE
              </div>
              <div
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl"
                style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
              >
                <select
                  value={uploadKind}
                  onChange={(e) => setUploadKind(e.target.value)}
                  className="bg-transparent outline-none text-sm w-full"
                  style={{ color: "#1f2a2e" }}
                >
                  {KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <div
                className="text-[11px] font-semibold tracking-[0.14em] mb-2"
                style={{ color: "#9a9178" }}
              >
                NOTES
                <span
                  className="ml-1 font-normal lowercase tracking-normal"
                  style={{ color: "#cfc6ad" }}
                >
                  · optional
                </span>
              </div>
              <div
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl"
                style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
              >
                <input
                  value={uploadNotes}
                  onChange={(e) => setUploadNotes(e.target.value)}
                  placeholder="Project, jurisdiction, expiry date…"
                  className="bg-transparent outline-none text-sm w-full"
                  style={{ color: "#1f2a2e" }}
                />
              </div>
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 mt-4">
            <button
              type="button"
              onClick={() => {
                resetUploadForm()
                setShowUpload(false)
                setError(null)
              }}
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
              onClick={submitUpload}
              disabled={busy === "upload"}
              className="px-4 py-2 rounded-full text-sm font-semibold transition"
              style={{
                background: busy === "upload" ? "#9bc9c5" : "#0a7870",
                color: "#fff",
                cursor: busy === "upload" ? "not-allowed" : "pointer",
              }}
            >
              {busy === "upload" ? "Uploading…" : "Archive document"}
            </button>
          </div>
        </div>
      )}

      {/* DROPZONE — only when there are no items so it doesn't crowd the page */}
      {!loading && items.length === 0 && !showUpload && (
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            const f = e.dataTransfer.files?.[0]
            if (f) onPickFile(f)
          }}
          className="rounded-2xl py-14 px-6 flex flex-col items-center text-center transition"
          style={{
            background: dragOver ? "#f0f7f5" : "#ffffff",
            border: `1px dashed ${dragOver ? "#0a7870" : "#cfc6ad"}`,
          }}
        >
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4"
            style={{ background: "#cfe6e2", color: "#0a7870" }}
          >
            <svg
              width="26"
              height="26"
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
          </div>
          <div
            className="text-[18px] font-semibold mb-1"
            style={{ color: "#1f2a2e" }}
          >
            Certifications library
          </div>
          <p
            className="text-sm max-w-md mb-5 leading-relaxed"
            style={{ color: "#8a8270" }}
          >
            Drop a signed affidavit, ISO 17100 certificate or sworn declaration
            here. Each upload is hashed with SHA-256 so you can verify
            authenticity later.
          </p>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="px-4 py-2.5 rounded-full text-sm font-semibold transition"
            style={{ background: "#0a7870", color: "#fff" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "#0a645d")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "#0a7870")}
          >
            Choose a file
          </button>
          <p className="text-[11px] mt-3" style={{ color: "#9a9178" }}>
            PDF, DOCX, JPG, JPEG, PNG · up to 20 MB
          </p>
        </div>
      )}

      {/* KIND FILTER PILLS */}
      {items.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <KindPill
            label="All"
            count={counts.all || 0}
            active={kindFilter === "all"}
            onClick={() => setKindFilter("all")}
          />
          {KINDS.map((k) => (
            <KindPill
              key={k.value}
              label={k.label}
              count={counts[k.value] || 0}
              active={kindFilter === k.value}
              onClick={() => setKindFilter(k.value)}
            />
          ))}
        </div>
      )}

      {/* TABLE */}
      {items.length > 0 && (
        <div
          className="rounded-2xl overflow-hidden"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
        >
          <div
            className="grid items-center text-[11px] font-semibold tracking-[0.14em] px-5 py-3"
            style={{
              gridTemplateColumns:
                "minmax(260px,2fr) 1fr 1.4fr 0.8fr 1fr 100px",
              background: "#faf5ee",
              borderBottom: "1px solid #f1e8d1",
              color: "#9a9178",
            }}
          >
            <div>DOCUMENT</div>
            <div>TYPE</div>
            <div>SHA-256</div>
            <div className="text-right">SIZE</div>
            <div className="text-right">UPLOADED</div>
            <div />
          </div>

          {loading ? (
            <div
              className="px-5 py-12 text-center text-sm"
              style={{ color: "#8a8270" }}
            >
              Loading library…
            </div>
          ) : visible.length === 0 ? (
            <div
              className="px-5 py-12 text-center text-sm"
              style={{ color: "#8a8270" }}
            >
              No documents match this filter.
            </div>
          ) : (
            visible.map((c) => (
              <div
                key={c.id}
                className="grid items-center px-5 py-4 text-sm group"
                style={{
                  gridTemplateColumns:
                    "minmax(260px,2fr) 1fr 1.4fr 0.8fr 1fr 100px",
                  borderBottom: "1px solid #f4ecd6",
                  color: "#1f2a2e",
                }}
              >
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
                      title={c.file_name}
                    >
                      {c.file_name}
                    </div>
                    <div
                      className="text-xs truncate"
                      style={{ color: "#8a8270" }}
                    >
                      {c.notes ? c.notes : c.uploader_email || "—"}
                    </div>
                  </div>
                </div>
                <div>
                  <span
                    className="inline-flex items-center text-[11px] font-semibold tracking-[0.04em] px-2.5 py-1 rounded-full"
                    style={{
                      background: KIND_BG[c.kind] || "#f3ecdb",
                      color: KIND_FG[c.kind] || "#6b6558",
                    }}
                  >
                    {KIND_LABEL[c.kind] || c.kind}
                  </span>
                </div>
                <div
                  className="font-mono text-[11px] truncate"
                  style={{ color: "#8a8270" }}
                  title={c.file_hash}
                >
                  {c.file_hash.slice(0, 16)}…{c.file_hash.slice(-8)}
                </div>
                <div
                  className="text-right tabular-nums"
                  style={{ color: "#4a4638" }}
                >
                  {formatBytes(c.size_bytes)}
                </div>
                <div
                  className="text-right text-sm"
                  style={{ color: "#6b6558" }}
                  title={c.uploaded_at || ""}
                >
                  {relativeTime(c.uploaded_at)}
                </div>
                <div className="flex justify-end items-center gap-1">
                  <button
                    type="button"
                    onClick={() => downloadCert(c)}
                    disabled={busy === `dl:${c.id}`}
                    aria-label="Download"
                    title="Download"
                    className="opacity-0 group-hover:opacity-100 transition p-1.5 rounded-full"
                    style={{ color: "#0a7870", background: "transparent" }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.background = "#e7f1ef")
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
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="7 10 12 15 17 10" />
                      <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteCert(c)}
                    disabled={busy === `del:${c.id}`}
                    aria-label="Delete"
                    title="Delete"
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
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

function KindPill({
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
        background: active ? "#0a7870" : "#ffffff",
        color: active ? "#fff" : "#1f2a2e",
        border: `1px solid ${active ? "#0a7870" : "#e7ddc5"}`,
      }}
    >
      {label}
      <span
        className="text-[10px] font-semibold tabular-nums px-1.5 py-0.5 rounded-full"
        style={{
          background: active ? "rgba(255,255,255,0.18)" : "#f3ecdb",
          color: active ? "#fff" : "#8a8270",
        }}
      >
        {count.toLocaleString()}
      </span>
    </button>
  )
}
