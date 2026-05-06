# 13F Admin Data Operations Dashboard Product Plan

## 1. Summary

ValuePilot already has the core EDGAR 13F ingestion pipeline, but the production operating experience is still too implicit. Today, `EDGAR_SCHEDULER_ENABLED=true` only means the scheduler is allowed to run. It does not guarantee that the system has a confirmed manager / CIK whitelist, that the latest quarter has been indexed, or that holdings have been parsed and mapped to stocks.

This plan defines an admin-facing 13F Data Operations dashboard that makes the ingestion system self-explaining:

- What data do we have?
- Which quarters are complete, partial, stale, or failed?
- What does the administrator need to fix?
- Can the administrator manually trigger or retry ingestion safely?
- Is an incomplete quarter actually a problem, or is it still inside the SEC filing window?

The first version should be operational and table-first, not decorative. Its job is to help an administrator confidently move 13F data from "configured" to "usable".

## 2. Current Known State

As of 2026-05-06, the observed production state was:

- `EDGAR_SCHEDULER_ENABLED=true`
- `institution_managers=0`
- `filings_13f=0`
- `holdings_13f=0`
- `cusip_ticker_map=0`
- `raw_source_documents` had one EDGAR `form_idx` document for `2025/QTR4`, but no derived filings or holdings

This is an important product lesson: the scheduler can be enabled while the pipeline has no usable capture target. The dashboard must not show this as a normal empty data state. It should show a clear blocking setup task:

> No confirmed manager / CIK whitelist. Bootstrap managers and confirm CIKs before scheduled 13F ingestion can produce holdings.

For the current calendar point, 2026-Q1 filings are in progress. The approximate Q1 filing deadline is 2026-05-15. Therefore, on 2026-05-06, a partial 2026-Q1 quarter is expected and should be labeled as "Filing window open", not "failed" or "incomplete" unless ingestion jobs are failing.

## 3. Goals

- Give admins a single place to understand 13F ingestion readiness.
- Show quarter-by-quarter progress, including partial quarters during the filing window.
- Convert hidden prerequisites into explicit checklist items.
- Provide a safe manual control surface for bootstrap, backfill, retry, enrichment, and quality checks.
- Separate "normal partial data" from "pipeline broken".
- Make Oracle's Lens and other 13F-powered user features depend on clear data readiness signals.

## 4. Non-Goals

- Do not redesign Oracle's Lens or investor-facing 13F analysis.
- Do not treat 13F data as current holdings or buy recommendations.
- Do not make Dataroma a source of truth for holdings.
- Do not let Dataroma availability block pure EDGAR ingestion for already confirmed managers.
- Do not expose raw EDGAR operations to non-admin users.
- Do not auto-confirm low-confidence manager / CIK matches without admin review.

## 4.1 Admin-Resolvable vs Escalation Required

The admin dashboard should cover the full operational loop for 13F ingestion: detect the problem, explain why it matters, offer a safe action when one exists, record the result, and clearly escalate issues that cannot be fixed by an administrator.

The product goal is not "admins can fix every possible 13F problem." The goal is:

> Admins can resolve normal data operations issues from the dashboard, and engineering-only or external dependency failures are clearly identified with evidence and next-step guidance.

### Admin-Resolvable Issues

These issues should be directly fixable from the dashboard through allowlisted UI actions.

| Issue | Dashboard Evidence | Admin Resolution |
| --- | --- | --- |
| No manager whitelist | `institution_managers=0` | Run `Bootstrap whitelist` |
| Managers seeded but no confirmed CIKs | confirmed CIK count = 0, candidates may exist | Run `Match CIK`, then review candidates |
| CIK candidates awaiting review | `match_status='candidate'` count > 0 | Confirm, reject, or retry search |
| Quarter not indexed | no `form_idx` raw document for target quarter | Fetch quarter index |
| Quarter index fetched but filings missing | `form_idx` exists, `filings_13f=0` | Check whitelist, rerun quarter ingest |
| Holdings not parsed for pending filings | filings exist with `raw_infotable_doc_id IS NULL` | Run or retry holdings ingest |
| Some filings failed | failed job records or filing-level errors | Retry failed filings |
| CUSIP / stock mapping incomplete | low linked holdings ratio | Run CUSIP enrichment and stock backfill |
| Quality check not current | no latest quality job for quarter | Run quality check |
| Historical coverage too shallow | fewer than target backfill quarters | Run historical backfill |

