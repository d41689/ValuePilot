# Review result — admin 13F page fixes

Date: 2026-05-20
Branch reviewed: `claude/admin-13f-page-fixes`
Prompt: `docs/tasks/2026-05-20_admin-13f-page-fixes-review-prompts.md`

## Verdict

暂不批准。

The four targeted fixes are mostly correct, but the security-header runtime check uncovered one blocker: the new Next.js headers cover Next-rendered page routes, but they do **not** cover `/api/*` rewrite responses. The review prompt explicitly calls out `/api/*` rewrite coverage, and the development summary frames this as affecting every production response.

## Blocking finding

### [P1] `/api/*` rewrite responses do not receive the security headers

`frontend/next.config.js` registers the five headers for `source: '/:path*'` and rewrites `/api/:path*` to `http://api:8000/api/:path*`.

Runtime verification with the production standalone server showed:

- `/`, `/login`, and `/admin/13f` all include:
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `X-Frame-Options: SAMEORIGIN`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `X-Powered-By` is absent on those Next routes.
- With the API service running behind the Next rewrite, `HEAD /api/v1/health` returned only the backend response headers observed in the probe, including `server: uvicorn`; the five security headers above were absent.

This means the implementation is correct for Next page responses, but not for rewritten API responses. Either add equivalent headers at the API/FastAPI layer or explicitly narrow the security-header contract to page responses only. Given the prompt's A3 requirement, this is currently a blocker.

## Prompt checklist

### A. Security headers

- **A1 runtime header check:** Page-route portion passes. Production standalone server emitted all five headers and suppressed `X-Powered-By` on `/`, `/login`, and `/admin/13f`. Full site-wide check fails because `/api/*` rewrite responses lack the headers.
- **A2 values:** Values are generally sane for app pages. `includeSubDomains` on `invest.richmom.vip` affects sub-subdomains under that host, not all of `richmom.vip`; deployers should confirm none of those need plain HTTP. `X-Frame-Options: SAMEORIGIN` is acceptable; static search found no app self-iframe dependency.
- **A3 matcher / rewrite coverage:** Fails for `/api/*` rewrite responses as described above.
- **A4 Cloudflare advisory:** Repo docs confirm production goes through Cloudflare/cloudflared. This review cannot verify Cloudflare header merging from the local branch; deploy-time check should confirm it does not strip, duplicate, or override these headers.

### B. Mutation error handling

- **B5 toast plumbing:** Pass. `notifyMutationError` reads the normal axios shape `error.response.data.detail`, falls back cleanly, and uses `appType: 'error'`, which is a valid toast type. All six admin mutations in the index page have `onError`.
- **B6 401 interaction:** Pass with a minor UX note. The axios interceptor redirects on 401 after refresh failure; mutation `onError` may also enqueue an error toast. That is not a functional break, and the redirect remains authoritative.

### C. Refresh invalidation

- **C7 exact key match:** Pass. `refreshAdminData` uses `['admin-13f-oracles-lens-unknown-manager-priority']`, matching `useUnknownManagerPriorityQuery` exactly.
- **C8 old refresh set preserved:** Pass. The current `refreshAdminData` key set is a superset of the old inline Refresh button's 14 keys and includes the missing unknown-manager-priority key.
- **C9 inactive keys:** Pass. Invalidating keys whose views are not mounted is harmless in React Query; it marks cached data stale and does not itself break absent observers.

### D. `formatInteger`

- **D10 NaN guard:** Pass. The guard now requires `typeof value === 'number' && Number.isFinite(value)`, so `NaN`, infinities, strings, `null`, and `undefined` render as `—`. Existing call sites that pass `Number(x ?? 0)` continue to render real zero as `0`.

### E. Scope / follow-up

- **E11 CSP:** Pass. CSP is explicitly deferred in `docs/BACKLOG.md`, and the task log states the review/fix scope. Deferring CSP is acceptable for this patch.

## Verification run

- `docker compose run --rm --no-deps web npm run lint` — passed.
- `docker compose run --rm --no-deps web sh -lc 'NODE_ENV=production npm run build'` — passed.
- `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'` — passed, 152 tests.
- Production standalone runtime probe — passed for Next page routes, failed for `/api/*` rewrite header coverage.

Backend tests were not rerun because this branch's reviewed code diff does not modify backend source. A temporary API container was started only to verify the `/api/*` rewrite behavior and then stopped.

## Recommended remediation

1. Decide whether security headers are intended to cover all browser-visible responses, including API responses through Next.
2. If yes, add equivalent headers at the FastAPI/backend layer or another layer that actually owns rewritten API responses.
3. Re-run the production standalone probe against both page routes and `/api/*`; approve only once both surfaces emit the expected headers or the documented contract is narrowed.
