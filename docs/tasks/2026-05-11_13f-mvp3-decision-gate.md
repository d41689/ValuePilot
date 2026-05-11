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
- Decision recommendations D1-D6 below.
- Whether MVP3-01 may begin.

## Decision Draft

### D1. Full Historical Backfill Strategy

Recommendation: MVP 3 should implement full historical backfill as an operational job family, not as ad hoc scripts.

Implementation constraints for MVP3-01+:
- Backfill must use the same SEC client, rate limiter, job runs, and raw document storage path as MVP 1/2 ingestion.
- Backfill should be resumable by manager, quarter, and accession.
- Backfill must not overwrite existing parse runs or holdings; it should create new parse runs and preserve audit history.
- Backfill should include dry-run / preview mode before enqueueing broad jobs.

Open decision:
- What historical range should MVP 3 target first: all available SEC history, last 5 years, or a curated manager/quarter subset?

### D2. CUSIP Source / Dataroma Legacy Surface

Recommendation: Do not revive Dataroma as a CUSIP source. MVP 3 should keep OpenFIGI / verified mapping workflows as the primary CUSIP-to-stock path, and treat legacy Dataroma code as manager-discovery or cleanup scope only.

Rationale:
- MVP 2 verification confirmed OpenFIGI-backed mapping is the current contract.
- Dataroma holdings do not expose CUSIP and should not be used as an authoritative security identifier source.

Implementation constraints for MVP3-01+:
- Any retained Dataroma client/stub should be explicitly documented as non-authoritative for CUSIP mapping.
- If not needed, remove or deprecate legacy `enrich_from_dataroma` naming to avoid future source confusion.

Open decision:
- Should MVP 3 remove legacy Dataroma CUSIP enrichment wrappers, or retain compatibility wrappers with clearer OpenFIGI naming?

### D3. Batch Reparse by Quarter / Manager

Recommendation: MVP 3 should add batch reparse jobs only after the backfill job contract is stable.

Implementation constraints for MVP3-01+:
- Batch reparse must use explicit job-run records and lock keys.
- Reparse must preserve parse-run audit history and current-pointer semantics.
- Admin actions must require preview / confirmation before broad enqueue.
- Reparse should not silently activate results that fail readiness or amendment rules.

Open decision:
- Should MVP 3 ship quarter reparse first, manager reparse first, or both behind the same admin workflow?

### D4. CUSIP Corporate Action Temporal Mapping UI

Recommendation: MVP 3 should design corporate-action mapping UI as an admin review surface, not an automatic correction engine.

Implementation constraints for MVP3-01+:
- UI may confirm/supersede CUSIP mappings and set temporal validity.
- UI must not automatically adjust historical `value_usd`, shares, or portfolio weights.
- User-facing Oracle's Lens should continue to label heuristic corporate action signals as possible/uncertain unless confirmed by mapping state.

Open decision:
- What evidence source is acceptable for confirming a CUSIP corporate action: admin manual review only, OpenFIGI metadata, SEC issuer data, or another licensed source?

### D5. Filing-Level Value Unit Override

Recommendation: MVP 3 should implement filing-level `value_unit_override` only after defining the audit and reparse protocol.

Implementation constraints for MVP3-01+:
- Overrides must be filing-scoped, not manager-scoped.
- Override changes must force a controlled reparse path; they must not mutate existing parsed holdings in place.
- Admin UI must show original parser rule, override value, reviewer, timestamp, and affected accession.

Open decision:
- Should `value_unit_override` live on `filings_13f`, a separate override audit table, or both?

### D6. Data Integrity Validation Jobs

Recommendation: MVP 3 should add validation jobs that produce admin-facing reports before adding more automated repair behavior.

Initial validation candidates:
- Orphan running parse runs / expired leases.
- Active filing without current parse run where one is expected.
- `ownership_changes` rows whose current/previous holdings no longer match active parse runs.
- CUSIP mappings with overlapping effective ranges.
- Stock-holder aggregation count semantics (`direct_holder_count` vs consensus-filtered count).
- Existing SQLAlchemy rollback warning in duplicate fingerprint test should be cleaned up as test infrastructure debt.

Open decision:
- Should validation findings be stored as persisted quality reports, emitted as alert summaries, or both?

## Proposed MVP 3 Task Sequence

1. `MVP3-01 Historical Backfill Job Contract and Preview`
2. `MVP3-02 Filing-Level Value Unit Override Schema / Audit Contract`
3. `MVP3-03 Batch Reparse Jobs by Quarter / Manager`
4. `MVP3-04 CUSIP Corporate Action Temporal Mapping Admin UI`
5. `MVP3-05 Data Integrity Validation Jobs and Admin Reports`
6. `MVP3-06 Legacy Dataroma Surface Cleanup / Naming Clarification`

## Approval Checklist

- [ ] D1 historical backfill initial range approved.
- [ ] D2 CUSIP source / Dataroma legacy decision approved.
- [ ] D3 batch reparse sequencing approved.
- [ ] D4 corporate action evidence policy approved.
- [ ] D5 value-unit override storage/audit model approved.
- [ ] D6 validation report persistence / alerting model approved.
- [ ] MVP3-01 explicitly approved to start.

## Progress Notes

- 2026-05-11: Created after MVP 2 final acceptance approved entry into MVP 3 decision gate / backlog planning.

## Verification Results

- Documentation-only decision gate; Docker verification not required.
