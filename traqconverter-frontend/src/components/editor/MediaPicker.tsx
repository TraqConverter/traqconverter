"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { api, apiErrorDetail } from "@/lib/api"
import { useFeature } from "@/lib/plan"
import { autoLabel, kindLabel, MEDIA_KINDS, type MediaAsset, type MediaKind } from "@/lib/media"

export type Placement = {
  scope: "page" | "all"
  vertical: "top" | "bottom" | "cursor"
  align: "left" | "center" | "right"
  width_cm: number
}

const SIZES = [
  { label: "S", width: 2.5 },
  { label: "M", width: 3.5 },
  { label: "L", width: 5 },
]

type Spot = { vertical: "top" | "bottom"; align: Placement["align"] }
const SPOTS: Spot[] = (["top", "bottom"] as const).flatMap((vertical) =>
  (["left", "center", "right"] as const).map((align) => ({ vertical, align })),
)

export default function MediaPicker({
  projectId,
  busy,
  onPlace,
  onClose,
}: {
  projectId: string
  busy: boolean
  onPlace: (asset: MediaAsset, placement: Placement) => Promise<boolean>
  onClose: () => void
}) {
  const access = useFeature("media")
  const [assets, setAssets] = useState<MediaAsset[] | null>(null)
  const [language, setLanguage] = useState<string | null>(null)
  const [error, setError] = useState("")
  const [mine, setMine] = useState(true)
  const [kind, setKind] = useState<"all" | MediaKind>("all")
  const [picked, setPicked] = useState<string | null>(null)
  const [scope, setScope] = useState<Placement["scope"]>("page")
  const [spot, setSpot] = useState<Spot | "cursor">({ vertical: "bottom", align: "right" })
  const [width, setWidth] = useState(3.5)

  useEffect(() => {
    if (access !== "allowed") return
    let live = true
    api
      .get<{ language: string | null; assets: MediaAsset[] }>(`/projects/${projectId}/document/media`)
      .then((res) => {
        if (!live) return
        setAssets(res.data.assets)
        setLanguage(res.data.language)
        // Nothing for this language: start on everything rather than an empty grid.
        if (!res.data.assets.some((a) => a.language === res.data.language)) setMine(false)
        setPicked(res.data.assets[0]?.id ?? null)
      })
      .catch((err) => live && setError(apiErrorDetail(err, "Couldn't load your media.")))
    return () => {
      live = false
    }
  }, [access, projectId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  const shown = (assets ?? []).filter(
    (a) => (!mine || !language || a.language === language) && (kind === "all" || a.kind === kind),
  )
  const asset = (assets ?? []).find((a) => a.id === picked) ?? null
  const tag = language ? language.toUpperCase() : ""

  const place = async () => {
    if (!asset) return
    const placement: Placement =
      spot === "cursor"
        ? { scope: "page", vertical: "cursor", align: "left", width_cm: width }
        : { scope, vertical: spot.vertical, align: spot.align, width_cm: width }
    if (await onPlace(asset, placement)) onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-3 sm:p-6 text-[12px] font-normal tracking-normal"
      style={{ background: "rgba(31,42,46,0.35)" }}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="media-picker-title"
        className="w-full max-w-2xl max-h-[92vh] flex flex-col rounded-2xl overflow-hidden tq-pop"
        style={{ background: "#ffffff", border: "1px solid #e7ddc5", boxShadow: "0 24px 60px rgba(30,30,20,0.25)", color: "#1f2a2e" }}
      >
        <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: "1px solid #f1e8d1" }}>
          <div>
            <div className="text-[10px] font-semibold tracking-[0.14em]" style={{ color: "#9a9178" }}>
              IMAGE
            </div>
            <h2 id="media-picker-title" className="text-[15px] font-semibold">
              From media
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-[#faf5ee]"
            style={{ color: "#6b6558" }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>

        {access === "locked" ? (
          <div className="p-6 text-sm" style={{ color: "#4a4638" }}>
            The media library is part of Basic and up. Upgrade in{" "}
            <Link href="/billing" className="font-semibold underline" style={{ color: "#0a7870" }}>
              Billing
            </Link>{" "}
            to keep your stamps and logos there and place them on every page.
          </div>
        ) : error ? (
          <div className="p-6 text-sm" style={{ color: "#7a2f24" }}>
            {error}
          </div>
        ) : assets === null ? (
          <div className="p-6 text-sm" style={{ color: "#8a8270" }}>
            Loading your media…
          </div>
        ) : assets.length === 0 ? (
          <div className="p-6 text-sm space-y-2" style={{ color: "#4a4638" }}>
            <p>Your media library is empty.</p>
            <p>
              Add your stamps, logos and signatures in{" "}
              <Link href="/media" className="font-semibold underline" style={{ color: "#0a7870" }}>
                Media
              </Link>
              , then place them here.
            </p>
          </div>
        ) : (
          <>
            <div className="px-4 pt-3 flex flex-wrap items-center gap-1.5">
              {language && (
                <div className="inline-flex rounded-full p-0.5 mr-1" style={{ background: "#faf5ee", border: "1px solid #e7ddc5" }}>
                  {[
                    { on: true, label: `For ${tag}` },
                    { on: false, label: "All" },
                  ].map((o) => (
                    <button
                      key={o.label}
                      type="button"
                      aria-pressed={mine === o.on}
                      onClick={() => setMine(o.on)}
                      className="text-[11px] font-semibold px-2.5 py-1 rounded-full"
                      style={mine === o.on ? { background: "#ffffff", color: "#0a5e58", boxShadow: "0 1px 2px rgba(30,30,20,0.08)" } : { color: "#6b6558" }}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
              )}
              {([{ value: "all", plural: "All kinds" }, ...MEDIA_KINDS] as { value: "all" | MediaKind; plural: string }[]).map((k) => (
                <button
                  key={k.value}
                  type="button"
                  aria-pressed={kind === k.value}
                  onClick={() => setKind(k.value)}
                  className="text-[11px] px-2.5 py-1 rounded-full"
                  style={
                    kind === k.value
                      ? { background: "#1f2a2e", color: "#ffffff", border: "1px solid #1f2a2e" }
                      : { background: "#ffffff", color: "#4a4638", border: "1px solid #e7ddc5" }
                  }
                >
                  {k.plural}
                </button>
              ))}
            </div>

            <div className="px-4 py-3 overflow-y-auto min-h-[120px]" style={{ maxHeight: "34vh" }}>
              {shown.length === 0 ? (
                <div className="text-sm py-6 text-center" style={{ color: "#8a8270" }}>
                  Nothing here{mine && tag ? ` for ${tag}` : ""}.{" "}
                  {mine && (
                    <button type="button" onClick={() => setMine(false)} className="font-semibold underline" style={{ color: "#0a7870" }}>
                      Show all
                    </button>
                  )}
                </div>
              ) : (
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                  {shown.map((a) => {
                    const active = a.id === picked
                    const auto = autoLabel(a)
                    return (
                      <button
                        key={a.id}
                        type="button"
                        aria-pressed={active}
                        onClick={() => setPicked(a.id)}
                        title={a.name}
                        className="rounded-xl p-1.5 text-left transition"
                        style={{ border: `2px solid ${active ? "#0a7870" : "#f1e8d1"}`, background: active ? "#f3faf8" : "#ffffff" }}
                      >
                        <div className="h-16 sm:h-20 flex items-center justify-center rounded-lg" style={{ background: "#faf7f0" }}>
                          {a.url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img src={a.url} alt="" className="max-h-full max-w-full object-contain" />
                          ) : null}
                        </div>
                        <div className="mt-1 text-[11px] font-medium truncate">{a.name}</div>
                        <div className="text-[10px] truncate" style={{ color: "#9a9178" }}>
                          {kindLabel(a.kind)} · {a.language ? a.language.toUpperCase() : "Any"}
                          {auto ? " · Auto" : ""}
                        </div>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            <div className="px-4 py-3 space-y-3 text-[12px]" style={{ borderTop: "1px solid #f1e8d1", background: "#fdfbf6" }}>
              <div className="grid grid-cols-1 sm:grid-cols-[auto_1fr] gap-x-4 gap-y-3 items-start">
                <div className="text-[10px] font-semibold tracking-[0.14em] pt-1.5" style={{ color: "#9a9178" }}>
                  PAGES
                </div>
                <div className="flex gap-1" role="group" aria-label="Pages">
                  {(
                    [
                      { value: "page", label: "This page" },
                      { value: "all", label: "Every page" },
                    ] as const
                  ).map((o) => (
                    <Choice
                      key={o.value}
                      active={scope === o.value}
                      onClick={() => {
                        setScope(o.value)
                        if (o.value === "all" && spot === "cursor") setSpot({ vertical: "bottom", align: "right" })
                      }}
                    >
                      {o.label}
                    </Choice>
                  ))}
                </div>

                <div className="text-[10px] font-semibold tracking-[0.14em] pt-1.5" style={{ color: "#9a9178" }}>
                  POSITION
                </div>
                <div className="space-y-1">
                  <div className="grid grid-cols-3 gap-1 max-w-[300px]" role="group" aria-label="Position on the page">
                    {SPOTS.map((s) => {
                      const active = spot !== "cursor" && spot.vertical === s.vertical && spot.align === s.align
                      const label = `${s.vertical === "top" ? "Top" : "Bottom"} ${s.align === "center" ? "centre" : s.align}`
                      return (
                        <Choice key={label} active={active} onClick={() => setSpot(s)}>
                          {label}
                        </Choice>
                      )
                    })}
                  </div>
                  <Choice
                    active={spot === "cursor"}
                    disabled={scope === "all"}
                    onClick={() => setSpot("cursor")}
                    title={scope === "all" ? "At the cursor is for this page only" : undefined}
                  >
                    At the cursor
                  </Choice>
                </div>

                <div className="text-[10px] font-semibold tracking-[0.14em] pt-1.5" style={{ color: "#9a9178" }}>
                  SIZE
                </div>
                <div className="flex items-center gap-1" role="group" aria-label="Size">
                  {SIZES.map((s) => (
                    <Choice key={s.label} active={width === s.width} onClick={() => setWidth(s.width)}>
                      {s.label} <span style={{ opacity: 0.6 }}>{s.width} cm</span>
                    </Choice>
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                <span className="text-[11px]" style={{ color: "#8a8270" }}>
                  {scope === "all" ? "Skips the certification page. " : ""}Move, resize or remove it afterwards like any picture.
                </span>
                <button
                  type="button"
                  onClick={() => void place()}
                  disabled={!asset || busy}
                  className="text-[13px] font-semibold px-4 py-2 rounded-full text-white disabled:opacity-60"
                  style={{ background: "#0a7870" }}
                >
                  {busy ? "Placing…" : scope === "all" ? "Place on every page" : "Place"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function Choice({
  active,
  disabled,
  onClick,
  title,
  children,
}: {
  active: boolean
  disabled?: boolean
  onClick: () => void
  title?: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      title={title}
      className="text-[11px] px-2.5 py-1.5 rounded-md disabled:opacity-40 disabled:cursor-not-allowed"
      style={
        active
          ? { background: "#e3f1ee", color: "#0a5e58", border: "1px solid #b7dad4", fontWeight: 600 }
          : { background: "#ffffff", color: "#4a4638", border: "1px solid #e7ddc5" }
      }
    >
      {children}
    </button>
  )
}
