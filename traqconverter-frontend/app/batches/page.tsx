"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { api } from "@/lib/api"

type Batch = {
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

const COLUMNS = "2fr 0.7fr 0.6fr 1.4fr 0.7fr 0.9fr"

function formatDate(iso: string | null) {
  if (!iso) return "—"
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })
}

function BatchProgress({ b }: { b: Pick<Batch, "documents" | "completed" | "failed" | "in_progress"> }) {
  const pct = b.documents ? Math.round((b.completed / b.documents) * 100) : 0
  return (
    <div className="min-w-0">
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "#f3ecdb" }}>
        <div className="h-1.5 rounded-full" style={{ width: `${pct}%`, background: "#0a7870" }} />
      </div>
      <div className="text-xs mt-1" style={{ color: "#8a8270" }}>
        {b.completed}/{b.documents} done
        {b.in_progress ? ` · ${b.in_progress} in progress` : ""}
        {b.failed ? <span style={{ color: "#b91c1c" }}> · {b.failed} failed</span> : null}
      </div>
    </div>
  )
}

export default function BatchesPage() {
  const [batches, setBatches] = useState<Batch[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .get("/batches")
      .then((res) => setBatches(res.data || []))
      .catch(() => setError("Couldn't load batches"))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="space-y-6 pb-16">
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        TraqConverter <span style={{ color: "#cfc6ad" }}>›</span> Workspace{" "}
        <span style={{ color: "#cfc6ad" }}>›</span> <span style={{ color: "#1f2a2e" }}>Batches</span>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[11px] font-semibold tracking-[0.18em] mb-1" style={{ color: "#9a9178" }}>
            BATCHES
          </div>
          <h1 className="text-[28px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
            Client batches
          </h1>
          <p className="text-sm mt-1" style={{ color: "#8a8270" }}>
            Documents uploaded together. Names and terms stay the same across each batch.
          </p>
        </div>
        <Link
          href="/new-translation"
          className="px-4 py-2 rounded-full text-sm font-medium text-white"
          style={{ background: "#0a7870" }}
        >
          New batch
        </Link>
      </div>

      {error && (
        <div className="text-sm rounded-lg px-3 py-2" style={{ background: "#f2d4cf", color: "#7a2f24" }}>
          {error}
        </div>
      )}

      <div className="rounded-2xl overflow-x-auto" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
        <div className="min-w-[760px]">
          <div
            className="grid items-center text-[11px] font-semibold tracking-[0.14em] px-5 py-3"
            style={{ gridTemplateColumns: COLUMNS, background: "#faf5ee", borderBottom: "1px solid #f1e8d1", color: "#9a9178" }}
          >
            <div>CLIENT / BATCH</div>
            <div className="text-right">DOCUMENTS</div>
            <div className="text-right">PAGES</div>
            <div className="pl-6">PROGRESS</div>
            <div className="text-right">TERMS</div>
            <div className="text-right">CREATED</div>
          </div>

          {loading ? (
            <div className="px-5 py-12 text-center text-sm" style={{ color: "#8a8270" }}>
              Loading batches…
            </div>
          ) : batches.length === 0 ? (
            <div className="px-5 py-16 text-center">
              <div className="text-[16px] font-semibold mb-1" style={{ color: "#1f2a2e" }}>
                No batches yet
              </div>
              <div className="text-sm" style={{ color: "#8a8270" }}>
                Drop several documents from one client on New project to create one.
              </div>
            </div>
          ) : (
            batches.map((b) => (
              <Link
                key={b.id}
                href={`/batches/${b.id}`}
                className="grid items-center px-5 py-4 text-sm transition hover:bg-[#fbf7ee]"
                style={{ gridTemplateColumns: COLUMNS, borderBottom: "1px solid #f4ecd6", color: "#1f2a2e" }}
              >
                <div className="pr-4 font-medium truncate">{b.name}</div>
                <div className="text-right tabular-nums">{b.documents}</div>
                <div className="text-right tabular-nums">{b.pages}</div>
                <div className="pl-6">
                  <BatchProgress b={b} />
                </div>
                <div className="text-right tabular-nums">{b.terms}</div>
                <div className="text-right" style={{ color: "#8a8270" }}>
                  {formatDate(b.created_at)}
                </div>
              </Link>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
