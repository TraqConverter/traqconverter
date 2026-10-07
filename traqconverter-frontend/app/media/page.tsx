"use client"

import { useEffect, useRef, useState } from "react"
import { api, apiErrorDetail } from "@/lib/api"
import { snapshotFile, UNREADABLE_FILE } from "@/lib/fileSnapshot"
import {
  AUTO_KINDS,
  autoLabel,
  guessFromFileName,
  kindLabel,
  languageName,
  MEDIA_KINDS,
  MEDIA_LANGUAGES,
  type MediaAsset,
  type MediaKind,
} from "@/lib/media"
import ProPaywall from "@/components/ProPaywall"
import { useFeature } from "@/lib/plan"

const ACCEPT = ".png,.jpg,.jpeg,.webp"
const MAX_BYTES = 5 * 1024 * 1024
const FILE_INPUT_ID = "media-upload"

type Filter = "all" | MediaKind

export default function MediaPage() {
  const access = useFeature("media")
  const [assets, setAssets] = useState<MediaAsset[]>([])
  const [canEdit, setCanEdit] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)
  const [uploading, setUploading] = useState(0)
  const [dragOver, setDragOver] = useState(false)
  const [filter, setFilter] = useState<Filter>("all")
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (access !== "allowed") return
    let live = true
    api
      .get<{ assets: MediaAsset[]; can_edit: boolean }>("/media")
      .then((res) => {
        if (!live) return
        setAssets(res.data.assets)
        setCanEdit(res.data.can_edit)
      })
      .catch((err) => live && setError(apiErrorDetail(err, "Couldn't load your media.")))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [access])

  useEffect(() => {
    if (!flash) return
    const t = window.setTimeout(() => setFlash(null), 4000)
    return () => window.clearTimeout(t)
  }, [flash])

  // A new automatic pick unsets the one it replaces; reloading shows that without guessing.
  const reload = async () => {
    try {
      const res = await api.get<{ assets: MediaAsset[]; can_edit: boolean }>("/media")
      setAssets(res.data.assets)
      setCanEdit(res.data.can_edit)
    } catch {
      /* the list on screen stays as it was */
    }
  }

  const addFiles = async (list: FileList | File[] | null | undefined) => {
    const picked = Array.from(list || [])
    if (!picked.length) return
    setError(null)
    let files: File[]
    try {
      files = await Promise.all(picked.map(snapshotFile))
    } catch {
      setError(UNREADABLE_FILE)
      return
    }
    const wrongType = files.find((f) => !/\.(png|jpe?g|webp)$/i.test(f.name))
    if (wrongType) {
      setError(`${wrongType.name} isn't a PNG, JPG or WebP image.`)
      return
    }
    const tooBig = files.find((f) => f.size > MAX_BYTES)
    if (tooBig) {
      setError(`${tooBig.name} is over 5 MB.`)
      return
    }
    setUploading((n) => n + files.length)
    let added = 0
    for (const file of files) {
      const guess = guessFromFileName(file.name)
      const form = new FormData()
      form.append("file", file)
      form.append("kind", guess.kind)
      if (guess.language) form.append("language", guess.language)
      try {
        const res = await api.post<MediaAsset>("/media", form)
        setAssets((list) => [res.data, ...list])
        added += 1
      } catch (err) {
        setError(apiErrorDetail(err, `Couldn't upload ${file.name}.`))
      } finally {
        setUploading((n) => n - 1)
      }
    }
    if (added) setFlash(added === 1 ? "Added. Check its kind and language below." : `Added ${added} pictures. Check their kind and language below.`)
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    if (canEdit) void addFiles(e.dataTransfer.files)
  }

  const save = async (id: string, change: Partial<Pick<MediaAsset, "name" | "kind" | "language" | "auto_use">>) => {
    setError(null)
    try {
      const res = await api.patch<MediaAsset>(`/media/${id}`, change)
      setAssets((list) => list.map((a) => (a.id === id ? res.data : a)))
      if (change.auto_use || change.kind !== undefined || change.language !== undefined) await reload()
      return true
    } catch (err) {
      setError(apiErrorDetail(err, "Couldn't save that change."))
      return false
    }
  }

  const remove = async (id: string) => {
    setError(null)
    try {
      await api.delete(`/media/${id}`)
      setAssets((list) => list.filter((a) => a.id !== id))
      setFlash("Deleted. Documents that already show it keep their copy.")
    } catch (err) {
      setError(apiErrorDetail(err, "Couldn't delete it."))
    }
  }

  if (access === "locked") {
    return (
      <ProPaywall
        feature="Media"
        plan="Basic"
        description="Keep your stamps, logos and signatures in one place. Give each a language and the editor and the certification page use the right one for every project. Upgrade to Basic to start your library."
      />
    )
  }

  const shown = filter === "all" ? assets : assets.filter((a) => a.kind === filter)
  const counts = Object.fromEntries(MEDIA_KINDS.map((k) => [k.value, assets.filter((a) => a.kind === k.value).length]))

  return (
    <div
      className="space-y-6 pb-16"
      onDragOver={(e) => {
        if (!canEdit) return
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) setDragOver(false)
      }}
      onDrop={onDrop}
    >
      <div className="text-[12px] tracking-wide" style={{ color: "#9a9178" }}>
        OnlineDocTranslator <span style={{ color: "#cfc6ad" }}>›</span> Assets{" "}
        <span style={{ color: "#cfc6ad" }}>›</span> <span style={{ color: "#1f2a2e" }}>Media</span>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold tracking-[0.18em] mb-1" style={{ color: "#9a9178" }}>
            MEDIA
          </div>
          <h1 className="text-[28px] font-semibold tracking-tight" style={{ color: "#1f2a2e" }}>
            Stamps, logos and signatures
          </h1>
          <p className="text-sm mt-1 max-w-2xl" style={{ color: "#8a8270" }}>
            Give a stamp or logo a language and turn on Auto: new translations into that language get it on every
            page and on the certification page. Anything here can be placed from the editor with Image → From media.
          </p>
        </div>
        {canEdit && (
          <label
            htmlFor={FILE_INPUT_ID}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault()
                inputRef.current?.click()
              }
            }}
            className="self-start sm:self-auto shrink-0 flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-semibold text-white transition hover:bg-[#0a645d] cursor-pointer select-none"
            style={{ background: "#0a7870" }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
            {uploading ? `Uploading ${uploading}…` : "Upload pictures"}
          </label>
        )}
        <input
          ref={inputRef}
          id={FILE_INPUT_ID}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            void addFiles(e.target.files)
            e.target.value = ""
          }}
        />
      </div>

      {error && (
        <div className="text-sm rounded-lg px-3 py-2" style={{ background: "#f2d4cf", color: "#7a2f24" }}>
          {error}
        </div>
      )}
      {flash && (
        <div className="text-sm rounded-lg px-3 py-2" style={{ background: "#d8ead6", color: "#2d5a24" }}>
          {flash}
        </div>
      )}
      {!canEdit && !loading && (
        <div className="text-sm rounded-lg px-3 py-2" style={{ background: "#faf5ee", color: "#6b6558", border: "1px solid #f1e8d1" }}>
          Your team owner or an admin adds and changes pictures here. You can place any of them from the editor.
        </div>
      )}

      {assets.length > 0 && (
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Kind">
          {([{ value: "all", plural: "All" }, ...MEDIA_KINDS] as { value: Filter; plural: string }[]).map((k) => {
            const active = filter === k.value
            const n = k.value === "all" ? assets.length : counts[k.value]
            return (
              <button
                key={k.value}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(k.value)}
                className="text-xs font-medium px-3 py-1.5 rounded-full transition"
                style={{
                  background: active ? "#1f2a2e" : "#ffffff",
                  color: active ? "#ffffff" : "#4a4638",
                  border: `1px solid ${active ? "#1f2a2e" : "#e7ddc5"}`,
                }}
              >
                {k.plural} <span style={{ opacity: 0.65 }}>{n}</span>
              </button>
            )
          })}
        </div>
      )}

      <div
        className="rounded-2xl transition"
        style={{
          outline: dragOver ? "2px dashed #0a7870" : "none",
          outlineOffset: 4,
        }}
      >
        {loading ? (
          <div className="rounded-2xl px-5 py-12 text-center text-sm" style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#8a8270" }}>
            Loading media…
          </div>
        ) : assets.length === 0 ? (
          <EmptyState canEdit={canEdit} />
        ) : shown.length === 0 ? (
          <div className="rounded-2xl px-5 py-12 text-center text-sm" style={{ background: "#ffffff", border: "1px solid #e7ddc5", color: "#8a8270" }}>
            Nothing of this kind yet.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-4">
            {shown.map((a) => (
              <MediaCard key={a.id} asset={a} canEdit={canEdit} onSave={save} onDelete={remove} />
            ))}
          </div>
        )}
      </div>
      {canEdit && assets.length > 0 && (
        <div className="text-xs" style={{ color: "#9a9178" }}>
          PNG, JPG or WebP up to 5 MB. Drop files anywhere on this page to add them. A stamp scanned on white paper gets a
          see-through background when it&apos;s placed.
        </div>
      )}
    </div>
  )
}

