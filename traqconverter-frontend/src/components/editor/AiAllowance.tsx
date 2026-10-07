"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"

type Allowance = {
  included: number
  used: number
  remaining_included: number
  next_block_cost_credits: number
  edits_per_extra_credit: number
  credits_charged: number
  regenerations_used: number
  regenerations_max: number
  regenerations_free: number
  next_regenerate_cost_credits: number
}

export default function AiAllowance({ projectId, remaining }: { projectId: string; remaining?: number }) {
  const [allowance, setAllowance] = useState<Allowance | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get(`/projects/${projectId}/ai-allowance`)
      .then((res) => {
        if (!cancelled) setAllowance(res.data)
      })
      .catch(() => {
        if (!cancelled) setAllowance(null)
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  if (!allowance) return null

  const left = remaining ?? allowance.remaining_included
  const cost = allowance.next_block_cost_credits
  const block = allowance.edits_per_extra_credit
  const costLabel = `${cost} credit${cost === 1 ? "" : "s"}`
  const label =
    left > 0
      ? `${left} of ${allowance.included} AI edits left`
      : `Included edits used · ${costLabel} per ${block} more`

  return (
    <div
      className="inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full tabular-nums"
      style={
        left > 0
          ? { background: "#e6f2f0", color: "#0a5e58", border: "1px solid #cfe6e2" }
          : { background: "#fbeedd", color: "#8a5a14", border: "1px solid #f0dcb8" }
      }
      title={
        left > 0
          ? `This document includes ${allowance.included} AI edits, then ${costLabel} per ${block} more`
          : `The next AI edit uses ${costLabel} and adds ${block} more`
      }
    >
      {label}
    </div>
  )
}
