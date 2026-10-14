import { NextResponse } from "next/server"
import {
  authorized,
  listAllPages,
  slugForId,
  toWpObject,
  upsertFromWp,
} from "@/lib/content/wp-shim"
import { normaliseSlug } from "@/lib/content/pages"

export const runtime = "nodejs"
// Writing a page is a database round trip, not a build.
export const dynamic = "force-dynamic"

/**
 * The WordPress REST surface SemanticWP drives.
 *
 * Implemented:
 *   GET  /users/me               the connection test
 *   GET  /types                  what post types exist
 *   GET  /pages|posts            the INVENTORY LISTING — array plus x-wp-total
 *   GET  /pages|posts?slug=      the duplicate probe
 *   GET  /pages|posts/<id>
 *   POST /pages|posts            create
 *   POST /pages|posts/<id>       update
 *   POST /media                  501, deliberately
 *
 * The listing route is the one that matters most and is easiest to get wrong.
 * Answering `[]` instead of the real inventory does not error anywhere — the
 * pipeline simply believes the site is empty, mirrors nothing, and then has no
 * targets for internal links and nothing to compare new pages against. Two
 * sibling sites ran that way for months.
 */

function deny() {
  return NextResponse.json(
    { code: "rest_not_logged_in", message: "Not authenticated.", data: { status: 401 } },
    { status: 401 },
  )
}

function notFound() {
  return NextResponse.json(
    { code: "rest_post_invalid_id", message: "Invalid post ID.", data: { status: 404 } },
    { status: 404 },
  )
}

const POST_TYPES = new Set(["pages", "posts"])

export async function GET(req: Request, ctx: { params: Promise<{ route?: string[] }> }) {
  if (!authorized(req)) return deny()
  const { route = [] } = await ctx.params
  const [head, second] = route
  const url = new URL(req.url)

  if (head === "users" && second === "me") {
    return NextResponse.json({
      id: 1,
      name: process.env.CONTENT_WP_USERNAME ?? "pipeline",
      slug: "pipeline",
      // The pipeline checks for publish capability before it tries to publish.
      capabilities: { edit_posts: true, publish_posts: true, edit_pages: true, publish_pages: true, upload_files: false },
    })
  }

  if (head === "types") {
    return NextResponse.json({
      page: { slug: "page", rest_base: "pages", name: "Pages" },
      post: { slug: "post", rest_base: "posts", name: "Posts" },
    })
  }

  if (head && POST_TYPES.has(head)) {
    const wantPosts = head === "posts"
    const all = await listAllPages()
    // `question` pages are the "posts"; everything else is a "page". The
    // pipeline asks for each separately and expects them not to overlap.
    const mine = all.filter((p) => (p.type === "question") === wantPosts)

    // /pages/<id>
    if (second && /^\d+$/.test(second)) {
      const slug = await slugForId(Number(second))
      const page = slug ? mine.find((p) => p.slug === slug) : undefined
      if (!page) return notFound()
      return NextResponse.json(await toWpObject(page))
    }

    const slugParam = url.searchParams.get("slug")
    const subset = slugParam
      ? mine.filter((p) => p.slug === normaliseSlug(slugParam))
      : mine

    const perPage = Math.min(100, Math.max(1, Number(url.searchParams.get("per_page") ?? 100)))
    const page = Math.max(1, Number(url.searchParams.get("page") ?? 1))
    const slice = subset.slice((page - 1) * perPage, page * perPage)
    const body = await Promise.all(slice.map(toWpObject))

    // x-wp-total is not decoration: the pipeline reads it to know whether it
    // has seen the whole inventory, and refuses to trust a sync that fetched
    // nothing.
    return NextResponse.json(body, {
      headers: {
        "x-wp-total": String(subset.length),
        "x-wp-totalpages": String(Math.max(1, Math.ceil(subset.length / perPage))),
      },
    })
  }

  return notFound()
}

export async function POST(req: Request, ctx: { params: Promise<{ route?: string[] }> }) {
  if (!authorized(req)) return deny()
  const { route = [] } = await ctx.params
  const [head, second] = route

  if (head === "media") {
    // Answer 501 rather than 404 or a silent success. The pipeline's
    // canAcceptUploads() treats 501 as "this site cannot store images" and
    // skips generation — a 404 instead makes it pay for images it then bins.
    return NextResponse.json(
      { code: "rest_cannot_upload", message: "This site does not store media.", data: { status: 501 } },
      { status: 501 },
    )
  }

  if (!head || !POST_TYPES.has(head)) return notFound()

  let payload: Record<string, unknown>
  try {
    payload = (await req.json()) as Record<string, unknown>
  } catch {
    return NextResponse.json(
      { code: "rest_invalid_json", message: "Body is not JSON.", data: { status: 400 } },
      { status: 400 },
    )
  }

  const asText = (v: unknown): string => {
    if (typeof v === "string") return v
    if (v && typeof v === "object" && "raw" in v) return String((v as { raw?: unknown }).raw ?? "")
    if (v && typeof v === "object" && "rendered" in v) return String((v as { rendered?: unknown }).rendered ?? "")
    return ""
  }

  // An update addresses an existing id; a create does not.
  let slug: string | undefined
  if (second && /^\d+$/.test(second)) {
    const found = await slugForId(Number(second))
    if (!found) return notFound()
    slug = found
  } else if (typeof payload.slug === "string" && payload.slug.trim()) {
    slug = normaliseSlug(payload.slug)
  }

  const title = asText(payload.title)
  if (!title && !slug) {
    return NextResponse.json(
      { code: "rest_empty_title", message: "A title or an existing id is required.", data: { status: 400 } },
      { status: 400 },
    )
  }

  const { page, id } = await upsertFromWp({
    title: title || (slug ?? ""),
    content: asText(payload.content),
    excerpt: asText(payload.excerpt),
    status: typeof payload.status === "string" ? payload.status : undefined,
    slug,
    postType: head === "posts" ? "post" : "page",
    metaDescription:
      typeof payload.meta === "object" && payload.meta
        ? String((payload.meta as Record<string, unknown>)._yoast_wpseo_metadesc ?? "")
        : "",
  })

  return NextResponse.json(await toWpObject(page), { status: second ? 200 : 201, headers: { "x-wp-id": String(id) } })
}

/** The pipeline probes with HEAD before trusting the connection. */
export async function HEAD(req: Request) {
  return authorized(req) ? new Response(null, { status: 200 }) : new Response(null, { status: 401 })
}
