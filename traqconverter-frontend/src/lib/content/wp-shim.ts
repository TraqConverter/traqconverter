import "server-only"
import { contentDb, selectAll } from "./client"
import { normaliseSlug, type ContentPage, type PageType } from "./pages"

/**
 * Enough of the WordPress REST API for SemanticWP to drive this site.
 *
 * SemanticWP connects to every site by speaking WordPress REST, so a Next.js
 * site has to answer that contract. The sibling sites do the same thing; the
 * routes below are the ones they learned are load-bearing.
 *
 * THE LISTING ROUTE IS THE ONE THAT BITES. `GET /pages` with no filters must
 * return an array AND an `x-wp-total` header. Two sibling sites shipped without
 * it and answered `[]`, so the pipeline's page mirror held zero rows for
 * months: internal linking had no targets and the duplicate check compared
 * every new page against nothing. It failed silently the whole time.
 */

/** Basic auth, against one username and one application password. */
export function authorized(req: Request): boolean {
  const user = process.env.CONTENT_WP_USERNAME
  const pass = process.env.CONTENT_WP_APP_PASSWORD
  if (!user || !pass) return false
  const header = req.headers.get("authorization") ?? ""
  if (!header.toLowerCase().startsWith("basic ")) return false
  let decoded = ""
  try {
    decoded = Buffer.from(header.slice(6).trim(), "base64").toString("utf8")
  } catch {
    return false
  }
  const i = decoded.indexOf(":")
  if (i < 0) return false
  // WordPress application passwords are shown in groups of four separated by
  // spaces, and operators paste them that way. Compare without the spaces or a
  // correct password is rejected.
  const given = decoded.slice(i + 1).replace(/\s+/g, "")
  return decoded.slice(0, i) === user && given === pass.replace(/\s+/g, "")
}

export async function idForSlug(slug: string): Promise<number> {
  const db = contentDb()
  const existing = await db.from("wp_ids").select("id").eq("slug", slug).maybeSingle()
  if (existing.data) return Number((existing.data as { id: number }).id)
  const inserted = await db.from("wp_ids").insert({ slug }).select("id").single()
  if (inserted.error) {
    // A concurrent create for the same slug loses the insert race; the row it
    // wanted now exists, so read it rather than failing the request.
    const again = await db.from("wp_ids").select("id").eq("slug", slug).maybeSingle()
    if (again.data) return Number((again.data as { id: number }).id)
    throw new Error(`could not allocate an id for ${slug}: ${inserted.error.message}`)
  }
  return Number((inserted.data as { id: number }).id)
}

export async function slugForId(id: number): Promise<string | null> {
  const { data } = await contentDb().from("wp_ids").select("slug").eq("id", id).maybeSingle()
  return (data as { slug: string } | null)?.slug ?? null
}

const SITE = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.onlinedoctranslator.ai").replace(/\/$/, "")

/** The subset of a WP post object the pipeline reads. */
export async function toWpObject(page: ContentPage): Promise<Record<string, unknown>> {
  const id = await idForSlug(page.slug)
  return {
    id,
    date: page.created_at,
    date_gmt: page.created_at,
    modified: page.updated_at,
    modified_gmt: page.updated_at,
    slug: page.slug,
    status: page.status === "published" ? "publish" : "draft",
    type: page.type === "question" ? "post" : "page",
    link: page.slug === "home" ? `${SITE}/` : `${SITE}/${page.slug}`,
    title: { rendered: page.title, raw: page.title },
    content: { rendered: page.body_html, raw: page.body_html, protected: false },
    excerpt: { rendered: page.excerpt, raw: page.excerpt, protected: false },
    parent: 0,
    menu_order: page.sort,
    meta: { _yoast_wpseo_metadesc: page.meta_description },
  }
}

export async function listAllPages(): Promise<ContentPage[]> {
  const db = contentDb()
  return selectAll<ContentPage>((from, to) =>
    db
      .from("pages")
      .select("*")
      .order("sort", { ascending: true })
      .order("title", { ascending: true })
      .range(from, to),
  )
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
  if (/\b(cat tool|translation memory|tmx|xliff|software|management system|trados|memoq|alternative)\b/.test(t)) return "tool"
  if (/\b(certif|accuracy statement|notaris|notariz|affidavit|sworn)\b/.test(t)) return "certify"
  if (/\b(ata|become|credential|qualif|exam|accredit)\b/.test(t)) return "credential"
  if (/\b(ocr|post.?edit|mtpe|quality assurance|proofread|word count|segmentation|layout)\b/.test(t)) return "workflow"
  if (/\b(rate|price|per word|invoice|quote|client|nda|agency)\b/.test(t)) return "practice"
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

export async function upsertFromWp(input: {
  title: string
  content: string
  excerpt?: string
  status?: string
  slug?: string
  postType: "page" | "post"
  metaDescription?: string
}): Promise<{ page: ContentPage; id: number }> {
  const slug = input.slug ? normaliseSlug(input.slug) : slugForTitle(input.title)
  const row = {
    slug,
    title: input.title,
    h1: input.title,
    body_html: input.content,
    excerpt: input.excerpt ?? "",
    meta_description: input.metaDescription ?? "",
    type: typeForTitle(input.title, input.postType),
    status: input.status === "draft" ? ("draft" as const) : ("published" as const),
    updated_at: new Date().toISOString(),
  }
  const { data, error } = await contentDb()
    .from("pages")
    .upsert(row, { onConflict: "slug" })
    .select("*")
    .single()
  if (error) throw new Error(`could not write ${slug}: ${error.message}`)
  const page = data as ContentPage
  return { page, id: await idForSlug(page.slug) }
}
