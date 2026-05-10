# 13F-1C1-03 Alert Rules and Data Health Summary

## Goal / Acceptance Criteria

- Implement MVP 1 13F alert evaluation rules from PRD §15.1-§15.3.
- Generate a daily data health summary payload with readiness, coverage, NT, combination/confidential, failed filing, amendment, and CUSIP mapping metrics.
- Schedule the daily health summary for 08:00 ET and send through the existing alert/Discord abstraction when configured.
- Keep alert logic deterministic and unit-testable without real Discord or network calls.

## Scope In

- Daily sync consecutive failed business day alert excluding active no-index dates.
- Expected filer coverage alert after official deadline when coverage is below 70%.
- CUSIP mapping ratio P1/P2 alert for closed windows.
- Amendment pending/failed age alerts.
- `parse_status=needs_review` age alert.
- Running job timeout/expired lease alert.
- SEC 429/403 alert hook using EDGAR rate-limit status.
- Readiness downgrade severity helper.
- Daily health summary builder and scheduler wrapper.

## Scope Out

- Email delivery unless an existing config path already supports it.
- UI/frontend.
- New persistence tables for alert state/history.
- MVP 2 change analysis.
- PRD or schema changes.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §15.1 alert levels.
- `docs/prd/13f_automation_and_resilience_prd.md` §15.2 alert trigger conditions.
- `docs/prd/13f_automation_and_resilience_prd.md` §15.3 daily health summary.
- `docs/prd/13f_automation_and_resilience_prd.md` §18 acceptance criteria around readiness, NT, caveats, and unavailable vs zero.

## Files Likely To Change

- `backend/app/services/thirteenf_health.py` (new)
- `backend/app/services/scheduler.py`
- `backend/tests/unit/test_13f_health_summary.py` (new)
- `backend/tests/unit/test_scheduler_alignment.py`
- `docs/tasks/2026-05-10_13f-alert-health-summary.md`

## Tests First

- Each MVP 1 alert condition emits the expected severity and structured context.
- No-index dates are excluded from consecutive daily sync failure.
- Readiness downgrade helper returns P2 for ready -> warning and P1 for closed-window unavailable.
- Daily health summary service emits through the alert abstraction without real Discord.
- Scheduler registers an 08:00 ET daily health summary job.

## Docker Verification Commands

- `docker compose exec api pytest -q tests/unit/test_13f_health_summary.py`
- `docker compose exec api pytest -q tests/unit/test_scheduler_alignment.py tests/unit/test_13f_alerts.py`
- `docker compose exec api pytest -q tests/unit`

## Review Gate

Tech Lead must review noisy-alert risk and exclusion rules.

## Progress Notes

- 2026-05-10: Started after G4 response-shape gate closed for 13F-1C1-02. Git worktree was clean. Next plan task confirmed as `13F-1C1-03`; dependencies `13F-1A-05` and `13F-1C1-01` are already complete.
- 2026-05-10: Wrote red tests first for daily sync consecutive failure, coverage/CUSIP thresholds, ingest timeout retry exhaustion, stale amendments, stale needs_review, running job timeout/lease, SEC block hook, readiness downgrade helper, health summary delivery, and 08:00 ET scheduler registration.
- 2026-05-10: Added `thirteenf_health` service with deterministic alert evaluators and daily health summary builder. Registered `thirteenf_daily_health_summary` in the scheduler using `America/New_York` 08:00.
- 2026-05-10: Verification:
  - `docker compose exec api pytest -q tests/unit/test_13f_health_summary.py` -> 8 passed.
  - `docker compose exec api pytest -q tests/unit/test_13f_health_summary.py tests/unit/test_scheduler_alignment.py tests/unit/test_13f_alerts.py` -> 20 passed.
  - `docker compose exec api pytest -q tests/unit` -> 483 passed, 1 existing SQLAlchemy transaction warning.

## Contract Checklist

- Alert severities follow PRD §15.1/§15.2 thresholds for implemented MVP 1 conditions.
- Daily sync consecutive failure excludes weekends and active `no_index_expected_dates`.
- Coverage and CUSIP mapping alerts require a filing window closed by at least 3 days.
- Ingest accession/filing timeout retry exhaustion triggers after 3 failed timeout jobs for the same dedupe key.
- SEC 403/429 alert hook consumes the existing EDGAR client health payload; no network call is made by evaluators.
- Daily health summary is delivered through the existing `emit_alert` Discord abstraction and is testable with `InMemoryAlertTransport`.
- Scheduler invokes the daily health summary at 08:00 ET; no UI, schema, PRD, or MVP 2 change-analysis implementation was added.
