"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { api, apiErrorDetail } from "@/lib/api"
import ProPaywall from "@/components/ProPaywall"
import { useFeature } from "@/lib/plan"

type Origin = "machine" | "approved" | "manual" | "import"

type TmEntry = {
  id: string
  source_language: string
  target_language: string
  source_text: string
  translated_text: string
  origin: Origin
  project_id: string | null
  project_name: string | null
  updated_at: string | null
}

type LanguagePair = { source: string; target: string; units: number }

type Summary = {
  total_units: number
  language_pairs: LanguagePair[]
  origins: Record<Origin, number>
  projects: { id: string; name: string; units: number }[]
  source_words_indexed: number
}

type Page = { items: TmEntry[]; total: number; limit: number; offset: number }

const PAGE_SIZE = 50

const ORIGIN_LABELS: Record<Origin, string> = {
  machine: "AI draft",
  approved: "Approved",
  manual: "Manual",
  import: "Imported",
}

const ORIGIN_STYLES: Record<Origin, { background: string; color: string; border: string }> = {
  machine: { background: "#f3ecdb", color: "#8a8270", border: "#e7ddc5" },
  approved: { background: "#cfe6e2", color: "#0a5e58", border: "#b7dad4" },
  manual: { background: "#e3e8f6", color: "#34497a", border: "#cdd6ee" },
  import: { background: "#f6e6d3", color: "#7a4d1f", border: "#ecd3b4" },
}

const LANGUAGES: { code: string; name: string }[] = [
  { code: "it", name: "Italian" },
  { code: "en", name: "English" },
  { code: "en-GB", name: "English (UK)" },
  { code: "en-US", name: "English (US)" },
  { code: "de", name: "German" },
  { code: "fr", name: "French" },
  { code: "es", name: "Spanish" },
  { code: "pt", name: "Portuguese" },
  { code: "pt-BR", name: "Portuguese (Brazil)" },
  { code: "nl", name: "Dutch" },
  { code: "pl", name: "Polish" },
  { code: "ro", name: "Romanian" },
  { code: "ru", name: "Russian" },
  { code: "uk", name: "Ukrainian" },
  { code: "ar", name: "Arabic" },
  { code: "zh", name: "Chinese" },
  { code: "ja", name: "Japanese" },
]

const SOURCE_LANGUAGES = LANGUAGES.filter((l) => !l.code.includes("-"))

function langName(code: string) {
  return LANGUAGES.find((l) => l.code.toLowerCase() === code.toLowerCase())?.name || code
}

function pairLabel(source: string, target: string) {
  return `${source.toUpperCase()} → ${target.toUpperCase()}`
}

function formatNumber(n: number) {
  if (!Number.isFinite(n)) return "0"
  return n.toLocaleString()
}

function downloadName(disposition: string | undefined, fallback: string) {
  const m = /filename="?([^";]+)"?/i.exec(disposition || "")
  return m ? m[1] : fallback
}

