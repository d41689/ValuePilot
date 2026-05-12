# 13F MVP4-03: Signal-Weighted Consensus Score Service + API

## Status

Authorized to start. All prerequisites complete (MVP4-01 schema,
MVP4-02 primitives, MVP4-09 rule codes, MVP4-10 conftest hardening,
MVP4-11 manager_type taxonomy).

## Goal / Acceptance Criteria

Implement the **primary ranking metric** for Oracle's Lens V1: the
signal-weighted consensus score (plan §7.2). Persist scores into
`oracles_lens_signals`, per-holder component breakdown into
`oracles_lens_score_components`. Expose a user-facing read endpoint
that future MVP4-04 / 05 / 06 services extend with their own
fields.

Acceptance criteria:

### Formula (plan §7.2)

For each stock with `>= min_holders` linked direct holdings in the
active HR/HR-A current parse run (PRD §7.3 query contract):

```
signal_weighted_consensus_score = Σ (manager_signal_weight × position_signal_weight)
```

where for each contributing holder:

- `manager_signal_weight` = `MANAGER_SIGNAL_WEIGHTS[canonical_type]`
  with `canonical_type` from `resolve_manager_type(manager,
  derived_profile=...)` (MVP4-11).
- `position_signal_weight` = `base + bonus_top_10 + bonus_weight_5pct
  + bonus_streak + action_adjustment`, where:
  - `base` = the holder's `portfolio_weight` (MVP4-02
    `compute_portfolio_weight`); `None` → `0` for arithmetic.
  - `bonus_top_10` = `0.40` if this stock is in the top 10 of the
    manager's portfolio by `value_thousands`, else `0`.
  - `bonus_weight_5pct` = `0.30` if `portfolio_weight >= 0.05`,
    else `0`.
  - `bonus_streak` = `0.30` if `holding_streak_quarters >= 4`
    (MVP4-02 `compute_holding_streak`), else `0`.
  - `action_adjustment` = a V1 calibration on `add_intensity`
    (MVP4-02 `compute_add_intensity`):
    - new position (value `1.0`): `+0.20`
    - added (`0 < value < 1`): `+0.10`
    - unchanged (`value == 0` or `None`): `0`
    - reduced (`-1 < value < 0`): `-0.10`
    - exit (`-1.0`): `-0.20`
    - **stale_until_recompute** or
      **HISTORICAL_BACKFILL_NEEDS_VALIDATION** caveat present:
      `action_adjustment = 0` (the underlying delta cannot be
      trusted; D3 rules (b)/(e)).
  - These calibration values ship as named constants in
    `oracles_lens/constants.py` next to `SCORE_VERSION` /
    `MANAGER_SIGNAL_WEIGHTS` so a future tuning round bumps
    `SCORE_VERSION` and ships new numbers together.

### Eligibility (plan §7.1)

- A stock is scored only when its `linked` direct-common holder
  count in the active HR/HR-A current parse run is `>= min_holders`
  (default `3`).
- Stocks failing eligibility are not written (no
  `oracles_lens_signals` row).

### Score Confidence (plan §7.12 + D3 caveat propagation)

The composite score's `score_confidence` is demoted by the
**worst** caveat surfacing on any contributing holder:

- Any `OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`
  (`stale_until_recompute`) or
  `HISTORICAL_BACKFILL_NEEDS_VALIDATION` caveat → **at most**
  `low_confidence` (D3 (b)/(e)).
- Any `PARTIAL_COVERAGE`, `CONFIDENTIAL_TREATMENT`,
  `NT_QUARTER_STREAK_BREAK`, or `PRE_2023_PRE_HISTORY_UNAVAILABLE`
  caveat → **at most** `medium_confidence` (D3 (a)/(c)/(d), D2).
- No caveats → `high_confidence`.

`score_explanation.confidence_demotion_reasons` is populated with
`[{"code": "<flag>", "demoted_to": "<level>"}]` per the MVP4-01
PO re-review P2 #4 contract.

### Persistence (MVP4-01 schema)

- Upsert one `oracles_lens_signals` row per
  `(stock_id, report_quarter, score_version)` via SQLAlchemy
  `INSERT ... ON CONFLICT DO UPDATE` (MVP4-01 D4 ORM upsert).
- Replace `oracles_lens_score_components` rows for the score: one
  per holder per component (`manager_signal_weight`,
  `position_signal_weight`, `position_weight_base`,
  `top_10_bonus`, `weight_5pct_bonus`, `streak_bonus`,
  `action_adjustment`).
- `source_job_id` populated when invoked via the JobRun
  orchestration path.

### JobRun Orchestration

- `enqueue_signal_weighted_backfill(session, *, quarter,
  score_version=SCORE_VERSION, requested_by_user_id=None,
  trigger_source='admin') -> JobRun` creates a `JobRun` with:
  - `job_type='oracles_lens_score_backfill'`
  - `lock_key='oracles_lens_score:{quarter}:{score_version}'`
  - `dedupe_key = lock_key`
  Duplicate active enqueue (`queued` / `running` /
  `cancel_requested`) raises `SignalWeightedBackfillError`;
  IntegrityError race translated to the same typed error per the
  MVP3-05 / MVP3-07 / MVP4-01 pattern.
