# Review prompt — readiness "operations blocked" false alarm + worker graceful shutdown (2026-05-20)

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the task log
`docs/tasks/2026-05-20_readiness-ops-health-worker-shutdown.md` and the audit
that spawned it, `docs/tasks/2026-05-20_admin-13f-ops-audit.md` (item #1).

---

## Reviewer brief

You are reviewing branch **`claude/fix-readiness-ops-health-worker-shutdown`**.
It came out of investigating why `/admin/13f/readiness` permanently shows
"Operations need intervention — no active worker heartbeat / operations
blocked". The investigation concluded there was **no outage** — the worker was
healthy throughout (live API showed heartbeat age ~1s). The branch fixes two
unrelated real bugs plus the resulting data clutter. Your job: confirm these
changes are correct, complete, and safe — and challenge the diagnosis itself.

The **highest-risk** change is `docker-compose.prod.yml` — it alters how the
**production API container boots**. If wrong, prod does not start. Treat B5 as
mandatory.

The fix is **not deployed**; `https://invest.richmom.vip/admin/13f/readiness`
still shows the old (always-blocked) behaviour. Verify by reading code and
running the built app locally, not against prod.

### Files in scope

- `frontend/app/(dashboard)/admin/13f/readiness/page.tsx` — `operationsHealth`
  call site + the hand-written type declaration for the `thirteenfAdmin` JS module
- `docker-compose.prod.yml` — the `api` service `command`
- `backend/app/services/thirteenf_job_worker.py` — new
  `reap_stale_worker_heartbeats()`; called at the top of `ThirteenFJobWorker._run()`
- `backend/tests/unit/test_13f_worker_heartbeat_reap.py` — new tests
- `docs/tasks/2026-05-20_readiness-ops-health-worker-shutdown.md` — task log
- `docs/tasks/2026-05-20_admin-13f-ops-audit.md` — audit tracker (item #1)

### Baseline

`git diff main...HEAD`. Pre-change versions via `git show main:<path>`. The
unchanged function under review is `operationsHealth` in
`frontend/lib/thirteenfAdmin.js` (4 positional params) and its existing tests
in `frontend/lib/thirteenfAdmin.test.js`.

### The diagnosis to verify

1. Frontend: `readiness/page.tsx` called `operationsHealth({ ...object })`, but
   the function takes 4 **positional** params `(readiness, tasks,
   hasAvailableWorker, options)`. So `hasAvailableWorker` was always `undefined`
   → `!undefined === true` → the page unconditionally reported "operations
   blocked". A wrong hand-written type declaration hid it from `tsc`.
2. Backend: `docker-compose.prod.yml` ran uvicorn as `sh -c "alembic ... &&
   uvicorn ..."` — the shell is PID 1, uvicorn its child. `docker stop` sends
   SIGTERM to PID 1; the shell does not forward it; uvicorn is SIGKILL'd after
   the grace period, so FastAPI's lifespan shutdown (`job_worker.stop()`, which
   records `status='stopped'`) never runs. Every deploy leaks a `stale`
   heartbeat row; 25 had accumulated.
3. The container churn itself is the deploy cadence (every `main` push →
   `deploy.yml`), not a fault — recreation timestamps match successful Deploy
   Prod runs 1:1.

## Answer every question with a verdict + evidence

### A. Frontend — the `operationsHealth` fix

1. **Call site.** The new positional call
   `operationsHealth(readiness, [], hasAvailableWorker, { workersIndeterminate })`
   matches the real signature in `frontend/lib/thirteenfAdmin.js` exactly —
   argument order and the `options` object shape.
2. **Type declaration honesty.** The corrected inline type in `page.tsx` must
   match the *actual* JS function. Confirm the `level` union — the function
   returns `'unknown' | 'blocked' | 'attention' | 'healthy'`; the old type said
   `'warning'` (never produced). Confirm no other field the page reads
   (`tone`, `label`, `summary`, `level`) is mistyped.
3. **Only consumer.** Grep the whole frontend for other `operationsHealth` call
   sites. Confirm the readiness page is the only one — i.e. no other page is
   silently mis-calling it the same way.
4. **It actually fixes the alarm.** Trace `operationsHealth` for
   `hasAvailableWorker = true`: it must NOT push "no active worker heartbeat"
   and must NOT return `level: 'blocked'` on that account. And for genuinely no
   worker (`false`) it must still block. The page component has no unit test —
   state how you convinced yourself (logic trace and/or running the built app).

### B. Backend — prod compose `exec` (highest risk)

5. **Prod still boots (MANDATORY).** Confirm `sh -c "alembic upgrade head &&
   exec uvicorn ..."` is correct: `alembic upgrade head` runs first; on success
   `exec` replaces the shell with uvicorn so uvicorn becomes PID 1 and receives
   SIGTERM directly; on alembic failure the `&&` short-circuits, `exec` is not
   reached, the container exits non-zero and the restart policy retries. Verify
   the YAML `>` folded scalar still produces a valid single command. If feasible,
   bring the prod-style command up and confirm SIGTERM triggers a clean
   shutdown (logs show "13F admin job worker stopped").
6. **Grace period.** Docker's default `stop_grace_period` is 10s. FastAPI
   shutdown drains connections, then `scheduler.shutdown(wait=False)` and
   `job_worker.stop(timeout=5.0)`. Is 10s comfortably enough for the common
   (idle worker) case? Should the compose set an explicit `stop_grace_period`?
   Advisory unless you find it actually truncates shutdown.
7. **Other entrypoints.** Confirm the dev `docker-compose.yml` `api` does NOT
   have the same bug (it uses exec-form `["uvicorn", ...]`, no shell). Note —
   advisory — that `backend/Dockerfile`'s `CMD` carries `--reload`; out of
   scope, but say whether it should be flagged.

### C. Backend — `reap_stale_worker_heartbeats`

8. **Query correctness.** The reaper marks rows `stopped` where: `worker_id !=
   current`, `status != 'stopped'`, `last_heartbeat_at < now - stale_window`.
   Confirm each clause and that the timezone-aware comparison is sound.
9. **Concurrency.** During a deploy the outgoing and incoming containers
   briefly overlap. The incoming worker reaps on startup. Confirm it cannot
   reap a *still-alive* worker: a worker is only reaped once its heartbeat is
   already older than the stale window (90s) — i.e. provably dead. Walk through
   the overlap window and confirm there is no race that stops a live worker.
10. **`stopped` vs delete.** The reaper sets `status='stopped'` rather than
    deleting. Confirm `stopped` rows are handled correctly downstream —
    `pick_worker_rows` / the workers dashboard — and that 25 rows flipping to
    `stopped` at once does not surface oddly.
11. **One-shot reap.** It runs once at worker startup. Stale rows created
    *later* (a mid-job-killed worker) are not reaped until the next restart.
    Given every deploy restarts the worker, is that acceptable, or should
    reaping also run periodically?
12. **Isolation.** The reap call in `_run()` is wrapped in try/except with
    rollback — a reap failure must never block the worker loop from starting.
    Confirm.
13. **Test adequacy.** `test_13f_worker_heartbeat_reap.py` covers reaping dead
    rows and sparing fresh/already-stopped rows. Anything material missing
    (e.g. the current worker's own row, the `now` / `stale_after_seconds`
    overrides)?

### D. Diagnosis & scope

14. **Churn is not a fault.** Challenge claim #3 — is "container recreation ==
    deploy cadence" actually supported, or could something else recreate the
    container? (Reviewer need not have prod access; judge whether the evidence
    in the task log is sufficient.)
15. **Existing 25 rows.** The fix relies on "the next deploy's worker reaps
    them". Confirm nothing needs the rows cleared sooner, and that no separate
    migration/manual step is being silently assumed.
16. **Task docs.** `2026-05-20_readiness-ops-health-worker-shutdown.md` and the
    `#1` entry + sign-off in `2026-05-20_admin-13f-ops-audit.md` accurately
    describe what shipped.

## Verification

The prod stack occupies host ports 8101/3101, so the dev stack cannot be
brought up with `docker compose up`; run the canonical suites via
`docker compose run --rm` against the running dev `db`:

- `docker compose run --rm api sh -lc "alembic upgrade head && pytest -q"`
- `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'`
- `docker compose run --rm --no-deps web npm run lint`
- `docker compose run --rm --no-deps web sh -lc 'NODE_ENV=production npm run build'`
- Plus the prod-boot / SIGTERM check in B5.

## Pass bar

Approve only if: **B5 holds** (prod boots and SIGTERM yields a clean worker
shutdown); A1–A4 confirmed (the call matches the signature, the type is honest,
the readiness page is the only consumer, the alarm genuinely clears); C8–C13
hold (reaper query correct, no live-worker race, isolated, adequately tested);
the diagnosis (D14–D15) is sound. B6, B7 are advisory. The bar is "these three
fixes are correct and safe and the diagnosis holds" — not "the readiness page
is bug-free".
