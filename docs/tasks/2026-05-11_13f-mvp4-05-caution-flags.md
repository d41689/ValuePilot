# 13F MVP4-05: Caution Flags Surface

## Status

Authorized to start. Depends on MVP4-03/04 caveat collection
(already populating `oracles_lens_signals.caution_flag_codes` as a
flat string array). MVP4-05 builds the **user-facing structured
surface** on top of that flat persisted shape.

## Goal / Acceptance Criteria

Honor SME D3 caution-flags vocabulary requirements: the user-facing
caution-flag surface must consume the canonical readiness vocabulary
as a transparent pass-through alongside score-emitted row-level codes.
Each surfaced flag carries severity, scope, and a stable label so
MVP4-07 frontend can render the panel without inventing presentation
metadata.

Acceptance criteria:

### Caveat Registry (new module)

- `app/services/oracles_lens/caution_flags.py` exposes
  `CAUTION_FLAG_REGISTRY: dict[str, CaveatMetadata]` keyed on every
  caveat code that may appear in `oracles_lens_signals.caution_flag_codes`
  or in the per-holder explanation. Each entry carries:
  - `code` — the canonical user-facing string (UPPER_SNAKE_CASE).
  - `severity` — `"low"` or `"medium"` (matching score_confidence
    demotion tiers from MVP4-03 `determine_score_confidence`).
  - `scope` — `"row"` (per-holder) or `"stock"` (per-stock-aggregate).
    Per the SME note `NT_DETECTION_UNSUPPORTED` is page-level and is
    deferred to MVP4-07 frontend; MVP4-05 ships only `row` and
    `stock` scopes.
  - `label` — human-readable surface text.
- Codes covered (all from MVP3/MVP4 caveat plumbing or readiness
  vocabulary):
  - `CONFIDENTIAL_TREATMENT` (medium, row)
  - `PARTIAL_COVERAGE` (medium, row)
  - `AMENDMENTS_PENDING` (medium, row) — **new collection in this task**
  - `AMENDMENT_FAILED` (medium, row) — **new collection in this task**
  - `OWNERSHIP_CHANGES_NEEDS_RECOMPUTE` (low, row) — readiness-vocab
    alias for the score-emitted `stale_until_recompute`
  - `HISTORICAL_BACKFILL_NEEDS_VALIDATION` (low, row)
  - `NT_QUARTER_STREAK_BREAK` (medium, row)
  - `PRE_2023_PRE_HISTORY_UNAVAILABLE` (medium, row)

### Score-Emitted ↔ Readiness Vocabulary Alias

The flat persisted list may carry either spelling for the same
concept (score services emit `stale_until_recompute`; the readiness
service emits `OWNERSHIP_CHANGES_NEEDS_RECOMPUTE` per MVP3-09). The
enrichment function dedupes them into a single user-facing entry
under the canonical readiness vocabulary name (UPPER_SNAKE_CASE).

### Enrichment Function

- `enrich_caveat_codes(codes: list[str]) -> list[dict]`:
  - Maps each input code (preserving order of first occurrence) to
    its registry entry.
  - Dedupes aliases (`stale_until_recompute` and
    `OWNERSHIP_CHANGES_NEEDS_RECOMPUTE` collapse to one surface entry).
  - Returns a list of structured payloads
    `[{"code": ..., "severity": ..., "scope": ..., "label": ...}]`.
  - Unknown codes (forward-compat) are surfaced with
    `severity="unknown"`, `scope="row"`, `label=code` rather than
    silently dropped so a regression in the registry surfaces in
    review.

### New Caveat Collection Sources

- `_contributions_for_stock` (in
  `app/services/oracles_lens/signal_weighted_score.py`) appends
  caveats when `Filing13F.amendment_status` is:
  - `amendments_pending` → `AMENDMENTS_PENDING`
  - `amendment_failed` → `AMENDMENT_FAILED`
  (These already drive readiness warnings in MVP1C-1 / MVP3-09; the
  score caveat surface now mirrors them per holder.)
- Each new caveat adds to the per-holder `per_holder_caveats` list,
  flows through `_aggregate_caveats`, and lands in
  `oracles_lens_signals.caution_flag_codes`. No schema change.

### Read API Surface

- `build_oracles_lens_response` adds a `caution_flags` field per
  item containing the structured list from `enrich_caveat_codes`.
  The flat `caution_flag_codes` field is preserved for
  backwards-compatibility with anything already consuming the raw
  array (e.g. the in-memory dashboard pass).
- `dashboard.py::_apply_persisted_scores` (MVP4-03b) likewise
  attaches the structured `caution_flags` payload alongside the
  flat list when persisted mode is active.

### Tests

- Registry has every documented code; metadata fields match the
  acceptance criteria.
- `enrich_caveat_codes`:
  - dedupes `stale_until_recompute` + `OWNERSHIP_CHANGES_NEEDS_RECOMPUTE`
    into one entry under the readiness vocabulary name;
  - preserves order of first occurrence;
  - surfaces unknown codes with `severity="unknown"`.
- DB integration:
  - Filing with `amendment_status='amendments_pending'` → contributor
    contributions carry `AMENDMENTS_PENDING`; persisted
    `caution_flag_codes` array contains it; structured response
    `caution_flags` entry has `severity="medium"`, `scope="row"`.
  - Same for `amendment_failed`.