function EmptyState({ canEdit }: { canEdit: boolean }) {
  return (
    <div className="rounded-2xl px-6 py-14 text-center" style={{ background: "#ffffff", border: "2px dashed #e7ddc5" }}>
      <div
        className="mx-auto mb-4 w-14 h-14 rounded-2xl flex items-center justify-center"
        style={{ background: "#cfe6e2", color: "#0a7870" }}
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <circle cx="9" cy="10" r="2" />
          <path d="m21 16-5-5-9 9" />
        </svg>
      </div>
      <div className="text-[16px] font-semibold mb-1" style={{ color: "#1f2a2e" }}>
        No pictures yet
      </div>
      <div className="text-sm max-w-md mx-auto" style={{ color: "#8a8270" }}>
        {canEdit
          ? "Upload your stamps and logos, one per language if they differ (an EN and an IT stamp, say). Drop files here or use Upload pictures."
          : "Your team owner or an admin can upload the team's stamps and logos here."}
      </div>
    </div>
  )
}

type Change = Partial<Pick<MediaAsset, "name" | "kind" | "language" | "auto_use">>

function MediaCard({
  asset,
  canEdit,
  onSave,
  onDelete,
}: {
  asset: MediaAsset
  canEdit: boolean
  onSave: (id: string, change: Change) => Promise<boolean>
  onDelete: (id: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState(asset.name)
  const [kind, setKind] = useState<MediaKind>(asset.kind)
  const [language, setLanguage] = useState<string>(asset.language ?? "")
  const [auto, setAuto] = useState(asset.auto_use)
  const auto_ = autoLabel(asset)
  const canAuto = AUTO_KINDS.includes(kind)

  const startEdit = () => {
    setName(asset.name)
    setKind(asset.kind)
    setLanguage(asset.language ?? "")
    setAuto(asset.auto_use)
    setEditing(true)
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    const ok = await onSave(asset.id, {
      name: name.trim(),
      kind,
      language: language || null,
      auto_use: canAuto && auto,
    })
    setBusy(false)
    if (ok) setEditing(false)
  }

  return (
    <div className="rounded-2xl overflow-hidden flex flex-col" style={{ background: "#ffffff", border: "1px solid #e7ddc5" }}>
      <div
        className="h-40 flex items-center justify-center p-4"
        style={{
          backgroundColor: "#faf7f0",
          backgroundImage:
            "linear-gradient(45deg, #f1ebdc 25%, transparent 25%), linear-gradient(-45deg, #f1ebdc 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #f1ebdc 75%), linear-gradient(-45deg, transparent 75%, #f1ebdc 75%)",
          backgroundSize: "16px 16px",
          backgroundPosition: "0 0, 0 8px, 8px -8px, -8px 0",
          borderBottom: "1px solid #f1e8d1",
        }}
      >
        {asset.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={asset.url} alt={asset.name} className="max-h-full max-w-full object-contain" />
        ) : (
          <span className="text-xs" style={{ color: "#9a9178" }}>
            Preview unavailable
          </span>
        )}
      </div>

      {editing ? (
        <form onSubmit={submit} className="p-4 space-y-3">
          <Field label="NAME" htmlFor={`name-${asset.id}`}>
            <input
              id={`name-${asset.id}`}
              value={name}
              maxLength={80}
              onChange={(e) => setName(e.target.value)}
              className="w-full text-sm rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-[#9bc9c5]"
              style={{ border: "1px solid #e7ddc5", color: "#1f2a2e" }}
            />
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="KIND" htmlFor={`kind-${asset.id}`}>
              <select
                id={`kind-${asset.id}`}
                value={kind}
                onChange={(e) => setKind(e.target.value as MediaKind)}
                className="w-full text-sm rounded-lg px-2 py-2 bg-white"
                style={{ border: "1px solid #e7ddc5", color: "#1f2a2e" }}
              >
                {MEDIA_KINDS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="LANGUAGE" htmlFor={`lang-${asset.id}`}>
              <select
                id={`lang-${asset.id}`}
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full text-sm rounded-lg px-2 py-2 bg-white"
                style={{ border: "1px solid #e7ddc5", color: "#1f2a2e" }}
              >
                <option value="">Any language</option>
                {MEDIA_LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.name} ({l.code.toUpperCase()})
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {canAuto && (
            <label className="flex items-start gap-2.5 text-sm cursor-pointer" style={{ color: "#1f2a2e" }}>
              <input
                type="checkbox"
                checked={auto}
                onChange={(e) => setAuto(e.target.checked)}
                className="mt-0.5 w-4 h-4 accent-[#0a7870]"
              />
              <span>
                Use automatically{" "}
                <span style={{ color: "#8a8270" }}>
                  {language
                    ? `for translations into ${languageName(language)}`
                    : "for any language without its own"}
                  {kind === "stamp" ? " (page stamp and certification page)" : " (certification page)"}
                </span>
              </span>
            </label>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="submit"
              disabled={busy || !name.trim()}
              className="text-sm font-semibold px-4 py-1.5 rounded-full text-white"
              style={{ background: busy || !name.trim() ? "#9bc9c5" : "#0a7870" }}
            >
              {busy ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="text-sm px-4 py-1.5 rounded-full"
              style={{ border: "1px solid #e7ddc5", color: "#4a4638" }}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="p-4 flex-1 flex flex-col gap-2.5">
          <div className="font-medium text-sm break-words" style={{ color: "#1f2a2e" }}>
            {asset.name}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Chip tone="neutral">{kindLabel(asset.kind)}</Chip>
            <Chip tone="lang" title={languageName(asset.language)}>
              {asset.language ? asset.language.toUpperCase() : "Any language"}
            </Chip>
            {auto_ && <Chip tone="auto">{auto_}</Chip>}
          </div>
          {asset.width_px && asset.height_px ? (
            <div className="text-xs" style={{ color: "#9a9178" }}>
              {asset.width_px} × {asset.height_px} px
            </div>
          ) : null}
          {canEdit && (
            <div className="flex flex-wrap gap-1.5 mt-auto pt-1">
              {confirming ? (
                <>
                  <span className="text-xs self-center mr-1" style={{ color: "#7a2f24" }}>
                    Delete it?
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true)
                      await onDelete(asset.id)
                      setBusy(false)
                      setConfirming(false)
                    }}
                    className="text-xs font-medium px-2.5 py-1 rounded-full"
                    style={{ background: "#7a2f24", color: "#fff", opacity: busy ? 0.6 : 1 }}
                  >
                    Delete
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirming(false)}
                    className="text-xs px-2.5 py-1 rounded-full"
                    style={{ border: "1px solid #e7ddc5", color: "#4a4638" }}
                  >
                    Keep
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={startEdit}
                    className="text-xs px-2.5 py-1 rounded-full transition hover:bg-[#faf5ee]"
                    style={{ border: "1px solid #e7ddc5", color: "#4a4638" }}
                  >
                    Edit
                  </button>
                  {AUTO_KINDS.includes(asset.kind) && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={async () => {
                        setBusy(true)
                        await onSave(asset.id, { auto_use: !asset.auto_use })
                        setBusy(false)
                      }}
                      className="text-xs px-2.5 py-1 rounded-full transition hover:bg-[#faf5ee]"
                      style={{ border: "1px solid #e7ddc5", color: "#4a4638" }}
                    >
                      {asset.auto_use ? "Turn Auto off" : "Use automatically"}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setConfirming(true)}
                    className="text-xs px-2.5 py-1 rounded-full transition hover:bg-[#f2d4cf]"
                    style={{ border: "1px solid #e7ddc5", color: "#7a2f24" }}
                  >
                    Delete
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-[10px] font-semibold tracking-[0.14em] mb-1" style={{ color: "#9a9178" }}>
        {label}
      </label>
      {children}
    </div>
  )
}

function Chip({ tone, title, children }: { tone: "neutral" | "lang" | "auto"; title?: string; children: React.ReactNode }) {
  const style =
    tone === "auto"
      ? { background: "#0a7870", color: "#ffffff", border: "1px solid #0a645d" }
      : tone === "lang"
        ? { background: "#cfe6e2", color: "#0a5e58", border: "1px solid #b7dad4" }
        : { background: "#faf5ee", color: "#4a4638", border: "1px solid #e7ddc5" }
  return (
    <span title={title} className="inline-flex items-center text-[10px] font-semibold tracking-[0.04em] px-1.5 py-0.5 rounded-md" style={style}>
      {children}
    </span>
  )
}
