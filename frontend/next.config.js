/** @type {import('next').NextConfig} */

const { buildContentSecurityPolicy } = require('./lib/csp')

// Security response headers. `headers()` matches `source: '/:path*'` below,
// which as a pattern also covers `/api/*` — but a rewritten `/api/*` response
// is proxied straight from the backend and bypasses Next's header layer, so it
// does not actually carry these. The admin-13f remediation confirmed this by
// runtime probe (`/api/v1/health` carried none of them). In practice these
// headers land on Next-rendered routes only; the backend sets the same five
// itself (backend/app/main.py) to keep non-CSP coverage uniform site-wide.
//
// Content-Security-Policy is deliberately NOT mirrored onto the backend: it
// governs document/script execution and is inert on a JSON API response. The
// policy is static (no per-request nonce); see lib/csp.js and
// docs/tasks/2026-05-21_content-security-policy.md for the rationale.
const isDev = process.env.NODE_ENV === 'development'

const securityHeaders = [
  { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
  { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
  { key: 'Content-Security-Policy', value: buildContentSecurityPolicy({ isDev }) },
]

const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  // Keep the long-running dev server's chunks isolated from the canonical
  // production build, which runs in the same bind-mounted container.
  distDir: isDev ? '.next-dev' : '.next',
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: '/:path*',
        headers: securityHeaders,
      },
    ]
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://api:8000/api/:path*', // Preserve /api prefix for backend routes
      },
    ]
  },
}

module.exports = nextConfig