Admin actions must be constrained to known internal jobs. The UI must never expose arbitrary shell command execution.

### Escalation Required Issues

These issues should be visible in the dashboard, but the primary action is to preserve evidence and escalate to engineering or wait for an external dependency to recover.

| Issue | Dashboard Evidence | Escalation Path |
| --- | --- | --- |
| SEC rate limit or block | repeated 429 / 403 responses, request throttling errors | Pause jobs, show retry-after guidance, escalate if persistent |
| SEC response format changed | parser errors across many filings or schema mismatch | Create engineering task with sample accession numbers |
| Dataroma unavailable or changed | bootstrap / enrichment failures from Dataroma parsing | Fall back to existing whitelist or pure EDGAR path; escalate parser update |
| Job worker unavailable | jobs stuck queued or no active worker heartbeat | Restart / inspect worker or deployment |
| Database or migration issue | SQL errors, missing tables, migration mismatch | Engineering / deployment intervention |
| Storage failure | raw document write/read errors | Infrastructure intervention |
| Code bug in parser or enrichment | deterministic failure on known filing after retry | Engineering fix with fixture coverage |
| Ambiguous manager identity | low-confidence CIK candidate with insufficient evidence | Human research; do not auto-confirm |

Escalation cards should include:

- failure category
- first seen / last seen
- affected quarter or filing accession
- latest error message
- recommended owner: Admin, Engineering, Infrastructure, or External Dependency
- safe immediate action: retry later, pause jobs, or open engineering task

This boundary keeps the dashboard powerful without pretending that every external or code-level failure can be solved by clicking a button.

## 5. Admin Jobs To Be Done

1. As an admin, I want to know whether 13F ingestion is actually ready, not merely enabled.
2. As an admin, I want to see which setup steps are blocking data capture.
3. As an admin, I want to review candidate manager / CIK matches and confirm or reject them.
4. As an admin, I want to see each quarter's capture status and whether the quarter is expected to be partial.
5. As an admin, I want to manually trigger backfill or retry jobs without SSHing into the server.
6. As an admin, I want to know which failures require action and which will be retried automatically.
7. As an admin, I want to know whether holdings are mapped to stocks well enough for product use.

## 6. Information Architecture

The dashboard should live under an admin-only route:

`/admin/13f`

Recommended navigation tabs:

| Tab | Purpose |
| --- | --- |
| Overview | Health, current quarter, latest usable period, major blockers |
| Quarters | Quarter-by-quarter status table and drilldowns |
| Tasks | Admin action queue ordered by severity |
| Managers | Whitelist and CIK review workflow |
| Jobs | Scheduled and manual job runs, retries, logs |
| Quality | Coverage, CUSIP mapping, linked holdings, validation checks |

For V1, these can be one page with anchored sections. The route should still be conceptually organized around these tabs so it can grow cleanly.

## 7. Overview Design

### 7.1 Top Health Banner

The top banner answers: "Can 13F data be trusted right now?"

Recommended states:

| State | Meaning | Example Copy |
| --- | --- | --- |
| Setup Required | Blocking prerequisites are missing | "13F ingestion is enabled, but no confirmed manager / CIK whitelist exists." |
| Operational | Scheduler and prerequisites are healthy | "13F ingestion is operational. Latest usable quarter: 2025-Q4." |
| Partial Current Quarter | Current quarter is inside filing window | "2026-Q1 filings are arriving. Completeness is expected to improve until 2026-05-15." |
| Needs Attention | Data exists but quality or job failures require admin action | "3 filings failed to parse and 18% of holdings are not linked to stocks." |
| Stale | No successful ingestion after expected deadline | "Latest complete quarter is older than expected. Run or inspect the quarterly pipeline." |

