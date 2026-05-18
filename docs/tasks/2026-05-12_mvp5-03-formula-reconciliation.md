# 13F MVP5-03: Reconcile Oracle's Lens Persisted vs Legacy Formula

## Status

Authorized to start. Third ticket of MVP 5
(`docs/tasks/2026-05-12_13f-mvp5-execution-plan.md`).

**Phased ticket.** Phases 1 + 2 ship in this commit; Phase 3
(server-default flip) is gated on PO sign-off after Phase 1 runs
against production data; Phase 4 (`?persisted=0` retirement) is a
post-observation follow-up.

**Dependency satisfied:** MVP5-01 deployed
(`c3887be`, behavior-derived manager_type wired). The Phase 1
comparison runs against post-MVP5-01 persisted scores so the
ranking diff reflects only the formula divergence, not the
behavior-path correction.

## Goal / Acceptance Criteria

Three reviewer threads converged on the same divergence (TL #1 #5,
PO #3 #3 / PO #4 #3, SME #6 #1):

- Dashboard's `_position_signal_weight` uses
  `min(weight*4, 1.0)` as the position base.
- MVP4-03 persisted scorer uses raw `portfolio_weight`.
- Dashboard's action magnitudes are inverted vs the persisted
  constants: dashboard has `new=+0.10, add=+0.20, reduce=-0.20`;
  persisted has `new=+0.20, add=+0.10, reduce=-0.10`.
- Dashboard exit isn't in the in-memory path at all.
- Frontend defaults to persisted (MVP4-07a); backend
  `/api/v1/oracles-lens?use_persisted_scores` server default is
  still `False`, so direct API consumers (curl / Postman / future
  programmatic clients) hit the legacy formula by default.
- The `?persisted=0` debug flag is a one-release escape hatch with
  no defined retirement condition.

### Phase 1 — Comparison utility (this commit)

- New admin endpoint
  `GET /api/v1/admin/13f/oracles-lens/formula-comparison`.
- Computes per-stock legacy vs persisted scores for the latest
  scored quarter (or an explicit `?quarter=` override).
- Returns:
  - `quarter`, `score_version`, `total_stocks_compared`.
  - Per-stock array with
    `{stock_id, legacy_score, persisted_score, score_delta,
    legacy_rank, persisted_rank, divergence_flags}`.
  - `divergence_flags` is a list of stable string codes:
    - `"TOP10_RANK_SWAP"` — stock in top 10 under one path
      but below position 20 under the other.
    - `"MAGNITUDE_DIFF_25_PCT"` — `|legacy - persisted| /
      max(|legacy|, |persisted|) > 0.25`.
- Summary counters at the top: `top10_swap_count`,
  `magnitude_diff_count`.
- Admin-gated via existing `AdminUser` dep.
- Tests pin the divergence detection logic with synthetic data
  (legacy and persisted scores manually seeded; the endpoint
  produces correct flags + counts).

### Phase 2 — Action-magnitude normalization (this commit)

- Update `dashboard.py:_position_signal_weight` so the action
  adjustments match `constants.py`:
  - `new=+0.20` (was `+0.10`)
  - `add=+0.10` (was `+0.20`)
  - `reduce=-0.10` (was `-0.20`)
- Add an `exit` branch with `-0.20` to align with
  `ACTION_ADJUSTMENT_EXIT` (legacy currently has no exit
  branch; the persisted path treats exit symmetrically with
  new).
- Inline comment recording the SME #6 #1 rationale: a new
  position is a more decisive signal than adding to an existing
  one; reduce is a softer signal than full exit.

### Phase 3 — PO sign-off + server-default flip (NOT in this commit)

- PO runs the Phase 1 comparison utility against the current
  active production quarter.
- Comparison report archived to
  `docs/tasks/YYYY-MM-DD_mvp5-03-comparison-report.md`.
- PO reviews; sign-off recorded inline.
- After sign-off: flip
  `read_oracles_lens` `use_persisted_scores: bool = Query(False)`
  → `Query(True)`. One-line change; no schema migration.

### Phase 4 — `?persisted=0` retirement (post-observation)

- Defined retirement condition: "after one full scoring cycle
  under the persisted default with no material ranking
  divergence observed."
- "Material" = the Phase 1 utility shows zero `TOP10_RANK_SWAP`
  flags on the current active quarter under the new default.
- Retirement ticket filed separately for the post-observation
  window; Phase 4 does NOT execute in MVP5-03.

## Scope In (Phase 1 + 2)

- `backend/app/services/oracles_lens/formula_comparison.py` (new) — the
  comparison helper.
- `backend/app/api/v1/endpoints/thirteenf_admin.py` — new admin
  route under the existing `admin_router`.
- `backend/app/services/oracles_lens/dashboard.py` — Phase 2
  action-magnitude normalization in `_position_signal_weight`
  + new `exit` branch.
- `backend/tests/unit/test_13f_mvp5_03_formula_comparison.py` (new).
- This task file.

## Scope Out

- **Phase 3 server-default flip.** Awaits PO sign-off after Phase
  1 runs on production data.
- **Phase 4 `?persisted=0` retirement.** Filed as a post-observation
  follow-up ticket.
- **Deleting the legacy `_stock_payload` formula entirely.** Keeps
  the legacy path available for one full release cycle so the
  `?persisted=0` debug escape hatch works during observation.
- **Base divergence (`min(weight*4, 1.0)` vs raw `portfolio_weight`).**
  MVP5-03 normalizes action magnitudes only. The base divergence
  is a larger numeric-scale change that requires explicit PO call
  on whether to align legacy toward persisted's raw `portfolio_weight`
  (smaller absolute scores, more weight-faithful) or to keep the
  legacy `*4` multiplier (larger absolute scores, more
  visualization-friendly). Capture the question in the Phase 1
  comparison report; defer the resolution to a follow-up MVP5
  ticket if PO chooses normalization.

## PRD / Decision References

- `docs/13f/mvp4-reviews.md` — TL #1 #5, PO #3 #3, PO #4 #3,
  SME #6 #1.
- `docs/tasks/2026-05-12_13f-mvp5-execution-plan.md` — MVP5-03
  phased acceptance criteria.

## Files Expected To Change

- `backend/app/services/oracles_lens/formula_comparison.py` (new)
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/app/services/oracles_lens/dashboard.py`
- `backend/tests/unit/test_13f_mvp5_03_formula_comparison.py` (new)
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp5_03_formula_comparison.py`
- `docker compose exec api pytest -q`

## Review Focus (for the MVP5-07 closing review)

- Does the comparison endpoint cover the intersection of stocks
  (both legacy and persisted scores present) and report the
  un-intersection separately?
- Are the divergence-flag thresholds the right shape for product
  judgment (25% magnitude, top10/below20 rank swap)?
- Is the Phase 2 action-magnitude change reflected in dashboard
  legacy output (a `?persisted=0` request now serves the
  normalized actions)?
- Is the server-default flip (Phase 3) gated by visible PO
  sign-off or is it accidentally landing in the same commit?

## Progress Notes

- 2026-05-12: Task spec filed. Phases 1 + 2 to ship together;
  Phase 3 waits for PO comparison run + sign-off.
- 2026-05-12: Phase 1 + Phase 2 implementation:
  - New module
    `backend/app/services/oracles_lens/formula_comparison.py`.
    Exposes a pure-function `compute_formula_comparison(legacy_by_stock,
    persisted_by_stock)` for divergence detection and a
    session-aware `build_formula_comparison(session, quarter, ...)`
    wrapper. Pure function is unit-tested with synthetic data;
    wrapper is integration-tested via the admin endpoint.
  - Divergence detection: per-stock items include
    `legacy_score`, `persisted_score`, `score_delta` (persisted -
    legacy), `legacy_rank`, `persisted_rank` (both 1-indexed,
    ties broken by stock_id ascending for determinism), and
    `divergence_flags`. Two stable flag codes:
    `TOP10_RANK_SWAP` (top 10 under one path / below position 20
    under the other) and `MAGNITUDE_DIFF_25_PCT` (`|legacy -
    persisted| / max(|legacy|, |persisted|) > 0.25`,
    division-by-zero safe).
  - Summary counters at the payload level:
    `total_stocks_compared`, `legacy_only_count`,
    `persisted_only_count`, `top10_swap_count`,
    `magnitude_diff_count`. The items array is the
    intersection; un-intersected stocks roll up to the
    `*_only_count` fields.
  - New admin endpoint
    `GET /api/v1/admin/13f/oracles-lens/formula-comparison`
    with optional `?quarter=` override. Admin-gated via the
    existing `AdminUser` dep. Defaults to the latest scored
    quarter (mirrors MVP4-07b `unknown-manager-priority` shape).
  - Phase 2: action magnitudes in
    `dashboard.py:_position_signal_weight` aligned to
    `constants.ACTION_ADJUSTMENT_*`: `new=+0.20`,
    `add=+0.10`, `reduce=-0.10`, new `exit=-0.20` branch. SME
    #6 #1 rationale captured inline.

  Tests:
  - `test_13f_mvp5_03_formula_comparison.py` with 8 cases:
    - 6 pure-function tests covering the divergence-flag
      thresholds (exact 25% inclusive cutoff, zero-score
      guard, top10 swap detection, intersection-only items
      array, score-delta sign convention).
    - 2 endpoint integration tests: admin-only gating and a
      seeded-stock end-to-end payload-shape assertion.

  Phase 3 (server-default flip) and Phase 4 (`?persisted=0`
  retirement) are NOT in this commit. They are tracked in the
  Sign-Off / Retirement Tracker sections below.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp5_03_formula_comparison.py` -> 8 passed.
- `docker compose exec api pytest -q` -> **772 passed** (was 764
  after MVP5-02; +8 new MVP5-03 tests; no regressions on the
  existing 764 — the Phase 2 action-magnitude change does not
  break any existing dashboard test because none of them pinned
  the absolute magnitudes).
- `docker compose exec web npm run lint` -> No ESLint warnings or errors.
- `docker compose exec web npm run build` -> compiled successfully.

## Phase 1 Validation Outcome (2026-05-12)

Phase 1 comparison utility validated against dev DB. PO
direction recorded:

- **Phase 1 utility contract**: validated. Empty-state call
  against current dev DB returns
  `{"quarter": null, "score_version": "v1.0",
  "total_stocks_compared": 0, ..., "items": []}` — the
  correct shape for "no persisted scores yet."
- **Synthetic divergence detection**: validated. A 30-stock
  seeded scenario (legacy_rank=23 / persisted_rank=1 on
  stock_id 1; legacy=1.0 / persisted=0.68 on stock_id 3)
  produces the expected
  `TOP10_RANK_SWAP=1, MAGNITUDE_DIFF_25_PCT=2` flags with
  correct per-item attribution.
- **Dev DB not suitable for PO sign-off**: all 4022 holdings
  in dev are `cusip_mapping_status="pending_mapping"` and
  `holding_attribution_status=None`. The persisted scoring
  path therefore writes zero `oracles_lens_signals` rows in
  dev, so a real legacy-vs-persisted ranking comparison
  cannot run there. **This is a dev-environment data state,
  not an MVP5-03 code defect.**

**Status as recorded by the PO:**

- MVP5-03 Phase 1: **Accepted** (utility complete and
  technically validated).
- Synthetic divergence validation: **Accepted**.
- Dev DB real-data sign-off: **Not applicable**.
- Phase 3 server-default flip: **Pending staging/prod
  comparison**.
- Dev CUSIP linking pipeline: backlogged under
  `docs/tasks/2026-05-12_backlog-dev-cusip-linking-fixture.md`;
  **not an MVP5 blocker**.

**Explicit instruction to engineering:** do not flip the
backend server default until the PO has reviewed a real-data
comparison report from a staging/prod environment that has
linked CUSIPs and at least one persisted scoring backfill
applied.

## Phase 3 Sign-Off Tracker

- [x] Phase 1 comparison utility deployed (2026-05-12).
- [x] Phase 1 utility contract validated against dev DB
      (empty-state + synthetic divergence detection, see
      "Phase 1 Validation Outcome" above).
- [ ] Comparison report run against the current active
      production quarter (**blocked on staging/prod
      environment with linked CUSIPs + at least one
      persisted scoring backfill**). Output archived to
      `docs/tasks/YYYY-MM-DD_mvp5-03-comparison-report.md`.
- [ ] PO reviewed the comparison report; sign-off recorded
      inline.
- [ ] Server default flipped from `Query(False)` to
      `Query(True)`.

## Phase 4 Retirement Tracker

- [ ] One full scoring cycle observed under the persisted default.
- [ ] No `TOP10_RANK_SWAP` flags on the current active quarter.
- [ ] `?persisted=0` debug flag retirement ticket filed and
      shipped.
