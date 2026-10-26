export type LangOption = {
  code: string
  flag: string
  name: string
}

const ENGLISH: LangOption[] = [
  { code: "en-GB", flag: "GB", name: "English (UK)" },
  { code: "en-US", flag: "US", name: "English (US)" },
]

// Everything after English, listed alphabetically. Keep in step with LANGUAGE_NAMES in the backend.
const OTHERS: LangOption[] = [
  { code: "af-ZA", flag: "ZA", name: "Afrikaans" },
  { code: "sq-AL", flag: "AL", name: "Albanian" },
  { code: "am-ET", flag: "ET", name: "Amharic" },
  { code: "ar-SA", flag: "SA", name: "Arabic" },
  { code: "hy-AM", flag: "AM", name: "Armenian" },
  { code: "az-AZ", flag: "AZ", name: "Azerbaijani" },
  { code: "eu-ES", flag: "EUS", name: "Basque" },
  { code: "bn-BD", flag: "BD", name: "Bengali" },
  { code: "bs-BA", flag: "BA", name: "Bosnian" },
  { code: "bg-BG", flag: "BG", name: "Bulgarian" },
  { code: "my-MM", flag: "MM", name: "Burmese" },
  { code: "ca-ES", flag: "CAT", name: "Catalan" },
  { code: "zh-CN", flag: "CN", name: "Chinese (Simplified)" },
  { code: "zh-TW", flag: "TW", name: "Chinese (Traditional)" },
  { code: "hr-HR", flag: "HR", name: "Croatian" },
  { code: "cs-CZ", flag: "CZ", name: "Czech" },
  { code: "da-DK", flag: "DK", name: "Danish" },
  { code: "prs-AF", flag: "AF", name: "Dari" },
  { code: "nl-NL", flag: "NL", name: "Dutch" },
  { code: "et-EE", flag: "EE", name: "Estonian" },
  { code: "fil-PH", flag: "PH", name: "Filipino (Tagalog)" },
  { code: "fi-FI", flag: "FI", name: "Finnish" },
  { code: "fr-FR", flag: "FR", name: "French" },
  { code: "gl-ES", flag: "GAL", name: "Galician" },
  { code: "ka-GE", flag: "GE", name: "Georgian" },
  { code: "de-DE", flag: "DE", name: "German" },
  { code: "el-GR", flag: "GR", name: "Greek" },
  { code: "gu-IN", flag: "IN", name: "Gujarati" },
  { code: "ht-HT", flag: "HT", name: "Haitian Creole" },
  { code: "ha-NG", flag: "NG", name: "Hausa" },
  { code: "he-IL", flag: "IL", name: "Hebrew" },
  { code: "hi-IN", flag: "IN", name: "Hindi" },
  { code: "hu-HU", flag: "HU", name: "Hungarian" },
  { code: "is-IS", flag: "IS", name: "Icelandic" },
  { code: "ig-NG", flag: "NG", name: "Igbo" },
  { code: "id-ID", flag: "ID", name: "Indonesian" },
  { code: "it-IT", flag: "IT", name: "Italian" },
  { code: "ja-JP", flag: "JP", name: "Japanese" },
  { code: "kk-KZ", flag: "KZ", name: "Kazakh" },
  { code: "km-KH", flag: "KH", name: "Khmer" },
  { code: "ko-KR", flag: "KR", name: "Korean" },
  { code: "ku", flag: "KU", name: "Kurdish (Kurmanji)" },
  { code: "ckb", flag: "CKB", name: "Kurdish (Sorani)" },
  { code: "lv-LV", flag: "LV", name: "Latvian" },
  { code: "lt-LT", flag: "LT", name: "Lithuanian" },
  { code: "mk-MK", flag: "MK", name: "Macedonian" },
  { code: "ms-MY", flag: "MY", name: "Malay" },
  { code: "mt-MT", flag: "MT", name: "Maltese" },
  { code: "mn-MN", flag: "MN", name: "Mongolian" },
  { code: "ne-NP", flag: "NP", name: "Nepali" },
  { code: "no-NO", flag: "NO", name: "Norwegian" },
  { code: "ps-AF", flag: "AF", name: "Pashto" },
  { code: "fa-IR", flag: "IR", name: "Persian (Farsi)" },
  { code: "pl-PL", flag: "PL", name: "Polish" },
  { code: "pt-PT", flag: "PT", name: "Portuguese" },
  { code: "pt-BR", flag: "BR", name: "Portuguese (Brazil)" },
  { code: "pa-IN", flag: "IN", name: "Punjabi (Gurmukhi)" },
  { code: "ro-RO", flag: "RO", name: "Romanian" },
  { code: "ru-RU", flag: "RU", name: "Russian" },
  { code: "sr-RS", flag: "RS", name: "Serbian" },
  { code: "si-LK", flag: "LK", name: "Sinhala" },
  { code: "sk-SK", flag: "SK", name: "Slovak" },
  { code: "sl-SI", flag: "SI", name: "Slovenian" },
  { code: "so-SO", flag: "SO", name: "Somali" },
  { code: "es-ES", flag: "ES", name: "Spanish" },
  { code: "sw-KE", flag: "KE", name: "Swahili" },
  { code: "sv-SE", flag: "SE", name: "Swedish" },
  { code: "ta-IN", flag: "IN", name: "Tamil" },
  { code: "th-TH", flag: "TH", name: "Thai" },
  { code: "ti-ER", flag: "ER", name: "Tigrinya" },
  { code: "tr-TR", flag: "TR", name: "Turkish" },
  { code: "uk-UA", flag: "UA", name: "Ukrainian" },
  { code: "ur-PK", flag: "PK", name: "Urdu" },
  { code: "uz-UZ", flag: "UZ", name: "Uzbek" },
  { code: "vi-VN", flag: "VN", name: "Vietnamese" },
  { code: "yo-NG", flag: "NG", name: "Yoruba" },
]

