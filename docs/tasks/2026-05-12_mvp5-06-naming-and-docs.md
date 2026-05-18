# 13F MVP5-06: Documentation + Naming Cleanup

## Status

Authorized to start. Sixth ticket of MVP 5
(`docs/tasks/2026-05-12_13f-mvp5-execution-plan.md`).

Pure maintenance — no behavior changes, no schema changes, no new
endpoints. Closes three carry-over flags from the MVP4 review.

## Goal / Acceptance Criteria

Three surgical pieces of cleanup:

1. **Rename `anti_crowding_factor` → `quality_agreement_factor`**
   in the distinctive-consensus implementation, dataclass field,
   docstrings, evidence_json keys, component_name written to
   `oracles_lens_score_components`, and the matching tests.
   Formula unchanged; this is a naming-only change per SME #6 #3.

   The previous name was misleading: the factor measures the
   *average manager_signal_weight* across the holder cluster
   (i.e. "are the holders high-quality managers who agree?"),
   not crowding volume or AUM concentration.

2. **Add a `CLAUDE.md` architecture note** codifying the
   two-pattern rule for write-conflict handling:
   - ORM upsert (`INSERT ... ON CONFLICT DO UPDATE`) for
     idempotent rewrites where last-writer-wins is correct.
     Used by `oracles_lens_signals` per MVP4-01.
   - `IntegrityError → typed error` for exclusive-lock guards
     where the conflict is a meaningful "another job already
     active" signal. Used by JobRun `lock_key` races per
     MVP3-05 / MVP3-07.

   Source: TL #1 follow-up + TL #2 backlog #4.

3. **Record the SME-vs-SME tier resolution** for
   `PRE_2023_PRE_HISTORY_UNAVAILABLE` in plan §7.13 so the
   medium-tier placement is documented and can't get re-litigated
   at GA. SME #5 wanted it in `_LOW_CAVEATS`; SME #6 argued
   medium is correct because pre-2023 history unavailability
   degrades the *cross-quarter delta* (streak / action_intensity)
   but the *current-quarter snapshot* itself is still valid.
   SME #6 prevailed; this is the canonical position.

The pre-existing ratio-design comment at `compute_portfolio_weight`
(MVP4 review-fix commit `ab7afeb`) is **already done**; no re-do.

## Scope In

- `backend/app/services/oracles_lens/distinctive_consensus.py`
  — variable + dataclass field + docstring rename.
- `backend/app/services/oracles_lens/signal_weighted_score.py`
  — component_name string + evidence_json key updates in
  `_replace_components`.
- `backend/tests/unit/test_13f_mvp4_distinctive_consensus.py`
  — test names + field assertions.
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §7.11
  formula + §7.13 PRE_2023 tier note.
- `docs/tasks/2026-05-12_13f-mvp4-end-to-end-verification.md`
  — update the SME #6 #3 follow-up flag entry to record it
  resolved.
- `docs/tasks/2026-05-12_post-mvp4-roadmap.md` — update the
  backlog mention.
- `CLAUDE.md` — architecture note.
- This task file.

## Scope Out

- Backfilling existing
  `oracles_lens_score_components` rows that carry the legacy
  `distinctive_anti_crowding_factor` component_name string. The
  table is rewritten on every recompute via the existing
  `_replace_components` DELETE-then-INSERT pattern, so legacy
  strings disappear at the next scoring run for each signal.
  Document this in the rename block; no migration needed.
- Plan-doc-wide rename pass on legacy "anti-crowding" prose
  outside §7.11 — those references are historical context and
  rewriting them would erase the rename audit trail.
- Wider docs reorganization. Surgical edits only.

## PRD / Decision References

- `docs/13f/mvp4-reviews.md` — SME #6 #3 (rename), SME #6 #4
  (PRE_2023 tier reasoning), TL #1 / TL #2 (architecture note).
- `docs/tasks/2026-05-12_13f-mvp5-execution-plan.md` — MVP5-06
  scope.

