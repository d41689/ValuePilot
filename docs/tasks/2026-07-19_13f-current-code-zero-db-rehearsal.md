# Current-code 13F zero-database rehearsal

Date: 2026-07-19
Branch: `codex/13f-daily-continuity`
Status: verified

## Goal

Prove that the current codebase can start from an empty, isolated database and
an empty EDGAR raw-document directory, seed the confirmed manager universe, run
the complete unattended 13F pipeline, and produce correct product data without
manual data repair.

## Acceptance criteria

- [x] The active `.env` contains the complete unattended 13F configuration and
      no required setting is silently supplied only at the command line.
- [x] A new database and independent EDGAR raw-document directory are used;
      existing dev, test, rehearsal, and production data are not read or
      modified.
- [x] Migrations and manager seeding happen automatically at container startup.
- [x] Every report quarter from the `2022-Q4` warm-up baseline through the
      latest scoreable quarter completes the six-stage pipeline; audited
      product history begins at `2023-Q1`.
- [x] Daily sync bootstraps the current filing window and retry/watchdog paths
      are enabled.
- [x] All database, filing-lineage, amendment, holdings, enrichment, ownership
      change, Oracle's Lens, and product-query invariants pass.
- [x] The 82-manager Dataroma reconciliation is rerun against the isolated
      result and every discrepancy is classified; any ValuePilot defect is
      fixed in code and proved again from zero.
- [x] API and browser product surfaces are verified against the isolated data.
- [x] All canonical Docker CI commands pass after the final watchdog repair.

## Scope

### In

- Local deployment configuration and production example configuration.
- Empty-database production-topology rehearsal using live EDGAR access through
  Rate Guard and live OpenFIGI enrichment.
- Defects discovered in the automatic ingestion, normalization, linkage,
  scoring, history, or 13F presentation paths.
- Durable audit evidence and runbook corrections discovered by the rehearsal.

### Out

- Changes to the real production database or production deployment.
- Manual edits to rehearsal business data, manual ingestion, or manual
  reconciliation used as a substitute for the automatic path.
- Commit, push, or pull-request creation unless requested separately.

## Files expected to change

- `.env` (gitignored local configuration; secrets never recorded here)
- `.env.prod.example`
- `backend/alembic.ini`
- `backend/alembic/env.py`
- `backend/test_support/database_isolation.py`
- `backend/tests/conftest.py`
- `backend/tests/unit/test_pytest_database_isolation.py`
- `docs/tasks/2026-07-19_13f-current-code-zero-db-rehearsal.md`
- 13F implementation/tests only when the rehearsal exposes a defect
- `docs/audits/**` and `docs/BACKLOG.md` when findings require them

## Test plan

1. Start an isolated production-topology compose project with a unique database,
   ports, and raw-document directory.
2. Observe startup migration/seed/reconciliation and let scheduled jobs finish;
   do not invoke data-repair CLI commands.
3. Run the invariant audit and 82-manager Dataroma reconciliation in-container.
4. Verify API responses and the five 13F manager tabs in a browser.
5. If a defect is found: add a failing test, fix it, destroy/recreate only the
   isolated rehearsal database and raw directory, and repeat from step 1.
6. Closing gate, verbatim:

       docker compose up -d --build
       docker compose exec -T api alembic upgrade head
       docker compose exec -T api pytest -q
       docker compose exec -T web sh -lc 'node --test lib/*.test.js'
       docker compose exec -T web npm run lint
       docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'

## Decision and sign-off log

- 2026-07-19: The proof standard is current code from an empty isolated database,
  not convergence of an already-populated dev database.
- 2026-07-19: Manual business-data correction is prohibited. Infrastructure
  setup (database creation, migration, container startup) and read-only audits
  are allowed.
- 2026-07-19: Audited history begins at `2023-Q1`; ingestion begins one quarter
  earlier at `2022-Q4` so Q1 Buy/Add/Reduce/Sell classifications have a complete
  prior-quarter baseline.
- 2026-07-19: The first rehearsal exposed a real unattended-path defect: late
  filings routed to older report quarters only emitted an operator warning,
  leaving quality, ownership changes, and Lens data stale. A regression now
  requires automatic recomputation of the restated quarter and any already-
  materialized following quarter.