export const TARGET_LANGUAGES: LangOption[] = [...ENGLISH, ...OTHERS]

export const SOURCE_LANGUAGES: LangOption[] = [{ code: "auto", flag: "AUTO", name: "Auto-detect" }, ...TARGET_LANGUAGES]

// Written right to left; the editor and exports set the text direction for these.
export const RTL_LANGUAGES = new Set(["ar", "he", "fa", "prs", "ps", "ur", "ckb"])

export function baseLanguage(code: string | null | undefined): string | null {
  const base = (code || "").trim().toLowerCase().split(/[-_]/)[0]
  return /^[a-z]{2,3}$/.test(base) ? base : null
}

export function isRtl(code: string | null | undefined): boolean {
  const base = baseLanguage(code)
  return !!base && RTL_LANGUAGES.has(base)
}

const VARIANTS = (() => {
  const n = new Map<string, number>()
  for (const l of TARGET_LANGUAGES) {
    const b = baseLanguage(l.code)
    if (b) n.set(b, (n.get(b) ?? 0) + 1)
  }
  return n
})()

// One entry per base language: "English", not UK and US; a name like "Kurdish (Sorani)" keeps its qualifier.
export const BASE_LANGUAGES: { code: string; name: string }[] = (() => {
  const seen = new Map<string, string>()
  for (const l of TARGET_LANGUAGES) {
    const code = baseLanguage(l.code)
    if (!code || seen.has(code)) continue
    seen.set(code, (VARIANTS.get(code) ?? 0) > 1 ? l.name.replace(/\s*\(.*\)$/, "") : l.name)
  }
  return Array.from(seen, ([code, name]) => ({ code, name }))
})()

// The regional entries of languages offered in more than one variant (en-GB, en-US, pt-BR...).
export const REGIONAL_LANGUAGES: { code: string; name: string }[] = TARGET_LANGUAGES.filter(
  (l) => (VARIANTS.get(baseLanguage(l.code) ?? "") ?? 0) > 1,
).map(({ code, name }) => ({ code, name }))

export const LANGUAGE_COUNT = BASE_LANGUAGES.length