The banner should include:

- Scheduler enabled / disabled
- Latest available quarter by deadline logic
- Latest usable quarter in product APIs
- Current quarter filing window status
- Last successful job time
- Top blocking task

### 7.2 Setup Checklist

This checklist should be visible whenever the system is not fully ready.

| Step | Data Source | Complete When | Admin Action |
| --- | --- | --- | --- |
| Scheduler configured | settings / env | `EDGAR_SCHEDULER_ENABLED=true` | Toggle env / deploy |
| Manager whitelist seeded | `institution_managers` | manager count > 0 | Run bootstrap whitelist |
| CIKs confirmed | `institution_managers` | confirmed CIK count > minimum threshold | Run match CIK, review candidates |
| Quarter index fetched | `raw_source_documents` | form.idx exists for target quarter | Fetch quarter index |
| Filing metadata ingested | `filings_13f` | filings exist for confirmed managers | Run quarter ingest |
| Holdings parsed | `holdings_13f` | holdings exist for filings | Run / retry holdings ingest |
| CUSIP mapping built | `cusip_ticker_map`, `holdings_13f.stock_id` | linked holding ratio above threshold | Run enrichment |
| Quality checked | quality report / job run | latest check passed or warnings accepted | Run quality check |

### 7.3 Current Quarter Card

For a date like 2026-05-06, the card should say:

- Quarter: `2026-Q1`
- Quarter end: `2026-03-31`
- Approximate filing deadline: `2026-05-15`
- Phase: `Filing window open`
- Completeness interpretation: "Partial data is expected before the deadline."

Metrics:

- Confirmed managers being tracked
- Managers filed
- Managers pending
- Filings indexed
- Holdings parsed
- Failed filings
- Linked holdings ratio
- Last index refresh
- Last holdings refresh

Primary action:

- `Refresh filing progress`

Secondary actions:

- `Fetch latest quarter`
- `Retry failed filings`
- `Run enrichment`

## 8. Quarter Status Model

The legacy single-label status below can still be used as a display convenience, but implementation should derive it from `quarter_phase` and `quarter_health`.

### 8.1 Phase vs Health

A quarter has two related but separate states:

- `quarter_phase`: the calendar / SEC filing-window state.
- `quarter_health`: the operational data-readiness state.

This separation prevents a normal filing-window state from hiding real pipeline problems.

Recommended `quarter_phase` values:

| Phase | Meaning |
| --- | --- |
| `pre_window` | Quarter has not ended or the filing window has not opened. |
| `filing_window_open` | Quarter ended and 13F filings are still expected to arrive. |
| `post_deadline` | The approximate 13F filing deadline has passed. |

Recommended `quarter_health` values:

| Health | Meaning |
| --- | --- |
| `setup_required` | Blocking prerequisites such as confirmed manager / CIKs are missing. |
| `not_started` | The quarter is eligible for ingestion but no index, filings, or holdings exist. |
| `index_fetched` | A quarter index exists, but no relevant filing metadata has been inserted. |
| `ingesting` | A job for the quarter is currently running. |
| `partial` | Some data exists and incompleteness is expected or not yet resolved. |
| `needs_review` | Admin action is required for candidates, failed filings, low coverage, or quality warnings. |
| `failed` | The latest job failed before producing usable data. |
| `complete` | The quarter is complete enough for product use. |
| `stale` | A newer usable quarter should exist but does not. |

The UI may present a combined label such as `Filing Window Open · Partial` or `Post Deadline · Needs Review`, but APIs should preserve the separate fields.

### 8.2 Status Resolution Rules

Quarter state must be derived deterministically. When multiple conditions apply, the dashboard should preserve both timing phase and operational health instead of collapsing everything into a single ambiguous status.

Resolution rules:

