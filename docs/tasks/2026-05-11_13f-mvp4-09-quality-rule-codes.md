# 13F MVP4-09: Shared QualityFinding rule_code Constants Module

## Status

Authorized as a parallel pre-MVP4-03 prerequisite per the MVP4 decision
gate's revised task sequence. No external dependencies.

## Goal / Acceptance Criteria

Eliminate rule_code drift across the three MVP3+ services that
emit `QualityFinding13F` rows and the three downstream services that
read those rows. The canonical strings already exist (TL1 fix in MVP3
end-to-end review normalized them to UPPER_SNAKE_CASE); this task
consolidates them into one importable module so MVP4-03 onward
cannot accidentally introduce a fourth spelling.

Acceptance criteria:

- New module `app/services/thirteenf_quality_codes.py` exposes three
  canonical constants with the **exact existing string values** (DB
  rows already use them; changing the values would require a
  migration):
  - `VALUE_UNIT_SANITY = "VALUE_UNIT_SANITY"`
  - `OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION = "OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION"`
  - `HISTORICAL_BACKFILL_NEEDS_VALIDATION = "HISTORICAL_BACKFILL_NEEDS_VALIDATION"`
- Every existing private copy is replaced with an import from the
  new module:
  - `app/services/edgar_quality.py` —
    `VALUE_UNIT_SANITY_RULE_CODE` (writer side).
  - `app/services/thirteenf_corporate_action_mapping.py` —
    `CORPORATE_ACTION_RULE_CODE` (writer side).
  - `app/services/thirteenf_historical_backfill.py` —
    `HISTORICAL_BACKFILL_RULE_CODE` (writer side).
  - `app/services/thirteenf_readiness.py` —
    `_RECOMPUTE_FINDING_RULE_CODE` /
    `_BACKFILL_FINDING_RULE_CODE` (reader side).
  - `app/services/thirteenf_admin_dashboard.py` —
    `_MVP3_RECOMPUTE_FINDING_RULE_CODE` /
    `_MVP3_BACKFILL_FINDING_RULE_CODE` (reader side).
  - `app/services/oracles_lens/base_primitives.py` —
    `_RECOMPUTE_FINDING_RULE_CODE` /
    `_BACKFILL_FINDING_RULE_CODE` (MVP4-02 reader side).
- Public-facing module-level aliases in writer modules can be kept
  if they help readability (e.g. `CORPORATE_ACTION_RULE_CODE` may
  alias `quality_codes.OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`),
  but the source of truth must be the new module.
- No behavior change. String values are identical to current
  production rows.
- Relevant tests pass in Docker; the full backend suite continues
  to pass without modification (existing tests assert against the
  string literals which remain unchanged).

## Scope In

- New `app/services/thirteenf_quality_codes.py`.
- Replacement of private copies in the six listed modules.
- One focused test asserting the canonical constants exist and have
  the documented values.

## Scope Out

- **Pre-MVP3 lowercase rule_codes** (`reconciliation`, `cusip_format`,
  `negative_values`, `duplicate_fingerprint`, `period_alignment`,
  `parse_failure`). The TL1 fix in MVP3 end-to-end review explicitly
  left these for a future task because renaming after prod rows
  exist requires a DB migration. Documented here for traceability.
- **Caveat code vocabulary** (`PARTIAL_COVERAGE`, `NT_QUARTER_STREAK_BREAK`,
  `stale_until_recompute`, `HISTORICAL_BACKFILL_NEEDS_VALIDATION`,
  `PRE_2023_PRE_HISTORY_UNAVAILABLE`) from
  `oracles_lens/base_primitives.py`. Different semantic concept (row
  caveat vs finding rule_code); kept local until a separate caveat
  consumer appears. Note: the string
  `HISTORICAL_BACKFILL_NEEDS_VALIDATION` happens to be the same
  literal for both vocabularies — the new shared module is the
  source of truth either way, and consumers in either vocabulary
  can import it.
- MVP4-10 conftest savepoint hardening (separate parallel ticket).
- MVP4-11 manager_type taxonomy reconciliation (separate parallel
  ticket).
- PRD edits, schema migrations.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D6: this is the
  promoted-to-MVP4-backlog ticket flagged by the Tech Lead end-to-end
  review.
