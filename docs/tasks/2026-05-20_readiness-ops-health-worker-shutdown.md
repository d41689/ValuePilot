# 2026-05-20 — Readiness "operations blocked" false alarm + worker graceful shutdown

## Goal / Acceptance Criteria

- The `/admin/13f/readiness` "Operations Health" banner reflects the *real*
  worker state instead of permanently reading "operations blocked / no active
  worker heartbeat".
- The 13F worker shuts down gracefully on container stop so it records
  `status='stopped'` instead of leaving a `stale` zombie heartbeat row, and the
  ~25 existing zombie rows get reaped.
- Acceptance: canonical CI green; the readiness banner is accurate against a
  live healthy worker.

This is item #1 of `docs/tasks/2026-05-20_admin-13f-ops-audit.md`.

## Diagnosis

`/admin/13f/readiness` permanently shows "Operations need intervention — no
active worker heartbeat". Investigation (live admin API + prod container
inspection) found **no actual outage** — two real but separate bugs:

### Bug 1 — frontend: `operationsHealth()` called with the wrong arg shape

`frontend/lib/thirteenfAdmin.js` defines:

```js
function operationsHealth(readiness, tasks, hasAvailableWorker, options = {})
```

— four positional args. But `readiness/page.tsx` calls it with a single object
`operationsHealth({ readiness, tasks, hasAvailableWorker, workersIndeterminate })`.
So `hasAvailableWorker` arrives `undefined`, `!undefined === true`, and the page
**unconditionally** renders "no active worker heartbeat" / "operations blocked",
regardless of real worker health. A hand-written (and wrong) type declaration
for the JS module in `page.tsx` matched the bad call, so `tsc` never caught it;
the function's own unit tests use the correct positional form and pass, and the
page component has no test — so CI stayed green.

### Bug 2 — backend: worker never shuts down gracefully → zombie heartbeat rows

`docker-compose.prod.yml` starts the API with
`command: sh -c "alembic upgrade head && uvicorn ..."`. The shell is PID 1;
`uvicorn` is its child. On `docker stop` (every deploy recreates the container),
SIGTERM goes to PID 1 (`sh`), which does **not** forward it to `uvicorn`.
uvicorn never runs FastAPI's lifespan shutdown, so `job_worker.stop()` — which
records `status='stopped'` — never runs. After the 10s grace period Docker
SIGKILLs everything. Every deploy therefore abandons the worker's
`job_worker_heartbeats` row as `stale` forever. 25 such zombie rows had
accumulated, which is what made the dashboard look alarming.

The container churn itself is **not** a bug — it is the deploy cadence: every
push to `main` runs CI then `deploy.yml` → `docker compose up -d --build`.
Container-recreation timestamps match successful Deploy Prod runs 1:1.

## Scope

- **In:** the `operationsHealth` call site + its type declaration; the prod
  compose signal-forwarding fix; reaping stale heartbeat rows on worker start.
- **Out:** the deploy cadence; mid-job interruption recovery (already handled by
  the job lease / `mark_stale_running_jobs_abandoned`); the dev compose (its api
  command is already exec-form `["uvicorn", ...]`).

## Files to change

- `frontend/app/(dashboard)/admin/13f/readiness/page.tsx` — call
  `operationsHealth` positionally; correct the module type declaration
  (`level` union `'warning'` → `'attention'`).
- `docker-compose.prod.yml` — `exec uvicorn ...` so SIGTERM reaches uvicorn.
- `backend/app/services/thirteenf_job_worker.py` — add
  `reap_stale_worker_heartbeats()`; call it when the worker starts.
- `backend/tests/unit/test_13f_worker_heartbeat_reap.py` — new test.

## Test plan (Docker)

- `docker compose exec -T api pytest -q` — full backend suite, incl. the new
  reap test.
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` — frontend
  unit suite (`thirteenfAdmin.test.js` unchanged, must stay green).
- `docker compose exec -T web npm run lint`
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` — the
  TypeScript build is what now enforces the corrected `operationsHealth` type.

## Verification results (2026-05-20)

The prod stack occupies host ports 8101/3101, so `docker compose up` cannot
bind for the dev stack. Per the repo's established workaround (memory +
`2026-05-20_admin-13f-page-fixes.md`), the canonical commands were run verbatim
but via `docker compose run --rm` against the already-running dev `db` — full
suites, no narrowing:

- `docker compose run --rm api sh -lc "alembic upgrade head && pytest -q"` →
  migrations applied; **868 passed** (incl. the 2 new reap tests).
- `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'` →
  **152 pass / 0 fail**.
- `docker compose run --rm --no-deps web npm run lint` → no warnings/errors.
- `docker compose run --rm --no-deps web sh -lc 'NODE_ENV=production npm run
  build'` → success; the build's `tsc` pass now enforces the corrected
  `operationsHealth` signature.

## Review remediation (2026-05-20)

External review (`2026-05-20_readiness-ops-health-worker-shutdown-review-result.md`)
verdict: **approved, no blocking findings**. The reviewer independently
confirmed the prod-style `exec uvicorn` boots, that `docker stop` yields a clean
uvicorn shutdown, and that with the worker enabled the shutdown records
`status='stopped'`. Two advisory notes, both handled here:

- **`stop_grace_period`** — added `stop_grace_period: 15s` to the `api` service
  in `docker-compose.prod.yml`, making the shutdown budget explicit (margin
  over Docker's 10s default). No code path changes.
- **`.env.prod` worker-enabled confusion** — *no code change; intentional.* The
  repo-root `.env.prod` is git-ignored; the deploy installs the runner's
  `~/.config/valuepilot/.env.prod` (which enables the worker) before bringing
  the prod stack up, so the local file never reaches prod. The local copy can
  mislead a reviewer about the worker's prod state — noted here so the next
  reader does not re-derive it. Not fixable in-repo (the file is ignored).

## Sign-off trail

- 2026-05-20: diagnosis complete; branch `claude/fix-readiness-ops-health-worker-shutdown`.
- 2026-05-20: all four changes made; canonical CI green (see above). Fix takes
  effect on the next prod deploy — the reaper clears the ~25 existing zombie
  rows when the new worker starts; the `exec` change makes every subsequent
  deploy shut the worker down cleanly.
- 2026-05-20: external review approved (no blockers); `stop_grace_period: 15s`
  added per advisory; canonical CI re-run green.
