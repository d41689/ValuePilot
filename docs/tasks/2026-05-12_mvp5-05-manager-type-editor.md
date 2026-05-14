# 13F MVP5-05: Manager Type Editor

## Status

Authorized to start. Fifth ticket of MVP 5
(`docs/tasks/2026-05-12_13f-mvp5-execution-plan.md`).

Independent of MVP5-03 Phase 3 / 4. Closes the MVP4-07b admin
priority Card loop: admin sees which managers to classify; this
ticket gives them a one-click path to classify each.

## Goal / Acceptance Criteria

Lightweight inline classification editor on the existing
`/admin/13f` managers section + deep links from the MVP4-07b
Unknown Manager Priority Card.

### Surface choice

**Inline dialog on the existing managers section, not a separate
`/admin/managers/{id}` page.** Rationale:

- The existing admin/13f page is the operator's working canvas;
  context-switching to a separate page disrupts the priority
  queue workflow.
- An anchor link (`#manager-row-{id}`) is zero-cost to add and
  needs no new route plumbing. FE Review #8 #6 prefers exactly
  this pattern.
- A dialog keeps the row layout untouched and matches the
  existing shadcn dialog usage (CIK review uses `ManagerCikDialogs`).
- Per the FE rejection R6, no stub routes; the editor must
  exist before any deep link points at it.

### Acceptance criteria

- New audit table
  `institution_manager_type_review_events` (Alembic migration
  + ORM model) with: `id`, `manager_id` FK to
  `institution_managers`, `old_manager_type`,
  `new_manager_type`, `reviewed_by_user_id` FK to `users`
  (nullable for null/service writes), `note` (nullable text),
  `evidence_json` (nullable JSONB), `created_at`. Indexed on
  `manager_id` and `created_at`.
- New ORM relationship
  `InstitutionManager.manager_type_review_events` ordered by
  `created_at` desc, mirrors the existing
  `cik_review_events` relationship.
- New service
  `update_manager_type(session, manager_id, *, new_manager_type,
  reviewer_user_id, note)` that:
  - Validates `new_manager_type` against the canonical 8-value
    `MANAGER_TYPES` set (raises a typed
    `ManagerTypeUpdateError` if not).
  - Reads current `manager.manager_type`; if unchanged, returns
    a no-op result with `changed=False` and writes no audit
    row (the editor's save button is a no-op for already-correct
    values).
  - Writes the new value to `InstitutionManager.manager_type`.
  - Inserts a new `InstitutionManagerTypeReviewEvent` row with
    `old_manager_type` (pre-change value), `new_manager_type`,
    `reviewed_by_user_id`, `note`, `created_at=now()`.
  - Returns a dict with `manager_id`, `old_manager_type`,
    `new_manager_type`, `changed`, `audit_event_id`.
- New admin endpoint
  `PATCH /api/v1/admin/13f/managers/{manager_id}/manager-type`
  with body `{new_manager_type: str, note?: str}`. Admin-gated
  via existing `AdminUser` dep. Returns the service result.
  404 when manager not found; 400 when new_manager_type invalid.
- New admin endpoint
  `GET /api/v1/admin/13f/managers/{manager_id}/manager-type-events`
  returning the last N (default 10) audit events for the
  manager.
- Frontend admin/13f managers section:
  - Each `<TableRow>` gets `id="manager-row-{manager.id}"`
    so anchors land precisely.
  - New "Manager Type" column rendering the current value as a
    badge and an "Edit" Button next to it. The button opens a
    new `<Dialog>` containing a `<Select>` of the canonical 8
    values (current value pre-selected), an optional note
    textarea, and a Save action.
  - On save, the frontend calls the PATCH endpoint; on
    success, invalidates both the `managers` query and the
    `admin-13f-oracles-lens-unknown-manager-priority` query
    so the Unknown Manager Priority Card refreshes.
- Frontend MVP4-07b Unknown Manager Priority Card:
  - Each row's manager name becomes a `<Link>` to
    `/admin/13f#manager-row-{manager_id}`. Clicking scrolls
    the page to the corresponding manager row in the existing
    managers section.
- Backend tests pin: admin-only gating (non-admin → 401/403);
  valid manager_type update writes both the column and the
  audit event; invalid manager_type returns 400; no-op when
  unchanged writes no audit event; missing manager returns
  404.

## Scope In

- `backend/alembic/versions/<ts>-mvp5_05_manager_type_review_events.py`
  (new migration)
- `backend/app/models/institutions.py` (new
  `InstitutionManagerTypeReviewEvent` ORM model + relationship)
- `backend/app/services/manager_type_review.py` (new service
  module) — or extend `thirteenf_admin_dashboard.py` if
  smaller fits there.
- `backend/app/api/v1/endpoints/thirteenf_admin.py` (new
  routes)
- `backend/tests/unit/test_13f_mvp5_05_manager_type_editor.py`
  (new)
- `frontend/app/(dashboard)/admin/13f/page.tsx`
  - Manager Type column + edit Dialog
  - `id` anchor on every TableRow in managers section
  - Priority Card row name → `<Link>` deep link
- This task file.

## Scope Out

- Bulk classification UI (one-at-a-time per V1).
- Behavior-derived `manager_type` admin override workflow.
- Manager detail page at `/admin/managers/{id}` — anchor link
  is the V1 deep-link mechanism. A separate page is a V2
  consideration.
