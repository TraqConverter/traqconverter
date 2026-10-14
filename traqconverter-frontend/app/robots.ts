import type { MetadataRoute } from "next"
import { SITE_URL } from "@/lib/content/config"

/**
 * There was no robots.txt: /robots.txt answered 404.
 *
 * Everything behind sign-in is disallowed, both because it is useless to a
 * crawler and because /d/ serves signed download links. The content section and
 * the public product pages are left open.
 *
 * One Sitemap line, pointing at the one sitemap. A sibling site advertises nine
 * overlapping sitemap URLs and another advertises a set chosen to match a
 * WordPress install it never had — neither helps, and both make it harder to
 * tell what Google is actually reading.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          "/api/",
          "/admin",
          "/dashboard",
          "/editor",
          "/jobs",
          "/media",
          "/settings",
          "/billing",
          "/new-translation",
          "/success",
          "/cancel",
          "/login",
          "/register",
          "/forgot-password",
          "/reset-password",
          // Signed, expiring links to a customer's own files.
          "/d/",
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  }
}
