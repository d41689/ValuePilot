# 13F MVP3-07: Validation-Gated Historical Backfill

## Goal / Acceptance Criteria

Implement the **service contract** for admin-triggered historical 13F backfill that
honors decision-gate D1: default start at `2023-Q1`, pre-2023 only as dry-run /
validation mode, preview before enqueue, resumable, no overwrite of existing parse
runs, and backfilled quarters remain in a `needs_validation` audit state until a
per-quarter validation gate clears them.

Acceptance criteria:
- `preview_historical_backfill` returns the scope (per manager × per quarter), the
  count of manager-quarters still missing an active filing, an explicit
  `value_unit_risk_warning` whenever the range crosses the 2023 transition, and a
  `requires_dry_run` flag for any pre-2023 range. Preview never mutates parse runs,
  holdings, filings, or quality records.
- `enqueue_historical_backfill` creates a `JobRun` with a deterministic
  `lock_key`/`dedupe_key` (`13f_historical_backfill:{start}-{end}:{manager_scope}`),
  matches the partial unique index `uq_job_runs_active_lock_key`, and translates the
  `IntegrityError` race window into a typed `HistoricalBackfillError` like MVP3-05.
- A pre-2023 range without `dry_run=True` is rejected at enqueue time with a typed
  error. With `dry_run=True`, the job is created but `summary_json["dry_run"]=true`
  and `execute_historical_backfill` short-circuits to discovery only (no ingestion).
- `execute_historical_backfill` requires an explicit `validation_gate`; missing gate
  raises `ValueError`, matching MVP3-04/05.
- Per manager-quarter, execute first checks whether an active 13F-HR / 13F-HR/A
  filing already exists. If yes: **skipped** with reason `already_ingested`. Never
  overwrites existing parse runs or holdings.
- For missing manager-quarters, execute calls an injectable `filing_discovery_fn`
  (default: existing SEC submissions parser) to enumerate accessions, then calls an
  injectable `ingest_fn` per accession (default: existing ingest_accession path).
- After each quarter completes, execute invokes the `validation_gate` with the
  quarter and the per-filing results. The gate returns `(passed, errors)`.
- For every quarter that touches data — successful ingestion or otherwise — execute
  writes a `QualityReport13F` event with one `QualityFinding13F` per backfilled
  filing using rule_code `HISTORICAL_BACKFILL_NEEDS_VALIDATION`, severity `warning`,
  status `open`. When the per-quarter validation gate returns `passed=True`, the
  findings for that quarter are flipped to status `resolved` with a resolution note.
  When the gate fails or is skipped, the findings stay open and downstream readiness
  surfaces see the quarter as `needs_validation`.
- Per-filing ingestion failures do not poison sibling work in the same quarter or
  later quarters. They are recorded in the per-filing report.
- The aggregate result includes counts of `quarters_scanned`, `quarters_validated`,
  `quarters_needs_validation`, `filings_ingested`, `filings_already_present`,
  `filings_failed`, plus the underlying job_run id.
- Relevant tests pass in Docker.

## Scope In

- New `thirteenf_historical_backfill` service module:
  - `preview_historical_backfill(session, *, start_quarter=None, end_quarter=None,
    manager_ids=None) -> dict`
  - `enqueue_historical_backfill(session, *, start_quarter=None, end_quarter=None,
    manager_ids=None, dry_run=False, requested_by_user_id=None,
    trigger_source="admin") -> JobRun`
  - `execute_historical_backfill(session, *, job_run_id, validation_gate,
    filing_discovery_fn, ingest_fn) -> dict`
- Reuse the same `DEFAULT_BACKFILL_START_QUARTER` setting that
  `build_manager_backfill_preview` already honors.
- Reuse the same canonical `JobRun` / `lock_key` partial unique index from MVP1A
  and the same `IntegrityError → typed-error` translation pattern from MVP3-05.
- New rule code `HISTORICAL_BACKFILL_NEEDS_VALIDATION` written as a per-filing
  `QualityFinding13F` tied to one per-quarter `QualityReport13F` event, with
  status flipping to `resolved` on validation success.
- Tests covering: default start quarter, pre-2023 dry-run gate, preview-no-mutation,
  enqueue dedupe + IntegrityError translation, no-overwrite of existing active
  filings, validation gate required, validation success resolves findings,
  validation failure keeps findings open, per-filing ingestion failure isolation,
  aggregate impact counts.

## Scope Out

- The actual SEC fetching + parsing pipeline used inside the default
  `filing_discovery_fn` and `ingest_fn`. MVP3-07 delegates to existing MVP1B
  paths; tests inject mocks.
- The HTTP admin endpoint and admin UI for the backfill dashboard. Backend
  response shapes stabilize first per dev-plan G4.
- The eventual MVP2 ownership-change recompute pass that consumes the released
  quarter snapshots — that pipeline runs separately.
