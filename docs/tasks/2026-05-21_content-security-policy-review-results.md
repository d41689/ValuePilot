# Review results — Content-Security-Policy response header

**Branch:** `claude/refresh-token-revocation` (CSP change ships in same PR)  
**Reviewer:** Claude Sonnet 4.6 (agent review)  
**Date:** 2026-05-21  
**Prompt:** `docs/tasks/2026-05-21_content-security-policy-review-prompts.md`

---

## Overall verdict: **APPROVE**

All mandatory gates (A1–A5, B6–B8, C9, D10) pass. The one accepted weakness
(`script-src 'unsafe-inline'`) is accepted in writing below. No breakage risk.
The bar — "a meaningful CSP now ships, provably does not break the running app,
`'unsafe-inline'` documented with an upgrade path, safe to auto-deploy" — is
met.

---

## A. Policy correctness

### A1. Hardening directives — **PASS**

Evidence: `frontend/lib/csp.js:30–44`; `frontend/next.config.js:17–22`

All required directives confirmed present and correctly set in the production
policy:

| Directive | Value | Location |
|---|---|---|
| `default-src` | `'self'` | `csp.js:31` |
| `object-src` | `'none'` | `csp.js:39` |
| `base-uri` | `'self'` | `csp.js:40` |
| `form-action` | `'self'` | `csp.js:41` |
| `frame-ancestors` | `'self'` | `csp.js:43` |
| `connect-src` | `'self'` | `csp.js:38` |
| `img-src` | `'self' data: blob:` | `csp.js:36` |
| `font-src` | `'self'` | `csp.js:37` |
| `style-src` | `'self' 'unsafe-inline'` | `csp.js:35` |

**`frame-ancestors` consistency:** `frame-ancestors 'self'` is semantically
equivalent to `X-Frame-Options: SAMEORIGIN` — both allow same-origin framing
only. The inline comment at `csp.js:42` confirms this was deliberately chosen
for consistency, not to retighten or loosen. ✓

### A2. `script-src 'unsafe-inline'` is the accepted weakness — **PASS** (residual accepted)

Evidence: `csp.js:22–23`; `BACKLOG.md:117–130`; task doc lines 15–33

`'unsafe-inline'` is deliberate: Next.js injects inline bootstrap scripts that
cannot be served with a nonce under a static policy without forcing every page
into dynamic rendering. The trade-off is documented in the task doc, the module
header comment (`csp.js:1–12`), and the BACKLOG entry.

**Inline-script XSS surface audit (grep results):**

- `dangerouslySetInnerHTML`: **zero hits** across `frontend/app/` and
  `frontend/components/`. ✓
- Literal `<script` tags: **zero hits** across `frontend/app/` and
  `frontend/components/`. ✓

React auto-escapes all JSX output. No `eval`-equivalent is used outside the
dev-only `'unsafe-eval'` allowance. The realistic inline-script XSS surface is
genuinely small.

**BACKLOG low entry** (`BACKLOG.md:117–130`) is present with two concrete
upgrade paths:
1. Per-request nonce via `middleware` (acknowledges the dynamic-rendering
   trade-off).
2. `experimental.sri` hash-based CSP once stable.

**Residual accepted:** `script-src 'unsafe-inline'` does not block a
specifically crafted inline `<script>` injection. The app mitigates this via
React's auto-escaping, the auth-gated v0.1 audience, and the absence of any
`dangerouslySetInnerHTML` usage. This is the correct stance at this maturity
level.

### A3. dev/prod conditionals — **PASS**

Evidence: `csp.js:23`, `csp.js:28`, `csp.js:47`

All three environment-gated tokens are on the correct side:

| Token | Gate | Reason | Line |
|---|---|---|---|
| `'unsafe-eval'` | `if (isDev)` — dev only | React Refresh uses `eval`; production must not get it | `csp.js:23` |
| `ws:` | `if (isDev)` — dev only | Next.js HMR websocket | `csp.js:28` |
| `upgrade-insecure-requests` | `if (!isDev)` — prod only | Would break plaintext-HTTP `localhost` dev server | `csp.js:47` |

No token is on the wrong side. The test suite enforces this (see C9).

### A4. `connect-src 'self'` — **PASS** with advisory

Evidence: `next.config.js:39–43`; `frontend/lib/api/client.ts:5`

The API rewrite (`source: '/api/:path*'` → `destination: 'http://api:8000/api/:path*'`) is same-origin from the browser's perspective. `connect-src 'self'` is correct for this deployment configuration. ✓

**Advisory (documented, no action needed now):** `client.ts:5` defines
`API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api/v1'`. If
`NEXT_PUBLIC_API_URL` is set to an absolute cross-origin URL in a future
deployment, `connect-src 'self'` would block API calls, silently breaking the
app. The task doc (lines 63–65) calls this out explicitly: *"A deployment that
points `NEXT_PUBLIC_API_URL` at an absolute cross-origin URL would need to widen
this."* Documented. No BACKLOG entry required for the current deployment; should
be noted in any deployment runbook if the architecture changes.

### A5. No-breakage audit — **PASS**

Evidence: `frontend/app/`, `frontend/components/` grep results; task doc lines 67–69

