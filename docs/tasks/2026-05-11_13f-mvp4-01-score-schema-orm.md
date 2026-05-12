# 13F MVP4-01: Oracle's Lens Score Schema and ORM

## Status

Authorized to start (delegated 2026-05-11). Pre-start conditions all
resolved in
`docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` § "MVP4-01 Pre-Start
Condition Resolutions".

## Goal / Acceptance Criteria

Land the schema, ORM models, and migration that the MVP4 scoring
services (MVP4-02 through MVP4-06) write into. No score computation,
no API, no frontend in this task.

Acceptance criteria:
- New table `oracles_lens_signals` exists with:
  - Primary key `id` (BigInteger autoincrement).
  - `stock_id BIGINT NOT NULL` (FK → `stocks.id`).
  - `report_quarter VARCHAR(10) NOT NULL` (e.g. `2024-Q3`).
  - `quarter_end_date DATE NOT NULL`.
  - `score_version VARCHAR(20) NOT NULL` (e.g. `v1.0`); pre-resolved
    in the gate's D5 / Pre-Start Condition Resolutions block.
  - `raw_consensus_count INT NOT NULL` (plan §7.1).
  - `signal_weighted_consensus_score NUMERIC(18,6) NULL`
    (plan §7.2; NULL when score_confidence == "unavailable").
  - `conviction_score NUMERIC(18,6) NULL` (plan §7.9).
  - `distinctive_consensus_score NUMERIC(18,6) NULL`
    (plan §7.11; advanced sort).
  - `add_intensity NUMERIC(18,6) NULL` (plan §7.4).
  - `holding_streak_quarters INT NULL` (plan §7.10).
  - `score_confidence VARCHAR(20) NOT NULL` (plan §7.12; one of
    `high` / `medium` / `low` / `unavailable`; same vocabulary as
    `ownership_signal_confidence_levels`).
  - `caution_flag_codes JSONB NULL` (per-row codes per plan §7.13;
    canonical readiness vocabulary + score-service-emitted
    row-level codes per D3 caveat propagation rules a–e and the
    MVP4-05 surface note).
  - `score_explanation JSONB NULL` (composite summary surfaced in
    main ranking table; component detail lives in
    `oracles_lens_score_components`).
  - `computed_at TIMESTAMPTZ NOT NULL`.
  - `source_job_id BIGINT NULL` (FK → `job_runs.id`; the JobRun
    that produced this row).
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
  - `updated_at TIMESTAMPTZ NOT NULL DEFAULT now() ON UPDATE`.
  - UNIQUE constraint on `(stock_id, report_quarter, score_version)`.
  - Indexes on `(report_quarter, score_version)` and
    `(score_version, signal_weighted_consensus_score DESC)`
    (primary ranking query path).
- New table `oracles_lens_score_components` exists with:
  - Primary key `id`.
  - `score_id BIGINT NOT NULL` (FK → `oracles_lens_signals.id`,
    `ON DELETE CASCADE`).
  - `component_name VARCHAR(80) NOT NULL`
    (e.g. `manager_signal_weight`, `position_signal_weight`,
    `holding_streak_bonus`, `recent_action_adjustment`).
  - `manager_id BIGINT NULL` (FK → `institution_managers.id`;
    NULL for aggregate components like overall raw consensus).
  - `numeric_value NUMERIC(18,6) NULL`.
  - `string_value VARCHAR(120) NULL` (for categorical components
    like normalized `manager_type`).
  - `evidence_json JSONB NULL` (e.g. for caution-flag-derived
    component demotions: which caveat caused the demote).
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
  - UNIQUE on `(score_id, component_name, manager_id)`
    (`manager_id` may be `NULL` — confirm Postgres null semantics
    or add a unique partial index for the aggregate-row case).
  - Index on `(score_id, component_name)`.
- `JOB_RUN_STATUSES` enum unchanged; new `JOB_TYPE` value
  `oracles_lens_score_backfill` documented in code constants for
  future MVP4-02/-03/-04/-05/-06 services to reuse.
- Alembic revision filename follows
  `backend/alembic/versions/YYYYMMDDHHMMSS-mvp4_01_oracles_lens_score_schema.py`.
- Migration applies cleanly from current head and rolls back cleanly
  on `alembic downgrade -1`.
- ORM model files added under `backend/app/models/` (or extend
  `institutions.py` if that file's pattern fits — TL call during
  implementation review).
- A `score_version` constant exposed in
  `app/services/oracles_lens/constants.py` (the typed Python config
  module from D5) so MVP4-02 onward writes the same version label
  consistently.
- No score computation, no API endpoint, no frontend work in this
  task.
- Relevant migration + model tests pass in Docker.

## Pre-Start Decisions (Authorized 2026-05-11)