- 2026-07-19: The second rehearsal proved the recompute fix on live SEC data:
  `2023-Q1` routed three filings to `2022-Q4`, ran three visible
  `pipeline_recompute` child jobs, finished green, and left no stale quarter.
- 2026-07-19: The second rehearsal also exposed a completion-contract loop.
  Four valid but extremely late filings had explicit quarter-end dates and were
  correctly routed/recomputed, while the preserved
  `PERIOD_SUSPICIOUSLY_STALE` review signal made the parent partial forever.
  Startup reconciliation would enqueue that deterministic quarter on every
  reboot. Routing now records routed-vs-unrouted reviews separately; only a
  fully-routed review with zero fetch/parse/quarantine failures and complete
  dependent recomputes counts as terminal coverage. Ambiguous/unrouted reviews
  still fail closed.
- 2026-07-19: The third rehearsal exposed a real lease-heartbeat concurrency
  defect. The heartbeat used its own Session but dereferenced the main
  Session-attached `JobRun` inside the background thread; commit expiry caused
  SQLAlchemy to issue concurrent SQL on the worker Session and raise
  `InvalidRequestError`. The thread now captures only scalar `job_id` and
  `lease_token` before it starts. A timing-independent regression prevents any
  thread-side ORM dereference.
- 2026-07-19: The fourth rehearsal completed all historical and daily jobs and
  exposed five terminal `13F-NT` coverage filings still persisted as
  `parse_status='pending'`. The API result said succeeded, but notices have no
  information table and therefore no later phase that could advance the stored
  state. Cleanly-routed NT-family filings now persist `succeeded`; HR-family
  filings remain pending until their information table parse. The NT/detail/
  ingest regression set passes 29 tests.
- 2026-07-19: A complete read-only Dataroma reconciliation on the fourth
  rehearsal compared all 82 managers: 80 mapped, Bridgewater and Daily Journal
  explicitly unmapped, zero fetch failures, 6,002 classified evidence items,
  zero suspected ValuePilot defects, and zero unclassified material
  differences. Evidence: `docs/audits/2026-07-19_13f-zero-db-dataroma-reconciliation.json`.
- 2026-07-19: The final rehearsal found an infrastructure configuration defect
  rather than a data-parser defect: this Mac's `.env` pointed at a public Rate
  Guard tunnel whose origin was down, while the one shared local Rate Guard
  container was not running and `.env` lacked the service's required
  `SEC_CONTACT_EMAIL`. The existing EDGAR User-Agent contact was copied into the
  dedicated setting without exposing it, `RATE_GUARD_URL` was corrected to the
  shared Docker-network service, and `docker-compose.rateguard.yml` was started.
  The same isolated database then recovered its three incomplete historical
  quarters through startup reconciliation; no business row was manually edited.
- 2026-07-19: The recovered historical chain has meaningful coverage for all 14
  quarters from `2022-Q4` through `2026-Q1`. The first hard audit found 82/82
  confirmed managers, 1,204 filings, 86,881 holdings, 0 pending filings, 0
  duplicate/zero-active filing groups, 0 missing acceptance timestamps, 0
  orphan/non-current parse-run holdings, 0 frozen amendment ordering, and 0
  attribution violations. The five daily dates affected by the tunnel outage
  remain deliberately visible until the next hourly scheduler retry.
- 2026-07-19: Browser acceptance on the isolated production topology verified
  all 82 managers and all five Duan Yongping views. His `2026-Q1` surface shows
  19 common positions, `$20B`, top-five concentration `87.13%`, 14 history rows,
  and no browser warning/error. Holdings, Activity, Buys, Sells, and History
  each rendered the expected table and URL state.
- 2026-07-19: A focused live Dataroma reconciliation for Duan Yongping compared
  Holdings / Activity / Buys / Sells / History with zero suspected ValuePilot
  defects and zero unclassified material differences. Its four evidence items
  are three intentional CRWD 4-for-1 split-adjustment differences plus the
  locked pre-`2023-Q1` history boundary. The persisted SEC InfoTable and raw XML
  both say CRWD value `3,904,100`, shares `10,000`; Dataroma retroactively shows
  `40,000` shares and one-quarter price while leaving value unchanged. Evidence:
  `docs/audits/2026-07-19_duan-zero-db-dataroma-reconciliation-final.json`.
