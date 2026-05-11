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

Implementation constraints for the relevant MVP 3 task:
- Backfill must use the same SEC client, rate limiter, job runs, and raw document storage path as MVP 1/2 ingestion.
- Backfill should be resumable by manager, quarter, and accession.
- Backfill must not overwrite existing parse runs or holdings; it should create new parse runs and preserve audit history.
- Backfill should include dry-run / preview mode before enqueueing broad jobs.

Open decision:
- PRD §19 closes the default backfill start at `DEFAULT_BACKFILL_START_QUARTER=2023-Q1`. Should MVP 3 target pre-2023-Q1 quarters, where the thousands/dollars dual-fixture rules apply, and if so what is the earliest bound: all available SEC history, the last 5 years before 2023-Q1, or a curated manager/quarter subset?

### D2. CUSIP Source / Dataroma Legacy Surface

Recommendation: Do not revive Dataroma as a CUSIP source. MVP 3 should keep OpenFIGI / verified mapping workflows as the primary CUSIP-to-stock path, and treat legacy Dataroma code as manager-discovery or cleanup scope only.

Rationale:
- MVP 2 verification confirmed OpenFIGI-backed mapping is the current contract.
- Dataroma holdings do not expose CUSIP and should not be used as an authoritative security identifier source.
- Note: this recommendation proposes to defer or remove PRD §17 `Dataroma CUSIP 来源` from MVP 3 scope. That is a PRD scope change and requires explicit human owner approval before this gate closes.

Implementation constraints for the relevant MVP 3 task:
- Any retained Dataroma client/stub should be explicitly documented as non-authoritative for CUSIP mapping.
- If not needed, remove or deprecate legacy `enrich_from_dataroma` naming to avoid future source confusion.

Open decision:
- D2a: Should human owner scope out PRD §17 `Dataroma CUSIP 来源` from MVP 3 entirely?
- D2b: If D2a is approved, should MVP 3 remove legacy Dataroma CUSIP enrichment wrappers, or retain compatibility wrappers with clearer OpenFIGI / non-authoritative naming?

### D3. Batch Reparse by Quarter / Manager

Recommendation: MVP 3 should add batch reparse jobs only after filing-level `value_unit_override` and baseline data-integrity validation are defined. Batch reparse is the execution path for override workflows and should not run at scale before validation reports can detect parse-run, current-pointer, and ownership-change drift.

Implementation constraints for the relevant MVP 3 task:
- Batch reparse must use explicit job-run records and lock keys.
- Reparse must preserve parse-run audit history and current-pointer semantics.
- Admin actions must require preview / confirmation before broad enqueue.
- Reparse should not silently activate results that fail readiness or amendment rules.

Open decision:
- Should MVP 3 ship quarter reparse first, manager reparse first, or both behind the same admin workflow?

### D4. CUSIP Corporate Action Temporal Mapping UI

Recommendation: MVP 3 should design corporate-action mapping UI as an admin review surface, not an automatic correction engine.

Implementation constraints for the relevant MVP 3 task:
- UI may confirm/supersede CUSIP mappings and set temporal validity.
- UI must not automatically adjust historical `value_usd`, shares, or portfolio weights.
- User-facing Oracle's Lens should continue to label heuristic corporate action signals as possible/uncertain unless confirmed by mapping state.

Open decision:
- What evidence source is acceptable for confirming a CUSIP corporate action: admin manual review only, OpenFIGI metadata, SEC issuer data, or another licensed source?

### D5. Filing-Level Value Unit Override

Recommendation: MVP 3 should implement filing-level `value_unit_override` only after defining the audit and reparse protocol.

Implementation constraints for the relevant MVP 3 task:
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

Sequence rationale: resolve source naming ambiguity and add validation safety nets before broad reparse/backfill work. Historical backfill remains in MVP 3 scope only after cleanup, validation, override, and reparse contracts are ready.

1. `MVP3-01 Legacy Dataroma Surface Cleanup / Naming Clarification`
2. `MVP3-02 Data Integrity Validation Jobs and Admin Reports`
3. `MVP3-03 Filing-Level Value Unit Override Schema / Audit Contract`
4. `MVP3-04 Batch Reparse Jobs by Quarter / Manager`
5. `MVP3-05 CUSIP Corporate Action Temporal Mapping Admin UI`
6. `MVP3-06 Historical Backfill Job Contract and Preview`

## Approval Checklist

- [ ] D1 historical backfill default range and any pre-2023-Q1 extension approved.
- [ ] D2 human owner explicitly approves scoping out PRD §17 `Dataroma CUSIP 来源` from MVP 3 as a PRD scope change, and approves the legacy wrapper cleanup/naming decision.
- [ ] D3 batch reparse sequencing approved after filing-level `value_unit_override` and baseline validation are defined.
- [ ] D4 corporate action evidence policy approved.
- [ ] D5 filing-level `value_unit_override` storage/audit model approved; filing-scoped per PRD §20 and does not modify or replace the existing manager-level `value_unit_override=infer` column.
- [ ] D6 validation report persistence / alerting model approved.
- [ ] MVP3-01 Legacy Dataroma Surface Cleanup / Naming Clarification explicitly approved to start.

## Progress Notes

- 2026-05-11: Created after MVP 2 final acceptance approved entry into MVP 3 decision gate / backlog planning.
- 2026-05-11: Applied Tech Lead review feedback: D2 now explicitly flags the PRD §17 Dataroma CUSIP source removal as a human-owner scope-change decision, D1 is framed against the PRD §19 2023-Q1 default, D3 now depends on value-unit override and validation readiness, and the task sequence now puts Dataroma cleanup / validation / override before batch reparse and historical backfill.

## Verification Results

- Documentation-only decision gate; Docker verification not required.
