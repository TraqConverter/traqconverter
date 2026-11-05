import "server-only"
import type { ContentPage } from "./shim-naming"

/**
 * The content store, as a file on the server's own disk.
 *
 * WHY THIS REPLACES A HOSTED POSTGRES. This section served 60 pages out of
 * Neon. On 2026-10-29 that database hit its free-tier egress limit, answered
 * HTTP 402 to every connection for a week, and took all 60 guides down with it
 * — while the homepage, which touches no database, stayed up. Reads already
 * come from a committed snapshot; this moves the WRITES, which is what finally
 * retires the dependency.
 *
 * It is also what the seven sibling sites do. One SQLite file per site, written
 * by the publish shim, excluded from every deploy so a release can never
 * overwrite the content. Nothing to bill, no quota, no egress, and a backup is
 * a file copy.
 *
 * ONLY LOADED WHERE IT WORKS. `better-sqlite3` is a native module and the app
 * also deploys to a serverless platform, where there is no persistent disk to
 * write to. The import is lazy and guarded by `usingSqlite()`, so the serverless
 * build neither bundles it nor needs it: there, reads come from the snapshot
 * and writes do not happen at all.
 */

type Db = {
  prepare: (sql: string) => {
    get: (...a: unknown[]) => unknown
    all: (...a: unknown[]) => unknown[]
    run: (...a: unknown[]) => { changes: number; lastInsertRowid: number | bigint }
  }
  exec: (sql: string) => void
}

/** Where the file lives. Absent means "this deployment does not write". */
export function sqlitePath(): string | null {
  return process.env.CONTENT_SQLITE_PATH?.trim() || null
}

export function usingSqlite(): boolean {
  return Boolean(sqlitePath())
}

let db: Db | null = null

function open(): Db {
  if (db) return db
  const path = sqlitePath()
  if (!path) throw new Error("CONTENT_SQLITE_PATH is not set; this deployment has no write store")

  const Database = require("better-sqlite3") as new (p: string) => Db
  const handle = new Database(path)
  // WAL so a read during a write does not block, and the publish shim and the
  // request path can touch the file at the same time.
  handle.exec("pragma journal_mode = WAL; pragma foreign_keys = on;")
  handle.exec(SCHEMA)
  db = handle
  return handle
}

/**
 * The schema, mirroring the Postgres one.
 *
 * Postgres enums become CHECK constraints — SQLite has no enum type, and a
 * plain TEXT column would let a typo become a page type nothing renders.
 * Timestamps are ISO-8601 TEXT because that is what the API returns and what
 * the snapshot already holds; storing them as text keeps one representation
 * end to end rather than converting at every boundary.
 */
const SCHEMA = `
create table if not exists pages (
  slug              text primary key,
  title             text not null,
  h1                text not null default '',
  meta_description  text not null default '',
  body_html         text not null default '',
  excerpt           text not null default '',
  type              text not null default 'generic'
                      -- Exactly content.page_type from migrations/0001_content.sql.
                      -- Guessed values failed the seed on real data; these are read
                      -- from the migration, not inferred from the rows present.
                      check (type in ('tool','certify','credential','workflow','practice','question','legal','generic','home')),
  wp_type           text not null default 'page' check (wp_type in ('page','post')),
  hub_slug          text references pages(slug) on delete set null,
  status            text not null default 'draft' check (status in ('draft','published')),
  faq               text not null default '[]',
  schema_json       text,
  canonical         text not null default '',
  in_nav            integer not null default 0,
  sort              integer not null default 100,
  created_at        text not null default (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at        text not null default (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
create index if not exists pages_published on pages (status, sort, title);
create index if not exists pages_hub on pages (hub_slug) where hub_slug is not null;

-- The pipeline stores this integer as wp_id and addresses the page by it
-- forever, so the mapping has to outlive any slug change.
create table if not exists wp_ids (
  id   integer primary key autoincrement,
  slug text unique not null
);

create table if not exists redirects (
  from_path text primary key,
  to_path   text not null
);
`

const COLS = `slug, title, h1, meta_description, body_html, excerpt, type, wp_type, hub_slug, status,
              faq, schema_json, canonical, in_nav, sort, created_at, updated_at`

/** SQLite has no boolean or json type; the rest of the app expects both. */
function hydrate(row: Record<string, unknown> | undefined): ContentPage | null {
  if (!row) return null
  return {
    ...row,
    in_nav: Boolean(row.in_nav),
    faq: typeof row.faq === "string" ? JSON.parse(row.faq || "[]") : (row.faq ?? []),
    schema_json:
      typeof row.schema_json === "string" && row.schema_json ? JSON.parse(row.schema_json) : null,
  } as ContentPage
}

