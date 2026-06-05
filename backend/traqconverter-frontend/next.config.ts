import type { NextConfig } from "next"

// Audit polish: was an empty default. Turn on strict mode and emit a
// standalone server bundle so the Docker image only needs the .next
// output, not the full source tree.
const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",

  // Trim what the runtime ships at the network layer.
  poweredByHeader: false,
  compress: true,

  // Mirror the security headers the backend now sets, so static assets
  // served by Next have the same defaults. CSP is intentionally loose
  // here because the SPA loads from the same origin; tighten per
  // deployment if you serve a known frontend domain.
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

export default nextConfig