1. **Storage = precomputed `oracles_lens_signals` table.** Not
   column extensions on `holdings_13f` / `ownership_changes`.
   Rationale: MVP3-06 no-mutation principle + clean
   `score_version` lifecycle.
2. **JobRun integration =** `job_type='oracles_lens_score_backfill'`,
   `lock_key=f"oracles_lens_score:{period}:{score_version}"`, one
   `JobRun` row per recompute. (Codified here so the FK reference
   on `oracles_lens_signals.source_job_id` is meaningful.)
3. **Scoring source-of-truth = `holdings_13f` (PRD §7.3 query
   contract).** Scoring services compute cross-quarter joins
   themselves. Confirmed in MVP4-05 caution-flag scope via D3 rule
   (b) `stale_until_recompute` — no new condition added here.
4. **Insert conflict = ORM upsert** (`INSERT ... ON CONFLICT
   (stock_id, report_quarter, score_version) DO UPDATE SET ...`).
   IntegrityError translator stays perpetual; no helper extraction
   in MVP4.

## Scope In

- Alembic migration creating `oracles_lens_signals` +
  `oracles_lens_score_components`.
- SQLAlchemy ORM models for both tables.
- `app/services/oracles_lens/constants.py` introduction (with
  `SCORE_VERSION = "v1.0"` plus a TODO comment that the plan §7.2
  manager/position weight tables land in MVP4-11 after taxonomy
  reconciliation, not here).
- New job_type / lock_key prefix constants in the worker
  configuration so MVP4-02 onward references them by name, not
  string literal.
- Model and migration tests (TDD).

## Scope Out

- Score computation logic (MVP4-02 through MVP4-06).
- API endpoints (folded into MVP4-02..-06 service tasks).
- Frontend (MVP4-07).
- Backfill orchestration (introduced incrementally per service).
- `manager_type` taxonomy reconciliation (MVP4-11).
- MVP3 carryover backlog tickets (MVP4-08 / -09 / -10).
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` — full gate;
  especially "MVP4-01 Pre-Start Conditions" and the matching
  "Pre-Start Condition Resolutions" block.
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §6.1
  (source-of-truth list), §7 (metrics), §7.12 (score_confidence
  vocabulary), §9.1 (API response sketch with
  `score_explanation`).
- `docs/prd/13f_automation_and_resilience_prd.md` §7.3
  (active-HR/HR-A current-parse_run query contract that scoring
  reads from), §10 (quality / readiness audit pattern that the
  component-audit table mirrors).
- MVP3-04 `controlled_reparse_accession` + MVP3-05
  `enqueue_batch_reparse` + MVP3-07 `enqueue_historical_backfill`
  as JobRun/lock_key precedents.

## Files Expected To Change

- `backend/alembic/versions/<timestamp>-mvp4_01_oracles_lens_score_schema.py`
  — new migration.
- `backend/app/models/institutions.py` OR
  `backend/app/models/oracles_lens.py` — new ORM models
  (file location is a TL call during review).
- `backend/app/services/oracles_lens/constants.py` — new module
  with `SCORE_VERSION` constant.
- `backend/app/services/thirteenf_job_worker.py` (or wherever
  job_type / job timeout constants live) — register
  `oracles_lens_score_backfill` job_type.
- `backend/tests/unit/test_13f_mvp4_score_schema.py` — new tests.
- This task file.

## Test Plan

- `docker compose exec api alembic upgrade head`
- `docker compose exec api alembic downgrade -1 && docker compose
  exec api alembic upgrade head` (round-trip)
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_score_schema.py`
- `docker compose exec api pytest -q`

## Tests To Write First

- Unique constraint `(stock_id, report_quarter, score_version)` is
  enforced — second insert with same triple raises `IntegrityError`.
- `score_confidence` accepts the four-value vocabulary and rejects
  others (validates with the same enum pattern as
  `OWNERSHIP_SIGNAL_CONFIDENCE_LEVELS`).
- `caution_flag_codes` accepts a JSON array of strings and round-trips.
- `oracles_lens_score_components.score_id ON DELETE CASCADE` deletes
  the components when the parent score is removed.
- `source_job_id` FK references `job_runs.id` and accepts NULL.
- `SCORE_VERSION` constant exists and is importable from
  `app.services.oracles_lens.constants`.
- Job type registration: `JOB_TIMEOUT_SECONDS_BY_TYPE` (or the
  equivalent dict) contains an entry for
  `oracles_lens_score_backfill`.

## Progress Notes

- 2026-05-11: Created after human owner delegated the MVP4 scope
  freeze + pre-start condition resolution + start authorization to
  the implementation engineer. All four pre-start decisions are
  recorded both here and on the decision gate.

## Verification Results

- Pending Docker run.
