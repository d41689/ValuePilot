/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://api:8000/:path*', // Proxy to backend service in Docker
      },
    ]
  },
}

module.exports = nextConfig
