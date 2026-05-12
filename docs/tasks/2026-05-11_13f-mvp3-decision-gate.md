# 13F MVP3 Decision Gate

## Goal / Acceptance Criteria

Define the MVP 3 scope and decision record before any resilience/backfill implementation begins.

Acceptance criteria:
- Enumerate all PRD §17 MVP 3 backlog items.
- Close or explicitly defer MVP 3 pre-implementation decisions.
- Capture follow-ups carried from MVP 2 final acceptance.
- Produce an approval checklist for Tech Lead / human owner before MVP3-01 starts.
- Do not implement any MVP 3 feature in this task.

## Scope In

- MVP 3 decision record and recommendations.
- Backlog sequencing proposal.
- Explicit scope-in / scope-out boundaries.
- Follow-up tracking for MVP 2 acceptance notes.

## Scope Out

- Schema migrations.
- Full historical backfill implementation.
- Batch reparse jobs.
- CUSIP corporate action temporal mapping UI.
- Filing-level value-unit override implementation.
- Data integrity validation job implementation.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §17: MVP 3 resilience and backfill scope.
- `docs/prd/13f_automation_and_resilience_prd.md` §20: MVP 3 pre-implementation `value_unit_override` decision.
- `docs/tasks/2026-05-09_13f-automation-development-plan.md` MVP 3 backlog.
- `docs/tasks/2026-05-11_13f-mvp2-end-to-end-verification.md` residual MVP 3 follow-ups.

## Files Likely To Change

- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md`

## Tests First

This is a documentation / decision-gate task. No code tests are expected. If the gate later authorizes implementation, each MVP3 task must create its own TDD task log.

## Docker Verification Commands

- Not required for this documentation-only decision gate.

## Review Gate

Tech Lead / human owner should review:
- MVP 3 scope boundaries.
- Decision record D1-D6 below.
- Whether MVP3-01 may begin.

## MVP 3 Data Safety Principles

- Any MVP 3 job that changes product-facing historical data must create an auditable before/after impact summary.
- Historical data interpretation must not be changed silently; parse-run current pointers, holdings, ownership changes, readiness, and user-visible aggregates need traceable deltas.
- Broad reparse and backfill must run behind validation reports, preview / confirmation, and recovery paths.

## Decision Record

### D1. Full Historical Backfill Strategy

Decision: MVP 3 production historical backfill starts at `DEFAULT_BACKFILL_START_QUARTER=2023-Q1` by default. Pre-2023-Q1 backfill is out of default production scope and may run only as an admin-triggered dry-run / validation mode for a curated manager-quarter subset with explicit approval.

Implementation constraints for the relevant MVP 3 task:
- Backfill must use the same SEC client, rate limiter, job runs, and raw document storage path as MVP 1/2 ingestion.
- Backfill should be resumable by manager, quarter, and accession.
- Backfill must not overwrite existing parse runs or holdings; it should create new parse runs and preserve audit history.
- Backfill should include dry-run / preview mode before enqueueing broad jobs.
- Backfilled quarters must enter `needs_validation` or equivalent non-ready state until validation jobs pass.

Rationale:
- PRD §19 already closes the default backfill start at 2023-Q1.
- Pre-2023 filings carry higher value-unit parsing and schema variability risk and should be treated as a separate validation-first phase.

### D2. CUSIP Source / Dataroma Legacy Surface

Decision: Scope out PRD §17 `Dataroma CUSIP 来源` from MVP 3. Dataroma must not be used as a CUSIP or security-identity source in MVP 3 or later unless a future PRD explicitly reclassifies it with evidence and provenance rules. MVP 3 keeps OpenFIGI / verified mapping workflows as the primary CUSIP-to-stock path and treats legacy Dataroma code as manager-discovery or cleanup scope only.

Rationale:
- MVP 2 verification confirmed OpenFIGI-backed mapping is the current contract.
- Dataroma holdings do not expose CUSIP and should not be used as an authoritative security identifier source.
- This is a PRD §17 scope change and must remain explicit in the approval checklist.

Implementation constraints for the relevant MVP 3 task:
- Any retained Dataroma client/stub should be explicitly documented as non-authoritative for CUSIP mapping.
- Retained compatibility wrappers must use `legacy` / `non_authoritative` naming and must not appear as CUSIP-source choices in new admin UI.
- If not needed, remove or deprecate legacy `enrich_from_dataroma` naming to avoid future source confusion.

Implementation choice:
- MVP3-01 should decide whether to remove legacy wrappers or retain compatibility wrappers with clearer legacy / non-authoritative naming.

### D3. Controlled Reparse and Batch Reparse

Decision: MVP 3 must define a controlled reparse contract before shipping batch reparse jobs. Batch reparse must not ship until baseline validation jobs exist, can run before and after reparse, and can report parse-run, current-pointer, and ownership-change drift.

Implementation constraints for the relevant MVP 3 task:
- Batch reparse must use explicit job-run records and lock keys.
- Reparse must preserve parse-run audit history and current-pointer semantics.
- Admin actions must require preview / confirmation before broad enqueue.
- Reparse should not silently activate results that fail readiness or amendment rules.
- Reparse must produce a before/after impact summary covering filings affected, parse runs created, active current pointers changed, holdings rows changed, ownership changes invalidated/recomputed, and readiness-level impact.

Implementation choice:
- MVP3-05 should default to quarter reparse before manager reparse. Manager reparse may be added after the quarter workflow is proven because it can affect a broader cross-quarter surface.
- 2026-05-11 supersede note: MVP3-05 review accepted shipping both quarter and manager scopes together at the **service layer**, because controlled reparse is a per-filing safety unit and both scopes share the same execution path (only the candidate query differs); manager-scope isolation tests cover the contract. The "quarter-first" ordering applies to the **admin UI rollout** instead: the future admin endpoint / dashboard for batch reparse must ship the quarter surface before exposing manager surface to admins.

### D4. CUSIP Corporate Action Temporal Mapping UI

Decision: MVP 3 corporate-action temporal mapping requires manual admin confirmation. OpenFIGI metadata and SEC issuer data may be shown as supporting evidence, but no source may auto-confirm temporal mapping in MVP 3.

Implementation constraints for the relevant MVP 3 task:
- UI may confirm/supersede CUSIP mappings and set temporal validity.
- UI must not automatically adjust historical `value_usd`, shares, or portfolio weights.
- User-facing Oracle's Lens should continue to label heuristic corporate action signals as possible/uncertain unless confirmed by mapping state.
- Confirmed temporal mapping should invalidate affected `ownership_changes` and require recomputation, not mutate existing change rows silently.
- Admin confirmation must require an evidence / reason note; it cannot be a confirmation-only click with no provenance.

Rationale:
- Temporal mapping changes security identity continuity and can transform exit/new-position signals into same-security identifier changes. MVP 3 should keep that correction human-reviewed and auditable.

### D5. Filing-Level Value Unit Override

Decision: MVP 3 should use both a filing-level effective override pointer and a separate override audit table.

Implementation constraints for the relevant MVP 3 task:
- Overrides must be filing-scoped, not manager-scoped.
- `filings_13f` should store the current effective override summary / pointer.
- A separate `filing_value_unit_overrides` audit table should store every override event, including prior parser rule, new override value, reason, evidence, reviewer, timestamp, reparse result, and status.
- Override changes must force a controlled reparse path; they must not mutate existing parsed holdings in place.
- Admin UI must show original parser rule, override value, reviewer, timestamp, and affected accession.
- No override takes effect for product-facing data until controlled reparse completes and validation passes.
- Value-unit override is an exception workflow; normal parsing should remain schema/spec-version driven.

Rationale:
- Query paths need an efficient effective override pointer, while auditability requires an immutable event history.

### D6. Data Integrity Validation Jobs

Decision: MVP 3 validation findings must be persisted as quality reports. Alerts may be emitted for P1/P2 findings, but alerts are not the source of truth.

Initial validation candidates:
- Orphan running parse runs / expired leases.
- Active filing without current parse run where one is expected.
- `ownership_changes` rows whose current/previous holdings no longer match active parse runs.
- CUSIP mappings with overlapping effective ranges.
- Stock-holder aggregation count semantics (`direct_holder_count` vs consensus-filtered count).
- Filing value-unit sanity checks, including suspicious 1000x value jumps, extreme quarter-over-quarter reported value changes, and parser-rule mismatches.
- Existing SQLAlchemy rollback warning in duplicate fingerprint test should be cleaned up as test infrastructure debt.

Report fields should include:
- `validation_run_id`, `rule_code`, `severity`, `entity_type`, `entity_id`, `quarter`, `manager_id`, `accession_number`, `status`, `first_seen_at`, `last_seen_at`, `resolved_at`, and `resolution_note`.

## Proposed MVP 3 Task Sequence

Sequence rationale: resolve source naming ambiguity, validation persistence, and override auditability before broad reparse/backfill work. Historical backfill remains in MVP 3 scope only after cleanup, validation, override, controlled reparse, and batch reparse contracts are ready.

1. `MVP3-01 Legacy Dataroma Surface Cleanup / Naming Clarification`
2. `MVP3-02 Data Integrity Validation Jobs and Persisted Quality Reports`
3. `MVP3-03 Filing-Level Value Unit Override Schema / Audit Contract`
4. `MVP3-04 Controlled Reparse Contract and Before/After Impact Summary`
5. `MVP3-05 Batch Reparse Jobs by Quarter / Manager`
6. `MVP3-06 CUSIP Corporate Action Temporal Mapping Admin UI`
7. `MVP3-07 Validation-Gated Historical Backfill Job Contract and Preview`

## Approval Checklist

- [x] D1 historical backfill default range approved as 2023-Q1 onward; pre-2023-Q1 limited to explicitly approved curated dry-run / validation mode.
- [x] D2 human owner explicitly approves scoping out PRD §17 `Dataroma CUSIP 来源` from MVP 3 as a PRD scope change, and approves legacy / non-authoritative wrapper cleanup or renaming.
- [x] D3 controlled reparse contract and before/after impact summary requirement approved before batch reparse.
- [x] D4 manual-confirmation-only corporate action evidence policy approved.
- [x] D5 filing-level `value_unit_override` storage/audit model approved; filing-scoped per PRD §20, uses effective filing pointer plus separate audit table, and does not modify or replace the existing manager-level `value_unit_override=infer` column.
- [x] D6 persisted quality reports approved as validation source of truth, with alerts only as notification surfaces.
- [x] Human owner approved MVP 3 scope freeze and exclusions.
- [x] MVP3-01 Legacy Dataroma Surface Cleanup / Naming Clarification explicitly approved to start.

## Progress Notes

- 2026-05-11: Created after MVP 2 final acceptance approved entry into MVP 3 decision gate / backlog planning.
- 2026-05-11: Applied Tech Lead review feedback: D2 now explicitly flags the PRD §17 Dataroma CUSIP source removal as a human-owner scope-change decision, D1 is framed against the PRD §19 2023-Q1 default, D3 now depends on value-unit override and validation readiness, and the task sequence now puts Dataroma cleanup / validation / override before batch reparse and historical backfill.
- 2026-05-11: Applied product owner review feedback: closed D1/D2/D4/D5/D6 as product decisions, added the MVP 3 data-safety principle for auditable before/after summaries, tightened D3 validation and impact-summary gates, split controlled reparse from batch reparse, and moved historical backfill to the final MVP 3 task.
- 2026-05-11: Product owner re-review approved MVP3-01 to start. Added accepted P2 refinements: quarter-first reparse default, required corporate-action evidence / reason notes, value-unit sanity validation candidate, validation-gated backfill naming, and explicit MVP 3 scope-freeze checklist approval.
- 2026-05-11: MVP3-05 review supersede on D3 implementation choice: quarter-first sequencing applies to the future admin UI rollout, not the service layer. MVP3-05 ships both scopes at the service layer with full per-scope test coverage; the admin endpoint / dashboard task must still expose quarter scope before manager scope.

## Verification Results

- Documentation-only decision gate; Docker verification not required.
