# 13F MVP5-01: Wire Behavior-Derived Manager Type Into Live Scoring

## Status

Authorized to start. First ticket of MVP 5
(`docs/tasks/2026-05-12_13f-mvp5-execution-plan.md`).

## Goal / Acceptance Criteria

The MVP4-11 manager_type taxonomy reconciliation documented a
three-tier precedence (admin → behavior → fallback_unknown) but
the live scoring path in `signal_weighted_score.py:510` calls
`resolve_manager_type(manager, derived_profile=None)` with the
behavior tier hardcoded to `None`. The precedence collapses to
two tiers in production: admin-set type if non-unknown, otherwise
`fallback_unknown=0.60`.

Real impact:

- A `long_term_fundamental` manager who has not been admin-typed
  gets weight `0.60` (unknown fallback) instead of `1.00`. Their
  signal is under-weighted by 40 %.
- A `high_turnover` manager who has not been admin-typed gets
  weight `0.60` (unknown fallback) instead of `0.30`. Their
  signal is over-weighted by 100 %.
- The MVP4-11 D2 source-label vocabulary
  (`admin` / `behavior` / `fallback_unknown`) is also
  incomplete in production output because the behavior branch
  never fires.

This ticket wires `derive_manager_signal_profile` into the live
scoring call so the three-tier precedence is real.

Acceptance criteria:

- `resolve_manager_type` is invoked with a non-None
  `derived_profile` argument in the live `_contributions_for_stock`
  loop when admin `manager_type` is `None` or `unknown`. The
  `derived_profile` is computed by calling
  `derive_manager_signal_profile` for the manager.
- Admin non-unknown `manager_type` still wins (MVP4-11
  regression coverage — already covered by
  `tests/unit/test_13f_mvp4_manager_taxonomy.py`).
- When admin `manager_type` is `unknown`, the resolver falls
  back to the behavior-derived profile, not directly to
  `fallback_unknown`.
- When the behavior derivation produces `None` (insufficient
  data) and admin is also `unknown` or `None`, the resolver
  returns `fallback_unknown=0.60`.
- The persisted `score_explanation.holder_contributions` entries
  expose `manager_type_source` for every holder
  (`admin` / `behavior` / `fallback_unknown`) so the admin
  priority queue (MVP4-07b) and the dashboard drilldown can
  surface the source.
- Tests cover all three resolution paths end-to-end through
  `compute_signal_weighted_scores`:
  1. Manager admin-typed as `long_term_fundamental` → weight
     1.00, source `admin`.
  2. Manager admin-typed as `unknown`, behavior derivation
     yields `high_turnover` → weight 0.30, source `behavior`.
  3. Manager admin-typed as `unknown`, behavior derivation
     yields `None` (insufficient holdings history) → weight
     0.60, source `fallback_unknown`.
- **Fixture audit:** every existing scoring test fixture whose
  manager has no admin `manager_type` set or has it set to
  `unknown` must be triaged. Either:
  - (a) Set an explicit admin `manager_type` on the fixture
    manager (preferred when the test isn't about the resolution
    path — keeps the test stable across resolver internals); or
  - (b) Re-baseline the expected score / weight values to
    reflect the behavior-derived output for the fixture's
    holdings shape.
  - Run the full backend pytest suite after the fixture audit;
    no test may regress silently. If a test now fails because
    the score changed, the failure must be traced to a specific
    fixture decision (a vs b) recorded in this task file.

## Scope In

- `backend/app/services/oracles_lens/signal_weighted_score.py`
  (the resolver call at line 510 plus the score_explanation
  payload).
- `backend/app/services/oracles_lens/manager_signal.py`
  (`derive_manager_signal_profile`) — confirm it's importable
  and ready; no behavior tuning in this ticket.
- `backend/app/services/oracles_lens/manager_taxonomy.py`
  (`resolve_manager_type` callers).
- `backend/tests/unit/test_13f_mvp5_01_*.py` (new) — three
  resolution-path end-to-end tests.
- Existing scoring test fixtures across MVP4-* test files —
  fixture audit per acceptance criteria.

## Scope Out

- New behavior-derivation heuristics. Use
  `derive_manager_signal_profile` as it stands; tuning is V2.
- Admin override workflow for behavior-derived results — that's
  in the MVP4-11 D5 V1-only caveat backlog.
- Frontend changes. The dashboard already reads
  `manager_type_source` via `lib/oraclesLens.js`; this ticket
  just makes the source label *correct* in production output.
