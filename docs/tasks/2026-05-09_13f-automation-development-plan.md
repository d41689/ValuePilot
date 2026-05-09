# 13F Automation Development Execution Plan

## Goal / Outcome

Create an execution plan for implementing `docs/prd/13f_automation_and_resilience_prd.md` through MVP 1A, MVP 1B, MVP 1C-1, and MVP 1C-2.

This document is for execution by a senior implementation engineer. It converts the PRD into ordered, reviewable development tasks with explicit dependencies, test-first expectations, Docker verification commands, and Tech Lead review gates.

MVP 2 and MVP 3 are recorded as backlog only. They must not be implemented during the MVP 1 execution track unless the human owner approves a scope change.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md`
- Key sections:
  - §2 Core concepts, date/quarter definitions, filing types
  - §3 Manager Management Center
  - §4 Daily Sync Engine
  - §5 Smart Routing
  - §6 Filing dedupe, reparse, parse_runs, amendment policy
  - §7 Holdings model, value units, attribution, 13F-NT query contract
  - §8 CUSIP mapping and temporal securities linkage
  - §10 Readiness and data quality
  - §11 Admin Dashboard
  - §12 Job runs, locks, retries
  - §13 API Requirements
  - §14 Performance, constraints, indexes
  - §15 Monitoring and alerts
  - §16 UX copy
  - §17 MVP Delivery Plan
  - §18 Acceptance Criteria
  - §20 Open Questions

## Tech Lead Findings

No new PRD blockers were found during this planning pass.

Known gate: MVP 1B parser implementation is blocked until the value-unit spike is completed and reviewed. This is intentional and required by PRD §17 and §20.

## Non-Goals

- Do not modify the PRD as part of these implementation tasks.
- Do not implement MVP 2 change analysis, holder aggregation, ownership changes precompute, or `/stocks/{stock_id}/holders` aggregation beyond MVP 1 unavailable/safe responses.
- Do not implement MVP 3 full historical backfill, Dataroma CUSIP source, batch reparse by quarter/manager, or CUSIP corporate action management UI.
- Do not introduce raw SQL generated from user input.
- Do not bypass the shared SEC/EDGAR client or global EDGAR rate limiter.
- Do not create one-off frontend controls; frontend work must use shadcn/ui style components from `frontend/components/ui/`.

## Global Engineering Rules

- Follow TDD: write or update tests first, then implement the smallest production change needed.
- Run all verification through Docker Compose:
  - `docker compose up -d --build`
  - `docker compose exec api pytest -q ...`
  - `docker compose exec api alembic upgrade head` when migrations change
- Every concrete implementation task must create its own task log in `docs/tasks/YYYY-MM-DD_<short-task-name>.md` before code changes.
- Keep PRD semantics fixed. If implementation reveals a PRD contradiction, stop and request Tech Lead / human approval before changing scope.
- Alembic revision filenames must follow `backend/alembic/versions/YYYYMMDDHHMMSS-description.py`.
- Screeners and Oracle's Lens user queries must not infer "no holdings" from missing data or 13F-NT.
- Product-facing 13F holdings queries must use active HR/HR-A filings joined to the current parse_run only.
- Admin UI must use shadcn/ui + Tailwind components and lucide-react icons where controls need icons.

## Blocking Gates

| Gate | Blocks | Required Output | Approval |
| --- | --- | --- | --- |
| G1: PRD execution plan accepted | All implementation tasks | Human owner accepts this plan | Human owner |
| G2: Value-unit spike complete | MVP 1B parser implementation | Mapping rule doc + 2022/pre-2023 and 2023+ fixtures + tests | Tech Lead |
| G3: Schema migration review | All services depending on 13F tables | Alembic migration reviewed against PRD §7, §12, §14 | Tech Lead |
| G4: API contract review | Frontend/admin UI work | Backend response shapes and error/unavailable contracts stabilized | Tech Lead |
| G5: 13F-NT query contract review | Readiness and Oracle's Lens integration | Tests prove NT active filings never enter holdings query path | Tech Lead |
| G6: CUSIP temporal mapping review | CUSIP-backed product/readiness use | Temporal lookup and overlap tests cover null end dates, inclusive quarter boundaries, and non-overlap invariants | Tech Lead |

## Development Sequence

### MVP 1A: Manager + Daily Index Infrastructure

#### 13F-1A-01: Schema Foundation for Managers, Sync Status, No-Index Dates, and Job Runs

Goal: Add the database foundation for MVP 1A without implementing SEC ingestion behavior yet.

PRD sections: §3.2-§3.6, §4.2-§4.4, §12, §13 no-index calendar, §14 indexes.

Dependencies: G1.

Scope In:
- Create/extend models and migration for tracked managers.
- Create `edgar_sync_status`.
- Create `no_index_expected_dates`.
- Create/extend `job_runs` with lock and lease fields needed by PRD §12.
- Add enum constraints or application-level enum validation for statuses.
- Add indexes needed for MVP 1A query paths.

Scope Out:
- No SEC network calls.
- No parser implementation.
- No frontend UI.
- No filing/holdings tables unless the repository already requires a single consolidated migration for all 13F schema; if so, gate with Tech Lead review.

Files likely to change:
- `backend/alembic/versions/*`
- `backend/app/models/*`
- `backend/app/schemas/*`
- `backend/tests/unit/*`

Tests to write first:
- Model/migration tests for required fields and unique constraints.
- Enum validation tests for manager status, sync status, and job status.
- `no_index_expected_dates` tests for active/inactive date behavior.

Docker verification commands:
- `docker compose up -d --build`
- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- Migrations apply cleanly from the current database head.
- Tables and indexes match MVP 1A PRD requirements.
- `no_index_expected_dates` supports `date`, `reason`, `source`, `active`, audit fields, and no physical delete path.
- `job_runs` can represent queued/running/succeeded/partial_success/failed/cancel_requested/canceled/skipped.

Tech Lead Review Gate:
- Review migration for naming, nullable fields, indexes, enum stability, and compatibility with later MVP 1B schema.

#### 13F-1A-02: Manager Admin Backend and CIK Confirmation Workflow

Goal: Implement backend manager CRUD, candidate import, and CIK confirmation surfaces.

PRD sections: §3, §13 Manager APIs.

Dependencies: 13F-1A-01.

Scope In:
- Admin manager list/create/patch/deactivate endpoints.
- Bulk CSV import endpoint with candidate-only creation.
- CIK confirmation endpoint.
- Backfill preview endpoint stub/initial implementation that estimates filing count/request count when possible and never triggers jobs silently.
- Validation that `value_unit_override` defaults to `infer`.

Scope Out:
- Full UI.
- Actual historical backfill job execution.
- Dataroma integration beyond existing discovery hints if already present.

Files likely to change:
- `backend/app/api/v1/endpoints/*`
- `backend/app/models/*`
- `backend/app/schemas/*`
- `backend/app/services/*`
- `backend/tests/unit/*`

Tests to write first:
- Manager create defaults `status=candidate` or explicit PRD-compatible status.
- Bulk import does not auto-confirm CIK.
- Confirm CIK transitions only valid records to `active`.
- Deactivate removes manager from automated tracking.
- Backfill preview does not enqueue work.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- Admin can create, edit, deactivate, import, and confirm managers.
- Confirmed active managers are the only managers eligible for daily index matching.
- No job is started from CIK confirmation without explicit admin confirmation.

Tech Lead Review Gate:
- Review status transitions and CIK audit fields before daily sync depends on them.

#### 13F-1A-03: Shared SEC Client, EDGAR Rate Limiter, and User-Agent Fail-Fast

Goal: Establish a single SEC/EDGAR access path with PRD-compliant rate limiting and configuration validation.

PRD sections: §3.5, §4.5, §12, §15.2.

Dependencies: 13F-1A-01.

Scope In:
- Shared SEC client/service.
- Global 10 requests/second EDGAR limiter.
- User-Agent construction from `SEC_CONTACT_EMAIL`.
- Application startup or client initialization fail-fast when `SEC_CONTACT_EMAIL` is missing.
- Retry/backoff behavior for transient network failures.
- 429/403 detection hook for alerts/health summaries.

Scope Out:
- Parsing daily index contents.
- OpenFIGI client.
- Production alert delivery beyond a service hook if alert infra is not implemented yet.

Files likely to change:
- `backend/app/edgar/*`
- `backend/app/core/*`
- `backend/app/services/*`
- `backend/tests/unit/*`

Tests to write first:
- Missing `SEC_CONTACT_EMAIL` fails before request execution.
- SEC client sets a compliant User-Agent.
- Retry policy stops after configured max retries.
- Rate limiter is invoked for every SEC request path.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- No EDGAR request path bypasses the shared client.
- Configuration failure is explicit and actionable.
- Tests can mock network calls without external SEC access.

Tech Lead Review Gate:
- Review that all future SEC fetch tasks can depend on this client.

#### 13F-1A-04: Daily Index Fetch, Parse, Sync Status, and No-Index Calendar APIs

Goal: Implement daily `form.idx` fetch/parse for tracked managers and expose no-index date maintenance APIs.

PRD sections: §4.2-§4.4, §13 sync and no-index APIs, §15.2.

Dependencies: 13F-1A-01, 13F-1A-02, 13F-1A-03.

Scope In:
- Fetch daily `form.YYYYMMDD.idx`.
- Save raw daily index document.
- Parse and count `13F-HR`, `13F-HR/A`, and `13F-NT`.
- Match only active tracked managers by CIK.
- Update `edgar_sync_status` with success/failed/no_data/partial_success.
- Apply 404 rules using `no_index_expected_dates`.
- Admin endpoints:
  - `GET /api/v1/admin/13f/no-index-dates`
  - `POST /api/v1/admin/13f/no-index-dates`
  - `PATCH /api/v1/admin/13f/no-index-dates/{date}`

Scope Out:
- Fetch filing detail/header.
- Parse information tables.
- Enqueue full holdings ingestion beyond creating job records or task placeholders.
- Frontend UI.

Files likely to change:
- `backend/app/edgar/*`
- `backend/app/api/v1/endpoints/*`
- `backend/app/services/*`
- `backend/app/schemas/*`
- `backend/tests/unit/*`
- `backend/tests/fixtures/*`

Tests to write first:
- Daily index fixture with HR, HR/A, NT rows counts correctly.
- Non-tracked CIK rows are ignored.
- 404 on expected no-index date becomes `no_data`.
- 404 on unexpected date retries/fails according to policy.
- Admin cannot manually create weekend/federal holiday auto rows if PRD policy says they are system generated.
- Patch deactivates but does not delete no-index rows.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- Daily sync identifies and records tracked HR/HR-A/NT filings without assigning report quarters from sync date.
- No-index calendar can be maintained without code deploy.
- Raw daily index content is persisted for audit.

Tech Lead Review Gate:
- Review 404/no_data semantics and no-index API before scheduling hourly polling.

#### 13F-1A-05: Job Scheduler Locks, Leases, Retry Skeleton, and Alerts Foundation

Goal: Implement the job execution primitives that later ingestion tasks will use.

PRD sections: §4.4, §12, §15.

Dependencies: 13F-1A-01, 13F-1A-04.

Scope In:
- Job creation with dedupe keys and lock keys.
- Lease token acquisition and heartbeat refresh.
- Expired lease detection.
- Job status transitions.
- Duplicate job policy: for daily sync and ingestion jobs, if a job with the same `dedupe_key` is already `queued` or `running`, the new request is ignored/skipped and does not enqueue another job.
- Retry skeleton for failed sync dates and partial_success.
- Hourly polling trigger for daily sync using `DAILY_SYNC_EARLIEST_ATTEMPT_ET` (default `20:00` ET).
- Watchdog/quality-check scheduling policy whose interval is longer than the maximum job timeout it evaluates; for the default 10-minute `ingest_filing` timeout, use a 15-minute or slower watchdog cadence unless explicitly reviewed.
- Alert service abstraction for P1/P2/P3, with Discord webhook support if configuration exists.

Scope Out:
- Full alert rule coverage.
- Full worker orchestration for all MVP 1B jobs.
- Admin dashboard UI.

Files likely to change:
- `backend/app/services/*`
- `backend/app/api/v1/endpoints/*`
- `backend/app/core/*`
- `backend/tests/unit/*`

Tests to write first:
- A second worker cannot take an unexpired lease.
- Expired leases can be taken over safely.
- Only lease owner can update running job.
- Duplicate daily sync or ingestion request with the same `dedupe_key` is skipped while an existing job is queued/running.
- Hourly polling does not enqueue daily sync before `DAILY_SYNC_EARLIEST_ATTEMPT_ET`.
- Watchdog does not mark jobs abandoned before their configured timeout and lease expiry.
- Alert service records/sends severity and message payloads.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- Job lock and lease behavior supports PRD §12 lock_key strategy.
- Daily sync can run through job_runs rather than ad hoc execution.
- Automatic hourly polling queues eligible daily sync work after the earliest attempt time.
- Alerting can be called by later quality/readiness tasks.

Tech Lead Review Gate:
- Review concurrency semantics before MVP 1B parse_runs use job lease state.

### MVP 1B: Filing + Holdings Ingestion + Amendment Replacement

#### 13F-1B-00: Value-Unit Spike Gate

Goal: Close the PRD §20 MVP 1B value-unit open question before parser implementation begins.

PRD sections: §7.2, §17 MVP 1B front gate, §18.2 value unit criteria, §20.

Dependencies: G1.

Scope In:
- Collect at least two real EDGAR 13F XML filings from 2022 or earlier.
- Collect at least two real EDGAR 13F XML filings from 2023 or later.
- Document mapping from XML namespace/schemaLocation/form_spec_version/accepted_at evidence to `schema_thousands` or `schema_dollars`.
- Add fixtures to the test suite.
- Add tests that prove the rule selection independent of report quarter-only heuristics.

Scope Out:
- Full parser implementation.
- Filing ingestion pipeline.
- UI.

Files likely to change:
- `docs/tasks/YYYY-MM-DD_13f-value-unit-spike.md`
- `backend/tests/fixtures/*`
- `backend/tests/unit/*`
- Possibly `backend/app/edgar/parsers/*` only for a narrow rule helper if needed for tests

Tests to write first:
- Pre-2023 fixture resolves to `schema_thousands`.
- 2023+ fixture resolves to `schema_dollars`.
- Q4 2022 submitted after 2023-01-03 is not classified only by report quarter.
- Unknown schema returns `inferred` with `VALUE_UNIT_UNCERTAIN` warning.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- A mapping rule document exists and is referenced by tests.
- Fixtures are committed under the test fixture tree.
- Parser implementation can consume a stable rule contract.
- Tech Lead approves closure of PRD §20 value-unit open question for MVP 1B.

Tech Lead Review Gate:
- Mandatory approval before 13F-1B-02 or any production parser work starts.

#### 13F-1B-01: Filing, Parse Run, Holdings, and CUSIP Mapping Schema

Goal: Add the MVP 1B persistence model with audit-preserving parse_runs and temporal CUSIP mapping.

PRD sections: §6, §7.1-§7.3, §8.3, §12.4, §14.

Dependencies: 13F-1A-01.

Scope In:
- Create/extend `filings_13f`.
- Create `parse_runs`.
- Create/extend `holdings_13f`.
- Create/extend `cusip_ticker_map`.
- Add constraints and indexes from PRD §14.
- Encode `filings_13f.parse_status` and `parse_runs.status` as independent statuses.
- Include `is_active_for_manager_period` partial unique index.
- Include `UNIQUE (parse_run_id, holding_row_fingerprint)`.
- Include temporal CUSIP mapping indexes and candidate uniqueness.

Scope Out:
- Parser behavior.
- SEC filing fetch behavior.
- OpenFIGI network calls.
- Admin UI.

Files likely to change:
- `backend/alembic/versions/*`
- `backend/app/models/*`
- `backend/app/schemas/*`
- `backend/tests/unit/*`

Tests to write first:
- Only one active filing per manager/quarter.
- Only one current parse_run per accession.
- Same holding fingerprint can exist in different parse_runs but not twice in one parse_run.
- CUSIP candidate uniqueness works.
- `superseded` and `confirmed` statuses are accepted for temporal mappings.

Docker verification commands:
- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- Schema supports audit history without deleting holdings.
- Schema supports NT active filings without requiring holdings rows.
- Schema supports temporal CUSIP mapping without `is_active`.

Tech Lead Review Gate:
- Mandatory migration review before parser or service implementation uses these tables.

#### 13F-1B-02: Filing Detail Fetch and Period Routing

Goal: Fetch filing detail/header for HR, HR/A, and NT filings, persist raw filing documents, and assign report quarters from `periodOfReport`.

PRD sections: §2.1-§2.4, §4.4, §5, §6.1, §7.1.

Dependencies: 13F-1A-04, 13F-1B-01, G3, G2 for any value-unit parsing touch.

Scope In:
- Fetch filing detail/header.
- Persist raw filing document URL and raw filing document content through existing document/storage patterns.
- Extract `periodOfReport`, `accepted_at`, `form_type`, accession metadata.
- Extract and persist `form_spec_version` and `xml_schema_version` from XML root, namespace, schemaLocation, form header, or equivalent SEC metadata available at filing fetch time.
- Implement quarter normalization and valid filing window checks.
- Missing/invalid period routes to `needs_review` and does not become product-facing active holdings.
- Calculate and store `official_filing_deadline`.
- Create/upsert filing records by accession.

Scope Out:
- Information table holdings parser.
- Amendment replacement.
- OpenFIGI enrichment.
- Frontend.

Files likely to change:
- `backend/app/edgar/*`
- `backend/app/edgar/parsers/*`
- `backend/app/services/*`
- `backend/tests/unit/*`
- `backend/tests/fixtures/*`

Tests to write first:
- `periodOfReport` exact quarter end routes correctly.
- ±1-2 day period normalizes only for HR/HR-A within valid filing window.
- Missing period creates `parse_status=needs_review` with `PERIOD_MISSING`.
- Invalid period creates `failed` or `needs_review` according to PRD §5.3.
- Official filing deadline handles weekend plus federal holiday/special closure.
- XML schema/version metadata is extracted and persisted on the filing record.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- Ownership grouping uses `periodOfReport`, never sync date or filing date.
- All filing window logic uses `official_filing_deadline`.
- Filing metadata ingest is idempotent by accession number.
- `form_spec_version` and `xml_schema_version` are available to the value-unit parser and audit trail.

Tech Lead Review Gate:
- Review period routing and deadline tests before holdings parser work.

#### 13F-1B-03: 13F-NT Header Handling and Query Contract Enforcement

Goal: Implement 13F-NT semantics as coverage/readiness data only, never as empty holdings.

PRD sections: §2.2, §4.4 step 7, §7.1, §7.3 query contract, §10.1, §16.

Dependencies: 13F-1B-01, G3, 13F-1B-02.

Scope In:
- Fetch 13F-NT filing header.
- Parse `other_managers_reporting` with `name`, `cik`, and `file_number` as distinct JSON keys when available, even if the referenced manager is not currently tracked.
- Set `report_type=notice_report`.
- Set `coverage_type=notice_reported_elsewhere`.
- Do not create parse_run or holdings rows for NT.
- Add a service-layer query guard so any future holdings endpoint/service consumer only uses active HR/HR-A filings. This guard must be testable before endpoint work exists.

Scope Out:
- Cross-manager attribution/merge of NT holdings.
- MVP 2 change calculation for NT beyond safe `no_prior_data`/unavailable semantics.
- UI beyond backend response/caveat data.

Files likely to change:
- `backend/app/edgar/parsers/*`
- `backend/app/services/*`
- `backend/app/api/v1/endpoints/*`
- `backend/tests/unit/*`

Tests to write first:
- NT filing creates active coverage record but no parse_run/holdings rows.
- NT is excluded from the service-layer holdings query path.
- Parsed `other_managers_reporting` preserves CIK and 13F file number in distinct JSON keys when present.
- NT is excluded from expected filers denominator where PRD requires.
- Holdings API does not return empty array as "no positions" for NT context; it returns unavailable/caveat metadata where endpoint applies.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- 13F-NT is never represented as "no holdings."
- NT active filing participates only in coverage/readiness/caveat logic.
- Query contract is protected by service-level tests and later reused by API endpoints.

Tech Lead Review Gate:
- Mandatory G5 review before readiness work.

#### 13F-1B-04: HR/HR-A Cover Page and Information Table Parser

Goal: Parse HR/HR-A cover page and holdings into normalized rows with lineage and stable fingerprints.

PRD sections: §6.2, §7.1-§7.2, §18.1-§18.2.

Dependencies: 13F-1B-00, 13F-1B-01, G3, 13F-1B-02.

Scope In:
- Parse cover page `report_type`, `coverage_completeness`, `other_managers_included`, `has_confidential_treatment`.
- Parse information table holdings.
- Assign `source_row_index` before filtering/cleaning.
- Normalize value units using G2-approved rules.
- Store `value_raw`, `value_unit_raw`, `value_parse_rule`, `value_usd`.
- Normalize `investment_discretion` to `SOLE/DFND/OTR`.
- Compute `holding_attribution_status`.
- Compute `holding_row_fingerprint` from raw-row anchored values, excluding parse_run_id.
- Compute total reported and common value fields.

Scope Out:
- OpenFIGI enrichment.
- Amendment activation.
- Computing `portfolio_weight_pct`; MVP 1B must write it as `NULL`, with MVP 2 responsible for calculation.
- UI.

Files likely to change:
- `backend/app/edgar/parsers/*`
- `backend/app/services/*`
- `backend/tests/unit/*`
- `backend/tests/fixtures/*`

Tests to write first:
- Combination Report sets `coverage_completeness=partial`.
- Confidential treatment sets independent `has_confidential_treatment=true`.
- Pre-2023 thousands fixture produces dollars in `value_usd`.
- 2023+ dollars fixture preserves raw dollars.
- `SHARED` normalizes to `OTR` and attribution `shared`.
- `DFND` with parseable manager numbers becomes `reported_for_other`.
- Duplicate fingerprint within one parse_run is rejected.
- Same raw holding content in two parse_runs produces the same `holding_row_fingerprint`, while uniqueness is enforced by `(parse_run_id, holding_row_fingerprint)`.
- MVP 1B writes `portfolio_weight_pct=NULL`.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- Product and analysis amount fields use dollars only.
- Parser preserves raw audit values.
- `portfolio_weight_pct` remains null in MVP 1B, including when totals are present.
- Combination/confidential can coexist.
- Attribution rules prevent shared/unresolved holdings from being counted as direct consensus later.

Tech Lead Review Gate:
- Review parser contract, lineage fields, unit handling, and fingerprint stability.

#### 13F-1B-05: Parse Run Audit, Reparse, Watchdog, and Idempotent Ingestion

Goal: Implement audit-preserving parse execution and reparse semantics.

PRD sections: §6.1-§6.5, §7.3, §12.4, §18.2 abandoned parse_run criterion.

Dependencies: 13F-1B-01, G3, 13F-1B-04, 13F-1A-05.

Scope In:
- Two-phase parse_run creation.
- Bulk insert holdings under new parse_run.
- Atomic switch of current parse_run only after successful holdings insert.
- Failed parse_run audit retention.
- Reparse by accession endpoint/service.
- Watchdog marking stale running parse_runs as `abandoned` when job lease expired.
- Idempotent accession-level skip/retry behavior.

Scope Out:
- Amendment active filing replacement.
- Admin UI for parse run history.

Files likely to change:
- `backend/app/services/*`
- `backend/app/api/v1/endpoints/*`
- `backend/tests/unit/*`

Tests to write first:
- Reparse creates a new current parse_run and retains old holdings.
- Stage 2 failure leaves old current parse_run unchanged.
- Failed parse_run persists with error.
- Watchdog marks stale running parse_run `abandoned`.
- Succeeded accession is skipped unless parser_version requires reparse.
- Succeeded accession is reparsed when `fingerprint_version` does not match the current fingerprint version.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- No DELETE of old holdings is required for reparse.
- Product queries can rely on `parse_runs.is_current=true`.
- Crash/orphan scenario is recoverable and auditable.

Tech Lead Review Gate:
- Review transaction boundaries and failure tests.

#### 13F-1B-06: Amendment Policy and Active Filing Switching

Goal: Implement amendment classification and safe active filing replacement.

PRD sections: §6.6, §7.1, §13 amendment review, §18.

Dependencies: 13F-1B-02, G3, 13F-1B-05.

Scope In:
- Parse amendment type and raw value.
- RESTATEMENT applies only after successful parse.
- Non-RESTATEMENT amendments become `amendments_pending`/needs review.
- `NEW HOLDINGS` requires admin `activate_as_original`.
- Same manager/period multiple original filings use latest `accepted_at`; ambiguous ordering requires admin review.
- Admin pending amendments list and resolve endpoint.

Scope Out:
- Partial amendment merge logic.
- UI.

Files likely to change:
- `backend/app/services/*`
- `backend/app/api/v1/endpoints/*`
- `backend/app/schemas/*`
- `backend/tests/unit/*`

Tests to write first:
- RESTATEMENT switches active filing atomically after parse success.
- RESTATEMENT parse failure keeps old active filing.
- Non-RESTATEMENT does not auto-merge.
- Same accepted_at produces `amendment_sort_warning`.
- `activate_as_original` is limited to `NEW_HOLDINGS`.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- Active product data always points to one manager/quarter filing.
- Original filings, parse_runs, and holdings are retained for audit.
- Ambiguous amendment/original ordering never crashes a unique constraint.

Tech Lead Review Gate:
- Review active filing switch transaction and admin actions.

#### 13F-1B-07: CUSIP Validation, OpenFIGI Mapping, Temporal Mapping, and Advisory Lock

Goal: Implement MVP 1B CUSIP enrichment with temporal validity and conservative auto-confirm rules.

PRD sections: §7.2, §8, §14 CUSIP indexes, §18 CUSIP criteria.

Dependencies: 13F-1B-01, G3, 13F-1B-04.

Scope In:
- CUSIP validation: all-zero, short length, invalid format.
- OpenFIGI client with independent rate limiter and 30-day cache.
- Auto-confirm only when all PRD conditions pass.
- `needs_review` for ambiguous ADR/share class/security type/exchange cases.
- Temporal lookup by quarter using `confirmed` and `superseded`.
- Application-level overlap check under canonical CUSIP 64-bit advisory lock.
- Enrichment writes back `holdings_13f.stock_id` and `holdings_13f.cusip_mapping_status` per holding: `linked` iff `stock_id IS NOT NULL`, `invalid_cusip` for invalid CUSIPs, `needs_review` for ambiguous mappings, `pending_mapping` for retryable provider failures, and `unresolved` when no mapping exists.
- Admin CUSIP mapping list/create/patch/unresolved backend endpoints.

Scope Out:
- Dataroma CUSIP source.
- Corporate action management UI.
- Full frontend review interface unless moved to MVP 1C-2.

Files likely to change:
- `backend/app/services/*`
- `backend/app/api/v1/endpoints/*`
- `backend/app/schemas/*`
- `backend/tests/unit/*`

Tests to write first:
- 7-character CUSIP is invalid and not padded.
- All-zero CUSIP is invalid.
- Single exact OpenFIGI common stock/ETF candidate can confirm.
- Multiple candidates produce `needs_review`.
- Temporal query returns superseded mapping for historical quarter.
- Overlap writes serialize through advisory lock helper and reject conflicts.
- Null `effective_to_quarter` is handled as open-ended in lookup and overlap checks.
- Holding rows receive the correct `cusip_mapping_status` for linked, invalid, unresolved, pending, and needs-review cases.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- `stock_id IS NOT NULL` is the authoritative linked signal.
- `cusip_mapping_status=linked` occurs if and only if `stock_id IS NOT NULL`.
- OpenFIGI failures do not block ingestion.
- Mapping intervals for `confirmed/superseded` cannot overlap for the same CUSIP.

Tech Lead Review Gate:
- G6 review: advisory lock key design, temporal query behavior, null end-date handling, and overlap invariants.

#### 13F-1B-08: Backfill Preview and Confirmed Ingestion Jobs

Goal: Implement explicit admin-driven backfill preview and confirmed job creation.

PRD sections: §3.5, §4, §12, §17 MVP 1B.

Dependencies: 13F-1A-05, 13F-1B-02.

Scope In:
- Preview estimated filings, EDGAR request count, rate limit wait, date/quarter range.
- Use `DEFAULT_BACKFILL_START_QUARTER=2023-Q1` unless the environment overrides it.
- If preview includes quarters before 2023-Q1, explicitly flag that the backfill must use the dual thousands/dollars fixture-validated value-unit rules.
- Explicit confirmation endpoint or existing job endpoint behavior to enqueue backfill.
- No silent backfill from CIK confirmation.
- Job records for daily index backfill and filing ingestion.

Scope Out:
- Full MVP 3 historical backfill automation.
- Reparse-by-quarter/manager MVP 3 endpoints.

Files likely to change:
- `backend/app/services/*`
- `backend/app/api/v1/endpoints/*`
- `backend/tests/unit/*`

Tests to write first:
- Preview does not mutate ingestion state.
- Preview uses the configured `DEFAULT_BACKFILL_START_QUARTER` when no explicit start quarter is provided.
- Preview warns when the requested range crosses the 2023 value-unit transition boundary.
- Confirmation creates expected job rows.
- Duplicate confirmation respects dedupe/lock policy.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- Admin sees work estimate before triggering backfill.
- Backfill preview makes value-unit risk visible for pre-2023-Q1 ranges.
- Backfill jobs use job_runs/locks.

Tech Lead Review Gate:
- Review operational safety before enabling in UI.

### MVP 1C-1: Readiness + Oracle's Lens Safe Integration

#### 13F-1C1-01: Readiness Summary and Data Quality Service

Goal: Compute readiness levels and data quality metrics from current active filings and holdings.

PRD sections: §9.1, §10, §15.2, §18.

Dependencies: 13F-1B-03, 13F-1B-05, 13F-1B-07.

Scope In:
- `ready`, `usable_with_warning`, `experimental`, `unavailable` logic.
- Expected filers excluding 13F-NT.
- Coverage ratio, parse success ratio, linked common holding ratio.
- `nt_detection_supported` and `coverage_ratio.estimated`.
- Confidential and combination report readiness caps.
- `amendments_pending` and `amendment_failed` readiness effects.
- Data gap, NT, confidential, and partial coverage quarter lists.

Scope Out:
- MVP 2 change analysis.
- UI.

Files likely to change:
- `backend/app/services/*`
- `backend/app/api/v1/endpoints/*`
- `backend/app/schemas/*`
- `backend/tests/unit/*`

Tests to write first:
- `nt_detection_supported=false` caps readiness.
- 13F-NT manager excluded from expected filer denominator.
- Confidential active filing caps at `usable_with_warning`.
- Combination active filing caps at `usable_with_warning`.
- CUSIP mapping below threshold blocks ready.
- Pending amendments cap readiness.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- Readiness explains why user features are unavailable or caveated.
- No missing data is represented as zero.
- Readiness uses `official_filing_deadline`, not raw quarter_end + 45.

Tech Lead Review Gate:
- Review readiness truth table and denominator definitions.

#### 13F-1C1-02: User-Facing 13F API Safe Responses

Goal: Expose MVP 1 user APIs with safe snapshot behavior and unavailable responses for future MVP 2 features.

PRD sections: §9.2, §13 Oracle's Lens APIs, §16, §18.

Dependencies: 13F-1C1-01.

Scope In:
- `GET /api/v1/13f/readiness`.
- `GET /api/v1/13f/managers`.
- `GET /api/v1/13f/managers/{manager_id}/holdings`.
- `GET /api/v1/13f/managers/{manager_id}/quarters`.
- `GET /api/v1/13f/managers/{manager_id}/holdings/changes` returns HTTP 200 with `status=unavailable` and structured reason.
- Holdings query uses active HR/HR-A current parse_run only.
- Common/options separation in response fields where relevant.
- Caveat metadata for NT, combination, confidential, and stale/current-quarter filing window.

Scope Out:
- MVP 2 computed changes.
- `/stocks/{stock_id}/holders` full aggregation; if route exists, it must return safe unavailable or minimal non-misleading response until MVP 2.
- Frontend.

Files likely to change:
- `backend/app/api/v1/endpoints/*`
- `backend/app/services/oracles_lens/*`
- `backend/app/schemas/*`
- `backend/tests/unit/*`

Tests to write first:
- Holdings changes returns 200 unavailable, not 503 and not empty array.
- NT manager context does not return empty holdings as "no positions."
- Partial/confidential filings include caveat metadata.
- Options are separate or have null common weight.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- User APIs are safe to wire to UI without overstating data completeness.
- Query contract from PRD §7.3 is preserved.

Tech Lead Review Gate:
- Review response shapes before frontend work starts (G4).

#### 13F-1C1-03: Alert Rules and Data Health Summary

Goal: Implement the MVP 1 alert and health summary rules that depend on readiness and ingestion state.

PRD sections: §15.1-§15.3.

Dependencies: 13F-1A-05, 13F-1C1-01.

Scope In:
- Daily sync consecutive failed business day alert excluding no-index dates.
- Expected filer coverage alert after official deadline.
- CUSIP mapping ratio P1/P2 alerts.
- Amendment pending/failed age alerts.
- Parse status needs_review age alert.
- Job running beyond timeout/lease alert.
- SEC 429/403 alert hook.
- Daily health summary payload/service.
- Scheduled daily health summary delivery at 08:00 ET to Discord when Discord alerting is configured.

Scope Out:
- Email unless existing config enables it.
- UI.

Files likely to change:
- `backend/app/services/*`
- `backend/tests/unit/*`

Tests to write first:
- Each alert condition triggers severity and payload.
- No-index dates are excluded from consecutive daily sync failure.
- Readiness downgrade severity differs for warning vs unavailable.
- 08:00 ET scheduler invokes the health summary service and posts through the alert/Discord abstraction.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- P1/P2/P3 semantics match PRD.
- Alert logic is testable without real Discord.
- Daily health summary is delivered by a scheduled trigger, not only generated as a payload.

Tech Lead Review Gate:
- Review noisy-alert risk and exclusion rules.

### MVP 1C-2: Admin Dashboard

#### 13F-1C2-01: Admin Backend Read Models for Dashboard Pages

Goal: Stabilize backend data contracts for the admin dashboard before building UI.

PRD sections: §11, §13 admin endpoints.

Dependencies: 13F-1C1-01, 13F-1C1-03.

Scope In:
- Admin status/readiness endpoint summaries.
- Filings list/detail with report_type, coverage_completeness, confidential treatment, amendments.
- Parse runs list by accession.
- Jobs list/detail/cancel support.
- Holdings coverage summaries.
- Pending amendments endpoint.
- CUSIP mappings unresolved endpoint.

Scope Out:
- Frontend UI.
- MVP 3 batch reparse endpoints.

Files likely to change:
- `backend/app/api/v1/endpoints/*`
- `backend/app/services/*`
- `backend/app/schemas/*`
- `backend/tests/unit/*`

Tests to write first:
- Admin filings expose caveat-driving fields.
- Parse runs endpoint returns audit history.
- Jobs filters support status/job_type/date/sync_date/quarter.
- Pending amendments grouped by type/status.

Docker verification commands:
- `docker compose exec api pytest -q tests/unit`

Acceptance Criteria:
- Frontend can build all MVP 1C-2 admin pages without inventing data semantics.
- Pagination is implemented for list endpoints.

Tech Lead Review Gate:
- Review API contracts and pagination before UI starts.

#### 13F-1C2-02: Admin Dashboard UI

Goal: Build the MVP 1C-2 admin dashboard pages using established frontend standards.

PRD sections: §11, §13, §16, frontend standards in `AGENTS.md`.

Dependencies: 13F-1C2-01, G4.

Scope In:
- Overview page.
- Managers page.
- Daily Sync page.
- Filings page.
- Holdings Coverage page.
- Jobs page.
- Readiness page.
- Parse runs view.
- Display report_type, coverage_completeness, confidential treatment, amendments, and NT caveats.
- Use `frontend/components/ui/` shadcn-style components.
- Use Tailwind for layout and component-specific adjustments.
- Use lucide-react for all new 13F admin control icons where an icon is needed.

Scope Out:
- MVP 3 CUSIP corporate action temporal mapping UI.
- Raw form/control primitives in product UI.
- Marketing/landing pages.

Files likely to change:
- `frontend/app/(dashboard)/admin/*`
- `frontend/app/(dashboard)/13f/*`
- `frontend/components/admin13f/*`
- `frontend/components/ui/*` only when a needed shadcn component is missing
- `frontend/lib/api/*`

Tests to write first:
- Component/unit tests if existing frontend test harness supports them.
- API client contract tests if present.
- At minimum, type/lint/build verification.

Docker verification commands:
- `docker compose exec frontend npm run lint`
- `docker compose exec frontend npm run build`

Acceptance Criteria:
- Admin can inspect health, sync dates, filings, parse_runs, jobs, readiness, and coverage.
- UI does not display missing data as zero.
- NT, combination, confidential treatment caveats are visible where relevant.
- Controls use shared UI components and Tailwind.
- New 13F admin icon controls consistently use lucide-react.

Tech Lead Review Gate:
- Visual/UX review plus code review for frontend standards compliance.

#### 13F-1C2-03: MVP 1 End-to-End Verification and Contract Gate

Goal: Verify MVP 1A/1B/1C behavior end to end and produce a final contract checklist.

PRD sections: §18, §19, all MVP 1 sections.

Dependencies: All MVP 1A, 1B, 1C-1, 1C-2 tasks.

Scope In:
- Run full relevant backend test suite.
- Run frontend lint/build.
- Run migrations from clean database state if feasible.
- Verify fixture-backed ingestion paths.
- Verify readiness and caveat behavior.
- Update the final implementation task log with verification results.

Scope Out:
- New feature work.
- MVP 2/3 work.

Files likely to change:
- `docs/tasks/*` implementation logs only, if needed.

Tests to write first:
- No new tests expected unless verification exposes gaps.

Docker verification commands:
- `docker compose up -d --build`
- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q`
- `docker compose exec frontend npm run lint`
- `docker compose exec frontend npm run build`

Acceptance Criteria:
- All relevant tests pass in Docker.
- MVP 1 acceptance criteria from PRD §18 are either satisfied or explicitly marked deferred with human approval.
- No PRD contract violations:
  - 13F-NT never means no holdings.
  - Holdings queries use current parse_run for active HR/HR-A filings only.
  - Value units are normalized to dollars.
  - Parse audit is retained.
  - Official filing deadline is used for filing window logic.
  - CUSIP temporal mapping uses effective quarter windows.

Tech Lead Review Gate:
- Final MVP 1 contract review before merge/release.

## Fixture Strategy

Required fixtures before or during MVP 1B:

- Daily index fixture with tracked and untracked CIK rows for `13F-HR`, `13F-HR/A`, and `13F-NT`.
- 13F-NT filing header with `periodOfReport` and `otherManagersInfo`.
- Normal 13F-HR holdings report.
- Combination Report cover page.
- Confidential treatment sample.
- 13F-HR/A RESTATEMENT sample.
- Non-RESTATEMENT amendment samples if available; otherwise minimal synthetic XML parser fixtures may be used for enum routing tests.
- At least two 2022-or-earlier value-unit fixtures and two 2023-or-later fixtures for G2.
- CUSIP mapping fixtures:
  - valid common stock/ETF exact match
  - multiple candidates
  - invalid short CUSIP
  - all-zero CUSIP
  - temporal superseded/confirmed mapping pair

Fixture rules:
- Prefer real SEC/EDGAR XML fixtures for parser behavior.
- Store expected parser outputs close to fixture files.
- Do not use live SEC/OpenFIGI calls in unit tests.
- Mock SEC/OpenFIGI clients for service tests.

## Migration Strategy

- Use incremental Alembic revisions by MVP slice.
- Prefer schema changes before service code in each MVP.
- Keep migrations forward-only for development; downgrade support should preserve existing project standards if present.
- Review partial unique indexes carefully:
  - `filings_13f(accession_number)` unique
  - current parse_run unique by accession
  - active filing unique by manager/quarter
  - holding fingerprint unique within parse_run
- Use application-level CUSIP overlap checks with transaction-scoped advisory lock for MVP 1.
- Do not add database exclusion constraints for CUSIP ranges until MVP 2/3 unless Tech Lead approves.

## API Contract Strategy

- Backend response shapes must stabilize before frontend work.
- Unavailable states are explicit response bodies, not empty arrays and not HTTP 503 for normal coverage limitations.
- Admin list endpoints must paginate.
- User endpoints must include caveat metadata where data can be partial, confidential, delayed, unavailable, or NT-reported elsewhere.
- `holdings/changes` must return HTTP 200 + `status=unavailable` until MVP 2.
- 13F-NT active filings must not enter holdings query joins.

## UI Strategy

- MVP 1C-2 admin UI starts only after G4 API contract review.
- Use shadcn/ui-style components under `frontend/components/ui/`.
- Add missing shared UI components first instead of one-off primitives.
- Use Tailwind classes for layout and local adjustments.
- Use lucide-react icons in icon controls.
- Do not show missing data as `0`.
- Do not label 13F data as current holdings, cost basis, buy signal, or total AUM.
- Must show caveats for:
  - 13F delayed snapshots
  - 13F-NT reported elsewhere
  - Combination Report partial coverage
  - Confidential treatment
  - unavailable ratios with no denominator

## MVP 2 / MVP 3 Backlog

Do not implement during MVP 1.

MVP 2 backlog:
- Consecutive-quarter ownership change analysis.
- Precomputed `ownership_changes`.
- CUSIP_CHANGED change-status handling.
- `/stocks/{stock_id}/holders` aggregation.
- Manager consensus, featured holder counts, recent changes.
- Corporate action data source decision.
- Per-manager CUSIP mapping threshold decision.
- 13F-NT cross-reference strategy decision.

MVP 3 backlog:
- Full historical backfill.
- Dataroma CUSIP source.
- Batch reparse by quarter/manager.
- CUSIP corporate action temporal mapping UI.
- Filing-level `value_unit_override`.
- Full data integrity validation jobs.

## Verification Checklist

Before closing MVP 1:

- [ ] `docker compose up -d --build` succeeds.
- [ ] `docker compose exec api alembic upgrade head` succeeds.
- [ ] `docker compose exec api pytest -q` succeeds.
- [ ] `docker compose exec frontend npm run lint` succeeds for UI work.
- [ ] `docker compose exec frontend npm run build` succeeds for UI work.
- [ ] Daily sync identifies HR, HR/A, and NT.
- [ ] No-index expected dates support auto-generated and admin-manual sources.
- [ ] Filing period routing uses `periodOfReport`.
- [ ] Filing window logic uses `official_filing_deadline`.
- [ ] Value-unit fixtures prove thousands/dollars rules.
- [ ] Parse runs retain audit history and current pointer semantics.
- [ ] 13F-NT active filing does not create parse_run/holdings and does not mean no holdings.
- [ ] RESTATEMENT amendment switches active filing only after successful parse.
- [ ] Non-RESTATEMENT amendments require review.
- [ ] CUSIP temporal mapping returns historical superseded mappings.
- [ ] Readiness distinguishes zero from unavailable.
- [ ] Oracle's Lens MVP 1 change endpoint returns HTTP 200 unavailable.
- [ ] Admin UI uses shared UI components and displays caveats.

## Immediate Next Steps

Tasks that can start immediately after human approval of this plan:

1. 13F-1A-01 Schema Foundation for Managers, Sync Status, No-Index Dates, and Job Runs.
2. 13F-1A-03 Shared SEC Client, EDGAR Rate Limiter, and User-Agent Fail-Fast, if it can be implemented independently against existing config patterns.
3. 13F-1B-00 Value-Unit Spike Gate, in parallel with MVP 1A, because it is research/fixture work and blocks MVP 1B parser implementation.

Tasks requiring human approval or fixture preparation:

- 13F-1B-00 requires approved real SEC fixture set and final value-unit mapping review.
- 13F-1B-01 requires Tech Lead migration review.
- 13F-1B-07 requires G6 CUSIP temporal mapping review before CUSIP-backed product/readiness use.
- 13F-1C2-02 requires API contract review before frontend starts.
- Any PRD change or MVP 2/3 early implementation requires explicit human approval.
