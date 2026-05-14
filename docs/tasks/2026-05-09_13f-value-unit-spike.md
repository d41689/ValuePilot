# 13F Value-Unit Spike

## Goal / Acceptance Criteria

Implement execution-plan task `13F-1B-00`: close the G2 value-unit spike gate before MVP 1B parser implementation begins.

Acceptance criteria:
- At least two real EDGAR 13F XML fixtures from 2022 or earlier are committed.
- At least two real EDGAR 13F XML fixtures from 2023 or later are committed.
- A mapping rule document explains how XML namespace, schemaLocation, form spec/version evidence, and accepted date map to:
  - `schema_thousands`
  - `schema_dollars`
  - fallback `inferred` + `VALUE_UNIT_UNCERTAIN`
- Tests prove:
  - pre-2023 fixture resolves to `schema_thousands`
  - 2023+ fixture resolves to `schema_dollars`
  - a Q4 2022 filing submitted after 2023-01-03 is not classified only by report quarter
  - unknown schema returns `inferred` with `VALUE_UNIT_UNCERTAIN`
- No full parser implementation is added.
- Tech Lead can review the rule contract to close G2.

## Scope

In:
- Real SEC fixture files for narrow value-unit evidence.
- A small value-unit rule helper if needed by tests.
- Focused tests for rule selection.
- Mapping rule documentation.

Out:
- Full 13F information table parser.
- Filing ingestion pipeline.
- UI.
- PRD edits.
- Database schema changes.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §7.2 holdings value units.
- `docs/prd/13f_automation_and_resilience_prd.md` §17 MVP 1B front gate.
- `docs/prd/13f_automation_and_resilience_prd.md` §18.2 value-unit acceptance criteria.
- `docs/prd/13f_automation_and_resilience_prd.md` §20 open questions.
- `docs/tasks/2026-05-09_13f-automation-development-plan.md` `13F-1B-00`.

## Files To Change

- `docs/tasks/2026-05-09_13f-value-unit-spike.md`
- `docs/13f/value-unit-mapping.md`
- `backend/app/edgar/parsers/value_units.py`
- `backend/tests/fixtures/13f/value_units/*`
- `backend/tests/unit/test_13f_value_units.py`

## Test Plan

Docker only:
- `docker compose exec api pytest -q tests/unit/test_13f_value_units.py`
- `docker compose exec api pytest -q tests/unit`

## Progress Notes

- 2026-05-09: Started `13F-1B-00` before MVP 1B parser work, per Tech Lead direction to close G2 early.
- 2026-05-09: Added red test coverage for real pre-2023 fixtures, real 2023+ fixtures, Q4 2022 accepted after `2023-01-03`, and unknown schema fallback. Initial focused test failed because `app.edgar.parsers.value_units` did not exist.
- 2026-05-09: Added five real SEC XML fixtures under `backend/tests/fixtures/13f/value_units/`:
  - `2022_sio_capital_0001214659-22-013603_infotable.xml` from `https://www.sec.gov/Archives/edgar/data/1482416/000121465922013603/infotable.xml`
  - `2022_mit_0001214659-22-013108_infotable.xml` from `https://www.sec.gov/Archives/edgar/data/351051/000121465922013108/infotable.xml`
  - `2023_berkshire_0000950123-23-005270_22815.xml` from `https://www.sec.gov/Archives/edgar/data/1067983/000095012323005270/22815.xml`
  - `2023_toms_capital_0000902664-23-004449_infotable.xml` from `https://www.sec.gov/Archives/edgar/data/1743937/000090266423004449/infotable.xml`
  - `2022q4_accepted_2023_arex_0000919574-23-001400_infotable.xml` from `https://www.sec.gov/Archives/edgar/data/1800261/000091957423001400/infotable.xml`
- 2026-05-09: Added `docs/13f/value-unit-mapping.md`. Key decision: real 2023 filings may still use `eis_13FDocument.xsd`, so schemaLocation alone is insufficient. Use explicit form/schema version evidence first; otherwise use known SEC 13F namespace plus `accepted_at` transition date `2023-01-03`; never use report quarter alone.
- 2026-05-09: Added `backend/app/edgar/parsers/value_units.py` as a narrow rule-classification helper only. It does not parse holdings, normalize persisted values, enqueue jobs, or implement manager overrides.
- 2026-05-09: Docker verification passed:
  - `docker compose exec api pytest -q tests/unit/test_13f_value_units.py` -> `4 passed in 0.02s`
  - `docker compose exec api pytest -q tests/unit` -> `330 passed in 38.77s`
- 2026-05-09: G2 implementation evidence is ready for Tech Lead review. Recommendation: close G2 after review approval; MVP 1B parser work can then rely on this mapping rule.
- 2026-05-09: Tech Lead reviews both approved closing G2. Accepted review feedback:
  - Added tests for explicit version evidence paths (`form_spec_version="2023"`, `xml_schema_version="1.6"`) and unknown version fallback to `accepted_at`.
  - Added `evidence["decided_by"]` to record whether the decision came from `form_spec_version`, `xml_schema_version`, `accepted_at`, or `fallback_uncertain`.
  - Added SEC FAQ Q36 reference to `docs/13f/value-unit-mapping.md`.
- 2026-05-09: Deferred review feedback:
  - Persisting `VALUE_UNIT_UNCERTAIN` to `filings_13f.parse_warning` belongs to later ingestion/parser tasks, not this spike.
  - Further broadening version-string parsing can happen when actual extracted version strings are available.
- 2026-05-09: Docker verification after review fixes passed:
  - `docker compose exec api pytest -q tests/unit/test_13f_value_units.py` -> `7 passed in 0.05s`
  - `docker compose exec api pytest -q tests/unit` -> `333 passed in 39.15s`
