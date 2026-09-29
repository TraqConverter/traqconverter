"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api, fetchObjectUrl } from "@/lib/api"
import type { Box, SourceMap, SourceRef } from "./useReview"

type PageSize = { width: number; height: number }
type PagesInfo = { available: boolean; count: number; pages: PageSize[] }

const ZOOMS = [0.75, 1, 1.25, 1.5, 2, 2.5]
const GAP = 12
const PAD = 12
const MAX_SCALE = 4

function scaleFor(displayWidth: number, page: PageSize) {
  const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1
  const raw = (displayWidth * Math.min(dpr, 2)) / page.width
  return Math.min(MAX_SCALE, Math.max(0.5, Math.ceil(raw * 2) / 2))
}

function rectStyle(bbox: Box, pad = 0.004) {
  const [x0, y0, x1, y1] = bbox
  return {
    left: `${Math.max(0, x0 - pad) * 100}%`,
    top: `${Math.max(0, y0 - pad) * 100}%`,
    width: `${(Math.min(1, x1 + pad) - Math.max(0, x0 - pad)) * 100}%`,
    height: `${(Math.min(1, y1 + pad) - Math.max(0, y0 - pad)) * 100}%`,
  }
}

export default function SourceViewer({
  projectId,
  fileName,
  map,
  activeBlockId,
  focus,
  hoverBlockId,
  onHoverBlock,
  onPickBlock,
  onUnavailable,
}: {
  projectId: string
  fileName: string
  map: SourceMap | null
  activeBlockId: string | null
  focus: (SourceRef & { key: number }) | null
  hoverBlockId: string | null
  onHoverBlock: (id: string | null) => void
  onPickBlock: (id: string) => void
  onUnavailable: () => void
}) {
  const [info, setInfo] = useState<PagesInfo | null>(null)
  const [failed, setFailed] = useState(false)
  const [width, setWidth] = useState(0)
  const [zoom, setZoom] = useState(1)
  const [urls, setUrls] = useState<Record<number, { url: string; scale: number }>>({})
  const [opening, setOpening] = useState(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const pageRefs = useRef<(HTMLDivElement | null)[]>([])
  const urlsRef = useRef<Record<number, { url: string; scale: number }>>({})
  const loadingRef = useRef(new Set<string>())
  const onUnavailableRef = useRef(onUnavailable)

  useEffect(() => {
    onUnavailableRef.current = onUnavailable
  }, [onUnavailable])

  useEffect(() => {
    let active = true
    api
      .get<PagesInfo>(`/projects/${projectId}/source/pages`)
      .then((res) => {
        if (!active) return
        setInfo(res.data)
        if (!res.data.available) onUnavailableRef.current()
      })
      .catch(() => {
        if (!active) return
        setFailed(true)
        onUnavailableRef.current()
      })
    return () => {
      active = false
    }
  }, [projectId])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const measure = () => setWidth(el.clientWidth)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [info])

  useEffect(() => {
    const loaded = urlsRef.current
    return () => {
      for (const v of Object.values(loaded)) URL.revokeObjectURL(v.url)
    }
  }, [])

  const displayWidth = Math.max(0, (width - PAD * 2) * zoom)

  useEffect(() => {
    if (!info?.available || displayWidth < 50) return
    info.pages.forEach((page, i) => {
      const scale = scaleFor(displayWidth, page)
      const have = urlsRef.current[i]
      const key = `${i}@${scale}`
      if ((have && have.scale >= scale) || loadingRef.current.has(key)) return
      loadingRef.current.add(key)
      fetchObjectUrl(`/projects/${projectId}/source/pages/${i}.png?scale=${scale}`)
        .then(({ url }) => {
          const prev = urlsRef.current[i]
          if (prev && prev.scale >= scale) {
            URL.revokeObjectURL(url)
            return
          }
          if (prev) URL.revokeObjectURL(prev.url)
          urlsRef.current = { ...urlsRef.current, [i]: { url, scale } }
          setUrls(urlsRef.current)
        })
        .catch(() => {})
        .finally(() => loadingRef.current.delete(key))
    })
  }, [info, displayWidth, projectId])

  const target: SourceRef | null = useMemo(() => {
    if (activeBlockId && map?.blocks[activeBlockId]) {
      const b = map.blocks[activeBlockId]
      return { page: b.page, bbox: b.bbox }
    }
    return focus ? { page: focus.page, bbox: focus.bbox } : null
  }, [activeBlockId, map, focus])

  const scrollToTarget = useCallback((t: SourceRef) => {
    const scroller = scrollRef.current
    const pageEl = pageRefs.current[t.page]
    if (!scroller || !pageEl) return
    const h = pageEl.offsetHeight
    const top = pageEl.offsetTop + t.bbox[1] * h
    const bottom = pageEl.offsetTop + t.bbox[3] * h
    const view = scroller.scrollTop
    if (top >= view + 24 && bottom <= view + scroller.clientHeight - 24) return
    scroller.scrollTo({ top: Math.max(0, (top + bottom) / 2 - scroller.clientHeight / 2), behavior: "smooth" })
  }, [])

  useEffect(() => {
    if (target && displayWidth > 0) scrollToTarget(target)
  }, [target, focus?.key, displayWidth, scrollToTarget])

  const openOriginal = async () => {
    if (opening) return
    const win = window.open("", "_blank")
    setOpening(true)
    try {
      const { url } = await fetchObjectUrl(`/projects/${projectId}/preview/source`)
      if (win) win.location.href = url
      else window.location.assign(url)
    } catch {
      win?.close()
    } finally {
      setOpening(false)
    }
  }

  const byPage = useMemo(() => {
    const out: Record<number, [string, SourceMap["blocks"][string]][]> = {}
    for (const [id, b] of Object.entries(map?.blocks ?? {})) (out[b.page] ||= []).push([id, b])
    return out
  }, [map])

  const zoomIndex = ZOOMS.indexOf(zoom)
  const pending = map?.status === "pending"

  return (
    <div className="rounded-2xl overflow-hidden flex flex-col" style={{ background: "#ffffff", border: "1px solid #e7ddc5", minHeight: 0 }}>
      <div
        className="px-4 py-2 flex items-center justify-between gap-2 text-[11px] font-semibold tracking-[0.14em]"
        style={{ color: "#9a9178", background: "#faf5ee", borderBottom: "1px solid #f1e8d1" }}
      >
        <span className="flex items-center gap-2">
          ORIGINAL
          {pending && (
            <span className="text-[10px] font-medium tracking-[0.04em] flex items-center gap-1.5" style={{ color: "#0a7870" }}>
              <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: "#0a7870" }} />
              Linking paragraphs…
            </span>
          )}
        </span>
        <span className="flex items-center gap-1">
          {info?.available && (
            <>
              <ZoomButton label="Zoom out" disabled={zoomIndex <= 0} onClick={() => setZoom(ZOOMS[Math.max(0, zoomIndex - 1)])}>
                <path d="M5 12h14" />
              </ZoomButton>
              <button
                type="button"
                onClick={() => setZoom(1)}
                className="text-[10px] font-semibold tracking-[0.06em] px-1.5 py-0.5 rounded-md tabular-nums hover:bg-[#f3ecdb]"
                style={{ color: zoom === 1 ? "#9a9178" : "#0a5e58" }}
                title="Fit width"
              >
                {zoom === 1 ? "FIT" : `${Math.round(zoom * 100)}%`}
              </button>
              <ZoomButton label="Zoom in" disabled={zoomIndex >= ZOOMS.length - 1} onClick={() => setZoom(ZOOMS[Math.min(ZOOMS.length - 1, zoomIndex + 1)])}>
                <path d="M12 5v14M5 12h14" />
              </ZoomButton>
              <span className="w-px h-3.5 mx-1" style={{ background: "#e7ddc5" }} />
            </>
          )}
          <button
            type="button"
            onClick={() => void openOriginal()}
            className="text-[10px] font-semibold tracking-[0.1em] hover:underline"
            style={{ color: "#0a7870" }}
            title={`Open ${fileName} in a new tab`}
          >
            {opening ? "OPENING…" : "OPEN ↗"}
          </button>
        </span>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-auto relative" style={{ background: "#fbf6ea", minHeight: 0 }} onMouseLeave={() => onHoverBlock(null)}>
        {!info && !failed && (
          <div className="px-4 py-8 text-sm text-center" style={{ color: "#8a8270" }}>
            Loading…
          </div>
        )}
        {(failed || info?.available === false) && (
          <div className="px-4 py-8 text-sm text-center" style={{ color: "#8a8270" }}>
            The original can&apos;t be shown here.
          </div>
        )}
        {info?.available && displayWidth > 0 && (
          <div style={{ padding: PAD, width: displayWidth + PAD * 2 }}>
            {info.pages.map((page, i) => {
              const height = (displayWidth * page.height) / page.width
              const blocks = byPage[i] ?? []
              return (
                <div
                  key={i}
                  ref={(el) => {
                    pageRefs.current[i] = el
                  }}
                  className="relative"
                  style={{
                    width: displayWidth,
                    height,
                    marginBottom: GAP,
                    background: "#ffffff",
                    boxShadow: "0 2px 8px rgba(0,0,0,0.10)",
                  }}
                >
                  {urls[i] && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={urls[i].url} alt={`Page ${i + 1} of the original`} draggable={false} className="absolute inset-0 w-full h-full select-none" />
                  )}
                  {blocks.map(([id, b]) =>
                    b.reading !== "high" ? (
                      <div
                        key={`u-${id}`}
                        className="absolute pointer-events-none tq-src-uncertain"
                        style={rectStyle(b.bbox, 0.006)}
                      />
                    ) : null,
                  )}
                  {blocks.map(([id, b]) => (
                    <button
                      key={id}
                      type="button"
                      aria-label="Show this part of the translation"
                      title={b.reading !== "high" && b.reason ? `Uncertain reading: ${b.reason}` : undefined}
                      onMouseEnter={() => onHoverBlock(id)}
                      onClick={() => onPickBlock(id)}
                      className="absolute tq-src-target"
                      data-hover={hoverBlockId === id && activeBlockId !== id ? "1" : undefined}
                      style={rectStyle(b.bbox)}
                    />
                  ))}
                  {target && target.page === i && (
                    <div
                      key={`${target.bbox.join(",")}-${focus?.key ?? 0}`}
                      className="absolute pointer-events-none tq-src-active"
                      style={rectStyle(target.bbox, 0.006)}
                    />
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
      <style>{`
        .tq-src-target { background: transparent; border-radius: 3px; cursor: pointer; transition: background-color 120ms ease, box-shadow 120ms ease; }
        .tq-src-target:hover, .tq-src-target[data-hover="1"] { background: rgba(10, 120, 112, 0.08); box-shadow: 0 0 0 1px rgba(10, 120, 112, 0.35); }
        .tq-src-uncertain { border-radius: 3px; box-shadow: 0 0 0 1.5px rgba(200, 138, 26, 0.55); background: rgba(246, 227, 184, 0.18); }
        .tq-src-active { border-radius: 4px; background: rgba(10, 120, 112, 0.12); box-shadow: 0 0 0 2px rgba(10, 120, 112, 0.8), 0 0 0 6px rgba(10, 120, 112, 0.12); animation: tq-src-in 220ms ease-out; }
        @keyframes tq-src-in { from { opacity: 0; transform: scale(1.04); } to { opacity: 1; transform: none; } }
      `}</style>
    </div>
  )
}

function ZoomButton({ label, disabled, onClick, children }: { label: string; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="w-6 h-6 rounded-md flex items-center justify-center hover:bg-[#f3ecdb] disabled:opacity-40"
      style={{ color: "#6b6558" }}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
        {children}
      </svg>
    </button>
  )
}
