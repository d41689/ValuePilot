# Clean SEC gold-set acceptance environment

Status: Complete — Terra PASS

Owner: Product / Engineering

Date: 2026-08-30

## Goal

Provide a clean, repeatable acceptance-only environment for the locked SEC
financial gold set without reading from, migrating, stamping, deleting, or
otherwise modifying the shared development `valuepilot` database. Preserve the
distinction between the historical filing-selection cutoff and database-stamped
evidence acquisition/finalization time, and prepare stable machine-readable and
human-readable reports for the authorized Step D run.

This advances source-traceable owner-earnings research and disconfirmation: the
acceptance evidence can be independently replayed without inheriting unknown
development state, and missing coverage remains visible as typed gaps rather
than being obscured by a dirty database.

## Acceptance criteria

- A caller supplies an explicit validated run ID. It deterministically maps to
  one `valuepilot_acceptance_<run-id>` database on the shared PostgreSQL server
  and one repository-local `storage/sec_gold_acceptance/<run-id>` directory.
- Creation refuses a pre-existing database or storage target, creates an empty
  database owned by the existing `valuepilot` role, runs `alembic upgrade head`,
  and verifies exactly one Alembic head/current revision.
- The lifecycle never targets the shared `valuepilot`, `valuepilot_prod`,
  `postgres`, or template databases. Cleanup validates and removes only the
  exact derived acceptance database and storage directory, and is deterministic
  when retried.
- Application and Alembic execution remain in Docker. The acceptance database
  uses the existing shared PostgreSQL service, satisfying the AGENTS rule that
  forbids a project-local PostgreSQL service while isolating by database as the
  shared-infra contract prescribes.
- One authoritative preflight derives the exact database URL and storage path
  from the validated run ID. It rejects absent acceptance mode, any configured
  run/database/URL/live-database mismatch, missing/wrong/escaped/symlink
  storage, or any Rate Guard fallback before migrations, tests, ingestion,
  finalization, or reports can start.
- A later normal gold-case command uses the isolated database/storage and one
  configured Rate Guard endpoint. Step C does not make a real SEC request.
- `filing_selection_as_of` remains the locked historical selection boundary.
  `operation_attempted_at` and `evidence_available_at` are PostgreSQL-stamped
  current evidence boundaries. They are never caller-backdated, and newly
  fetched evidence is unavailable immediately before its availability marker
  and available at/after that marker.
- Stable JSON and human summaries expose run/case identity, selection cutoff,
  operation attempted/finalized/available times, expected completed fiscal
  years, selected accessions/forms, typed gaps/failures, lineage counts, and
  the `metric_facts` publication count.
- Local fake-client tests prove clean migration, PIT before/equal/after
  availability, no raw SEC publication to `metric_facts`, deterministic
  report output, and safe lifecycle planning/cleanup behavior.
- Every acceptance container verifies both its configured database name and
  PostgreSQL `current_database()` against the exact derived acceptance target
  before head verification. Lifecycle SQL addresses only `postgres` for
  create/drop and the derived acceptance database for migrations/tests.
- Read-only shared-development fingerprints record its revision/table count for
  visibility. They are not treated as exclusive write-audit evidence because
  unrelated shared services continue to update that database concurrently.

## Scope

### In

- Acceptance-only database/storage lifecycle and safety validation.
- Docker Compose override and operator commands for create, verify, future
  run-case/report, and exact cleanup.
- Database-stamped ingestion-operation attempt time.
- Stable per-case JSON and human report scaffolding.
- Fake-client, isolated-database, CLI/report, migration, and lifecycle tests.
- Acceptance architecture/operator documentation.

### Out

- Real SEC requests or the 24-company gold-set run (Step D).
- Any modification, migration, stamping, cleanup, or revision repair of the
  shared development `valuepilot` database.
- A project-local PostgreSQL service.
- Security testing, credentials probing, external probes, or adversarial SEC
  traffic.
- Canonical SEC-to-`metric_facts` publication.
- The full Step E closing gate.

## PRD and architecture references

- `AGENTS.md`
- `docs/architecture/parsing.md`
- `docs/architecture/data-layer.md`
- `docs/acceptance/financial_truth_beta_gold_set.yml`
- `docs/prd/value-pilot-prd-v0.1.md` §H
- `docs/tasks/2026-08-30_sec-submission-snapshot-decoupling.md`
- `/Users/dane/projects/infra/README.md`

## Planned files

- `docker-compose.acceptance.yml`
- `scripts/sec_gold_acceptance.sh`
- `scripts/test_sec_gold_acceptance_lifecycle.sh`
- `backend/app/acceptance/sec_gold_environment.py`
- `backend/app/acceptance/sec_gold_report.py`
- `backend/app/core/config.py`
- `backend/app/cli/sec_financials.py`
- `backend/app/services/sec_financial_ingestion.py`
- `backend/alembic/versions/20260830140000-sec-acceptance-timestamps.py`
- `backend/tests/unit/test_sec_gold_acceptance.py`
- `backend/tests/unit/test_sec_financial_cli.py`
- `backend/tests/unit/test_sec_financial_lineage.py`
- `backend/tests/unit/test_sec_financial_lineage_migration.py`
- `backend/test_support/database_isolation.py`
- `docs/acceptance/sec-gold-environment.md`
- `docs/architecture/parsing.md`
- `docs/prd/value-pilot-prd-v0.1.md`

## Test plan

1. Write failing timestamp, environment, report, fake-ingestion, and lifecycle
   regressions before production changes.
2. Run focused Docker tests for acceptance environment/report, SEC CLI, lineage,
   migration, source/egress guards, Rate Guard client, and Edgar client.
