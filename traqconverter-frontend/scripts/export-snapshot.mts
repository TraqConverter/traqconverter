/**
 * Dump every published page to a file the site can serve without a database.
 *
 * WHY. This section serves 62 pages out of a hosted Postgres, and on 2026-10-29
 * that database hit its free-tier EGRESS limit and answered HTTP 402 to every
 * query. All 62 guides served 500s for a week while the homepage — which
 * touches no database — stayed up. Shipping page bodies over the wire on every
 * revalidation to render content that changes a few times a day is the whole
 * fault; a snapshot in the repo makes that egress zero.
 *
 * It is ALSO the only backup. The full bodies exist nowhere else: the
 * pipeline's own cache is capped at 50KB and 34 of the 62 are truncated by it.
 * Run this whenever the database is reachable, and commit the result.
 *
 *   npx tsx scripts/export-snapshot.mts            # writes src/content/snapshot.json
 *   npx tsx scripts/export-snapshot.mts --check    # report only, write nothing
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");
const OUT = path.join(root, "src/content/snapshot.json");
const CHECK = process.argv.includes("--check");

for (const line of fs.readFileSync(path.join(root, ".env.local"), "utf8").split("\n")) {
  const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
  if (m && !process.env[m[1]]) process.env[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
}

const url =
  process.env.CONTENT_DATABASE_URL ?? process.env.DATABASE_URL ?? process.env.POSTGRES_URL;
if (!url) throw new Error("no content database URL in .env.local");

const { neon } = await import("@neondatabase/serverless");
const sql = neon(url);

let rows: Array<Record<string, unknown>>;
try {
  rows = (await sql`
    select slug, title, h1, meta_description, body_html, excerpt, type, wp_type, hub_slug, status,
           faq, schema_json, canonical, in_nav, sort,
           to_char(created_at at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as created_at,
           to_char(updated_at at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as updated_at
    from content.pages
    where status = 'published'
    order by sort asc, title asc
  `) as unknown as Array<Record<string, unknown>>;
} catch (e) {
  const msg = String((e as Error)?.message ?? e);
  console.error(`could not read the content database: ${msg.slice(0, 160)}`);
  if (/quota/i.test(msg)) {
    console.error(
      "\nThe quota is still exceeded, so there is nothing to export. This snapshot is what\n" +
        "ends that for good — run it the moment the database answers, and commit the file.",
    );
  }
  process.exit(1);
}

/**
 * REFUSE TO WRITE A WORSE SNAPSHOT THAN THE ONE ALREADY COMMITTED.
 *
 * This file is the site's only full copy of its own content. A run against a
 * half-populated or partially-restored database would otherwise overwrite a
 * good backup with a worse one, silently, and that is unrecoverable.
 */
const previous: { pages?: Array<{ slug: string; body_html?: string }> } = fs.existsSync(OUT)
  ? JSON.parse(fs.readFileSync(OUT, "utf8"))
  : {};
const prevPages = previous.pages ?? [];
const bytes = (r: Array<{ body_html?: string }>) => r.reduce((n, p) => n + String(p.body_html ?? "").length, 0);
const now = rows as unknown as Array<{ slug: string; body_html?: string }>;

console.log(`database: ${now.length} published page(s), ${(bytes(now) / 1024).toFixed(0)} KB of bodies`);
if (prevPages.length) {
  console.log(`snapshot: ${prevPages.length} page(s), ${(bytes(prevPages) / 1024).toFixed(0)} KB`);
  const lostSlugs = prevPages.filter((p) => !now.some((n) => n.slug === p.slug)).map((p) => p.slug);
  const emptied = now.filter((n) => {
    const was = prevPages.find((p) => p.slug === n.slug);
    return was && String(was.body_html ?? "").length > 500 && String(n.body_html ?? "").length < 500;
  });
  if (lostSlugs.length || emptied.length) {
    console.error(`\nREFUSING to overwrite the snapshot:`);
    for (const s of lostSlugs.slice(0, 10)) console.error(`   would lose entirely: ${s}`);
    for (const p of emptied.slice(0, 10)) console.error(`   would empty the body: ${p.slug}`);
    console.error(`\nIf the database really is the newer truth, delete ${path.relative(root, OUT)} and re-run.`);
    process.exit(1);
  }
}

const empty = now.filter((p) => String(p.body_html ?? "").length < 500);
if (empty.length) console.warn(`${empty.length} page(s) have almost no body: ${empty.slice(0, 5).map((p) => p.slug).join(", ")}`);

if (CHECK) {
  console.log("\n--check — nothing written");
  process.exit(0);
}
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify({ exported_at: new Date().toISOString(), pages: rows }, null, 0));
console.log(`\nwrote ${path.relative(root, OUT)} — commit it; it is the only full copy of this content.`);
