import "server-only"
import { cache } from "react"
import { ContentDbUnavailableError, hasContentDb, sql } from "./client"
import { normaliseSlug, type ContentPage, type Faq, type PageType } from "./shim-naming"

// Re-exported: these are the public names of the content layer, and they stay
// importable from here even though the pure definitions live next door so a
// test can reach them without Next's bundler.
export { normaliseSlug }
export type { ContentPage, Faq, PageType }

// created_at and updated_at are cast to text so the shape stays a plain string
// everywhere. The column is a real timestamptz; only the transport is flattened.
//
// The list is written out in both queries rather than interpolated. It is
// static code, and an `unsafe()` call inside a query template is the kind of
// thing a later edit quietly feeds user input into.

/**
 * Every published page.
 *
 * `cache` dedupes within a single render: the body, the breadcrumb, the related
 * rail and the nav all want this list, and without it one page view would make
 * four round trips for identical data.
 *
 * No paging. The Supabase version needed it because PostgREST silently caps a
 * response at 1000 rows; SQL has no such ceiling.
 */
export const listPages = cache(async (): Promise<ContentPage[]> => {
  if (!hasContentDb()) return []
  const rows = (await sql()`
    select slug, title, h1, meta_description, body_html, excerpt, type, wp_type, hub_slug, status,
           faq, schema_json, canonical, in_nav, sort,
           to_char(created_at at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as created_at,
           to_char(updated_at at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as updated_at
    from content.pages
    where status = 'published'
    order by sort asc, title asc
  `) as unknown as ContentPage[]
  return rows.map(normalise)
})

/**
 * Every published page, WITHOUT the bodies.
 *
 * WHY THIS EXISTS. `listPages` selects `body_html` (plus `schema_json` and
 * `faq`) for all ~190 pages, and the two things that call it — the related rail
 * and the sitemap — need none of them. `cache` only dedupes within ONE render,
 * so with `revalidate = 300` every page re-fetched every body every five
 * minutes: roughly 7MB of egress per render across the section, continuously.
 *
 * On 2026-10-29 the content database started answering every query with
 * HTTP 402 "Your account or project has exceeded the quota", and all 45 guide
 * pages served 500s while the homepage — which touches no database — stayed up.
 * Egress, not compute, is what was being spent.
 *
 * The index is ~200 bytes a row instead of ~40KB. Use it for navigation,
 * breadcrumbs, related links and the sitemap; use `getPage` for the one body a
 * request actually renders.
 */
export type ContentPageIndex = Pick<
  ContentPage,
  "slug" | "title" | "type" | "wp_type" | "hub_slug" | "in_nav" | "sort" | "updated_at"
>

export const listPageIndex = cache(async (): Promise<ContentPageIndex[]> => {
  if (!hasContentDb()) return []
  const rows = (await sql()`
    select slug, title, type, wp_type, hub_slug, in_nav, sort,
           to_char(updated_at at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as updated_at
    from content.pages
    where status = 'published'
    order by sort asc, title asc
  `) as unknown as ContentPageIndex[]
  return rows.map((r) => ({ ...r, slug: normaliseSlug(r.slug) }))
})

/** One page by slug. A draft 404s for the public. */
export const getPage = cache(async (slug: string): Promise<ContentPage | null> => {
  // Throw, never return null: the route turns null into notFound(), and a
  // missing connection string would 404 the whole section instead of failing
  // loudly. null here means "the database answered and has no such page".
  if (!hasContentDb()) throw new ContentDbUnavailableError("no connection string configured")
  const rows = (await sql()`
    select slug, title, h1, meta_description, body_html, excerpt, type, wp_type, hub_slug, status,
           faq, schema_json, canonical, in_nav, sort,
           to_char(created_at at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as created_at,
           to_char(updated_at at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as updated_at
    from content.pages
    where slug = ${normaliseSlug(slug)} and status = 'published'
    limit 1
  `) as unknown as ContentPage[]
  return rows.length ? normalise(rows[0]) : null
})

/**
 * A redirect for a path that is no longer a page.
 *
 * Checked before serving a 404, because renaming a slug without one throws away
 * whatever the old URL earned. On a sibling site a single renamed page was
 * holding 1,296 impressions.
 */
export async function getRedirect(path: string): Promise<string | null> {
  if (!hasContentDb()) return null
  const rows = (await sql()`
    select to_path from content.redirects where from_path = ${`/${normaliseSlug(path)}`} limit 1
  `) as unknown as Array<{ to_path: string }>
  return rows.length ? rows[0].to_path : null
}

/** The other members of this page's hub: for a question, the service page it
 *  supports and its sibling questions; for a service page, its questions. */
/** Everything the relation helpers actually read — so they work on the light
 *  index as well as a full page. */
export type Relatable = Pick<ContentPage, "slug" | "title" | "type" | "hub_slug">

export function hubMembers<T extends Relatable>(page: Relatable, all: T[]): T[] {
  const hub = page.hub_slug ?? page.slug
  return all.filter((p) => p.slug !== page.slug && (p.hub_slug === hub || p.slug === hub))
}

/**
 * The related rail: this page's hub first, then a rotating fill from the others.
 *
 * The rotation matters. A fixed `.slice(0, n)` over a stably ordered list hands
 * the same n pages every internal link on the site and leaves the rest with
 * none — which is what happened on three sibling sites, where six pages of
 * seventy-four held every link the rail produced.
 */
export function relatedPages<T extends Relatable>(page: Relatable, all: T[], limit = 6): T[] {
  if (page.type === "legal" || page.type === "home") return []
  const eligible = all.filter((p) => p.type !== "legal" && p.type !== "home")
  const out: T[] = []
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

function normalise(row: ContentPage): ContentPage {
  return {
    ...row,
    // jsonb arrives parsed, but a hand-edited row can still hold the wrong
    // shape. Render nothing rather than throw inside a server component.
    faq: Array.isArray(row.faq)
      ? (row.faq as Faq[]).filter((f) => f && typeof f.q === "string" && typeof f.a === "string")
      : [],
  }
}