- If no confirmed manager CIKs exist, `quarter_health` should be `setup_required` regardless of quarter timing.
- `filing_window_open` should not hide actual job failures. If jobs are failing, show `needs_review` or `failed` health even during the filing window.
- Partial data before the filing deadline is expected if there are no job failures.
- Missing data after the filing deadline should become `needs_review` or `stale` depending on last successful job time and expected coverage.
- Active jobs should surface as `ingesting`, but blockers and failures should remain visible as supporting evidence.
- A quarter should be considered `complete` only when tracked managers have filed or are accepted as not filed, holdings are parsed, and quality checks pass or warnings have been explicitly accepted.

Suggested precedence for `quarter_health` when multiple conditions apply:

1. `setup_required`
2. `failed`
3. `needs_review`
4. `ingesting`
5. `stale`
6. `not_started`
7. `index_fetched`
8. `partial`
9. `complete`

| Status | Criteria | Admin Interpretation |
| --- | --- | --- |
| Not Available | Filing deadline window has not opened | No action needed |
| Filing Window Open | Quarter ended, deadline not yet reached | Partial data is normal |
| No Whitelist | No confirmed manager CIKs | Setup required before ingestion can work |
| Not Started | Deadline reached or target quarter selected, no index or filings | Run ingestion |
| Index Fetched | `form_idx` exists, no filings inserted | Investigate whitelist or parser |
| Partial | Some filings / holdings exist, not all expected managers filed | Monitor or refresh |
| Ingesting | Active job currently running | Wait or inspect job logs |
| Complete | Deadline passed, tracked managers filed or accepted as not filed, quality checks pass | Safe for product use |
| Needs Review | Candidate CIKs, failed filings, quality errors, or low link coverage | Admin action required |
| Failed | Latest job failed before producing usable data | Retry or inspect logs |
| Stale | Newer quarter should be available but latest usable quarter is older | Run pipeline |

Important nuance: before 2026-05-15, 2026-Q1 should generally be `Filing Window Open` or `Partial`, not `Failed`, unless actual jobs are failing.

## 9. Quarter Table

The Quarters table should be the operational backbone.

Columns:

- Quarter
- Phase / Status
- Filing deadline
- Tracked managers
- Filed managers
- Pending managers
- Filings indexed
- Holdings parsed
- Failed filings
- Linked holdings ratio
- Quality status
- Last successful job
- Actions

Example rows:

| Quarter | Status | Deadline | Filed / Tracked | Holdings | Linked | Action |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-Q1 | Filing Window Open | 2026-05-15 | 23 / 80 | 14,210 | 82% | Refresh |
| 2025-Q4 | Needs Review | 2026-02-14 | 0 / 0 | 0 | 0% | Setup whitelist |
| 2025-Q3 | Not Started | 2025-11-14 | 0 / 0 | 0 | 0% | Backfill |

The exact numbers above are illustrative. The product must use live counts from the database.

## 10. Admin Task Queue

The dashboard should list admin tasks in priority order. This is the most important usability layer.

Task types:

| Priority | Task | Trigger | Resolution |
| --- | --- | --- | --- |
| P0 | No confirmed manager / CIK whitelist | confirmed manager count = 0 | Bootstrap whitelist, match CIK, review candidates |
| P0 | Scheduler disabled in prod | env false | Enable and redeploy |
| P1 | CIK candidates need review | candidate count > 0 | Confirm or reject candidate |
| P1 | Quarter index fetched but no filings | form_idx exists, filings = 0 | Check whitelist and form parser |
| P1 | Filing parse failures | failed filings > 0 | Retry failed filings or inspect EDGAR document |
| P1 | Current quarter stale after deadline | deadline passed, no latest quarter data | Run quarterly pipeline |
| P2 | Low stock link coverage | linked holding ratio below threshold | Run CUSIP enrichment, review unmatched CUSIPs |
| P2 | Quality warnings | quality checks warning only | Review and accept or fix |
| P3 | Backfill recommended | fewer than target historical quarters | Run historical backfill |

