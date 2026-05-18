# 13F MVP5-02: Exclude Amendment-Blocked Holder Contributions

## Status

Authorized to start. Second ticket of MVP 5
(`docs/tasks/2026-05-12_13f-mvp5-execution-plan.md`).

## Goal / Acceptance Criteria

PO + SME consensus from the MVP4 end-to-end review: when a holder's
filing has `amendment_status` of `amendments_pending` or
`amendment_failed`, the snapshot itself is potentially unreliable
(positions may change materially when the amendment lands). The
current MVP4-05 Class A treatment merely flags the caveat and lets
the contribution stay in the score with a `score_confidence`
demotion. MVP5-02 escalates to **Class B narrow scope**: the holder
contribution is excluded from the score-side aggregate entirely;
the existence of the excluded holder is still surfaced at the
page level via caution_flags + a new `excluded_holders` block in
the score explanation.

Source: PO #3 + PO #4 in `docs/13f/mvp4-reviews.md`.

Acceptance criteria:

- A holder whose filing has `amendment_status="amendments_pending"`
  is omitted from `signal_weighted_consensus_score`,
  `conviction_score`, and `distinctive_consensus_score`.
- A holder whose filing has `amendment_status="amendment_failed"`
  is omitted from the same three aggregates.
- The per-stock score response includes:
  - `excluded_holder_count: int` on the score explanation
    payload.
  - `excluded_holders: list[{manager_id, manager_canonical_name,
    exclusion_reason}]` carrying enough detail for the
    MVP5-04 drilldown render to show the exclusion without a
    new query.
  - `exclusion_reason` is one of the canonical constants
    `"AMENDMENT_PENDING_EXCLUDED"` /
    `"AMENDMENT_FAILED_EXCLUDED"`. Stable strings so frontend /
    admin code can switch on them.
- Excluded holders still propagate their `AMENDMENTS_PENDING` /
  `AMENDMENT_FAILED` caveat into `caution_flag_codes` at the
  page level, so the existing MVP4-05 caveat panel keeps the
  visibility signal. (Excluding the score contribution, not the
  user-facing notice.)
- After exclusion, if `len(included_contributions) < min_holders`
  (the existing eligibility floor), the stock is dropped from
  scoring entirely. The pre-MVP5-02 floor check at
  `signal_weighted_score.py:285` is the right hook — it already
  re-validates count after portfolio_weight derivation drops some
  holders.
- Tests pin: an `AMENDMENTS_PENDING` holder is missing from the
  aggregate; `excluded_holder_count` matches; same stock with 3
  holders (1 amendment-pending + 2 clean) still scores using the
  2 clean holders only; conviction and distinctive also drop the
  excluded holder; an over-excluded stock (post-exclusion below
  min_holders) writes no `oracles_lens_signals` row.

## Scope In

- `backend/app/services/oracles_lens/signal_weighted_score.py`
  — partition contributions vs excluded in
  `_contributions_for_stock`; thread the excluded list to
  `compute_signal_weighted_scores`; extend
  `_build_score_explanation` with `excluded_holders` /
  `excluded_holder_count`; preserve aggregate caveats so
  `caution_flag_codes` still surfaces the codes.
- `backend/tests/unit/test_13f_mvp5_02_amendment_exclusion.py`
  (new) — 5 end-to-end cases per acceptance criteria.
- This task file.

## Scope Out

- UI rendering of the excluded-holders drilldown — MVP5-04.
- NT (`coverage_type=notice_reported_elsewhere`),
  combination-report (`PARTIAL_COVERAGE`), and confidential
  treatment exclusion. Stay caveat-only; revisit V2.
- Unresolved-CUSIP exclusion. **Already covered** by the
  pre-existing `cusip_mapping_status == "linked"` filter in
  `_contributions_for_stock`; verified during the MVP5-02 spec
  pass. No code change needed.
- Conviction / distinctive formula changes. They consume the
  partitioned `contributions` list; the existing math is
  correct over the included subset.

## PRD / Decision References

- `docs/13f/mvp4-reviews.md` — PO #3 #4 (Class B narrow: amendments
  only in MVP5; defer NT / combination / confidential to V2).
- `docs/tasks/2026-05-11_13f-mvp4-05-caution-flags.md` — original
  Class A vs Class B distinction.
- `docs/tasks/2026-05-12_13f-mvp5-execution-plan.md` — MVP5-02
  scope.

## Files Expected To Change