## Files Expected To Change

- `backend/app/services/oracles_lens/distinctive_consensus.py`
- `backend/app/services/oracles_lens/signal_weighted_score.py`
- `backend/tests/unit/test_13f_mvp4_distinctive_consensus.py`
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md`
- `docs/tasks/2026-05-12_13f-mvp4-end-to-end-verification.md`
- `docs/tasks/2026-05-12_post-mvp4-roadmap.md`
- `CLAUDE.md`
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_distinctive_consensus.py`
- `docker compose exec api pytest -q` (full regression — the
  rename touches the component_name string read by one test).

## Progress Notes

- 2026-05-12: Task spec filed. Surveyed: 7 code references in
  the distinctive-consensus path, 1 test reference to the
  component_name string, no frontend references.
- 2026-05-12: Implementation:
  - `distinctive_consensus.py`: renamed
    `anti_crowding_factor` → `quality_agreement_factor` on the
    `DistinctiveConsensusResult` dataclass, the local variable
    in `compute_distinctive_consensus`, and the docstring.
    Added a parenthetical "(Renamed from `anti_crowding_factor`
    in MVP5-06 per SME #6 #3 ...)" so the rename audit trail
    is visible to future readers.
  - `signal_weighted_score.py`: renamed
    `"distinctive_anti_crowding_factor"` →
    `"distinctive_quality_agreement_factor"` (the
    `oracles_lens_score_components.component_name` value) and
    the `"anti_crowding_factor"` key in the
    `distinctive_total` evidence_json. Inline comment notes
    that existing production rows carrying the legacy string
    will be rewritten on the next recompute via the existing
    `_replace_components` DELETE-then-INSERT pattern.
  - `test_13f_mvp4_distinctive_consensus.py`: bulk rename of
    7 references (`anti_crowding_factor` → `quality_agreement_factor`
    in function names, dataclass field assertions, and the
    component_name string check).
  - `docs/plans/13f_oracles_lens_dashboard_product_plan.md`
    §7.11: formula updated to `quality_agreement_factor`;
    added a "MVP5-06 naming note" block explaining the
    rename + SME #6 #3 rationale. Historical "anti-crowding"
    prose preserved beneath the formula so the rename audit
    trail stays intact.
  - `docs/plans/13f_oracles_lens_dashboard_product_plan.md`
    §7.13: added a new §7.13.1 subsection "Caveat Tier
    Resolution (MVP5-06 record)" documenting the SME-vs-SME
    decision to keep `PRE_2023_PRE_HISTORY_UNAVAILABLE` in
    `_MEDIUM_CAVEATS` (SME #6's argument prevailed: pre-2023
    history unavailability degrades only the cross-quarter
    delta; the snapshot itself remains valid; low-tier
    demotion would overclaim the loss).
  - `CLAUDE.md`: new "Write-conflict handling: upsert vs
    IntegrityError" section codifying the two-pattern rule
    per TL #1 / TL #2 follow-up. Records when to use each
    pattern, the anti-pattern to avoid (upserting a JobRun
    "steals" the mutex), and a hint to colocate the rationale
    with the unique-constraint definition in new models.
  - `docs/tasks/2026-05-12_post-mvp4-roadmap.md` +
    `docs/tasks/2026-05-12_13f-mvp4-end-to-end-verification.md`:
    SME #6 #3 (rename) and TL #2 backlog #4 / TL #1 follow-up
    (CLAUDE.md architecture note) flag entries updated to
    "**Resolved in MVP5-06**".

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_distinctive_consensus.py` -> 13 passed (all rename references resolved).
- `docker compose exec api pytest -q` -> **781 passed** (unchanged from MVP5-05; no new tests in MVP5-06, no regressions).
- `docker compose exec web npm run lint` -> No ESLint warnings or errors.
- `docker compose exec web npm run build` -> compiled successfully.
- `grep -rn "anti_crowding" backend/ frontend/` -> two matches remain, both inline rename-audit comments (intentional).
