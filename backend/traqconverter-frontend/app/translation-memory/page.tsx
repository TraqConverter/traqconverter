"use client"

import { useEffect, useMemo, useState } from "react"
import { api } from "@/lib/api"
import ProPaywall from "@/components/ProPaywall"

// ============================================================
// TRANSLATION MEMORY — ESPRESSO LOOK
// Wired to real backend:
//   GET /tm/summary  → { total_units, language_pairs[], source_words_indexed }
//   GET /tm/?source=&target=&q=&limit=  → [ { id, source_language, target_language, source_text, translated_text } ]
//
// The TranslationMemory table doesn't track contributors, dates or use counts,
// so this page only renders fields that actually exist. No placeholder columns.
// ============================================================

type TmEntry = {
  id: string
  source_language: string
  target_language: string
  source_text: string
  translated_text: string
}

type LanguagePair = {
  source: string
  target: string
  units: number
}

type Summary = {
  total_units: number
  language_pairs: LanguagePair[]
  source_words_indexed: number
}

function formatNumber(n: number) {
  if (!Number.isFinite(n)) return "0"
  return n.toLocaleString()
}

function formatK(n: number) {
  if (!n) return "0"
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`
  return String(n)
}

// "English" / "en" / "en-GB" → tidy chip text
function toLangCode(raw?: string) {
  if (!raw) return "—"
  const s = raw.trim()
  if (s.length <= 5 && /^[a-z]/i.test(s)) return s.toLowerCase()
  const map: Record<string, string> = {
    english: "en",
    spanish: "es",
    french: "fr",
    german: "de",
    italian: "it",
    portuguese: "pt",
    dutch: "nl",
    polish: "pl",
    chinese: "zh",
    japanese: "ja",
    arabic: "ar",
    swedish: "sv",
  }
  return map[s.toLowerCase()] || s.slice(0, 2).toLowerCase()
}

export default function TranslationMemoryPage() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [entries, setEntries] = useState<TmEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activePair, setActivePair] = useState<string>("all")
  const [query, setQuery] = useState("")
  const [debouncedQuery, setDebouncedQuery] = useState("")
  const [gated, setGated] = useState(false)

  useEffect(() => {
    fetchAll()
  }, [])

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 250)
    return () => clearTimeout(t)
  }, [query])

  // Re-fetch when filters change
  useEffect(() => {
    if (loading) return
    fetchEntries(debouncedQuery, activePair)
  }, [debouncedQuery, activePair])

  const fetchAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [sumRes, listRes] = await Promise.all([
        api.get("/tm/summary"),
        api.get("/tm/", { params: { limit: 200 } }),
      ])
      setSummary(sumRes.data)
      setEntries(listRes.data || [])
    } catch (err: any) {
      console.error("TM ERROR:", err)
      // 403 = plan doesn't include this feature → render the paywall.
      if (err?.response?.status === 403) {
        setGated(true)
      } else {
        setError(
          err?.response?.data?.detail ||
            "Couldn't load your translation memory — try refreshing in a moment."
        )
      }
      setSummary(null)
      setEntries([])
    } finally {
      setLoading(false)
    }
  }

  const fetchEntries = async (q: string, pair: string) => {
    try {
      setSearching(true)
      const params: Record<string, string | number> = { limit: 200 }
      if (q.trim()) params.q = q.trim()
      if (pair !== "all") {
        const [s, t] = pair.split("→")
        if (s) params.source = s
        if (t) params.target = t
      }
      const res = await api.get("/tm/", { params })
      setEntries(res.data || [])
    } catch (err: any) {
      console.error("TM SEARCH ERROR:", err)
      setEntries([])
    } finally {
      setSearching(false)
    }
  }

  const pairs = summary?.language_pairs || []
  const totalUnits = summary?.total_units ?? 0
  const wordsIndexed = summary?.source_words_indexed ?? 0

  const visibleHeader = useMemo(() => {
    if (activePair === "all") return null
    const [src, tgt] = activePair.split("→")
    return { source: src, target: tgt }
  }, [activePair])

  if (gated) {
    return (
      <ProPaywall
        feature="Translation Memory"
        description="Translation Memory reuses approved segments across every project so your team translates the same phrases the same way every time. Upgrade to Pro to start building your TM."
      />
    )
  }

  return (
    <div className="space-y-6 pb-16">
      {/* BREADCRUMB */}
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span> Assets{" "}
        <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <span style={{ color: "#1f2a2e" }}>Translation Memory</span>
      </div>

      {/* HEADER */}
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div
            className="text-[11px] font-semibold tracking-[0.18em] mb-1"
            style={{ color: "#9a9178" }}
          >
            TRANSLATION MEMORY
          </div>
          <h1
            className="text-[28px] font-semibold tracking-tight"
            style={{ color: "#1f2a2e" }}
          >
            {visibleHeader
              ? `${toLangCode(visibleHeader.source).toUpperCase()} ↔ ${toLangCode(
                  visibleHeader.target
                ).toUpperCase()}`
              : "Your team's translation memory"}
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            {totalUnits.toLocaleString()} translation unit
            {totalUnits === 1 ? "" : "s"} · {pairs.length} language pair
            {pairs.length === 1 ? "" : "s"}
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
              placeholder="Search segments…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: "#1f2a2e" }}
            />
          </div>
        </div>
      </div>

      {error && (
        <div
          className="text-sm rounded-lg px-3 py-2"
          style={{ background: "#f2d4cf", color: "#7a2f24" }}
        >
          {error}
        </div>
      )}

      {/* KPI CARDS — only fields that actually exist on the model */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <KpiCard
          label="TRANSLATION UNITS"
          value={formatNumber(totalUnits)}
          accent
          sub={
            totalUnits > 0
              ? `Across ${pairs.length} language pair${pairs.length === 1 ? "" : "s"}`
              : "Your TM will populate as you approve segments"
          }
        />
        <KpiCard
          label="SOURCE WORDS INDEXED"
          value={formatK(wordsIndexed)}
          sub="Total words across all source segments"
        />
        <KpiCard
          label="TOP LANGUAGE PAIR"
          value={
            pairs.length === 0
              ? "—"
              : (() => {
                  const top = [...pairs].sort((a, b) => b.units - a.units)[0]
                  return `${toLangCode(top.source).toUpperCase()} → ${toLangCode(
                    top.target
                  ).toUpperCase()}`
                })()
          }
          sub={
            pairs.length === 0
              ? "No data yet"
              : `${[...pairs]
                  .sort((a, b) => b.units - a.units)[0]
                  .units.toLocaleString()} units`
          }
        />
      </div>

      {/* LANGUAGE PAIR FILTER PILLS */}
      {pairs.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <PairPill
            label="All pairs"
            count={totalUnits}
            active={activePair === "all"}
            onClick={() => setActivePair("all")}
          />
          {pairs.map((p) => {
            const key = `${p.source}→${p.target}`
            return (
              <PairPill
                key={key}
                label={`${toLangCode(p.source).toUpperCase()} → ${toLangCode(
                  p.target
                ).toUpperCase()}`}
                count={p.units}
                active={activePair === key}
                onClick={() => setActivePair(key)}
              />
            )
          })}
        </div>
      )}

      {/* TABLE */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
      >
        <div
          className="grid items-center text-[11px] font-semibold tracking-[0.14em] px-5 py-3"
          style={{
            gridTemplateColumns: "1.6fr 1.6fr 0.9fr",
            background: "#faf5ee",
            borderBottom: "1px solid #f1e8d1",
            color: "#9a9178",
          }}
        >
          <div>SOURCE</div>
          <div>TARGET</div>
          <div className="text-right">PAIR</div>
        </div>

        {loading || searching ? (
          <div
            className="px-5 py-12 text-center text-sm"
            style={{ color: "#8a8270" }}
          >
            {loading ? "Loading translation memory…" : "Searching…"}
          </div>
        ) : entries.length === 0 ? (
          <div className="px-5 py-16 flex flex-col items-center text-center">
            <div
              className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4"
              style={{ background: "#f3ecdb", color: "#9a9178" }}
            >
              <svg
                width="22"
                height="22"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <ellipse cx="12" cy="6" rx="8" ry="3" />
                <path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
                <path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
              </svg>
            </div>
            <div
              className="text-[16px] font-semibold mb-1"
              style={{ color: "#1f2a2e" }}
            >
              {query.trim() || activePair !== "all"
                ? "No segments match this filter"
                : "Your translation memory is empty"}
            </div>
            <div className="text-sm" style={{ color: "#8a8270" }}>
              {query.trim() || activePair !== "all"
                ? "Try clearing the search or picking a different language pair."
                : "Approved segments from your projects will appear here."}
            </div>
          </div>
        ) : (
          entries.map((e) => (
            <div
              key={e.id}
              className="grid items-start px-5 py-4 text-sm"
              style={{
                gridTemplateColumns: "1.6fr 1.6fr 0.9fr",
                borderBottom: "1px solid #f4ecd6",
                color: "#1f2a2e",
              }}
            >
              <div className="pr-4 leading-relaxed" style={{ color: "#4a4638" }}>
                {e.source_text}
              </div>
              <div
                className="pr-4 leading-relaxed font-medium"
                style={{ color: "#1f2a2e" }}
              >
                {e.translated_text}
              </div>
              <div className="flex justify-end gap-1.5 items-center pt-0.5">
                <LangChip text={toLangCode(e.source_language)} />
                <svg
                  width="11"
                  height="11"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#9a9178"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
                <LangChip text={toLangCode(e.target_language)} />
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ============================================================
// SUBCOMPONENTS
// ============================================================

function KpiCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub?: string
  accent?: boolean
}) {
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
      <div
        className="text-[11px] font-semibold tracking-[0.14em] mb-2"
        style={{ color: accent ? "#cfe6e2" : "#9a9178" }}
      >
        {label}
      </div>
      <div className="text-[28px] font-semibold tracking-tight tabular-nums">
        {value}
      </div>
      {sub && (
        <div
          className="text-xs mt-1"
          style={{ color: accent ? "#cfe6e2" : "#8a8270" }}
        >
          {sub}
        </div>
      )}
    </div>
  )
}

function PairPill({
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

function LangChip({ text }: { text: string }) {
  return (
    <span
      className="inline-flex items-center text-[10px] font-semibold tracking-[0.04em] px-1.5 py-0.5 rounded-md uppercase"
      style={{
        background: "#cfe6e2",
        color: "#0a5e58",
        border: "1px solid #b7dad4",
      }}
    >
      {text}
    </span>
  )
}