- Performance work. `derive_manager_signal_profile` may hit the
  DB per manager; if that becomes a measurable problem at
  recompute time, profile + cache as a follow-up ticket.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp4-11-manager-type-taxonomy.md` —
  D1 (8-value canonical taxonomy), D2 (three-tier precedence
  + source labels), D5 (V1-only caveat).
- `docs/13f/mvp4-reviews.md` — SME #6 #6 ("FLAG critical:
  `resolve_manager_type` collapses to two tiers because
  `derived_profile=None`").
- `docs/tasks/2026-05-12_13f-mvp4-end-to-end-verification.md` —
  Eight-Reviewer Pass log accepted this as a deferred MVP5
  critical item.

## Files Expected To Change

- `backend/app/services/oracles_lens/signal_weighted_score.py`
- `backend/app/services/oracles_lens/manager_taxonomy.py` (if
  the resolver signature needs an adjustment)
- `backend/tests/unit/test_13f_mvp5_01_wire_behavior_manager_type.py`
  (new)
- Existing MVP4 scoring test fixtures across:
  - `tests/unit/test_13f_mvp4_signal_weighted_score.py`
  - `tests/unit/test_13f_mvp4_conviction_score.py`
  - `tests/unit/test_13f_mvp4_distinctive_consensus.py`
  - `tests/unit/test_13f_mvp4_caution_flags.py`
  - `tests/unit/test_13f_mvp4_dashboard_persisted_scores.py`
  - `tests/unit/test_13f_mvp4_unknown_manager_priority.py`
  - (others as discovered during the audit)
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp5_01_wire_behavior_manager_type.py`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_*.py`
  (regression check after fixture audit)
- `docker compose exec api pytest -q` (full suite green)

## Review Focus (for the MVP5-07 closing review)

- Did `derive_manager_signal_profile` actually run for at least
  one production-shape holder during scoring (not just in
  isolation tests)?
- Is admin-set `manager_type` still winning when non-unknown?
- Does the `unknown` admin value correctly delegate to behavior
  vs the bare `None` admin value?
- Are the scoring outputs reasonable on a real quarter — do
  long-term-fundamental managers now appear higher in the
  Oracle's Lens table than they did pre-fix?
- Is `manager_type_source` exposed end-to-end (DB →
  `score_explanation` → API → dashboard normalizer →
  drilldown)?

## Progress Notes

- 2026-05-12: Task spec filed per the MVP5 execution plan. No
  code changes yet; awaiting PO go-ahead before implementation
  starts.
- 2026-05-12: Implementation:
  - New helper `_derive_manager_profile` in
    `app/services/oracles_lens/signal_weighted_score.py`. Lazily
    pulls a manager's full current-quarter eligible portfolio,
    computes `portfolio_weight` + streak per holding, derives
    `turnover_proxy` from previous-quarter `stock_id` symmetric
    difference (same algorithm as the in-memory dashboard's
    `_manager_turnover_proxy`), and calls
    `derive_manager_signal_profile`. Returns the profile (which
    may have `manager_type='unknown'` — the resolver still
    falls back).
  - `_DerivedProfileCache` dict[int, Optional[Profile]] threads
    from `compute_signal_weighted_scores` down into
    `_contributions_for_stock`. Populated lazily on first hit
    per manager; subsequent stocks held by the same manager
    reuse the cached profile.
  - Inside `_contributions_for_stock`, the
    `derived_profile=None` hardcode at line 510 is replaced
    with `derived_profile = _derive_manager_profile(...)`
    triggered only when `manager.manager_type == "unknown"`.
    Admin-typed managers skip derivation entirely (cost-free
    for the common case).
  - `_build_score_explanation` now emits a
    `manager_type_source_counts` summary
    (`{"admin": N, "behavior": N, "fallback_unknown": N}`) in
    addition to the existing `primary_reasons` and
    `confidence_demotion_reasons`. Per-holder detail still
    lives in `oracles_lens_score_components.evidence_json` on
    the `manager_signal_weight` rows (already there pre-MVP5-01
    via MVP4-03).
  - Fixture audit: every existing MVP4 scoring test fixture
    admin-types its managers explicitly
    (`long_term_fundamental` or other non-unknown). The
    behavior path therefore never fires inside the MVP4-03 / 04
    / 05 / 06 test files, and they pass unchanged. The MVP4-07b
    unknown-manager-priority tests use admin `manager_type=
    "unknown"` for the manager being prioritized, but the
    priority query filters by the admin column, not the
    resolution source, so those tests also pass unchanged.

  Tests:
  - New `test_13f_mvp5_01_wire_behavior_manager_type.py` with
    4 end-to-end cases through `compute_signal_weighted_scores`:
    admin path (long_term_fundamental → weight 1.00 source
    admin), behavior path (turnover_proxy=1.0 →
    high_turnover → weight 0.30 source behavior),
    fallback_unknown (low-turnover + low-concentration +
    short-streak → unknown → weight 0.60 source
    fallback_unknown), and a cache-correctness test (manager
    held by 3 scored stocks produces identical resolution per
    stock).

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp5_01_wire_behavior_manager_type.py` -> 4 passed.
- `docker compose exec api pytest -q` -> **759 passed** (was
  755 after the MVP4-review-fixes commit `ab7afeb`; +4 new
  MVP5-01 tests, no regressions on the existing 755).
- `docker compose exec web npm run lint` -> No ESLint warnings or errors.
- `docker compose exec web npm run build` -> compiled successfully.
