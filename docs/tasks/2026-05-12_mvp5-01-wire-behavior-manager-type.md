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

## Verification Results

- Pending implementation.
