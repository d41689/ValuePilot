# 13F MVP4-06: Distinctive Consensus Score

## Status

Authorized to start. Depends on MVP4-02 primitives (✅), MVP4-03
signal-weighted score (✅), and MVP4-04 conviction (✅) only for the
shared `_HolderContribution` payload. Persisted alongside the other
scores in the same MVP4-03 backfill pass — no new JobRun.

## Goal / Acceptance Criteria

Implement plan §7.11 distinctive consensus score — an
advanced-sort metric that penalizes signal-weighted score for
weak / crowded / low-conviction consensus. V1 conservative
calibration; factors clamped to `[0, 1]` so
`distinctive ≤ signal_weighted` by construction.

Acceptance criteria:

### Formula (plan §7.11)

```
distinctive_consensus_score =
    signal_weighted_consensus_score
  × concentration_factor
  × persistence_factor
  × anti_crowding_factor
```

V1 calibration (each factor in `[0, 1]`):

- **concentration_factor** = `min(aggregate_weight / 0.10, 1.0)`.
  `aggregate_weight` is the sum of per-holder
  `portfolio_weight` across contributing holders. Saturates at
  10% aggregate — a stock where holders collectively put 10%+ of
  their portfolios into it gets full credit.
- **persistence_factor** = `min(median_streak / 4, 1.0)`. Median
  `holding_streak_quarters` across contributors. Saturates at 4
  quarters — matches the streak bonus threshold in
  MVP4-03 `position_signal_weight`.
- **anti_crowding_factor** = `min(avg_manager_signal_weight, 1.0)`.
  Mean of `manager_signal_weight` across contributors. Saturates
  at 1.0 — high-signal manager mix gets full credit.

Plan §7.11 explicit guidance:
- "anti-crowding is a weak proxy and should not be used as a hard
  default ranking determinant" — distinctive is an **advanced
  sort option**, default sort stays `signal_weighted_consensus`.
- "do not emit `crowded_mega_cap`; emit `low_conviction_consensus`
  or `low_signal_quality` instead" — V1 has no market-cap data,
  so the factors are computed but no `crowded_mega_cap` flag is
  emitted. Future task (when market-cap data lands) can layer it.

### Persistence

- Writes to `oracles_lens_signals.distinctive_consensus_score`
  (column already exists from MVP4-01).
- Adds four component rows to `oracles_lens_score_components`:
  - `distinctive_concentration_factor` — numeric_value =
    concentration_factor, evidence_json carries
    `aggregate_weight`.
  - `distinctive_persistence_factor` — numeric_value =
    persistence_factor, evidence_json carries
    `median_streak_quarters`.
  - `distinctive_anti_crowding_factor` — numeric_value =
    anti_crowding_factor, evidence_json carries
    `avg_manager_signal_weight`.
  - `distinctive_total` — numeric_value = the composite, plus
    evidence_json carrying `signal_weighted_consensus_score` so
    the drilldown can render
    "signal-weighted 3.12 × 0.82 conc × 0.75 persist × 0.92
    quality = 1.77 distinctive".

### Pure Function

- `app/services/oracles_lens/distinctive_consensus.py`:
  - `DistinctiveConsensusResult` frozen dataclass carrying the
    composite + three factors.
  - `compute_distinctive_consensus(signal_weighted_score:
    Decimal, contributions: list[_HolderContribution]) ->
    DistinctiveConsensusResult`. No DB access; consumes the same
    `_HolderContribution` payload MVP4-03/04 already build.
  - Empty `contributions` → composite 0 and zero factors (avoids
    division-by-zero on empty mean).
  - Result factors are `Decimal` for arithmetic precision; the
    composite is the product of signal_weighted × all three
    factors.

### Integration

- `compute_signal_weighted_scores` calls
  `compute_distinctive_consensus` inline after conviction; passes
  the composite into `_upsert_signal` via a new
  `distinctive_consensus_score` kwarg; passes the dataclass into
  `_replace_components` to write the four new rows.

### Read Surface

- `build_oracles_lens_response` already exposes
  `distinctive_consensus_score` (was a passthrough of the
  persisted column since MVP4-03). No code change needed there;
  the column is now populated and the existing serializer reads
  it.

### Test Coverage (TDD)

- Pure-function:
  - concentration_factor saturates at 10% aggregate weight.
  - persistence_factor saturates at 4-quarter median.
  - anti_crowding_factor caps at 1.0 (high-signal mix) and is
    low for unknown-heavy mix.
  - Composite = signal × concentration × persistence × anti_crowding
    (within `Decimal` tolerance).
  - Empty contributions → composite 0, all factors 0.
- DB integration:
  - After backfill, `oracles_lens_signals.distinctive_consensus_score`
    is populated.
  - The 4 distinctive component rows are present in
    `oracles_lens_score_components`.
  - `build_oracles_lens_response` items expose a non-null
    `distinctive_consensus_score` for scored stocks.

