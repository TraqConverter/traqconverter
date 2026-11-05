/**
 * The publish path end to end, against a database seeded from the real snapshot.
 *
 *   npx tsx scripts/seed-sqlite.mts --db /tmp/odt-e2e.db
 *   NODE_OPTIONS=--conditions=react-server npx tsx scripts/test-shim-sqlite.mts
 */
process.env.CONTENT_SQLITE_PATH = process.env.TEST_DB ?? "/tmp/odt-e2e.db"
const shim = await import("../src/lib/content/wp-shim.ts")
const pages = await import("../src/lib/content/pages.ts")

let bad = 0
const ck = (n: string, c: boolean, d = "") => { if (!c) { bad++; console.error("FAIL", n, d) } else console.log("  ok  ", n) }

// A create, as the pipeline sends it.
const made = await shim.upsertFromWp({
  title: "A Brand New Guide", content: "<h1>A Brand New Guide</h1><p>Body text here.</p>",
  excerpt: "An excerpt", metaDescription: "A meta description",
  status: "publish", postType: "page", isUpdate: false,
})
ck("a create returns a page and an id", made.id > 0 && made.page.slug === "a-brand-new-guide", `${made.id} ${made.page.slug}`)
ck("the leading H1 is lifted out of the body", !made.page.body_html.includes("<h1>"), made.page.body_html.slice(0, 60))
ck("…and becomes the page h1", made.page.h1 === "A Brand New Guide", made.page.h1)

// THE PARTIAL UPDATE: the optimize flow sends only content, addressed by id.
const slug = await shim.slugForId(made.id)
ck("the id maps back to the slug", slug === "a-brand-new-guide", String(slug))
const updated = await shim.upsertFromWp({
  content: "<p>Rewritten body.</p>", postType: "page", slug: slug!, isUpdate: true,
})
ck("title survives a content-only update", updated.page.title === "A Brand New Guide", updated.page.title)
ck("excerpt survives", updated.page.excerpt === "An excerpt", updated.page.excerpt)
ck("meta survives", updated.page.meta_description === "A meta description", updated.page.meta_description)
ck("the body changed", updated.page.body_html.includes("Rewritten"), updated.page.body_html.slice(0, 40))
ck("the id is stable across the update", (await shim.idForSlug("a-brand-new-guide")) === made.id)

// The listing route the pipeline mirrors from — the one that bit two siblings.
const all = await shim.listAllPages()
ck("the listing returns every page, drafts included", all.length >= 61, String(all.length))
ck("the new page is in it", all.some((p) => p.slug === "a-brand-new-guide"))
const published = await shim.listAllPages({ status: "publish" })
ck("filtering by publish works", published.every((p) => p.status === "published"))
const posts = await shim.listAllPages({ wpType: "post" })
ck("filtering by route works", posts.every((p) => p.wp_type === "post") && posts.length > 0, String(posts.length))

// A draft must not be publicly readable, exactly as the SQL filtered.
await shim.upsertFromWp({ title: "A Hidden Draft", content: "<p>x</p>", status: "draft", postType: "page", isUpdate: false })
ck("a draft is not served publicly", (await pages.getPage("a-hidden-draft")) === null)
ck("…but the shim can still see it", (await shim.listAllPages()).some((p) => p.slug === "a-hidden-draft"))

// And the public read path sees the newly published page immediately —
// the whole reason writes moved off the snapshot.
const live = await pages.getPage("a-brand-new-guide")
ck("a page published now is readable now", !!live && live.body_html.includes("Rewritten"))
const idx = await pages.listPageIndex()
ck("and it is in the index", idx.some((p) => p.slug === "a-brand-new-guide"))
ck("the index still carries the seeded pages", idx.length >= 61, String(idx.length))

if (bad) { console.error(`\n${bad} failure(s)`); process.exit(1) }
console.log("\nshim over sqlite: all checks passed")
