import type { NextConfig } from "next"
import { PHASE_PRODUCTION_BUILD } from "next/constants"

function origin(url: string | undefined): string | null {
  try {
    return url ? new URL(url).origin : null
  } catch {
    return null
  }
}

function contentSecurityPolicy(): string {
  const isDev = process.env.NODE_ENV === "development"
  const api = origin(process.env.NEXT_PUBLIC_API_URL) ?? (isDev ? "http://127.0.0.1:8000" : null)
  const apiSocket = api ? api.replace(/^http/, "ws") : null
  // Signed links to the stored files (PDF preview iframe, media thumbnails) point at Supabase Storage.
  const storage = ["https://*.supabase.co", origin(process.env.NEXT_PUBLIC_STORAGE_ORIGIN)]
  const stripe = ["https://js.stripe.com", "https://checkout.stripe.com"]
  const list = (...items: (string | null | undefined)[]) => items.filter(Boolean).join(" ")
  return [
    "default-src 'self'",
    // Next's bootstrap scripts are inline; the dev server also needs eval.
    `script-src ${list("'self'", "'unsafe-inline'", isDev ? "'unsafe-eval'" : null, stripe[0])}`,
    // React style props and docx-preview's injected <style> blocks.
    "style-src 'self' 'unsafe-inline'",
    `img-src ${list("'self'", "data:", "blob:", api, ...storage)}`,
    "font-src 'self' data: blob:",
    `connect-src ${list("'self'", "blob:", "data:", api, apiSocket, ...storage, isDev ? "ws:" : null)}`,
    `frame-src ${list("'self'", "blob:", ...storage, ...stripe)}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    `form-action ${list("'self'", stripe[1])}`,
    "frame-ancestors 'none'",
    // Only when the API itself is on https, so a local http build still reaches it.
    api?.startsWith("https:") ? "upgrade-insecure-requests" : null,
  ]
    .filter(Boolean)
    .join("; ")
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Used by the Dockerfile; Vercel ignores it.
  output: "standalone",

  poweredByHeader: false,
  compress: true,

  async redirects() {
    return [
      { source: "/batches", destination: "/jobs", permanent: false },
      { source: "/batches/:id", destination: "/jobs?batch=:id", permanent: false },
    ]
  },

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: "geolocation=(), microphone=(), camera=()",
          },
          { key: "Content-Security-Policy", value: contentSecurityPolicy() },
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
    ]
  },
}

export default function config(phase: string): NextConfig {
  // NEXT_PUBLIC_* is inlined at build time; a missing value would ship a bundle with no API.
  if (phase === PHASE_PRODUCTION_BUILD && !process.env.NEXT_PUBLIC_API_URL) {
    throw new Error("NEXT_PUBLIC_API_URL must be set for production builds.")
  }
  return nextConfig
}
