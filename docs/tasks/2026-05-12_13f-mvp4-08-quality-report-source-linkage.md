# 13F MVP4-08: Quality Report Source Linkage (Dry-Run vs Real)

## Status

Authorized to start. Backlog ticket filed at MVP4 decision gate
(D6 table row: "Dry-run vs real quality_report disambiguation").
Independent of scoring work; parallel-safe with the rest of MVP4.

## Goal / Acceptance Criteria

Make every `quality_reports_13f` row carry an explicit dry-run
flag so dashboards aggregating quality runs can filter out
dry-run noise — today the historical-backfill writer emits a row
with `status='passed'` or `status='warning'` whether or not the
batch actually ingested data, and the only signal that a report
is a dry-run is a substring in the free-text `summary` column.

Acceptance criteria:

- `quality_reports_13f` gains an `is_dry_run BOOLEAN NOT NULL
  DEFAULT FALSE` column via Alembic migration. The default keeps
  every existing row interpreted as "real" without a backfill
  pass.
- `QualityReport13F` SQLAlchemy model adds the field with a sane
  default; existing constructors (`edgar_quality`,
  `thirteenf_corporate_action_mapping`) leave it false implicitly.
- `thirteenf_historical_backfill._execute_quarter` accepts the
  current `dry_run` value and threads it to
  `QualityReport13F(is_dry_run=dry_run, ...)`.
- The same writer also stamps `source_job_id=job.id` on the new
  row (the column has existed since the table was created but
  the backfill path never set it — that's the "source linkage"
  half of the backlog title).
- `build_quality_reports` (the admin dashboard recent-reports
  list) excludes dry-run rows by default and accepts an optional
  `include_dry_run` flag callers can pass to opt in. The admin
  endpoint surfaces the same opt-in via a query param.
- `_latest_quality_report` (per-quarter detail / readiness)
  excludes dry-run rows unconditionally — a passing dry-run must
  never mask whether the real production parse for that quarter
  is healthy.
- No `summary`-string parsing introduced. The flag is the
  authoritative signal.

## Scope In

- New Alembic migration adding `is_dry_run` column.
- `QualityReport13F` ORM column.
- `_execute_quarter` writer changes (set `is_dry_run`,
  `source_job_id`).
- `thirteenf_admin_dashboard.build_quality_reports` /
  `_latest_quality_report` filter changes.
- Admin endpoint query param wiring for `include_dry_run` (the
  detail endpoint stays implicit-exclude; only the list one
  exposes the opt-in).
- Backend tests pinning the new behavior end-to-end.

## Scope Out

- No `source_kind` discriminator column. Backlog entry covers
  dry-run only; broader kind taxonomy can land separately if a
  consumer needs it.
- No frontend admin UI surface for dry-run filter UI — the API
  exposes it; the existing recent-reports table already filters
  to "real" by default, which matches user expectations.
- No retrofit / backfill of the `is_dry_run` value on historical
  rows. Existing rows are interpreted as "real"; the cost of
  walking the summary text is not worth the precision gain on
  pre-MVP4-08 data.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D6 backlog
  table: "Dry-run vs real quality_report disambiguation."
- `docs/tasks/2026-05-11_13f-mvp3-07-historical-backfill.md` —
  introduced the dry-run path that creates this report.
- `CLAUDE.md` schema-change rule: schema constraints get fixed
  at the schema level, not via free-text-summary parsing.

## Files Expected To Change

- `backend/alembic/versions/<ts>-add_is_dry_run_to_quality_reports_13f.py` (new)
- `backend/app/models/institutions.py`
- `backend/app/services/thirteenf_historical_backfill.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_mvp4_quality_report_source_linkage.py` (new)
- This task file.

## Test Plan

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_quality_report_source_linkage.py`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-12: Started after MVP4-07b shipped. PO picked
  is_dry_run-only scope to keep the change minimal.
- 2026-05-12: Implementation:
  - New Alembic migration `20260512120000` adds
    `is_dry_run BOOLEAN NOT NULL DEFAULT FALSE` to
    `quality_reports_13f`. Existing rows default to false (real).
  - ORM column added to `QualityReport13F` with matching default.
  - `thirteenf_historical_backfill._execute_quarter` now takes
    `job_run_id` and stamps both `is_dry_run=dry_run` and
    `source_job_id=job_run_id` on the report it writes. The
    caller already had `job_run_id` in scope; thread-through
    only.
  - `build_quality_reports(include_dry_run=False)` filters
    dry-run rows out of the admin recent-reports list; the
    admin endpoint `GET /api/v1/admin/13f/quality` accepts
    `?include_dry_run=true` for the opt-in.
  - `_latest_quality_report` unconditionally excludes dry-run
    rows so a passing dry-run can never mask a missing or
    failed production parse for the same quarter.
  - No frontend admin UI change required — the existing
    recent-reports table already aligns with the new
    "real only by default" behavior.

## Verification Results

- `docker compose exec api alembic upgrade head` -> 20260511140000 -> 20260512120000, mvp4-08 quality_report is_dry_run.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_quality_report_source_linkage.py` -> 6 passed.
- `docker compose exec api pytest -q` -> 754 passed (was 748; +6 new MVP4-08 tests; no regressions).
