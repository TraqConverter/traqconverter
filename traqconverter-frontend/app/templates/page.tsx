"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"

type Template = {
  id: string
  title: string
  document_type: string
  issuing_authority: string
  country: string
  target_language: string
  target_language_name: string
  use_count: number
  last_used_at: string | null
  updated_at: string | null
}

type Term = {
  id: string
  source_term: string
  target_term: string
  source_language: string
  target_language: string
}

type Summary = {
  templates: number
  learned_terms: number
  recent_terms: Term[]
}

const COLUMNS = "1.8fr 1.3fr 0.8fr 0.5fr 0.9fr 0.9fr"

function formatDate(iso: string | null) {
  if (!iso) return "—"
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })
}

function capitalise(s: string) {
  return s ? s[0].toUpperCase() + s.slice(1) : "—"
}

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const [list, sum] = await Promise.all([api.get("/templates"), api.get("/learning/summary")])
        setTemplates(list.data || [])
        setSummary(sum.data)
      } catch (err) {
        setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Couldn't load templates")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const remove = async (id: string) => {
    setBusy(id)
    setError(null)
    try {
      await api.delete(`/templates/${id}`)
      setTemplates((ts) => ts.filter((t) => t.id !== id))
      setSummary((s) => (s ? { ...s, templates: Math.max(0, s.templates - 1) } : s))
      setConfirming(null)
    } catch {
      setError("Couldn't delete the template")
    } finally {
      setBusy(null)
    }
  }

  const rejectTerm = async (id: string) => {
    setBusy(id)
    setError(null)
    try {
      await api.post(`/learning/terms/${id}/reject`)
      setSummary((s) =>
        s
          ? { ...s, learned_terms: Math.max(0, s.learned_terms - 1), recent_terms: s.recent_terms.filter((t) => t.id !== id) }
          : s
      )
    } catch {
      setError("Couldn't remove the term")
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-6 pb-16">
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span> Assets{" "}
        <span style={{ color: "#cfc6ad" }}>›</span> <span style={{ color: "#1f2a2e" }}>Templates</span>
      </div>

      <div>
        <div className="text-[11px] font-semibold tracking-[0.18em] mb-1" style={{ color: "#9a9178" }}>
          TEMPLATES
        </div>
        <h1 className="text-[28px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
          Your team&apos;s templates
        </h1>
        <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
          Finished documents are saved here. The next document of the same kind is built from them.
        </p>
      </div>

      {error && (
        <div className="text-sm rounded-lg px-3 py-2" style={{ background: "#f2d4cf", color: "#7a2f24" }}>
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Kpi label="TEMPLATES" value={summary?.templates ?? 0} accent />
        <Kpi label="LEARNED TERMS" value={summary?.learned_terms ?? 0} />
      </div>

      <div className="rounded-2xl overflow-x-auto" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
        <div className="min-w-[720px]">
          <div
            className="grid items-center text-[11px] font-semibold tracking-[0.14em] px-5 py-3"
            style={{ gridTemplateColumns: COLUMNS, background: "#faf5ee", borderBottom: "1px solid #f1e8d1", color: "#9a9178" }}
          >
            <div>TITLE</div>
            <div>DOCUMENT TYPE</div>
            <div>TARGET</div>
            <div className="text-right">USES</div>
            <div className="text-right">LAST USED</div>
            <div />
          </div>

          {loading ? (
            <div className="px-5 py-12 text-center text-sm" style={{ color: "#8a8270" }}>
              Loading templates…
            </div>
          ) : templates.length === 0 ? (
            <div className="px-5 py-16 text-center">
              <div className="text-[16px] font-semibold mb-1" style={{ color: "#1f2a2e" }}>
                No templates yet
              </div>
              <div className="text-sm" style={{ color: "#8a8270" }}>
                Export or certify a translation, or use Save as template in the editor.
              </div>
            </div>
          ) : (
            templates.map((t) => (
              <div
                key={t.id}
                className="grid items-center px-5 py-4 text-sm"
                style={{ gridTemplateColumns: COLUMNS, borderBottom: "1px solid #f4ecd6", color: "#1f2a2e" }}
              >
                <div className="pr-4 font-medium">{t.title}</div>
                <div className="pr-4" style={{ color: "#4a4638" }}>
                  {capitalise(t.document_type)}
                  {t.country ? <span style={{ color: "#9a9178" }}> · {t.country}</span> : null}
                </div>
                <div>
                  <span
                    className="inline-flex items-center text-[10px] font-semibold tracking-[0.04em] px-1.5 py-0.5 rounded-md uppercase"
                    style={{ background: "#cfe6e2", color: "#0a5e58", border: "1px solid #b7dad4" }}
                    title={t.target_language_name}
                  >
                    {t.target_language}
                  </span>
                </div>
                <div className="text-right tabular-nums">{t.use_count}</div>
                <div className="text-right" style={{ color: "#8a8270" }}>{formatDate(t.last_used_at)}</div>
                <div className="flex justify-end gap-1.5">
                  {confirming === t.id ? (
                    <>
                      <button
                        type="button"
                        onClick={() => remove(t.id)}
                        disabled={busy === t.id}
                        className="text-xs font-medium px-2.5 py-1 rounded-full"
                        style={{ background: "#7a2f24", color: "#fff", opacity: busy === t.id ? 0.6 : 1 }}
                      >
                        Delete
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirming(null)}
                        className="text-xs px-2.5 py-1 rounded-full"
                        style={{ border: "1px solid #e7ddc5", color: "#4a4638" }}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirming(t.id)}
                      className="text-xs px-2.5 py-1 rounded-full transition hover:bg-[#faf5ee]"
                      style={{ border: "1px solid #e7ddc5", color: "#4a4638" }}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {summary && summary.recent_terms.length > 0 && (
        <div className="rounded-2xl p-5" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
          <div className="text-[11px] font-semibold tracking-[0.14em] mb-3" style={{ color: "#9a9178" }}>
            RECENTLY LEARNED TERMS
          </div>
          <div className="flex flex-wrap gap-1.5">
            {summary.recent_terms.map((t) => (
              <span
                key={t.id}
                className="inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 rounded-full text-xs"
                style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
              >
                <span style={{ color: "#4a4638" }}>{t.source_term}</span>
                <span style={{ color: "#9a9178" }}>→</span>
                <span className="font-medium" style={{ color: "#1f2a2e" }}>{t.target_term}</span>
                <button
                  type="button"
                  aria-label={`Reject ${t.source_term}`}
                  title="Reject"
                  disabled={busy === t.id}
                  onClick={() => rejectTerm(t.id)}
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
    </div>
  )
}

function Kpi({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div
      className="rounded-2xl p-5"
      style={{
        background: accent ? "#0a7870" : "#ffffff",
        border: accent ? "1px solid #0a645d" : "1px solid #e7ddc5",
        color: accent ? "#fff" : "#1f2a2e",
      }}
    >
      <div className="text-[11px] font-semibold tracking-[0.14em] mb-2" style={{ color: accent ? "#cfe6e2" : "#9a9178" }}>
        {label}
      </div>
      <div className="text-[28px] font-semibold tracking-tight tabular-nums">{value.toLocaleString()}</div>
    </div>
  )
}
