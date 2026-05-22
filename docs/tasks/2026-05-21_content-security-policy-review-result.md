# Review result — Content-Security-Policy response header

Date: 2026-05-21
Branch reviewed: `claude/content-security-policy`
Baseline: `git diff main...HEAD`
Prompt: `docs/tasks/2026-05-21_content-security-policy-review-prompts.md`

## Overall verdict

PASS with one advisory. The production CSP materially improves the frontend
security posture without taking on the nonce/dynamic-rendering risk. The one
accepted weakness, `script-src 'unsafe-inline'`, is documented as a deliberate
static-policy trade-off and moved to a low-priority backlog upgrade path.

Advisory: `next.config.js` applies `securityHeaders` to `source: '/:path*'`.
Depending on Next's header/rewrite ordering, rewritten `/api/*` responses may
also receive the CSP despite the comment saying CSP is for Next-rendered routes
only. That is not a breakage/security blocker because CSP is inert on JSON API
responses, but the comment/source could be tightened if strict route scoping is
important.

Evidence: `frontend/next.config.js:5-13`, `frontend/next.config.js:29-35`.

## Prompt checklist

### A. Policy correctness

1. PASS. The policy includes the expected hardening directives:
   `default-src 'self'`, `object-src 'none'`, `base-uri 'self'`,
   `form-action 'self'`, `frame-ancestors 'self'`, same-origin `connect-src`,
   constrained `img-src`, `font-src`, and `style-src`. `frame-ancestors 'self'`
   is consistent with the existing `X-Frame-Options: SAMEORIGIN`. Evidence:
   `frontend/lib/csp.js:30-43`, `frontend/next.config.js:16-22`,
   `frontend/lib/csp.test.js:25-35`.
2. PASS, accepted residual. `script-src 'unsafe-inline'` is deliberate for the
   static no-nonce approach and is recorded as a low backlog item with nonce/SRI
   upgrade paths. Code audit found no `dangerouslySetInnerHTML`, no
   `next/script`, and no inline/third-party `<script>` in the app/component
   surfaces searched. Evidence: `frontend/lib/csp.js:4-8`,
   `docs/tasks/2026-05-21_content-security-policy.md:12-31`,
   `docs/BACKLOG.md:117-130`.
3. PASS. The environment-gated tokens are on the right side:
   `'unsafe-eval'` is dev-only, `ws:` is dev-only, and
   `upgrade-insecure-requests` is prod-only. Evidence:
   `frontend/lib/csp.js:19-28`, `frontend/lib/csp.js:46-47`,
   `frontend/lib/csp.test.js:37-59`.
4. PASS. The default frontend API base is same-origin `/api/v1`, and
   `next.config.js` rewrites `/api/:path*` to the backend container, so
   `connect-src 'self'` is correct for the intended deployment. A cross-origin
   absolute `NEXT_PUBLIC_API_URL` would require widening `connect-src`; this is
   documented in the task doc and code comments. Evidence:
   `frontend/lib/api/client.ts:5`, `frontend/next.config.js:37-43`,
   `frontend/lib/csp.js:25-28`,
   `docs/tasks/2026-05-21_content-security-policy.md:64-66`.
5. PASS. I found no app usage of `<embed>`, `<object>`, `<iframe>`,
   `next/image`, remote images, web/service workers, media elements, or blob URL
   document loading in the audited app/component/lib surfaces. The document page
   uses a `Blob` for File System Access/download-style writing, which does not
   require loading a blob document/resource. Evidence:
   `frontend/app/(dashboard)/documents/page.tsx:200`,
   `docs/tasks/2026-05-21_content-security-policy.md:68-71`.

### B. Wiring / mechanism

6. PASS with advisory. `headers()` emits the CSP through the shared
   `securityHeaders` on `source: '/:path*'`, so it reaches Next-rendered routes.
   The documented decision not to add CSP to backend API middleware is correct:
   a CSP on JSON is inert, and backend security headers remain otherwise
   untouched. Advisory noted above: because the source is all paths, `/api/*`
   may also receive the header when routed through Next, but that is harmless.
   Evidence: `frontend/next.config.js:29-35`, `backend/app/main.py:100-118`,
   `docs/tasks/2026-05-21_content-security-policy.md:74-77`.
7. PASS. `isDev` comes from `process.env.NODE_ENV === 'development'`, which is
   the expected Next distinction for `next dev` versus production build/start,
   so the production policy does not include dev allowances. Evidence:
   `frontend/next.config.js:14`,
   `frontend/lib/csp.test.js:37-59`.
8. PASS. `frontend/lib/csp.js` is CommonJS and is required by both
   `next.config.js` and `frontend/lib/csp.test.js` using the correct relative
   paths. This matches the repo's existing CommonJS test helper pattern.
   Evidence: `frontend/lib/csp.js:10-12`, `frontend/lib/csp.js:52`,
   `frontend/next.config.js:3`, `frontend/lib/csp.test.js:1-5`.

### C. Tests

9. PASS. `frontend/lib/csp.test.js` is under `frontend/lib/`, so it is picked up
   by the canonical `node --test lib/*.test.js` glob when run from the frontend
   container. It covers production hardening directives, production absence of
   `'unsafe-eval'`, production `connect-src 'self'`, production
   `upgrade-insecure-requests`, and dev-only `unsafe-eval`/`ws:` with no
   upgrade directive. Dropping a hardening directive or leaking dev tokens into
   prod would fail these tests. Evidence: `frontend/lib/csp.test.js:19-63`;
   canonical glob in `AGENTS.md` / prompt.

### D. Scope / deferred

10. PASS. The resolved medium backlog item is replaced with a low-priority
    `script-src 'unsafe-inline'` residual that names nonce and SRI upgrade
    paths. The task doc records the static-vs-nonce decision, the Next.js
    dynamic-rendering rationale, and the user-confirmed trade-off. Evidence:
    `docs/BACKLOG.md:117-130`,
    `docs/tasks/2026-05-21_content-security-policy.md:12-31`,
    `docs/tasks/2026-05-21_content-security-policy.md:100-109`.

## Verification performed

- Read the review prompt and task log.
- Inspected `git diff main...HEAD` scope.
- Reviewed CSP builder, CSP tests, Next config wiring, backend security headers,
  task/backlog updates, and frontend API base.
- Grepped frontend app/components/features/lib for inline script sinks, embeds,
  iframes, workers, `next/image`, and blob/document-loading patterns.

I did not run the Docker canonical CI commands or browser/curl runtime checks in
this review pass.
