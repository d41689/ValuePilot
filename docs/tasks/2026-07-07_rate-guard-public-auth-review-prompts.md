# Review prompts — PR #103 (Rate Guard shared-key auth + public exposure)

Task doc: [`2026-07-07_rate-guard-public-auth.md`](./2026-07-07_rate-guard-public-auth.md)
PR: https://github.com/d41689/ValuePilot/pull/103 (MERGED → `main` as `a4a927a`)
Branch: `claude/rate-guard-public-auth`
Change commit: `3e173c5`

## What shipped tonight

Rate Guard — the single shared egress chokepoint for SEC EDGAR / OpenFIGI /
Dataroma — was **internal-only**. This change exposes it on the public internet
so **one remote dev machine** can reach it, and gates the surface behind an
**opt-in shared Bearer key**:

- `rate-guard/app/auth.py` (new) — `configured_api_key()` reads
  `RATE_GUARD_API_KEY` live from env; `is_authorized(auth_header)` returns
  `True` when **no key is configured** (auth disabled), else requires the header
  to equal `Bearer <key>` via `secrets.compare_digest`.
- `rate-guard/app/main.py` — one `@app.middleware("http")` that, for every path
  except `/healthz`, rejects with `401` when `is_authorized` is false. Runs
  before route handling, so `/v1/fetch` and `/v1/metrics` 401 before any
  upstream call.
- `backend/app/rate_guard/client.py` — `_auth_headers()` adds
  `Authorization: Bearer <key>` to the `/v1/fetch` POST and `/v1/metrics` GET
  when `RATE_GUARD_API_KEY` is set.
- `backend/app/core/config.py` — new `RATE_GUARD_API_KEY: Optional[str] = None`.
- `docker-compose.rateguard.yml` — host port bound `127.0.0.1:${RATE_GUARD_HOST_PORT:-9099}:9000`.
- Docs: `.env.prod.example`, `rate-guard/README.md`.

### Out-of-repo operational changes made the same night (NOT in the diff — a code reviewer cannot see these; they are part of the change under review)

- Host `~/.cloudflared/config.yml`: added ingress `rate-guard.richmom.vip →
  http://localhost:9099` (before the `http_status:404` catch-all); Cloudflare
  DNS CNAME created via `cloudflared tunnel route dns`.
- Host `~/.config/valuepilot/.env` (canonical, copied into the runner workspace
  on deploy) and the dev working-copy `.env`: `RATE_GUARD_API_KEY=<64-hex>` added.
- The shared Rate Guard reached prod via the auto-deploy (`deploy.yml` on the
  self-hosted runner, triggered by CI success on `main`). Verified live:
  `/v1/fetch` no-key → 401, with-key → 200 both internally (`:9099`) and
  externally (`https://rate-guard.richmom.vip`); `9099` now on `127.0.0.1`.
