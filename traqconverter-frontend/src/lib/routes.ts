// Reachable without a token. Signed-in users visiting these are sent into the app.
const PUBLIC_ROUTES = new Set(["/", "/login", "/register"])

export function isPublicRoute(pathname: string): boolean {
  return PUBLIC_ROUTES.has(pathname)
}

const LEGAL_ROUTES = new Set(["/terms", "/privacy", "/cookies"])

// Reachable with or without a token, and shown without the app chrome (client download links, legal pages).
export function isOpenRoute(pathname: string): boolean {
  return pathname.startsWith("/d/") || LEGAL_ROUTES.has(pathname)
}

export function safeNextPath(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return "/dashboard"
  }
  if (isPublicRoute(next.split("?")[0])) return "/dashboard"
  return next
}

export function loginUrl(next?: string): string {
  if (!next || isPublicRoute(next.split("?")[0])) return "/login"
  return `/login?next=${encodeURIComponent(next)}`
}
