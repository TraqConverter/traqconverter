"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { api } from "@/lib/api"
import { useFeature } from "@/lib/plan"

type Term = {
  id: string
  source_term: string
  target_term: string
  origin: string
}

type DocProfile = {
  document_type?: string
  issuing_authority?: string
  country?: string
}

type Learning = {
  template_used: { id: string; title: string; created_at: string | null } | null
  saved_as_template: { id: string; title: string } | null
  doc_profile: DocProfile | null
  terms_applied: Term[]
  terms_learned_here: Term[]
}

const POLL_MS = 10_000

function formatDate(iso: string | null) {
  if (!iso) return ""
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })
}

function capitalise(s: string) {
  return s ? s[0].toUpperCase() + s.slice(1) : s
}

export default function LearningPanel({ projectId }: { projectId: string }) {
  const [data, setData] = useState<Learning | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const templates = useFeature("templates")
  const terms = useFeature("glossaries")
  const ready = templates !== "loading" && terms !== "loading"
  const locked = templates === "locked" && terms === "locked"

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/projects/${projectId}/learning`)
      setData(res.data)
      setLoadFailed(false)
    } catch {
      // Polling keeps the last good state; only a panel that never loaded says so.
      setLoadFailed(true)
    }
  }, [projectId])

  useEffect(() => {
    if (!ready || locked) return
    load()
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [load, ready, locked])

  const reject = async (term: Term) => {
    setBusy(term.id)
    setError(null)
    try {
      await api.post(`/learning/terms/${term.id}/reject`)
      setData((d) =>
        d ? { ...d, terms_learned_here: d.terms_learned_here.filter((t) => t.id !== term.id) } : d
      )
    } catch {
      setError("Couldn't remove the term")
    } finally {
      setBusy(null)
    }
  }

  const saveTemplate = async () => {
    setBusy("template")
    setError(null)
    try {
      await api.post(`/projects/${projectId}/template`)
      await load()
    } catch (err) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Couldn't save the template")
    } finally {
      setBusy(null)
    }
  }

  if (locked) {
    return (
      <div
        className="rounded-2xl p-4 space-y-2 text-sm"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#1f2a2e" }}
      >
        <div className="flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.14em]" style={{ color: "#9a9178" }}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="4" y="11" width="16" height="10" rx="2" />
            <path d="M8 11V7a4 4 0 0 1 8 0v4" />
          </svg>
          LEARNING
        </div>
        <p className="text-xs leading-relaxed" style={{ color: "#6b6558" }}>
          Templates come with Basic: the next document of the same kind is built from this one. Pro adds the
          translation memory and the team terms learned from your edits.
        </p>
        <Link href="/billing" className="inline-block text-xs font-semibold" style={{ color: "#0a7870" }}>
          See plans
        </Link>
      </div>
    )
  }

  if (!data) {
    if (!loadFailed) return null
    return (
      <div
        className="rounded-2xl p-4 text-xs"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#6b6558" }}
      >
        Learning details couldn&apos;t be loaded. They&apos;ll appear here once the connection is back.
      </div>
    )
  }

  const profile = data.doc_profile || {}
  const docLine = [
    capitalise(profile.document_type || ""),
    profile.issuing_authority,
    profile.country,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <div
      className="rounded-2xl p-4 space-y-3 text-sm"
      style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#1f2a2e" }}
    >
      <div className="text-[11px] font-semibold tracking-[0.14em]" style={{ color: "#9a9178" }}>
        LEARNING
      </div>

      {data.template_used && (
        <div
          className="rounded-lg px-3 py-2 flex items-center gap-2"
          style={{ background: "#e1efec", color: "#0a5e58" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="4" y="3" width="16" height="18" rx="2" />
            <path d="M8 8h8M8 12h8M8 16h5" />
          </svg>
          <span>
            Built from your template: <span className="font-semibold">{data.template_used.title}</span>
            {data.template_used.created_at ? ` · ${formatDate(data.template_used.created_at)}` : ""}
          </span>
        </div>
      )}

      {docLine && (
        <div>
          <div className="text-xs" style={{ color: "#8a8270" }}>Document type</div>
          <div className="font-medium">{docLine}</div>
        </div>
      )}

      {data.terms_applied.length > 0 && (
        <div className="text-xs" style={{ color: "#8a8270" }}>
          {data.terms_applied.length} team term{data.terms_applied.length === 1 ? "" : "s"} applied
        </div>
      )}

      {data.terms_learned_here.length > 0 && (
        <div>
          <div className="text-xs mb-1.5" style={{ color: "#8a8270" }}>Learned from your edits</div>
          <div className="flex flex-wrap gap-1.5">
            {data.terms_learned_here.map((t) => (
              <span
                key={t.id}
                className="inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 rounded-full text-xs"
                style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
              >
                <span style={{ color: "#4a4638" }}>{t.source_term}</span>
                <span style={{ color: "#9a9178" }}>→</span>
                <span className="font-medium">{t.target_term}</span>
                <button
                  type="button"
                  aria-label={`Reject ${t.source_term}`}
                  title="Reject"
                  disabled={busy === t.id}
                  onClick={() => reject(t)}
                  className="w-5 h-5 rounded-full flex items-center justify-center transition hover:bg-[#f2d4cf]"
                  style={{ color: "#9a9178" }}
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                    <path d="M6 6l12 12M18 6 6 18" />
                  </svg>
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between pt-1">
        {data.saved_as_template ? (
          <span className="text-xs" style={{ color: "#0a5e58" }}>Saved as template</span>
        ) : (
          <button
            type="button"
            onClick={saveTemplate}
            disabled={busy === "template"}
            className="text-xs font-medium px-3 py-1.5 rounded-full transition"
            style={{ background: "#0a7870", color: "#fff", opacity: busy === "template" ? 0.6 : 1 }}
          >
            {busy === "template" ? "Saving…" : "Save as template"}
          </button>
        )}
        {error && <span className="text-xs" style={{ color: "#7a2f24" }}>{error}</span>}
      </div>
    </div>
  )
}