- 2026-07-19: Closing gates so far: compose build/start, migrations, 198 frontend
  tests, lint, production build, and 36 Rate Guard tests pass. The full backend
  suite passes 1,321 tests on the migrated isolated PostgreSQL test database.
  The verbatim backend command against the populated shared dev database
  reproduces the pre-existing test-isolation defect already recorded at the top
  of `docs/BACKLOG.md`; it was stopped after widespread fixture-state failures
  to avoid clearing or mutating developer data.
- 2026-07-19: No daily job was invoked manually after Rate Guard recovery. At
  the next hourly scheduler tick, the system automatically retried all five
  workdays (`2026-07-13` through `2026-07-17`), completed five daily-index jobs,
  ingested three new accessions, and ran all six `2026-Q2` pipeline stages. All
  five sync dates are now `success` with `attempt_count=2`; there are no active
  jobs or failed job locks.
- 2026-07-19: The final hard audit on the untouched rehearsal result records
  82/82 confirmed managers, 1,209 filings, 87,027 holdings, 1,155 active
  filings, 81,610 ownership changes, and 7,934 Lens signals. It found zero
  pending filings or NT notices, missing acceptance timestamps, duplicate or
  zero-active filing groups, deferred filings, orphan/non-current parse-run
  holdings, enrichable unresolved holdings, frozen amendment ordering, or
  attribution violations. The ten pending amendment adjudications are expected
  review state and none is incorrectly active. Meaningful coverage is true for
  every quarter from `2022-Q4` through `2026-Q2`.
- 2026-07-19: The pre-daily Dataroma run was retained as a negative control: it
  correctly identified nine ValuePilot defects, exactly the three missing Q2
  surfaces for Guy Spier, Nick Train, and David Katz. After the unattended daily
  retry, each manager has zero Q2 ValuePilot defects and zero unclassified
  material differences. The final 82-manager report has 80 mapped managers,
  two explicitly unavailable on current Dataroma, zero fetch failures, 6,003
  fully classified differences, zero suspected ValuePilot defects, and zero
  unclassified material differences. Evidence:
  `docs/audits/2026-07-19_13f-zero-db-dataroma-reconciliation-final.json`.
- 2026-07-19: The remaining canonical-test gap was fixed rather than waived.
  `pytest` now generates a narrowly validated `valuepilot_pytest_<hex>` schema,
  sets PostgreSQL `search_path` to only that schema before importing the app,
  migrates it to Alembic head, disables unattended background work for the test
  process, and drops the schema on teardown. It refuses production, maintenance,
  non-PostgreSQL, and unsafe schema targets. A database assertion proves the
  running test session can resolve only the generated schema; post-run inspection
  found zero leaked pytest schemas. Programmatic Alembic migration also preserves
  application loggers so `caplog` remains effective.
- 2026-07-19: Pre-watchdog canonical closing gate, run verbatim and in order:
  fixes: compose build/start passed; migration passed; backend `1331 passed` in
  102.16 seconds with zero warnings; frontend `198 passed`; lint reported no
  warnings/errors; and the production build completed successfully. Rate Guard
  remains green at 36 tests. `git diff --check` is clean, the isolated API health
  endpoint is `ok`, and both compose configurations validate.
- 2026-07-19: The completion audit then observed a real process-interruption
  recovery gap in the populated dev runtime: a synchronous pipeline child was
  stranded as `running` without a lease when hot reload killed its parent
  process. Existing recovery only considered rows with an expired non-null
  lease, so this child could hold its unique lock forever. A red regression now
  covers both sides of the boundary: a lease-less scoring stage at 61 minutes is
  failed and unlocked, while the same stage at 59 minutes remains running under
  its one-hour job-type timeout. The watchdog repair passes the scheduler,
  alignment, and health regression set (48 tests).
- 2026-07-19: Final post-watchdog canonical closing gate was rerun verbatim and
  in order: compose build/start passed; migration passed; backend `1332 passed`
  in 103.80 seconds with zero warnings; frontend `198 passed`; lint reported no
  warnings/errors; and the production build completed successfully. The current
  API container registers `thirteenf_job_watchdog` and contains the lease-less
  recovery branch. The final inspection found zero leaked pytest schemas; the
  isolated rehearsal has zero active jobs, zero latest-failed locks, zero
  pending filings, and a healthy API. Both compose configurations validate and
  `git diff --check` is clean.
