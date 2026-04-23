# Task: Audit metric_facts taxonomy coverage

## Goal / Acceptance Criteria
- Add a read-only audit script that reports how much of the current `metric_facts` dataset is covered by taxonomy v1.
- The audit must distinguish covered canonical keys from uncovered / legacy keys.
- The audit must report `fact_nature` coverage and highlight missing or legacy patterns.
- The script must run inside Docker and not mutate database state.

## Scope
**In**
- A read-only audit script under `backend/scripts/`
- Unit tests for taxonomy coverage classification logic
- Task log updates
- Running the audit against the current local database

**Out**
- Backfilling or reparsing historical documents
- Changing parser or ingestion semantics
- Migrating existing facts

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> three-layer storage, normalized facts, lineage
- `AGENTS.md` -> Docker-only execution, task logging, metric_facts as source of truth

## Files To Change
- `docs/tasks/2026-04-23_audit-metric-taxonomy-coverage.md`
- `backend/scripts/audit_metric_taxonomy_coverage.py`
- `backend/tests/unit/test_audit_metric_taxonomy_coverage.py`

## Execution Plan
1. Add unit tests for taxonomy coverage matching, including dynamic `rates.*` keys.
2. Implement a read-only audit script that loads mapping spec + taxonomy and classifies DB metric keys.
3. Run targeted tests in Docker.
4. Run the audit script in Docker against the current local database and record results.

## Contract Checks
- The script must only read from the database.
- The audit should focus on parsed facts and taxonomy-backed canonical metrics.
- Evidence-only taxonomy entries must not be counted as canonical `metric_facts`.

## Rollback Strategy
- Remove the audit script/test if the output proves misleading or the matcher logic is incorrect.

## Progress Log
- [x] Add failing unit tests for taxonomy coverage matching.
- [x] Implement read-only audit script.
- [x] Run targeted Docker verification.
- [x] Run audit script and record findings.

## Notes / Decisions / Gotchas
- Dynamic taxonomy-backed rate keys need pattern matching, not exact-key-only lookup.
- The audit currently focuses on `source_type='parsed'`, which is the right scope for Value Line ingestion coverage.
- The first live run shows only two uncovered parsed metric keys, both in the owners earnings derived family.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_audit_metric_taxonomy_coverage.py tests/unit/test_value_line_field_taxonomy.py`
- `docker compose exec api python -m scripts.audit_metric_taxonomy_coverage --limit 50`
- Results:
  - Tests: `4 passed in 0.10s`
  - Audit summary:
    - `fact_rows=694`
    - `distinct_metric_keys=59`
    - `covered_metric_keys=57`
    - `uncovered_metric_keys=2`
    - `covered_row_count=655`
    - `uncovered_row_count=39`
  - Uncovered keys:
    - `owners_earnings_per_share` (`36` rows)
    - `owners_earnings_per_share_normalized` (`3` rows)
  - Missing `fact_nature` keys are concentrated in owners earnings plus `rates.*.cagr_est`.
