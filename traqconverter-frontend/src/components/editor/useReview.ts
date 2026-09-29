"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"

export type Box = [number, number, number, number]
export type SourceRef = { page: number; bbox: Box }
export type Severity = "error" | "warning" | "info"

export type CheckItem = {
  id: string
  kind: string
  severity: Severity
  message: string
  block_id?: string
  source?: SourceRef
  reason?: string
  dismissed: boolean
}

export type Checks = {
  ready: boolean
  document_version: number
  items: CheckItem[]
  checked_at: string
  pending: boolean
  counts: Record<Severity, number>
}

export type SourceBlock = {
  page: number
  bbox: Box
  confidence: number
  reading: "high" | "medium" | "low"
  reason: string
}

export type SourceMap = {
  status: "ready" | "pending" | "unavailable"
  version: number
  revision: number
  blocks: Record<string, SourceBlock>
  elements: { page: number; bbox: Box; kind: string; text: string; reading: string; block_id: string }[]
}

const REFRESH_DELAY_MS = 1500
const MAP_POLL_MS = 2500
const MAP_POLL_LIMIT = 60

export function blocking(item: CheckItem) {
  return !item.dismissed && (item.severity === "error" || item.severity === "warning")
}

function withCounts(checks: Checks, items: CheckItem[]): Checks {
  const counts = { error: 0, warning: 0, info: 0 }
  for (const i of items) if (!i.dismissed) counts[i.severity]++
  return { ...checks, items, counts, ready: !items.some(blocking) }
}

export function useReview(projectId: string, version: number) {
  const [checks, setChecks] = useState<Checks | null>(null)
  const [map, setMap] = useState<SourceMap | null>(null)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState("")
  const checkSeq = useRef(0)
  const mapSeq = useRef(0)
  const pollTimer = useRef<number | null>(null)
  const revisionRef = useRef(-1)

  const fetchChecks = useCallback(
    async (refresh = false): Promise<Checks | null> => {
      const seq = ++checkSeq.current
      setChecking(true)
      try {
        const res = await api.get<Checks>(`/projects/${projectId}/checks`, { params: refresh ? { refresh: 1 } : {} })
        if (seq === checkSeq.current) {
          setChecks(res.data)
          setError("")
        }
        return res.data
      } catch {
        if (seq === checkSeq.current) setError("Couldn't run the checks.")
        return null
      } finally {
        if (seq === checkSeq.current) setChecking(false)
      }
    },
    [projectId],
  )

  const fetchMap = useCallback(
    async (attempt = 0) => {
      const seq = ++mapSeq.current
      if (pollTimer.current) window.clearTimeout(pollTimer.current)
      try {
        const res = await api.get<SourceMap>(`/projects/${projectId}/source/map`)
        if (seq !== mapSeq.current) return
        setMap(res.data)
        const revisionChanged = revisionRef.current >= 0 && res.data.revision !== revisionRef.current
        revisionRef.current = res.data.revision
        // Uncertain readings come from the map, so the checklist follows each new map revision.
        if (revisionChanged) void fetchChecks()
        if (res.data.status === "pending" && attempt < MAP_POLL_LIMIT) {
          pollTimer.current = window.setTimeout(() => void fetchMap(attempt + 1), MAP_POLL_MS)
        }
      } catch {
        // The source pane keeps its last map; the next document change retries.
      }
    },
    [projectId, fetchChecks],
  )

  useEffect(() => {
    if (!projectId || version <= 0) return
    const t = window.setTimeout(() => {
      void fetchMap().then(() => fetchChecks())
    }, REFRESH_DELAY_MS)
    return () => window.clearTimeout(t)
  }, [projectId, version, fetchMap, fetchChecks])

  useEffect(() => {
    return () => {
      if (pollTimer.current) window.clearTimeout(pollTimer.current)
    }
  }, [])

  const dismiss = useCallback(
    async (id: string, on: boolean) => {
      const flip = (value: boolean) =>
        setChecks((c) => (c ? withCounts(c, c.items.map((i) => (i.id === id ? { ...i, dismissed: value } : i))) : c))
      flip(on)
      try {
        if (on) await api.post(`/projects/${projectId}/checks/${id}/dismiss`)
        else await api.delete(`/projects/${projectId}/checks/${id}/dismiss`)
      } catch {
        flip(!on)
      }
    },
    [projectId],
  )

  return { checks, map, checking, error, fetchChecks, dismiss }
}
