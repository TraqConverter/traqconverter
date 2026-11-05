/**
 * The content store, tested against a database seeded from the real snapshot.
 *
 *   npx tsx scripts/seed-sqlite.mts --db /tmp/odt-test.db
 *   NODE_OPTIONS=--conditions=react-server npx tsx scripts/test-store-sqlite.mts
 *
 * The condition is required because `server-only` throws by design outside a
 * server build; its react-server export is the no-op the Next compiler uses.
 */
process.env.CONTENT_SQLITE_PATH = process.env.TEST_DB ?? "/tmp/odt-test.db"
const s = await import("../src/lib/content/store-sqlite.ts")
let bad = 0
const ck = (n: string, c: boolean, d = "") => { if (!c) { bad++; console.error("FAIL", n, d) } else console.log("  ok  ", n) }

// A real page from the rescued snapshot.
const before = s.getPage("cat-tool")!
ck("a seeded page reads back", !!before && before.body_html.length > 1000, String(before?.body_html?.length))
ck("faq hydrates to an array", Array.isArray(before.faq))
ck("in_nav is a boolean, not 0/1", typeof before.in_nav === "boolean")

/**
 * THE ONE THAT MATTERS. The optimize flow POSTs only `content`. On the
 * Postgres side an early version wrote every column, so that call replaced the
 * title and H1 with the slug and blanked the excerpt and meta description.
 */
const after = s.upsert({ slug: "cat-tool", body: "<p>new body</p>", wpType: "page", fallbackType: "generic" })
ck("title survives a content-only update", after.title === before.title, `${before.title} -> ${after.title}`)
ck("h1 survives", after.h1 === before.h1, `${before.h1} -> ${after.h1}`)
ck("excerpt survives", after.excerpt === before.excerpt)
ck("meta description survives", after.meta_description === before.meta_description)
ck("type survives", after.type === before.type, `${before.type} -> ${after.type}`)
ck("status survives", after.status === before.status)
ck("the body DID change", after.body_html === "<p>new body</p>")
ck("updated_at moved", after.updated_at >= before.updated_at)

// A title-only update changes the title and leaves the body.
const t = s.upsert({ slug: "cat-tool", title: "A New Title", wpType: "page", fallbackType: "generic" })
ck("title-only update sets the title", t.title === "A New Title")
ck("…and leaves the body alone", t.body_html === "<p>new body</p>")

// wp_type is the exception: the caller's route wins.
const w = s.upsert({ slug: "cat-tool", wpType: "post", fallbackType: "generic" })
ck("wp_type follows the caller", w.wp_type === "post", w.wp_type)

// A create still works and gets an id.
const made = s.upsert({ slug: "brand-new-page", title: "Brand New", wpType: "page", fallbackType: "generic", body: "<p>x</p>" })
ck("a create inserts", made.slug === "brand-new-page" && made.title === "Brand New")
const id1 = s.idForSlug("brand-new-page")
const id2 = s.idForSlug("brand-new-page")
ck("wp_id is stable across calls", id1 === id2 && id1 > 0, `${id1} vs ${id2}`)
ck("and maps back", s.slugForId(id1) === "brand-new-page")

// An unknown type must be refused, not silently stored.
let refused = false
try { s.upsert({ slug: "bad-type", title: "x", wpType: "page", fallbackType: "nonsense" }) } catch { refused = true }
ck("an invalid page type is refused by the schema", refused)

// Rename leaves a redirect behind.
s.rename("brand-new-page", "renamed-page")
ck("rename moves the page", !!s.getPage("renamed-page") && !s.getPage("brand-new-page"))
ck("rename leaves a redirect", s.getRedirect("/brand-new-page") === "/renamed-page", String(s.getRedirect("/brand-new-page")))
ck("and the wp_id follows the rename", s.slugForId(id1) === "renamed-page", String(s.slugForId(id1)))

// Listing filters.
ck("list published", s.listPages({ status: "published" }).length >= 60)
ck("list by route", s.listPages({ wpType: "post" }).every((p) => p.wp_type === "post"))

if (bad) { console.error(`\n${bad} failure(s)`); process.exit(1) }
console.log("\nstore-sqlite: all checks passed")
