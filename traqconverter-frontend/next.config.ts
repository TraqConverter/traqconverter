import type { NextConfig } from "next"
import { PHASE_PRODUCTION_BUILD } from "next/constants"

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