Each task card should include:

- Problem
- Why it matters
- Evidence
- Recommended action
- Button to resolve where safe
- Link to relevant detail view

Example task:

> No confirmed manager / CIK whitelist
> 13F scheduler is enabled, but there are no confirmed managers with CIKs. Scheduled ingestion cannot create filings or holdings.
> Action: Run `Bootstrap whitelist`, then `Match CIK`, then review candidates.

## 11. Manual Actions

Admins should be able to manually trigger jobs from the UI. All actions should create an auditable job run record.

Recommended actions:

| Action | Existing CLI Equivalent | Confirmation Required | Notes |
| --- | --- | --- | --- |
| Bootstrap whitelist | `bootstrap-whitelist` | Yes | Uses Dataroma only as a discovery source; EDGAR remains source of truth for filings and holdings |
| Match CIK | `match-cik` | Yes | May create candidates requiring review |
| Fetch quarter index | `fetch-holdings --quarter YYYY-Qn` | Yes | Name should be clearer in UI: "Fetch quarter index" |
| Ingest holdings | `ingest-holdings --quarter YYYY-Qn` | Yes | Retry-safe for pending filings |
| Backfill quarters | `backfill --quarters N` | Yes | Show SEC rate-limit warning |
| Enrich CUSIP | `enrich-cusip` | Yes | Uses Dataroma only as a helper; preserve provenance and do not override EDGAR-derived facts without review |
| Bootstrap stocks | `bootstrap-stocks` | Yes | Creates stock links from mappings |
| Enrich stocks from EDGAR | `enrich-stocks-edgar` | Yes | Official source enrichment |
| Quality check | `quality-check --quarter YYYY-Qn` | No for read-only check | Should be safe and frequent |
| Retry failed filings | filtered ingest retry | Yes | Prefer targeted retry over full rerun |

Manual action UX:

- Disable duplicate job buttons while the same job is running.
- Show expected duration and rate-limit warning.
- Show dry-run style preview when possible: target quarter, tracked managers, pending filings.
- Require confirmation for network-heavy jobs.
- Persist all job runs.

### 11.1 Manual Action Safety Contract

Every manual action must define a safety contract before it is exposed in the UI:

- allowlisted `job_type` enum
- idempotency behavior
- tables written
- dry-run support, when practical
- duplicate job `lock_key`
- retry behavior
- cancellation behavior
- audit summary fields
- product readiness impact

Manual actions must use upsert, replace-safe, or skip-existing semantics wherever possible. Retrying a quarter or filing must not duplicate filings, holdings, raw documents, manager candidates, CUSIP mappings, or stock links.

Recommended action metadata:

| Action | Idempotency Expectation | Writes | Retry Behavior | Product Impact |
| --- | --- | --- | --- | --- |
| Bootstrap whitelist | Mostly idempotent | `institution_managers` | Upsert managers; do not duplicate existing rows | May unlock setup checklist |
| Match CIK | Partially idempotent | manager candidate / status fields | Reuse or supersede prior candidates with audit history | Enables admin review, but not ingestion until confirmed |
| Fetch quarter index | Idempotent | `raw_source_documents` | Reuse existing raw document or replace safely | Enables filing metadata ingestion |
| Ingest holdings | Must be idempotent | `filings_13f`, `holdings_13f`, raw infotable documents | Skip existing accession numbers or replace a filing atomically | Directly affects readiness and Oracle's Lens coverage |
| Backfill quarters | Must be idempotent per quarter | same as quarter ingestion | Resume from completed quarters and retry failed filings only | Expands historical coverage |
| Enrich CUSIP | Must be idempotent | `cusip_ticker_map`, `holdings_13f.stock_id` | Upsert mappings; preserve provenance | Improves stock link coverage |
| Bootstrap stocks | Must be idempotent | stocks and related mapping fields | Upsert by stable symbol / CUSIP identity | Improves product usability |
| Quality check | Read-only or report-write only | quality report / job summary | Safe to rerun frequently | Updates readiness and warnings |

