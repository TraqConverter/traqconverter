import { TARGET_LANGUAGES } from "@/components/LangSelect"

export type MediaKind = "stamp" | "logo" | "signature" | "other"

export type MediaAsset = {
  id: string
  name: string
  kind: MediaKind
  language: string | null
  auto_use: boolean
  mime_type: string | null
  width_px: number | null
  height_px: number | null
  size_bytes: number | null
  created_at: string | null
  url: string | null
}

export const MEDIA_KINDS: { value: MediaKind; label: string; plural: string }[] = [
  { value: "stamp", label: "Stamp", plural: "Stamps" },
  { value: "logo", label: "Logo", plural: "Logos" },
  { value: "signature", label: "Signature", plural: "Signatures" },
  { value: "other", label: "Other", plural: "Other" },
]

// Only these are picked automatically by the project's target language.
export const AUTO_KINDS: MediaKind[] = ["stamp", "logo"]

export function kindLabel(kind: MediaKind): string {
  return MEDIA_KINDS.find((k) => k.value === kind)?.label ?? kind
}

export function baseLanguage(code: string | null | undefined): string | null {
  const base = (code || "").trim().toLowerCase().split(/[-_]/)[0]
  return /^[a-z]{2,3}$/.test(base) ? base : null
}

// The New project language list, one entry per base language ("English", not UK and US).
export const MEDIA_LANGUAGES: { code: string; name: string }[] = (() => {
  const seen = new Map<string, string>()
  for (const l of TARGET_LANGUAGES) {
    const code = baseLanguage(l.code)
    if (code && !seen.has(code)) seen.set(code, l.name.replace(/\s*\(.*\)$/, ""))
  }
  return Array.from(seen, ([code, name]) => ({ code, name }))
})()

export function languageName(code: string | null): string {
  if (!code) return "Any language"
  return MEDIA_LANGUAGES.find((l) => l.code === code)?.name ?? code.toUpperCase()
}

export function autoLabel(asset: Pick<MediaAsset, "auto_use" | "language">): string | null {
  if (!asset.auto_use) return null
  return asset.language ? `Auto for ${asset.language.toUpperCase()}` : "Auto, any language"
}

// A first guess from the file name ("ISO_stamp_EN.png" is an English stamp); editable afterwards.
export function guessFromFileName(name: string): { kind: MediaKind; language: string | null } {
  const stem = name.replace(/\.[^.]+$/, "").toLowerCase()
  const words = stem.split(/[^a-z]+/).filter(Boolean)
  const kind: MediaKind = words.some((w) => ["stamp", "timbro", "seal", "sello", "carimbo", "stempel"].includes(w))
    ? "stamp"
    : words.some((w) => ["logo", "header", "letterhead"].includes(w))
      ? "logo"
      : words.some((w) => ["signature", "firma", "sign", "assinatura"].includes(w))
        ? "signature"
        : "other"
  // Upper case only, so "it" or "no" inside an ordinary name isn't read as a language.
  const tags = name.replace(/\.[^.]+$/, "").split(/[^A-Za-z]+/).filter((w) => /^[A-Z]{2}$/.test(w))
  const language = tags.map((w) => w.toLowerCase()).find((w) => MEDIA_LANGUAGES.some((l) => l.code === w)) ?? null
  return { kind, language }
}
