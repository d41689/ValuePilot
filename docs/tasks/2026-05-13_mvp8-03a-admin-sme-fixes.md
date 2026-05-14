# MVP8-03A: Admin SME Fixes (4 items)

## Status

**Authorized to open 2026-05-13** per Pre-MVP8-03 D5 (gated on MVP8-03B
closing review, completed 2026-05-13 at commit `6a1d003`).

Child ticket of the MVP8-03 SME flag cluster, executing the
admin-surface 4 items. MVP8-03B (watchlist / scoring) is closed.

## Goal

Ship four SME-flagged improvements to the admin-only surfaces
(manager classification editor, Historical Backfill card, Batch
Reparse card, Quality Reports drawer). Strict scope discipline —
only the 4 items below. No DrawerShell move, no a11y suite, no
accession URL backlog.

## D1 — A1: manager_type editor — note required + evidence_json threading

**Root cause**: `ManagerTypeUpdateRequest` at
`backend/app/api/v1/endpoints/thirteenf_admin.py:76` has
`note: str | None = None` (optional) and no `evidence_json` field.
`InstitutionManagerTypeReviewEvent` has both `note` and
`evidence_json` columns (model at `backend/app/models/institutions.py:185`),
but the API surface and `update_manager_type` service never thread
`evidence_json` through. The dialog label reads "(optional)" which
gives no signal that classification changes need documented rationale.

**Fix contract**:

- `ManagerTypeUpdateRequest` gains a Pydantic `@model_validator`
  that raises `ValueError` when `new_manager_type != "unknown"` and
  `note` is empty or whitespace. The 400 message: `"note is required
  when classifying to a non-unknown manager_type"`.
- `ManagerTypeUpdateRequest` adds `evidence_json: dict | None = None`.
- `update_manager_type` service adds `evidence_json: dict | None = None`
  kwarg and passes it into `InstitutionManagerTypeReviewEvent(evidence_json=evidence_json)`.
- `patch_manager_type` endpoint passes `evidence_json=payload.evidence_json`
  to the service.
- `ManagerTypeEditorDialog.tsx`: (a) note label changes from
  "(optional)" to "(required when classifying)" with a `*` indicator
  when `draft !== 'unknown'`; (b) Save button disabled when
  `draft !== 'unknown' && !note.trim()`; (c) new optional `Evidence URL`
  input below the note field; the caller receives `evidenceUrl` in
  the `onSave` payload and converts it to `evidence_json: { url: evidenceUrl }`.
- `managers/page.tsx` mutation: include `evidence_json: payload.evidenceUrl
  ? { url: payload.evidenceUrl } : null` in the `PATCH` body.

**Scope**:

- `backend/app/api/v1/endpoints/thirteenf_admin.py` —
  `ManagerTypeUpdateRequest` validator + `evidence_json` field +
  `patch_manager_type` passes it through.
- `backend/app/services/manager_type_review.py` —
  `update_manager_type` `evidence_json` kwarg + model assignment.
- `frontend/components/admin13f/ManagerTypeEditorDialog.tsx` —
  note required signal + Save guard + evidence URL input.
- `frontend/app/(dashboard)/admin/13f/managers/page.tsx` —
  mutation payload includes `evidence_json`.
- `backend/tests/unit/` — one test confirming 400 when note is
  missing for a non-unknown transition; one test confirming no-op
  when note is provided.

## D2 — A2: Historical Backfill Kahn Brothers True-Positive caveat

**Root cause**: `preview_historical_backfill` in
`backend/app/services/thirteenf_historical_backfill.py` returns a
generic `value_unit_risk_warning` flag but has no per-filer caveat
for Kahn Brothers (CIK `0001039565`). During backfill, Kahn
Brothers reconciliation warnings appear in job output and are
routinely mistaken for parse errors — they are True Positives
because this filer reports values in dollars, not thousands.

**Fix contract**:

- `preview_historical_backfill` checks `any(m.cik == "0001039565"
  for m in managers)` and adds `"kahn_brothers_in_scope": bool` to
  the preview dict.
- Frontend `jobs/page.tsx` Historical Backfill section renders an
  amber banner when `hbPreview['kahn_brothers_in_scope']` is truthy:
  `"Kahn Brothers (CIK 0001039565) is in scope. This filer reports
  values in dollars, not thousands — reconciliation warnings during
  ingestion are True Positives, not parse errors."`

**Scope**:

- `backend/app/services/thirteenf_historical_backfill.py` —
  `preview_historical_backfill` adds `kahn_brothers_in_scope` key.
- `frontend/app/(dashboard)/admin/13f/jobs/page.tsx` — amber banner
  in the Historical Backfill preview section.
