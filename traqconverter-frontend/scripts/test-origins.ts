// Host x path matrix for the www / app split in proxy.ts.
//
//   npx tsx scripts/test-origins.ts
import { test } from "node:test"
import assert from "node:assert/strict"
import { classifyHost, decideHostRouting, isMarketingRoute, isSharedRoute } from "../src/lib/origins"

const APP = "https://app.onlinedoctranslator.ai"
const WWW = "https://www.onlinedoctranslator.ai"
const decide = (host: string, path: string, search = "") => decideHostRouting(host, path, search, APP, WWW)

const toApp = (pathAndQuery: string) => ({ action: "redirect", location: `${APP}${pathAndQuery}`, status: 308 })
const toWww = (pathAndQuery: string) => ({ action: "redirect", location: `${WWW}${pathAndQuery}`, status: 308 })
const stay = { action: "next", noindex: false }
const stayNoindex = { action: "next", noindex: true }

test("hosts", () => {
  assert.equal(classifyHost("app.onlinedoctranslator.ai", APP, WWW), "app")
  assert.equal(classifyHost("APP.onlinedoctranslator.ai:443", APP, WWW), "app")
  assert.equal(classifyHost("www.onlinedoctranslator.ai", APP, WWW), "marketing")
  assert.equal(classifyHost("onlinedoctranslator.ai", APP, WWW), "marketing")
  assert.equal(classifyHost("phpstack-123-456.cloudwaysapps.com", APP, WWW), "marketing")
  assert.equal(classifyHost("localhost:3000", APP, WWW), "other")
  assert.equal(classifyHost("127.0.0.1:3100", APP, WWW), "other")
  assert.equal(classifyHost("traqconverter-git-feat-x-traqworx.vercel.app", APP, WWW), "other")
  assert.equal(classifyHost("evil.example.com", APP, WWW), "other")
  assert.equal(classifyHost(null, APP, WWW), "other")
  // No split configured: never classify, so nothing can loop.
  assert.equal(classifyHost("www.onlinedoctranslator.ai", "", WWW), "other")
  assert.equal(classifyHost("www.onlinedoctranslator.ai", WWW, WWW), "other")
})

test("route lists", () => {
  for (const p of ["/", "/guides", "/guides/x", "/guides/a/b", "/sitemap.xml", "/wp-json", "/wp-json/wp/v2/pages", "/api/indexnow/k"]) {
    assert.ok(isMarketingRoute(p), p)
  }
  for (const p of ["/terms", "/privacy", "/cookies", "/security", "/dpa", "/robots.txt", "/_next/static/chunks/a.js",
    "/_next/image", "/icon.svg", "/apple-icon.png", "/favicon.ico", "/brand/logo.png", "/fonts/office/x.woff2",
    "/landing/hero.webp", "/abc123.txt", "/.well-known/security.txt"]) {
    assert.ok(isSharedRoute(p), p)
  }
  for (const p of ["/login", "/register", "/dashboard", "/d/abc", "/reset-password", "/guidesx", "/editor/1",
    "/settings/account", "/certifications", "/templates", "/translation-memory", "/unsubscribe", "/accept-invite"]) {
    assert.ok(!isMarketingRoute(p) && !isSharedRoute(p), p)
  }
})

test("marketing host sends app routes to the app, query kept", () => {
  for (const host of ["www.onlinedoctranslator.ai", "onlinedoctranslator.ai", "phpstack-1-2.cloudwaysapps.com"]) {
    assert.deepEqual(decide(host, "/d/abc"), toApp("/d/abc"))
    assert.deepEqual(decide(host, "/reset-password", "?token=t.k-1"), toApp("/reset-password?token=t.k-1"))
    assert.deepEqual(decide(host, "/unsubscribe", "?token=u"), toApp("/unsubscribe?token=u"))
    assert.deepEqual(decide(host, "/accept-invite", "?token=i"), toApp("/accept-invite?token=i"))
    assert.deepEqual(decide(host, "/login"), toApp("/login"))
    assert.deepEqual(decide(host, "/register", "?plan=pro"), toApp("/register?plan=pro"))
    assert.deepEqual(decide(host, "/dashboard"), toApp("/dashboard"))
    assert.deepEqual(decide(host, "/editor/123"), toApp("/editor/123"))
    assert.deepEqual(decide(host, "/batches/9"), toApp("/batches/9"))
  }
})

test("marketing host keeps marketing and shared routes", () => {
  const host = "www.onlinedoctranslator.ai"
  for (const p of ["/", "/guides", "/guides/x", "/terms", "/dpa", "/sitemap.xml", "/robots.txt",
    "/_next/static/chunks/main.js", "/icon.svg", "/brand/og-image-1200x630.png", "/wp-json/wp/v2/pages"]) {
    assert.deepEqual(decide(host, p), stay, p)
  }
})

test("app host", () => {
  const host = "app.onlinedoctranslator.ai"
  assert.deepEqual(decide(host, "/"), { action: "redirect", location: `${APP}/login`, status: 307 })
  assert.deepEqual(decide(host, "/guides"), toWww("/guides"))
  assert.deepEqual(decide(host, "/guides/x", "?ref=1"), toWww("/guides/x?ref=1"))
  assert.deepEqual(decide(host, "/sitemap.xml"), toWww("/sitemap.xml"))
  assert.deepEqual(decide(host, "/robots.txt"), { action: "robots-disallow" })
  for (const p of ["/login", "/dashboard", "/d/abc", "/reset-password", "/terms", "/privacy", "/_next/static/a.js"]) {
    assert.deepEqual(decide(host, p), stayNoindex, p)
  }
})

test("no redirect, ever, on localhost or a preview", () => {
  for (const host of ["localhost:3000", "127.0.0.1:3100", "traqconverter-abc.vercel.app"]) {
    for (const p of ["/", "/d/abc", "/reset-password", "/unsubscribe", "/guides/x", "/_next/static/a.js", "/robots.txt", "/login"]) {
      assert.deepEqual(decide(host, p), stay, `${host}${p}`)
    }
  }
})

test("no loops: every redirect target is final", () => {
  const paths = ["/", "/login", "/d/abc", "/guides", "/guides/x", "/terms", "/sitemap.xml", "/robots.txt", "/dashboard"]
  for (const host of ["www.onlinedoctranslator.ai", "onlinedoctranslator.ai", "app.onlinedoctranslator.ai"]) {
    for (const p of paths) {
      let d = decide(host, p)
      let hops = 0
      while (d.action === "redirect") {
        const u = new URL(d.location)
        d = decide(u.host, u.pathname, u.search)
        hops += 1
        assert.ok(hops <= 2, `${host}${p} loops`)
      }
    }
  }
})