- Schema migrations. The "needs_validation" state is expressed via
  `QualityFinding13F.status='open'` + the new rule code; no new column on
  `filings_13f` is added.
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D1: backfill must use shared
  SEC client / rate limiter / job_runs / raw storage; resumable by manager,
  quarter, accession; no overwrite of existing parse runs; preview before
  broad enqueue; backfilled quarters enter `needs_validation` until validation
  jobs pass.
- `docs/prd/13f_automation_and_resilience_prd.md` §17, §19, §20: MVP 3
  backfill scope, default 2023-Q1 start, pre-2023 value-unit transition risk.
- `docs/prd/13f_automation_and_resilience_prd.md` §10: quality reports +
  findings as the audit-trail surface.

## Files Expected To Change

- `backend/app/services/thirteenf_historical_backfill.py` — new module.
- `backend/tests/unit/test_13f_mvp3_historical_backfill.py` — new tests.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_historical_backfill.py`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-11: Started after MVP3-06 corporate-action mapping was approved. Scope
  limited to the validation-gated orchestration service. The HTTP admin endpoint
  and dashboard pages are explicit follow-ups so the response shape can settle
  per G4.
- 2026-05-11: Wrote TDD coverage first under
  `tests/unit/test_13f_mvp3_historical_backfill.py` (15 tests):
  - `DEFAULT_BACKFILL_START_QUARTER=2023-Q1` default when caller omits start.
  - Pre-2023 ranges flagged with `value_unit_risk_warning=true` and
    `requires_dry_run=true`.
  - Preview is pure read (job_runs / quality reports / findings untouched).
  - Enqueue creates a `JobRun(job_type='historical_backfill')` with
    deterministic `lock_key=13f_historical_backfill:{start}:{end}:{manager_scope}`.
  - Duplicate active enqueue rejected by pre-check and by the partial unique
    index race translator (mirrors MVP3-05's `IntegrityError → typed-error`
    pattern).
  - Pre-2023 enqueue rejected without `dry_run=True`; accepted with it.
  - Execute requires explicit `validation_gate`.
  - Execute skips manager-quarters that already have an active filing (no
    overwrite); audit-history retention is by-design because the service
    never touches existing `Filing13F` / `ParseRun13F` / `Holding13F` rows.
  - Per-quarter findings written via `QualityReport13F` +
    `QualityFinding13F(rule_code=HISTORICAL_BACKFILL_NEEDS_VALIDATION,
    status=open)`. Validation success flips findings to `resolved` (only for
    successfully-ingested filings; failed ingestions stay open because
    validation can't certify what didn't ingest).
  - Per-filing ingest failure does not poison sibling filings; aggregate counts
    succeeded / failed independently.
  - `dry_run=True` skips ingest_fn invocations but still writes the quarter's
    audit report so the admin dashboard sees the dry-run attempt.
  - Aggregate `status` reflects mixed-quarter outcomes (e.g. one quarter
    validated, one quarter `needs_validation` → `partial_success`).
- 2026-05-11: Implemented `thirteenf_historical_backfill`:
  - `preview_historical_backfill` enumerates quarter list, resolves the
    manager scope (defaults to active managers), and returns risk flags.
  - `enqueue_historical_backfill` creates the `JobRun`, hashes the manager
    scope into the `lock_key`, and translates the partial-unique-index race
    via try/except IntegrityError.
  - `execute_historical_backfill` walks quarters in order; per quarter loops
    managers, skips those with an existing active filing, calls
    `filing_discovery_fn` and `ingest_fn` injected by the caller (default
    implementations wire to existing MVP1B ingestion paths — left to the
    eventual admin endpoint to wire in). After each quarter it writes one
    `QualityReport13F` event + per-filing findings, then invokes
    `validation_gate(session, quarter, results)` and flips findings if the
    gate passes.
  - Aggregate `_overall_status` returns `succeeded` when every quarter was
    validated and no filings failed; `failed` when nothing ingested and
    nothing validated; otherwise `partial_success` / `skipped`.
- 2026-05-11: Defensive choice — `_active_job_for_lock_key` uses `.first()`
  ordered by `created_at desc, id desc` rather than `.one_or_none()`. The
  partial unique index uq_job_runs_active_lock_key guarantees uniqueness in
  production, but ordering by recency lets the pre-check survive any
  short-lived duplicate state (e.g. between two simultaneous test
  fixtures).
- 2026-05-11: Scope guard — no admin HTTP endpoint, no admin UI, no migration,
  no parser changes, no PRD edits.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_historical_backfill.py` -> 15 passed.
- `docker compose exec api pytest -q` -> 614 passed (was 599 before MVP3-07; +15), 3 SQLAlchemy rollback warnings — the two pre-existing from MVP1B / MVP3-05 plus one new in `test_enqueue_translates_unique_index_race` (deliberate rollback inside the IntegrityError → HistoricalBackfillError translator; mirrors MVP3-05's pattern; benign).
