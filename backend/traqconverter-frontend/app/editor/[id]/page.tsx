"use client"

import { useEffect, useMemo, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { api } from "@/lib/api"
import {
  Avatar,
  IconBell,
  IconBolt,
  IconCertify,
  IconCheck,
  IconComment,
  IconDB,
  IconExport,
  IconKeyboard,
  IconWarn,
  LangChip,
} from "@/components/editor/EditorIcons"
import { EditorSidePanel } from "@/components/editor/EditorSidePanel"

// ============================================================
// EDITOR — ESPRESSO LOOK
// ============================================================

type Segment = {
  id: string | number
  source: string
  target: string
  tmPct?: number
  machine?: boolean
  approved?: boolean
  warn?: number
  comments?: number
  reviewer?: string
  glossary?: string[]
}

const MOCK_SEGMENTS: Segment[] = [
  { id: 1, source: "Informed Consent for Clinical Investigation", target: "Consenso informato per la sperimentazione clinica", tmPct: 100, approved: true, glossary: ["Informed Consent"] },
  { id: 2, source: "Protocol Reference: ACME-2184 · Version 3.2 · 12 March 2024", target: "Riferimento del protocollo: ACME-2184 · Versione 3.2 · 12 marzo 2024", tmPct: 98, approved: true },
  { id: 3, source: "You are invited to take part in a research study.", target: "La invitiamo a prendere parte a uno studio di ricerca.", tmPct: 100, approved: true, reviewer: "DC", comments: 1, glossary: ["research study"] },
  { id: 4, source: "Before you decide whether to participate, it is important that you understand why the research is being done and what it will involve.", target: "Prima di decidere se partecipare, è importante che Lei comprenda perché la ricerca viene condotta e cosa comporta.", tmPct: 86, comments: 1, glossary: ["participate"] },
  { id: 5, source: "Please take time to read the following information carefully and discuss it with others if you wish.", target: "La preghiamo di prendersi il tempo necessario per leggere attentamente le seguenti informazioni e di discuterne con altri, se lo desidera.", tmPct: 92 },
  { id: 6, source: "Approximately 240 participants will be enrolled across 12 sites in the United Kingdom and Italy.", target: "Saranno arruolati circa 24 partecipanti in 12 centri nel Regno Unito e in Italia.", machine: true, reviewer: "MR", warn: 1, comments: 1 },
  { id: 7, source: "If you decide to take part, you will be asked to sign an informed consent form.", target: "Se decide di partecipare, Le sarà chiesto di firmare un modulo di consenso informato.", tmPct: 94, glossary: ["informed consent"] },
  { id: 8, source: "You are free to withdraw from the research study at any time, without giving a reason.", target: "È libero/a di ritirarsi dallo studio di ricerca in qualsiasi momento, senza fornire alcuna motivazione.", tmPct: 88, glossary: ["withdraw", "research study"] },
  { id: 9, source: "Your decision whether or not to participate will not affect your current or future medical care.", target: "La Sua decisione di partecipare o meno non influirà sulle cure mediche attuali o future.", machine: true, glossary: ["participate"] },
]

function highlight(text: string, terms: string[] = []) {
  if (!terms.length) return <>{text}</>
  const pattern = new RegExp(`(${terms.map(escape).join("|")})`, "gi")
  const parts = text.split(pattern)
  return (
    <>
      {parts.map((p, i) =>
        terms.some((t) => t.toLowerCase() === p.toLowerCase()) ? (
          <span
            key={i}
            style={{
              borderBottom: "1px dashed #c88a1a",
              background: "#f9efd5",
            }}
          >
            {p}
          </span>
        ) : (
          <span key={i}>{p}</span>
        )
      )}
    </>
  )
}
function escape(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

export default function EditorPage() {
  const router = useRouter()
  const params = useParams()
  const id = params?.id as string

  const [project, setProject] = useState<any>(null)
  const [segments, setSegments] = useState<Segment[]>([])
  const [loading, setLoading] = useState(true)
  const [activeIdx, setActiveIdx] = useState(0)

  const fetchData = async () => {
    try {
      const [projRes, segRes] = await Promise.all([
        api.get(`/projects/${id}`),
        api.get(`/projects/${id}/segments`),
      ])
      setProject(projRes.data)

      const raw = (segRes.data || []) as any[]
      if (raw.length === 0) {
        setSegments(MOCK_SEGMENTS)
      } else {
        setSegments(
          raw.map((s: any, i: number) => ({
            id: s.id ?? i + 1,
            source: s.source_text || s.source || "",
            target: s.translated_text || s.target || "",
            tmPct: s.tm_pct,
            machine: s.machine || false,
            approved: s.approved || false,
            comments: s.comments || 0,
            glossary: s.glossary || [],
          }))
        )
      }
    } catch (err) {
      console.error("EDITOR ERROR:", err)
      setSegments(MOCK_SEGMENTS)
      setProject({
        file_name: "Patient Consent Pack",
        source_language: "en-GB",
        target_language: "it-IT",
        status: "COMPLETED",
        client: "Acme Pharma",
        domain: "Medical · Certified",
      })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!id) return
    fetchData()
  }, [id])

  useEffect(() => {
    if (!project || project.status === "COMPLETED") return
    const interval = setInterval(fetchData, 3000)
    return () => clearInterval(interval)
  }, [project])

  const stats = useMemo(() => {
    const translated = segments.filter((s) => s.target).length
    const approved = segments.filter((s) => s.approved).length
    const warnings = segments.reduce((n, s) => n + (s.warn || 0), 0)
    const total = segments.length
    const pctTranslated = total ? Math.round((translated / total) * 100) : 0
    return { translated, approved, warnings, total, pctTranslated }
  }, [segments])

  if (loading) {
    return (
      <div className="py-20 text-center" style={{ color: "#8a8270" }}>
        Loading editor...
      </div>
    )
  }

  if (project?.status && project.status !== "COMPLETED") {
    return (
      <div className="py-20 text-center">
        <h2 className="text-xl font-semibold mb-2" style={{ color: "#1f2a2e" }}>
          Processing your document…
        </h2>
        <p style={{ color: "#8a8270" }}>
          This usually takes under a minute. Polling for updates…
        </p>
      </div>
    )
  }

  const title =
    project?.file_name ||
    project?.filename ||
    project?.title ||
    "Patient Consent Pack"
  const client = project?.client || "Acme Pharma"
  const domain = project?.domain || "Medical · Certified"
  const src = project?.source_language || "en-GB"
  const tgt = project?.target_language || "it-IT"

  return (
    <div className="max-w-[1400px] mx-auto">
      {/* TOP META ROW (breadcrumb-ish back + status pill + bell + avatar) */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-start gap-6">
          <button
            onClick={() => router.push("/jobs")}
            className="text-sm mt-2 hover:underline"
            style={{ color: "#0a7870" }}
          >
            ← Projects
          </button>
          <div>
            <div className="text-sm" style={{ color: "#8a8270" }}>
              {client} <span className="mx-2">›</span> {domain}
            </div>
            <h1
              className="text-[30px] font-semibold tracking-tight"
              style={{ color: "#1f2a2e" }}
            >
              {title}
            </h1>
          </div>
        </div>

        <div className="flex items-center gap-3 mt-2">
          <span
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs"
            style={{ background: "#f6e3b8", color: "#7a5a10" }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: "#c88a1a" }}
            />
            In review
          </span>
          <button
            className="w-10 h-10 rounded-full flex items-center justify-center"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              color: "#6b6558",
            }}
          >
            {IconBell}
          </button>
          <Avatar initials="NL" size={36} />
        </div>
      </div>

      {/* TOOLBAR */}
      <div
        className="flex items-center justify-between gap-4 px-5 py-3 rounded-2xl mb-5"
        style={{
          background: "#ffffff",
          border: "1px solid #e7ddc5",
          boxShadow: "0 1px 2px rgba(30,30,20,0.03)",
        }}
      >
        <div className="flex items-center gap-3 flex-wrap">
          <LangChip code={src} />
          <span style={{ color: "#b9ac8e" }}>→</span>
          <LangChip code={tgt} active />
          <span className="mx-2" style={{ color: "#e7ddc5" }}>
            |
          </span>
          <Stat label="translated" value={`${stats.pctTranslated || 86}%`} />
          <Stat
            label="approved"
            value={`${stats.approved || 3} of ${stats.total || 14}`}
          />
          <Stat label="TM" value="64%" color="#0a7870" />
          <Stat
            label="QA"
            value={String(stats.warnings || 3)}
            color="#b06a2a"
            icon={IconWarn}
          />
        </div>

        <div className="flex items-center gap-3">
          <div className="flex -space-x-2">
            <Avatar initials="NL" />
            <Avatar initials="DC" />
            <Avatar initials="MR" />
          </div>
          <button
            className="w-9 h-9 rounded-md flex items-center justify-center"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              color: "#6b6558",
            }}
            title="Keyboard shortcuts"
          >
            {IconKeyboard}
          </button>
          <button
            className="flex items-center gap-2 px-4 py-2 rounded-full text-sm"
            style={{
              background: "#ffffff",
              border: "1px solid #e7ddc5",
              color: "#4a4638",
            }}
          >
            {IconExport}
            Export
          </button>
          <button
            className="flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium text-white transition"
            style={{ background: "#0a7870" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "#0a645d")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "#0a7870")}
          >
            {IconCertify}
            Certify & deliver
          </button>
        </div>
      </div>

      {/* MAIN GRID: SEGMENTS | SIDE PANEL */}
      <div
        className="grid gap-6"
        style={{ gridTemplateColumns: "minmax(0, 1fr) 340px" }}
      >
        {/* SEGMENTS TABLE */}
        <section
          className="rounded-2xl overflow-hidden"
          style={{
            background: "#ffffff",
            border: "1px solid #e7ddc5",
            boxShadow: "0 1px 2px rgba(30,30,20,0.03)",
          }}
        >
          {/* COL HEADER */}
          <div
            className="grid px-5 py-3 text-[11px] font-semibold tracking-[0.12em]"
            style={{
              color: "#9a9178",
              borderBottom: "1px solid #f1e8d1",
              gridTemplateColumns: "40px minmax(0,1fr) minmax(0,1fr) 110px",
            }}
          >
            <div />
            <div>SOURCE · ENGLISH (UK)</div>
            <div>TARGET · ITALIAN</div>
            <div />
          </div>

          {segments.map((seg, i) => (
            <SegmentRow
              key={seg.id}
              seg={seg}
              index={i + 1}
              active={i === activeIdx}
              onClick={() => setActiveIdx(i)}
            />
          ))}
        </section>

        {/* RIGHT PANEL */}
        <EditorSidePanel activeSegment={activeIdx + 1} />
      </div>
    </div>
  )
}