## Scope In

- New `app/services/oracles_lens/distinctive_consensus.py`.
- Update `compute_signal_weighted_scores` to compute + persist
  distinctive inline.
- New test file
  `tests/unit/test_13f_mvp4_distinctive_consensus.py`.

## Scope Out

- New JobRun — distinctive is a passenger on MVP4-03's
  `oracles_lens_score_backfill`.
- `crowded_mega_cap` flag (requires market-cap data, deferred).
- `low_conviction_consensus` / `low_signal_quality` row caveat
  codes — those belong with the MVP4-05 caution-flags surface
  but the V1 plan note ("weak proxy") argues for deferring
  emission until distinctive is observed in production. Filed
  as a future surface task; MVP4-06 just produces the number.
- Frontend rendering (MVP4-07).
- PRD edits.

## PRD / Decision References

- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §7.11
  distinctive consensus.
- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D3
  "Distinctive Consensus Score (§7.11) is proposed as advanced
  sort, off by default" — PO clarification: visible-but-off in UI
  dropdown.
- `docs/tasks/2026-05-11_13f-mvp4-01-score-schema-orm.md`:
  `oracles_lens_signals.distinctive_consensus_score` column
  already exists.
- `docs/tasks/2026-05-11_13f-mvp4-03-signal-weighted-score.md`:
  `_HolderContribution` shape MVP4-06 consumes.

## Files Expected To Change

- `backend/app/services/oracles_lens/distinctive_consensus.py` — new.
- `backend/app/services/oracles_lens/signal_weighted_score.py` —
  small additions to call `compute_distinctive_consensus`, pass
  the score into `_upsert_signal`, pass the dataclass into
  `_replace_components`.
- `backend/tests/unit/test_13f_mvp4_distinctive_consensus.py` — new.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_distinctive_consensus.py`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_signal_weighted_score.py tests/unit/test_13f_mvp4_conviction_score.py tests/unit/test_13f_mvp4_caution_flags.py tests/unit/test_13f_mvp4_dashboard_persisted_scores.py`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-11: Started after MVP4-05 caution-flags landed. Distinctive
  is the fourth and final V1 score metric; once landed, all four
  V1 columns will be persisted and exposed via the read helper,
  unblocking MVP4-07 frontend.
- 2026-05-11: Wrote TDD coverage first under
  `tests/unit/test_13f_mvp4_distinctive_consensus.py` (13 tests):
  - Pure-function factor caps (concentration saturates at 10%
    aggregate weight; persistence saturates at 4-quarter median;
    anti-crowding caps at 1.0 high-signal mix; uses median not
    mean for persistence).
  - Composite = signal × three factors (within Decimal
    tolerance).
  - High-signal stock distinctive ≈ signal; low-signal stock
    distinctive collapses far below signal.
  - Empty contributions → zero composite + zero factors.
  - DB integration: `oracles_lens_signals.distinctive_consensus_score`
    persisted ≤ signal_weighted_consensus_score; four
    `distinctive_*` component rows present.
  - Read helper exposes a non-null `distinctive_consensus_score`.
- 2026-05-11: Implementation:
  - New `app/services/oracles_lens/distinctive_consensus.py`
    with `DistinctiveConsensusResult` frozen dataclass and pure
    `compute_distinctive_consensus`. Factors clamped to `[0, 1]`
    so distinctive ≤ signal_weighted by construction —
    distinctive cannot *enhance* a score, only soften one that
    looks artificially strong.
  - `compute_signal_weighted_scores` calls
    `compute_distinctive_consensus(signal_weighted_score=total,
    contributions=...)` per stock; passes the composite into
    `_upsert_signal`'s new `distinctive_consensus_score` kwarg.
  - `_replace_components` writes four distinctive component rows
    with evidence_json carrying the raw inputs
    (`aggregate_weight`, `median_streak_quarters`,
    `avg_manager_signal_weight`, and the per-factor breakdown on
    `distinctive_total`).
- 2026-05-11: Read helper integration was a no-op — the
  `distinctive_consensus_score` field was already a passthrough of
  the persisted column since MVP4-03; the column is now
  populated.
- 2026-05-11: Scope guard — no new JobRun, no schema change, no
  `crowded_mega_cap` / `low_conviction_consensus` flag emission
  (deferred per plan §7.11 "V1 weak proxy" guidance), no
  frontend, no PRD edits.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_distinctive_consensus.py` -> 13 passed.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_signal_weighted_score.py tests/unit/test_13f_mvp4_conviction_score.py tests/unit/test_13f_mvp4_caution_flags.py tests/unit/test_13f_mvp4_dashboard_persisted_scores.py` -> 47 passed (all four V1-score-service siblings stay green).
- `docker compose exec api pytest -q` -> **741 passed** (was 728 pre-MVP4-06; +13), 0 warnings.
