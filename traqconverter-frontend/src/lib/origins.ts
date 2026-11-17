// The marketing site (landing, /guides, legal) and the app run from the same build on two hosts.
// Pure module: imported by proxy.ts, the components and the node:test suite alike.

function trimOrigin(value: string): string {
  return value.trim().replace(/\/+$/, "")
}

// Empty string means "same origin": links stay relative. Local dev gets that by default.
export const APP_ORIGIN = trimOrigin(
  process.env.NEXT_PUBLIC_APP_ORIGIN ??
    (process.env.NODE_ENV === "development" ? "" : "https://app.onlinedoctranslator.ai"),
)

export const MARKETING_ORIGIN = trimOrigin(
  process.env.NEXT_PUBLIC_MARKETING_ORIGIN ?? process.env.NEXT_PUBLIC_SITE_URL ?? "https://www.onlinedoctranslator.ai",
)

export function appUrl(path: string): string {
  return `${APP_ORIGIN}${path}`
}

const LEGAL_PATHS = new Set(["/terms", "/privacy", "/cookies", "/security", "/dpa"])

// Served on both hosts and never redirected: legal pages (linked from inside the app), build output and files in public/.
export function isSharedRoute(pathname: string): boolean {
  return (
    LEGAL_PATHS.has(pathname) ||
    pathname === "/robots.txt" ||
    pathname.startsWith("/_next/") ||
    pathname.startsWith("/.well-known/") ||
    pathname.startsWith("/brand/") ||
    pathname.startsWith("/fonts/") ||
    pathname.startsWith("/landing/") ||
    // icon.svg, apple-icon.png, favicon.ico, the IndexNow <key>.txt and anything else at the root of public/.
    /^\/[^/]+\.[a-z0-9]+$/i.test(pathname)
  )
}

// Belongs on the marketing host only; on the app host it is redirected there.
export function isMarketingRoute(pathname: string): boolean {
  return (
    pathname === "/" ||
    pathname === "/guides" ||
    pathname.startsWith("/guides/") ||
    pathname === "/sitemap.xml" ||
    pathname === "/wp-json" ||
    pathname.startsWith("/wp-json/") ||
    pathname.startsWith("/api/indexnow/")
  )
}

export type HostKind = "app" | "marketing" | "other"

function hostnameOf(origin: string): string | null {
  try {
    return origin ? new URL(origin).hostname.toLowerCase() : null
  } catch {
    return null
  }
}

function apexTwin(hostname: string): string {
  return hostname.startsWith("www.") ? hostname.slice(4) : `www.${hostname}`
}

const NEVER_REDIRECT = /^(localhost|127\.\d+\.\d+\.\d+|\[::1\]|::1)$|\.vercel\.app$|\.local$/

// Only known production hosts are classified; localhost, Vercel previews and anything unknown are "other" and never redirected.
export function classifyHost(
  host: string | null | undefined,
  appOrigin: string = APP_ORIGIN,
  marketingOrigin: string = MARKETING_ORIGIN,
): HostKind {
  if (!host) return "other"
  const hostname = host.toLowerCase().replace(/:\d+$/, "")
  if (NEVER_REDIRECT.test(hostname)) return "other"
  const app = hostnameOf(appOrigin)
  const marketing = hostnameOf(marketingOrigin)
  // A same-host config (or a missing app origin) would loop; treat it as no split at all.
  if (!app || !marketing || app === marketing) return "other"
  if (hostname === app) return "app"
  if (hostname === marketing || hostname === apexTwin(marketing)) return "marketing"
  // The Cloudways staging hostname of the marketing server.
  if (hostname.endsWith(".cloudwaysapps.com")) return "marketing"
  return "other"
}

export type HostDecision =
  | { action: "next"; noindex: boolean }
  | { action: "redirect"; location: string; status: 307 | 308 }
  | { action: "robots-disallow" }

export function decideHostRouting(
  host: string | null | undefined,
  pathname: string,
  search: string,
  appOrigin: string = APP_ORIGIN,
  marketingOrigin: string = MARKETING_ORIGIN,
): HostDecision {
  const kind = classifyHost(host, appOrigin, marketingOrigin)
  if (kind === "other") return { action: "next", noindex: false }

  if (kind === "marketing") {
    if (isSharedRoute(pathname) || isMarketingRoute(pathname)) return { action: "next", noindex: false }
    return { action: "redirect", location: `${appOrigin}${pathname}${search}`, status: 308 }
  }

  if (pathname === "/robots.txt") return { action: "robots-disallow" }
  // Temporary: /login sends a signed-in visitor on to /dashboard, and that answer depends on the visitor.
  if (pathname === "/") return { action: "redirect", location: `${appOrigin}/login${search}`, status: 307 }
  if (isMarketingRoute(pathname)) {
    return { action: "redirect", location: `${marketingOrigin}${pathname}${search}`, status: 308 }
  }
  return { action: "next", noindex: true }
}
