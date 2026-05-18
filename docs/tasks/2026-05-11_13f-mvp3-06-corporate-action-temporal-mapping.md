# 13F MVP3-06: CUSIP Corporate Action Temporal Mapping Admin Backend

## Goal / Acceptance Criteria

Implement the **service contract and admin HTTP endpoints** that let an admin manually
confirm or supersede a CUSIP temporal mapping after a corporate action, with mandatory
evidence + reason notes and an auditable invalidation of affected `ownership_changes`.

Per MVP3 decision-gate D4, MVP 3 corporate-action temporal mapping requires manual admin
confirmation. No source may auto-confirm; the action must not silently mutate historical
`value_usd`, shares, or portfolio weights.

Acceptance criteria:
- A confirm action requires all of: canonical CUSIP, new ticker / issuer (optional), an
  `effective_from_quarter`, an `evidence_url`, a `reason`, and a `reviewer_id`. Missing
  evidence or reason rejects with a typed error.
- Confirming a temporal mapping creates a new `cusip_ticker_map` row with
  `mapping_status='confirmed'`, `source='manual'`, `confidence='manual'`, the
  effective-quarter pair, the evidence URL and reason, and the reviewer audit fields.
- An optional `prior_mapping_id` flag supersedes a previously-confirmed mapping: that
  row's `mapping_status` flips to `'superseded'` and its `effective_to_quarter` is set
  to the quarter immediately before the new mapping's `effective_from_quarter`.
- Overlapping `[effective_from_quarter, effective_to_quarter]` intervals for the same
  canonical CUSIP (excluding the explicitly-superseded prior) are rejected. The check
  runs under the existing 64-bit advisory-lock helper.
- A `null` `effective_to_quarter` is treated as open-ended in both lookup and overlap
  detection.
- A preview action returns the count and sample of affected `ownership_changes` rows
  without mutating any state.
- A confirm action does **not** mutate existing `ownership_changes`, holdings,
  `value_usd`, `shares`, or `portfolio_weight_pct` rows. Instead it persists a
  `QualityReport13F` event and one `QualityFinding13F` per affected change row with a
  fixed rule code (`OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`). Downstream
  recomputation pipelines (MVP3-05 controlled / batch reparse, future MVP2 ownership
  recompute) pick the work up from there.
- Admin endpoints are gated by the existing `AdminUser` dependency. Non-admin requests
  are rejected before any service code runs.
- Relevant tests pass in Docker.

## Scope In

- New service module `thirteenf_corporate_action_mapping`:
  - `preview_corporate_action_confirmation(session, *, cusip, effective_from_quarter,
    effective_to_quarter=None) -> dict` — pure read; returns affected ownership_changes
    rows summary and overlap diagnostics.
  - `confirm_corporate_action_mapping(session, *, cusip, new_ticker, new_issuer_name,
    effective_from_quarter, effective_to_quarter=None, evidence_url, reason, reviewer_id,
    prior_mapping_id=None) -> dict` — full confirm contract.
- New admin endpoints under `/api/v1/admin/13f/cusips/corporate-actions`:
  - `POST .../preview`
  - `POST .../confirm`
- Pydantic request/response schemas under `app/schemas/thirteenf_corporate_action.py`.
- Reuse the existing `pg_try_advisory_xact_lock` helper from
  `app/services/cusip_enrichment.py`. No new advisory lock infrastructure.
- Test coverage: confirm-with-evidence happy path, missing-evidence rejection,
  missing-reason rejection, overlap rejection, supersede sets prior row's
  `effective_to_quarter` and status, null end-quarter open-ended handling,
  affected-ownership-changes findings written without mutating change rows,
  preview-no-mutation, non-admin caller rejected at the endpoint layer.

## Scope Out

- Full frontend admin UI dashboard pages for corporate-action review. Backend response
  shapes ship first; UI is a follow-up task once contracts are reviewed (per dev plan
  G4: "Backend response shapes must stabilize before frontend work").
- Auto-confirmation from OpenFIGI or SEC issuer feeds (D4: manual only).
- Mutation of historical `ownership_changes`, holdings, or computed totals (D4: no
  silent rewrites).
- Heuristic Oracle's Lens corporate-action signal changes (D4: user-facing labelling
  stays "possible/uncertain" until confirmed; MVP3-06 does not touch the Oracle's Lens
  surface).
- Batch corporate-action confirmation (out of scope; one confirmation per admin click).
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D4: manual confirmation, evidence
  required, no silent mutation, ownership_changes invalidated and require recomputation.
- `docs/prd/13f_automation_and_resilience_prd.md` §8.3, §14: temporal `cusip_ticker_map`
  schema, partial unique index, advisory-lock overlap rules.
- `docs/prd/13f_automation_and_resilience_prd.md` §9.2.2 / §9.2.3: corporate-action
  caveat semantics on Oracle's Lens.
- `docs/prd/13f_automation_and_resilience_prd.md` §13: admin endpoint shape conventions.
- `docs/prd/13f_automation_and_resilience_prd.md` §10: quality findings as audit trail.

