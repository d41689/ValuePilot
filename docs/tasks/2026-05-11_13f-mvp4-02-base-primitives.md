# 13F MVP4-02: Holding Streak + Portfolio Weight Base Primitives

## Status

Authorized to start. MVP4-01 schema (`9b33f9f`) is in. MVP4-09 /
MVP4-10 / MVP4-11 are MVP4-03 prereqs, not MVP4-02 prereqs — MVP4-02
depends only on MVP4-01.

## Goal / Acceptance Criteria

Implement the three shared primitive inputs that MVP4-03
(signal-weighted consensus) and MVP4-04 (conviction score) consume.
No score table writes, no scoring formula, no API, no frontend in
this task.

Acceptance criteria:

- **`compute_portfolio_weight(holding) -> PortfolioWeightResult`**
  (plan §7.3). Returns:
  - `value`: `Decimal` weight on `[0, 1]`, or `None`.
  - `caveats`: list of caveat codes.
  Behavior:
  - Uses `holding.value_thousands / filing.computed_total_value_thousands`.
  - Falls back to `filing.reported_total_value_thousands` when
    computed total is null.
  - Returns `value=None, caveats=["PARTIAL_COVERAGE"]` when
    `filing.coverage_completeness='partial'` (D3 rule (a):
    structurally unevaluable per PRD §7.2 line 588–592).
  - Returns `value=None` when both totals are null (no
    denominator).

- **`compute_holding_streak(session, *, manager_id, stock_id,
  current_quarter, lookback=8,
  data_window_start_quarter='2023-Q1') -> HoldingStreakResult`**
  (plan §7.10). Returns:
  - `streak_quarters`: int ≥ 0 — consecutive-ownership count ending
    at `current_quarter`.
  - `caveats`: list of caveat codes.
  Behavior:
  - Walks backward from `current_quarter` quarter-by-quarter.
  - A quarter counts toward streak iff the manager has an active
    HR/HR-A holding for the stock in that quarter (joining
    `holdings_13f` ↔ active `Filing13F` ↔ current `ParseRun13F`).
  - Stops counting at the first non-owning quarter.
  - An NT quarter (`coverage_type='notice_reported_elsewhere'`
    active filing for that manager in that quarter) **resets** the
    streak; D3 rule (d) emits `NT_QUARTER_STREAK_BREAK` caveat
    and prevents exit classification.
  - When the walk reaches `data_window_start_quarter` while the
    streak is still active, emits `PRE_2023_PRE_HISTORY_UNAVAILABLE`
    (D2): the holder may have started before the window.

- **`compute_add_intensity(session, *, manager_id, stock_id,
  current_quarter,
  data_window_start_quarter='2023-Q1') -> AddIntensityResult`**
  (plan §7.4). Returns:
  - `value`: `Decimal` shares-delta ratio
    (`(current_shares − previous_shares) / max(previous_shares,
    current_shares)`), or `None`.
  - `caveats`: list of caveat codes.
  Behavior:
  - Uses shares (`ssh_prnamt`) rather than value.
  - Previous quarter is `current_quarter` minus one
    (Q1 → prior year Q4).
  - Returns `value=None` when no prior data and previous quarter is
    at the data-window floor, with caveat
    `PRE_2023_PRE_HISTORY_UNAVAILABLE` (D2).
  - Returns `value=1.0` (new position) when previous quarter is
    after the data-window floor but the manager had no holding
    (genuine new position).
  - Returns `value=-1.0` (full exit) when current quarter has no
    holding but previous did.
  - Per D3 rule (b): when an open `QualityFinding13F` with
    `rule_code='OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION'`
    exists for the holder × `current_quarter`, snaps the value to
    `0.0` and emits `stale_until_recompute` caveat.
  - Per D3 rule (e): when an open `QualityFinding13F` with
    `rule_code='HISTORICAL_BACKFILL_NEEDS_VALIDATION'` exists for
    the holder × `current_quarter`, snaps to `0.0` and emits
    `HISTORICAL_BACKFILL_NEEDS_VALIDATION` caveat.

- All three functions return frozen dataclasses (no in-place
  mutation by callers).
- Canonical caveat-code constants exposed from
  `app/services/oracles_lens/base_primitives.py` so MVP4-03/04/05
  import them by name, not literal strings.