- `execute_signal_weighted_backfill(session, *, job_run_id) ->
  dict` reads `JobRun.input_json` for scope, runs the compute
  service, sets `JobRun.status='succeeded'` / `'failed'` /
  `'partial_success'`, persists an aggregate impact summary.

### HTTP Read Endpoint (MVP4-07 G4 contract boundary)

- `GET /api/v1/13f/oracles-lens` (consumer-facing, no admin
  auth) returns the ranking table.
- Query params per plan §9.1: `period`, `min_holders`, `limit`
  (sort defaults to `signal_weighted_consensus`).
- Other params from plan §9.1 (`lookback_quarters`,
  `superinvestor_only`, `min_signal_score`,
  `sort=conviction|distinctive_consensus|add_intensity|aggregate_weight|quality`)
  are accepted in the route signature but no-op in MVP4-03 — they
  belong to MVP4-04 / MVP4-05 / MVP4-06 columns. They are
  declared now so the response shape MVP4-07 consumes is stable.
- Response items expose, for V1: `stock_id`, `ticker`,
  `company_name`, `consensus_count`,
  `signal_weighted_consensus_score`, `score_confidence`,
  `score_explanation`, `caution_flag_codes`. Fields belonging to
  later MVP4 services (`conviction_score`,
  `distinctive_consensus_score`, `add_intensity` aggregate,
  `caution flags` etc.) are emitted as `null` so MVP4-07
  frontend gets a stable shape.
- Response payload includes `period`, `score_version`, and a
  small `coverage` block (`manager_count`,
  `holding_count`, `linked_holding_count`) per plan §9.1
  sketch.

### Tests

TDD (test file `tests/unit/test_13f_mvp4_signal_weighted_score.py`):

- Eligibility: 2 holders → not scored; 3 holders → scored.
- Formula direct check: known manager_type + known holdings →
  expected composite within `Decimal` tolerance.
- `bonus_top_10` fires for top-10 position, doesn't fire for
  rank 11.
- `bonus_weight_5pct` fires at `portfolio_weight = 0.05`, not at
  `0.049`.
- `bonus_streak` fires at `streak = 4`, not at `streak = 3`.
- Manager weight from admin enum (D2 admin source).
- Manager weight from behavior fallback (D2 behavior source).
- Score confidence demotion: PARTIAL_COVERAGE → medium;
  stale_until_recompute → low; multiple caveats → worst wins.
- Component rows: one per holder × component, with
  `numeric_value` matching what went into the composite.
- Upsert idempotence: re-running compute for same
  (stock, quarter, version) does not duplicate rows.
- JobRun lock_key + dedupe rejection + IntegrityError
  translation.
- HTTP endpoint returns scored stocks sorted by composite desc;
  empty quarter returns 200 with empty list; min_holders param
  honored.

## Scope In

- New `app/services/oracles_lens/signal_weighted_score.py` —
  compute service + JobRun orchestration.
- New `app/schemas/oracles_lens.py` (or extension) — Pydantic
  response models.
- Update `app/api/v1/endpoints/thirteenf_admin.py` (the
  `consumer_router` lives here) — add the new endpoint route.
- Update `app/services/oracles_lens/constants.py` with the V1
  position-signal calibration constants
  (`POSITION_BASE_BONUS_TOP_10`,
  `POSITION_BASE_BONUS_WEIGHT_5PCT`, `POSITION_BASE_BONUS_STREAK`,
  `ACTION_ADJUSTMENT_NEW`, `ACTION_ADJUSTMENT_ADD`,
  `ACTION_ADJUSTMENT_REDUCE`, `ACTION_ADJUSTMENT_EXIT`).
- TDD test file.

## Scope Out

- Conviction score (MVP4-04).
- Caution flags surface (MVP4-05) — score-level caveats are
  populated here but the user-facing per-row caveat panel is
  MVP4-05.
- Distinctive consensus (MVP4-06).
- Value Line overlay (D4 deferred to V2).
- Frontend (MVP4-07).
- Manager top-10 ranking precompute table — V1 computes top-10
  per (manager, quarter) on the fly inside the compute loop; if
  this becomes a hot path later it can be promoted to a cached
  table.
- Behavior-derived profile orchestration — `resolve_manager_type`
  accepts `derived_profile=None`; MVP4-03 passes `None` by default
  and admins can re-tune via the admin `manager_type` enum.
  Behavior fallback wiring is deferred until there is a real
  consumer of behavior outputs in V1 (currently none).
- PRD edits.

## Files Expected To Change

- `backend/app/services/oracles_lens/signal_weighted_score.py` — new.
- `backend/app/services/oracles_lens/constants.py` — add V1
  position / action calibration constants.