- Wider admin manager management redesign.
- Frontend lib tests for the new editor — the editor lives in
  page.tsx and is exercised by manual smoke; the backend
  endpoint is fully tested.

## PRD / Decision References

- `docs/tasks/2026-05-12_13f-mvp5-execution-plan.md` — MVP5-05
  scope.
- `docs/13f/mvp4-reviews.md` — FE #8 #6 (deep-link via anchor
  is the right V1), FE rejection R6 (no stub routes).
- `docs/tasks/2026-05-11_13f-mvp4-11-manager-type-taxonomy.md`
  — canonical 8-value MANAGER_TYPES set.

## Files Expected To Change

- `backend/alembic/versions/20260512130000-mvp5_05_manager_type_review_events.py`
  (new)
- `backend/app/models/institutions.py`
- `backend/app/services/manager_type_review.py` (new)
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_mvp5_05_manager_type_editor.py`
  (new)
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- This task file.

## Test Plan

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp5_05_manager_type_editor.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`

## Progress Notes

- 2026-05-12: Task spec filed. Surveyed the existing managers
  section + CIK review event pattern; choosing inline dialog +
  anchor link over a separate detail page per FE Review
  guidance.
- 2026-05-12: Implementation:
  - New Alembic migration `20260512130000` creates
    `institution_manager_type_review_events` with columns
    `id`, `manager_id` FK, `old_manager_type`,
    `new_manager_type`, `reviewed_by_user_id` FK,
    `note`, `evidence_json`, `created_at`. Indexed on
    `manager_id` and `created_at`.
  - ORM model `InstitutionManagerTypeReviewEvent` + a
    `manager_type_review_events` relationship on
    `InstitutionManager` (newest-first ordering, matches the
    existing `cik_review_events` pattern).
  - New service module `app/services/manager_type_review.py`:
    `update_manager_type(session, manager_id, *,
    new_manager_type, reviewer_user_id, note)` validates the
    new type against the canonical 8-value `MANAGER_TYPES`
    set, no-ops when unchanged (no audit row written),
    otherwise writes the column + the audit row in one
    transaction (`session.commit()` after `add(event)`). A
    typed `ManagerTypeUpdateError` distinguishes "manager not
    found" from "invalid type" so the endpoint can translate
    to 404 vs 400. `list_manager_type_review_events` reads
    the audit log with a deterministic
    `(created_at DESC, id DESC)` ordering so events from the
    same transaction return in stable order.
  - New admin routes in `thirteenf_admin.py`:
    - `PATCH /api/v1/admin/13f/managers/{manager_id}/manager-type`
      with `ManagerTypeUpdateRequest` body
      (`new_manager_type` + optional `note`). 200 with the
      service result, 400 on invalid type, 404 on missing
      manager.
    - `GET /api/v1/admin/13f/managers/{manager_id}/manager-type-events`
      returning the last 10 audit events (configurable up to
      100).
  - Frontend `admin/13f/page.tsx`:
    - New `MANAGER_TYPE_OPTIONS` constant mirroring the
      canonical 8-value `MANAGER_TYPES` set, ordered by
      `MANAGER_SIGNAL_WEIGHTS` descending so the highest-
      signal types appear first.
    - `managerTypeEditor` state + `managerTypeMutation`
      (React Query) wired to the new PATCH endpoint;
      `onSuccess` invalidates both `admin-13f-managers` and
      `admin-13f-oracles-lens-unknown-manager-priority`
      queries so the priority Card updates immediately.
    - Managers section table:
      - Each `<TableRow>` carries
        `id="manager-row-{manager.id}"` + `scroll-mt-6` so
        anchor links land precisely.
      - New "Manager Type" column shows the current value as
        a Badge (warning variant when `unknown`, secondary
        otherwise) + an inline "Edit" button.
    - Single `<Dialog>` instance lifted to the component
      scope renders the canonical-taxonomy `<Select>` +
      optional note `<Textarea>` + Save action. Cancel /
      backdrop-close / save-success all clear the editor
      state.
    - MVP4-07b Unknown Manager Priority Card row name now
      wraps in an `<a href="#manager-row-{id}">` so the admin
      can click straight from the queue into the inline
      editor.

  Tests:
  - New `test_13f_mvp5_05_manager_type_editor.py` with 9
    cases:
    - 4 service-layer tests: write column + audit, no-op
      when unchanged, invalid taxonomy raises typed error,
      404 when manager missing.
    - 5 endpoint integration tests: admin-only gating,
      update + payload shape, 400 on invalid type, 404 on
      missing manager, history endpoint returns newest-first
      audit events.
  - History test exposed a tied `created_at` bug (events in
    the same transaction get identical `func.now()`
    timestamps); fixed by adding `id DESC` as the
    secondary sort key in `list_manager_type_review_events`.

## Verification Results

- `docker compose exec api alembic upgrade head` -> at head
  `20260512130000`.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp5_05_manager_type_editor.py` -> 9 passed.
- `docker compose exec api pytest -q` -> **781 passed** (was
  772 after MVP5-03; +9 new MVP5-05 tests; no regressions).
- `docker compose exec web npm run lint` -> No ESLint warnings or errors.
- `docker compose exec web npm run build` -> compiled successfully.
- `docker compose exec web node --test lib/oraclesLens.test.js` -> 17 passed (regression check; MVP5-04 normalizer untouched).