3. Exercise create → empty/head verification → fake acceptance → cleanup →
   cleanup retry using a disposable acceptance database and storage target.
4. Run isolated Alembic upgrade/downgrade/upgrade and verify one head.
5. Run `sh -n` on the lifecycle script, validate normal/acceptance Compose,
   compile backend code, and run `git diff --check`.
6. Record read-only shared-development fingerprints and an exact runtime
   acceptance-database identity assertion. Verify no disposable database or
   storage target remains after cleanup.

## Decisions and gotchas

- 2026-08-30: a schema inside `valuepilot` would still modify the drifted shared
  development database. The acceptance environment therefore uses a separate
  disposable database on the already-authorized shared PostgreSQL instance.
  This honors the shared-infra rule (no second Postgres service) and the stated
  isolation model (database plus role).
- 2026-08-30: the host lifecycle script only coordinates Docker processes. SQL,
  Alembic, application, and report execution occur inside containers.
- 2026-08-30: database and storage names are derived from one strict run-ID
  grammar. Cleanup never accepts a raw database name or arbitrary path.
- 2026-08-30: Step C uses only fake SEC clients. The normal Rate Guard-backed
  `run-case` command is scaffolding for Step D and is not invoked here.
- 2026-08-30: the shared development database remained at revision
  `20260828500000` with 68 public tables. Its cumulative table counters moved
  while this work ran because existing shared services remained active, so
  those non-exclusive counters cannot establish attribution. The acceptance
  proof instead checks the configured URL and live `current_database()` in
  every lifecycle verification; the observed target was exactly
  `valuepilot_acceptance_step_c_proof_02`. All final lifecycle migration and
  focused-suite commands ran through a verified acceptance environment.
- 2026-08-30: before the acceptance test harness was switched to the disposable
  database, early red/green integration tests used the repository's pre-existing
  temporary-schema isolation helper against `valuepilot`. Their own schemas
  were removed by test finalizers and they did not touch `public`, but this was
  still shared-database DDL and means the work session cannot truthfully claim
  zero shared-database mutation. The final harness now explicitly permits and
  uses only a strictly named acceptance database. Two other unknown
  `valuepilot_pytest_*` schemas remain in shared state and were deliberately not
  deleted or attributed to this task.
- 2026-08-30: the selection cutoff remains caller/manifest historical policy;
  the new database insert guard overwrites operation `attempted_at` and
  `created_at` with one PostgreSQL clock value. The existing separately
  committed availability marker is the finalization/availability boundary.
- 2026-08-30: Terra's first review found the lifecycle's database identity
  check was not an authoritative runtime preflight and the acceptance CLI could
  enter through a normal API environment. The corrected preflight is shared by
  lifecycle and CLI, validates the exact URL/live database/storage/mode/no-
  fallback contract, and runs before any write-capable command. The lifecycle
  ordering test records commands and proves a failed preflight invokes zero
  Alembic, pytest, or ingestion commands.

## Sign-off trail

- Test-first report/environment/timestamp regressions were written before their
  implementations. The new runtime identity regression was observed failing on
  its missing import before implementation.
- Disposable lifecycle `step-c-local-01`: empty create, upgrade to the single
  `20260830140000` head, focused suite **169 passed**, downgrade to
  `20260830130000`, upgrade back to the single head, destroy twice, recreate
  the same run ID from empty, and destroy twice all succeeded.
- Runtime-target lifecycle `step-c-proof-02` reported
  `acceptance_database_identity=valuepilot_acceptance_step_c_proof_02` and the
  single `20260830140000` head before exact cleanup.
- Final from-empty lifecycle `step-c-final-01` reported the exact runtime
  database identity, upgraded to the single head, ran the current focused suite
  with **170 passed**, completed the 140000 → 130000 → 140000 roundtrip, and
  succeeded at cleanup plus cleanup retry.
- Terra P1 verification lifecycle `step-c-preflight-01`: authoritative
  preflight succeeded before the first empty-database Alembic upgrade; the
  expanded isolated suite passed **183 tests**; each downgrade/upgrade leg
  preflighted and returned to the single head; validated destroy and destroy
  retry succeeded. Acceptance/CLI preflight regressions passed **51 tests** and
  the command-recorder lifecycle ordering test passed.
- Final Terra P1 lifecycle `step-c-preflight-02`: exact URL/storage/live-DB
  preflight ran before the empty-database upgrade and every later leg; the
  current isolated suite passed **185 tests**; the roundtrip returned to the
  single head; destroy and destroy retry passed. The standard-API CLI negative
  proves a valid run ID cannot open `SessionLocal` or write a report without the
  full configured acceptance runtime.
- Symlink-ancestry hardening rerun `step-c-preflight-03`: the final **185-test**
  focused suite passed in the isolated database, roundtrip returned to head,
  and validated destroy/retry left no database or storage. Storage validation
  rejects symlinks at the storage base, acceptance parent, or run target.
- Cleanup proof: zero databases matched
  `valuepilot_acceptance_step_c_%`; both exercised storage roots were absent.
- Post-refactor Docker checks: acceptance/report plus source/egress guards
  **19 passed**; backend acceptance/CLI/service compile succeeded; normal and
  acceptance Compose configuration validation, `sh -n`, and
  `git diff --check` succeeded.
- No real SEC request, external probe, security test, shared-development
  migration, full gold-set run, or full Step E closing gate was performed.
- Terra Step C re-review: **PASS — no actionable in-scope findings**.
- Approved as a self-contained Step C commit after final identity/status/diff
  verification; no real SEC request or Step D execution was included.
