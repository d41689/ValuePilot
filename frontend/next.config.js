/** @type {import('next').NextConfig} */

// Security response headers applied to every route. Content-Security-Policy is
// intentionally omitted here — a correct policy for the Next.js runtime must be
// built and tested against the running app; tracked in docs/BACKLOG.md.
const securityHeaders = [
  { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
  { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
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