function Stat({
  label,
  value,
  color = "#1f2a2e",
  icon,
}: {
  label: string
  value: string
  color?: string
  icon?: React.ReactNode
}) {
  return (
    <span className="flex items-center gap-1.5 text-sm">
      {icon}
      <span className="font-semibold" style={{ color }}>
        {value}
      </span>
      <span style={{ color: "#8a8270" }}>{label}</span>
    </span>
  )
}

function SegmentRow({
  seg,
  index,
  active,
  onClick,
}: {
  seg: Segment
  index: number
  active: boolean
  onClick: () => void
}) {
  return (
    <div
      onClick={onClick}
      className="grid items-stretch cursor-pointer"
      style={{
        gridTemplateColumns: "40px minmax(0,1fr) minmax(0,1fr) 110px",
        borderBottom: "1px solid #f1e8d1",
        background: active ? "#fbf7ee" : "transparent",
        borderLeft: active ? "3px solid #0a7870" : "3px solid transparent",
      }}
    >
      {/* index + status dot */}
      <div className="flex flex-col items-center pt-5 gap-3 relative">
        <div
          className="text-xs font-mono"
          style={{ color: active ? "#0a7870" : "#9a9178" }}
        >
          {String(index).padStart(2, "0")}
        </div>
        <div
          className="w-2 h-2 rounded-full"
          style={{
            background: seg.approved
              ? "#4a8a3a"
              : seg.machine
              ? "#c88a1a"
              : "#0a7870",
          }}
        />
        {seg.reviewer && (
          <div className="absolute left-1 top-16">
            <Avatar initials={seg.reviewer} size={22} />
          </div>
        )}
      </div>

      {/* source */}
      <div className="py-5 pr-5" style={{ color: "#1f2a2e" }}>
        <div className="text-[15px] leading-relaxed">
          {highlight(seg.source, seg.glossary)}
        </div>
      </div>

      {/* target */}
      <div className="py-5 pl-5 pr-4 relative" style={{ color: "#1f2a2e" }}>
        <textarea
          defaultValue={seg.target}
          rows={2}
          className="w-full resize-none bg-transparent outline-none leading-relaxed text-[15px]"
          style={{
            color: "#1f2a2e",
            minHeight: 48,
          }}
        />
        {(seg.warn || seg.comments) && (
          <div className="absolute bottom-1 right-4 flex items-center gap-3 text-xs" style={{ color: "#9a9178" }}>
            {seg.warn ? (
              <span className="flex items-center gap-1" style={{ color: "#b06a2a" }}>
                {IconWarn} {seg.warn}
              </span>
            ) : null}
            {seg.comments ? (
              <span className="flex items-center gap-1">
                {IconComment} {seg.comments}
              </span>
            ) : null}
          </div>
        )}
      </div>

      {/* right mini status */}
      <div className="flex flex-col items-end justify-center pr-4 py-5 gap-2">
        {typeof seg.tmPct === "number" ? (
          <span
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px]"
            style={{ background: "#f6e3c8", color: "#8a5316" }}
          >
            <span style={{ color: "#b06a2a" }}>{IconDB}</span>
            {seg.tmPct}% TM
          </span>
        ) : seg.machine ? (
          <span
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px]"
            style={{ background: "#f6e3c8", color: "#8a5316" }}
          >
            {IconBolt}
            MT
          </span>
        ) : null}
        {seg.approved && IconCheck}
      </div>
    </div>
  )
}
