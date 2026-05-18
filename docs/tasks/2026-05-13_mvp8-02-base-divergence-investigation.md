# MVP8-02: Base-Formula Divergence Investigation

## Status

**Queued 2026-05-13** as a direct follow-up to MVP8-01 (Phase 3
flip). Filed per PO direction at MVP8-01 sign-off — "approve flip
+ investigate base divergence first". Not yet authorized to open;
unblocked after observation-window data lands (post-2025-Q4
scoring cycle).

## Goal

The MVP8-01 Phase 1 comparison report showed
`magnitude_diff_count=59` (24.6% of the 240-stock intersection)
with persisted scores systematically ~70% of legacy scores. This
is **scale-only**, not ranking — top-9 stocks are identical, only
position 10 swaps within tolerance. But product needs an explicit
decision on whether to normalize the base divergence so users
don't read absolute score numbers as inconsistent across the
legacy/persisted escape-hatch surfaces during the observation
window.

## Background

Two implementations of `_position_signal_weight`:

- **Legacy in-memory** (`backend/app/services/oracles_lens/dashboard.py`
  `_position_signal_weight`): base = `min(weight * 4, 1.0)` —
  amplifies small weights (e.g. 5% → 0.20 base, capped at 100%
  for ≥ 25% positions). Visualization-friendly: produces larger
  absolute scores that are easier to compare visually.
- **Persisted** (`backend/app/services/oracles_lens/base_primitives.py`
  `compute_position_signal_weight` via
  `compute_portfolio_weight`): base = raw `portfolio_weight`
  (Decimal). Weight-faithful: 5% position contributes 0.05 base,
  no cap.

Phase 2 of MVP5-03 already normalized the **action magnitudes**
between the two (new=+0.20, add=+0.10, reduce=-0.10, exit=-0.20),
but explicitly deferred the base alignment to a separate ticket
because it's a larger product-judgment call.

## D1 — Normalization direction (open)

Two candidate alignments. PO chooses one before any code change:

- **(A) Align legacy → persisted** (drop the `*4` multiplier in
  `dashboard.py:_position_signal_weight`). Score absolute values
  fall to ~70% of current legacy. Rank ordering preserved (Phase
  1 already proved this). Implementation: one-line dashboard
  edit. Downstream: the legacy `?use_persisted_scores=false`
  escape hatch produces scores in the same numeric range as
  persisted.
- **(B) Align persisted → legacy** (add a `*4`-like scaling
  factor in `compute_position_signal_weight`). Score absolute
  values rise on the persisted side. Implementation: requires
  re-running the D2 backfill against the new formula; one-line
  primitive edit. Downstream: persisted scores become more
  visualization-friendly; existing 2025-Q3 240 signals + 4822
  components need recompute.

Neither option changes rank ordering. The choice is between
"weight-faithful smaller numbers" (A) vs "visualization-friendly
larger numbers" (B).

## D2 — When to land (open)

Two timing options:

- **(A) During the observation window** — land before Phase 4
  (`?persisted=0` retirement). The legacy escape hatch is still
  live, so a normalization commit covers both paths in lockstep.
- **(B) After Phase 4** — only normalize the persisted side
  (option B above no longer applies because the legacy formula
  is deleted; option A is moot because there's nothing to align).
  Simpler scope. The trade-off: any consumer that compared
  pre-Phase-4 legacy scores to post-Phase-4 persisted scores
  sees a 30% absolute scale shift in the upgrade.

## Out-of-Scope

- The Phase 4 `?persisted=0` retirement itself (separate
  follow-up ticket queued after one full scoring cycle observation).
- Re-running the D2 backfill against any new formula (covered
  inside the chosen direction in D1).
- Changing the action-magnitude constants (already aligned in
  Phase 2 of MVP5-03).

## Dependencies

- MVP8-01 (Phase 3 flip) closed 2026-05-13. ✓
- One full scoring cycle observation window (post-2025-Q4 cycle)
  to confirm no material ranking divergence under the new
  default. Until that's done, this ticket is **queued, not
  authorized to open**.

## Files Expected To Change (after PO chooses direction)

If D1 = A:
- `backend/app/services/oracles_lens/dashboard.py` —
  `_position_signal_weight` base normalization.
- `backend/tests/unit/test_oracles_lens.py` — any tests that
  pin specific legacy score absolute values.

If D1 = B:
- `backend/app/services/oracles_lens/base_primitives.py` —
  `compute_position_signal_weight` base scaling.
- D2 backfill re-run for 2025-Q3 + any other persisted quarters.
- `backend/tests/unit/test_13f_mvp4_*` — any pinned numeric
  assertions.

## References

- `docs/tasks/2026-05-13_mvp8-01-mvp5-03-phase3-flip.md` —
  Phase 1 comparison report with the magnitude_diff_count=59
  data that motivated this ticket.
- `docs/tasks/2026-05-12_mvp5-03-formula-reconciliation.md`
  Phase 2 — the action-magnitude normalization precedent.
