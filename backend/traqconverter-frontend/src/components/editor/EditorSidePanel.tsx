"use client"

import { useState } from "react"

// ============================================================
// EDITOR SIDE PANEL — TM · Glossary · Comments · Status
// ============================================================

export type TmMatch = {
  pct: number
  source: string
  date: string
  author?: string
  src: string
  tgt: string
}

type Tab = "tm" | "glossary" | "comments" | "status"

// Real TM matches come from the backend — no fake placeholder data here.
// The panel renders an empty state if `matches` is missing or empty.
export function EditorSidePanel({
  activeSegment,
  matches = [],
}: {
  activeSegment: number
  matches?: TmMatch[]
}) {
  const [tab, setTab] = useState<Tab>("tm")

  return (
    <aside
      className="rounded-2xl overflow-hidden flex flex-col"
      style={{
        background: "#ffffff",
        border: "1px solid #e7ddc5",
        boxShadow: "0 1px 2px rgba(30,30,20,0.03)",
      }}
    >
      {/* TABS */}
      <div
        className="grid grid-cols-4 px-3 pt-3 pb-0"
        style={{ borderBottom: "1px solid #f1e8d1" }}
      >
        <TabButton
          label="TM"
          count={3}
          active={tab === "tm"}
          onClick={() => setTab("tm")}
        />
        <TabButton
          label="Glossary"
          count={1}
          active={tab === "glossary"}
          onClick={() => setTab("glossary")}
        />
        <TabButton
          label="Comments"
          count={0}
          active={tab === "comments"}
          onClick={() => setTab("comments")}
        />
        <TabButton
          label="Status"
          active={tab === "status"}
          onClick={() => setTab("status")}
        />
      </div>

      {/* BODY */}
      <div className="p-5 overflow-y-auto flex-1">
        {tab === "tm" && (
          <>
            <div
              className="text-[10px] font-semibold tracking-[0.14em] mb-3"
              style={{ color: "#9a9178" }}
            >
              MATCHES FOR SEGMENT #{activeSegment}
            </div>
            {matches.length === 0 ? (
              <div
                className="text-sm text-center py-12"
                style={{ color: "#8a8270" }}
              >
                No TM matches yet — your translation memory will populate as
                you approve segments.
              </div>
            ) : (
              <div className="space-y-4">
                {matches.map((m, i) => (
                  <MatchCard key={i} match={m} />
                ))}
              </div>
            )}
          </>
        )}

        {tab === "glossary" && (
          <>
            <div
              className="text-[10px] font-semibold tracking-[0.14em] mb-3"
              style={{ color: "#9a9178" }}
            >
              GLOSSARY TERMS IN #{activeSegment}
            </div>
            <div
              className="text-sm text-center py-12"
              style={{ color: "#8a8270" }}
            >
              No glossary terms detected in this segment.
            </div>
          </>
        )}

        {tab === "comments" && (
          <div className="text-sm text-center py-12" style={{ color: "#8a8270" }}>
            No comments on this segment.
          </div>
        )}

        {tab === "status" && (
          <div
            className="text-sm text-center py-12"
            style={{ color: "#8a8270" }}
          >
            Project-wide stats will appear here once segments are translated.
          </div>
        )}
      </div>
    </aside>
  )
}

function TabButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string
  count?: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="py-3 text-center transition"
      style={{
        borderBottom: active ? "2px solid #0a7870" : "2px solid transparent",
        color: active ? "#0a7870" : "#8a8270",
      }}
    >
      <div className="text-xs font-semibold">{label}</div>
      {typeof count === "number" && (
        <div className="text-[11px] mt-0.5" style={{ color: "#9a9178" }}>
          · {count}
        </div>
      )}
    </button>
  )
}

function MatchCard({ match }: { match: TmMatch }) {
  const pctColor =
    match.pct >= 95 ? "#0a7870" : match.pct >= 80 ? "#b06a2a" : "#9a9178"
  return (
    <div
      className="rounded-xl p-4"
      style={{
        background: "#fbf7ee",
        border: "1px solid #f1e8d1",
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <div
            className="text-sm font-semibold"
            style={{ color: pctColor }}
          >
            {match.pct}%
          </div>
          <div className="text-xs" style={{ color: "#6b6558" }}>
            {match.source} · {match.date}
            {match.author ? ` · ${match.author}` : ""}
          </div>
        </div>
        <button
          className="text-[10px] font-semibold tracking-[0.12em]"
          style={{ color: "#0a7870" }}
        >
          TAB TO APPLY
        </button>
      </div>
      <div
        className="text-xs mb-1.5 leading-relaxed"
        style={{ color: "#8a8270" }}
      >
        {match.src}
      </div>
      <div
        className="text-sm font-medium leading-relaxed"
        style={{ color: "#1f2a2e" }}
      >
        {match.tgt}
      </div>
    </div>
  )
}