- `build_oracles_lens_response` items each include
  `caution_flags` structured list alongside the flat
  `caution_flag_codes`.

## Scope In

- New `app/services/oracles_lens/caution_flags.py`.
- Two new caveat sources in `_contributions_for_stock` based on
  `Filing13F.amendment_status`.
- Update `build_oracles_lens_response` to expose
  `caution_flags` structured field.
- Update `dashboard.py::_apply_persisted_scores` to surface the
  structured field in persisted mode.
- TDD test file
  `tests/unit/test_13f_mvp4_caution_flags.py`.

## Scope Out

- `NT_DETECTION_UNSUPPORTED` page-level banner — deferred to
  MVP4-07 frontend integration. MVP4-05 ships `row` and `stock`
  scopes only.
- New JobRun / schema migration (the existing
  `caution_flag_codes` JSONB array is sufficient).
- Class B caveat exclusion of whole holder contribution —
  filed in MVP4-03 backlog; not implemented here.
- Distinctive consensus score (MVP4-06).
- Frontend rendering (MVP4-07).
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D3 SME
  caution-flags vocabulary block.
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §7.13
  caution flags surface.
- `docs/tasks/2026-05-11_13f-mvp4-03-signal-weighted-score.md`
  Class A caveat rule (already collected per-row) and Class B
  caveat backlog (out of MVP4-05 scope).
- `docs/tasks/2026-05-11_13f-mvp3-09-readiness-integration.md`
  for the readiness vocabulary
  (`OWNERSHIP_CHANGES_NEEDS_RECOMPUTE` / `HISTORICAL_BACKFILL_NEEDS_VALIDATION`).

## Files Expected To Change

- `backend/app/services/oracles_lens/caution_flags.py` — new.
- `backend/app/services/oracles_lens/signal_weighted_score.py` —
  add amendment-status caveat collection + structured
  `caution_flags` in `build_oracles_lens_response`.
- `backend/app/services/oracles_lens/dashboard.py` — attach
  structured `caution_flags` in persisted mode.
- `backend/tests/unit/test_13f_mvp4_caution_flags.py` — new.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_caution_flags.py`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_signal_weighted_score.py tests/unit/test_13f_mvp4_dashboard_persisted_scores.py tests/unit/test_13f_mvp4_conviction_score.py`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-11: Started after MVP4-04 conviction landed. Goal is the
  user-facing surface for what MVP4-03/04 already collect, plus the
  two missing amendment caveats.
- 2026-05-11: Wrote TDD coverage first under
  `tests/unit/test_13f_mvp4_caution_flags.py` (9 tests):
  - Registry covers every canonical code (8 readiness vocab +
    `stale_until_recompute` score-emitted alias).
  - Severity tiers match `determine_score_confidence` demotion
    (low for stale/backfill-validation, medium for everyone else).
  - `enrich_caveat_codes` dedupes `stale_until_recompute` ↔
    `OWNERSHIP_CHANGES_NEEDS_RECOMPUTE` to one surface entry
    under the readiness canonical name; preserves first-occurrence
    order; surfaces unknown codes with `severity="unknown"`.
  - DB integration: filings with `amendment_status='amendments_pending'`
    or `'amendment_failed'` produce the corresponding caveat code
    on the persisted `caution_flag_codes`.
  - `build_oracles_lens_response` items expose both the flat
    `caution_flag_codes` (backwards-compat) and the new structured
    `caution_flags` array.
- 2026-05-11: Implementation:
  - New `app/services/oracles_lens/caution_flags.py` with
    `CaveatMetadata` frozen dataclass, `CAUTION_FLAG_REGISTRY`, and
    `enrich_caveat_codes`. The alias dedupe is implemented by
    pointing both `stale_until_recompute` and
    `OWNERSHIP_CHANGES_NEEDS_RECOMPUTE` at the same
    `CaveatMetadata` object; the enrichment loop tracks seen
    canonical codes by `metadata.code` so duplicates collapse.
  - Module-level caveat code constants (`CAVEAT_*`) so producer
    sites import the canonical strings by name; renaming flows
    through the codebase via the import graph.
  - `_contributions_for_stock` in signal_weighted_score.py emits
    `AMENDMENTS_PENDING` or `AMENDMENT_FAILED` per holder based on
    `Filing13F.amendment_status`. Both are added to
    `_MEDIUM_CAVEATS` so `determine_score_confidence` demotes the
    composite score's confidence appropriately.
  - `build_oracles_lens_response` exposes both
    `caution_flag_codes` (flat, backwards-compat) and
    `caution_flags` (structured) per item; also now exposes
    `conviction_score` (was a TODO stub since MVP4-03).
  - `_apply_persisted_scores` in dashboard.py also surfaces the
    structured `caution_flags` so persisted-mode responses are
    shape-compatible with the signal-weighted read helper.
- 2026-05-11: Scope guard — no schema change (the flat
  `caution_flag_codes` JSONB array remains canonical persistence),
  no new JobRun, no NT page-level banner (deferred to MVP4-07),
  no Class B caveat exclusion (still backlog).

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_caution_flags.py` -> 9 passed.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_signal_weighted_score.py tests/unit/test_13f_mvp4_dashboard_persisted_scores.py tests/unit/test_13f_mvp4_conviction_score.py` -> 38 passed (siblings stay green).
- `docker compose exec api pytest -q` -> **728 passed** (was 719 pre-MVP4-05; +9), 0 warnings.
