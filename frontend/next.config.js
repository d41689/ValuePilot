/** @type {import('next').NextConfig} */

const { buildContentSecurityPolicy } = require('./lib/csp')

// Security response headers for Next-rendered routes. The `/api/*` paths are
// rewritten to the backend (see rewrites() below), which sets the same headers
// itself (backend/app/main.py) so coverage is uniform site-wide.
//
// Content-Security-Policy is the one exception to that mirroring: it governs
// document/script execution and is inert on a JSON API response, so it is set
// here (on Next-rendered routes) only — the backend is intentionally not given
// a CSP. The policy is static (no per-request nonce); see lib/csp.js and
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
