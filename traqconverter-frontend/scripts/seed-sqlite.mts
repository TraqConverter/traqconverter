/**
 * Build the content database from the committed snapshot.
 *
 * This is the migration off the hosted Postgres: the snapshot is the rescued
 * copy of all 60 published pages, and this turns it into the SQLite file the
 * server writes to from then on. Run once per server.
 *
 * It REFUSES to touch an existing file that already holds pages. The live file
 * is the only copy of anything published since the snapshot was taken, and a
 * re-seed would silently roll the site back to export day.
 *
 *   npx tsx scripts/seed-sqlite.mts --db /path/to/site.db
 *   npx tsx scripts/seed-sqlite.mts --db /path/to/site.db --force   # only on an empty/absent file
 */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.join(here, "..")
const argv = process.argv.slice(2)
const DB = argv[argv.indexOf("--db") + 1]
const FORCE = argv.includes("--force")
if (!DB || DB.startsWith("--")) throw new Error("pass --db <path to site.db>")

const SNAP = path.join(root, "src/content/snapshot.json")
if (!fs.existsSync(SNAP)) throw new Error(`no snapshot at ${SNAP} — run export-snapshot.mts first`)
const snap = JSON.parse(fs.readFileSync(SNAP, "utf8")) as {
  exported_at?: string
  pages?: Array<Record<string, unknown>>
}
const pages = snap.pages ?? []
if (pages.length === 0) throw new Error("the snapshot holds no pages; refusing to seed an empty database")

process.env.CONTENT_SQLITE_PATH = DB
const { default: Database } = (await import("better-sqlite3")) as unknown as {
  default: new (p: string) => {
    prepare: (s: string) => { get: (...a: unknown[]) => unknown; run: (...a: unknown[]) => unknown }
    exec: (s: string) => void
    transaction: <T>(fn: T) => T
  }
}

fs.mkdirSync(path.dirname(DB), { recursive: true })
const db = new Database(DB)
db.exec("pragma journal_mode = WAL;")

// Reuse the application's own schema rather than a second copy of it here: two
// definitions of one table drift, and the one that drifts is never the one
// anybody reads.
const storeSrc = fs.readFileSync(path.join(root, "src/lib/content/store-sqlite.ts"), "utf8")
const schema = /const SCHEMA = `([\s\S]*?)`/.exec(storeSrc)?.[1]
if (!schema) throw new Error("could not read SCHEMA out of store-sqlite.ts")
db.exec(schema)

const existing = (db.prepare("select count(*) as n from pages").get() as { n: number }).n
if (existing > 0 && !FORCE) {
  console.error(
    `REFUSING: ${DB} already holds ${existing} page(s).\n` +
      `That file is the only copy of anything published since the snapshot was taken\n` +
      `(${snap.exported_at ?? "unknown date"}); re-seeding would roll the site back to it.\n` +
      `Pass --force only if you are certain this database is disposable.`,
  )
  process.exit(1)
}

const insert = db.prepare(
  `insert or replace into pages
     (slug, title, h1, meta_description, body_html, excerpt, type, wp_type, hub_slug, status,
      faq, schema_json, canonical, in_nav, sort, created_at, updated_at)
   values (@slug, @title, @h1, @meta_description, @body_html, @excerpt, @type, @wp_type, @hub_slug, @status,
      @faq, @schema_json, @canonical, @in_nav, @sort, @created_at, @updated_at)`,
)
const mapId = db.prepare("insert or ignore into wp_ids (slug) values (?)")

const now = new Date().toISOString().replace(/\.\d{3}Z$/, "Z")
const run = db.transaction((rows: Array<Record<string, unknown>>) => {
  for (const p of rows) {
    insert.run({
      slug: String(p.slug),
      title: String(p.title ?? p.slug),
      h1: String(p.h1 ?? p.title ?? ""),
      meta_description: String(p.meta_description ?? ""),
      body_html: String(p.body_html ?? ""),
      excerpt: String(p.excerpt ?? ""),
      type: String(p.type ?? "generic"),
      wp_type: String(p.wp_type ?? "page"),
      hub_slug: p.hub_slug ? String(p.hub_slug) : null,
      status: String(p.status ?? "published"),
      // SQLite has no json or boolean type.
      faq: JSON.stringify(p.faq ?? []),
      schema_json: p.schema_json == null ? null : JSON.stringify(p.schema_json),
      canonical: String(p.canonical ?? ""),
      in_nav: p.in_nav ? 1 : 0,
      sort: Number(p.sort ?? 100),
      created_at: String(p.created_at ?? now),
      updated_at: String(p.updated_at ?? now),
    })
    mapId.run(String(p.slug))
  }
})
// hub_slug is a self-reference, so a child inserted before its hub would fail
// the foreign key. One transaction with the constraint deferred is simpler than
// sorting the rows into dependency order.
db.exec("pragma foreign_keys = off")
run(pages)
db.exec("pragma foreign_keys = on")

const n = (db.prepare("select count(*) as n from pages").get() as { n: number }).n
const published = (db.prepare("select count(*) as n from pages where status = 'published'").get() as { n: number }).n
const ids = (db.prepare("select count(*) as n from wp_ids").get() as { n: number }).n
const bytes = (db.prepare("select sum(length(body_html)) as n from pages").get() as { n: number }).n
console.log(`seeded ${DB}`)
console.log(`   ${n} page(s), ${published} published, ${ids} wp_id mapping(s), ${Math.round(bytes / 1024)} KB of bodies`)
const orphans = db.prepare("select count(*) as n from pages where hub_slug is not null and hub_slug not in (select slug from pages)").get() as { n: number }
if (orphans.n) console.warn(`   ${orphans.n} page(s) point at a hub that is not in the snapshot`)
