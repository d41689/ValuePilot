# 13F MVP3-01: Legacy Dataroma Surface Cleanup / Naming Clarification

## Goal / Acceptance Criteria

Remove source-authority ambiguity around legacy Dataroma surfaces without changing ingestion, mapping, backfill, reparse, value-unit override, corporate-action UI, or validation-job behavior.

Acceptance criteria:
- Dataroma remains allowed only as manager-discovery / legacy non-authoritative hinting.
- No code path, CLI command, admin job, or task note presents Dataroma as a CUSIP or security-identity authority.
- Legacy compatibility wrappers, if retained, are named or documented as non-authoritative and OpenFIGI-backed where applicable.
- Existing discovery/parser behavior remains intact.
- Relevant unit tests are updated before implementation and pass in Docker.

## Scope In

- Legacy Dataroma naming and documentation cleanup in code comments, CLI/admin labels, and service wrappers.
- Compatibility naming for any retained CUSIP-enrichment wrapper.
- Tests that assert the non-authoritative / OpenFIGI-backed contract.
- Task-file progress notes and verification results.

## Scope Out

- Historical backfill implementation.
- Batch reparse implementation.
- Filing-level value-unit override implementation.
- Corporate-action temporal mapping UI.
- Data integrity validation jobs.
- PRD edits.
- Schema migrations.
- Removing Dataroma manager-discovery support.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D2: Dataroma is scoped out as a CUSIP / security-identity source.
- `docs/prd/13f_automation_and_resilience_prd.md` §17 / §20: MVP 3 backlog and decision-gate constraints.
- `docs/tasks/2026-05-11_13f-mvp2-end-to-end-verification.md`: MVP 3 follow-up to remove/refactor legacy Dataroma client/stub surfaces.

## Files Expected To Change

- `backend/app/services/cusip_enrichment.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/cli/edgar.py`
- `backend/app/services/scheduler.py`
- `backend/app/services/edgar_ingestion.py`
- `README.md`
- `CLAUDE.md`
- Relevant backend unit tests.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_cusip_enrichment.py`
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- Additional focused tests if CLI/admin labels are covered elsewhere.

## Progress Notes

- 2026-05-11: Started after product owner explicitly approved MVP3-01 with scope limited to legacy Dataroma surface cleanup, naming clarification, and source-authority ambiguity removal.
- 2026-05-11: Chose compatibility-wrapper approach: active CUSIP enrichment call sites now use OpenFIGI naming; the old `enrich_from_dataroma` symbol remains only as a deprecated alias that explicitly does not call Dataroma.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_cusip_enrichment.py` → 7 passed.
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` → 51 passed.
- `rg` check: active CUSIP enrichment call sites use `enrich_cusips_from_openfigi`; remaining `enrich_from_dataroma` references are the deprecated compatibility alias and its unit test.