Network-heavy and write-heavy actions should preview their target quarter, tracked managers, estimated filings, and rate-limit risk before execution.

## 12. Manager / CIK Review

The Managers tab should replace direct DB edits for candidate review.

Columns:

- Display name from Dataroma
- Parsed manager company name
- Candidate EDGAR legal name
- CIK
- Similarity score
- Current status
- Last checked
- Actions
- Evidence source
- Evidence URL
- Prior rejected candidates
- Review note

Actions:

- Confirm candidate
- Reject candidate
- Edit search name and retry
- Mark as ignored
- Open SEC entity page

Rules:

- Auto-confirm only high-confidence matches, as existing code already does.
- Candidate matches must not be used by ingestion until confirmed.
- Rejected candidates should be retained for audit, not deleted silently.
- Confirming a CIK should immediately make the manager eligible for the next ingestion run.

### 12.1 CIK Confirmation Audit

CIK confirmation is a high-impact data operation because a wrong CIK contaminates every downstream filing and holding for that manager. Candidate review must retain provenance and review history.

Each candidate should retain:

- source
- evidence URL
- similarity score
- created_at
- last_checked_at
- confirmed_or_rejected_by
- confirmed_or_rejected_at
- review note
- prior rejected candidates for the same manager

The confirmation UI should show the Dataroma display name, parsed manager company name, EDGAR legal name, CIK, SEC entity link, similarity score, evidence source, and any prior rejected candidates before allowing confirmation.

## 13. Job Runs And Audit Trail

The product needs a persistent job history. Logs alone are not enough.

Recommended `job_runs` concept:

- id
- job_type
- status: queued, running, succeeded, partial_success, failed, cancel_requested, canceled, skipped
- requested_by_user_id
- trigger_source: scheduler, manual, deployment, retry
- dedupe_key
- lock_key
- quarter
- started_at
- finished_at
- input_json
- summary_json
- error_message

Useful summary fields:

- managers_seen
- managers_confirmed
- filings_inserted
- filings_failed
- holdings_inserted
- raw_documents_fetched
- mappings_created
- holdings_linked
- quality_errors
- quality_warnings

`dedupe_key` and `lock_key` should be stable enough to prevent duplicate network-heavy or write-heavy jobs. Common examples include `job_type + quarter`, `job_type + accession`, or `job_type + quarter + manager_id`. A job that succeeds for most filings but fails for some should use `partial_success` with failure details in `summary_json`, not a misleading all-or-nothing status.

This allows the UI to answer "what happened?" without scraping container logs.

## 14. Data Quality And Product Readiness

Quality should be shown as product readiness, not just engineering validation.

Core indicators:

- Manager coverage: filed managers / confirmed tracked managers
- Holding coverage: holdings parsed / expected filings
- Stock link coverage: holdings with `stock_id` / total holdings
- CUSIP map coverage: CUSIPs mapped / distinct CUSIPs
- Failed filing count
- Amendment handling status
- Latest usable period
- Data age

Suggested readiness levels:

| Level | Meaning | Product Use |
| --- | --- | --- |
| Unavailable | No holdings data | Hide or show setup notice |
| Experimental | Data exists but quality is weak | Admin only |
| Usable With Warning | Most data present, known gaps | Show user caveats |
| Ready | Complete enough for user-facing features | Normal display |

Oracle's Lens should consume a readiness summary so it can show a clear empty/setup/partial state instead of silently returning zero candidates.

### 14.1 Readiness Contract For Consumer Features

Oracle's Lens and other 13F-powered features must consume a readiness summary instead of inferring state directly from raw table counts.

The readiness contract should include:

- readiness_level
- frontend_behavior
- latest_usable_quarter
- current_quarter_phase
- current_quarter_health
- blockers
- warnings
- unavailable_reasons
- key coverage ratios
- last_successful_job_at

Recommended `frontend_behavior` values:

