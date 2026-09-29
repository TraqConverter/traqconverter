"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import { api } from "@/lib/api"

type Doc = {
  id: string
  filename: string
  status: string
  review_status: string
  progress: number
  page_count: number
  source_lang: string
  target_lang: string
  failure_reason: string | null
}

type Term = {
  source_term: string
  target_term: string
  kind: string
  first_project_name: string | null
}

type BatchDetail = {
  id: string
  name: string
  created_at: string | null
  documents: number
  pages: number
  completed: number
  failed: number
  in_progress: number
  projects: Doc[]
  batch_terms: Term[]
}

const COLUMNS = "2.2fr 1fr 0.5fr 1fr 0.8fr"
const POLL_MS = 5000

const STATUS_STYLES: Record<string, { bg: string; dot: string; text: string; label: string }> = {
  PENDING: { bg: "#ede3cc", dot: "#9a9178", text: "#6b6558", label: "Queued" },
  PROCESSING: { bg: "#cfe6e2", dot: "#0a7870", text: "#0a5e58", label: "Translating" },
  IN_REVIEW: { bg: "#f6e3b8", dot: "#c88a1a", text: "#7a5a10", label: "In review" },
  COMPLETED: { bg: "#d8ead6", dot: "#4a8a3a", text: "#2d5a24", label: "Delivered" },
  CERTIFIED: { bg: "#d8ead6", dot: "#4a8a3a", text: "#2d5a24", label: "Certified" },
  FAILED: { bg: "#f2d4cf", dot: "#b14a3a", text: "#7a2f24", label: "Failed" },
}

const KIND_ORDER = ["person", "institution", "place", "degree", "term"]
const KIND_LABEL: Record<string, string> = {
  person: "Names",
  institution: "Institutions",
  place: "Places",
  degree: "Degrees",
  term: "Terms",
}

function effectiveStatus(d: Doc) {
  const s = (d.status || "").toUpperCase()
  if (s !== "COMPLETED") return s || "PENDING"
  const r = (d.review_status || "").toUpperCase()
  return r === "CERTIFIED" || r === "IN_REVIEW" ? r : "COMPLETED"
}

function isActive(d: Doc) {
  const s = (d.status || "").toUpperCase()
  return s === "PENDING" || s === "PROCESSING"
}

async function blobErrorDetail(err: unknown, fallback: string) {
  const e = err as { response?: { status?: number; data?: unknown } }
  if (e?.response?.status === 403) return "Downloads need a paid plan. Upgrade in Billing."
  const raw = e?.response?.data
  if (raw instanceof Blob) {
    try {
      return JSON.parse(await raw.text())?.detail || fallback
    } catch {
      return fallback
    }
  }
  return fallback
}

