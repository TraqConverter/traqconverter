// Reachable without a token. Signed-in users visiting these are sent into the app.
const PUBLIC_ROUTES = new Set(["/", "/login", "/register"])

export function isPublicRoute(pathname: string): boolean {
  return PUBLIC_ROUTES.has(pathname)
}

const LEGAL_ROUTES = new Set(["/terms", "/privacy", "/cookies", "/security", "/dpa"])
// Open rather than public: an emailed reset link must work even in a browser that is still signed in.
const PASSWORD_RESET_ROUTES = new Set(["/forgot-password", "/reset-password"])

// Reachable with or without a token, and shown without the app chrome (client download links, legal pages, password reset).
//
// /guides is OPEN, not public. Open because it has to render on the server for
// anyone, signed in or not: the guard's server snapshot is always "no token", so
// a route that is neither public nor open renders "Loading..." and then
// client-redirects to /login. The whole content section served an empty shell
// and a redirect to a search engine — a section that cannot be read cannot
// rank, and the AI crawlers that drive a third of this estate's referrals do not
// run JavaScript at all. Public would be wrong for the opposite reason: a
// signed-in reader following a link to a guide would be thrown into /dashboard.
export function isOpenRoute(pathname: string): boolean {
  return (
    pathname.startsWith("/d/") ||
    pathname === "/guides" ||
    pathname.startsWith("/guides/") ||
    LEGAL_ROUTES.has(pathname) ||
    PASSWORD_RESET_ROUTES.has(pathname)
  )
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
