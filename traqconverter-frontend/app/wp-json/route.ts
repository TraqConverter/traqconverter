import { NextResponse } from "next/server"
import { SITE_URL } from "@/lib/content/config"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/**
 * The REST root, UNAUTHENTICATED.
 *
 * SemanticWP's `testConnection` fetches exactly this before it checks any
 * credential and refuses the site on a non-2xx, and `checkShimConformance`
 * lists it as required — so a shim without it cannot be connected at all, and
 * the error it produces blames WordPress and a security plugin, neither of
 * which exists here. All six sibling sites were missing it on 2026-09-28; the
 * five already in the database only survived because nothing re-runs the check
 * on a site already connected.
 *
 * Unauthenticated on purpose: WordPress serves its index to anyone, the probe
 * sends no credential, and nothing here is a secret. The namespaces advertised
 * are only the ones actually implemented — claiming more would make a later
 * failure look like a bug rather than a gap.
 */
export async function GET() {
  return NextResponse.json({
    name: "OnlineDocTranslator",
    description: "Guides for translators and translation agencies",
    url: SITE_URL,
    home: SITE_URL,
    gmt_offset: 0,
    timezone_string: "UTC",
    namespaces: ["wp/v2"],
    authentication: {},
    routes: {
      "/wp/v2": { namespace: "wp/v2", methods: ["GET"] },
      "/wp/v2/types": { namespace: "wp/v2", methods: ["GET"] },
      "/wp/v2/users/me": { namespace: "wp/v2", methods: ["GET"] },
      "/wp/v2/pages": { namespace: "wp/v2", methods: ["GET", "POST"] },
      "/wp/v2/posts": { namespace: "wp/v2", methods: ["GET", "POST"] },
    },
  })
}