- `backend/app/services/oracles_lens/signal_weighted_score.py`
- `backend/tests/unit/test_13f_mvp5_02_amendment_exclusion.py` (new)
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp5_02_amendment_exclusion.py`
- `docker compose exec api pytest -q`

## Review Focus (for the MVP5-07 closing review)

- Are amendment-blocked holders ALWAYS excluded from
  signal-weighted / conviction / distinctive (not just one of
  the three)?
- Does the eligibility floor re-check fire correctly when
  exclusion drops count below `min_holders=3`?
- Is the `caution_flag_codes` page-level signal still set
  even when the holder is excluded? (Investors must see "this
  stock has a holder with a pending amendment" even if that
  holder doesn't contribute to the score.)
- Are `excluded_holders` records stable across recompute runs?
  (Same manager + same amendment status should produce the same
  exclusion_reason, same manager_canonical_name.)

## Progress Notes

- 2026-05-12: Task spec filed. CUSIP-unresolved verified
  already excluded by `cusip_mapping_status == "linked"`
  pre-MVP5-02; scope stays amendments-only.
- 2026-05-12: Implementation:
  - New `_ExcludedHolder` frozen dataclass next to
    `_HolderContribution` in
    `signal_weighted_score.py`, carrying `manager_id`,
    `manager_canonical_name`, `exclusion_reason`, and
    `caveats`.
  - New module-level constants
    `EXCLUSION_REASON_AMENDMENT_PENDING` /
    `EXCLUSION_REASON_AMENDMENT_FAILED` so frontend / admin
    consumers can switch on stable strings.
  - `_contributions_for_stock` partitions the holder loop:
    when the holder's filing has
    `amendment_status="amendments_pending"` or
    `"amendment_failed"`, the holder goes into the
    ``excluded`` list with `caveats` carrying their
    AMENDMENTS_PENDING / AMENDMENT_FAILED code; otherwise the
    holder builds a normal `_HolderContribution`. Returns a
    `(contributions, excluded)` tuple.
  - `compute_signal_weighted_scores` unpacks the tuple; the
    `len(contributions) < min_holders` floor check at the
    pre-existing hook re-validates the INCLUDED count (the
    score is over the included subset). Stocks that fall below
    the floor post-exclusion are dropped — no
    `oracles_lens_signals` row written.
  - `_aggregate_caveats` now unions caveats from BOTH
    contributions and excluded holders so AMENDMENTS_PENDING /
    AMENDMENT_FAILED still surface in
    `caution_flag_codes` at the page level even though the
    holder's contribution was dropped.
  - `_build_score_explanation` gains an optional
    `excluded` kwarg and emits two new fields in the score
    explanation payload: `excluded_holder_count: int` and
    `excluded_holders: list[{manager_id, manager_canonical_name,
    exclusion_reason}]`. The shape is stable (empty list /
    zero count when nothing is excluded).
  - Conviction (MVP4-04) and distinctive (MVP4-06) consume
    the same `contributions` list, so they automatically drop
    excluded holders without any formula change.
  - Fixture re-baseline: three MVP4-05 caution-flag tests and
    one MVP4-review-fix demotion-reasons test seeded
    1 amendment-blocked + 2 clean holders (3 total). Post-
    MVP5-02 the included count is 2 < min_holders=3 → no
    signal → tests fail. Each test bumped to 3 clean holders
    (1 excluded + 3 included = 3 above floor) with an inline
    comment explaining why.
  - CUSIP-unresolved exclusion verified already covered by the
    pre-existing `cusip_mapping_status == "linked"` filter
    in `_contributions_for_stock`. No new code needed.

  Tests:
  - New `test_13f_mvp5_02_amendment_exclusion.py` with 5
    end-to-end cases through `compute_signal_weighted_scores`:
    AMENDMENTS_PENDING exclusion, AMENDMENT_FAILED exclusion,
    over-excluded eligibility floor (signal skipped entirely),
    conviction / distinctive consistency (a control stock with
    3 clean holders and a treatment stock with the same 3 plus
    1 amendment-pending holder produce IDENTICAL conviction +
    distinctive + signal-weighted scores), and a mixed-exclusion
    case (1 pending + 1 failed + 3 clean) verifying both
    exclusion_reason values surface correctly.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp5_02_amendment_exclusion.py` -> 5 passed.
- `docker compose exec api pytest -q` -> **764 passed** (was
  759 after MVP5-01; +5 new MVP5-02 tests; the 4 MVP4-05
  fixture re-baselines covered above pass under the new
  contract).
- `docker compose exec web npm run lint` -> No ESLint warnings or errors.
- `docker compose exec web npm run build` -> compiled successfully.
