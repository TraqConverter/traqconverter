import "server-only"
import { sql } from "./client"
import { contentUrl } from "./config"
import { normaliseSlug, type ContentPage } from "./pages"
import { extractLeadingH1, slugForTitle, statusFor, typeForTitle, wpDate } from "./shim-naming"

// Re-exported so the route and anything else keeps importing them from here.
export { extractLeadingH1, slugForTitle, typeForTitle }

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
  // One statement, so a concurrent create for the same slug cannot lose a race
  // between a select and an insert. `do update` rather than `do nothing`
  // because `do nothing` returns no row on conflict and there would be nothing
  // to read back.
  const rows = (await sql()`
    insert into content.wp_ids (slug) values (${slug})
    on conflict (slug) do update set slug = excluded.slug
    returning id
  `) as unknown as Array<{ id: number | string }>
  return Number(rows[0].id)
}

export async function slugForId(id: number): Promise<string | null> {
  const rows = (await sql()`
    select slug from content.wp_ids where id = ${id} limit 1
  `) as unknown as Array<{ slug: string }>
  return rows.length ? rows[0].slug : null
}

/** The subset of a WP post object the pipeline reads. */
export async function toWpObject(page: ContentPage): Promise<Record<string, unknown>> {
  const id = await idForSlug(page.slug)
  const date = wpDate(page.created_at)
  const modified = wpDate(page.updated_at)
  return {
    id,
    date,
    date_gmt: date,
    modified,
    modified_gmt: modified,
    slug: page.slug,
    status: page.status === "published" ? "publish" : "draft",
    // The ROUTE the page belongs to, never re-derived from its title. See
    // migrations/0002_wp_type.sql.
    type: page.wp_type,
    // The real URL. These pages live under /guides — the section has a prefix
    // because twenty-two app routes sit at the root. Returning a root-level link
    // would have mirrored a 404 into site_pages for every page on the site, and
    // internal linking plans against exactly those stored URLs.
    link: contentUrl(page.slug),
    title: { rendered: page.title, raw: page.title },
    content: { rendered: page.body_html, raw: page.body_html, protected: false },
    excerpt: { rendered: page.excerpt, raw: page.excerpt, protected: false },
    parent: 0,
    menu_order: page.sort,
    meta: { _yoast_wpseo_metadesc: page.meta_description },
  }
}

/**
 * The pipeline's inventory.
 *
 * `status` honours the filter the caller sent: `listPosts` asks for
 * `status=publish` because `site_pages` is meant to hold real public URLs and
 * internal linking uses those rows as link targets — mirroring a draft puts a
 * link to a 404 in the plan. With no filter, drafts are included, because the
 * duplicate probe has to see a page the pipeline created but has not published.
 */
export async function listAllPages(opts: { wpType?: "page" | "post"; status?: "publish" | "draft" } = {}): Promise<ContentPage[]> {
  const wpType = opts.wpType ?? null
  const status = opts.status === "publish" ? "published" : opts.status === "draft" ? "draft" : null
  return (await sql()`
    select slug, title, h1, meta_description, body_html, excerpt, type, wp_type, hub_slug, status,
           faq, schema_json, canonical, in_nav, sort,
           to_char(created_at at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as created_at,
           to_char(updated_at at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as updated_at
    from content.pages
    where (${wpType}::text is null or wp_type = ${wpType})
      and (${status}::text is null or status::text = ${status})
    -- Qualified, because a bare updated_at would resolve to the to_char alias
    -- above: an output-column name beats a table column in ORDER BY. Sorting
    -- ISO text happens to agree with sorting the timestamp, which is exactly why
    -- that would survive review and then break the day the format changed.
    order by content.pages.updated_at desc, sort asc, title asc
  `) as unknown as ContentPage[]
}

