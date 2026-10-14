import "server-only"
import { createClient } from "@supabase/supabase-js"

/**
 * Server-only client for the content schema.
 *
 * WHY PostgREST RATHER THAN A POSTGRES CONNECTION. This app runs on Vercel, so
 * every request may be a cold serverless invocation. A `pg` pool per invocation
 * exhausts Supabase's connection limit under any real traffic, and the usual
 * fix — the transaction pooler — forbids prepared statements, which the driver
 * uses by default. HTTP has no connection to exhaust.
 *
 * WHAT IT COSTS. PostgREST caps a response at 1000 rows SERVER-SIDE, and
 * neither .limit() nor .range() lifts it. That cap is silent: you get 1000 rows
 * and no error, which on a sibling project read as a traffic collapse for four
 * days. Anything that can exceed 1000 rows must page — see `selectAll` below.
 *
 * The service-role key bypasses row level security, which is correct here
 * because this module is server-only and the content tables carry leads. It
 * must never be imported into a client component; the "server-only" import
 * above turns that mistake into a build error rather than a leaked key.
 */
// The schema option changes the client's generic signature, so the type is
// inferred from the factory rather than written out — naming it means naming
// five generic parameters that move between supabase-js releases.
function create() {
  const url = process.env.CONTENT_SUPABASE_URL
  const key = process.env.CONTENT_SUPABASE_SERVICE_KEY
  if (!url || !key) {
    throw new Error(
      "CONTENT_SUPABASE_URL and CONTENT_SUPABASE_SERVICE_KEY must be set. They point at this product's own Supabase project — the one already used for Storage, whose Postgres was idle — and the content lives in its `content` schema. Not SemanticWP's project: a customer-facing site must not share a database with the SaaS that manages it.",
    )
  }
  return createClient(url, key, {
    db: { schema: "content" },
    auth: { persistSession: false, autoRefreshToken: false },
  })
}

type ContentClient = ReturnType<typeof create>
let cached: ContentClient | null = null

export function contentDb(): ContentClient {
  if (!cached) cached = create()
  return cached
}

/**
 * Read every row a query matches, a page at a time.
 *
 * `build` receives the row range and must return the query for it. Each page is
 * checked for an error rather than treated as the end of the table: a failed
 * page that is read as "no more rows" silently truncates the site's own
 * navigation and sitemap.
 */
export async function selectAll<T>(
  build: (from: number, to: number) => PromiseLike<{ data: T[] | null; error: { message: string } | null }>,
  pageSize = 1000,
): Promise<T[]> {
  const out: T[] = []
  for (let from = 0; ; from += pageSize) {
    const { data, error } = await build(from, from + pageSize - 1)
    if (error) throw new Error(`content read failed at offset ${from}: ${error.message}`)
    const rows = data ?? []
    out.push(...rows)
    if (rows.length < pageSize) return out
    // A site with more pages than this is not impossible, but it is far enough
    // out that silently looping forever is the worse failure.
    if (from > 50_000) throw new Error("content read exceeded 50k rows — check the filter")
  }
}
