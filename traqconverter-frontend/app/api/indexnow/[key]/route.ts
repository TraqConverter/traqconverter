import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/**
 * The IndexNow key file, served at /<key>.txt via the rewrite in next.config.
 *
 * IndexNow verifies ownership by fetching `https://<host>/<key>.txt` and
 * requiring it to contain exactly the key. Without it every submission is
 * rejected, and SemanticWP's publish path calls submitUrlToIndexNow on every
 * page — two sibling sites published for weeks with IndexNow doing nothing at
 * all, because the guard that notices is a report nobody reads.
 *
 * The comparison is against one configured key, so this cannot be used to echo
 * arbitrary text back at a crawler.
 */
export async function GET(_req: Request, ctx: { params: Promise<{ key: string }> }) {
  const { key } = await ctx.params
  const expected = process.env.INDEXNOW_KEY
  if (!expected || key !== expected) {
    return new NextResponse("Not found", { status: 404, headers: { "Content-Type": "text/plain" } })
  }
  return new NextResponse(expected, {
    status: 200,
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "public, max-age=3600" },
  })
}