- `backend/app/schemas/oracles_lens.py` — new Pydantic schemas.
- `backend/app/api/v1/endpoints/thirteenf_admin.py` — new
  consumer endpoint route.
- `backend/tests/unit/test_13f_mvp4_signal_weighted_score.py` — new.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_signal_weighted_score.py`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-11: Started after MVP4-11 manager_type taxonomy
  reconciliation landed; all MVP4-03 prerequisites complete.
- 2026-05-11: Discovery during recon — an in-memory Oracle's Lens
  dashboard endpoint already exists at
  `app/api/v1/endpoints/oracles_lens.py` (consumed via
  `app/services/oracles_lens/dashboard.py`). It computes
  `signal_weighted_consensus_score` on the fly without reading from
  the `oracles_lens_signals` table MVP4-01 added. **Scope
  adjustment:** MVP4-03 ships the persistence path (compute service
  + JobRun + table writes) but does **not** rewire the existing
  endpoint. Wiring `oracles_lens_signals` into the dashboard read
  path is filed as a follow-up — `MVP4-03b dashboard endpoint
  reads persisted scores` — and is required before MVP4-07 frontend
  can reliably consume backfilled scores.
- 2026-05-11: Wrote TDD coverage first under
  `tests/unit/test_13f_mvp4_signal_weighted_score.py` (20 tests):
  - **Pure-function math** (no DB): position-signal-weight base /
    top-10 bonus / 5% threshold (inclusive) / streak threshold
    (inclusive) / action adjustments (new=+0.20, add=+0.10,
    reduce=-0.10, exit=-0.20, no signal=0) / stale-caveat-zeros-
    action (D3 rule b/e).
  - **Confidence demotion**: high default, medium tier (partial
    coverage / confidential / NT in streak / pre-2023), low tier
    (stale / backfill-validation), worst tier wins on mixed
    caveats.
  - **DB integration**: <3 holders → no score row; ≥3 holders →
    score row with correct caveats; partial-coverage holder →
    medium confidence demotion; upsert idempotence; component
    rows persisted per holder per component.
  - **JobRun orchestration**: enqueue creates row with correct
    lock_key `oracles_lens_score:{quarter}:{score_version}`;
    duplicate active rejected; execute marks succeeded with
    aggregate impact summary.
  - **Read helper**: `build_oracles_lens_response` returns ranked
    list with the V1 fields plus null placeholders for MVP4-04 /
    05 / 06 fields (frozen response shape for MVP4-07 frontend).
- 2026-05-11: Implemented
  `app/services/oracles_lens/signal_weighted_score.py`:
  - Pure functions: `compute_position_signal_weight`,
    `determine_score_confidence` — testable without DB so the
    math contract is locked.
  - V1 calibration constants live in
    `app/services/oracles_lens/constants.py`
    (`POSITION_BASE_BONUS_*`, `ACTION_ADJUSTMENT_*`) next to
    `SCORE_VERSION` and `MANAGER_SIGNAL_WEIGHTS`. A future tuning
    round bumps `SCORE_VERSION` and ships new values together.
  - `compute_signal_weighted_scores` walks eligible stocks,
    builds per-holder contributions via MVP4-02 primitives +
    MVP4-11 `resolve_manager_type`, applies the §7.2 formula, and
    upserts `oracles_lens_signals` via
    `INSERT ... ON CONFLICT DO UPDATE` (MVP4-01 D4).
    `oracles_lens_score_components` rows are replaced per score.
  - Top-10 ranking computed once per (manager, quarter) via a
    single in-memory query and reused across all eligible stocks.
  - Cross-quarter joins read `holdings_13f` via the PRD §7.3
    contract (active HR/HR-A, current parse_run, linked direct
    holdings); ownership_changes is not consulted (MVP4-01
    pre-start condition #3).
  - `enqueue_signal_weighted_backfill` / `execute_signal_weighted_backfill`
    mirror the MVP3-05 / MVP3-07 JobRun + IntegrityError
    translator pattern.
  - `build_oracles_lens_response` is the read helper for the
    eventual endpoint integration; the existing dashboard
    endpoint is unchanged.
- 2026-05-11: Caveat propagation pipeline confirmed end-to-end:
  MVP4-02 primitive caveats + per-row
  `Filing13F.has_confidential_treatment` flow into a union per
  stock, drive `determine_score_confidence`, and populate
  `oracles_lens_signals.caution_flag_codes` plus the
  `score_explanation.confidence_demotion_reasons` array (MVP4-01
  PO P2 #4 contract).
- 2026-05-11: Scope guard — no admin UI; existing
  `/api/v1/13f/oracles-lens` endpoint unchanged; integration of
  persisted scores into the dashboard endpoint deferred to
  MVP4-03b.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_signal_weighted_score.py` -> 20 passed.
- `docker compose exec api pytest -q` -> **701 passed** (was 681 pre-MVP4-03; +20), 0 warnings.