export default function BatchPage() {
  const params = useParams()
  const id = params?.id as string
  const router = useRouter()
  const [batch, setBatch] = useState<BatchDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/batches/${id}`)
      setBatch(res.data)
      setError(null)
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      setError(status === 404 ? "Batch not found" : "Couldn't load the batch")
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const polling = !!batch?.projects.some(isActive)
  useEffect(() => {
    if (!polling) return
    const t = window.setInterval(load, POLL_MS)
    return () => window.clearInterval(t)
  }, [polling, load])

  const download = async (format: "docx" | "pdf") => {
    setBusy(`zip:${format}`)
    setNotice(null)
    try {
      const res = await api.get(`/batches/${id}/export.zip`, { params: { format }, responseType: "blob" })
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/zip" }))
      const a = document.createElement("a")
      a.href = url
      a.download = `${(batch?.name || "batch").replace(/[^\w .-]+/g, "_")} (${format.toUpperCase()}).zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      setNotice(await blobErrorDetail(err, "Download failed"))
    } finally {
      setBusy(null)
    }
  }

  const markDelivered = async () => {
    setBusy("review")
    setNotice(null)
    try {
      const res = await api.post(`/batches/${id}/review-status`, { status: "CERTIFIED" })
      const { updated, skipped } = res.data as { updated: number; skipped: number }
      setNotice(
        `${updated} document${updated === 1 ? "" : "s"} marked delivered` +
          (skipped ? ` · ${skipped} not finished yet, left as is` : ""),
      )
      setConfirming(false)
      await load()
    } catch {
      setNotice("Couldn't update the documents")
    } finally {
      setBusy(null)
    }
  }

  if (error && !batch) {
    return (
      <div className="py-16 text-center">
        <div className="text-[16px] font-semibold mb-2" style={{ color: "#1f2a2e" }}>
          {error}
        </div>
        <Link href="/batches" className="text-sm hover:underline" style={{ color: "#0a7870" }}>
          ← All batches
        </Link>
      </div>
    )
  }

  if (!batch) {
    return (
      <div className="py-16 text-center text-sm" style={{ color: "#8a8270" }}>
        Loading batch…
      </div>
    )
  }

  const canDownload = batch.completed > 0
  const terms = [...batch.batch_terms].sort(
    (a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind),
  )
  const groups = KIND_ORDER.map((k) => ({ kind: k, items: terms.filter((t) => t.kind === k) })).filter(
    (g) => g.items.length,
  )

  return (
    <div className="space-y-6 pb-16">
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <Link href="/batches" className="hover:underline">
          Batches
        </Link>{" "}
        <span style={{ color: "#cfc6ad" }}>›</span> <span style={{ color: "#1f2a2e" }}>{batch.name}</span>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold tracking-[0.18em] mb-1" style={{ color: "#9a9178" }}>
            BATCH
          </div>
          <h1 className="text-[28px] font-semibold tracking-tight truncate" style={{ color: "#1f2a2e" }}>
            {batch.name}
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            {batch.documents} document{batch.documents === 1 ? "" : "s"} · {batch.pages} page
            {batch.pages === 1 ? "" : "s"} · {batch.completed} done
            {batch.in_progress ? ` · ${batch.in_progress} in progress` : ""}
            {batch.failed ? ` · ${batch.failed} failed` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(["docx", "pdf"] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => download(f)}
              disabled={!canDownload || !!busy}
              title={canDownload ? `Every finished document as ${f.toUpperCase()}, in one ZIP` : "No finished documents yet"}
              className="px-4 py-2 rounded-full text-sm font-medium transition"
              style={{
                background: f === "docx" ? "#0a7870" : "#ffffff",
                color: f === "docx" ? "#ffffff" : "#0a7870",
                border: "1px solid #0a7870",
                opacity: !canDownload || busy ? 0.55 : 1,
                cursor: !canDownload || busy ? "not-allowed" : "pointer",
              }}
            >
              {busy === `zip:${f}` ? "Preparing…" : `Download all (${f.toUpperCase()} ZIP)`}
            </button>
          ))}
          {confirming ? (
            <span className="inline-flex items-center gap-1.5">
              <button
                type="button"
                onClick={markDelivered}
                disabled={!!busy}
                className="px-4 py-2 rounded-full text-sm font-medium text-white"
                style={{ background: "#4a8a3a", opacity: busy ? 0.6 : 1 }}
              >
                {busy === "review" ? "Updating…" : `Confirm: ${batch.completed} finished`}
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="px-3 py-2 rounded-full text-sm"
                style={{ border: "1px solid #e7ddc5", color: "#4a4638" }}
              >
                Cancel
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              disabled={!canDownload || !!busy}
              title="Set every finished document to Certified"
              className="px-4 py-2 rounded-full text-sm font-medium"
              style={{
                border: "1px solid #e7ddc5",
                color: "#2d5a24",
                background: "#ffffff",
                opacity: !canDownload || busy ? 0.55 : 1,
                cursor: !canDownload || busy ? "not-allowed" : "pointer",
              }}
            >
              Mark all delivered
            </button>
          )}
        </div>
      </div>

      {notice && (
        <div className="text-sm rounded-lg px-3 py-2" style={{ background: "#faf5ee", border: "1px solid #e7ddc5", color: "#4a4638" }}>
          {notice}
        </div>
      )}

      <div className="rounded-2xl p-5" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
        <div className="text-[11px] font-semibold tracking-[0.14em] mb-1" style={{ color: "#9a9178" }}>
          CONSISTENT ACROSS THIS BATCH
        </div>
        {groups.length === 0 ? (
          <div className="text-sm" style={{ color: "#8a8270" }}>
            {polling
              ? "The first document is translating. Its names and terms will be reused in the others."
              : "No shared names or terms recorded for this batch."}
          </div>
        ) : (
          <div className="space-y-3 mt-3">
            {groups.map((g) => (
              <div key={g.kind} className="flex flex-wrap items-baseline gap-1.5">
                <span className="text-xs w-24 shrink-0" style={{ color: "#8a8270" }}>
                  {KIND_LABEL[g.kind] || g.kind}
                </span>
                {g.items.map((t) => (
                  <span
                    key={`${t.kind}:${t.source_term}`}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs"
                    style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
                    title={t.first_project_name ? `First used in ${t.first_project_name}` : undefined}
                  >
                    <span style={{ color: "#4a4638" }}>{t.source_term}</span>
                    <span style={{ color: "#9a9178" }}>→</span>
                    <span className="font-medium" style={{ color: "#1f2a2e" }}>
                      {t.target_term}
                    </span>
                  </span>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-2xl overflow-x-auto" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
        <div className="min-w-[720px]">
          <div
            className="grid items-center text-[11px] font-semibold tracking-[0.14em] px-5 py-3"
            style={{ gridTemplateColumns: COLUMNS, background: "#faf5ee", borderBottom: "1px solid #f1e8d1", color: "#9a9178" }}
          >
            <div>DOCUMENT</div>
            <div>STATUS</div>
            <div className="text-right">PAGES</div>
            <div className="pl-6">LANGUAGES</div>
            <div />
          </div>
          {batch.projects.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm" style={{ color: "#8a8270" }}>
              No documents in this batch.
            </div>
          ) : (
            batch.projects.map((d) => {
              const s = STATUS_STYLES[effectiveStatus(d)] || STATUS_STYLES.PENDING
              const active = isActive(d)
              return (
                <div
                  key={d.id}
                  className="grid items-center px-5 py-4 text-sm"
                  style={{ gridTemplateColumns: COLUMNS, borderBottom: "1px solid #f4ecd6", color: "#1f2a2e" }}
                >
                  <div className="pr-4 min-w-0">
                    <div className="font-medium truncate">{d.filename}</div>
                    {d.failure_reason && (
                      <div className="text-xs truncate" style={{ color: "#7a2f24" }} title={d.failure_reason}>
                        {d.failure_reason}
                      </div>
                    )}
                  </div>
                  <div>
                    <span
                      className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full"
                      style={{ background: s.bg, color: s.text }}
                    >
                      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.dot }} />
                      {s.label}
                      {active && d.progress ? ` ${d.progress}%` : ""}
                    </span>
                  </div>
                  <div className="text-right tabular-nums">{d.page_count}</div>
                  <div className="pl-6 text-xs font-mono" style={{ color: "#6b6558" }}>
                    {d.source_lang} → {d.target_lang}
                  </div>
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={() => router.push(`/editor/${d.id}`)}
                      className="text-xs px-3 py-1 rounded-full transition hover:bg-[#faf5ee]"
                      style={{ border: "1px solid #e7ddc5", color: "#0a7870" }}
                    >
                      Open in editor
                    </button>
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