## Files Expected To Change

- `backend/app/services/thirteenf_corporate_action_mapping.py` — new service module.
- `backend/app/schemas/thirteenf_corporate_action.py` — request/response schemas.
- `backend/app/api/v1/endpoints/thirteenf_admin.py` — new endpoints.
- `backend/tests/unit/test_13f_mvp3_corporate_action_mapping.py` — new tests.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_corporate_action_mapping.py`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-11: Started after MVP3-05 batch reparse contract was approved as the recompute
  consumer for MVP3-06 invalidation. Scope limited to backend service contract + admin
  HTTP endpoints; the admin UI dashboard pages are an explicit follow-up so that the
  response shapes can stabilize per G4 before frontend work.
- 2026-05-11: Wrote TDD coverage first under
  `tests/unit/test_13f_mvp3_corporate_action_mapping.py` (10 tests):
  - `evidence_url` / `reason` required (empty / whitespace rejected).
  - Confirm writes the audit fields (source=manual, mapping_status=confirmed,
    confidence=manual, evidence_url, mapping_reason, reviewed_by/reviewed_at,
    effective_from/to_quarter).
  - Supersede prior confirmed mapping → status flips to `superseded`,
    `effective_to_quarter` set to the quarter immediately before the new mapping's
    `effective_from_quarter`.
  - Overlap rejection for both closed-range and null-end-quarter cases.
  - Affected `ownership_changes` flagged via `QualityFinding13F`
    (`rule_code=OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`,
    severity=warning, status=open) tied to a single `QualityReport13F` event;
    the ownership_change rows themselves are **not** mutated (no change to
    `change_status` / `current_value_usd` / shares / weights), honoring D4.
  - Preview is pure read (no mapping/report/finding mutation).
  - Admin endpoint rejects non-admin caller; happy-path confirm endpoint records
    `reviewed_by = current_user.id`.
- 2026-05-11: Implemented `thirteenf_corporate_action_mapping`:
  - `preview_corporate_action_confirmation` runs no commit; returns affected
    ownership-change count + sample (up to 25), plus a list of mapping IDs that
    overlap the proposed window.
  - `confirm_corporate_action_mapping` acquires the canonical-CUSIP 64-bit
    advisory lock (PRD §14), validates evidence + reason, validates quarter
    format/ordering, detects overlap (excluding any explicit
    `prior_mapping_id`), supersedes the prior row when given, inserts the new
    `confirmed` mapping row, persists one `QualityReport13F` + N
    `QualityFinding13F` entries for affected ownership-change rows, then
    commits as a single transaction.
  - Quarter math reuses the same `previous_quarter` semantics as the admin
    dashboard's `previous_quarter_label`; not imported because the service
    only needs the canonical 1→Q4 carry rule.
- 2026-05-11: Added Pydantic schemas
  (`app/schemas/thirteenf_corporate_action.py`) and admin endpoints under
  `/api/v1/admin/13f/cusips/corporate-actions/{preview,confirm}`. The confirm
  endpoint takes `reviewer_id` from the authenticated `AdminUser` rather than
  trusting the client payload.
- 2026-05-11: Scope guard — no frontend UI added, no auto-confirmation source
  introduced, no `ownership_changes` mutation, no PRD edits.

- 2026-05-11: Applied review followups from Tech Lead + Product Owner reviews:
  - Tech Lead blocking-before-MVP3-07: added
    `test_confirm_rejects_prior_mapping_for_different_cusip` covering the
    cross-CUSIP supersede invariant. The service guard already exists
    (`prior_mapping.cusip != cusip → CorporateActionMappingError`); the test
    pins the behavior so a future refactor cannot remove it silently. The test
    also asserts that the foreign mapping is left untouched and no new mapping
    is created for the target CUSIP — the rejection happens before any session
    writes.
  - Tech Lead recommendation (not accepted, deferred per TL's own guidance):
    advisory lock helper deduplication into a shared util. TL note: "Recommend
    extracting only if a third service adopts the pattern — not worth the
    refactor now." Currently used in two places (cusip_enrichment and
    thirteenf_corporate_action_mapping); will revisit when a third caller
    appears.
  - Tech Lead recommendation (not accepted, deferred per TL's own guidance):
    add `corporate_action` to QualityReport13F.status vocabulary. TL note:
    "Defer until there's a concrete filtering use case that rule_code can't
    handle." Currently `rule_code=OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`
    is sufficient for downstream filtering; introducing a new status value
    requires a migration and dashboard vocabulary alignment for zero current
    benefit.
  - Product Owner D4 review: all seven gates PASS. No follow-ups requested.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_corporate_action_mapping.py` -> 11 passed (10 initial + 1 review followup).
- `docker compose exec api pytest -q` -> 599 passed (was 598; +1), 2 pre-existing SQLAlchemy rollback warnings (`test_duplicate_fingerprint_within_same_parse_run_raises` from MVP1B and `test_enqueue_translates_unique_index_race_into_scope_error` from MVP3-05) — neither introduced by this task.
