# MVP8-03A Four-Role Review Prompts

Four reviewer prompts for the MVP8-03A (admin SME fixes) closing
review. Each is self-contained — drop the prompt into a fresh chat
or hand it to a human reviewer without needing the rest of this
repository's history.

**Branch**: `docs/13f-automation-prd`
**Implementation commit**: `4a159a5` ("MVP8-03A: four admin SME fixes
(note required, Kahn caveat, reparse banner, QR drilldown)")
**Spec**: `docs/tasks/2026-05-13_mvp8-03a-admin-sme-fixes.md`
**Parent cluster**:
`docs/tasks/2026-05-13_pre-mvp8-03-sme-flag-cluster-decision-gate.md`

Roles (priority order):

1. **Financial Data Product Reviewer (13F Domain SME) — HIGH.**
   Validates that the four admin-surface items match the product
   intent for admin + operator workflows.
2. **Staff Engineer — MEDIUM.** Cross-cutting contract / scope /
   API design review.
3. **Backend Reviewer — MEDIUM.** Pydantic validator behavior,
   service threading, test coverage.
4. **Frontend Reviewer — MEDIUM.** TypeScript correctness, dialog
   state management, UX hierarchy, accessibility.

---

## 1. Financial Data Product Reviewer (13F Domain SME) Prompt

You are the 13F domain SME conducting the MVP8-03A closing review
for ValuePilot's 13F automation track. MVP8-03A implements four
admin-surface SME-flagged improvements deferred from earlier review
cycles. Implementation commit is `4a159a5` on branch
`docs/13f-automation-prd`.

**Read these files in order:**

1. `docs/tasks/2026-05-13_mvp8-03a-admin-sme-fixes.md` — full spec
   for the four items (A1–A4) including root causes and fix
   contracts.
2. `backend/app/api/v1/endpoints/thirteenf_admin.py` lines 76–90
   (`ManagerTypeUpdateRequest` with the new `model_validator` +
   `evidence_json` field).
3. `frontend/components/admin13f/ManagerTypeEditorDialog.tsx` —
   the updated dialog (note required indicator, Save guard,
   Evidence URL input).
4. `backend/app/services/thirteenf_historical_backfill.py` lines
   100–125 (`preview_historical_backfill` with the new
   `kahn_brothers_in_scope` flag).
5. `frontend/app/(dashboard)/admin/13f/jobs/page.tsx` lines 718–770
   (Historical Backfill preview — amber banner for Kahn Brothers)
   and lines 852–880 (Batch Reparse preview — amber banner for
   `missing_raw_infotable_count > 0`).
6. `frontend/app/(dashboard)/admin/13f/readiness/page.tsx` lines
   1155–1210 (Quarter Detail drawer Quality Report section — new
   per-finding cards replacing the raw JSON dump).

**Four key product questions you must answer:**

### A1 — manager_type note required + evidence_json

The dialog previously labelled note as "(optional)". A1 makes note
**required** whenever the admin classifies to any non-unknown type.
Reclassifying to `unknown` (undoing a classification) still allows
an empty note.

- Is "required when classifying to a non-unknown type, optional
  when reverting to unknown" the right UX gate? Or should reverting
  to `unknown` also require a rationale (e.g. "we couldn't confirm
  this manager's style")?
- The Evidence URL field is purely optional — there is no validation
  that the URL format is correct (browser-native `type="url"`
  attribute hints but doesn't enforce on click-based submit). Is
  URL format validation needed, or is a freeform URL good enough
  for an internal admin tool?
- `evidence_json` is stored as `{ "url": "..." }` — a flat
  one-field dict. Is that schema sufficient for the audit trail, or
  do you anticipate needing additional fields (e.g. `title`,
  `source`, `fetched_at`) that would require a richer structure
  from the start?
- The 400/422 error message returned when note is missing is:
  `"note is required when classifying to a non-unknown manager_type"`.
  Is that wording clear enough for an operator who sees it in an
  API error toast?

### A2 — Historical Backfill Kahn Brothers caveat

When a backfill preview includes Kahn Brothers (CIK `0001039565`),
an amber banner appears:

> "Kahn Brothers (CIK 0001039565) is in scope. This filer reports
> values in dollars, not thousands — reconciliation warnings during
> ingestion are True Positives, not parse errors."

- Is the banner copy accurate and actionable? Does it give an
  operator enough information to handle the reconciliation warnings
  correctly, or does it need to say more (e.g. what to do when
  warnings appear, whether to set `value_unit_override`)?
- The banner fires whenever Kahn Brothers is in the full active
  manager list (or in the scoped `manager_ids` list). For a
  full-universe backfill that always includes Kahn Brothers, the
  banner will always appear. Is that the right behavior, or should
  it only fire for date ranges where the Kahn Brothers filings are
  known to have the dollar-unit issue (pre-some-cutoff)?

### A3 — Batch Reparse missing_raw_infotable_count amber banner

When the batch reparse preview shows `missing_raw_infotable_count > 0`,
an amber banner appears above the Enqueue button:

> "{N} filing(s) are missing raw infotable XML. Reparse cannot
> recover discarded raw XML — these filings will produce empty
> holdings unless re-fetched from EDGAR first."

- Is the copy accurate? Is "re-fetched from EDGAR first" a
  real path an operator can take, and is it accessible from another
  admin surface? If the re-fetch path is not yet built, should the
  copy say something like "re-fetching from EDGAR is required but
  not yet supported via this UI"?
- The metric grid cell for `missing_raw_infotable_count` stays
  as-is. Is having both the metric cell (neutral numeric) and the
  amber banner (explicit warning) for the same field clear, or
  does it read as redundant?

### A4 — Quality Reports V2 per-finding drilldown

The Quarter Detail drawer's Quality Report section previously showed
a raw JSON dump of the `issues` array. A4 replaces it with
per-finding cards showing: severity badge (danger/warning/secondary),
monospace `check` code, optional `accession_no`, `detail` text.
Empty array → "No issues recorded." muted text.

- Does the card layout surface enough information for an operator
  to act on a finding? Is there a missing field from the `{check,
  severity, accession_no, detail}` shape that you'd expect to see
  (e.g. a timestamp, a count, a recommended action)?
- The severity mapping is: `error` → red danger badge, `warning` →
  amber warning badge, `info` → grey secondary badge. Is that the
  right color hierarchy for this admin context? Are there severity
  values other than `error`, `warning`, `info` that the
  quality-check job at `thirteenf_admin_dashboard.py:2841` may
  emit that would fall through to the `secondary` badge?

**Output format:**

```
VERDICT: APPROVE / APPROVE-WITH-CONDITIONS / REJECT

A1 (note required + evidence_json):
- [your read]

A2 (Kahn Brothers caveat):
- [your read]

A3 (missing infotable banner):
- [your read]

A4 (per-finding drilldown):
- [your read]

MVP8-03A should-block items (if any):
1. ...

Future backlog (separate ticket):
1. ...
```

Be terse.

---

## 2. Staff Engineer Prompt

You are the Staff Engineer conducting the MVP8-03A cross-ticket
review for ValuePilot's 13F automation track. MVP8-03A is a four-fix
admin-surface ticket shipped as commit `4a159a5` on branch
`docs/13f-automation-prd`. It is a child of the MVP8-03 SME-flag
cluster; MVP8-03B (watchlist/scoring) closed first and authorized
this ticket.

**Read these files in order:**

1. `docs/tasks/2026-05-13_mvp8-03a-admin-sme-fixes.md` — full spec.
2. The diff at commit `4a159a5` — 9 files, ~400 lines net.
3. `backend/app/api/v1/endpoints/thirteenf_admin.py` lines 76–95
   (`ManagerTypeUpdateRequest` — model_validator placement).
4. `backend/app/services/manager_type_review.py` — full file (~125
   lines). Note: `update_manager_type` is the only caller of
   `InstitutionManagerTypeReviewEvent`; the service is only called
   from the admin endpoint.
5. `backend/app/services/thirteenf_historical_backfill.py` lines
   100–125 (`preview_historical_backfill` with CIK hardcode).
6. `frontend/components/admin13f/ManagerTypeEditorDialog.tsx` —
   full file. Note: `evidenceUrl` is managed as internal state
   (not a prop), unlike `note` which is a prop.

**Review angles + accept/reject criteria:**

1. **Validator placement — API layer vs service layer.**
   The note-required constraint lives in `ManagerTypeUpdateRequest`
   (Pydantic model, API layer), not in `update_manager_type`
   (service layer). This means a direct call to the service with
   `note=None` for a non-unknown transition would succeed without
   the constraint firing. Assess: is there any call site (test
   helper, management command, background job) that calls
   `update_manager_type` directly with `note=None` for a non-unknown
   type? If not, is the API-only placement acceptable given the
   service is single-caller admin-only? Should the constraint be
   duplicated at the service layer as a defensive check?

2. **CIK hardcoding in `preview_historical_backfill`.**
   `any(m.cik == "0001039565" for m in managers)` — a magic string
   in a service function. CLAUDE.md names this filer as a documented
   project-level exception. Assess: (a) Is this the right layer for
   the check (service preview vs endpoint vs a config constant)?
   (b) Should the CIK be extracted to a named constant (e.g.
   `KAHN_BROTHERS_CIK = "0001039565"`) adjacent to
   `DEFAULT_BACKFILL_START_QUARTER` in the same file? (c) If a
   second filer with a similar dollar-vs-thousands anomaly is
   discovered, does the pattern scale (an allowlist), or does it
   require a DB-level flag?

3. **`evidenceUrl` as internal dialog state.**
   `note` / `setNote` are props (parent resets `note` in `onSuccess`
   via `setManagerTypeNote('')`). `evidenceUrl` is internal to the
   dialog component. The parent never sees or resets the URL
   directly — the dialog clears it in `handleClose()`, which fires
   via `onOpenChange(false)` when the parent sets `editor=null`
   after a successful save. Assess: is this asymmetry in state
   ownership (props for note, internal for URL) a coherent pattern,
   or does it create a subtle bug if a future caller needs to reset
   `evidenceUrl` without going through the dialog's close cycle?

4. **`evidence_json` dict shape — forward compatibility.**
   The frontend sends `{ url: evidenceUrl }` and the backend stores
   it verbatim in a JSONB column with no shape constraint. If a
   future PR adds a second evidence type (e.g. `{ file_hash: ... }`
   or `{ transcript: ... }`), the existing rows with `{ url }` stay
   valid and the new shape is also accepted — no migration needed.
   Is that the right contract, or should a schema-constrained
   approach (Pydantic union discriminator) be used now to prevent
   drift?

5. **Scope discipline.**
   A1–A4 are the only changes in `4a159a5`. Confirm the commit
   doesn't touch: DrawerShell component, manager-name truncation,
   accession URL threading, a11y suite, any watchlist-surface code.
   These are explicitly scoped out per the spec.

6. **A4 type cast duplication.**
   `readiness/page.tsx` casts `selectedQuarterDetail.quality_report
   .issues` to the per-finding type twice — once for `.length` and
   once for `.map()`. This is safe (read-only) but could be
   extracted to a local typed variable. Non-blocking but worth a
   note.

**Output format:**

```
VERDICT: APPROVE / APPROVE-WITH-CONDITIONS / REJECT

MVP8-03A should-block items (before this ticket closes):
1. ...

Follow-up tech-debt tickets to file:
1. ...
```

---

## 3. Backend Reviewer Prompt

You are the Backend Reviewer for ValuePilot's 13F automation track.
MVP8-03A shipped four admin SME fixes in commit `4a159a5` on branch
`docs/13f-automation-prd`. Backend changes: one Pydantic
model_validator, one service kwarg + model field pass-through, one
preview function key addition, and new unit tests.

**Read these files in order:**

1. `backend/app/api/v1/endpoints/thirteenf_admin.py` lines 1–10
   (imports — note `model_validator` added) and lines 76–95
   (`ManagerTypeUpdateRequest` — full model with validator).
2. `backend/app/services/manager_type_review.py` — full file.
   Focus: `update_manager_type` kwarg addition + event construction.
3. `backend/app/services/thirteenf_historical_backfill.py` lines
   100–125 (`preview_historical_backfill`).
4. `backend/tests/unit/test_13f_mvp5_05_manager_type_editor.py`
   lines 162–186 (two updated existing tests) and lines 225–285
   (three new A1 tests).
5. `backend/tests/unit/test_13f_mvp3_historical_backfill.py` lines
   121–160 (two new A2 tests).

**Review angles:**

1. **Pydantic v2 `model_validator(mode="after")` behavior.**
   The validator fires after all field-level validators. If the
   client sends `{"new_manager_type": "long_term_fundamental"}` with
   no `note` key, `note` defaults to `None` (per `note: str | None
   = None`). Then `(None or "").strip()` → `""` → raises ValueError.
   FastAPI wraps this in a 422 Unprocessable Entity (not 400).

   Assess: (a) Is a 422 the right HTTP status for this business-rule
   violation? The spec says "400 message: …" but Pydantic validation
   errors produce 422 in FastAPI. Should the validator be moved out
   of the Pydantic model into the endpoint body so the 400 contract
   can be preserved exactly? (b) The A1 test correctly uses
   `status_code in (400, 422)`. Is that dual-accept appropriate
   for the test, or should it pin to one value to prevent future
   drift?

2. **`evidence_json: dict | None` field type.**
   No shape constraint on the dict. The only current producer is the
   frontend, which sends `{ "url": "..." }`. A future producer could
   send an arbitrary dict. Assess: is the open `dict` type correct
   for an MVP (flexible, no migration needed), or should a TypedDict
   / Pydantic inner model be used to constrain the shape and make
   the audit trail self-describing?

3. **`update_manager_type` service — note validation not duplicated.**
   The service accepts `note=None` without raising even for non-unknown
   transitions. This is by design (the constraint lives at the API
   layer). Verify: is `update_manager_type` called from anywhere
   other than `patch_manager_type` endpoint? Search for other call
   sites in the codebase. If none exist, the API-layer-only placement
   is safe. If any internal tooling calls the service directly,
   document the bypass risk.

4. **`test_endpoint_returns_400_on_invalid_taxonomy` — note added.**
   The test now sends `"note": "re-classifying"` so the model
   validator passes and the taxonomy check fires. The taxonomy check
   is in the service: `if new_manager_type not in MANAGER_TYPES:
   raise ManagerTypeUpdateError(...)`. The endpoint catches this
   and returns `HTTPException(status_code=400, ...)`. So the test
   gets a 400 with the taxonomy error message. Confirm the test's
   assertion `"new_manager_type" in response.json()["detail"]`
   still holds against the actual error text: "new_manager_type must
   be one of: activist, high_turnover, index_like, long_term_fundamental,
   multi_strategy, quant, unknown, value_concentrated". ✓ (the
   substring "new_manager_type" is present). Verify.

5. **Kahn Brothers CIK string format.**
   `m.cik == "0001039565"` — the CIK is stored as a string.
   `InstitutionManager.cik` is VARCHAR. The seed fixture pads CIKs
   with `zfill(10)`. Kahn Brothers CIK in the EDGAR system is
   `0001039565` (10 digits). Verify: (a) Is the CIK stored in the
   DB as `"0001039565"` (with leading zeros) or as `"1039565"`
   (without)? If without, the hardcoded string would never match.
   Check `backend/app/services/thirteenf_daily_sync.py` or the
   EDGAR CIK normalization path to confirm.

6. **A2 test — get-or-create pattern.**
   `test_preview_kahn_brothers_in_scope_true_when_cik_matches`
   queries for the existing Kahn Brothers manager (dev fixture may
   have seeded it) then falls back to inserting. This is the correct
   pattern given the dev-fixture DB state. Assess: is
   `scalar_one_or_none()` the right query method here, or could
   there be two rows with the same CIK in the DB (which would cause
   a `MultipleResultsFound` error)?

**Output format:**

```
VERDICT: APPROVE / APPROVE-WITH-CONDITIONS / REJECT

Code-level findings:
- [path:line — finding — severity: blocker/should-fix/nit]

MVP8-03A should-block items (if any):
1. ...

Tech-debt notes:
1. ...
```

---

## 4. Frontend Reviewer Prompt

You are the Frontend Reviewer for ValuePilot's 13F automation track.
MVP8-03A shipped four admin SME fixes in commit `4a159a5` on branch
`docs/13f-automation-prd`. Frontend changes: `ManagerTypeEditorDialog`
gains note-required UX + evidence URL field; `jobs/page.tsx` gains
two amber banners; `readiness/page.tsx` replaces a JSON dump with
per-finding cards.

**Read these files in order:**

1. `frontend/components/admin13f/ManagerTypeEditorDialog.tsx` —
   full file (~175 lines). Focus: internal `evidenceUrl` state,
   `noteRequired` derived value, `handleClose`, `saveDisabled`.
2. `frontend/app/(dashboard)/admin/13f/managers/page.tsx` lines
   78–110 (mutation — new `evidenceUrl` field in payload type +
   `evidence_json` in PATCH body).
3. `frontend/app/(dashboard)/admin/13f/jobs/page.tsx` lines
   718–775 (Historical Backfill `kahn_brothers_in_scope` banner)
   and lines 852–880 (Batch Reparse `missing_raw_infotable_count`
   banner).
4. `frontend/app/(dashboard)/admin/13f/readiness/page.tsx` lines
   1155–1215 (per-finding cards replacing `formatJson()`).

**Review angles:**

1. **`evidenceUrl` internal state — close lifecycle.**
   `evidenceUrl` is managed as internal component state (not a
   prop), unlike `note` which is a prop (parent resets it in
   `onSuccess`). After a successful save:
   - Parent calls `setManagerTypeEditor(null)` in `onSuccess`
   - `open={editor !== null}` becomes `false`
   - `onOpenChange(false)` fires → `handleClose()` → `setEvidenceUrl('')`
   
   Verify: does `handleClose()` fire correctly when the save
   triggers the parent `onSuccess` path? Is there any code path
   where `editor` is set to null without triggering `onOpenChange`?
   (E.g., if the parent calls `setManagerTypeEditor(null)` without
   the Dialog being open — can that happen in the existing call
   sites?)

2. **Note label rendering.**
   The label renders as:
   ```tsx
   Note{noteRequired
     ? <span className="ml-0.5 text-destructive">*</span>
     : ' (optional)'}
   {noteRequired ? ' (required when classifying)' : null}
   ```
   This produces:
   - When `noteRequired=true`: `Note* (required when classifying)`
     where `*` is red.
   - When `noteRequired=false`: `Note (optional)`.
   
   Assess: (a) Is the `text-destructive` class the right color
   for the `*` indicator in this admin context (it uses the same
   red as form error states — may feel alarming before the user
   does anything)? (b) The label text node `' (required when
   classifying)'` follows the `<span>` — check that browsers
   render the space correctly (inline + text node with leading
   space should be fine, but worth confirming).

3. **Save button disabled state.**
   `saveDisabled = !editor || isPending || (noteRequired && !note.trim())`.
   When the Select changes from `'unknown'` to `'long_term_fundamental'`,
   `noteRequired` becomes `true` immediately and `note` is still
   `''`, so `saveDisabled` becomes `true`. This is correct. Verify:
   when the user then types in the note field, does `saveDisabled`
   re-evaluate on each keystroke? (Yes — it's a derived value from
   props, not memoized.) Is there any stale-closure risk here?

4. **Evidence URL `type="url"` input.**
   `<Input type="url" ... />` — browser's native URL parsing runs
   only on form submission via `<form>`. Since the dialog uses an
   `onClick` handler (not `<form onSubmit>`), the browser's URL
   format validation does NOT fire. The input accepts any string.
   Is this acceptable for an internal admin tool? Or should a manual
   URL validation check be added before enabling Save (e.g.
   `value.startsWith('https://')`)?

5. **A3 type cast chain.**
   ```tsx
   {((brPreview['estimated_scope'] as Record<string, unknown>)?.[
     'missing_raw_infotable_count'
   ] as number) > 0 ? (
   ```
   If `missing_raw_infotable_count` is absent from the payload,
   the cast `undefined as number` → `NaN`. And `NaN > 0` is
   `false`, so the banner stays hidden. No false positives. But
   the `missing_raw_infotable_count` is also accessed a second
   time inside the banner to display the count. Is that access
   safe under the same `undefined → NaN` chain? Verify: `String(
   undefined ?? 0)` → `"0"` — yes, safe. But the display would
   show "0 filing(s)" which shouldn't happen since the banner
   only shows when `> 0`. ✓

6. **A4 `key={i}` on the issues array.**
   `(issues).map((issue, i) => <div key={i} ...>)` uses the array
   index as key. Acceptable for a read-only, server-rendered list
   that is never reordered or filtered client-side. Confirm: is
   there any sort control, filter, or client-side mutation of the
   `issues` array in this drawer? If not, `key={i}` is fine.

7. **A4 type annotation duplication.**
   The `issues` field is cast twice to `Array<{check, severity,
   accession_no?, detail?}>`:
   ```tsx
   (selectedQuarterDetail.quality_report.issues as Array<{...}> | undefined)?.length
   // and then again:
   (selectedQuarterDetail.quality_report.issues as Array<{...}>).map(...)
   ```
   A local typed variable would eliminate the duplication:
   ```tsx
   const issues = selectedQuarterDetail.quality_report.issues as
     Array<{check: string; severity: string; accession_no?: string;
     detail?: string}> | undefined;
   ```
   Non-blocking but worth a nit.

8. **A4 `max-h-60` scrollable area.**
   The old JSON dump used `max-h-44`; the per-finding cards use
   `max-h-60`. Each card is ~2–3 lines tall (severity badge row +
   optional detail row), so `max-h-60` accommodates roughly 4–6
   cards before scrolling. Assess: is that height appropriate for
   a typical quality report, or should it be `max-h-80` /
   unbounded with a scroll container?

9. **Accessibility.**
   - The `*` required indicator is a `<span>` with no
     `aria-hidden` or `role`. Screen readers will read it as
     "asterisk". For proper a11y, the textarea should have
     `aria-required="true"` when `noteRequired` is true. This is
     explicitly out of scope for this ticket (a11y suite is a
     separate track), but note it.
   - The per-finding cards in A4 have no `role="listitem"` or
     wrapping `role="list"`. Again, out of scope per the spec.

**Output format:**

```
VERDICT: APPROVE / APPROVE-WITH-CONDITIONS / REJECT

UX findings:
- [component — finding — severity: blocker/should-fix/nit]

Code-level findings:
- [file:line — finding — severity: blocker/should-fix/nit]

MVP8-03A should-block items (if any):
1. ...

Future backlog (out of scope for this ticket):
1. ...
```

---

## Dispatch Notes

- Each prompt is self-contained; hand any one to a fresh chat or
  human reviewer without sharing the others.
- For agent dispatch, all four can run in parallel — there is no
  dependency between reviewer roles.
- Output bucketing: "MVP8-03A should-block" items must be addressed
  before this ticket's sign-off trail closes. "Future backlog"
  items file as separate tickets.
- Implementation verdict (internal four-role review): all four roles
  APPROVE 2026-05-13. Two scoped-out notes: (1) `*` required
  indicator is visual-only, no `aria-required`; (2) A4 type cast is
  duplicated. Both explicitly deferred per spec scope-out clause.
