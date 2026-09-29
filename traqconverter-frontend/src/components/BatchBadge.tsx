"use client"

import Link from "next/link"

export type BatchRef = { id: string; name: string }

export default function BatchBadge({ batch }: { batch: BatchRef }) {
  return (
    <Link
      href={`/jobs?batch=${batch.id}`}
      onClick={(e) => e.stopPropagation()}
      title={`Batch: ${batch.name}`}
      className="inline-flex items-center gap-1 max-w-[180px] px-2 py-0.5 rounded-full text-[11px] font-medium align-middle hover:underline"
      style={{ background: "#e1efec", color: "#0a5e58", border: "1px solid #cfe6e2" }}
    >
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
        <rect x="7" y="3" width="13" height="15" rx="2" />
        <path d="M4 7v12a2 2 0 0 0 2 2h10" />
      </svg>
      <span className="truncate">{batch.name || "Batch"}</span>
    </Link>
  )
}
