# Task: Add owners earnings derived metrics to taxonomy v1

## Goal / Acceptance Criteria
- Formally register owners earnings metrics as taxonomy v1 derived metrics.
- `owners_earnings_per_share` and `owners_earnings_per_share_normalized` should no longer show up as uncovered keys in the taxonomy audit.
- Newly derived owners earnings facts must carry `fact_nature` in `value_json`.
- Existing stock API / DCF behavior must remain intact.

## Scope
**In**
- Taxonomy contract updates for derived metrics
- Owners earnings derivation semantics
- Audit matcher updates
- Unit tests and targeted Docker verification

**Out**
- Historical DB backfill or migration
- Frontend changes
- Renaming owners earnings metric keys

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> normalized facts and metric_facts source of truth
- `AGENTS.md` -> Docker-only verification and task logging

## Files To Change
- `docs/tasks/2026-04-23_add-owners-earnings-derived-taxonomy.md`
- `docs/value_line_field_taxonomy.yml`
- `backend/scripts/audit_metric_taxonomy_coverage.py`
- `backend/app/services/owners_earnings.py`
- `backend/tests/unit/test_audit_metric_taxonomy_coverage.py`
- `backend/tests/unit/test_owners_earnings_facts.py`
- `backend/tests/unit/test_value_line_field_taxonomy.py`

## Execution Plan
1. Update tests to expect owners earnings derived metrics to be taxonomy-covered and fact-nature-tagged.
2. Add derived metric declarations to taxonomy and teach the audit matcher to include them.
3. Update owners earnings derivation to emit `fact_nature`.
4. Run targeted tests and rerun the audit script.

## Contract Checks
- Owners earnings remains derived from canonical parsed facts, not from raw extraction tables.
- No schema changes.
- Audit script remains read-only.

## Rollback Strategy
- Revert the taxonomy and owners earnings changes if they create ambiguity in metric semantics.

## Progress Log
- [x] Add failing tests.
- [x] Implement taxonomy + derivation changes.
- [x] Run targeted Docker verification.
- [x] Rerun audit and record findings.

## Notes / Decisions / Gotchas
- Owners earnings is not a direct source mapping; it belongs in taxonomy as a derived canonical metric.
- Kept the existing owners earnings metric keys to avoid breaking current DCF and stock API reads; the consistency fix is taxonomy registration + fact_nature on newly derived writes.
- The live audit now treats owners earnings as covered taxonomy v1 keys, but existing rows in the local DB still lack `fact_nature` until they are reparsed/backfilled.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_audit_metric_taxonomy_coverage.py tests/unit/test_owners_earnings_facts.py tests/unit/test_value_line_field_taxonomy.py`
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py tests/unit/test_owners_earnings_facts.py tests/unit/test_audit_metric_taxonomy_coverage.py tests/unit/test_value_line_field_taxonomy.py`
- `docker compose exec api python -m scripts.audit_metric_taxonomy_coverage --limit 50`
- `docker compose exec api pytest -q`
- Results:
  - Targeted tests: `6 passed in 0.11s`
  - Extended regression: `11 passed in 0.21s`
  - Audit summary:
    - `fact_rows=694`
    - `distinct_metric_keys=59`
    - `covered_metric_keys=59`
    - `uncovered_metric_keys=0`
  - Full suite: `127 passed in 21.67s`