export function getPage(slug: string): ContentPage | null {
  return hydrate(open().prepare(`select ${COLS} from pages where slug = ?`).get(slug) as never)
}

export function listPages(opts: { wpType?: "page" | "post"; status?: "published" | "draft" } = {}): ContentPage[] {
  const rows = open()
    .prepare(
      `select ${COLS} from pages
       where (? is null or wp_type = ?) and (? is null or status = ?)
       order by updated_at desc, sort asc, title asc`,
    )
    .all(opts.wpType ?? null, opts.wpType ?? null, opts.status ?? null, opts.status ?? null)
  return (rows as Record<string, unknown>[]).map((r) => hydrate(r)!)
}

export function idForSlug(slug: string): number {
  const d = open()
  const found = d.prepare("select id from wp_ids where slug = ?").get(slug) as { id?: number } | undefined
  if (found?.id) return found.id
  const r = d.prepare("insert into wp_ids (slug) values (?)").run(slug)
  return Number(r.lastInsertRowid)
}

export function slugForId(id: number): string | null {
  const r = open().prepare("select slug from wp_ids where id = ?").get(id) as { slug?: string } | undefined
  return r?.slug ?? null
}

/**
 * Create or update, preserving the partial-update contract exactly.
 *
 * AN UPDATE IS A PARTIAL UPDATE, and getting this wrong has already cost this
 * project once on the Postgres side: an early version wrote every column on
 * every call, so a content-only POST (which is what the optimize flow sends)
 * replaced the page's title and H1 with its own slug, blanked the excerpt and
 * meta description, and re-derived the editorial type from that slug. One page
 * per run, silently.
 *
 * The `coalesce(?, pages.col)` pairs below are the whole mechanism: a field the
 * caller omitted binds null and the stored value survives. Changing any of them
 * to a bare `?` reintroduces exactly that fault, which is why they are written
 * out rather than generated.
 */
export function upsert(input: {
  slug: string
  title?: string
  h1?: string
  body?: string
  excerpt?: string
  metaDescription?: string
  type?: string
  wpType: "page" | "post"
  status?: "published" | "draft"
  /** Used only on insert, where a column cannot be left unset. */
  fallbackType: string
}): ContentPage {
  const d = open()
  const now = new Date().toISOString().replace(/\.\d{3}Z$/, "Z")
  d.prepare(
    `insert into pages (slug, title, h1, body_html, excerpt, meta_description, type, wp_type, status, created_at, updated_at)
     values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     on conflict(slug) do update set
       title            = coalesce(?, pages.title),
       h1               = coalesce(?, pages.h1),
       body_html        = coalesce(?, pages.body_html),
       excerpt          = coalesce(?, pages.excerpt),
       meta_description = coalesce(?, pages.meta_description),
       type             = coalesce(?, pages.type),
       -- The caller's route WINS here, unlike every other column: the pipeline
       -- addresses a page only through the route it filed it under, so a row
       -- left under the other one can never be read or updated again.
       wp_type          = excluded.wp_type,
       status           = coalesce(?, pages.status),
       updated_at       = ?`,
  ).run(
    input.slug,
    input.title ?? input.slug,
    input.h1 ?? input.title ?? input.slug,
    input.body ?? "",
    input.excerpt ?? "",
    input.metaDescription ?? "",
    input.type ?? input.fallbackType,
    input.wpType,
    input.status ?? "published",
    now,
    now,
    // …and the update half, in the same order as the SET clauses above.
    input.title ?? null,
    input.h1 ?? null,
    input.body ?? null,
    input.excerpt ?? null,
    input.metaDescription ?? null,
    input.type ?? null,
    input.status ?? null,
    now,
  )
  const page = getPage(input.slug)
  if (!page) throw new Error(`could not write ${input.slug}`)
  return page
}

/** Renaming a slug without a redirect throws away whatever the old URL earned. */
export function rename(oldSlug: string, newSlug: string): void {
  const d = open()
  if (oldSlug === newSlug) return
  d.prepare("update pages set slug = ? where slug = ?").run(newSlug, oldSlug)
  d.prepare("update pages set hub_slug = ? where hub_slug = ?").run(newSlug, oldSlug)
  d.prepare("update wp_ids set slug = ? where slug = ?").run(newSlug, oldSlug)
  d.prepare("insert or replace into redirects (from_path, to_path) values (?, ?)").run(`/${oldSlug}`, `/${newSlug}`)
}

export function getRedirect(fromPath: string): string | null {
  const r = open().prepare("select to_path from redirects where from_path = ?").get(fromPath) as
    | { to_path?: string }
    | undefined
  return r?.to_path ?? null
}
