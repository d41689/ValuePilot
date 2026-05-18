# 13F MVP4-03b: Dashboard Endpoint Reads Persisted Signal-Weighted Scores

## Status

Authorized to start. Filed during MVP4-03 as the integration follow-up
that connects the persisted-scores table (MVP4-01 schema, MVP4-03
compute) to the existing user-facing Oracle's Lens dashboard endpoint
at `/api/v1/13f/oracles-lens`.

## Goal / Acceptance Criteria

Make the existing dashboard endpoint **opt-in** read from
`oracles_lens_signals` so a backfilled period serves the canonical
plan §7.2 scores. Preserve existing in-memory compute as the default
so callers that haven't migrated keep working unchanged.

Acceptance criteria:

- `GET /api/v1/13f/oracles-lens` accepts a new query param
  `use_persisted_scores: bool` (default `false`).
- When `use_persisted_scores=false` (existing default):
  - Behavior is unchanged from MVP4-03 baseline. The in-memory
    compute in `dashboard._stock_payload` produces the
    `signal_weighted_consensus_score` for each stock.
- When `use_persisted_scores=true`:
  - The endpoint queries `oracles_lens_signals` for the requested
    `period` and `score_version=SCORE_VERSION`.
  - Each item in the response carries the persisted score:
    `signal_weighted_consensus_score`, `score_confidence`,
    `caution_flag_codes`, `score_explanation.confidence_demotion_reasons`.
  - Stocks **without** a persisted row are excluded from the
    response — no in-memory fallback in persisted mode (avoids
    serving two formulas side-by-side in one response).
  - Each item exposes `score_source: "persisted"` for observability.
  - Items still carry the non-score fields the existing endpoint
    emits (`top_holders`, `manager_signal_summary`, etc.) from the
    in-memory pipeline; persisted mode only overrides the score
    payload.
- The `coverage` block of the response gains a
  `persisted_score_count` field equal to the number of items whose
  score came from `oracles_lens_signals`.
- TDD coverage:
  - default mode (`use_persisted_scores=false`) returns existing
    in-memory behavior;
  - persisted mode returns the table's score for stocks with rows;
  - persisted mode excludes stocks without rows;
  - `score_source` field is present in persisted-mode items;
  - persisted mode respects `score_version`;
  - no-rows-at-all in persisted mode returns an empty `items`
    list (not 500 / not the in-memory list).
- Full suite stays green; no behavior regression on
  default-mode callers.

## Scope In

- Update `app/services/oracles_lens/dashboard.py`:
  - `build_oracles_lens_dashboard` accepts
    `use_persisted_scores` and threads it into the per-stock
    payload build.
  - When persisted mode is active, look up
    `oracles_lens_signals` rows for the (period, score_version)
    and use those values for the score fields; mark
    `score_source="persisted"`.
- Update the endpoint route at
  `app/api/v1/endpoints/oracles_lens.py` to accept the new param.
- New TDD test file
  `tests/unit/test_13f_mvp4_dashboard_persisted_scores.py`.

## Scope Out

- Refactor the dashboard's in-memory formula to match plan §7.2
  (the two formulas legitimately diverge; that's the whole reason
  MVP4-03 ships a separate persisted layer). Formula reconciliation
  is a future task once the persisted path is consumed by
  production.
- Conviction score from MVP4-04 (not yet built).
- Distinctive consensus from MVP4-06.
- Frontend changes (MVP4-07).
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md`: MVP4-07 G4
  contract boundary requires backend response shape stability
  before frontend work; MVP4-03b is the integration that makes that
  shape persistable.
- `docs/tasks/2026-05-11_13f-mvp4-03-signal-weighted-score.md`:
  Progress note about the existing dashboard endpoint already
  serving an in-memory score; MVP4-03b is the connector.
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §9.1:
  response shape that both modes honor.

## Files Expected To Change

- `backend/app/services/oracles_lens/dashboard.py` — accept the
  flag, branch the per-stock score path.
- `backend/app/api/v1/endpoints/oracles_lens.py` — new query
  param.
- `backend/tests/unit/test_13f_mvp4_dashboard_persisted_scores.py`
  — new tests.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_dashboard_persisted_scores.py`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-11: Started after MVP4-03 landed. Discovery from MVP4-03
  recon: the existing `dashboard.py` has its own in-memory formula
  (`_position_signal_weight`) that differs in base normalization
  from plan §7.2 (`min(position_weight * 4, 1.0)` vs raw
  `portfolio_weight`). MVP4-03b takes the conservative path —
  opt-in flag, no formula reconciliation — so the persisted layer
  can be exercised end-to-end without changing default behavior.
- 2026-05-11: Wrote TDD coverage first under
  `tests/unit/test_13f_mvp4_dashboard_persisted_scores.py` (6 tests):
  - default mode (no flag) preserves in-memory behavior; the
    rendered score differs numerically from the persisted row
    (confirming the two formulas legitimately diverge);
  - persisted mode surfaces the table's
    `signal_weighted_consensus_score` and `score_confidence` for
    stocks with rows;
  - persisted mode excludes stocks without rows — no mixing of
    formulas in one response;
  - persisted mode with no rows for the quarter returns
    `items=[]`, not 500 / not in-memory fallback;
  - persisted mode respects `score_version` — rows under a
    non-default version are not visible;
  - `coverage.persisted_score_count` is populated in persisted
    mode.
- 2026-05-11: Implemented:
  - `build_oracles_lens_dashboard` gains
    `use_persisted_scores: bool = False`. When true, items are
    post-processed via `_apply_persisted_scores` which queries
    `oracles_lens_signals` by (period, score_version) and
    overrides each item's score fields plus marks
    `score_source="persisted"`. Stocks without a persisted row
    are dropped.
  - `_apply_persisted_scores` merges the persisted
    `score_explanation` into the dashboard's existing one so
    `confidence_demotion_reasons` (from MVP4-03) survives
    alongside the dashboard's `primary_reasons` /
    `negative_reasons` / `conviction_components`.
  - Coverage block gains `persisted_score_count` for
    observability.
  - Endpoint route gains `use_persisted_scores: bool` query
    param with documentation.
- 2026-05-11: Scope guard — no formula reconciliation (the
  dashboard's in-memory formula stays as the default-mode
  authority); no schema changes; no frontend changes; no PRD
  edits.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_dashboard_persisted_scores.py` -> 6 passed.
- `docker compose exec api pytest -q` -> **707 passed** (was 701 pre-MVP4-03b; +6), 0 warnings.
