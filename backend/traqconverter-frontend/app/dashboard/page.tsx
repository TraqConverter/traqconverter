"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"

// ============================================================
// DASHBOARD — ESPRESSO LOOK
// ============================================================

type Project = {
  id: string | number
  file_name?: string
  filename?: string
  name?: string
  title?: string
  source_language?: string
  source_lang?: string
  target_language?: string
  target_lang?: string
  status?: string
  progress_percent?: number
  progress?: number
  domain?: string
  words?: number
  word_count?: number
  due?: string
  due_date?: string
  team?: string[]
}

type Tab = "all" | "assigned" | "review"

const STATUS_STYLES: Record<
  string,
  { bg: string; dot: string; text: string; label: string }
> = {
  IN_REVIEW: { bg: "#f6e3b8", dot: "#c88a1a", text: "#7a5a10", label: "In review" },
  TRANSLATING: { bg: "#cfe6e2", dot: "#0a7870", text: "#0a5e58", label: "Translating" },
  PROCESSING: { bg: "#cfe6e2", dot: "#0a7870", text: "#0a5e58", label: "Translating" },
  DRAFT: { bg: "#ede3cc", dot: "#9a9178", text: "#6b6558", label: "Draft" },
  QUEUED: { bg: "#ede3cc", dot: "#9a9178", text: "#6b6558", label: "Draft" },
  CERTIFIED: { bg: "#d8ead6", dot: "#4a8a3a", text: "#2d5a24", label: "Certified" },
  COMPLETED: { bg: "#d8ead6", dot: "#4a8a3a", text: "#2d5a24", label: "Delivered" },
  FAILED: { bg: "#f2d4cf", dot: "#b14a3a", text: "#7a2f24", label: "Failed" },
}

function statusStyle(status?: string) {
  const key = (status || "DRAFT").toUpperCase()
  return STATUS_STYLES[key] || STATUS_STYLES.DRAFT
}

function hashHue(s: string) {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h % 360
}

function Avatar({ initials }: { initials: string }) {
  const hue = hashHue(initials)
  return (
    <div
      className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-semibold"
      style={{
        background: `hsl(${hue} 40% 82%)`,
        color: `hsl(${hue} 45% 28%)`,
        border: "2px solid #fff",
      }}
    >
      {initials}
    </div>
  )
}

function LangChip({ code }: { code: string }) {
  return (
    <span
      className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-mono"
      style={{
        background: "#f3ecdb",
        color: "#6b6558",
        border: "1px solid #e7ddc5",
      }}
    >
      {code}
    </span>
  )
}

function IconFile() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#b14a3a" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v4h4" />
    </svg>
  )
}

function IconFilter() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M6 12h12M10 18h4" />
    </svg>
  )
}

function IconPlus() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

function IconDots() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="#9a9178">
      <circle cx="6" cy="12" r="1.6" />
      <circle cx="12" cy="12" r="1.6" />
      <circle cx="18" cy="12" r="1.6" />
    </svg>
  )
}

// Placeholder mock rows used when API has no data yet — keeps the
// screen looking alive when the backend has zero projects.
const MOCK_PROJECTS: Project[] = [
  { id: "m1", name: "Acme Pharma — Patient Consent Pack", domain: "Medical · Certified", words: 4820, source_language: "en-GB", target_language: "it-IT", status: "IN_REVIEW", progress_percent: 76, team: ["NI", "DC", "MR"], due: "Due Fri" },
  { id: "m2", name: "Lumen Bank — Credit Agreement", domain: "Legal · Sworn", words: 12400, source_language: "it-IT", target_language: "en-US", status: "TRANSLATING", progress_percent: 42, team: ["DC", "SB"], due: "Due 24 Apr" },
  { id: "m3", name: "Kōso App — iOS Localisation Strings", domain: "Software · TM-heavy", words: 3210, source_language: "en-GB", target_language: "ja-JP", status: "TRANSLATING", progress_percent: 28, team: ["KT", "NL"], due: "Due 28 Apr" },
  { id: "m4", name: "Firenze Tourism Board — Brochure", domain: "Marketing · Transcreation", words: 2100, source_language: "it-IT", target_language: "fr-FR", status: "DRAFT", progress_percent: 12, team: ["PM"], due: "Due 2 May" },
  { id: "m5", name: "Nordic Health — Device Instructions", domain: "Medical · Certified", words: 5600, source_language: "sv-SE", target_language: "en-GB", status: "CERTIFIED", progress_percent: 100, team: ["OL", "NI", "DC"], due: "Delivered" },
]

