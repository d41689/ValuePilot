# 13F MVP4-04: Conviction Score Service

## Status

Authorized to start. Depends on MVP4-02 streak primitive (✅) and
MVP4-03's contribution-building scaffold (✅). Parallel-safe with
MVP4-03 per the gate's task sequence; lands as an inline extension
of the same backfill loop.

## Goal / Acceptance Criteria

Implement plan §7.9 conviction score — a secondary explainer metric
capped at 0–100 — and write it into `oracles_lens_signals` during
the same `compute_signal_weighted_scores` pass that MVP4-03 already
runs. No new JobRun, no second compute walk over holdings; the
existing per-holder `_HolderContribution` payload carries every
input.

Acceptance criteria:

### Formula (plan §7.9)

```
conviction_score_0_100 =
    position_importance      (max 30)
  + holding_persistence      (max 25)
  + manager_quality          (max 20)
  + recent_action            (max 15)
  + agreement                (max 10)
```

V1 component formulas (mirror the dashboard's
`_conviction_components` so the in-memory and persisted paths
agree on what each component means, even though the
signal-weighted formula deliberately differs between them):

- **position_importance** (max 30):
  `min(30, round(min(max_weight / 0.10, 1) * 20 +
                  min(top_10_count / 2, 1) * 10))`
  where `max_weight = max(portfolio_weight per holder)` and
  `top_10_count = count of holders ranking this stock in their
  top 10`.
- **holding_persistence** (max 25):
  `min(25, round(min(median_streak / 4, 1) * 25))`
  where `median_streak = median(holding_streak_quarters per
  holder)`.
- **manager_quality** (max 20):
  `min(20, round(min(avg_manager_weight, 1) * 20))`
  where `avg_manager_weight = mean(manager_signal_weight per
  holder)`.
- **recent_action** (max 15):
  `min(15, round(add_context * 15))`
  where `add_context = fraction of holders with add_intensity
  > 0` (i.e. new or added positions).
- **agreement** (max 10):
  `min(10, round(min(holder_count / 5, 1) * 10))`.

The cap on each component prevents one strong signal from
overwhelming the total. Component breakdown is written to
`oracles_lens_score_components` for drilldown UI (PO MVP4-01 D5:
component inputs must be exposable in the drilldown).

### Persistence

- Existing `oracles_lens_signals.conviction_score` column
  (already created in MVP4-01) gets populated per stock per
  backfill pass.
- New rows in `oracles_lens_score_components` keyed by
  `score_id`:
  - `component_name="conviction_position_importance"` with
    `numeric_value` = position_importance points, `evidence_json`
    carrying `max_weight` and `top_10_count`.
  - Same for `conviction_holding_persistence`,
    `conviction_manager_quality`, `conviction_recent_action`,
    `conviction_agreement`. Each row carries an `evidence_json`
    documenting the underlying inputs so the drilldown can render
    "median streak: 6 quarters → 25/25".
  - One additional row
    `component_name="conviction_total"` with the capped 0–100
    composite for easy ranking-table read.

### Pure-Function Module

- `app/services/oracles_lens/conviction_score.py` exposes:
  - `ConvictionComponents` dataclass (frozen) carrying the five
    component point values + the composite total.
  - `compute_conviction_components(contributions:
    list[_HolderContribution]) -> ConvictionComponents`. No DB
    access; consumes the same `_HolderContribution` dataclass
    MVP4-03 already builds.

### Integration

- `compute_signal_weighted_scores` in
  `app/services/oracles_lens/signal_weighted_score.py`:
  - Calls `compute_conviction_components(contributions)` for
    each stock alongside the signal-weighted sum.
  - Passes `conviction_score=components.total` into
    `_upsert_signal`.
  - Passes the components into `_replace_components` so the new
    six rows land alongside the existing manager / position
    component rows.

### Test Coverage (TDD)

- Pure-function tests for each component cap and edge cases
  (zero holders, all-unknown managers, all-top-10, all-new
  actions, etc.).
- Total composite is capped at 100.
- Integration test: after `compute_signal_weighted_scores`
  for a quarter with 3 known holders, the persisted
  `oracles_lens_signals.conviction_score` matches what the pure
  function returns for the same inputs.