- Pure functions: no commits, no writes; tests can run with a clean
  rolling-back session.
- Relevant tests pass in Docker.

## Scope In

- New `app/services/oracles_lens/base_primitives.py`.
- New test file
  `backend/tests/unit/test_13f_mvp4_base_primitives.py`.
- Reuse of existing models (`Filing13F`, `Holding13F`,
  `ParseRun13F`, `QualityFinding13F`). No new ORM.

## Scope Out

- Score row writes to `oracles_lens_signals` (MVP4-03+).
- Score formula (signal-weighted, conviction). MVP4-03/04 wire the
  primitives into composite scores.
- JobRun orchestration / backfill (MVP4-03+ when actually invoking).
- API endpoint / frontend.
- Caveats from other rules (e.g. confidential treatment) — those are
  per-row characteristics of the holding itself; MVP4-05 maps them
  in the caution-flags service.
- Manager taxonomy / weight constants — MVP4-11 prerequisite.
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D3 rules (a),
  (b), (d), (e) + D2 caveat code + MVP4-01 pre-start condition #3
  (scoring reads `holdings_13f`).
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §7.3
  (portfolio weight), §7.4 (add intensity), §7.10 (holding
  duration / streak).
- `docs/prd/13f_automation_and_resilience_prd.md` §7.2 (partial
  coverage portfolio_weight=NULL constraint), §7.3 (query
  contract), §9.1 (NT quarter semantics).

## Files Expected To Change

- `backend/app/services/oracles_lens/base_primitives.py` — new.
- `backend/tests/unit/test_13f_mvp4_base_primitives.py` — new.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_base_primitives.py`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-11: Started after MVP4-01 schema landed and PO re-review
  of the gate closed. MVP4-02 depends only on MVP4-01; MVP4-03's
  prerequisites (MVP4-09/10/11) are not in scope here.
- 2026-05-11: Wrote TDD coverage first under
  `tests/unit/test_13f_mvp4_base_primitives.py` (13 tests):
  - portfolio_weight: computed-total path, reported-total fallback,
    `PARTIAL_COVERAGE` → None+caveat, both-totals-null → None;
  - holding_streak: consecutive count, break terminates streak, NT
    quarter resets with `NT_QUARTER_STREAK_BREAK` caveat,
    data-window floor emits `PRE_2023_PRE_HISTORY_UNAVAILABLE`;
  - add_intensity: shares-delta ratio, new-position returns 1.0
    when previous quarter is after floor, data-window floor emits
    `PRE_2023_PRE_HISTORY_UNAVAILABLE` + None, open recompute
    finding snaps to 0.0 + `stale_until_recompute`, open backfill
    validation finding snaps to 0.0 +
    `HISTORICAL_BACKFILL_NEEDS_VALIDATION`.
- 2026-05-11: Implemented `app/services/oracles_lens/base_primitives.py`:
  - Three frozen result dataclasses
    (`PortfolioWeightResult`, `HoldingStreakResult`,
    `AddIntensityResult`) each carrying value + caveats list.
  - Five canonical caveat-code constants exposed at module level so
    MVP4-03/04/05 import by name, not literal strings.
  - All cross-quarter joins read `holdings_13f` ↔ active `Filing13F`
    ↔ current `ParseRun13F` (PRD §7.3 contract) — never reads
    `ownership_changes`, honoring MVP4-01 pre-start condition #3.
  - D3 rules (b) / (e) fire **before** the numeric computation, so a
    downstream consumer always sees the caveat before a (potentially
    misleading) magnitude.
  - Quarter math (`_quarter_key`, `_previous_quarter`) duplicated
    locally rather than imported from `thirteenf_admin_dashboard` to
    avoid a cross-service dependency on the dashboard module;
    MVP4-09 shared rule_code constants module will be the right
    place to also consolidate the quarter math if a third caller
    appears.
- 2026-05-11: Scope guard — no score writes, no API, no frontend,
  no schema. Pure functions; tests use a rolling-back session.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_base_primitives.py` -> 13 passed.
- `docker compose exec api pytest -q` -> 666 passed (was 653 pre-MVP4-02; +13), 4 SQLAlchemy rollback warnings (same set as MVP4-01 baseline; covered by MVP4-10 conftest hardening backlog).
