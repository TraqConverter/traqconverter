import "server-only"
import { neon } from "@neondatabase/serverless"

/**
 * The content database.
 *
 * ITS OWN POSTGRES, ON PURPOSE. The first version of this pointed at the
 * product's Supabase project, on the assumption that only Storage was in use
 * there. It was not: that project holds translation_jobs, translation_segments,
 * delivery_links and media_assets — 28 tables of customers' documents — so any
 * credential the content layer held would have reached all of it. A separate
 * Postgres means there is no such credential to leak, rather than a narrower
 * one.
 *
 * NEON'S HTTP DRIVER, NOT A POOL. Every request here may be a cold serverless
 * invocation, and a `pg` pool per invocation exhausts the connection limit under
 * any real traffic. `neon()` issues each query over HTTP, so there is no
 * connection to exhaust and no pooler mode to work around.
 *
 * It also removes a workaround: the Supabase version went through PostgREST,
 * which caps a response at 1000 rows server-side and says nothing when it does
 * — a cap that cost four days on a sibling project. Plain SQL has no such
 * ceiling, so `selectAll` and its paging are gone.
 */

/**
 * Vercel's Neon integration injects several URLs. DATABASE_URL is the pooled
 * one and is what this wants; the unpooled variant is only for migrations and
 * long transactions, neither of which happen in a request.
 */
function connectionString(): string {
  const url =
    process.env.CONTENT_DATABASE_URL ??
    process.env.DATABASE_URL ??
    process.env.POSTGRES_URL
  if (!url) {
    throw new Error(
      "No content database URL. Expected CONTENT_DATABASE_URL, or DATABASE_URL / POSTGRES_URL as injected by Vercel's Neon integration.",
    )
  }
  return url
}

let cached: ReturnType<typeof neon> | null = null

/**
 * A tagged-template query function. Interpolations are sent as bound
 * parameters, never concatenated, so a page slug from a URL cannot alter the
 * statement:
 *
 *   const rows = await sql`select * from content.pages where slug = ${slug}`
 */
export function sql() {
  if (!cached) cached = neon(connectionString())
  return cached
}

/** True when a content database is configured at all, so a route can degrade
 *  to the product pages rather than throwing during a build. */
export function hasContentDb(): boolean {
  return Boolean(
    process.env.CONTENT_DATABASE_URL ?? process.env.DATABASE_URL ?? process.env.POSTGRES_URL,
  )
}
