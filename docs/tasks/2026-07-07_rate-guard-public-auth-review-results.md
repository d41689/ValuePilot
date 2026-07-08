# Review results — PR #103 (Rate Guard shared-key auth + public exposure)

**Reviewed:** 2026-07-08
**Change:** commit `3e173c5` on `claude/rate-guard-public-auth`, merged to `main`
as `a4a927a`, auto-deployed to prod.
**Prompts:** [`2026-07-07_rate-guard-public-auth-review-prompts.md`](./2026-07-07_rate-guard-public-auth-review-prompts.md)
**Task doc:** [`2026-07-07_rate-guard-public-auth.md`](./2026-07-07_rate-guard-public-auth.md)

## How this review was run

Three independent review passes (application-security, backend/infra correctness,
staff-engineer posture) per the prompt doc, plus an **independent runtime
verification**: the actual middleware was exercised in a `python:3.11-slim`
container (the README's Rate-Guard test image) driving the real ASGI app, and
the git diff was inspected to confirm the pre-change bind and the unguarded
compare. Findings below are reconciled across all three passes and the runtime
check; each carries a confidence verdict (CONFIRMED = traced in code/at runtime;
PLAUSIBLE = needs a further runtime check).

## Verdict

The auth mechanism is **fundamentally sound** where it matters most: route
coverage is fail-closed on every path variant, there is no credential-format
bypass, the constant-time compare is real, no secret is logged or cached, and
the pre-existing SSRF backstops (host allowlist, https-only, no-redirect-follow)
are untouched. The problems are at the **edges and in the operational envelope**:
a fail-open default on a now-public service, an unhandled-exception path on
attacker input, a single static shared secret, and a set of out-of-repo
operational gaps (rollback coupling, discoverability, observability) that were
never recorded in the backlog.

Nothing here is an active auth **bypass**. The most serious item (fail-open) is
**latent** — mitigated today because the key *is* set and the host port is now
loopback-bound — but it is one env slip away from a silently-open public egress
proxy, so it warrants a hotfix.

### Summary table

| # | Finding | Severity | Confidence |
|---|---|---|---|
| 1 | Fail-open on missing/blank key — public deploy safety rests on one env var, no signal if it's dropped | **P0** | CONFIRMED |
| 2 | Non-ASCII `Authorization` byte → `TypeError` → HTTP 500 (unhandled), not 401 | **P1** | CONFIRMED (mechanism); repro only via raw socket / curl |
| 3 | Rollback coupling — a code-only revert restores the `0.0.0.0` bind while tunnel+DNS live ⇒ re-opens an unauthenticated public proxy | **P1 (operational, ENFORCE)** | CONFIRMED |
| 4 | Static single shared key: no expiry, no per-client identity, no revocation, no 401 lockout, reused dev+prod+remote | **P1** | CONFIRMED |
| 5 | Client sends `Bearer <key>` to whatever `RATE_GUARD_URL` points at — key-leak on a misconfigured/non-HTTPS URL | **P2** | CONFIRMED |
| 6 | CI only ever exercises the auth-**disabled** path; no end-to-end proof the enabled config works | **P2** | CONFIRMED |
| 7 | Unauthenticated `/healthz` discloses upstream names `["edgar","openfigi","dataroma"]` | **P2** | CONFIRMED |
| 8 | Repo↔reality drift — the public exposure (cloudflared ingress, DNS, host secret) is in no version-controlled artifact | **P2 (operational, DEFER)** | CONFIRMED |
| 9 | No observability — no 401/abuse metric or alert on the public path | **P2 (operational, DEFER)** | CONFIRMED |
| 10 | Deferred-work discipline — the dev-api 401 side effect (and items 3,4,8,9) never reached `docs/BACKLOG.md` | **P2 (process, ENFORCE)** | CONFIRMED |
| 11 | Client key not rotatable without an api restart (pydantic settings loaded once) vs server reads env live | **NIT** | CONFIRMED |
| 12 | Key transits Cloudflare in cleartext (TLS terminates at the edge) — acceptable, document the trust assumption | **NIT** | CONFIRMED |
| 13 | Process: test-first ordering unverifiable (one squashed commit); merge=auto-deploy not flagged; CI-clean asserted, not linked | **NIT (process)** | CONFIRMED |

### Severity reconciliation note

The non-ASCII header finding (#2) was rated **P0** by the appsec pass and **P1**
by the backend pass; it is recorded here as **P1**. Rationale: the doc's P0 bar
is "fail-open / bypass, hotfix now" — this is neither. It returns **500, not
200**, so it is not an auth bypass and touches no data; its impact is
error-log flooding / an availability nuisance and a fail-*shape* oracle,
triggerable by any unauthenticated caller. That is a real public-endpoint
robustness defect worth a prompt fix, but it is P1, not P0. Note also: the
backend pass's `TestClient` repro is **not reliable** — httpx/`TestClient`
rejects non-ASCII header values *client-side* (`UnicodeEncodeError`), so the 500
is only reachable over a raw socket (e.g. `curl -H $'Authorization: Bearer
\xc3\xa9'`). The underlying mechanism is CONFIRMED (uvicorn latin-1-decodes the
header → non-ASCII `str` → `secrets.compare_digest` raises `TypeError` → the
middleware has no `try/except` → 500). Because the fix lives in the same
`auth.py` function as the P0 fail-closed guard, **bundle it into the same
hotfix**.

---

## P0 — hotfix now (it's live)

### 1. Fail-open on missing/blank key
- **Where:** `rate-guard/app/auth.py:35-37` (`is_authorized` returns `True` when
  `configured_api_key()` is empty); `rate-guard/app/auth.py:25` (`.strip()` maps
  unset / `""` / `"   "` / `"\n"` all to `""`).
- **What:** On the public deployment, any ordinary env mishap silently disables
  auth and turns `/v1/fetch` + `/v1/metrics` into an open relay to
  SEC/OpenFIGI/Dataroma under our egress IP + SEC-registered User-Agent (→ SEC
  can ban that IP). The container gives **no signal**: `/healthz` returns 200
  either way and the deploy's `wait_for_url .../healthz` passes.
- **Repro (CONFIRMED at runtime):** with `RATE_GUARD_API_KEY` unset / `""` /
  `"   "` / `"\n"`, `POST /v1/fetch` with **no** Authorization header → **200**
  and the upstream fetch executes. Realistic ways the key ends up empty on
  `rate-guard.richmom.vip`:
  - the deploy runner's workspace `.env` is copied (`deploy.yml` step "Install
    deploy env files") before the key was added, or a bad `.env` merge drops the
    line;
  - a trimmed/blank value (`RATE_GUARD_API_KEY=` or a stray trailing space) —
    `.strip()` erases it;
  - a container started against a `.env` that doesn't contain the key (compose
    does not error on a missing var);
  - the key rotated to blank / accidentally removed; the container restarts open.
- **Fix (proposed, same hotfix):** make the public path fail **closed** with an
  explicit opt-in signal, mirroring the existing `SEC_CONTACT_EMAIL`
  fail-loud-at-startup pattern. Concrete:

  ```python
  # rate-guard/app/auth.py
  import hmac  # for the byte-compare fix in P1 #2

  def public_auth_required() -> bool:
      return os.environ.get("RATE_GUARD_REQUIRE_AUTH", "").strip().lower() in {"1", "true", "yes"}

  def is_authorized(auth_header: str | None) -> bool:
      key = configured_api_key()
      if not key:
          return True  # opt-in default preserved for CI / internal
      if not auth_header:
          return False
      # bytes compare: never raises on non-ASCII header bytes (P1 #2)
      return hmac.compare_digest(
          auth_header.encode("latin-1", "replace"), f"Bearer {key}".encode("latin-1")
      )
  ```

  ```python
  # rate-guard/app/main.py — at module load, next to _cache/_gateway
  if public_auth_required() and not configured_api_key():
      raise RuntimeError(
          "RATE_GUARD_REQUIRE_AUTH is set but RATE_GUARD_API_KEY is empty — "
          "refusing to start an unauthenticated public Rate Guard."
      )
  if not configured_api_key():
      logging.getLogger("rate_guard.auth").warning(
          "RATE_GUARD_API_KEY is not set — auth DISABLED, all /v1/* are open."
      )
  ```

  Then set `RATE_GUARD_REQUIRE_AUTH=1` in the host `~/.config/valuepilot/.env`
  (or the public-instance env) so the exposed container refuses to boot keyless.
  Document that the tunnel must never be created without it. Add regression tests
  for both the startup-refusal and the loud-warning paths.

---

## P1 — same-week follow-up PR

### 2. Non-ASCII `Authorization` byte crashes the auth check (500, not 401)
- **Where:** `rate-guard/app/auth.py:40` (`secrets.compare_digest(auth_header,
  ...)` unguarded); `rate-guard/app/main.py:41-43` (middleware does not wrap
  `is_authorized`).
- **What:** `secrets.compare_digest` raises `TypeError: comparing strings with
  non-ASCII characters is not supported` for any `str` code point > 127. uvicorn
  latin-1-decodes header bytes, so any header byte ≥ 0x80 reaches the compare and
  the request 500s (with a server-side traceback) instead of returning a clean
  401.
- **Repro:** stdlib CONFIRMED — `secrets.compare_digest("Bearer \x80", "Bearer
  s3cret")` → `TypeError` (verified in `python:3.11-slim`). End-to-end reachable
  via a raw client, e.g. `curl -H $'Authorization: Bearer \xc3\xa9'
  https://rate-guard.richmom.vip/v1/fetch` → 500. **Not** reproducible through
  `TestClient`/httpx (they guard non-ASCII header values client-side). Not an
  auth bypass (500 ≠ 200).
- **Fix:** the `hmac.compare_digest(...encode("latin-1", "replace"), ...)`
  byte-compare shown in the P0 patch — bytes `compare_digest` accepts any byte
  value and is still constant-time. (Alternatively wrap the compare in
  `try/except TypeError: return False`.) Add a high-byte header regression test
  in `rate-guard/tests/test_auth.py`.

### 3. Rollback coupling re-opens an unauthenticated public proxy — ENFORCE
- **What:** A code-only revert of PR #103 removes the auth middleware **and**
  restores the `0.0.0.0` host-port bind on the next deploy (the pre-change
  compose bound `"${RATE_GUARD_HOST_PORT:-9099}:9000"`; CONFIRMED in the diff)
  — while the cloudflared ingress `rate-guard.richmom.vip → localhost:9099` and
  its DNS CNAME still point at the container. Result:
  `rate-guard.richmom.vip/v1/fetch` becomes an **unauthenticated public egress
  proxy**. This ordering hazard is documented nowhere in the repo.
- **Fix (ENFORCE — do now, cheap):** add a **Rollback** runbook (see the new
  `docs/architecture/rate-guard-public-exposure.md` recommended below), and keep
  the loopback bind (`127.0.0.1:9099`) even under a code rollback so removing
  auth alone never exposes the host IP. Correct order:
  1. **Tear down the public path FIRST** — remove the `rate-guard.richmom.vip`
     ingress from `~/.cloudflared/config.yml`, restart cloudflared, delete the
     Cloudflare DNS CNAME; verify the URL no longer routes.
  2. **Only then** revert the code + redeploy. Never revert code while the tunnel
     is live.

### 4. Static single shared secret — no expiry, per-client identity, revocation, or lockout
- **What:** One 256-bit static bearer gates a public relay, reused across dev +
  prod + the remote box, with no expiry, no per-client key, no per-client
  revocation, and no rate-limit/lockout on repeated 401s. 256-bit entropy makes
  *online guessing* a non-threat; the realistic threat is **leak reuse** (a dev
  laptop `.env`, a CI log, the remote box, a chat paste), after which the only
  remedy is rotating the one key everywhere at once (a hard cutover — no dual-key
  window; `is_authorized` accepts exactly one `Bearer {key}`).
- **Fix (pick a lane; record in backlog):**
  - *Preferred:* move auth to the edge — **Cloudflare Access service tokens**
    (per-client, revocable, expiring) or mTLS — and keep the app bearer only as
    defense-in-depth.
  - *If keeping the app bearer:* (1) separate dev vs prod keys; (2) accept a
    **set** of keys so rotation has a dual-key window
    (`RATE_GUARD_API_KEY` + `RATE_GUARD_API_KEY_PREVIOUS`); (3) a **Cloudflare
    WAF rate rule** on the subdomain; (4) alert on 401 spikes / `/v1/fetch`
    volume spikes.

---

## P2 / NIT — route to `docs/BACKLOG.md` (link this doc)

### 5. Bearer key sent to whatever `RATE_GUARD_URL` points at (P2)
`backend/app/rate_guard/client.py:67-72,87-89` — `_auth_headers()` attaches the
key on every request with no scheme/host check, so a misconfigured
`RATE_GUARD_URL` (plain-http tunnel, wrong subdomain, typo host) transmits the
shared key to an unintended endpoint. **Fix:** when a key is set and the base URL
is not `https://` (and the host is not the internal `rate-guard`/loopback), log a
warning or refuse; at minimum document that `RATE_GUARD_URL` must be HTTPS
whenever `RATE_GUARD_API_KEY` is set.

### 6. CI never exercises the auth-ENABLED path end-to-end (P2)
`ci.yml` sets `RATE_GUARD_URL=http://rate-guard.invalid` and never sets
`RATE_GUARD_API_KEY`, so CI green only proves the auth-**disabled** path.
rate-guard's own with-key happy path through `/v1/fetch` is explicitly skipped
(`test_auth.py:72-81`), and nothing asserts a per-upstream client
(`EdgarClient`/`OpenFigiClient`/`DataromaClient`) propagates the header
end-to-end. A header-plumbing regression in a per-upstream client, or a
`/v1/fetch` auth regression, passes CI. **Fix:** add (a)
`test_fetch_accepts_correct_key_and_reaches_gateway` (monkeypatch
`main._gateway.fetch` to a stub, POST with the correct key, assert 200 + stub
called — proves the middleware passes auth *through*, not just short-circuits
401); and (b) `test_edgar_sends_bearer_end_to_end` (set
`settings.RATE_GUARD_API_KEY`, drive `EdgarClient` with a `MockTransport`, assert
the captured request carries `Authorization: Bearer <key>`).

### 7. Unauthenticated `/healthz` discloses upstream names (P2)
`rate-guard/app/main.py:57-59` returns `{"status":"ok","upstreams":
["edgar","openfigi","dataroma"]}` without auth, confirming to an attacker that
this is an SEC/OpenFIGI/Dataroma relay and narrowing their `upstream` guessing
for a leaked-key attack. **Fix:** return only `{"status":"ok"}` on the
unauthenticated liveness probe (the deploy poller and any Docker healthcheck only
need a 200); keep the upstream list on the authenticated `/v1/metrics`.

### 8. Repo↔reality drift — public exposure captured in no manifest (P2, operational)
The cloudflared ingress, the Cloudflare DNS CNAME, and the `RATE_GUARD_API_KEY`
host secret live entirely outside the repo; the only in-repo trace is prose in
`rate-guard/README.md`. A future engineer greps `richmom` and finds a *how-to*,
not a *this-is-live* record. **Fix:** create
`docs/architecture/rate-guard-public-exposure.md` recording the live ingress
hostname→port map, the DNS CNAME, the `127.0.0.1:9099` bind, which host file
holds the key (value not committed), and a committed **secret-free** copy of the
cloudflared ingress block so tunnel state is diffable. (This is also the home for
the #3 rollback runbook and the #4 rotation runbook.)

### 9. No observability on the public path (P2, operational)
No metric/alert for auth failures or public traffic; `/v1/metrics` tracks
per-upstream volume only. A leaked key or brute-force spray would first surface
as our egress IP getting banned. **Fix:** (1) counter/log on every 401 in the
auth middleware + alert on 401-rate spikes; (2) a Cloudflare WAF rate-limit rule
on `rate-guard.richmom.vip` + source-IP via CF logs (CF sees the real client IP
before the tunnel); (3) alert on anomalous `/v1/fetch` volume.

### 10. Deferred-work discipline — known items never reached the backlog (P2, process, ENFORCE)
The dev-api 401 side effect (`valuepilot-dev-api-1`'s running container predates
the key, so its EDGAR calls 401 until a recreate coupled to #99) is recorded in
neither `docs/BACKLOG.md` nor the task doc's sign-off trail. AGENTS.md "Deferred
work" requires every out-of-scope discovered problem to be recorded before
calling the work done. It is correctly **dev-only** (no prod impact — not a
stop-and-tell breakage), but "dev-only" is the medium-severity backlog channel,
not silence. Items 3, 4, 8, 9 are likewise unrecorded. **Fix:** add the backlog
entries below.

### 11. Client key not rotatable without an api restart (NIT)
Server reads the key live from `os.environ` per request (rotatable); the api
reads `settings.RATE_GUARD_API_KEY` (pydantic, loaded once at import,
`config.py:102`), so a rotation or first-time key add needs an **api container
recreate**, not just an env edit — this is exactly the dev-api 401 smell.
Symmetric blank-handling is fine (no `Bearer `-empty vs server-disabled
mismatch). **Fix:** document that changing the key requires recreating the api
containers; or, if live rotation is wanted, have `_auth_headers()` read
`os.environ` directly like the server.

### 12. Key transits Cloudflare in cleartext (NIT)
TLS terminates at Cloudflare, so the bearer is visible at the CF edge and on the
cloudflared hop — acceptable for this threat model (adversary is on the internet,
not CF), matching how CF Access works. **Fix:** none; document the "Cloudflare is
trusted" assumption in the README. The #4 move to CF Access/mTLS subsumes it.

### 13. Process gaps (NIT)
- Test-first ordering is **unverifiable** — the change is one squashed commit
  (`3e173c5`) mixing production code and tests, so red→green can't be confirmed
  from history; it rests on the task doc's word.
- The **merge = auto-deploy-to-prod** coupling (`deploy.yml`: CI success on
  `main` → self-hosted runner → `deploy_prod_from_main.sh`) means merging this PR
  auto-shipped the loopback bind + auth to prod; the task doc doesn't flag that
  merging is the deploy trigger (ties into #3 — the rollout ordering must be
  ready *before* merge).
- The **canonical backend gate was never run green in-repo** — the task doc
  reports full `pytest -q` at 185 failures + 11 errors, waved off as
  environmental (live dev DB; consistent with the known
  `full_backend_suite_vs_dev_db` behavior), with CI-on-fresh-volume as the
  authoritative gate — but no CI run is linked, so the clean-DB result rests on
  assertion. **Fix:** for future security-sensitive PRs, link the green CI run in
  the PR/task doc and prefer separate test/impl commits (or a documented TDD
  trail).

---

## Confirmed safe (defense-in-depth that held)

Recorded so the next reviewer knows these were checked, not skipped:

- **Route coverage / path normalization.** `_AUTH_EXEMPT_PATHS` is an
  exact-string match on `request.url.path`. Verified at runtime that with the key
  set, `/v1/fetch`, `/v1/metrics`, `/docs`, `/openapi.json`, `/redoc`,
  `/healthz/` (trailing slash), `//v1/fetch`, and `/HEALTHZ` (case) **all return
  401**; only the literal `/healthz` is open. No normalization trick reaches a
  capability route while dodging the check, and the exemption is not over-broad.
- **No credential-format bypass.** lowercase `bearer`, leading/trailing space,
  trailing `\n`, double space, no-scheme, and duplicated `Authorization` headers
  (wrong+correct) all return 401; only the exact `Bearer <key>` returns 200. The
  constant-time compare holds for ASCII inputs. (The one comparison defect is the
  non-ASCII TypeError, #2.)
- **Secret handling.** Nothing logs the Authorization header or the key:
  `logging.basicConfig` + gateway logs record upstream name + upstream URL only
  (the key is a header, never in a URL); backend `client.py` warnings log
  `url`/`upstream` only; uvicorn access logs record method/path/status, not
  headers; the on-disk cache key is `sha256(upstream, method, url, body)` — no
  auth material; `/v1/metrics` output carries no key.
- **Universal-caller completeness (code).** Every rate-guard access goes through
  `RateGuardClient` — the three per-upstream clients (`edgar`/`openfigi`/
  `dataroma`) and the admin dashboard (`thirteenf_admin_dashboard.py:293`). No
  direct `httpx`/`requests`/`curl` to `rate-guard:9000` or `:9099`; the Dockerfile
  defines no `HEALTHCHECK`; the only `/healthz` poller is the deploy script, and
  `/healthz` is exempt. The dev-api 401 is env-propagation, not a code bypass.
- **Middleware ordering.** The `@app.middleware("http")` runs before route
  handling, so a no-key `/v1/fetch` returns 401 **before** body parse or any
  `_gateway.fetch` — no upstream call, no cache write. Order-independent w.r.t.
  the route decorators.
- **The 127.0.0.1 bind is correct.** Loopback keeps `/healthz` reachable for the
  deploy poller (`127.0.0.1:9099`) and for cloudflared (host-local); internal
  callers use `rate-guard:9000` on `projects-shared`, unaffected. The only thing
  removed is off-host LAN metrics inspection — intended hardening, correct as
  defense-in-depth even with auth in-app.
- **SSRF backstops untouched.** The change did not touch `gateway.py`; the host
  allowlist (`host in u.allowed_hosts`), https-only scheme check, and
  `follow_redirects=False` all still run on every `fetch()` before any upstream
  request, independent of auth. Residual (by design): a leaked key = free relay
  to the *allowlisted* hosts under our IP — which is exactly why #4's
  compensating controls matter.

---

## Recommended actions

**P0 hotfix (new branch → PR → merge → auto-deploy):** the fail-closed guard
(#1) + the byte-compare (#2) + `/healthz` slimming (#7) — all in `auth.py` /
`main.py`, one small PR. Then set `RATE_GUARD_REQUIRE_AUTH=1` on the public
instance's env. Re-run the gates and re-verify the live surface (below).

**P1, same week:** rollback runbook + `rate-guard-public-exposure.md` (#3, #8);
decide the secret-strength lane (#4) — at minimum add the CF WAF rate rule and a
401 alert (#9).

**Backlog now (paste into `docs/BACKLOG.md`, per #10):**

```
### Rate Guard auth is fail-open — no fail-closed guard for the public path
- **Found:** 2026-07-08, PR #103 staff review
- **Severity:** high
- **Problem:** rate-guard/app/auth.py returns authorized when RATE_GUARD_API_KEY
  is unset/blank. On the public rate-guard.richmom.vip path, a dropped, blanked,
  or non-interpolated key silently turns /v1/fetch into an open egress proxy with
  no error. Safety depends entirely on an env var being present.
- **Fix sketch:** add RATE_GUARD_REQUIRE_AUTH=true that makes a missing/blank key
  a hard startup failure, mirroring the SEC_CONTACT_EMAIL fail-loud pattern; set
  it on the exposed instance, keep opt-in default for CI/internal.
- **Context:** docs/tasks/2026-07-07_rate-guard-public-auth-review-results.md (P0 #1)
- **Issue:** —

### Rate Guard public exposure (rate-guard.richmom.vip) is undocumented in-repo
- **Found:** 2026-07-08, PR #103 staff review
- **Severity:** medium
- **Problem:** rate-guard.richmom.vip is a live public egress proxy, but the only
  in-repo trace is prose in rate-guard/README.md. The cloudflared ingress and the
  Cloudflare DNS CNAME are version-controlled nowhere; a future engineer cannot
  discover the subdomain is provisioned and serving, nor safely reason about the
  rollback ordering (a code-only revert re-opens it unauthenticated).
- **Fix sketch:** add docs/architecture/rate-guard-public-exposure.md recording
  the live ingress hostname→port map, the DNS CNAME, the 127.0.0.1:9099 bind,
  which host file holds RATE_GUARD_API_KEY, a secret-free copy of the cloudflared
  ingress block, and a Rollback runbook (tear down the tunnel route FIRST).
- **Context:** docs/tasks/2026-07-07_rate-guard-public-auth-review-results.md (#3, #8)
- **Issue:** —

### Rate Guard shared key — no rotation runbook, no dual-key window
- **Found:** 2026-07-08, PR #103 staff review
- **Severity:** medium
- **Problem:** One static RATE_GUARD_API_KEY is shared across dev, prod, and the
  remote dev machine, no expiry, no documented rotation. is_authorized() accepts
  exactly one key (no dual-key support), so rotation is an atomic cutover — every
  caller on the old key 401s until updated. On leak, blast radius is full
  egress-proxy access under our IP/User-Agent, and the same key also gates dev.
- **Fix sketch:** (1) document rotation in rate-guard-public-exposure.md, noting
  the atomic-cutover 401 window; (2) add RATE_GUARD_API_KEY_PREVIOUS so two keys
  are accepted during rotation; (3) separate dev vs prod keys.
- **Context:** docs/tasks/2026-07-07_rate-guard-public-auth-review-results.md (P1 #4)
- **Issue:** —

### Rate Guard public path has no auth-failure / abuse observability
- **Found:** 2026-07-08, PR #103 staff review
- **Severity:** medium
- **Problem:** No metric or alert exists for 401s or for public traffic hitting
  rate-guard.richmom.vip. A leaked key or brute-force would go unnoticed until our
  egress IP is banned by SEC/OpenFIGI. /v1/metrics tracks upstream volume only;
  the auth middleware emits no 401 signal and no source-IP visibility.
- **Fix sketch:** (1) counter/log on every 401 in the auth middleware + alert on
  401-rate spikes; (2) a Cloudflare WAF rate-limit rule on rate-guard.richmom.vip
  plus source-IP via CF logs; (3) alert on anomalous /v1/fetch volume.
- **Context:** docs/tasks/2026-07-07_rate-guard-public-auth-review-results.md (#9)
- **Issue:** —

### Rate Guard key not yet in dev api container — EDGAR calls 401
- **Found:** 2026-07-07, PR #103 rollout
- **Severity:** medium (dev-only — prod verified working with the key)
- **Problem:** Enabling RATE_GUARD_API_KEY turned on auth for the shared Rate
  Guard, but valuepilot-dev-api-1's running container predates the key and does
  not carry it, so its EDGAR/OpenFIGI/Dataroma fetches 401. Needs a container
  recreate coupled to the already-merged #99 (dev → shared Postgres) work.
- **Fix sketch:** recreate valuepilot-dev-api-1 so it picks up RATE_GUARD_API_KEY
  from the shared .env, coupled to the #99 dev recreate; verify dev EDGAR → 200.
- **Context:** docs/tasks/2026-07-07_rate-guard-public-auth-review-results.md (#10)
- **Issue:** —

### Rate Guard CI never exercises the auth-enabled path; RATE_GUARD_URL leaks key on non-HTTPS
- **Found:** 2026-07-08, PR #103 backend review
- **Severity:** low
- **Problem:** CI sets RATE_GUARD_URL=http://rate-guard.invalid and no key, so
  only the auth-disabled path is covered; the with-key /v1/fetch happy path and
  end-to-end header propagation from EdgarClient are untested. Separately,
  RateGuardClient sends the Bearer key to whatever RATE_GUARD_URL points at with
  no scheme/host guard.
- **Fix sketch:** add test_fetch_accepts_correct_key_and_reaches_gateway and
  test_edgar_sends_bearer_end_to_end; warn/refuse when a key is set and
  RATE_GUARD_URL is non-HTTPS to a non-internal host.
- **Context:** docs/tasks/2026-07-07_rate-guard-public-auth-review-results.md (#5, #6)
- **Issue:** —
```

## Re-run gates before any re-deploy (from the prompt doc)

```
# rate-guard suite (containerized)
docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim \
  sh -c "pip install -q -r requirements-dev.txt && pytest -q"
# backend + frontend canonical CI
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

Then re-verify the live surface: `/v1/fetch` no-key → 401, with-key → 200, both
on `127.0.0.1:9099` and `https://rate-guard.richmom.vip`; and, with the new
guard, that a keyless public instance with `RATE_GUARD_REQUIRE_AUTH=1` refuses to
boot.

## Appendix — independent runtime verification

Run in `python:3.11-slim` against the real ASGI app (`RATE_GUARD_API_KEY=s3cret`):

| Input | Result |
|---|---|
| no Authorization header | 401 |
| `Bearer nope` (wrong) | 401 |
| `Bearer s3cret` (correct) | 200 |
| `bearer s3cret` (lowercase scheme) | 401 |
| `Bearer  s3cret` (double space) | 401 |
| `Bearer s3cret\n` (trailing newline) | 401 |
| `/healthz` | 200 (exempt) |
| `/healthz/`, `//v1/fetch`, `/v1/metrics`, `/docs`, `/openapi.json` | 401 |
| key unset / `""` / `"   "` / `"\n"`, no header → `/v1/fetch` | 200 (fail-open, #1) |
| `secrets.compare_digest("Bearer \x80", "Bearer s3cret")` | raises `TypeError` (#2) |

Diff check: pre-change `docker-compose.rateguard.yml` bound
`"${RATE_GUARD_HOST_PORT:-9099}:9000"` (`0.0.0.0`), confirming the #3 rollback
hazard; `auth.py`'s `compare_digest` call has no `try/except`, confirming #2.

---

## Resolution verified — 2026-07-08 (live)

All findings addressed by PR #104 (`Harden Rate Guard public auth`, merged
`0bbad71`), auto-deployed to prod, then **verified on the running service** — see
[`2026-07-08_rate-guard-auth-hardening.md`](./2026-07-08_rate-guard-auth-hardening.md).

| # | Fix | Live check on the deployed rate-guard |
|---|---|---|
| P0 #1 | Fail-closed `enforce_auth_config()` + `RATE_GUARD_REQUIRE_AUTH=1` | Container runs with `REQUIRE_AUTH=1` + key present → boots (guard passes); keyless-boot refusal covered by unit test |
| P1 #2 | Bytes-based `compare_digest` | non-ASCII `Authorization` (`\xe9\x80`) → **401**, no 500 |
| P1 #3 | Rollback runbook + keep loopback bind | `docs/architecture/rate-guard-public-exposure.md`; port is `127.0.0.1:9099` |
| P1 #4 | Dual-key `RATE_GUARD_API_KEY_PREVIOUS` + rotation runbook | primary/previous both accepted (unit); WAF/split-values → backlog |
| P2 #5 | Client warns on key-over-insecure-URL | 2 tests |
| P2 #6 | with-key `/v1/fetch` + `EdgarClient` e2e tests | pass |
| P2 #7 | `/healthz` = `{"status":"ok"}` only | internal + public both `{"status":"ok"}` (no upstream list) |
| P2 #8 | Exposure manifest | `docs/architecture/rate-guard-public-exposure.md` |
| #10 | Backlog entries | added; the dev-api 401 entry is now **resolved** (below) |

Auth still enforced post-deploy: no-key → 401, wrong-key → 401, correct-key →
200, on both `127.0.0.1:9099` and `https://rate-guard.richmom.vip`. Prod api
carries the key.

**Dev-api 401 (review #10 side effect) — resolved 2026-07-08.**
`valuepilot-dev-api-1` was recreated onto the shared Postgres (adopting the
already-merged #99), which loaded `RATE_GUARD_API_KEY`; the shared `valuepilot`
db was migrated to head (36 tables). Verified: dev `/health` → 200, and dev api →
rate-guard `/v1/metrics` → **200** (was 401). Old local dev data remains in
`valuepilot-dev-db-1` / `./storage/postgres`, unused per #99. Backlog entry
cleared in this PR.

Still deferred (backlog): #9 observability (CF WAF + 401 alerting), #4 residual
(distinct dev/prod key values; Cloudflare Access as a future option).
