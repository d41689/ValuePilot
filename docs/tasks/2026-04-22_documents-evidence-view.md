# Task: Add document evidence view for evidence-only Value Line fields

## Goal / Acceptance Criteria
- Provide a minimal authenticated document-level evidence view for fields classified as `evidence_only`.
- Evidence view must not require new database schema.
- Evidence-only fields must remain readable after being removed from canonical `metric_facts`.
- Initial coverage should include the currently evidence-only Value Line fields:
  - `company.business_description.as_of`
  - `analyst.commentary.as_of`
  - `rating.timeliness.event`
  - `rating.safety.event`
  - `rating.technical.event`

## Scope
**In**
- Document evidence contract additions in taxonomy if needed.
- Minimal backend endpoint/helper to return evidence-only fields for a document.
- Targeted tests for evidence-only retrieval.

**Out**
- New persistence layer or schema changes.
- Frontend UI changes.
- Broad stock-level evidence aggregation.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Value Line parser scope, lineage, and audit trail
- `AGENTS.md` -> task logging, Docker-only verification, lineage and safety rules

## Files To Change
- `docs/tasks/2026-04-22_documents-evidence-view.md` (this file)
- `docs/value_line_field_taxonomy.yml`
- `backend/app/api/v1/endpoints/documents.py`
- `backend/tests/unit/*document*` or other targeted tests
- Minimal helper/service files only if needed

## Execution Plan (Assumed approved per direct request)
1. Add failing tests for document evidence retrieval.
2. Extend taxonomy with evidence read contract as needed.
3. Implement minimal authenticated document evidence endpoint.
4. Run Docker verification and record outcomes.

## Contract Checks
- No schema changes.
- Evidence values come from existing audit-layer storage (`metric_extractions`) or stored document metadata.
- Canonical/evidence split remains taxonomy-driven.

## Rollback Strategy
- Revert taxonomy evidence-read additions.
- Revert evidence endpoint and tests.

## Progress Log
- [x] Add failing tests.
- [x] Implement evidence read contract + endpoint.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Evidence-only reads are now explicit in `docs/value_line_field_taxonomy.yml` under `evidence_reads`.
- `/api/v1/documents/{document_id}/evidence` reads from `metric_extractions`; no schema change and no page-json persistence requirement.
- Rating event parsing was moved to a shared helper so parser page JSON and document evidence view use the same `Raised/Lowered/New mm/dd/yy` logic.
- When multiple extractions exist for the same field key on a document, the endpoint prefers the highest parser version rank, then highest extraction id. This avoids obvious stale-row regressions while keeping implementation minimal.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_documents_api.py tests/unit/test_value_line_field_taxonomy.py`
- `docker compose exec api pytest -q`
- Result: `115 passed in 19.03s`