/**
 * Create or update a page from a WP REST body.
 *
 * AN UPDATE IS A PARTIAL UPDATE. WordPress leaves a field it was not sent
 * alone, and so must this: the optimize flow POSTs only `content` to
 * `/pages/<id>`. The first version wrote every column on every call, with
 * `title: input.title`, and on an update with no title the route fell back to
 * `title || slug` — so one content-only update replaced the page's title and H1
 * with its own slug, blanked the excerpt and the meta description, and then
 * re-derived the editorial type from that slug. The probe caught it live: a page
 * titled "What is a translation memory?" came back titled
 * "probe-what-is-a-translation-memory" and retyped from question to generic.
 * On an estate of real pages that is an SEO extinction event, applied silently,
 * one page per optimize run.
 *
 * The nulls below are the whole mechanism: a field the caller omitted binds
 * null, `coalesce` keeps what is stored, and only a value actually sent is
 * written.
 */
export async function upsertFromWp(input: {
  title?: string
  content?: string
  excerpt?: string
  status?: string
  slug?: string
  postType: "page" | "post"
  metaDescription?: string
  /** True when the request addressed an existing id, so the slug is known to
   *  exist and nothing may be derived from a missing title. */
  isUpdate: boolean
}): Promise<{ page: ContentPage; id: number }> {
  const title = input.title?.trim() || undefined
  if (!input.isUpdate && !title && !input.slug) {
    throw new Error("a create needs a title or a slug")
  }
  const slug = input.slug ? normaliseSlug(input.slug) : slugForTitle(title ?? "")

  // The body's own H1 becomes the page's h1 and leaves the markup, so the
  // template's heading is the only one on the page.
  const lifted = input.content === undefined ? { h1: null, body: undefined } : extractLeadingH1(input.content)
  const h1 = lifted.h1 ?? title

  // The editorial type follows the title, so it is recomputed only when a title
  // was actually sent. wp_type is the route and is set once, on insert.
  const type = title ? typeForTitle(title, input.postType) : null
  const status = statusFor(input.status)

  const rows = (await sql()`
    insert into content.pages (slug, title, h1, body_html, excerpt, meta_description,
                               type, wp_type, status, updated_at)
    values (
      ${slug},
      ${title ?? slug},
      ${h1 ?? slug},
      ${lifted.body ?? ""},
      ${input.excerpt ?? ""},
      ${input.metaDescription ?? ""},
      ${type ?? typeForTitle(title ?? slug, input.postType)}::content.page_type,
      ${input.postType},
      ${status ?? "published"}::content.page_status,
      now()
    )
    on conflict (slug) do update set
      title            = coalesce(${title}, content.pages.title),
      h1               = coalesce(${h1}, content.pages.h1),
      body_html        = coalesce(${lifted.body ?? null}, content.pages.body_html),
      excerpt          = coalesce(${input.excerpt ?? null}, content.pages.excerpt),
      meta_description = coalesce(${input.metaDescription ?? null}, content.pages.meta_description),
      type             = coalesce(${type}::content.page_type, content.pages.type),
      -- The caller's route wins, unlike every other column here. The pipeline
      -- addresses a page only through the route it filed it under, so a row left
      -- under the other one is a row it can never read or update again — the
      -- exact un-addressable state 0002 exists to prevent. WordPress keeps posts
      -- and pages in separate namespaces where both slugs can coexist; here the
      -- slug is the key, so the collision has to resolve one way, and it resolves
      -- towards whoever is writing.
      wp_type          = excluded.wp_type,
      status           = coalesce(${status}::content.page_status, content.pages.status),
      updated_at       = now()
    returning slug, title, h1, meta_description, body_html, excerpt, type, wp_type, hub_slug, status,
              faq, schema_json, canonical, in_nav, sort,
              to_char(created_at at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as created_at,
              to_char(updated_at at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as updated_at
  `) as unknown as ContentPage[]
  if (!rows.length) throw new Error(`could not write ${slug}`)
  const page = rows[0]
  return { page, id: await idForSlug(page.slug) }
}