- Known dev-only side effect: `valuepilot-dev-api-1` still lacks the key in its
  running container (needs a recreate, which is coupled to the already-merged
  #99 "dev → shared Postgres" compose change), so its EDGAR calls 401 until then.

**The reviewer is NOT given the key value.** Do not expect it; reason about the
mechanism, not the secret.

The three prompts below are for **three different external agents**, reviewing
the same change from different angles. Run in parallel; collect findings under
`2026-07-07_rate-guard-public-auth-review-results.md`.

---

## Prompt 1 — Application security reviewer (the critical angle)

```
You are a senior application-security engineer reviewing a change that takes an
internal-only egress proxy and exposes it to the public internet behind a shared
Bearer key. Assume an adversary who knows the URL exists and wants to (a) use the
proxy without the key, or (b) turn it into a free relay to SEC / OpenFIGI /
Dataroma under the victim's IP + SEC-registered User-Agent (which can get that IP
banned by the SEC).

Repository: https://github.com/d41689/ValuePilot
Branch: claude/rate-guard-public-auth  (PR #103, merged as a4a927a)
Read first:
  - docs/tasks/2026-07-07_rate-guard-public-auth.md (task doc + the "out-of-repo
    operational changes" section of the review-prompts doc)
  - AGENTS.md ("Critical invariants — never violate")
  - rate-guard/app/auth.py, rate-guard/app/main.py (the whole auth path)
  - rate-guard/app/gateway.py (host allowlist, no-redirect-follow — the pre-existing
    controls this change must not weaken)
  - backend/app/rate_guard/client.py (_auth_headers)

Threat model: the service is now reachable at https://rate-guard.richmom.vip.
TLS terminates at Cloudflare; a cloudflared tunnel carries the request to
localhost:9099 → the container's :9000. Auth is enforced in the app, not at the
edge (Option A "app bearer", NOT Cloudflare Access).

Scrutinize, most-severe first:

  1. FAIL-OPEN ON MISSING KEY. is_authorized() returns True when
     RATE_GUARD_API_KEY is unset/blank — auth DISABLED. The service is now
     public. Enumerate every way the key could end up empty at runtime (env not
     copied on deploy, a bad .env merge, a trimmed/blank value, a container
     started without env_file) and the blast radius of each: a silent open proxy
     on a public URL. Argue whether a publicly-exposed deployment should instead
     fail CLOSED (refuse to serve /v1/* without a key) or at least log a loud
     startup warning. Propose the concrete guard.

  2. COMPARISON CORRECTNESS. is_authorized does
     secrets.compare_digest(auth_header, f"Bearer {key}"). Verify: constant-time
     property holds for str inputs; no exception path leaks (None/empty handled);
     the whole "Bearer <key>" string is matched (scheme required). Probe bypass
     inputs: lowercase "bearer", extra whitespace, trailing "\n", duplicated
     Authorization headers, "Bearer  <key>" (double space), a valid key with a
     query/body twist.

  3. ROUTE COVERAGE / PATH NORMALIZATION. Only "/healthz" is exempt (exact
     string match on request.url.path). Confirm /v1/fetch, /v1/metrics, /docs,
     /openapi.json, /redoc are all gated. Test normalization bypasses that reach
     a route while dodging the exact-match exemption OR vice-versa: "/healthz/",
     "//v1/fetch", "/v1/%2e%2e/healthz", trailing dot, case. Does Starlette
     normalize the path before or after the middleware sees it?

  4. SECRET HANDLING. Does anything log the Authorization header or the key?
     Check rate-guard logging (main.py logging.basicConfig INFO, gateway logs,
     uvicorn access logs) and the client's warning logs (client.py logs URLs on
     failure — does a URL ever carry the key?). Confirm the key is never cached
     to the on-disk response cache key or written to metrics.

  5. STRENGTH OF THE MECHANISM. A single static 256-bit shared secret, one value
     for dev + prod + the remote machine, no expiry, no per-client identity, no
     revocation-per-client, no rate-limit/lockout on 401s. For a public endpoint,
     is that adequate? Compare against Cloudflare Access service tokens / mTLS /
     per-client keys. If you'd accept the static bearer, say under what
     compensating controls (rotation cadence, monitoring, CF WAF rule).

  6. RESIDUAL EXPOSURE. The /healthz exemption returns {status, upstreams:[...]}
     publicly — does leaking upstream names matter? Is there any un-authenticated
     information disclosure or oracle (timing, error-message shape 401-vs-400)
     that aids an attacker? The key transits Cloudflare in cleartext (TLS
     terminates there) — acceptable for this trust boundary?

  7. DEFENSE-IN-DEPTH THAT SURVIVED. Confirm the change did NOT weaken the
     pre-existing gateway controls: host allowlist, HTTPS-only upstream, and
     "redirects are not followed". A public caller with the key can drive
     arbitrary {upstream,url} into the gateway — is the allowlist still the hard
     backstop against SSRF to non-allowlisted hosts?

For each finding: severity P0 (hotfix now — it's live) / P1 (follow-up) / P2 /
NIT, a concrete exploit or failing input, and a specific fix.
```

---

## Prompt 2 — Backend / infra engineer (correctness + deployment topology)

```
You are a senior backend engineer reviewing PR #103 of ValuePilot for
correctness of the auth middleware, the client change, and how the change
interacts with the real deployment topology.

Repository: https://github.com/d41689/ValuePilot
Branch: claude/rate-guard-public-auth (merged a4a927a)
Read first:
  - rate-guard/app/main.py, rate-guard/app/auth.py, rate-guard/tests/test_auth.py
  - backend/app/rate_guard/client.py, backend/tests/unit/test_rate_guard_client.py
  - backend/app/edgar/client.py + any OpenFigi/Dataroma client (all callers of
    RateGuardClient)
  - docker-compose.rateguard.yml, docker-compose.yml, docker-compose.prod.yml
    (env_file wiring), scripts/deploy_prod_from_main.sh, .github/workflows/deploy.yml
  - AGENTS.md (canonical CI, test-first)

Topology facts to hold in mind: there is ONE shared rate-guard container on the
external `projects-shared` network, deployed from the CI-runner workspace via
main. Dev api, prod api, and the remote machine all call it. When
RATE_GUARD_API_KEY is set, the middleware enforces it for EVERY caller — internal
`rate-guard:9000` traffic included.

Review:

  1. UNIVERSAL-CALLER COMPLETENESS. Turning auth on globally breaks any caller
     that doesn't send the key. Enumerate EVERY code path that reaches rate-guard
     and confirm each goes through RateGuardClient (which now attaches the
     header). Is there any direct httpx/requests call to rate-guard:9000, any
     worker, any script, any healthcheck, that would silently 401? (A dev-api
     instance already hit exactly this — treat it as a smell, not a one-off.)

  2. MIDDLEWARE SEMANTICS. Confirm the middleware returns 401 BEFORE route
     handling and body parsing, so a no-key /v1/fetch makes no upstream call and
     no cache write. Confirm order-independence w.r.t. the route decorators.
     is_authorized reads os.environ per request — any correctness/perf/threading
     concern under uvicorn workers? Does per-request env read enable key rotation
     without restart, and is that intended/documented?

  3. CLIENT HEADER PLUMBING. _auth_headers() is passed to both the POST /v1/fetch
     and GET /v1/metrics. Verify it does not clobber other headers, that httpx
     merges rather than replaces, that an empty dict (no key) yields today's exact
     behavior (existing tests assert URL/payload unchanged), and that the header
     is not sent when RATE_GUARD_URL points somewhere unexpected.

  4. TEST ADEQUACY. rate-guard has 10 new auth tests; backend has 3. What's
     missing? Candidates: a with-key happy path through /v1/fetch (the suite only
     asserts the 401 short-circuit to avoid a network call — is there a way to
     assert pass-through with a mocked gateway?); path-normalization cases;
     duplicate/again-cased Authorization headers; a test that a real internal
     caller (EdgarClient) sends the header end-to-end. Importing app.main needs
     SEC_CONTACT_EMAIL + a writable cache dir — is the test's env setup robust on
     a clean CI runner?

  5. THE 127.0.0.1 BIND. Confirm binding the host port to loopback does not break
     (a) the deploy healthcheck (scripts/deploy_prod_from_main.sh polls
     127.0.0.1:9099/healthz — fine?), (b) the Docker healthcheck if any, (c) the
     cloudflared tunnel (runs on the host, reaches localhost:9099 — fine?). Does
     any LAN-based metrics inspection workflow break? Is the bind the right layer
     given auth is already enforced in-app?

  6. CONFIG HANDLING. RATE_GUARD_API_KEY: Optional[str] = None via pydantic
     settings; the code does (settings.RATE_GUARD_API_KEY or "").strip(). Confirm
     blank/whitespace is treated as "unset" consistently on BOTH sides (client
     _auth_headers and server configured_api_key) so there's no asymmetry where
     the client sends "Bearer " (empty) and the server treats blank as disabled.

  7. CI vs DEPLOYED CONFIG. CI does not set the key, so CI exercises the
     auth-DISABLED path; the deployed config is auth-ENABLED. Is the enabled path
     covered well enough by unit tests that CI green ⇒ prod-config safe? Note any
     gap.

For each finding: P0/P1/P2/NIT, with a failing test or a concrete repro.
```

---

## Prompt 3 — Staff engineer (invariants, operability, rollback)

```
You are a staff engineer reviewing PR #103 for system-level posture, not local
correctness. Your concern is: is this safe to run publicly, discoverable by the
next engineer, and reversible?

Repository: https://github.com/d41689/ValuePilot
Branch: claude/rate-guard-public-auth (merged a4a927a)
Read first:
  - docs/tasks/2026-07-07_rate-guard-public-auth.md and the review-prompts doc's
    "out-of-repo operational changes" section
  - AGENTS.md ("Critical invariants", "Deferred work", "When to stop and ask")
  - docs/BACKLOG.md
  - rate-guard/README.md (public-exposure section)

Review:

  1. REPO ↔ REALITY DRIFT. The actual public exposure lives OUTSIDE the repo:
     ~/.cloudflared/config.yml, a Cloudflare DNS record, and host .env secrets.
     The repo only hints at it (README). How does a future engineer discover that
     rate-guard.richmom.vip exists and is a public egress proxy? Is the README
     section sufficient, or is an in-repo runbook / infra manifest needed? Is the
     tunnel/DNS state captured anywhere version-controlled?

  2. ROLLBACK COUPLING (important). Reverting this PR removes the auth middleware
     AND restores the 0.0.0.0 bind on the next deploy — but the cloudflared
     ingress + DNS route still exist. So a code-only rollback RE-OPENS an
     unauthenticated public proxy. Document the correct rollback order (tear down
     the tunnel route FIRST). Should the code and the exposure be coupled so one
     can't exist without the other?

  3. FAIL-OPEN AS A DESIGN CHOICE. Auth is opt-in (disabled when no key). That
     keeps CI/internal use frictionless but means the public deployment's safety
     depends on an env var being present. Weigh this against a fail-closed design
     for the public path. Is "opt-in" the right default for a service that is now
     internet-reachable? (Cross-check the security reviewer's finding #1.)

  4. SECRET LIFECYCLE. One static shared key for dev + prod + the remote machine,
     no expiry. Is there a documented rotation/revocation procedure (edit
     canonical .env → redeploy → update the remote machine), and what's the
     window where old/new keys must both be accepted? What's the blast radius and
     detection story if the key leaks (e.g., committed by accident, logged, shared
     in chat)?

  5. DEFERRED-WORK DISCIPLINE. The dev-stack 401 side effect is known but was NOT
     recorded in docs/BACKLOG.md. Per AGENTS.md, should it be? Is it correctly
     classified as dev-only (not a "production breakage" that must stop-and-tell)?
     Are there other discovered-but-deferred items (e.g., no auth-layer rate
     limiting, single shared key) that belong in the backlog with severity?

  6. OBSERVABILITY. There is no metric/alert for auth failures or for "public
     traffic hitting rate-guard". If someone brute-forces or the key leaks, how
     would the operator notice? Recommend the minimum monitoring (401 rate,
     source-IP via CF, a CF WAF rate rule) commensurate with the new exposure.

  7. PROCESS. Confirm AGENTS.md alignment: test-first evidence in the branch
     history; canonical CI green pre-merge; the merge-to-main = auto-deploy-to-prod
     coupling was acknowledged; the PR body names the security-critical rollout
     ordering (expose only after auth verified live). Flag any step that was
     asserted but not evidenced.

For each item: recommend ENFORCE (block/hotfix), DEFER (backlog entry with
severity + text), or ACCEPT (with rationale). Abstract critique without a
concrete next step is not actionable.
```

---

## How to consume the results

Collect all three agents' findings into
`2026-07-07_rate-guard-public-auth-review-results.md`, grouped by severity.
Because the PR is **already merged and deployed**:

- **P0** — hotfix immediately (new branch → PR → merge → the auto-deploy applies
  it). The most likely P0 is a fail-open / bypass finding from Prompt 1.
- **P1** — schedule a same-week follow-up PR.
- **P2 / NIT** — `docs/BACKLOG.md` with a link to the results doc.

If any P0/P1 lands, re-run the gates before re-deploying:

```
# rate-guard suite (containerized, per rate-guard/README.md)
docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim \
  sh -c "pip install -q -r requirements-dev.txt && pytest -q"
# backend + frontend canonical CI
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

Then re-verify the live surface: `/v1/fetch` no-key → 401, with-key → 200, both
on `127.0.0.1:9099` and `https://rate-guard.richmom.vip`.