export default function DashboardPage() {
  const router = useRouter()
  const [loading, setLoading] = useState(true)
  const [projects, setProjects] = useState<Project[]>([])
  const [tab, setTab] = useState<Tab>("all")
  const [name, setName] = useState<string>("Niki")

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const res = await api.get("/projects/")
      const data = (res.data || []) as Project[]
      setProjects(data.length > 0 ? data : MOCK_PROJECTS)
    } catch (err) {
      console.error(err)
      setProjects(MOCK_PROJECTS)
    } finally {
      setLoading(false)
    }
  }

  // KPIs
  const kpis = useMemo(() => {
    const active = projects.filter((p) => {
      const s = (p.status || "").toUpperCase()
      return s !== "COMPLETED" && s !== "CERTIFIED" && s !== "FAILED"
    }).length

    const wordsInFlight = projects
      .filter((p) => (p.status || "").toUpperCase() !== "COMPLETED")
      .reduce((sum, p) => sum + (p.words || p.word_count || 0), 0)

    return {
      active,
      wordsInFlight,
    }
  }, [projects])

  const filtered = useMemo(() => {
    if (tab === "assigned") {
      return projects.filter((p) => (p.team || []).includes("NL"))
    }
    if (tab === "review") {
      return projects.filter(
        (p) => (p.status || "").toUpperCase() === "IN_REVIEW"
      )
    }
    return projects
  }, [projects, tab])

  // Try to read name from token-backed profile — fallback to "Niki"
  useEffect(() => {
    const stored =
      typeof window !== "undefined" ? localStorage.getItem("userName") : null
    if (stored) setName(stored)
  }, [])

  return (
    <div className="max-w-[1200px] mx-auto">
      {/* BREADCRUMB + WELCOME */}
      <div className="mb-8">
        <div className="text-sm mb-2" style={{ color: "#8a8270" }}>
          <span>TraqConverter</span>
          <span className="mx-2">›</span>
          <span>Workspace</span>
        </div>
        <h1
          className="text-[34px] font-semibold tracking-tight"
          style={{ color: "#1f2a2e" }}
        >
          Welcome back, {name}
        </h1>
      </div>

      {/* KPI CARDS */}
      <div className="grid grid-cols-4 gap-5 mb-10">
        <KpiCard
          label="ACTIVE PROJECTS"
          value={String(kpis.active || 12)}
          pill={{ text: "+2 this week", color: "#0a7870", bg: "#e1efec" }}
          footer={`Across ${Math.max(3, Math.min(7, kpis.active || 7))} language pairs`}
        />
        <KpiCard
          label="WORDS IN FLIGHT"
          value={formatK(kpis.wordsInFlight || 38400)}
          pill={{ text: "On pace", color: "#0a7870", bg: "#e1efec" }}
          footer="2 due this week"
        />
        <KpiCard
          label="TM LEVERAGE"
          value="64%"
          pill={{ text: "+6%", color: "#b06a2a", bg: "#f6e3c8" }}
          footer="Saving ~4,200 words / mo"
        />
        <KpiCard
          label="AVG. DELIVERY"
          value="2.1d"
          pill={null}
          footer="vs. 2.4d last quarter"
        />
      </div>

      {/* PROJECTS SECTION */}
      <section
        className="rounded-2xl"
        style={{
          background: "#ffffff",
          border: "1px solid #e7ddc5",
          boxShadow: "0 1px 2px rgba(30,30,20,0.03)",
        }}
      >
        <header className="flex items-center justify-between px-7 pt-6 pb-5">
          <div>
            <h2
              className="text-[22px] font-semibold"
              style={{ color: "#1f2a2e" }}
            >
              Projects
            </h2>
            <p className="text-sm mt-0.5" style={{ color: "#8a8270" }}>
              Recent work across your team
            </p>
          </div>

          <div className="flex items-center gap-3">
            {/* TABS */}
            <div
              className="flex items-center p-1 rounded-full"
              style={{ background: "#f6efe0" }}
            >
              {(
                [
                  { key: "all", label: "All" },
                  { key: "assigned", label: "Assigned to me" },
                  { key: "review", label: "Awaiting review" },
                ] as { key: Tab; label: string }[]
              ).map((t) => {
                const active = tab === t.key
                return (
                  <button
                    key={t.key}
                    onClick={() => setTab(t.key)}
                    className="text-sm px-4 py-1.5 rounded-full transition"
                    style={{
                      background: active ? "#ffffff" : "transparent",
                      color: active ? "#1f2a2e" : "#8a8270",
                      fontWeight: active ? 600 : 500,
                      boxShadow: active
                        ? "0 1px 2px rgba(30,30,20,0.06)"
                        : "none",
                    }}
                  >
                    {t.label}
                  </button>
                )
              })}
            </div>

            {/* FILTER */}
            <button
              className="flex items-center gap-2 px-4 py-2 rounded-full text-sm"
              style={{
                background: "#ffffff",
                border: "1px solid #e7ddc5",
                color: "#4a4638",
              }}
            >
              <IconFilter />
              Filter
            </button>

            {/* NEW PROJECT */}
            <button
              onClick={() => router.push("/new-translation")}
              className="flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium text-white transition"
              style={{ background: "#0a7870" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "#0a645d")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "#0a7870")}
            >
              <IconPlus />
              New project
            </button>
          </div>
        </header>

        {/* TABLE HEADER */}
        <div
          className="grid px-7 py-3 text-[11px] font-semibold tracking-[0.12em]"
          style={{
            color: "#9a9178",
            borderTop: "1px solid #f1e8d1",
            borderBottom: "1px solid #f1e8d1",
            gridTemplateColumns: "minmax(320px,2.2fr) 1.4fr 1fr 1.4fr 1fr 40px",
          }}
        >
          <div>PROJECT</div>
          <div>LANGUAGES</div>
          <div>STATUS</div>
          <div>PROGRESS</div>
          <div>TEAM · DUE</div>
          <div />
        </div>

        {/* ROWS */}
        <div>
          {loading && (
            <div className="px-7 py-10 text-center" style={{ color: "#8a8270" }}>
              Loading projects...
            </div>
          )}

          {!loading && filtered.length === 0 && (
            <div className="px-7 py-10 text-center" style={{ color: "#8a8270" }}>
              No projects match this view.
            </div>
          )}

          {!loading &&
            filtered.map((p, idx) => {
              const title = p.name || p.file_name || p.filename || p.title || "Untitled project"
              const src = p.source_language || p.source_lang || "en-GB"
              const tgt = p.target_language || p.target_lang || "en-US"
              const progress = p.progress_percent ?? p.progress ?? 0
              const s = statusStyle(p.status)
              const team = p.team || ["NL"]
              const due = p.due || p.due_date || "—"

              return (
                <div
                  key={p.id ?? idx}
                  onClick={() => router.push(`/editor/${p.id}`)}
                  className="grid px-7 py-5 items-center cursor-pointer transition"
                  style={{
                    gridTemplateColumns: "minmax(320px,2.2fr) 1.4fr 1fr 1.4fr 1fr 40px",
                    borderBottom:
                      idx < filtered.length - 1 ? "1px solid #f1e8d1" : "none",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "#fbf7ee")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                >
                  {/* PROJECT */}
                  <div className="flex items-center gap-3 min-w-0">
                    <div
                      className="w-10 h-11 flex items-center justify-center rounded-md shrink-0"
                      style={{ background: "#faf0e6", border: "1px solid #f0dcc6" }}
                    >
                      <IconFile />
                    </div>
                    <div className="min-w-0">
                      <div
                        className="font-medium truncate"
                        style={{ color: "#1f2a2e" }}
                      >
                        {title}
                      </div>
                      <div className="text-xs mt-0.5" style={{ color: "#8a8270" }}>
                        {p.domain ||
                          `${(p.words || p.word_count || 0).toLocaleString()} words`}
                        {p.domain && p.words
                          ? ` · ${p.words.toLocaleString()} words`
                          : ""}
                      </div>
                    </div>
                  </div>

                  {/* LANGUAGES */}
                  <div className="flex items-center gap-2">
                    <LangChip code={src} />
                    <span style={{ color: "#b9ac8e" }}>→</span>
                    <LangChip code={tgt} />
                  </div>

                  {/* STATUS */}
                  <div>
                    <span
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs"
                      style={{ background: s.bg, color: s.text }}
                    >
                      <span
                        className="w-1.5 h-1.5 rounded-full"
                        style={{ background: s.dot }}
                      />
                      {s.label}
                    </span>
                  </div>

                  {/* PROGRESS */}
                  <div className="flex items-center gap-3">
                    <div
                      className="flex-1 h-1.5 rounded-full overflow-hidden max-w-[140px]"
                      style={{ background: "#f1e8d1" }}
                    >
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${progress}%`,
                          background: "#0a7870",
                        }}
                      />
                    </div>
                    <span className="text-xs" style={{ color: "#6b6558" }}>
                      {progress}%
                    </span>
                  </div>

                  {/* TEAM · DUE */}
                  <div className="flex items-center gap-3">
                    <div className="flex -space-x-2">
                      {team.slice(0, 3).map((t, i) => (
                        <Avatar key={i} initials={t} />
                      ))}
                      {team.length > 3 && (
                        <div
                          className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-semibold"
                          style={{
                            background: "#ede3cc",
                            color: "#6b6558",
                            border: "2px solid #fff",
                          }}
                        >
                          +{team.length - 3}
                        </div>
                      )}
                    </div>
                    <span className="text-xs" style={{ color: "#6b6558" }}>
                      {due}
                    </span>
                  </div>

                  {/* DOTS */}
                  <div className="flex justify-end">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                      }}
                      className="w-8 h-8 rounded-md flex items-center justify-center"
                      style={{ color: "#9a9178" }}
                    >
                      <IconDots />
                    </button>
                  </div>
                </div>
              )
            })}
        </div>
      </section>
    </div>
  )
}

function formatK(n: number) {
  if (!n) return "0"
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`
  return String(n)
}

function KpiCard({
  label,
  value,
  pill,
  footer,
}: {
  label: string
  value: string
  pill: { text: string; color: string; bg: string } | null
  footer: string
}) {
  return (
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
        {label}
      </div>
      <div className="flex items-center gap-3 mb-2">
        <div
          className="text-[40px] font-semibold leading-none"
          style={{ color: "#1f2a2e" }}
        >
          {value}
        </div>
        {pill && (
          <span
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs"
            style={{ background: pill.bg, color: pill.color }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: pill.color }}
            />
            {pill.text}
          </span>
        )}
      </div>
      <div className="text-xs" style={{ color: "#8a8270" }}>
        {footer}
      </div>
    </div>
  )
}
