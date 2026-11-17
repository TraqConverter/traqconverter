import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"
import { decideHostRouting } from "@/lib/origins"

const NOINDEX = "noindex, nofollow"

export function proxy(request: NextRequest) {
  // Host, not X-Forwarded-Host: the Cloudways PHP proxy sets Host itself but passes a client's X-Forwarded-Host through.
  const host = request.headers.get("host")
  const { pathname, search } = request.nextUrl
  const decision = decideHostRouting(host, pathname, search)

  if (decision.action === "redirect") {
    return NextResponse.redirect(decision.location, decision.status)
  }
  if (decision.action === "robots-disallow") {
    return new NextResponse("User-agent: *\nDisallow: /\n", {
      headers: { "Content-Type": "text/plain; charset=utf-8", "X-Robots-Tag": NOINDEX },
    })
  }
  if (decision.noindex) {
    const response = NextResponse.next()
    response.headers.set("X-Robots-Tag", NOINDEX)
    return response
  }
  return NextResponse.next()
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
}
