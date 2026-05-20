# 2026-05-20 — /admin/13f page: review findings + fixes

## Goal / Acceptance Criteria

- Triage and fix the problems found on the `/admin/13f` admin page, in severity
  order.
- Acceptance: each finding below is fixed in this change or recorded in
  `docs/BACKLOG.md` with a reason; canonical CI green.

## How the page was reviewed

`/admin/13f` is admin-auth-gated and the deployment is a client-rendered Next.js
app, so it could not be driven in a browser from this environment. The review
was: (1) an HTTP-level probe of the live site (`invest.richmom.vip`), and (2) a
static code review of `frontend/app/(dashboard)/admin/13f/page.tsx`, its query
module, the Next config, and the React Query provider.

HTTP probe confirmed: the site is behind Cloudflare (HTTPS); `/admin/13f`
correctly `307`s to `/login` when unauthenticated; `/api/v1/*` is correctly
proxied to the API. Runtime / visual issues (rendering, real-data correctness)
were NOT checked — that needs a browser plus admin credentials.

## Findings (severity high → low)

1. **[Medium-High] No security response headers.** `next.config.js` sets no
   `Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options`,
   `Referrer-Policy`, or `Permissions-Policy`, and leaks `X-Powered-By: Next.js`.
   The admin panel — which has one-click destructive job triggers — has no
   clickjacking protection. → FIXED in `next.config.js`.
2. **[Medium] Admin mutations fail silently.** The 6 `useMutation` calls on the
   page have no `onError`, and `providers.tsx` creates `new QueryClient()` with
   no global error handler. A failed job trigger / manager action gives the
   operator zero feedback. → FIXED: a shared `onError` toast on all 6 mutations.
3. **[Low] Refresh-button invalidation list has drifted.** The header `Refresh`
   button inlines 14 `invalidateQueries` calls; `refreshAdminData` has 16; both
   omit the Oracle's Lens query key. → FIXED: the button now calls
   `refreshAdminData`, and the missing key is added to it (single source).
4. **[Low] `formatInteger` renders "NaN".** Call sites pass `Number(x ?? 0)`; a
   non-numeric value becomes `NaN`, which is `typeof 'number'`, so it prints
   "NaN" instead of "—". → FIXED: a `Number.isFinite` guard.

## Deferred

- **Content-Security-Policy** — a correct CSP for the Next.js runtime must be
  built and tested against the running app (inline scripts / nonces); shipping a
  wrong CSP breaks prod. Recorded in `docs/BACKLOG.md`.

## Files changed

- `frontend/next.config.js` — `headers()` + `poweredByHeader: false`.
- `frontend/app/(dashboard)/admin/13f/page.tsx` — mutation `onError`, Refresh
  button, `formatInteger`.
- `docs/BACKLOG.md` — CSP follow-up entry.

## Test plan

These are config + JSX-wiring changes; the repo's unit harness
(`node --test lib/*.test.js`) covers pure lib modules only, not pages or the
Next config. Verification:

- `docker compose run --rm --no-deps web npm run lint`
- `docker compose run --rm --no-deps web npm run build` (validates the config)
- `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'`
- Header emission to be confirmed with `curl -I` against the page once deployed.

## Notes

- 2026-05-20: review requested by the user. The page could not be browser-QA'd,
  so scope is the `/admin/13f` index page plus its infrastructure (Next config,
  React Query provider). The 7 sub-routes under `/admin/13f/*` were not reviewed.

## Review remediation (2026-05-20)

External review (`2026-05-20_admin-13f-page-fixes-review-result.md`) verdict was
**not approved yet** — one blocker:

**[P1] Security headers did not cover `/api/*` rewrite responses.** Next.js
`headers()` decorates Next-rendered routes, but the `/api/*` paths are rewritten
to the backend (uvicorn) and that proxied response bypasses Next's header layer.
The reviewer's runtime probe confirmed `/`, `/login`, and `/admin/13f` carried
all five headers while `/api/v1/health` carried none.

Fix: the API now sets the same five headers itself via an `add_security_headers`
middleware in `backend/app/main.py`, so coverage is uniform site-wide regardless
of how a response is routed. `backend/tests/unit/test_security_headers.py`
asserts the headers on both `/health` and an `/api/v1/*` response. The
`next.config.js` comment (which claimed "every route") was corrected.

Non-blocking review notes — B6 (a 401 may both redirect and toast), A2
(`includeSubDomains` scope), A4 (Cloudflare header merging is a deploy-time
check) — were accepted as-is; see the review result.

Additional files changed in remediation:
- `backend/app/main.py` — security-headers middleware.
- `backend/tests/unit/test_security_headers.py` — new test.
