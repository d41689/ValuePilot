# Review prompt — Content-Security-Policy response header

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the task log
`docs/tasks/2026-05-21_content-security-policy.md` and the diff on branch.

---

## Reviewer brief

You are reviewing a **security-header change** to ValuePilot's Next.js frontend.
It adds a `Content-Security-Policy` response header, resolving the
`docs/BACKLOG.md` item *"Content-Security-Policy response header"* (medium,
opened 2026-05-20). The backlog warned a wrong CSP **breaks the site**, so weigh
both the security value and the breakage risk.

### What changed and why

- Before: `next.config.js` set HSTS, X-Frame-Options, nosniff, Referrer-Policy,
  Permissions-Policy — but no CSP.
- After: a **static** CSP (no per-request nonce) is added, built by
  `frontend/lib/csp.js` and emitted via `next.config.js` `headers()`.
- The static approach was chosen over a nonce-based one **deliberately**: the
  Next.js CSP guide is explicit that nonces force *every* page into dynamic
  rendering ("pages will build successfully but may encounter runtime errors").
  The trade-off accepted: `script-src` keeps `'unsafe-inline'`; every other
  directive is locked down. The user confirmed this approach.

The emitted policy (production):

```
default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'
'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src
'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors
'self'; upgrade-insecure-requests
```

Development differs only by: `+ 'unsafe-eval'` (script-src), `+ ws:`
(connect-src), `- upgrade-insecure-requests`.

### Files in scope

- `frontend/lib/csp.js` — new: `buildContentSecurityPolicy({ isDev })`.
- `frontend/lib/csp.test.js` — new: directive + dev/prod-variant tests.
- `frontend/next.config.js` — CSP added to `securityHeaders`; comment refreshed.
- `docs/BACKLOG.md`, `docs/tasks/2026-05-21_content-security-policy.md`.

### Baseline

`git diff main...HEAD`.

## Answer every question below with a verdict (PASS / FAIL / advisory) + file:line evidence

### A. Policy correctness — MANDATORY

1. **Hardening directives.** Confirm the policy includes and correctly sets
   `default-src 'self'`, `object-src 'none'`, `base-uri 'self'`,
   `form-action 'self'`, `frame-ancestors 'self'`, and source-restricted
   `connect-src` / `img-src` / `font-src` / `style-src`. Confirm
   `frame-ancestors 'self'` is consistent with the existing
   `X-Frame-Options: SAMEORIGIN` (not a silent retighten/loosen).
2. **`script-src 'unsafe-inline'` is the accepted weakness.** Confirm this is
   the deliberate cost of the static (no-nonce) approach, that it is recorded as
   a **low** `docs/BACKLOG.md` follow-up with the nonce/SRI upgrade paths, and
   that the residual inline-script-XSS surface is genuinely small — grep
   confirms no `dangerouslySetInnerHTML` and no third-party/inline `<script>` in
   `app/` or `components/`.
3. **dev/prod conditionals.** Three tokens are environment-gated. Confirm each
   gate: `'unsafe-eval'` dev-only (React Refresh uses `eval`; prod must not get
   it), `ws:` dev-only (the HMR websocket), `upgrade-insecure-requests`
   prod-only (it would break the plaintext-HTTP `localhost` dev server). A token
   on the wrong side is a FAIL.
4. **`connect-src 'self'`.** Confirm the API is same-origin — `/api/v1` is
   rewritten to the backend in `next.config.js` — so `'self'` is correct, and
   that a deployment pointing `NEXT_PUBLIC_API_URL` at a cross-origin absolute
   URL would need to widen this (is that documented?).
5. **No-breakage audit.** `object-src 'none'` and no `frame-src` / `media-src` /
   `worker-src` overrides (they fall back to `default-src 'self'`). Confirm this
   is safe for the actual app: no `<embed>`/`<object>`/`<iframe>`, no
   `next/image` or remote images, no web/service workers, and PDFs are
   download-only (File System Access API — no `blob:` URL is ever loaded as a
   document/resource).

### B. Wiring / mechanism

6. **Where the CSP applies.** `headers()` emits it on `source: '/:path*'`.
   Confirm it reaches Next-rendered routes, and assess the **deliberate**
   decision *not* to set CSP on `/api/*`: those paths are rewritten to the
   backend, a CSP is inert on a JSON response, and the backend security-headers
   middleware was intentionally left untouched. Is omitting it correct?
7. **`NODE_ENV` resolution.** `next.config.js` computes `isDev` from
   `process.env.NODE_ENV`. Confirm it resolves to `development` under
   `next dev` and `production` under `next build` / `next start`, so the right
   variant ships to prod.
8. **CJS module.** `lib/csp.js` is CommonJS, `require`d by both `next.config.js`
   and the test — the same pattern as `lib/authRoutes.js`. Confirm there is no
   ESM/CJS mismatch and the `require('./lib/csp')` path is correct.

### C. Tests

9. `lib/csp.test.js` is discovered by the canonical `lib/*.test.js` glob.
   Confirm it covers both the dev and prod variants and would actually **fail**
   if a hardening directive were dropped or a dev-only token (`'unsafe-eval'` /
   `ws:`) leaked into the production policy.

### D. Scope / deferred

10. Confirm the resolved backlog entry is removed, the `'unsafe-inline'`
    residual is recorded (low) with concrete upgrade paths, and the task doc
    records the static-vs-nonce decision and its rationale.

## Verification performed by the author

- Emitted CSP inspected under both `NODE_ENV` values.
- `curl -I` against the running dev server — header present on `/login` and `/`.
- Browser (Claude-in-Chrome) loaded `/login`: renders fully styled, **zero CSP
  violations / zero console errors**, all 10 network requests same-origin.
  Coverage boundary: only `/login` was browser-driven (no admin credentials in
  the environment); it exercises the shared infrastructure — Next.js framework
  scripts, hydration, `next/font`, the CSS pipeline. Authenticated dashboard
  pages were assessed by code audit (same framework, same `'self'` posture,
  same-origin API).
- All six canonical CI commands green; production build still emits
  `○ (Static)` pages (the static policy did not force dynamic rendering).

Reviewer: re-run if desired —

- `docker compose up -d --build`
- `docker compose exec -T web npm run lint`
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
- Header check: `curl -I http://localhost:3001/login | grep -i content-security`

## Pass bar

Approve only if: **A1–A5** carry no breakage risk and no unaccepted security
gap (A2's `'unsafe-inline'` residual may be accepted in writing — it is the
chosen trade-off); **B6–B8** are correct; **C9** passes; **D10** is recorded.
The bar is: "a meaningful CSP now ships, it provably does not break the running
app, and the one accepted weakness (`script-src 'unsafe-inline'`) is documented
with an upgrade path — safe to auto-deploy to prod."