- No new tests required beyond the existing backfill preview tests
  (the flag is a trivial boolean addition; the amber banner is
  frontend-only). One unit test asserting `kahn_brothers_in_scope=True`
  when Kahn is in the managers list.

## D3 — A3: Batch Reparse `missing_raw_infotable_count > 0` → amber banner

**Root cause**: The batch reparse preview on `/admin/13f/jobs` shows
`missing_raw_infotable_count` as a neutral metric in the two-cell
preview grid. When this count is > 0, there is no visual distinction
— operators don't know that missing raw infotable XML means those
filings cannot produce holdings even after reparse.

**Fix contract**:

- Frontend only. In the `brPreview` section of the Batch Reparse
  card in `jobs/page.tsx`, when `missing_raw_infotable_count > 0`,
  render an amber banner ABOVE the Enqueue button:
  `"{N} filing(s) are missing raw infotable XML. Reparse cannot
  recover discarded raw XML — these filings will produce empty
  holdings unless re-fetched from EDGAR first."`
- The metric grid cell for `missing_raw_infotable_count` stays
  as-is for at-a-glance numeric reference.

**Scope**:

- `frontend/app/(dashboard)/admin/13f/jobs/page.tsx` — amber banner
  in batch reparse preview section (frontend-only change).

## D4 — A4: Quality Reports V2 per-finding drilldown

**Root cause**: The Quarter Detail drawer in `/admin/13f/readiness`
renders `selectedQuarterDetail.quality_report.issues` as a raw JSON
dump via `formatJson()` in a monospace code block (lines 1167–1168).
This is hard to scan. The issues array already has structured shape
`{check, severity, accession_no, detail}` (set by the quality-check
job at `thirteenf_admin_dashboard.py:2841`). A per-finding card
list makes the signal immediately legible.

**Fix contract**:

- Replace the `{formatJson(selectedQuarterDetail.quality_report.issues)}`
  code block with a structured per-finding list:
  - Each finding renders as a compact card: severity badge
    (`error` → danger, `warning` → warning, `info` → secondary) +
    monospace `check` code + optional `accession_no` + `detail` text.
  - Empty `issues` array → "No issues recorded." muted text.
  - Preserve the existing header row (status + checked_at).
- The `issues` array comes from `_quality_report_payload`
  (`issues: report.issues_json or []`) — no backend changes needed.

**Scope**:

- `frontend/app/(dashboard)/admin/13f/readiness/page.tsx` —
  replace JSON dump with structured per-finding list in the Quarter
  Detail drawer's Quality Report section.

## Scope Out (this ticket)

- DrawerShell move, drawer a11y, manager-name truncate, accession URL
  threading — separate Track-E tickets.
- MVP8-02 base divergence — observation-window-gated.
- Any watchlist-surface changes — MVP8-03B closed.

## Verification Plan

- `docker compose exec api pytest -q` — full suite green.
- `docker compose exec web npm run lint` — clean.
- `docker compose exec web npm run build` — clean.
- Manual probe:
  1. `/admin/13f/managers` → classify a manager to
     `long_term_fundamental` WITHOUT a note → Save button is
     disabled / API returns 400.
  2. Classify WITH a note and optional evidence URL → audit trail
     shows note + evidence_json.
  3. `/admin/13f/jobs` → Historical Backfill preview with a quarter
     range that includes Kahn Brothers (CIK `0001039565`) → amber
     banner appears.
  4. Batch Reparse preview for a quarter with
     `missing_raw_infotable_count > 0` → amber banner appears.
  5. `/admin/13f/readiness` → open a quarter with a quality report
     → per-finding cards visible instead of JSON dump.

## Sign-Off Trail

- [x] A1 note required + evidence_json backend + frontend shipped.
- [x] A2 Kahn Brothers caveat banner shipped.
- [x] A3 missing_raw_infotable_count amber banner shipped.
- [x] A4 Quality Reports V2 per-finding drilldown shipped.
- [x] pytest -q → 818 passed; lint clean; build clean (commit `4a159a5`).
- [ ] Four-role review pass.
- [ ] **MVP8-03A closed.**

## Files Expected To Change

- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/app/services/manager_type_review.py`
- `backend/app/services/thirteenf_historical_backfill.py`
- `backend/tests/unit/` (new A1 + A2 unit tests)
- `frontend/components/admin13f/ManagerTypeEditorDialog.tsx`
- `frontend/app/(dashboard)/admin/13f/managers/page.tsx`
- `frontend/app/(dashboard)/admin/13f/jobs/page.tsx`
- `frontend/app/(dashboard)/admin/13f/readiness/page.tsx`
- `docs/tasks/2026-05-13_mvp8-03a-admin-sme-fixes.md` (this file)
