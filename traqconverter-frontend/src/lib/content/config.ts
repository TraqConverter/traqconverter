/**
 * Where the content section lives, and the palette it borrows.
 *
 * The root is the converter's landing page and twenty-two app routes sit beside
 * it, so a catch-all at the root would swallow /dashboard and /editor. The
 * content needs a prefix, and it is a single constant here: changing it moves
 * the whole section, and the sitemap and canonicals follow.
 *
 * `guides` rather than `translate`: it cannot be mistaken for an action in the
 * tool, and it reads as editorial to the audience this is written for —
 * translators and agencies, not people with a document.
 */
export const CONTENT_BASE = "guides"

export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.onlinedoctranslator.ai").replace(/\/$/, "")

export const SITE_NAME = "OnlineDocTranslator"

/** `/guides/<slug>`, and the section root for the home page of the section. */
export function contentHref(slug: string): string {
  return slug === "home" ? `/${CONTENT_BASE}` : `/${CONTENT_BASE}/${slug}`
}

export function contentUrl(slug: string): string {
  return `${SITE_URL}${contentHref(slug)}`
}

/**
 * The landing page's palette, lifted from app/page.tsx where it is declared as
 * local constants. Shared here so the content section cannot drift from the
 * product it sits inside — a content area in a different palette reads as a
 * bolted-on blog, which is what it must not look like.
 */
export const COLOR = {
  cream: "#faf5ee",
  creamDark: "#f3ecdb",
  teal: "#0a7870",
  tealDark: "#0a5e58",
  tealSoft: "#cfe6e2",
  text: "#1f2a2e",
  muted: "#6b6558",
  subtle: "#8a8270",
} as const

/** Human label for a page type, used as the eyebrow above the H1. */
export const TYPE_LABEL: Record<string, string> = {
  tool: "Tools and software",
  certify: "Certifying a translation",
  credential: "Credentials",
  workflow: "Production workflow",
  practice: "Running your practice",
  question: "Answer",
  legal: "",
  generic: "",
  home: "",
}
