# 2026-05-21 — Content-Security-Policy response header

Resolves the `docs/BACKLOG.md` item **"Content-Security-Policy response
header"** (found 2026-05-20, admin/13f security-header review, severity medium).
Prior context: `docs/tasks/2026-05-20_admin-13f-page-fixes.md` (Deferred).

## Goal

`next.config.js` already sets HSTS, X-Frame-Options, nosniff, Referrer-Policy
and Permissions-Policy but no `Content-Security-Policy`. Add a CSP that hardens
the frontend without breaking it.

## Decision — pragmatic static policy

Two viable approaches were weighed (Next.js CSP guide):

- **Nonce-based** (`middleware`): a genuinely strict `script-src`, but Next.js
  docs are explicit — *"all pages must be dynamically rendered"*, static
  optimization and CDN caching are disabled, and *"pages will build
  successfully but may encounter runtime errors if not properly configured."*
  This app has 23 statically-prerendered client-component pages → an app-wide
  rendering change with real breakage risk.
- **Static policy** (`next.config.js`): keeps `'unsafe-inline'` in `script-src`
  but locks every other directive down. One file, no rendering change, near-zero
  breakage risk.

**Chosen: the static policy.** The user picked it after the trade-off was laid
out. It is the right call for an internal, auth-gated v0.1 tool: the realistic
inline-script-XSS surface is small (no `dangerouslySetInnerHTML`, no
third-party/inline `<script>`, React auto-escapes), while the directives that do
not need a nonce — `frame-ancestors`, `base-uri`, `form-action`, `object-src`,
and source-locking `default/connect/img/font/style` — deliver most of the value.
The residual (a non-strict `script-src`) is recorded as a low backlog item.

## The policy

Built by `frontend/lib/csp.js`; `next.config.js` adds it to `securityHeaders`.

```
default-src 'self';
script-src 'self' 'unsafe-inline' [dev: 'unsafe-eval'];
style-src 'self' 'unsafe-inline';
img-src 'self' data: blob:;
font-src 'self';
connect-src 'self' [dev: ws:];
object-src 'none';
base-uri 'self';
form-action 'self';
frame-ancestors 'self';
[prod: upgrade-insecure-requests]
```

Why each non-obvious choice:
- `script-src`/`style-src 'unsafe-inline'` — Next.js injects inline bootstrap
  scripts and inline styles; without a nonce these need `'unsafe-inline'`.
- `'unsafe-eval'` **dev only** — React Refresh / HMR uses `eval`; production
  does not.
- `ws:` **dev only** — the Next.js dev HMR websocket.
- `upgrade-insecure-requests` **prod only** — would break the plaintext-HTTP
  local dev server (`http://localhost`).
- `frame-ancestors 'self'` — kept consistent with the existing
  `X-Frame-Options: SAMEORIGIN` rather than silently retightening to `'none'`.
- `connect-src 'self'` — the API is same-origin (`/api/v1`, rewritten to the
  backend). A deployment that points `NEXT_PUBLIC_API_URL` at an absolute
  cross-origin URL would need to widen this.

Verified safe for this codebase: no `next/image` / remote images, no web or
service workers, no `<embed>`/`<object>`/`<iframe>`, PDFs are download-only via
the File System Access API (no blob URL is ever loaded as a resource).

## Scope

**In:** `frontend/lib/csp.js` + test; `next.config.js` CSP header.
**Out:**
- CSP on `/api/*` responses — CSP governs document/script execution and is inert
  on a JSON API response; the backend security-headers middleware is untouched.
- A strict (nonce / SRI) `script-src` — deferred to `docs/BACKLOG.md` (low).
- `report-uri` / `report-to` — no collector endpoint exists.

## Files to change

- `frontend/lib/csp.js` — new: `buildContentSecurityPolicy({ isDev })`.
- `frontend/lib/csp.test.js` — new: directive coverage, dev/prod variants.
- `frontend/next.config.js` — add the CSP header; refresh the comment.
- `docs/BACKLOG.md` — remove the resolved entry; add the strict-script-src item.

## Test plan (Docker)

```
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

Plus runtime verification (the backlog item demanded "tested against the
running app"):
- Evaluate `next.config.js` `headers()` under both `NODE_ENV` values and inspect
  the emitted CSP string.
- `curl -I` the running dev server — confirm the header is present and well-formed.
- Load the app in a browser — confirm no CSP violation breaks rendering.

## Sign-off trail

- 2026-05-21 — task opened; approach = static policy (user-confirmed).
- 2026-05-21 — implemented. Verified: emitted CSP inspected in both `NODE_ENV`
  modes; `curl -I` confirmed the header live on `/login` and `/`; browser
  (Claude-in-Chrome) loaded `/login` — page renders fully styled, **zero CSP
  violations / zero console errors**, all 10 network requests same-origin
  (`/_next/static/...`, self-hosted fonts). All six canonical CI commands green
  — `pytest` 902, `node --test` 159, lint clean, production build OK and **still
  emitting `○ (Static)` pages** (the static policy did not force dynamic
  rendering, confirming the chosen-approach trade-off held).
- 2026-05-21 — two independent reviews returned PASS / APPROVE, no blockers
  (`..._review-result.md`, `..._review-results.md`). One advisory: the
  `next.config.js` comment said "Next-rendered routes only" while the `/:path*`
  matcher pattern also covers `/api/*`. Resolved as comment accuracy — `headers()`
  does not in fact decorate the `/api/*` rewrite-to-backend responses (proven by
  the admin-13f runtime probe), so the comment now states that mechanism
  precisely. No behavior change. The A4 advisory (cross-origin
  `NEXT_PUBLIC_API_URL` would need `connect-src` widened) was already documented
  and needs no action for the current same-origin deployment.
