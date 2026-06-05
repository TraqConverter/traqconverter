"use client"

import { useEffect, useMemo, useState } from "react"
import { api } from "@/lib/api"
import ProPaywall from "@/components/ProPaywall"

// ============================================================
// GLOSSARY — ESPRESSO LOOK
// Wired to real backend:
//   GET    /glossary
//   POST   /glossary  { source_language, target_language, source_term, target_term, notes? }
//   PATCH  /glossary/{id}  { ...partial }
//   DELETE /glossary/{id}
//
// The Glossary model now stores: id, source/target language, source/target term,
// notes (free-form), usage_count (auto-incremented when the AI translation
// service applies the term during a batch).
// ============================================================

type Term = {
  id: string
  source_language: string
  target_language: string
  source_term: string
  target_term: string
  notes: string | null
  usage_count: number
}

const COMMON_LANGUAGES = [
  "English",
  "Spanish",
  "French",
  "German",
  "Italian",
  "Portuguese",
  "Dutch",
  "Polish",
  "Chinese",
  "Japanese",
  "Arabic",
  "Swedish",
]

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

export default function GlossaryPage() {
  const [terms, setTerms] = useState<Term[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [activePair, setActivePair] = useState<string>("all")
  const [query, setQuery] = useState("")

  // Add term modal/inline form state
  const [showAdd, setShowAdd] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [sourceTerm, setSourceTerm] = useState("")
  const [targetTerm, setTargetTerm] = useState("")
  const [sourceLang, setSourceLang] = useState("English")
  const [targetLang, setTargetLang] = useState("Spanish")
  const [notes, setNotes] = useState("")
  const [gated, setGated] = useState(false)

  useEffect(() => {
    fetchTerms()
  }, [])

  const resetForm = () => {
    setEditingId(null)
    setSourceTerm("")
    setTargetTerm("")
    setSourceLang("English")
    setTargetLang("Spanish")
    setNotes("")
  }

  const startEdit = (t: Term) => {
    setEditingId(t.id)
    setSourceTerm(t.source_term)
    setTargetTerm(t.target_term)
    setSourceLang(t.source_language)
    setTargetLang(t.target_language)
    setNotes(t.notes || "")
    setShowAdd(true)
    setError(null)
  }

  const fetchTerms = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await api.get("/glossary")
      setTerms(res.data || [])
    } catch (err: any) {
      console.error("GLOSSARY ERROR:", err)
      if (err?.response?.status === 403) {
        setGated(true)
      } else {
        setError(
          err?.response?.data?.detail ||
            "Couldn't load your glossary — try refreshing in a moment."
        )
      }
      setTerms([])
    } finally {
      setLoading(false)
    }
  }

  const saveTerm = async () => {
    if (!sourceTerm.trim() || !targetTerm.trim()) {
      setError("Both source and target terms are required.")
      return
    }
    try {
      setBusy(editingId ? `edit:${editingId}` : "add")
      setError(null)
      const payload = {
        source_language: sourceLang,
        target_language: targetLang,
        source_term: sourceTerm.trim(),
        target_term: targetTerm.trim(),
        notes: notes.trim() ? notes.trim() : null,
      }
      if (editingId) {
        await api.patch(`/glossary/${editingId}`, payload)
      } else {
        await api.post("/glossary", payload)
      }
      resetForm()
      setShowAdd(false)
      await fetchTerms()
    } catch (err: any) {
      console.error("SAVE GLOSSARY ERROR:", err)
      setError(
        err?.response?.data?.detail ||
          "Couldn't save the term. Please try again."
      )
    } finally {
      setBusy(null)
    }
  }

  const deleteTerm = async (id: string) => {
    if (!confirm("Delete this glossary term?")) return
    try {
      setBusy(`del:${id}`)
      await api.delete(`/glossary/${id}`)
      setTerms((t) => t.filter((x) => x.id !== id))
    } catch (err: any) {
      console.error("DELETE GLOSSARY ERROR:", err)
      setError(
        err?.response?.data?.detail || "Couldn't delete that term."
      )
    } finally {
      setBusy(null)
    }
  }

  // Group by language pair to drive filter pills
  const pairs = useMemo(() => {
    const counts = new Map<string, number>()
    for (const t of terms) {
      const key = `${t.source_language}→${t.target_language}`
      counts.set(key, (counts.get(key) || 0) + 1)
    }
    return Array.from(counts.entries())
      .map(([key, units]) => {
        const [s, t] = key.split("→")
        return { key, source: s, target: t, units }
      })
      .sort((a, b) => b.units - a.units)
  }, [terms])

  const visible = useMemo(() => {
    let list = terms
    if (activePair !== "all") {
      list = list.filter(
        (t) => `${t.source_language}→${t.target_language}` === activePair
      )
    }
    if (query.trim()) {
      const q = query.trim().toLowerCase()
      list = list.filter(
        (t) =>
          t.source_term.toLowerCase().includes(q) ||
          t.target_term.toLowerCase().includes(q)
      )
    }
    return list
  }, [terms, activePair, query])

  const visiblePairLabel = useMemo(() => {
    if (activePair === "all") return null
    const [s, t] = activePair.split("→")
    return { source: s, target: t }
  }, [activePair])

  if (gated) {
    return (
      <ProPaywall
        feature="Glossary"
        description="Lock approved terminology so every translation uses the same wording for medications, legal terms or product names. Upgrade to Pro to start your team glossary."
      />
    )
  }

  return (
    <div className="space-y-6 pb-16">
      {/* BREADCRUMB */}
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span> Assets{" "}
        <span style={{ color: "#cfc6ad" }}>›</span>{" "}
        <span style={{ color: "#1f2a2e" }}>Glossary</span>
      </div>

      {/* HEADER */}
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div
            className="text-[11px] font-semibold tracking-[0.18em] mb-1"
            style={{ color: "#9a9178" }}
          >
            GLOSSARY
          </div>
          <h1
            className="text-[28px] font-semibold tracking-tight"
            style={{ color: "#1f2a2e" }}
          >
            {visiblePairLabel
              ? `${toLangCode(visiblePairLabel.source).toUpperCase()} ↔ ${toLangCode(
                  visiblePairLabel.target
                ).toUpperCase()}`
              : "Your team's glossary"}
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            {terms.length.toLocaleString()} term{terms.length === 1 ? "" : "s"} ·{" "}
            {pairs.length} language pair{pairs.length === 1 ? "" : "s"}
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
              placeholder="Search terms…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: "#1f2a2e" }}
            />
          </div>
          <button
            type="button"
            onClick={() => {
              if (showAdd) {
                setShowAdd(false)
                resetForm()
              } else {
                resetForm()
                setShowAdd(true)
              }
              setError(null)
            }}
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
            {showAdd ? "Close" : "Add term"}
          </button>
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

      {/* ADD TERM PANEL */}
      {showAdd && (
        <div
          className="rounded-2xl p-5"
          style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}
        >
          <div
            className="text-[11px] font-semibold tracking-[0.14em] mb-4"
            style={{ color: "#9a9178" }}
          >
            {editingId ? "EDIT TERM" : "ADD A NEW TERM"}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
            <FieldGroup label="SOURCE LANGUAGE">
              <LangSelect value={sourceLang} onChange={setSourceLang} />
            </FieldGroup>
            <FieldGroup label="TARGET LANGUAGE">
              <LangSelect value={targetLang} onChange={setTargetLang} />
            </FieldGroup>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
            <FieldGroup label="SOURCE TERM">
              <input
                value={sourceTerm}
                onChange={(e) => setSourceTerm(e.target.value)}
                placeholder="e.g. informed consent"
                className="bg-transparent outline-none text-sm w-full"
                style={{ color: "#1f2a2e" }}
              />
            </FieldGroup>
            <FieldGroup label="TARGET TERM">
              <input
                value={targetTerm}
                onChange={(e) => setTargetTerm(e.target.value)}
                placeholder="e.g. consenso informato"
                className="bg-transparent outline-none text-sm w-full"
                style={{ color: "#1f2a2e" }}
              />
            </FieldGroup>
          </div>
          <div className="mb-4">
            <div
              className="text-[11px] font-semibold tracking-[0.14em] mb-2"
              style={{ color: "#9a9178" }}
            >
              NOTES
              <span className="ml-1 font-normal lowercase tracking-normal" style={{ color: "#cfc6ad" }}>
                · optional
              </span>
            </div>
            <div
              className="px-4 py-2.5 rounded-xl"
              style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
            >
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="When to use it, register, regulatory caveats, references…"
                rows={2}
                className="bg-transparent outline-none text-sm w-full resize-none leading-relaxed"
                style={{ color: "#1f2a2e" }}
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setShowAdd(false)
                resetForm()
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
              onClick={saveTerm}
              disabled={
                busy === "add" ||
                busy === `edit:${editingId}` ||
                !sourceTerm.trim() ||
                !targetTerm.trim()
              }
              className="px-4 py-2 rounded-full text-sm font-semibold transition"
              style={{
                background:
                  busy === "add" ||
                  busy === `edit:${editingId}` ||
                  !sourceTerm.trim() ||
                  !targetTerm.trim()
                    ? "#9bc9c5"
                    : "#0a7870",
                color: "#fff",
                cursor:
                  busy === "add" ||
                  busy === `edit:${editingId}` ||
                  !sourceTerm.trim() ||
                  !targetTerm.trim()
                    ? "not-allowed"
                    : "pointer",
              }}
            >
              {busy === "add" || busy === `edit:${editingId}`
                ? "Saving…"
                : editingId
                ? "Save changes"
                : "Save term"}
            </button>
          </div>
        </div>
      )}

      {/* LANGUAGE PAIR PILLS */}
      {pairs.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <PairPill
            label="All pairs"
            count={terms.length}
            active={activePair === "all"}
            onClick={() => setActivePair("all")}
          />
          {pairs.map((p) => (
            <PairPill
              key={p.key}
              label={`${toLangCode(p.source).toUpperCase()} → ${toLangCode(
                p.target
              ).toUpperCase()}`}
              count={p.units}
              active={activePair === p.key}
              onClick={() => setActivePair(p.key)}
            />
          ))}
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
            gridTemplateColumns:
              "minmax(180px,1.3fr) minmax(180px,1.3fr) minmax(220px,1.5fr) 0.9fr 0.8fr 90px",
            background: "#faf5ee",
            borderBottom: "1px solid #f1e8d1",
            color: "#9a9178",
          }}
        >
          <div>SOURCE TERM</div>
          <div>TARGET TERM</div>
          <div>NOTES</div>
          <div className="text-right">PAIR</div>
          <div className="text-right">USAGE</div>
          <div />
        </div>

        {loading ? (
          <div
            className="px-5 py-12 text-center text-sm"
            style={{ color: "#8a8270" }}
          >
            Loading glossary…
          </div>
        ) : visible.length === 0 ? (
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
                <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22.5Z" />
                <path d="M4 4.5v18" />
              </svg>
            </div>
            <div
              className="text-[16px] font-semibold mb-1"
              style={{ color: "#1f2a2e" }}
            >
              {query.trim() || activePair !== "all"
                ? "No terms match this filter"
                : "Your glossary is empty"}
            </div>
            <div className="text-sm mb-5" style={{ color: "#8a8270" }}>
              {query.trim() || activePair !== "all"
                ? "Try clearing the search or picking a different language pair."
                : "Add approved terminology so your team translates consistently."}
            </div>
            {!(query.trim() || activePair !== "all") && (
              <button
                type="button"
                onClick={() => setShowAdd(true)}
                className="px-4 py-2.5 rounded-full text-sm font-semibold transition"
                style={{ background: "#0a7870", color: "#fff" }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.background = "#0a645d")
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.background = "#0a7870")
                }
              >
                Add your first term
              </button>
            )}
          </div>
        ) : (
          visible.map((t) => (
            <div
              key={t.id}
              className="grid items-start px-5 py-4 text-sm group"
              style={{
                gridTemplateColumns:
                  "minmax(180px,1.3fr) minmax(180px,1.3fr) minmax(220px,1.5fr) 0.9fr 0.8fr 90px",
                borderBottom: "1px solid #f4ecd6",
                color: "#1f2a2e",
              }}
            >
              <div
                className="font-medium leading-relaxed pr-4"
                style={{ color: "#1f2a2e" }}
              >
                {t.source_term}
              </div>
              <div
                className="leading-relaxed pr-4 font-semibold"
                style={{ color: "#0a5e58" }}
              >
                {t.target_term}
              </div>
              <div
                className="leading-relaxed pr-4 text-[13px]"
                style={{ color: t.notes ? "#4a4638" : "#cfc6ad" }}
              >
                {t.notes || "—"}
              </div>
              <div className="flex justify-end gap-1.5 items-center pt-0.5">
                <LangChip text={toLangCode(t.source_language)} />
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
                <LangChip text={toLangCode(t.target_language)} />
              </div>
              <div className="flex justify-end pt-0.5">
                <UsageBadge count={t.usage_count} />
              </div>
              <div className="flex justify-end items-center gap-1 pt-0.5">
                <RowAction
                  label="Edit"
                  onClick={() => startEdit(t)}
                  color="#0a7870"
                  hoverBg="#e7f1ef"
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
                    <path d="M12 20h9" />
                    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z" />
                  </svg>
                </RowAction>
                <RowAction
                  label="Delete"
                  onClick={() => deleteTerm(t.id)}
                  disabled={busy === `del:${t.id}`}
                  color="#b14a3a"
                  hoverBg="#f9efe9"
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
                </RowAction>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function UsageBadge({ count }: { count: number }) {
  const isUsed = count > 0
  return (
    <span
      className="inline-flex items-center text-[11px] font-semibold tabular-nums px-2 py-0.5 rounded-md"
      style={{
        background: isUsed ? "#cfe6e2" : "#f3ecdb",
        color: isUsed ? "#0a5e58" : "#9a9178",
        border: `1px solid ${isUsed ? "#b7dad4" : "#e7ddc5"}`,
      }}
      title={`${count.toLocaleString()} match${count === 1 ? "" : "es"} across translations`}
    >
      {count.toLocaleString()}×
    </span>
  )
}

function RowAction({
  label,
  onClick,
  disabled,
  color,
  hoverBg,
  children,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  color: string
  hoverBg: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="opacity-0 group-hover:opacity-100 transition p-1.5 rounded-full"
      style={{ color, background: "transparent" }}
      onMouseEnter={(e) => (e.currentTarget.style.background = hoverBg)}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      {children}
    </button>
  )
}

// ============================================================
// SUBCOMPONENTS
// ============================================================

function FieldGroup({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div
        className="text-[11px] font-semibold tracking-[0.14em] mb-2"
        style={{ color: "#9a9178" }}
      >
        {label}
      </div>
      <div
        className="flex items-center gap-2 px-4 py-2.5 rounded-xl"
        style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}
      >
        {children}
      </div>
    </div>
  )
}

function LangSelect({
  value,
  onChange,
}: {
  value: string
  onChange: (v: string) => void
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-transparent outline-none text-sm w-full"
      style={{ color: "#1f2a2e" }}
    >
      {COMMON_LANGUAGES.map((l) => (
        <option key={l} value={l}>
          {l}
        </option>
      ))}
    </select>
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
