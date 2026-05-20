# Review result — readiness ops health false alarm + worker shutdown

Date: 2026-05-20
Branch reviewed: `claude/fix-readiness-ops-health-worker-shutdown`
Prompt: `docs/tasks/2026-05-20_readiness-ops-health-worker-shutdown-review-prompts.md`

## Verdict

批准。No blocking findings.

The frontend false-alarm fix matches the real `operationsHealth` signature, the
prod-style `exec uvicorn` command boots and shuts down cleanly, and the stale
heartbeat reaper is conservative enough to avoid stopping live workers.

## A. Frontend — `operationsHealth`

1. **Call site: pass.** `readiness/page.tsx` now calls
   `operationsHealth(readiness, [], hasAvailableWorker, { workersIndeterminate:
   workersQuery.isError })`, matching the real JS signature
   `(readiness, tasks, hasAvailableWorker, options = {})`.
2. **Type declaration honesty: pass.** The inline declaration now models four
   positional args and the real level union:
   `'healthy' | 'blocked' | 'attention' | 'unknown'`. The page-read fields
   `level`, `tone`, `label`, and `summary` are present. The previous
   impossible `'warning'` level is gone.
3. **Only consumer: pass.** Full frontend grep found only the readiness page
   calls `operationsHealth`; other `thirteenfAdmin` consumers import different
   helpers.
4. **Alarm actually clears: pass.** Logic trace and containerized node probe:
   with no setup blockers/tasks and `hasAvailableWorker=true`, the helper
   returns `level: 'healthy'` and no `"no active worker heartbeat"` reason.
   With `hasAvailableWorker=false`, it still returns `level: 'blocked'` with
   `"no active worker heartbeat"`. With `workersIndeterminate=true`, it returns
   `level: 'unknown'`, not blocked.

## B. Backend — prod compose `exec`

5. **Prod still boots / SIGTERM clean shutdown: pass.** `docker compose -f
   docker-compose.prod.yml config` parses the folded scalar into a valid
   `sh -c` command:
   `alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port
   8000`. The `&&` preserves fail-fast behavior: alembic must succeed before
   `exec`; if alembic fails, uvicorn is not reached and the container exits
   non-zero. A prod-style run against the dev DB confirmed uvicorn starts as
   server process `1`; `docker stop` produced normal uvicorn shutdown logs
   (`Shutting down`, `Waiting for application shutdown`, `Application shutdown
   complete`, `Finished server process [1]`). With
   `THIRTEENF_JOB_WORKER_ENABLED=true`, the latest worker heartbeat row was
   written as `status='stopped'` after `docker stop`, proving FastAPI lifespan
   shutdown reached `job_worker.stop()`.
6. **Grace period: pass / advisory.** Docker's default 10s grace period is
   enough for the common idle path: shutdown calls `scheduler.shutdown(wait=False)`
   and `job_worker.stop(timeout=5.0)`. Setting an explicit
   `stop_grace_period: 15s` would make the contract clearer, but I do not see
   evidence that the current default truncates the idle shutdown.
7. **Other entrypoints: pass / advisory.** Dev compose uses exec-form
   `["uvicorn", ...]`, so it does not have the same shell PID 1 bug. The
   backend Dockerfile still has a `CMD` with `--reload`; prod/dev compose
   override it, so this is out of scope, but it is worth cleaning up later so
   the image default is not development-flavored.

## C. Backend — stale heartbeat reaper

8. **Query correctness: pass.** The reaper filters
   `worker_id != current_worker_id`, `status != 'stopped'`, and
   `last_heartbeat_at < now - stale_window`. It uses timezone-aware UTC `now`;
   the model column is `DateTime(timezone=True)`, so the comparison is sound.
9. **Concurrency: pass.** On deploy overlap, the incoming worker only reaps
   other workers whose last heartbeat is already older than the 90s stale
   window. A still-alive outgoing worker beating every poll interval remains
   newer than the cutoff and is spared.
10. **`stopped` vs delete: pass.** Downstream already treats old non-stopped
    rows as computed `stale`; flipping them to `stopped` is less destructive
    than deleting and works with existing worker history UI. `visibleWorkerRows`
    hides stopped rows by default and has tests for that behavior.
11. **One-shot reap: pass / accepted tradeoff.** Startup-only reaping means a
    mid-run killed worker's stale heartbeat is cleaned on the next worker
    restart, not immediately. Given the target clutter was deploy-created rows
    and deploys restart the worker, this is acceptable. Periodic reaping can be
    a follow-up if stale history grows outside deploys.
12. **Isolation: pass.** `_run()` wraps the startup reap in `try/except`, calls
    `session.rollback()` on failure, logs a warning, closes the session, and
    continues into the worker loop.
13. **Test adequacy: pass.** The new tests cover stale idle/running rows,
    sparing the current worker, sparing fresh rows, and leaving already-stopped
    rows alone. Material gaps are minor: no explicit custom `now` /
    `stale_after_seconds` override test, but the production path is covered by
    the default stale window.

## D. Diagnosis & scope

14. **Churn is not a fault: pass with evidence caveat.** The reviewer session
    cannot independently inspect prod container history, but the task log
    records live prod/API inspection and states recreation timestamps matched
    successful Deploy Prod runs 1:1. Repo evidence supports the cadence model:
    `.github/workflows/deploy.yml` runs Deploy Prod after successful CI on
    `main`, and CI itself runs on push. I would not block on this.
15. **Existing 25 rows: pass.** No migration/manual deletion is required.
    Leaving them until the next deployed worker startup is safe: they only
    affect worker-history clutter, and the reaper flips them to `stopped`.
16. **Task docs: pass.** The task log and ops-audit item #1 accurately describe
    the frontend arg-shape bug, prod shell/exec shutdown issue, startup reaper,
    verification results, and next-deploy cleanup behavior.

## Verification run

- `docker compose run --rm api sh -lc "alembic upgrade head && pytest -q"` —
  passed, 868 tests, 3 SQLAlchemy legacy warnings.
- `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'` —
  passed, 152 tests.
- `docker compose run --rm --no-deps web npm run lint` — passed, no ESLint
  warnings/errors.
- `docker compose run --rm --no-deps web sh -lc 'NODE_ENV=production npm run
  build'` — passed.
- Prod-style boot/SIGTERM probe — passed as described in B5.

## Advisory notes

- Local ignored `.env.prod` currently shows the worker disabled, while later
  runbook docs say the runner's deploy-time `~/.config/valuepilot/.env.prod`
  has it enabled. This is not a code blocker because deploy installs runner
  env files before running the prod stack, but the local ignored file can
  mislead future reviewers.
- Consider adding `stop_grace_period: 15s` to `docker-compose.prod.yml` for a
  more explicit shutdown budget.
