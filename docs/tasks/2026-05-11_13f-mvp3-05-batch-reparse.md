# 13F MVP3-05: Batch Reparse Jobs by Quarter / Manager

## Goal / Acceptance Criteria

Implement the batch reparse service that fans the MVP3-04 controlled single-filing reparse
contract out across a quarter or a manager scope, with preview + confirmation,
job_runs / lock_key safety, validation-gated activation, and an aggregated
before/after impact summary.

Acceptance criteria:
- Batch scope is exactly one of `{quarter}` or `{manager_id}`; mixed/empty scope is rejected.
- Preview mode returns the candidate filing list and an estimated scope, and does not mutate any
  parse run, filing, holdings row, or override.
- Confirmed batch creates a `job_runs` row with a stable `lock_key` and `dedupe_key`; a second
  request for the same scope while a batch is `queued`/`running`/`cancel_requested` is skipped, not
  duplicated.
- Per-filing execution delegates to `thirteenf_controlled_reparse.controlled_reparse_accession`
  with the caller-supplied `validation_gate`; the batch never inlines its own parse logic.
- A single filing's `validation_failed`, `failed`, or controlled-reparse `ValueError` (override
  state mismatch) does not stop sibling filings in the batch; it is recorded in the per-filing
  report instead.
- The aggregated impact summary uses the typed `ImpactSummary` shape introduced in this task
  (carried over from MVP3-04 review) and reports:
  - `filings_scanned`, `filings_attempted`, `filings_skipped` with reasons
  - per-status counts (`succeeded`, `validation_failed`, `failed`, `rejected`)
  - sums of `parse_runs_created`, `current_pointers_changed`, `holdings_rows_created`,
    `holdings_row_count_delta`
  - aggregated `ownership_changes_recompute_scope` (the per-filing scopes, deduped by accession)
  - aggregated `quality_finding_delta` (`open_before`, `open_after`, `delta`)
  - `readiness_level_impact` collapsed to per-parse-status before/after counts
- Quarter-default ordering matches the MVP3 decision gate: MVP3-05 ships quarter scope first;
  manager scope is gated on the same contract but documented as MVP3 follow-up if the test
  matrix is incomplete.
- DB-error integration coverage from MVP3-04 review is closed: a per-filing reparse exception
  inside the batch does not poison sibling work, and the batch keeps the session usable for the
  remaining filings.
- The MVP3-04 carryover (`impact_summary` typed dataclass) is extracted before the batch layer
  consumes it.
- Relevant tests pass in Docker.

## Scope In

- New batch service module (`thirteenf_batch_reparse`) that wraps controlled reparse.
- `ImpactSummary` typed dataclass extracted from MVP3-04 and reused by both controlled reparse
  and the new batch service.
- Batch preview + confirmed-enqueue contract that produces deterministic `lock_key` /
  `dedupe_key` strings tied to the scope.
- Batch execution that loops over candidate filings, calls controlled reparse per filing, and
  aggregates results into a single payload.
- Tests covering: preview-does-not-mutate, validation-gate required, mixed quarter/manager
  rejection, partial failure isolation, dedupe lock, override status carryover, aggregated
  impact summary fields.

## Scope Out

- Admin API endpoint surface (`POST /admin/13f/jobs/reparse-by-quarter|by-manager`) and admin UI;
  this task ships the service contract, not the HTTP/UI layer.
- Corporate-action temporal mapping UI (D4 / MVP3-06).
- Historical backfill (D1 / MVP3-07).
- Parser feature changes.
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D3: controlled reparse contract before batch
  reparse; batch must require preview/confirmation, lock keys, before/after impact summary, and
  must not silently activate results that fail readiness/amendment rules.
- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` Proposed sequence: MVP3-05 quarter reparse
  default before manager reparse.
- `docs/tasks/2026-05-11_13f-mvp3-04-controlled-reparse-contract.md`: foundation contract,
  including the two carryovers (typed `ImpactSummary`; DB-error integration test).
- `docs/prd/13f_automation_and_resilience_prd.md` §6.3 / §17 / §13:
  `POST /admin/13f/jobs/reparse-by-quarter` and `POST /admin/13f/jobs/reparse-by-manager` are MVP 3.
- `docs/prd/13f_automation_and_resilience_prd.md` §12: job_runs lock_key uniqueness for active
  statuses.

## Files Expected To Change

- `backend/app/services/thirteenf_controlled_reparse.py` — introduce `ImpactSummary` dataclass,
  return it inside `ControlledReparseResult`, keep `to_dict()` backwards-compatible.
- `backend/app/services/thirteenf_batch_reparse.py` — new batch service.
- `backend/tests/unit/test_13f_mvp3_batch_reparse.py` — new tests.
- `backend/tests/unit/test_13f_mvp3_controlled_reparse.py` — update assertions to match the new
  dataclass shape while keeping behavior identical.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_batch_reparse.py`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_controlled_reparse.py`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-11: Started after MVP3-04 controlled reparse contract was approved as the foundation
  for batch work. Scope limited to service-level batch contract; admin API/UI is out of scope
  this task.
- 2026-05-11: Added TDD coverage first under `tests/unit/test_13f_mvp3_batch_reparse.py`:
  scope-validation, preview-no-mutation, NT/inactive exclusion, enqueue-creates-job-run,
  duplicate-active-rejection, aggregated-impact-summary, per-filing-validation-failure
  isolation, per-filing-parse-crash isolation, invariant-rejection isolation, required
  validation_gate, no-raw-infotable skip path, and manager-scope isolation.
- 2026-05-11: Extracted MVP3-04 carryover `ImpactSummary` typed dataclass into
  `thirteenf_controlled_reparse`. The dataclass exposes `to_dict()` and `__getitem__`
  so existing MVP3-04 dict-style call sites and tests keep working. `ControlledReparseResult`
  now carries `ImpactSummary` instead of `dict[str, Any]`.
- 2026-05-11: Added `thirteenf_batch_reparse` service. The service:
  - Accepts exactly one of `quarter` or `manager_id` (mutual exclusion rejected with
    `BatchReparseScopeError`).
  - Builds a deterministic `lock_key` / `dedupe_key` of
    `13f_batch_reparse:{quarter|manager}:{value}`; matches the partial unique index
    `uq_job_runs_active_lock_key` so a duplicate active batch is rejected with a typed
    pre-check error instead of an `IntegrityError`.
  - `preview_batch_reparse` is pure-read: returns candidate filings, scope estimate,
    lock_key, and a confirmation warning, and never mutates parse runs, holdings, or
    overrides.
  - `enqueue_batch_reparse` creates a `JobRun` in `status='queued'` with
    `job_type=batch_reparse_by_{quarter|manager}` and `input_json` capturing the scope.
  - `execute_batch_reparse` snapshots candidate filings into plain dicts up front so that
    a per-filing rollback cannot detach sibling filings. Each filing delegates to
    `controlled_reparse_accession` with the caller-supplied `validation_gate`. Per-filing
    outcomes (`succeeded`, `validation_failed`, `failed`, `rejected`, `skipped`) are
    recorded individually; the batch tally rolls up into an aggregate impact summary.
  - Aggregate impact summary preserves the MVP3-04 contract surface: filings counts,
    parse_runs_created, current_pointers_changed, holdings totals, ownership-changes
    recompute scope list (deduplicated by per-filing scope dict), and quality-finding
    delta sums. Readiness impact is collapsed to per-status before/after counts because
    aggregating raw before/after strings across filings has no meaningful interpretation.
- 2026-05-11: Excluded NT filings (`coverage_type='notice_reported_elsewhere'`) from the
  candidate list per PRD §7.3 query contract. NT carries no holdings table and is not a
  reparse target.
- 2026-05-11: PRD §7.3 query-contract guard: the candidate query filters on
  `is_active_for_manager_period=True`, so reparse batches operate on the active filing per
  manager/quarter only — superseded amendments are not re-activated by batch reparse.
- 2026-05-11: MVP3-04 carryovers addressed:
  - `ImpactSummary` typed dataclass extracted before batch layer consumed it.
  - DB-error integration coverage closed via `test_execute_isolates_per_filing_parse_crash`,
    which mocks `reparse_accession` at the controlled-reparse boundary so
    `controlled_reparse_accession` follows its own catch-and-return-`failed` path and the
    batch service tallies it as a per-filing failure without poisoning siblings.
- 2026-05-11: Scope guard: no admin API endpoint, no admin UI, no historical backfill, no
  corporate-action UI, no parser feature change, no PRD edit.

- 2026-05-11: Applied review followups from Tech Lead + Product Owner reviews:
  - D3 supersede: documented in `2026-05-11_13f-mvp3-decision-gate.md` that
    quarter-first sequencing applies to the future admin UI rollout, not the
    service layer. MVP3-05 ships both scopes at the service layer because
    controlled reparse is a per-filing safety unit and both scopes share the
    same execution path; the admin endpoint / dashboard task is still bound
    by "quarter scope ships before manager scope" when it lands.
  - Tech Lead nit (a) — `enqueue_batch_reparse` now catches `IntegrityError`
    from the `uq_job_runs_active_lock_key` partial unique index and
    re-raises as `BatchReparseScopeError`. Closes the TOCTOU window where
    two simultaneous admins both pass the pre-check.
    `_active_job_for_lock_key` helper extracted so the race can be
    deterministically tested via monkeypatch.
  - Tech Lead nit (b) — added explicit `status == "skipped"` assertion to
    the no-raw-infotable test; added `test_execute_all_failed_sets_aggregate_status_failed`
    to cover the all-failed branch; simplified `_overall_status` by
    collapsing the two redundant `attempted == 0` arms.
  - Tech Lead nit (c) — `execute_batch_reparse` docstring now documents
    that the loop does not poll `job_runs.status` mid-batch; a
    `cancel_requested` flip during execution runs to completion. MVP3
    batches are expected to be short; preemptive cancellation is a
    deferred concern for the future admin endpoint task.
  - Tech Lead nit (d) — signed `holdings_rows_net_delta` recommendation
    deferred to MVP3-06 admin UI; not a hardening item, and changing
    the existing `abs()` field would break the established test contract.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_controlled_reparse.py tests/unit/test_13f_mvp3_batch_reparse.py` -> 21 passed (7 controlled-reparse + 14 batch).
- `docker compose exec api pytest -q` -> 588 passed, 2 SQLAlchemy rollback warnings: one pre-existing in `test_duplicate_fingerprint_within_same_parse_run_raises` (carryover from MVP3-04) and one new in `test_enqueue_translates_unique_index_race_into_scope_error` (deliberate rollback inside the IntegrityError → BatchReparseScopeError translator; benign).
