# Task: Split Value Line observation-only fields from canonical metric facts

## Goal / Acceptance Criteria
- Define an explicit contract for which Value Line mappings should emit canonical `metric_facts` and which should remain evidence-only.
- Apply that contract in the mapping/fact generation path.
- Keep core investment-use metrics in `metric_facts`, while preventing obvious document/evidence text fields from being emitted as canonical facts.
- Add tests that prove the split is enforced.

## Scope
**In**
- Extend the Value Line taxonomy contract with storage-role semantics.
- Minimal mapping generation changes to skip evidence-only mappings.
- Tests for taxonomy-driven inclusion/exclusion.

**Out**
- New database tables for observation storage.
- UI changes.
- Cross-source resolver logic.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Value Line parser scope and normalized storage
- `AGENTS.md` -> task logging, Docker-only verification, lineage and safety rules

## Files To Change
- `docs/tasks/2026-04-22_value-line-observation-canonical-split.md` (this file)
- `docs/value_line_field_taxonomy.yml`
- `backend/app/services/mapping_spec.py`
- `backend/tests/unit/test_value_line_field_taxonomy.py`
- `backend/tests/unit/test_metric_facts_mapping_spec.py`
- Other targeted tests only if needed

## Execution Plan (Assumed approved per direct request)
1. Add failing tests for taxonomy-driven storage role behavior.
2. Extend taxonomy with storage-role metadata.
3. Update mapping generation to skip evidence-only mappings.
4. Run Docker verification and record outcomes.

## Contract Checks
- No schema changes in this task.
- No change to parsed extraction lineage.
- Canonical facts remain generated only via the mapping layer.

## Rollback Strategy
- Revert taxonomy storage-role additions.
- Revert mapping filtering changes and related tests.

## Progress Log
- [x] Add failing tests.
- [x] Implement taxonomy storage-role split.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Applied the first observation/canonical split only to the clearest evidence-only fields: `company.business_description.as_of` and `analyst.commentary.as_of`.
- Added `storage_role` to the Value Line taxonomy contract with allowed values `canonical_fact` and `evidence_only`.
- `MappingSpec.generate_facts()` now skips mappings marked `evidence_only`, so those fields remain available in page JSON / document evidence but no longer emit canonical `metric_facts`.
- Kept structured opinion fields like ratings, quality metrics, targets, and projections in `metric_facts` for now; they are still actively used by product flows and need a more explicit downstream design before being split further.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_value_line_field_taxonomy.py tests/unit/test_metric_facts_mapping_spec.py tests/unit/test_value_line_metric_facts_time_series.py tests/unit/test_value_line_annual_facts.py tests/unit/test_screener_api_metrics.py`
- `docker compose exec api pytest -q`

All passed. Final full API test run: `113 passed in 18.30s`.
