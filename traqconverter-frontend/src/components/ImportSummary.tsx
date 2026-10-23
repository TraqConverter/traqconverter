"use client"

export type ImportResult = {
  format: string
  imported: number
  updated: number
  duplicates: number
  conflicts: number
  unsupported_language: number
  invalid: number
  unconfirmed?: number
  skipped: number
}

const FORMAT_LABELS: Record<string, string> = {
  tmx: "TMX",
  xliff: "XLIFF",
  sdlxliff: "Trados SDLXLIFF",
  csv: "CSV",
  tbx: "TBX",
}

export default function ImportSummary({
  result,
  unit,
  onClose,
}: {
  result: ImportResult
  unit: "entries" | "terms"
  onClose: () => void
}) {
  const rows: { label: string; value: number; hint: string }[] = [
    { label: "Added", value: result.imported, hint: `New ${unit}` },
    { label: "Updated", value: result.updated, hint: "Replaced an AI draft, a learned term or, if you chose it, an older translation" },
    { label: "Already there", value: result.duplicates, hint: "Same source and translation, so skipped" },
    { label: "Kept yours", value: result.conflicts, hint: "You already have a different translation; tick “Replace” and import again to overwrite" },
    { label: "Language not supported", value: result.unsupported_language, hint: "The file's language code isn't one the app translates" },
    { label: "Unconfirmed", value: result.unconfirmed ?? 0, hint: "Segments not confirmed or approved in the CAT tool" },
    { label: "Invalid", value: result.invalid, hint: "Empty, too long, or missing a translation" },
  ].filter((r) => r.value > 0 || r.label === "Added")

  return (
    <div className="rounded-2xl p-4 sm:p-5" style={{ background: "#ffffff", border: "1px solid #b7dad4" }}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="text-[11px] font-semibold tracking-[0.14em]" style={{ color: "#9a9178" }}>
            IMPORT FINISHED · {FORMAT_LABELS[result.format] || result.format.toUpperCase()}
          </div>
          <div className="text-sm mt-1" style={{ color: "#1f2a2e" }}>
            {result.imported.toLocaleString()} added
            {result.updated ? `, ${result.updated.toLocaleString()} updated` : ""}
            {result.skipped ? `, ${result.skipped.toLocaleString()} skipped` : ""}.
          </div>
        </div>
        <button type="button" onClick={onClose} className="font-semibold" style={{ color: "#8a8270" }} aria-label="Close">
          ×
        </button>
      </div>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between gap-3" title={r.hint}>
            <dt style={{ color: "#4a4638" }}>{r.label}</dt>
            <dd className="font-semibold tabular-nums" style={{ color: "#1f2a2e" }}>
              {r.value.toLocaleString()}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