| Behavior | Meaning |
| --- | --- |
| `hide_feature` | Feature should not be shown because no usable data exists. |
| `show_setup_required` | Show an admin/setup notice instead of an empty investment result. |
| `show_partial_warning` | Show data with a clear current-quarter partial warning. |
| `show_with_warning` | Show data but surface quality or coverage warnings. |
| `show_normally` | Data is ready for normal user-facing display. |

Example readiness payload:

```json
{
  "feature": "oracles_lens",
  "readiness_level": "usable_with_warning",
  "frontend_behavior": "show_with_warning",
  "latest_usable_quarter": "2025-Q4",
  "current_quarter": {
    "quarter": "2026-Q1",
    "phase": "filing_window_open",
    "health": "partial",
    "is_partial_expected": true,
    "filing_deadline": "2026-05-15"
  },
  "blockers": [],
  "warnings": [
    {
      "code": "LOW_STOCK_LINK_COVERAGE",
      "message": "82% of holdings are linked to stocks."
    }
  ],
  "counts": {
    "confirmed_managers": 80,
    "filed_managers": 23,
    "failed_filings": 3,
    "linked_holdings_ratio": 0.82
  },
  "last_successful_job_at": "2026-05-06T10:30:00Z"
}
```

### 14.2 Zero vs Unavailable

Quality metrics must distinguish zero from unavailable.

Rules:

- `0` failed filings means filings were checked and none failed.
- `null` failed filings with an `unavailable_reason` means filings were not checked.
- `0%` linked holdings means holdings exist but none linked.
- `null` linked holdings ratio means no holdings denominator exists.
- Missing denominator data should never be displayed as `0%`.

Metric payloads should support:

```json
{
  "metric": "linked_holding_ratio",
  "value": null,
  "status": "unavailable",
  "unavailable_reason": "NO_HOLDINGS_PARSED",
  "last_checked_at": null
}
```

## 15. API Requirements

Proposed admin endpoints:

- `GET /api/v1/admin/13f/status`
- `GET /api/v1/admin/13f/readiness`
- `GET /api/v1/admin/13f/quarters`
- `GET /api/v1/admin/13f/quarters/{quarter}`
- `GET /api/v1/admin/13f/tasks`
- `GET /api/v1/admin/13f/managers`
- `POST /api/v1/admin/13f/managers/{id}/confirm-cik`
- `POST /api/v1/admin/13f/managers/{id}/reject-cik`
- `GET /api/v1/admin/13f/jobs`
- `POST /api/v1/admin/13f/jobs`
- `POST /api/v1/admin/13f/jobs/{id}/cancel`
- `POST /api/v1/admin/13f/jobs/retry-failed-filings`

The job trigger endpoint should accept a constrained enum, not arbitrary shell commands.

Example job request:

```json
{
  "job_type": "backfill_quarters",
  "quarter": null,
  "quarters": 8,
  "dry_run": false
}
```

The job trigger endpoint must reject duplicate active jobs that share the same `lock_key` with a conflict response instead of starting another job.

## 16. Permission And Safety Requirements

- Only admin users can access the dashboard.
- Manual ingestion actions require admin permissions.
- Network-heavy jobs require confirmation.
- Only one job of the same type and quarter should run at a time.
- Duplicate job prevention should be enforced with a stable `lock_key`, not only disabled UI buttons.
- EDGAR rate limits must be respected across manual and scheduled jobs.
- Job execution must use allowlisted internal functions, not arbitrary command execution.
- All manual changes to manager / CIK status must be auditable.

## 17. UX Copy Principles

Use precise language:

- Say "13F filings are delayed snapshots."
- Say "Partial data is expected before the filing deadline."
- Say "Tracked managers" instead of implying all SEC filers.
- Say "Linked to stocks" instead of "matched perfectly."
- Say "Unavailable" with a reason when a metric has no valid denominator; do not show misleading `0%` values.
- Do not say "smart money buys" or "buy signal."

