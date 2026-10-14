import "server-only"
import { cache } from "react"
import { contentDb, selectAll } from "./client"

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

const COLUMNS =
  "slug,title,h1,meta_description,body_html,excerpt,type,hub_slug,status,faq,schema_json,canonical,in_nav,sort,created_at,updated_at"

/**
 * Every published page.
 *
 * `cache` dedupes this within a single render: the page body, the nav, the
 * related rail and the breadcrumb all want the same list, and without it one
 * page view would make four round trips for identical data.
 *
 * It pages, because PostgREST stops at 1000 rows without saying so.
 */
export const listPages = cache(async (): Promise<ContentPage[]> => {
  const db = contentDb()
  const rows = await selectAll<ContentPage>((from, to) =>
    db
      .from("pages")
      .select(COLUMNS)
      .eq("status", "published")
      .order("sort", { ascending: true })
      .order("title", { ascending: true })
      .range(from, to),
  )
  return rows.map(normalise)
})

/** One page by slug, published only. Drafts 404 for the public. */
export const getPage = cache(async (slug: string): Promise<ContentPage | null> => {
  const { data, error } = await contentDb()
    .from("pages")
    .select(COLUMNS)
    .eq("slug", normaliseSlug(slug))
    .eq("status", "published")
    .maybeSingle()
  if (error) throw new Error(`content read failed for ${slug}: ${error.message}`)
  return data ? normalise(data as ContentPage) : null
})

/**
 * A redirect for a path that is no longer a page.
 *
 * Checked before serving a 404, because renaming a slug without one throws away
 * whatever the old URL had earned. On a sibling site a single renamed page
 * carried 1,296 impressions.
 */
export async function getRedirect(path: string): Promise<string | null> {
  const from = `/${normaliseSlug(path)}`
  const { data, error } = await contentDb()
    .from("redirects")
    .select("to_path")
    .eq("from_path", from)
    .maybeSingle()
  if (error) return null
  return (data?.to_path as string | undefined) ?? null
}

/** The hub a page belongs to, and the pages that belong to it. */
export function hubMembers(page: ContentPage, all: ContentPage[]): ContentPage[] {
  const hub = page.hub_slug ?? page.slug
  return all.filter((p) => p.slug !== page.slug && (p.hub_slug === hub || p.slug === hub))
}

/**
 * The related rail: the page's own hub first, then a rotating fill from the
 * others.
 *
 * The rotation matters. A fixed `.slice(0, n)` over a stably ordered list hands
 * the same n pages every internal link on the site and leaves the rest with
 * none — which is exactly what happened on three sibling sites, where six pages
 * of seventy-four held every link the rail produced.
 */
export function relatedPages(page: ContentPage, all: ContentPage[], limit = 6): ContentPage[] {
  if (page.type === "legal" || page.type === "home") return []
  const eligible = all.filter((p) => p.type !== "legal" && p.type !== "home")
  const out: ContentPage[] = []
  const taken = new Set<string>([page.slug])

  for (const p of hubMembers(page, eligible)) {
    if (out.length >= limit) break
    if (taken.has(p.slug)) continue
    taken.add(p.slug)
    out.push(p)
  }

  const self = eligible.findIndex((p) => p.slug === page.slug)
  for (let i = 1; i < eligible.length && out.length < limit; i += 1) {
    const candidate = eligible[(Math.max(0, self) + i) % eligible.length]
    if (taken.has(candidate.slug)) continue
    taken.add(candidate.slug)
    out.push(candidate)
  }
  return out
}

/** "home" is the root; everything else is its slug. Trailing slashes and a
 *  leading slash are accepted because links, sitemaps and redirects disagree. */
export function normaliseSlug(input: string): string {
  const s = input.trim().replace(/^\/+|\/+$/g, "").toLowerCase()
  return s === "" ? "home" : s
}

function normalise(row: ContentPage): ContentPage {
  return {
    ...row,
    // jsonb comes back parsed, but a hand-edited row can still hold the wrong
    // shape. Render nothing rather than throw inside a server component.
    faq: Array.isArray(row.faq)
      ? (row.faq as Faq[]).filter((f) => f && typeof f.q === "string" && typeof f.a === "string")
      : [],
  }
}
