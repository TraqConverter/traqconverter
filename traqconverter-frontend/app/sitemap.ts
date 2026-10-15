import type { MetadataRoute } from "next"
import { listPages } from "@/lib/content/pages"
import { CONTENT_BASE, SITE_URL, contentUrl } from "@/lib/content/config"

// GENERATED PER REQUEST, not cached.
//
// It was `revalidate = 300`, and that did not work: a page published half an
// hour earlier was still missing, the CDN serving a HIT at age 410 — past its
// own window — while the sitemap listed 3 guides and the database held 4. A
// sitemap that silently lists fewer URLs than the site serves is
// indistinguishable from a small site, which is the exact failure the note
// below is about, so it must not depend on a cache expiring on time.
//
// The cost is one query per fetch, on a route a crawler reads occasionally, and
// the guide pages themselves already render per request.
export const dynamic = "force-dynamic"
export const revalidate = 0

/**
 * The site had no sitemap and no robots.txt at all — /sitemap.xml and
 * /robots.txt both answered 404 — so nothing told Google what exists here.
 *
 * Only PUBLISHED pages appear: listPages filters drafts. The count must equal
 * the number of published pages, and on the sibling sites that equality is the
 * check that catches a broken content layer, because a sitemap that silently
 * lists fewer URLs than the site serves is indistinguishable from a small site.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // The product pages a visitor can reach without signing in. Listed by hand
  // because the app's other twenty-two routes are behind auth and must not be
  // advertised.
  const appPages: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/certifications`, changeFrequency: "monthly", priority: 0.7 },
    { url: `${SITE_URL}/templates`, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/translation-memory`, changeFrequency: "monthly", priority: 0.6 },
    { url: `${SITE_URL}/terms`, changeFrequency: "yearly", priority: 0.1 },
    { url: `${SITE_URL}/privacy`, changeFrequency: "yearly", priority: 0.1 },
    { url: `${SITE_URL}/cookies`, changeFrequency: "yearly", priority: 0.1 },
  ]

  let guides: MetadataRoute.Sitemap = []
  try {
    const pages = await listPages()
    guides = pages.map((p) => ({
      url: contentUrl(p.slug),
      lastModified: new Date(p.updated_at),
      changeFrequency: p.type === "question" ? ("monthly" as const) : ("weekly" as const),
      // A hub outranks its own spokes; both outrank a legal page.
      priority: p.type === "question" ? 0.6 : p.slug === "home" ? 0.9 : 0.8,
    }))
  } catch {
    // Before the content database exists this throws, and a sitemap that 500s
    // is worse than one listing only the product pages — Google retries a 200.
    guides = [{ url: `${SITE_URL}/${CONTENT_BASE}`, changeFrequency: "weekly", priority: 0.9 }]
  }

  return [...appPages, ...guides]
}
