"use client"

import { forwardRef, useState, type ReactNode } from "react"
import { api } from "@/lib/api"

export type BatchSummary = {
  id: string
  name: string
  created_at: string | null
  documents: number
  pages: number
  completed: number
  failed: number
  in_progress: number
  terms: number
}

export type BatchDoc = {
  id: string
  filename: string
  status: string
  review_status: string
  progress: number
  page_count: number
  source_lang: string
  target_lang: string
  failure_reason: string | null
  created_at: string | null
}

export type BatchTerm = {
  source_term: string
  target_term: string
  kind: string
  first_project_name: string | null
}

export type BatchDetail = BatchSummary & {
  projects: BatchDoc[]
  batch_terms: BatchTerm[]
}

const KIND_ORDER = ["person", "institution", "place", "degree", "term"]

const ZIP_FORMATS = ["docx", "pdf", "delivery"] as const
type ZipFormat = (typeof ZIP_FORMATS)[number]
const ZIP_LABELS: Record<ZipFormat, { button: string; file: string; title: string }> = {
  docx: { button: "DOCX ZIP", file: "DOCX", title: "Every finished document as DOCX, in one ZIP" },
  pdf: { button: "PDF ZIP", file: "PDF", title: "Every finished document as PDF, in one ZIP" },
  delivery: {
    button: "Delivery PDFs ZIP",
    file: "Delivery PDF",
    title: "Every finished document as one PDF with its certification page and a copy of the original, in one ZIP",
  },
}
const KIND_LABEL: Record<string, string> = {
  person: "Names",
  institution: "Institutions",
  place: "Places",
  degree: "Degrees",
  term: "Terms",
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

type Props = {
  id: string
  name: string
  summary: Pick<BatchSummary, "documents" | "pages" | "completed" | "failed" | "in_progress" | "terms">
  detail: BatchDetail | null
  expanded: boolean
  highlighted: boolean
  onToggle: () => void
  onNeedDetail: () => void
  onChanged: () => void
  children: ReactNode
}

const BatchGroup = forwardRef<HTMLDivElement, Props>(function BatchGroup(
  { id, name, summary, detail, expanded, highlighted, onToggle, onNeedDetail, onChanged, children },
  ref,
) {
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [termsOpen, setTermsOpen] = useState(false)

  const { documents, pages, completed, failed, in_progress } = summary
  const canAct = completed > 0 && !busy
  const pct = documents ? Math.round((completed / documents) * 100) : 0

  const download = async (format: ZipFormat) => {
    setBusy(`zip:${format}`)
    setNotice(null)
    try {
      const res = await api.get(`/batches/${id}/export.zip`, { params: { format }, responseType: "blob" })
      const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/zip" }))
      const a = document.createElement("a")
      a.href = url
      a.download = `${(name || "batch").replace(/[^\w .-]+/g, "_")} (${ZIP_LABELS[format].file}).zip`
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
      onChanged()
    } catch {
      setNotice("Couldn't update the documents")
    } finally {
      setBusy(null)
    }
  }

  const terms = [...(detail?.batch_terms || [])].sort(
    (a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind),
  )
  const termGroups = KIND_ORDER.map((k) => ({ kind: k, items: terms.filter((t) => t.kind === k) })).filter(
    (g) => g.items.length,
  )

  const actionBtn = "px-3 py-1.5 rounded-full text-xs font-semibold transition whitespace-nowrap"

  return (
    <div
      ref={ref}
      style={{
        borderBottom: "1px solid #f1e8d1",
        boxShadow: highlighted ? "inset 3px 0 0 #0a7870" : undefined,
        background: highlighted ? "#f4faf8" : "#fbf8f1",
      }}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3 px-4 sm:px-5 py-3.5">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className="flex items-center gap-3 min-w-0 flex-1 basis-[240px] text-left"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#6b6558"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="shrink-0 transition-transform"
            style={{ transform: expanded ? "rotate(90deg)" : "none" }}
          >
            <path d="m9 6 6 6-6 6" />
          </svg>
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: "#e1efec", color: "#0a5e58" }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="7" y="3" width="13" height="15" rx="2" />
              <path d="M4 7v12a2 2 0 0 0 2 2h10" />
            </svg>
          </div>
          <div className="min-w-0">
            <div className="font-semibold truncate" style={{ color: "#1f2a2e" }}>
              {name || "Batch"}
            </div>
            <div className="text-xs truncate" style={{ color: "#8a8270" }}>
              Batch · {documents} document{documents === 1 ? "" : "s"} · {pages} page{pages === 1 ? "" : "s"}
            </div>
          </div>
        </button>

        <div className="flex items-center gap-3 shrink-0">
          <div className="w-20 h-1.5 rounded-full overflow-hidden" style={{ background: "#ede3cc" }}>
            <div
              className="h-full rounded-full"
              style={{ width: `${pct}%`, background: pct >= 100 ? "#4a8a3a" : "#0a7870" }}
            />
          </div>
          <div className="text-xs whitespace-nowrap" style={{ color: "#4a4638" }}>
            {completed} of {documents} done
            {in_progress ? <span style={{ color: "#8a8270" }}> · {in_progress} in progress</span> : null}
            {failed ? <span style={{ color: "#b14a3a" }}> · {failed} failed</span> : null}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              if (!termsOpen) onNeedDetail()
              setTermsOpen(!termsOpen)
            }}
            aria-expanded={termsOpen}
            className={actionBtn}
            style={{
              background: termsOpen ? "#e1efec" : "#ffffff",
              color: "#0a5e58",
              border: "1px solid #cfe6e2",
            }}
          >
            Terms{summary.terms ? ` · ${summary.terms}` : ""}
          </button>
          {ZIP_FORMATS.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => download(f)}
              disabled={!canAct}
              title={completed ? ZIP_LABELS[f].title : "No finished documents yet"}
              className={actionBtn}
              style={{
                background: "#ffffff",
                color: "#0a7870",
                border: "1px solid #b7dad4",
                opacity: canAct ? 1 : 0.5,
                cursor: canAct ? "pointer" : "not-allowed",
              }}
            >
              {busy === `zip:${f}` ? "Preparing…" : ZIP_LABELS[f].button}
            </button>
          ))}
          {confirming ? (
            <>
              <button
                type="button"
                onClick={markDelivered}
                disabled={!!busy}
                className={actionBtn}
                style={{ background: "#4a8a3a", color: "#ffffff", border: "1px solid #4a8a3a", opacity: busy ? 0.6 : 1 }}
              >
                {busy === "review" ? "Updating…" : `Confirm ${completed}`}
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className={actionBtn}
                style={{ background: "#ffffff", color: "#4a4638", border: "1px solid #e7ddc5" }}
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              disabled={!canAct}
              title="Set every finished document to Certified"
              className={actionBtn}
              style={{
                background: "#ffffff",
                color: "#2d5a24",
                border: "1px solid #e7ddc5",
                opacity: canAct ? 1 : 0.5,
                cursor: canAct ? "pointer" : "not-allowed",
              }}
            >
              Mark all delivered
            </button>
          )}
        </div>
      </div>

      {notice && (
        <div className="px-4 sm:px-5 pb-3 -mt-1 text-xs" style={{ color: "#4a4638" }}>
          {notice}
        </div>
      )}

      {termsOpen && (
        <div className="mx-4 sm:mx-5 mb-3 rounded-xl px-4 py-3" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
          <div className="text-[11px] font-semibold tracking-[0.14em] mb-2" style={{ color: "#9a9178" }}>
            CONSISTENT ACROSS THIS BATCH
          </div>
          {!detail ? (
            <div className="text-sm" style={{ color: "#8a8270" }}>
              Loading…
            </div>
          ) : termGroups.length === 0 ? (
            <div className="text-sm" style={{ color: "#8a8270" }}>
              {in_progress
                ? "The first document is translating. Its names and terms will be reused in the others."
                : "No shared names or terms recorded for this batch."}
            </div>
          ) : (
            <div className="space-y-2.5">
              {termGroups.map((g) => (
                <div key={g.kind} className="flex flex-wrap items-baseline gap-1.5">
                  <span className="text-xs w-full sm:w-24 shrink-0" style={{ color: "#8a8270" }}>
                    {KIND_LABEL[g.kind] || g.kind}
                  </span>
                  {g.items.map((t) => (
                    <span
                      key={`${t.kind}:${t.source_term}`}
                      className="inline-flex flex-wrap items-center gap-1.5 px-2.5 py-1 rounded-full text-xs max-w-full"
                      style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
                      title={t.first_project_name ? `First used in ${t.first_project_name}` : undefined}
                    >
                      <span className="break-words" style={{ color: "#4a4638" }}>{t.source_term}</span>
                      <span style={{ color: "#9a9178" }}>→</span>
                      <span className="font-medium break-words" style={{ color: "#1f2a2e" }}>
                        {t.target_term}
                      </span>
                    </span>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {expanded && children}
    </div>
  )
})

export default BatchGroup