- `docs/tasks/2026-05-11_13f-mvp3-end-to-end-verification.md` TL1
  remediation: the canonical UPPER_SNAKE_CASE form of
  `VALUE_UNIT_SANITY` was normalized there; this task only moves the
  constant, not its value.

## Files Expected To Change

- `backend/app/services/thirteenf_quality_codes.py` — new.
- `backend/app/services/edgar_quality.py` — replace local constant
  with import.
- `backend/app/services/thirteenf_corporate_action_mapping.py` — same.
- `backend/app/services/thirteenf_historical_backfill.py` — same.
- `backend/app/services/thirteenf_readiness.py` — same.
- `backend/app/services/thirteenf_admin_dashboard.py` — same.
- `backend/app/services/oracles_lens/base_primitives.py` — same.
- `backend/tests/unit/test_13f_mvp4_quality_rule_codes.py` — new.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_quality_rule_codes.py`
- `docker compose exec api pytest -q` (full suite — assert no behavior
  regression).

## Progress Notes

- 2026-05-11: Started after MVP4-02 base primitives landed. Picking
  MVP4-09 next because (a) it's pre-MVP4-03 prereq, (b) zero
  external deps, (c) closes the "three private copies" smell
  introduced by MVP4-02.
- 2026-05-11: Audited the codebase for duplicate rule_code literals.
  Found six modules holding private copies of the same three
  canonical strings (MVP3-02 / MVP3-06 / MVP3-07 writers + MVP3-09
  readiness / admin dashboard readers + MVP4-02 scoring primitive
  reader). Confirmed all six strings matched exactly before
  consolidation.
- 2026-05-11: Wrote TDD coverage first under
  `tests/unit/test_13f_mvp4_quality_rule_codes.py` (3 tests):
  - canonical constants have documented values;
  - the three writer modules' local aliases (kept for readability)
    resolve to the canonical strings;
  - the canonical module exposes exactly the three expected
    constants (defensive — flags any future drift in a single
    place).
- 2026-05-11: Implemented `app/services/thirteenf_quality_codes.py`
  with the three constants and explicit out-of-scope notes for
  pre-MVP3 lowercase codes and the caveat-code vocabulary.
- 2026-05-11: Replaced private copies in:
  - `edgar_quality.py`: kept `VALUE_UNIT_SANITY_RULE_CODE` local
    alias because it reads naturally next to `report.add(...)`;
    now bound to the canonical `VALUE_UNIT_SANITY`.
  - `thirteenf_corporate_action_mapping.py`: same pattern with
    `CORPORATE_ACTION_RULE_CODE`.
  - `thirteenf_historical_backfill.py`: same pattern with
    `HISTORICAL_BACKFILL_RULE_CODE`.
  - `thirteenf_readiness.py`: private `_RECOMPUTE_FINDING_RULE_CODE` /
    `_BACKFILL_FINDING_RULE_CODE` now imported under those exact
    names from the canonical module (zero call-site churn). Kept
    `RECOMPUTE_WARNING_CODE` / `BACKFILL_WARNING_CODE` local because
    the warning-code vocabulary is distinct from rule_codes
    (`OWNERSHIP_CHANGES_NEEDS_RECOMPUTE` plural vs
    `OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`).
  - `thirteenf_admin_dashboard.py`: private
    `_MVP3_RECOMPUTE_FINDING_RULE_CODE` /
    `_MVP3_BACKFILL_FINDING_RULE_CODE` now imported under those
    exact names.
  - `oracles_lens/base_primitives.py`: private MVP4-02-introduced
    copies now imported under their existing names.
- 2026-05-11: Caveat-code constants in
  `oracles_lens/base_primitives.py`
  (`HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT`, etc.) left local
  per task scope. They share a string with the new rule_code module
  by coincidence (D3 explicitly requires the same canonical
  spelling), but the vocabularies are conceptually distinct.
- 2026-05-11: Scope guard — no behavior change, no schema, no API,
  no frontend, no PRD edits.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_quality_rule_codes.py` -> 3 passed.
- `docker compose exec api pytest -q` -> 669 passed (was 666 pre-MVP4-09; +3), 4 SQLAlchemy rollback warnings (unchanged from MVP4-02 baseline).
