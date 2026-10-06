"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { isStaffRole } from "@/lib/staff"

type Totals = {
  usd: number
  calls: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  credits: number
  revenue_usd: number
  margin_usd: number
}

type ActionRow = { action: string; usd: number; calls: number }

type TeamRow = {
  team_id: string | null
  name: string
  usd: number
  calls: number
  credits: number
  revenue_usd: number
  margin_usd: number
}

type ProjectRow = {
  project_id: string
  file_name: string
  team_name: string | null
  page_count: number | null
  usd: number
  calls: number
}

type Report = {
  days: number
  credit_price_cents: number
  totals: Totals
  by_action: ActionRow[]
  by_team: TeamRow[]
  top_projects: ProjectRow[]
}

const PERIODS = [7, 30, 90]

function money(n: number) {
  const digits = Math.abs(n) < 10 ? 2 : 0
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
}

function marginPct(revenue: number, margin: number) {
  return revenue > 0 ? `${Math.round((margin / revenue) * 100)}%` : "—"
}

function actionLabel(action: string) {
  return action.replace(/_/g, " ")
}

export default function AdminUsagePage() {
  const [staff, setStaff] = useState<boolean | null>(null)
  const [days, setDays] = useState(30)
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .get("/auth/me")
      .then((res) => setStaff(isStaffRole(res.data?.role)))
      .catch(() => setStaff(false))
  }, [])

  useEffect(() => {
    if (!staff) return
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await api.get("/admin/ai-usage", { params: { days } })
        if (!cancelled) setReport(res.data)
      } catch {
        if (!cancelled) setError("Couldn't load the usage report")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [staff, days])

  if (staff === null) return null

  if (!staff) {
    return (
      <div className="py-24 text-center">
        <div className="text-[16px] font-semibold mb-1" style={{ color: "#1f2a2e" }}>
          Not available
        </div>
        <div className="text-sm" style={{ color: "#8a8270" }}>
          This page is for OnlineDocTranslator staff.
        </div>
      </div>
    )
  }

  const totals = report?.totals
  const maxAction = Math.max(0.0001, ...(report?.by_action.map((a) => a.usd) ?? [0]))

  return (
    <div className="space-y-6 pb-16">
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        OnlineDocTranslator <span style={{ color: "#cfc6ad" }}>›</span> Admin{" "}
        <span style={{ color: "#cfc6ad" }}>›</span> <span style={{ color: "#1f2a2e" }}>AI usage</span>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[11px] font-semibold tracking-[0.18em] mb-1" style={{ color: "#9a9178" }}>
            AI USAGE
          </div>
          <h1 className="text-[28px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
            Model cost and margin
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            Real API cost against credits used
            {report ? ` at ${money(report.credit_price_cents / 100)} a credit` : ""}.
          </p>
        </div>
        <div className="flex rounded-full p-0.5" style={{ background: "#f3ecdb", border: "1px solid #e7ddc5" }}>
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setDays(p)}
              className="text-xs font-medium px-3 py-1 rounded-full transition"
              style={days === p ? { background: "#ffffff", color: "#0a7870" } : { color: "#6b6558" }}
            >
              {p} days
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="text-sm rounded-lg px-3 py-2" style={{ background: "#f2d4cf", color: "#7a2f24" }}>
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" style={{ opacity: loading ? 0.6 : 1 }}>
        <Kpi label="AI COST" value={totals ? money(totals.usd) : "—"} accent />
        <Kpi label="CALLS" value={totals ? totals.calls.toLocaleString() : "—"} />
        <Kpi label="CREDIT REVENUE" value={totals ? money(totals.revenue_usd) : "—"} sub={totals ? `${totals.credits.toLocaleString()} credits` : undefined} />
        <Kpi
          label="MARGIN"
          value={totals ? money(totals.margin_usd) : "—"}
          sub={totals ? marginPct(totals.revenue_usd, totals.margin_usd) : undefined}
          negative={!!totals && totals.margin_usd < 0}
        />
      </div>

      <Card title="BY ACTION">
        {!report || report.by_action.length === 0 ? (
          <Empty loading={loading} />
        ) : (
          <div className="px-5 py-3 space-y-2.5">
            {report.by_action.map((a) => (
              <div key={a.action} className="grid items-center gap-3 text-sm" style={{ gridTemplateColumns: "minmax(140px,1.2fr) 3fr 90px 70px" }}>
                <div className="truncate" style={{ color: "#1f2a2e" }} title={a.action}>
                  {actionLabel(a.action)}
                </div>
                <div className="h-2 rounded-full overflow-hidden" style={{ background: "#f3ecdb" }}>
                  <div className="h-full rounded-full" style={{ width: `${(a.usd / maxAction) * 100}%`, background: "#0a7870" }} />
                </div>
                <div className="text-right tabular-nums">{money(a.usd)}</div>
                <div className="text-right tabular-nums" style={{ color: "#8a8270" }}>
                  {a.calls.toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="BY TEAM">
        {!report || report.by_team.length === 0 ? (
          <Empty loading={loading} />
        ) : (
          <Table
            columns="2fr 0.8fr 0.8fr 0.8fr 0.9fr 0.9fr 0.6fr"
            head={["TEAM", "CALLS", "AI COST", "CREDITS", "REVENUE", "MARGIN", ""]}
            rows={report.by_team.map((t) => ({
              key: t.team_id ?? "none",
              cells: [
                t.name,
                t.calls.toLocaleString(),
                money(t.usd),
                t.credits.toLocaleString(),
                money(t.revenue_usd),
                <span key="m" style={{ color: t.margin_usd < 0 ? "#a14e2e" : "#1f2a2e" }}>{money(t.margin_usd)}</span>,
                <span key="p" style={{ color: "#8a8270" }}>{marginPct(t.revenue_usd, t.margin_usd)}</span>,
              ],
            }))}
          />
        )}
      </Card>

      <Card title="TOP PROJECTS BY COST">
        {!report || report.top_projects.length === 0 ? (
          <Empty loading={loading} />
        ) : (
          <Table
            columns="2.2fr 1.4fr 0.6fr 0.7fr 0.8fr"
            head={["DOCUMENT", "TEAM", "PAGES", "CALLS", "AI COST"]}
            rows={report.top_projects.map((p) => ({
              key: p.project_id,
              cells: [p.file_name, p.team_name || "—", p.page_count ?? "—", p.calls.toLocaleString(), money(p.usd)],
            }))}
          />
        )}
      </Card>
    </div>
  )
}

function Kpi({ label, value, sub, accent, negative }: { label: string; value: string; sub?: string; accent?: boolean; negative?: boolean }) {
  return (
    <div
      className="rounded-2xl p-5"
      style={{
        background: accent ? "#0a7870" : "#ffffff",
        border: accent ? "1px solid #0a645d" : "1px solid #e7ddc5",
        color: accent ? "#fff" : negative ? "#a14e2e" : "#1f2a2e",
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

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
      <div
        className="text-[11px] font-semibold tracking-[0.14em] px-5 py-3"
        style={{ background: "#faf5ee", borderBottom: "1px solid #f1e8d1", color: "#9a9178" }}
      >
        {title}
      </div>
      {children}
    </div>
  )
}

function Empty({ loading }: { loading: boolean }) {
  return (
    <div className="px-5 py-10 text-center text-sm" style={{ color: "#8a8270" }}>
      {loading ? "Loading…" : "No AI usage in this period"}
    </div>
  )
}

function Table({
  columns,
  head,
  rows,
}: {
  columns: string
  head: string[]
  rows: { key: string; cells: React.ReactNode[] }[]
}) {
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[640px]">
        <div
          className="grid items-center text-[11px] font-semibold tracking-[0.14em] px-5 py-2.5"
          style={{ gridTemplateColumns: columns, borderBottom: "1px solid #f1e8d1", color: "#9a9178" }}
        >
          {head.map((h, i) => (
            <div key={i} className={i === 0 ? "" : "text-right"}>
              {h}
            </div>
          ))}
        </div>
        {rows.map((r) => (
          <div
            key={r.key}
            className="grid items-center px-5 py-3 text-sm"
            style={{ gridTemplateColumns: columns, borderBottom: "1px solid #f4ecd6", color: "#1f2a2e" }}
          >
            {r.cells.map((c, i) => (
              <div key={i} className={i === 0 ? "pr-4 truncate font-medium" : "text-right tabular-nums"}>
                {c}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
