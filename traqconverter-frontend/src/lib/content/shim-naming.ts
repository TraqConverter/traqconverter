export type PageType =
  | "tool"
  | "certify"
  | "credential"
  | "workflow"
  | "practice"
  | "question"
  | "legal"
  | "generic"
  | "home"

export type Faq = { q: string; a: string }

export type ContentPage = {
  slug: string
  title: string
  h1: string
  meta_description: string
  body_html: string
  excerpt: string
  type: PageType
  /** Which WP REST route this page belongs to — the pipeline's view of it, kept
   *  apart from the editorial `type` above. See migrations/0002_wp_type.sql. */
  wp_type: "page" | "post"
  hub_slug: string | null
  status: "draft" | "published"
  faq: Faq[]
  schema_json: unknown | null
  canonical: string
  in_nav: boolean
  sort: number
  created_at: string
  updated_at: string
}

/** "home" is the section root; everything else is its slug. A leading or
 *  trailing slash is accepted because links, sitemaps and redirects disagree. */
export function normaliseSlug(input: string): string {
  const s = input.trim().replace(/^\/+|\/+$/g, "").toLowerCase()
  return s === "" ? "home" : s
}

/**
 * The shim's pure logic: naming, typing, and the two normalisations that run on
 * every write.
 *
 * SEPARATE FROM wp-shim.ts BECAUSE IT IS TESTABLE. That file opens with
 * `import "server-only"`, which cannot resolve outside Next's bundler, so
 * nothing in it could be exercised by a test — and both functions below shipped
 * broken in ways no call site reveals. `typeForTitle` wrote `\bcertif\b`, which
 * cannot match "certificate", so the first page the pipeline published was filed
 * `generic`; and `extractLeadingH1` did not exist, so that page rendered two
 * H1s and SemanticWP's own post-publish check pulled it back to draft.
 *
 * Tests: scripts/test-wp-shim.ts
 */

/**
 * WordPress sends `2026-10-15T09:14:02`, with no zone marker, in both `modified`
 * and `modified_gmt`. The queries already hand back ISO-with-Z (see the
 * `to_char` in the column lists — a bare `::text` renders a timestamptz as
 * `2026-10-15 09:14:02.41+00`, which `new Date()` rejects outright because `+00`
 * is not a valid ISO offset), so this only drops the Z.
 */
export function wpDate(value: string): string {
  return value.replace(/Z$/, "")
}

/**
 * Decide where a page the pipeline is creating belongs.
 *
 * The audience is translators and agencies who certify translations, so the
 * type is read off the subject rather than guessed: a question keeps its own
 * type so the hub rail can pair it with the page it supports.
 */
export function typeForTitle(title: string, postType: "page" | "post"): PageType {
  const t = title.toLowerCase()
  if (/^(how|what|why|when|which|who|can|do|does|is|are|should|will)\b/.test(t) || t.includes("?")) {
    return "question"
  }
  if (postType === "post") return "question"
  // STEMS ARE OPEN-ENDED. These were written `\b(certif|notaris|qualif)\b`,
  // which cannot match the words they were meant to catch: the position after
  // "certif" inside "certificate" sits between two word characters, so there is
  // no boundary there and `\bcertif\b` never fires. The first page the pipeline
  // published — "Certificate of Translation for USCIS" — was filed `generic`,
  // which is the wrong eyebrow label and the wrong hub rail on every
  // certification page the site will ever have. A trailing \b belongs only on a
  // whole word.
  if (/\b(cat tool|translation memor|tmx|xliff|software|management system|trados|memoq|alternative)/.test(t)) return "tool"
  // CREDENTIAL BEFORE CERTIFY, and the order is the whole distinction: a
  // credential is something a PERSON holds, a certification is something a
  // DOCUMENT carries, and both say "certif". "ATA certification" is a
  // credential; "certificate of translation accuracy" is not. Tested on the
  // real titles in scripts/test-wp-shim.ts, because reading these two lines is
  // not enough to know which one claims a given title.
  if (/\b(ata\b|becom(e|ing)|credential|qualif|accredit|exam\b|sworn translator|certified translator)/.test(t)) {
    return "credential"
  }
  if (/\b(certif|accuracy statement|notaris|notariz|affidavit|sworn)/.test(t)) return "certify"
  if (/\b(ocr\b|post.?edit|mtpe\b|quality assurance|proofread|word count|segmentation|layout)/.test(t)) return "workflow"
  if (/\b(rate|pricing|price|per word|invoice|quot|client|nda\b|agenc)/.test(t)) return "practice"
  return "generic"
}

export function slugForTitle(title: string): string {
  return normaliseSlug(
    title
      .toLowerCase()
      .normalize("NFD")
      // Fold accents rather than percent-encoding them. A sibling site served
      // /chi-pu%C3%B2-fare-... for months: ugly to share and easy to mistype.
      .replace(/[̀-ͯ]/g, "")
      .replace(/['’]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      // No truncation mid-phrase. A sibling site cut slugs at ~60 characters
      // and shipped five URLs ending in a dangling "-for" and "-in".
      .slice(0, 110)
      .replace(/-+$/g, ""),
  )
}

/**
 * Lift the body's own H1 out of the markup and return it separately.
 *
 * The pipeline writes a complete page, H1 included, and the guides template
 * renders its own H1 above the body — so the first published page had TWO, the
 * same text twice. SemanticWP's own post-publish check caught it
 * (`duplicate_h1`) and pulled the page back to draft, which is the system
 * working: a duplicate H1 is a real defect, not a cosmetic one.
 *
 * Stripping on WRITE rather than on render, so the stored row is the clean
 * thing. A render-time strip would leave every row holding markup that
 * disagrees with how it is displayed, and the next thing to read the column —
 * the duplicate check, the retrieval index, a hand edit — would see the H1 and
 * be wrong about the page.
 *
 * The Gutenberg comment pair around the heading goes with it. Left behind, it
 * is an orphan `<!-- wp:heading -->` with no block, which the companion's
 * serialiser treats as malformed.
 */
export function extractLeadingH1(html: string): { h1: string | null; body: string } {
  const m = html.match(
    /(?:<!--\s*wp:heading[^>]*?-->\s*)?<h1\b[^>]*>([\s\S]*?)<\/h1>(?:\s*<!--\s*\/wp:heading\s*-->)?/i,
  )
  if (!m) return { h1: null, body: html }
  const text = m[1]
    .replace(/<[^>]*>/g, "")
    .replace(/&#x27;|&#39;|&apos;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim()
  const body = html.slice(0, m.index).concat(html.slice((m.index ?? 0) + m[0].length))
  return { h1: text || null, body }
}

/**
 * WordPress maps a handful of statuses onto something a reader can or cannot
 * see. Only `publish` is public. Everything else — draft, pending, private,
 * future, trash — is not, and the previous version treated every one of them as
 * a publish instruction, so a page the pipeline queued for review would have
 * gone live.
 */
export function statusFor(value: string | undefined): "published" | "draft" | null {
  if (value === undefined) return null
  return value === "publish" ? "published" : "draft"
}