| Feature | Check | Result |
|---|---|---|
| `<embed>` / `<object>` | grep app/ + components/ | **zero hits** — `object-src 'none'` is safe ✓ |
| `<iframe>` | grep app/ + components/ | **zero hits** — `frame-src` falls through to `default-src 'self'`, safe ✓ |
| Web / service workers | grep app/ + components/ | **zero hits** (the "worker" references are application-level task-queue workers, not browser workers) — `worker-src` falls through to `default-src 'self'`, safe ✓ |
| Remote images / `next/image` | grep + task doc | No remote image domains configured; all images same-origin — `img-src 'self' data: blob:` is correct ✓ |
| PDFs as loaded resources | task doc line 68–69 | PDFs are download-only via the File System Access API; no `blob:` URL is ever loaded as a document or sub-resource ✓ |
| `media-src` | (no override) | Falls through to `default-src 'self'`; no `<video>` / `<audio>` used ✓ |

The `blob:` in `img-src` covers image `<img>` previews if any are generated
client-side; it does not extend to loading blob-URL documents (which would
require a separate `frame-src blob:` or similar). ✓

---

## B. Wiring / mechanism

### B6. Where the CSP applies — **PASS**

Evidence: `next.config.js:29–36`

`source: '/:path*'` in Next.js uses `path-to-regexp` with zero-or-more
semantics, matching the root `/` as well as every sub-path. The CSP header
reaches all Next-rendered routes. ✓

**CSP omitted from `/api/*` — correct:** The `/api/:path*` rewrites deliver
requests to the backend (`http://api:8000`). A CSP on a JSON API response is
inert (browsers apply CSP to document/script execution contexts, not JSON
payloads). The backend already sets security headers via its own middleware
(`backend/app/main.py`). The `next.config.js` comment at lines 6–13 documents
this split explicitly. Omitting CSP from the backend is the right call. ✓

### B7. `NODE_ENV` resolution — **PASS**

Evidence: `next.config.js:14`

`isDev = process.env.NODE_ENV === 'development'` resolves correctly:

- `next dev` → `NODE_ENV=development` → `isDev = true` → dev policy with
  `'unsafe-eval'` and `ws:`, without `upgrade-insecure-requests`.
- `next build` / `next start` → `NODE_ENV=production` → `isDev = false` → prod
  policy, locked down.
- The canonical CI command `NODE_ENV=production npm run build` explicitly forces
  the production path. Sign-off trail confirms both variants were inspected. ✓

### B8. CJS module — **PASS**

Evidence: `csp.js:52`; `next.config.js:3`; `csp.test.js:5`

`csp.js` exports via `module.exports = { buildContentSecurityPolicy }` (CJS).
It is `require`d by `next.config.js` (line 3: `require('./lib/csp')`) and by
`csp.test.js` (line 5: `require('./csp')`). This is the same pattern as
`lib/authRoutes.js` (also CJS, first line: `const AUTH_PUBLIC_PATHS = ...`
without `import`). No ESM/CJS mismatch. Path `./lib/csp` from `next.config.js`
and `./csp` from within `lib/` both resolve to the same file. ✓

---

## C. Tests

### C9. `lib/csp.test.js` coverage — **PASS**

Evidence: `frontend/lib/csp.test.js:1–63`

File is at `frontend/lib/csp.test.js` — discovered by the canonical
`node --test lib/*.test.js` glob. ✓

Five tests; coverage verified:

| Test | What it guards | Would fail if… |
|---|---|---|
| `production policy locks the non-script-source directives down` | All 7 hardening directives (exact equality) | Any directive is dropped or its value changes |
| `production script-src allows inline but not eval` | `'self'` + `'unsafe-inline'` present; `'unsafe-eval'` absent | `'unsafe-eval'` leaks into prod |
| `production policy upgrades insecure requests…` | `upgrade-insecure-requests` present; `connect-src` = `'self'` | Prod-only token dropped; connect-src widened unexpectedly |
| `development policy adds the HMR allowances…` | `'unsafe-eval'` + `ws:` in dev; `upgrade-insecure-requests` absent | Any dev-only token is gated incorrectly |
| `defaults to the production policy` | No-arg call = prod policy | Default flipped to dev |

The `assert.ok(!csp['script-src'].includes("'unsafe-eval'"))` assertion on line
42 explicitly catches a prod leak of the dev-only eval allowance — the most
dangerous possible misconfiguration. ✓

---

## D. Scope / deferred

### D10. Deferral hygiene — **PASS**

Evidence: `BACKLOG.md:117–130`; task doc lines 15–33, 71–78

1. **Original entry removed.** The BACKLOG entry "Content-Security-Policy
   response header" (medium, opened 2026-05-20) is absent from `BACKLOG.md`.
   The new low entry at line 117 explicitly notes "the original 'no
   Content-Security-Policy header' item is resolved." ✓

2. **New low entry present with concrete upgrade paths.** `BACKLOG.md:117–130`
   — severity low, problem described (static policy keeps `'unsafe-inline'`),
   two upgrade paths named (per-request nonce; `experimental.sri` hash-based
   CSP). ✓

3. **Static-vs-nonce decision recorded in task doc.** Lines 15–33 lay out both
   approaches, the Next.js rendering consequence of the nonce approach (23
   statically-prerendered pages would all become dynamic), and the user
   confirmation of the static choice. ✓

---

## Summary of advisory items

| # | Item | Severity | Action |
|---|---|---|---|
| A2 | `script-src 'unsafe-inline'` does not block crafted inline script injection | low (accepted) | BACKLOG low entry with upgrade paths — no immediate action |
| A4 | Cross-origin `NEXT_PUBLIC_API_URL` deployment would need `connect-src` widening | low (current deployment unaffected) | Documented in task doc; note in deployment runbook if architecture changes |

Neither advisory is a blocker. Both are documented. No mandatory gate fails.
