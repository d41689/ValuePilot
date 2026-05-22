/**
 * Content-Security-Policy for ValuePilot's Next.js frontend.
 *
 * This is a deliberately *static* policy (set in next.config.js, no per-request
 * nonce). `script-src` therefore keeps `'unsafe-inline'` — Next.js injects
 * inline bootstrap scripts and a strict nonce-based script-src would force every
 * page into dynamic rendering. See docs/tasks/2026-05-21_content-security-policy.md
 * for the trade-off; the strict-script-src upgrade is a docs/BACKLOG.md item.
 *
 * CommonJS so it can be `require`d from both next.config.js (build/start time)
 * and the node:test suite — same pattern as lib/authRoutes.js.
 */

/**
 * Build the CSP header value.
 * @param {{ isDev?: boolean }} [options] - `isDev` true for `next dev`.
 * @returns {string} the `Content-Security-Policy` header value.
 */
function buildContentSecurityPolicy({ isDev = false } = {}) {
  // Inline bootstrap scripts need 'unsafe-inline'; React Refresh / HMR uses
  // eval, but only in dev — production never evaluates strings as code.
  const scriptSrc = ["'self'", "'unsafe-inline'"];
  if (isDev) scriptSrc.push("'unsafe-eval'");

  // The API is same-origin (/api/v1, rewritten to the backend). Dev adds the
  // Next.js HMR websocket.
  const connectSrc = ["'self'"];
  if (isDev) connectSrc.push('ws:');

  const directives = [
    "default-src 'self'",
    `script-src ${scriptSrc.join(' ')}`,
    // Inline style attributes (React style props, Next.js, next/font) — CSS
    // injection is far lower-risk than script injection.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src ${connectSrc.join(' ')}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    // Kept consistent with the existing X-Frame-Options: SAMEORIGIN.
    "frame-ancestors 'self'",
  ];

  // Would break the plaintext-HTTP local dev server, so production only.
  if (!isDev) directives.push('upgrade-insecure-requests');

  return directives.join('; ');
}

module.exports = { buildContentSecurityPolicy };
