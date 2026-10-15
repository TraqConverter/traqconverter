import "server-only"
import { cache } from "react"
import { hasContentDb, sql } from "./client"
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

/** One page by slug. A draft 404s for the public. */
export const getPage = cache(async (slug: string): Promise<ContentPage | null> => {
  if (!hasContentDb()) return null
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
export function hubMembers(page: ContentPage, all: ContentPage[]): ContentPage[] {
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