- Component rows for conviction are present with the documented
  names and `evidence_json` keys.

## Scope In

- New `app/services/oracles_lens/conviction_score.py`.
- Update `compute_signal_weighted_scores` to compute + persist
  conviction inline.
- New test file
  `tests/unit/test_13f_mvp4_conviction_score.py`.

## Scope Out

- New JobRun type — conviction is a passenger on MVP4-03's
  `oracles_lens_score_backfill` job.
- Distinctive consensus (MVP4-06) and caution flags
  (MVP4-05).
- Frontend rendering (MVP4-07).
- Refactor of dashboard's in-memory `_conviction_components` —
  the dashboard's path remains unchanged; persisted-mode
  consumers (MVP4-03b) get the canonical conviction from the
  table.
- PRD edits.

## PRD / Decision References

- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §7.9
  conviction formula and component caps.
- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D3 V1 score
  surface — conviction is in V1.
- `docs/tasks/2026-05-11_13f-mvp4-01-score-schema-orm.md`:
  `oracles_lens_signals.conviction_score` column already exists.
- `docs/tasks/2026-05-11_13f-mvp4-03-signal-weighted-score.md`:
  `_HolderContribution` shape MVP4-04 consumes.

## Files Expected To Change

- `backend/app/services/oracles_lens/conviction_score.py` — new.
- `backend/app/services/oracles_lens/signal_weighted_score.py` —
  small additions to call `compute_conviction_components`, pass
  the score into `_upsert_signal`, pass components into
  `_replace_components`.
- `backend/tests/unit/test_13f_mvp4_conviction_score.py` — new.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_conviction_score.py`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_signal_weighted_score.py`
  (sibling — must stay green)
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-11: Started after MVP4-03b dashboard integration landed.
  Conviction is the second of four V1 scoring metrics; it shares
  MVP4-03's compute loop and persists into the same row.
- 2026-05-11: Wrote TDD coverage first under
  `tests/unit/test_13f_mvp4_conviction_score.py` (12 tests):
  - **Pure-function** (no DB): per-component caps (30/25/20/15/10);
    scaling on median streak; recent_action zero when nobody
    adding; agreement saturates at 5 holders; total = sum of
    components; total capped at 100 when all components maxed.
  - **DB integration**: `compute_signal_weighted_scores` writes
    `conviction_score` to `oracles_lens_signals` and inserts six
    new component rows (`conviction_position_importance`,
    `conviction_holding_persistence`, `conviction_manager_quality`,
    `conviction_recent_action`, `conviction_agreement`,
    `conviction_total`).
- 2026-05-11: Implementation:
  - New `app/services/oracles_lens/conviction_score.py` with
    `ConvictionComponents` frozen dataclass + pure
    `compute_conviction_components`.
  - `_HolderContribution` gained `holding_streak_quarters` and
    `add_intensity` so conviction can read the raw primitive
    inputs rather than re-inferring them from
    `position_signal_weight.bonus_streak` (which discards the
    sub-4-quarter precision the persistence component needs).
  - `_contributions_for_stock` already computes both values via
    MVP4-02 primitives; passing them through is a single-line
    change in the constructor call.
  - `compute_signal_weighted_scores` calls
    `compute_conviction_components(contributions)` per stock,
    passes the total into `_upsert_signal`'s new `conviction_score`
    kwarg, and passes the components dataclass into
    `_replace_components` to write the six conviction component
    rows alongside the existing manager + position rows.
  - `recent_action` reads `add_intensity > 0` directly (not the
    clamped `action_adjustment`). Rationale: conviction is about
    the underlying story; a Class A stale-recompute caveat that
    suppresses the signal-weighted `action_adjustment` should
    still let conviction count the "manager is adding" fact.
- 2026-05-11: Scope guard — no new JobRun, no new endpoint, no
  schema change (the `conviction_score` column was already created
  in MVP4-01), no frontend, no dashboard formula change, no PRD
  edits.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_conviction_score.py` -> 12 passed.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_signal_weighted_score.py tests/unit/test_13f_mvp4_dashboard_persisted_scores.py` -> 26 passed (siblings stay green).
- `docker compose exec api pytest -q` -> **719 passed** (was 707 pre-MVP4-04; +12), 0 warnings.