export default function TranslationMemoryPage() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [page, setPage] = useState<Page | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [gated, setGated] = useState(false)
  const access = useFeature("terminology_memory")
  const [busy, setBusy] = useState<string | null>(null)

  const [activePair, setActivePair] = useState<string>("all")
  const [origin, setOrigin] = useState<string>("")
  const [projectId, setProjectId] = useState<string>("")
  const [query, setQuery] = useState("")
  const [debouncedQuery, setDebouncedQuery] = useState("")
  const [offset, setOffset] = useState(0)

  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState({ source: "", target: "" })
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [newEntry, setNewEntry] = useState({ source_language: "it", target_language: "en-GB", source_text: "", translated_text: "" })
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQuery(query)
      setOffset(0)
    }, 250)
    return () => clearTimeout(t)
  }, [query])

  const loadSummary = useCallback(async () => {
    try {
      const res = await api.get<Summary>("/tm/summary")
      setSummary(res.data)
    } catch (err: unknown) {
      if ((err as { response?: { status?: number } })?.response?.status === 403) setGated(true)
      else setError(apiErrorDetail(err, "Couldn't load your translation memory. Try refreshing in a moment."))
    }
  }, [])

  const loadEntries = useCallback(async () => {
    const params: Record<string, string | number> = { limit: PAGE_SIZE, offset }
    if (debouncedQuery.trim()) params.q = debouncedQuery.trim()
    if (activePair !== "all") {
      const [s, t] = activePair.split("→")
      params.source = s
      params.target = t
    }
    if (origin) params.origin = origin
    if (projectId) params.project_id = projectId
    try {
      const res = await api.get<Page>("/tm/", { params })
      setPage(res.data)
    } catch (err: unknown) {
      if ((err as { response?: { status?: number } })?.response?.status === 403) setGated(true)
      else setError(apiErrorDetail(err, "Couldn't load entries."))
      setPage(null)
    } finally {
      setLoading(false)
    }
  }, [offset, debouncedQuery, activePair, origin, projectId])

  useEffect(() => {
    if (access === "allowed") void loadSummary()
  }, [loadSummary, access])

  useEffect(() => {
    if (access === "allowed") void loadEntries()
  }, [loadEntries, access])

  const refresh = async () => {
    await Promise.all([loadSummary(), loadEntries()])
  }

  const pickFilter = (fn: () => void) => {
    fn()
    setOffset(0)
  }

  const startEdit = (e: TmEntry) => {
    setConfirmDelete(null)
    setEditing(e.id)
    setDraft({ source: e.source_text, target: e.translated_text })
  }

  const saveEdit = async (e: TmEntry) => {
    const body: Record<string, string> = {}
    if (draft.source.trim() !== e.source_text) body.source_text = draft.source
    if (draft.target.trim() !== e.translated_text) body.translated_text = draft.target
    if (!Object.keys(body).length) {
      setEditing(null)
      return
    }
    try {
      setBusy(`edit:${e.id}`)
      setError(null)
      await api.patch(`/tm/${e.id}`, body)
      setEditing(null)
      await refresh()
    } catch (err: unknown) {
      setError(apiErrorDetail(err, "Couldn't save the entry."))
    } finally {
      setBusy(null)
    }
  }

  const deleteEntry = async (e: TmEntry) => {
    try {
      setBusy(`del:${e.id}`)
      setError(null)
      await api.delete(`/tm/${e.id}`)
      setConfirmDelete(null)
      if (page && page.items.length === 1 && offset > 0) setOffset(Math.max(0, offset - PAGE_SIZE))
      await refresh()
    } catch (err: unknown) {
      setError(apiErrorDetail(err, "Couldn't delete the entry."))
    } finally {
      setBusy(null)
    }
  }

  const addEntry = async () => {
    if (!newEntry.source_text.trim() || !newEntry.translated_text.trim()) {
      setError("Fill in both the source and the translation.")
      return
    }
    try {
      setBusy("add")
      setError(null)
      await api.post("/tm/", newEntry)
      setNewEntry((n) => ({ ...n, source_text: "", translated_text: "" }))
      setAdding(false)
      setNotice("Entry added.")
      await refresh()
    } catch (err: unknown) {
      setError(apiErrorDetail(err, "Couldn't add the entry."))
    } finally {
      setBusy(null)
    }
  }

  const importTmx = async (file: File) => {
    const form = new FormData()
    form.append("file", file)
    try {
      setBusy("import")
      setError(null)
      setNotice(null)
      const res = await api.post<{ imported: number; skipped: number; units: number }>("/tm/import", form)
      const { imported, skipped } = res.data
      setNotice(`Imported ${formatNumber(imported)} entr${imported === 1 ? "y" : "ies"}${skipped ? ` (${formatNumber(skipped)} skipped)` : ""}.`)
      setOffset(0)
      await refresh()
    } catch (err: unknown) {
      setError(apiErrorDetail(err, "Couldn't import that file."))
    } finally {
      setBusy(null)
      if (fileInput.current) fileInput.current.value = ""
    }
  }

  const exportTmx = async () => {
    const params: Record<string, string> = {}
    if (activePair !== "all") {
      const [s, t] = activePair.split("→")
      params.source = s
      params.target = t
    }
    try {
      setBusy("export")
      setError(null)
      const res = await api.get<Blob>("/tm/export", { params, responseType: "blob" })
      const href = window.URL.createObjectURL(res.data)
      const a = document.createElement("a")
      a.href = href
      a.download = downloadName(res.headers["content-disposition"], "translation-memory.tmx")
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(href)
    } catch (err: unknown) {
      setError(apiErrorDetail(err, "Couldn't export the translation memory."))
    } finally {
      setBusy(null)
    }
  }

  const pairs = summary?.language_pairs || []
  const totalUnits = summary?.total_units ?? 0
  const origins = summary?.origins
  const approvedUnits = origins ? origins.approved + origins.manual + origins.import : 0
  const projects = summary?.projects || []
  const entries = page?.items || []
  const total = page?.total ?? 0
  const filtered = !!(debouncedQuery.trim() || activePair !== "all" || origin || projectId)
  const top = pairs[0]

  if (gated || access === "locked") {
    return (
      <ProPaywall
        feature="Translation Memory"
        description="Translation Memory reuses approved segments across every project so your team translates the same phrases the same way every time. Upgrade to Pro to start building your TM."
      />
    )
  }

  return (
    <div className="space-y-6 pb-16">
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        OnlineDocTranslator <span style={{ color: "#cfc6ad" }}>›</span> Assets{" "}
        <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <span style={{ color: "#1f2a2e" }}>Translation Memory</span>
      </div>

      <div className="flex items-end justify-between flex-wrap gap-4">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold tracking-[0.18em] mb-1" style={{ color: "#9a9178" }}>
            TRANSLATION MEMORY
          </div>
          <h1 className="text-[24px] sm:text-[28px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
            {activePair !== "all"
              ? pairLabel(activePair.split("→")[0], activePair.split("→")[1])
              : "Your team's translation memory"}
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            {formatNumber(totalUnits)} translation unit{totalUnits === 1 ? "" : "s"} · {pairs.length} language pair
            {pairs.length === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
          <ActionButton onClick={() => { setAdding((v) => !v); setNotice(null) }} primary>
            {adding ? "Close" : "Add entry"}
          </ActionButton>
          <ActionButton onClick={() => fileInput.current?.click()} disabled={busy === "import"}>
            {busy === "import" ? "Importing…" : "Import TMX"}
          </ActionButton>
          <ActionButton onClick={exportTmx} disabled={busy === "export" || totalUnits === 0}>
            {busy === "export" ? "Exporting…" : "Export TMX"}
          </ActionButton>
          <input
            ref={fileInput}
            type="file"
            accept=".tmx,.xml"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void importTmx(f)
            }}
          />
        </div>
      </div>

      {error && (
        <div className="text-sm rounded-lg px-3 py-2 flex justify-between gap-3" style={{ background: "#f2d4cf", color: "#7a2f24" }}>
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} className="font-semibold">×</button>
        </div>
      )}
      {notice && (
        <div className="text-sm rounded-lg px-3 py-2 flex justify-between gap-3" style={{ background: "#dcefe9", color: "#0a5e58" }}>
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice(null)} className="font-semibold">×</button>
        </div>
      )}

      {adding && (
        <div className="rounded-2xl p-4 sm:p-5 space-y-3" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
          <div className="text-[11px] font-semibold tracking-[0.14em]" style={{ color: "#9a9178" }}>NEW ENTRY</div>
          <div className="flex flex-wrap items-center gap-2">
            <LangSelect
              value={newEntry.source_language}
              options={SOURCE_LANGUAGES}
              onChange={(v) => setNewEntry((n) => ({ ...n, source_language: v }))}
              label="Source language"
            />
            <span style={{ color: "#9a9178" }}>→</span>
            <LangSelect
              value={newEntry.target_language}
              options={LANGUAGES}
              onChange={(v) => setNewEntry((n) => ({ ...n, target_language: v }))}
              label="Target language"
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <TextBox
              value={newEntry.source_text}
              onChange={(v) => setNewEntry((n) => ({ ...n, source_text: v }))}
              placeholder="Source sentence"
            />
            <TextBox
              value={newEntry.translated_text}
              onChange={(v) => setNewEntry((n) => ({ ...n, translated_text: v }))}
              placeholder="Approved translation"
            />
          </div>
          <div className="flex gap-2 justify-end">
            <ActionButton onClick={() => setAdding(false)}>Cancel</ActionButton>
            <ActionButton onClick={addEntry} primary disabled={busy === "add"}>
              {busy === "add" ? "Saving…" : "Save entry"}
            </ActionButton>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <KpiCard
          label="TRANSLATION UNITS"
          value={formatNumber(totalUnits)}
          accent
          sub={totalUnits > 0 ? `${formatNumber(summary?.source_words_indexed ?? 0)} source words` : "Your TM fills up as you translate and approve"}
        />
        <KpiCard
          label="APPROVED BY TRANSLATORS"
          value={formatNumber(approvedUnits)}
          sub={origins ? `${formatNumber(origins.machine)} AI drafts not yet approved` : "—"}
        />
        <KpiCard
          label="TOP LANGUAGE PAIR"
          value={top ? pairLabel(top.source, top.target) : "—"}
          sub={top ? `${formatNumber(top.units)} units` : "No data yet"}
        />
      </div>

      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div
            className="flex items-center gap-2 px-4 py-2 rounded-full w-full sm:w-72"
            style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            <input
              placeholder="Search segments…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1 min-w-0 bg-transparent outline-none text-sm"
              style={{ color: "#1f2a2e" }}
            />
          </div>
          <FilterSelect value={origin} onChange={(v) => pickFilter(() => setOrigin(v))} label="Origin">
            <option value="">All origins</option>
            {(Object.keys(ORIGIN_LABELS) as Origin[]).map((o) => (
              <option key={o} value={o}>
                {ORIGIN_LABELS[o]}
                {origins ? ` (${formatNumber(origins[o])})` : ""}
              </option>
            ))}
          </FilterSelect>
          {projects.length > 0 && (
            <FilterSelect value={projectId} onChange={(v) => pickFilter(() => setProjectId(v))} label="Project">
              <option value="">All projects</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({formatNumber(p.units)})
                </option>
              ))}
            </FilterSelect>
          )}
        </div>

        {pairs.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap">
            <PairPill label="All pairs" count={totalUnits} active={activePair === "all"} onClick={() => pickFilter(() => setActivePair("all"))} />
            {pairs.map((p) => {
              const key = `${p.source}→${p.target}`
              return (
                <PairPill
                  key={key}
                  label={pairLabel(p.source, p.target)}
                  title={`${langName(p.source)} → ${langName(p.target)}`}
                  count={p.units}
                  active={activePair === key}
                  onClick={() => pickFilter(() => setActivePair(key))}
                />
              )
            })}
          </div>
        )}
      </div>

      <div className="rounded-2xl overflow-hidden" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
        <div
          className="hidden md:grid items-center text-[11px] font-semibold tracking-[0.14em] px-5 py-3"
          style={{ gridTemplateColumns: "1.5fr 1.5fr 0.9fr", background: "#faf5ee", borderBottom: "1px solid #f1e8d1", color: "#9a9178" }}
        >
          <div>SOURCE</div>
          <div>TARGET</div>
          <div className="text-right">DETAILS</div>
        </div>

        {loading ? (
          <div className="px-5 py-12 text-center text-sm" style={{ color: "#8a8270" }}>Loading translation memory…</div>
        ) : entries.length === 0 ? (
          <EmptyState filtered={filtered} />
        ) : (
          entries.map((e) => (
            <div key={e.id} className="px-4 sm:px-5 py-4 text-sm" style={{ borderBottom: "1px solid #f4ecd6", color: "#1f2a2e" }}>
              {editing === e.id ? (
                <div className="space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <TextBox value={draft.source} onChange={(v) => setDraft((d) => ({ ...d, source: v }))} placeholder="Source" />
                    <TextBox value={draft.target} onChange={(v) => setDraft((d) => ({ ...d, target: v }))} placeholder="Translation" />
                  </div>
                  <div className="flex gap-2 justify-end">
                    <ActionButton onClick={() => setEditing(null)}>Cancel</ActionButton>
                    <ActionButton onClick={() => saveEdit(e)} primary disabled={busy === `edit:${e.id}`}>
                      {busy === `edit:${e.id}` ? "Saving…" : "Save"}
                    </ActionButton>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-2 md:grid md:items-start" style={{ gridTemplateColumns: "1.5fr 1.5fr 0.9fr" }}>
                  <div className="md:pr-4 leading-relaxed break-words" style={{ color: "#4a4638" }}>{e.source_text}</div>
                  <div className="md:pr-4 leading-relaxed font-medium break-words" style={{ color: "#1f2a2e" }}>{e.translated_text}</div>
                  <div className="flex flex-wrap md:flex-col md:items-end gap-1.5 items-center">
                    <div className="flex gap-1.5 items-center">
                      <OriginBadge origin={e.origin} />
                      <LangChip text={e.source_language} />
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#9a9178" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M5 12h14M13 6l6 6-6 6" />
                      </svg>
                      <LangChip text={e.target_language} />
                    </div>
                    {e.project_name && (
                      <div className="text-[11px] truncate max-w-[14rem]" style={{ color: "#8a8270" }} title={e.project_name}>
                        {e.project_name}
                      </div>
                    )}
                    {confirmDelete === e.id ? (
                      <div className="flex items-center gap-2 text-[12px]">
                        <span style={{ color: "#7a2f24" }}>Delete this entry?</span>
                        <button
                          type="button"
                          className="font-semibold px-2 py-0.5 rounded-md"
                          style={{ background: "#7a2f24", color: "#fff" }}
                          disabled={busy === `del:${e.id}`}
                          onClick={() => deleteEntry(e)}
                        >
                          Delete
                        </button>
                        <button type="button" style={{ color: "#8a8270" }} onClick={() => setConfirmDelete(null)}>
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div className="flex gap-3 text-[12px] font-medium">
                        <button type="button" style={{ color: "#0a7870" }} onClick={() => startEdit(e)}>Edit</button>
                        <button type="button" style={{ color: "#9a5b4e" }} onClick={() => { setEditing(null); setConfirmDelete(e.id) }}>
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))
        )}

        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between gap-3 px-4 sm:px-5 py-3 text-sm" style={{ background: "#faf5ee", color: "#8a8270" }}>
            <span>
              {formatNumber(offset + 1)}–{formatNumber(Math.min(offset + PAGE_SIZE, total))} of {formatNumber(total)}
            </span>
            <div className="flex gap-2">
              <ActionButton onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0}>Previous</ActionButton>
              <ActionButton onClick={() => setOffset(offset + PAGE_SIZE)} disabled={offset + PAGE_SIZE >= total}>Next</ActionButton>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function EmptyState({ filtered }: { filtered: boolean }) {
  return (
    <div className="px-5 py-16 flex flex-col items-center text-center">
      <div className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4" style={{ background: "#f3ecdb", color: "#9a9178" }}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <ellipse cx="12" cy="6" rx="8" ry="3" />
          <path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
          <path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
        </svg>
      </div>
      <div className="text-[16px] font-semibold mb-1" style={{ color: "#1f2a2e" }}>
        {filtered ? "No segments match this filter" : "Your translation memory is empty"}
      </div>
      <div className="text-sm" style={{ color: "#8a8270" }}>
        {filtered
          ? "Try clearing the search or picking a different filter."
          : "Sentences you approve in the editor appear here. You can also add entries or import a TMX file."}
      </div>
    </div>
  )
}

function ActionButton({
  children,
  onClick,
  primary,
  disabled,
}: {
  children: React.ReactNode
  onClick: () => void
  primary?: boolean
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="px-3.5 py-1.5 rounded-full text-sm font-medium transition disabled:opacity-50"
      style={{
        background: primary ? "#0a7870" : "#ffffff",
        color: primary ? "#fff" : "#1f2a2e",
        border: `1px solid ${primary ? "#0a7870" : "#e7ddc5"}`,
      }}
    >
      {children}
    </button>
  )
}

function FilterSelect({
  value,
  onChange,
  label,
  children,
}: {
  value: string
  onChange: (v: string) => void
  label: string
  children: React.ReactNode
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="px-3 py-2 rounded-full text-sm outline-none max-w-full"
      style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#1f2a2e" }}
    >
      {children}
    </select>
  )
}

function LangSelect({
  value,
  options,
  onChange,
  label,
}: {
  value: string
  options: { code: string; name: string }[]
  onChange: (v: string) => void
  label: string
}) {
  return (
    <FilterSelect value={value} onChange={onChange} label={label}>
      {options.map((l) => (
        <option key={l.code} value={l.code}>
          {l.name} ({l.code.toUpperCase()})
        </option>
      ))}
    </FilterSelect>
  )
}

function TextBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={3}
      className="w-full rounded-xl px-3 py-2 text-sm outline-none resize-y"
      style={{ background: "#fdfbf6", border: "1px solid #e7ddc5", color: "#1f2a2e" }}
    />
  )
}

function KpiCard({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div
      className="rounded-2xl p-5"
      style={{
        background: accent ? "#0a7870" : "#ffffff",
        border: accent ? "1px solid #0a645d" : "1px solid #e7ddc5",
        color: accent ? "#fff" : "#1f2a2e",
        boxShadow: "0 1px 2px rgba(30,30,20,0.04)",
      }}
    >
      <div className="text-[11px] font-semibold tracking-[0.14em] mb-2" style={{ color: accent ? "#cfe6e2" : "#9a9178" }}>
        {label}
      </div>
      <div className="text-[28px] font-semibold tracking-tight tabular-nums">{value}</div>
      {sub && (
        <div className="text-xs mt-1" style={{ color: accent ? "#cfe6e2" : "#8a8270" }}>
          {sub}
        </div>
      )}
    </div>
  )
}

function PairPill({
  label,
  title,
  count,
  active,
  onClick,
}: {
  label: string
  title?: string
  count: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
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
        style={{ background: active ? "rgba(255,255,255,0.18)" : "#f3ecdb", color: active ? "#fff" : "#8a8270" }}
      >
        {count.toLocaleString()}
      </span>
    </button>
  )
}

function OriginBadge({ origin }: { origin: Origin }) {
  const s = ORIGIN_STYLES[origin] || ORIGIN_STYLES.machine
  return (
    <span
      className="inline-flex items-center text-[10px] font-semibold px-1.5 py-0.5 rounded-md whitespace-nowrap"
      style={{ background: s.background, color: s.color, border: `1px solid ${s.border}` }}
    >
      {ORIGIN_LABELS[origin] || origin}
    </span>
  )
}

function LangChip({ text }: { text: string }) {
  return (
    <span
      className="inline-flex items-center text-[10px] font-semibold tracking-[0.04em] px-1.5 py-0.5 rounded-md uppercase"
      style={{ background: "#cfe6e2", color: "#0a5e58", border: "1px solid #b7dad4" }}
      title={langName(text)}
    >
      {text}
    </span>
  )
}
