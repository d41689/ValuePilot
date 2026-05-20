# Review prompt — /admin/13f page fixes (2026-05-20, PR #67)

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the task log
`docs/tasks/2026-05-20_admin-13f-page-fixes.md`.

---

## Reviewer brief

You are reviewing **PR #67**, four fixes to the `/admin/13f` admin page that came
out of a review. The originating review could not drive a browser (the page is
admin-auth-gated, client-rendered) — it was an HTTP probe of the live site plus a
static code read. So **do not assume the page is bug-free**; your job is to
confirm these four fixes are correct, complete, and safe — nothing more.

The **highest-risk** piece is the security-header change: it changes **every
response site-wide on production**, and the PR itself admits header emission was
*not* runtime-verified (only `next build` validated the config). Treat A1 below
as mandatory.

### Files in scope

- `frontend/next.config.js` — `securityHeaders` + `headers()` + `poweredByHeader: false`
- `frontend/app/(dashboard)/admin/13f/page.tsx` — `formatInteger`, `refreshAdminData`,
  the header `Refresh` button, `notifyMutationError` + `onError` on 6 mutations
- `docs/BACKLOG.md` — deferred CSP entry
- `docs/tasks/2026-05-20_admin-13f-page-fixes.md` — task log

### Baseline

`git show main:frontend/next.config.js` and `git show main:frontend/app/(dashboard)/admin/13f/page.tsx`
for the pre-change versions. The fix is NOT deployed — curling
`https://invest.richmom.vip` still shows the *old* (header-less) state; verify
the fix by running the built code locally, not against prod.

## Answer every question with a verdict + evidence

### A. Security headers (`next.config.js`) — highest risk

1. **Headers are actually emitted (MANDATORY — do not skip).** `output:
   'standalone'` is set; confirm `headers()` is honored by the production
   server. Build and run the web service, then `curl -I` a route and confirm all
   five headers (`Strict-Transport-Security`, `X-Frame-Options`,
   `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`) are present
   and `X-Powered-By` is **absent**. Both `next start` and the standalone
   `node .next/standalone/server.js` (what `docker-compose.prod.yml` runs) honor
   `headers()` — use whichever is convenient; publish a host port and curl it.
   If the headers do not appear, the entire fix #1 is a silent no-op.
2. **Header values are sane.** `Strict-Transport-Security:
   max-age=31536000; includeSubDomains` — is `includeSubDomains` safe given the
   host is the subdomain `invest.richmom.vip` (i.e. are there HTTP-only
   sub-subdomains it would break)? `X-Frame-Options: SAMEORIGIN` — does the app
   embed itself in an iframe anywhere (which SAMEORIGIN allows and DENY would
   not)? Flag anything risky.
3. **The matcher.** `source: '/:path*'` — confirm it matches `/` as well as all
   nested routes, and note that it also applies to the `/api/*` rewrite
   responses; confirm that is harmless.
4. **Cloudflare interaction (advisory).** Prod sits behind Cloudflare. Note
   whether these origin headers will reach the browser unchanged, and whether
   HSTS should instead/also be managed at the CDN — this cannot be fully
   verified from the repo, so flag it as a deploy-time check, not a blocker.

### B. Mutation error handling (`page.tsx`)

5. **`notifyMutationError`.** It reads `error.response.data.detail` — confirm
   that is the correct axios error shape, and that `appType: 'error'` is a valid
   toast type. Confirm all **six** mutations (`triggerJob`, `releaseStaleLock`,
   `confirmManager`, `rejectManager`, `revokeManager`, `retryCikSearch`) received
   an `onError` and none was missed.
6. **401 interaction.** The `apiClient` response interceptor (PR #64) already
   redirects to `/login` on a 401. A mutation that 401s will now *also* fire
   `onError` → a toast. Confirm this is harmless (no broken UX, no double-handling
   that matters) or flag it.

### C. Refresh button / `refreshAdminData`

7. **Exact key match.** `refreshAdminData` gained the key
   `'admin-13f-oracles-lens-unknown-manager-priority'`. Verify it matches the
   `queryKey` in `frontend/lib/admin13f/queries.ts` **character-for-character** —
   a typo here is a silent no-op (the card never refreshes).
8. **Nothing lost.** The header `Refresh` button previously inlined a 14-key
   `invalidateQueries` list and now just calls `refreshAdminData`. Confirm
   `refreshAdminData`'s key set is a **superset** of that old 14-key list, so no
   query that used to refresh has stopped refreshing.
9. Confirm that invalidating keys for queries not mounted on the index page is
   harmless (no spurious refetch / error).

### D. `formatInteger`

10. The `Number.isFinite` guard is correct and no caller depended on the old
    `"NaN"` output.

### E. Scope & deferral

11. CSP deferral is recorded in `docs/BACKLOG.md` and the deferral reason is
    sound. The change's scope (the `/admin/13f` index page + its config/provider,
    not the 7 sub-routes) is acknowledged in the task log — confirm it is stated,
    not silently narrowed.

## Verification

- `docker compose run --rm --no-deps web npm run lint`
- `docker compose run --rm --no-deps web sh -lc 'NODE_ENV=production npm run build'`
- `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'`
- Plus the runtime header check in A1.
- (Backend is untouched by this PR.)

## Pass bar

Approve only if: **A1 is confirmed by actually running the built app** (headers
present, `X-Powered-By` gone); A2–A3 are sane; B5–B6 hold; C7 (exact key match)
and C8 (superset) are verified; D10 holds; E11 confirmed. A4 is advisory. The
bar is "these four fixes are correct and safe" — not "the page is bug-free".