Recommended current-quarter copy:

> 2026-Q1 is still inside the SEC filing window. Some managers have filed and others may file by approximately 2026-05-15. This quarter should be treated as partial until the deadline passes and quality checks complete.

Filing deadlines should be calculated rather than hard-coded. The UI may show approximate dates unless the system has an official SEC deadline calendar. The default calculation should follow the 13F convention of approximately 45 days after calendar quarter end, adjusted only when the application explicitly supports a more precise deadline calendar.

## 18. MVP Delivery Plan

### MVP 1A: Status / Readiness Read Model

- Derive `quarter_phase` and `quarter_health`
- Derive setup blockers and admin tasks
- Produce readiness summary payload for consumer features
- Distinguish zero from unavailable for quality metrics

### MVP 1B: Read-Only Operations Dashboard

- Overview health banner
- Setup checklist
- Quarter table
- Admin task queue
- Current quarter partial-state logic
- Job history read model if available, otherwise latest derived status

### MVP 2: Job Run Persistence And Manual Controls

- Persist job run records with `dedupe_key` and `lock_key`
- Trigger bootstrap whitelist
- Trigger match CIK
- Trigger latest-quarter refresh
- Trigger backfill
- Trigger enrichment
- Trigger quality check
- Prevent duplicate active jobs with the same lock key

### MVP 3: Manager / CIK Review

- Candidate review table
- Confirm / reject actions
- Retry search with edited name
- Audit status changes and review notes

### MVP 4: Oracle's Lens Readiness Integration

- Stale quarter alerts
- Failed job alerts
- Low coverage alerts
- Oracle's Lens data readiness integration

### MVP 5: Alerts

- Email or Slack alerts, if needed
- In-app admin alerts
- Escalation task creation for engineering-only failures

## 19. Acceptance Criteria For Implementation

- Admin can tell within 10 seconds whether 13F ingestion is ready.
- Admin can see why enabled scheduler has not produced data.
- Admin can see each quarter's status and whether partial data is expected.
- Admin can manually trigger the main ingestion jobs from a safe UI.
- Admin can review and confirm manager / CIK candidates without direct DB access.
- Admin can inspect failed filings and retry them.
- User-facing 13F features can distinguish no data, setup required, partial quarter, and ready states.

### 19.1 Testable Acceptance Criteria

- When `institution_managers=0` and `EDGAR_SCHEDULER_ENABLED=true`, the status API returns `setup_required` and the top task is `NO_CONFIRMED_MANAGER_CIK_WHITELIST`.
- When the current date is before the filing deadline and partial filings exist with no job failures, the quarter response includes `quarter_phase=filing_window_open` and does not return `failed` health.
- When a candidate CIK has `match_status='candidate'`, ingestion must not treat it as confirmed.
- When a job is running for the same `job_type + quarter`, a duplicate job request returns a conflict response instead of starting another job.
- When no holdings exist, `linked_holding_ratio` is `null` with `unavailable_reason=NO_HOLDINGS_PARSED`, not `0%`.
- When a quarter ingest partially succeeds, job status is `partial_success` and `summary_json` includes failed accession numbers or managers.
- When a CIK candidate is confirmed or rejected, the audit trail records reviewer, timestamp, source, evidence URL, and review note.

## 20. Open Questions

- What minimum confirmed manager count should qualify the system as "ready" for initial production use?
- Should we track all Dataroma managers or allow a curated subset for ValuePilot?
- What linked holdings ratio should be considered acceptable for Oracle's Lens?
- Should manual backfill be available for arbitrary historical depth or capped to protect EDGAR rate limits?
- Do we want email / Slack alerts for failed scheduled jobs, or only in-app admin alerts for V1?
- What exact `lock_key` should be used for each job type?
- Which readiness payload fields should be shared with non-admin consumer APIs versus kept admin-only?
- Should `partial_success` jobs automatically create retry tasks for failed filings?
- What official or internal calendar, if any, should be used for precise 13F filing deadlines?
