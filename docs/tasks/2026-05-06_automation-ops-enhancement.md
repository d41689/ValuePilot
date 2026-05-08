# 2026-05-06 Automation Operations Enhancement

## Goal
Enhance the 13F data operations with automated alerts and improved data linking to reduce manual oversight and ensure data quality.

## Acceptance Criteria
- [ ] Implement a Slack notification service (or a mock for now) to alert admins of failed or partially successful 13F jobs.
- [ ] Integrate alerts into the `ThirteenFJobWorker` execution loop.
- [ ] Add a "Ready" threshold check that triggers a notification if a quarter's linked holdings ratio is below 80% after a pipeline run.
- [ ] Support "Escalation" tasks in the dashboard for engineering-level failures (e.g., persistent parser errors).

## Scope
- `backend/app/services/notifications.py`: New service for Slack/Email alerts.
- `backend/app/services/thirteenf_job_worker.py`: Trigger notifications on job completion.
- `backend/app/services/thirteenf_admin_dashboard.py`: Refine task/readiness logic for automated escalations.
- `backend/app/core/config.py`: Add notification settings (e.g., Slack webhook URL).

## Test Plan
- Unit tests for the notification service.
- Integration tests simulating a failed job and verifying a notification is triggered.
- Verify "Escalation" tasks appear in the Admin Dashboard via API tests.

## Files to change
- `backend/app/core/config.py`
- `backend/app/services/thirteenf_job_worker.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/services/notifications.py` (New)
