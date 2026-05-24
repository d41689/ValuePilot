# Staff engineer review — manager taxonomy V2 + bootstrap decouple

**Branch:** `claude/manager-taxonomy-v2`
**Reviewer role:** Staff engineer (contract / architecture)
**Review date:** 2026-05-24
**Task docs reviewed:**
- `docs/tasks/2026-05-24_manager-taxonomy-v2.md`
- `docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md`

**Overall verdict:** Approve with two required pre-merge actions and several
deferrable follow-ups. No critical invariants from `AGENTS.md` are violated.

---

## C1 — Schema migration

**File:** `backend/alembic/versions/20260524120000-manager_taxonomy_v2.py`

### Column sizing

All seven columns are appropriately sized for their controlled vocabularies.

| Column | Migration DDL | Longest current value | Assessment |
|---|---|---|---|
| `style_primary` | `String(40)` | `multi_strategy_macro` (21 chars) | Safe — 19 chars headroom |
| `capital_structure` | `String(40)` | `endowment_foundation` (21 chars) | Safe — 19 chars headroom |
| `market_cap_focus` | `String(20)` | `mega` (4 chars) | Safe |
| `historical_turnover` | `String(10)` | `high` (4 chars) | Safe |
| `position_concentration_top10_pct` | `Numeric(6, 2)` | 999.99 max representable | Correct — percentage to 2 dp, no value exceeds 100.00 |
| `ideology_tags` | `JSONB` | unbounded list | Correct type choice |

`geo_focus` (also `String(20)`) is sized similarly to `market_cap_focus` and is
adequate for its five-value vocabulary.

### `server_default='unknown'` on NOT NULL columns

The two NOT NULL columns (`style_primary`, `capital_structure`) carry
`server_default='unknown'` in the migration DDL. PostgreSQL applies
`server_default` synchronously during `ALTER TABLE ... ADD COLUMN` — it
backfills every pre-existing row before the DDL transaction commits. This is
safe for a table that, in production, holds O(100) manager rows. No separate
data migration step is needed, and the task doc is correct to claim
"existing rows backfill cleanly."

One nuance worth recording: `server_default` is applied by the DB engine, not
SQLAlchemy, so the Python-side `default='unknown'` on the `mapped_column` is the
in-memory default for new objects created before the session flushes — not a
redundancy. Both are correct and complementary.

### Index justification

Two B-tree indexes are added:

- `ix_institution_managers_style_primary` — justified. The screener and Oracle's
  Lens filter by `style_primary` when constructing "value-only" universe
  subsets. Even at 100 rows today the index is cheap to create and the query
  pattern is clear.
- `ix_institution_managers_capital_structure` — borderline. The current PR has
  no query that filters by `capital_structure` in isolation. The task doc
  mentions "filters" as a future milestone, so the index is forward-looking. At
  100 rows the cost is zero, but the justification is somewhat speculative.
  **Low-severity finding** — acceptable to keep; record the intent in a comment.

Neither index on a table that stays below O(10 000) rows will ever cause
performance harm, so this is not blocking.

### Downgrade path

The `downgrade()` function correctly:
1. Drops both indexes first (in reverse creation order, capital_structure then
   style_primary).
2. Drops all seven columns in reverse addition order
   (`ideology_tags` → `position_concentration_top10_pct` → `historical_turnover`
   → `geo_focus` → `market_cap_focus` → `capital_structure` → `style_primary`).

This restores the table to its prior shape cleanly. **No issues.**

### Should the migration include a data backfill?

No. The task doc correctly separates schema and data concerns: the migration
provides the structural guarantee (`server_default='unknown'` for not-null
columns), and the data population runs through `seed_confirmed_managers()` via
the `bootstrap_whitelist` admin job. Running service-layer code inside Alembic
migrations is an anti-pattern (circular imports, session management, no
rollback guarantee) that `docs/architecture/data-layer.md` explicitly warns
against. The current design is correct.

**C1 verdict: No blocking issues.**

---

## C2 — Backward compat for `manager_type`

**Files:** `backend/app/models/institutions.py`, `backend/app/services/oracles_lens/manager_style.py`, `backend/app/services/edgar_ingestion.py`

### Auto-derivation at write time vs. model-layer hook

The current design derives `manager_type` from `style_primary` inside
`seed_confirmed_managers()` (line 127: `derive_legacy_manager_type(style_primary)`)
and writes both columns explicitly. There is no `@event.listens_for`
hook in the model that automatically sets `manager_type` whenever `style_primary`
changes.

This is defensible for the V1 scope where `seed_confirmed_managers()` is the
only write path for `style_primary`. However it creates a latent drift risk
(see next sub-section). A model-layer hook would be stronger but has a downside:
it fires on every INSERT/UPDATE of the manager row, including writes that don't
touch `style_primary`, and it introduces a dependency from the model layer on
`manager_style.py`. The current task doc explicitly calls this out of scope
(`manager_type` becomes a derived view; future consumers read `style_primary`).
The trade-off is acceptable for V1 — but the hook gap must be documented.

### Drift risk when `style_primary` is updated outside the seed

The `update_manager()` function (`thirteenf_admin_dashboard.py`, lines 569–597)
allows patching `manager_type` directly through the admin API, and
`ManagerPatchRequest` (`thirteenf_admin.py`, lines 111–122) exposes
`manager_type` as an editable field. **Neither `style_primary` nor any V2
field is in `update_manager()`'s allowed-field list.** This means:

- An admin cannot update `style_primary` via the existing edit dialog today
  (the V2 fields are out of scope for the current admin UI, per the task doc).
- If a future endpoint or admin pathway writes `style_primary` without also
  calling `derive_legacy_manager_type()` and setting `manager_type`, the two
  columns will diverge.

**Required action (pre-merge):** Add a comment to `update_manager()` at line
573 explicitly naming this invariant: "If `style_primary` is added to this
field list in a future PR, also derive and set `manager_type` from it — they
must stay in sync." Add a corresponding backlog entry for "add V2 fields to
`update_manager()` + admin UI" so the next agent that extends the edit dialog
knows to enforce derivation.

The current V1 behaviour is safe — the drift scenario cannot occur without a
code change — but the invariant is invisible to a future agent working from
only the service code. This is medium severity.

### `derive_legacy_manager_type` raising `ValueError` on unknown input

This is the right contract. The docstring explicitly documents the rationale:
"a typo in the seed JSON surfaces immediately instead of silently degrading to
`unknown` (which would mask the regression)." Fail-loud is correct because:

1. The function is called only from `seed_confirmed_managers()` (one call site,
   at line 127), which runs in the admin job system with a visible exception
   surface.
2. The seed JSON passes through CI test
   `test_seed_json_classifications_use_canonical_vocabularies`, which validates
   every entry's `style_primary` against `STYLE_PRIMARY` before the seed runs.
3. The defense-in-depth check at lines 79–83 of `manager_style.py` catches any
   future edit that adds a non-canonical value on the mapping's right-hand side.

A defensive `return 'unknown'` default would silently let a mis-classified seed
entry through with the wrong Oracle's Lens weight — exactly the failure mode the
entire PR exists to fix.

One gap: `quant` is in `MANAGER_TYPES` but has no `style_primary` that maps to
it. This means no new V2-seeded manager can derive `manager_type='quant'`. The
existing pre-V2 rows with `manager_type='quant'` (if any) are not touched by
the seed unless their CIK appears in `confirmed_managers.json` with a
`style_primary` that maps to something else. This is correct by intent — the V2
taxonomy has no quant bucket — but worth confirming with the PO that any
quant-style managers in the confirmed universe are classified under the closest
V2 bucket (e.g. `multi_strategy_macro`).

**C2 verdict: One required pre-merge action (comment + backlog entry for the
drift risk). The `ValueError` contract is correct as-is.**

---

## C3 — Bootstrap / sync separation

**Files:** `backend/app/services/thirteenf_admin_dashboard.py`, `backend/app/api/v1/endpoints/thirteenf_admin.py`

### Job_type name reuse: `bootstrap_whitelist`

Keeping the legacy `job_type='bootstrap_whitelist'` name while changing its
handler to call `seed_confirmed_managers()` is a pragmatic compatibility
decision the task doc explicitly justifies: "Renaming it would require
coordinated FE+BE deploy." The handler comment at lines 2918–2924 clearly
documents the old behavior and the change. The summary key change from
`managers_seen` to `managers_seeded` is the correct signal to admin that the
semantics changed.

The honest-contract concern is real but low severity. The existing deployed UI
button says "Bootstrap whitelist" and still works. A later rename to "Seed
manager universe" (mentioned in the task doc as a follow-up) would require only
a frontend label change at that point. The backlog should capture this.

**Verdict:** Acceptable for V1. The code comment is clear enough that a future
agent will not be confused. Confirm the backlog entry mentions this label change.

### Synchronous endpoints vs. job system

`POST /admin/13f/managers/dataroma-sync` is synchronous and does not go through
the job system. The task doc justification is sound: the Dataroma fetch via Rate
Guard returns in 1–3 seconds, and synchronous keeps the frontend shape trivial.

However, there is a **material discrepancy between the task doc and the code.**
The task doc (line 162) states: "The locking is still respected via the job
system if admin spams the button — second click within the lock window returns
409 / 'another sync in progress' rather than racing."

This is incorrect. The `/admin/13f/managers/dataroma-sync` endpoint at lines
477–498 does not call the job system's lock mechanism at all. It calls
`sync_dataroma_managers(session)` directly. Two concurrent requests from
different admin users (or the same admin double-clicking before the first
response arrives) will both execute against Rate Guard simultaneously. Rate
Guard's own per-upstream rate limiting will apply, but there is no
application-layer deduplication or 409 response.

For a pure read operation (no writes), two concurrent `sync_dataroma_managers()`
calls are safe — they will both complete and return a diff. The practical impact
is two Rate Guard fetches instead of one, and the admin seeing a slightly stale
result for one of them. This is acceptable for a rare admin-only button.

**Required action (pre-merge):** Fix or remove the incorrect claim in the task
doc. The endpoint comment at line 463 ("concurrent admins double-clicking just
hit Rate Guard twice — acceptable for a button this rare") is correct. The task
doc's 409 claim is not. Update `docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md`
line 162 to remove the job-system lock reference and replace it with the actual
behaviour: "Two concurrent sync calls both complete — Rate Guard serializes the
upstream fetches per its own rate-limit policy." This is a documentation
correctness issue, not a code defect, but leaving the wrong claim in the task
doc will mislead the next engineer who reads it.

**C3 verdict: One required pre-merge action (fix task doc concurrency claim).
The code itself is correct for the stated use case.**

---

## C4 — The diff algorithm

**File:** `backend/app/services/edgar_ingestion.py`, `sync_dataroma_managers()`

### Match by `dataroma_code` only — no fuzzy name match

The diff indexes `institution_managers` rows by `dataroma_code` only (lines
356–363). A manager we have confirmed (e.g., from the seed JSON, with no
`dataroma_code`) that Dataroma starts tracking (with a code) will appear in the
`new` bucket even though it may be a conceptual duplicate.

The task doc explicitly accepts this as a V1 tradeoff (Scope → Out):
"Fuzzy name match to bind a Dataroma code to an existing manager that has no
`dataroma_code` ... For V1 such managers show up in `new` and the admin can
manually attach the code via the existing edit dialog later."

The UX implication is correct: when the admin sees a "new" entry in the diff
that they recognise as a manager they already track, they can close the dialog
without adding (or add it and let the idempotency in `add_dataroma_candidates`
catch the duplicate by `dataroma_code`). The existing edit dialog then lets the
admin attach the `dataroma_code` to the already-confirmed row. No data loss.

One edge case not documented: if the admin clicks "Add selected" on a manager
that already exists with no `dataroma_code`, `add_dataroma_candidates()` will
create a *second* `institution_managers` row with the `dataroma_code` set.
The admin would then have two rows for the same manager. The `dataroma_code`
field is nullable and has no UNIQUE constraint. This is a known limitation of
the V1 design — the task doc acknowledges it — but it is worth explicitly
noting in the backlog as a potential data-quality risk.

**Add to backlog:** "Dataroma sync V1 — admin may create a duplicate manager
row if they click Add for a manager that already exists without a
`dataroma_code`. Mitigate in V2 by either adding a UNIQUE constraint on
`dataroma_code` or by showing a warning when a `new` Dataroma entry
name-matches an existing confirmed manager."

### `dropped` excludes managers without `dataroma_code`

The logic at lines 385–393 is correct and well-documented: only rows with a
`dataroma_code` can be considered "dropped" from Dataroma's list. Managers
seeded from `confirmed_managers.json` without a `dataroma_code` are excluded
from the dropped bucket, which is correct — Dataroma never tracked them, so
their absence from Dataroma's current payload is not a signal.

The UX implication — the `dropped` list may be substantially empty even when
Dataroma's universe has shrunk — is correctly handled by the frontend component
showing `{droppedCount} dropped from Dataroma` with a count badge, so the admin
can see the number even when the sample list is empty.

**C4 verdict: No blocking issues. One backlog suggestion for the duplicate-row
risk.**

---

## C5 — Test coverage

**Files:** `backend/tests/unit/test_13f_manager_taxonomy_v2.py` (23 cases),
`backend/tests/unit/test_13f_dataroma_sync.py` (10 cases)

### Overall assessment

Coverage is good for the core contract: the mapping, the seed JSON, and the
two functional paths (seed + sync diff). The critical hero assertion
(`test_derive_legacy_manager_type_tiger_cubs_become_high_turnover`) is present
and correctly ties to the Oracle's Lens weight table.

### Specific gaps

**1. Missing auth test for the two new REST endpoints.**

The task doc AC #3 (`docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md`,
line 84) states: "Admin endpoints require auth (admin role)." There is no test
in `test_13f_dataroma_sync.py` that exercises the endpoints via the HTTP client
and asserts a 401/403 for unauthenticated or non-admin callers. Other endpoint
tests in the suite do this correctly (e.g.
`test_13f_mvp4_unknown_manager_priority.py`, line 300:
`test_endpoint_requires_admin`). The `AdminUser` dependency in FastAPI provides
the auth guard, but without a test that actually calls the endpoint without auth
headers, the guard is only confirmed by inspection. **Low-severity finding** —
the pattern is consistent with how similar admin endpoints are protected — but
missing from this PR's test file.

**2. `test_bootstrap_whitelist_job_type_uses_offline_seed_path` — strength
of the contract test.**

The test monkeypatches `app.services.edgar_ingestion._fetch_dataroma_managers`
to raise `AssertionError` if called, then runs `_execute_job(db_session,
"bootstrap_whitelist", {})` and asserts the result contains `managers_seeded`.
This is a reasonable seam. A stronger version would also assert that the
`_execute_job` call returns an integer count `>= 80` for `managers_seeded` (not
just that the key exists), tying the contract test to the full seed path. As
written, a handler that returns `{"managers_seeded": 0, "status": "succeeded"}`
would pass the test even if `seed_confirmed_managers` was replaced with a stub.
**Low-severity finding** — the end-to-end test
`test_bootstrap_whitelist_handler_actually_seeds_v2_managers` provides the
stronger wiring check, so the gap is partially covered.

**3. Test isolation rewrite: "my row isn't dropped" vs "no rows are dropped."**

`test_sync_dataroma_dropped_excludes_rows_without_dataroma_code` uses subset
semantics: "my fixture row's id does not appear in the dropped list." The
comment (lines 130–141) correctly explains why the full `== []` assertion was
replaced — the dev DB may have pre-existing committed rows with `dataroma_code`
set, and those legitimately appear in `dropped` against an empty fake payload.

The rewrite is the right call. The subset check is exactly the right scope for
this test: it verifies the invariant ("rows without a `dataroma_code` must not
be dropped") without coupling to the state of the dev DB. CI (empty volume)
would have passed both forms; the subset form is more robust in local dev.

The underlying isolation problem (test suite against the dev DB) is correctly
captured in `docs/BACKLOG.md` with the relevant two pre-existing entries.

**4. Sample truncation: no test for >25 new entries.**

`DataromaSyncDiff.to_summary_dict()` truncates each sample list to
`sample_size=25`. There is no test that exercises the truncation path (a
Dataroma payload with >25 new entries) and verifies that `new_count` reflects
the full count while `new_sample` is capped. The frontend component handles
this correctly (`lines 202–207`: "Showing first N of M. Re-run sync after
adding to see the rest."), but the backend truncation is untested. **Low
severity** — the logic is a simple list slice, and the FE behaviour is correct
— but a test would pin the contract.

**C5 verdict: No blocking issues. Four low-severity gaps, all deferrable. One
auth test gap should be considered for a post-merge follow-up.**

---

## C6 — Pre-existing test isolation issue

**Reference:** `docs/BACKLOG.md`, entry "_clear_13f test helper raises FK
violation when dev DB has committed rows"

### Triage correctness

**Severity: medium (dev-only)** is correct. The entry accurately describes the
problem scope:

- CI always starts from an empty volume. The FK violation cannot occur in CI
  because the `quality_findings_13f` and related FK-bearing rows are never
  committed before the test suite runs in CI.
- Local dev is affected when any real bootstrap / ingestion run has left data in
  the dev DB.
- The new `test_13f_manager_taxonomy_v2.py` and `test_13f_dataroma_sync.py`
  tests do not use `_clear_13f` — they use `db_session` (transactional
  rollback). They are not affected by this issue.

The backlog entry correctly confirms: "Verified non-regressing by my own work."
This means the new tests do not worsen the isolation problem.

### Should this PR fix the issue?

No. The fix in scope for this PR would be either (a) expanding `_clear_13f` to
also delete `quality_findings_13f` and `quality_reports_13f` before
`institution_managers`, or (b) switching the conftest to a dedicated test
database. Option (b) is the correct long-term fix (the backlog entry correctly
calls it the "AGENTS.md-aligned" path).

Either fix is out of scope for this PR because:
1. The issue reproduces on `main` with all V2 changes stashed — it is not
   introduced by this PR.
2. The test isolation architecture is a cross-cutting concern that warrants its
   own change, its own test plan, and its own sign-off.
3. Expanding `_clear_13f` without a dedicated test database still doesn't solve
   the root cause (test data leaking from app runs).

The deferred-work workflow in `AGENTS.md` is correctly applied here: the PR
names the deferral (backlog entry exists, is linked from the task doc), and the
next agent can find the entry by reading the repo.

**One suggestion:** Promote the backlog entry to a GitHub Issue for human
triage. The current entry notes "Severity: medium" which does not rise to the
"stop and tell the user" threshold, but the test isolation problem has been
present in at least three backlog entries with overlapping descriptions (the
`_clear_13f` FK entry added by this PR, the "13F test suite is not isolated"
entry from 2026-05-22, and the "dev-cusip-linking-fixture" task). Consolidating
them into a single GitHub Issue with an owner would help. This is a process
suggestion, not a blocking code issue.

**C6 verdict: Triage is correct. No fix required in this PR. One process
suggestion (GitHub Issue consolidation).**

---

## Required pre-merge actions

1. **[C2]** Add a comment to `update_manager()` in
   `backend/app/services/thirteenf_admin_dashboard.py` (after line 583 — the
   end of the allowed-field list) documenting the V2 derivation invariant:
   "If `style_primary` is added to this list in a future PR, call
   `derive_legacy_manager_type(style_primary)` and set `manager_type`
   accordingly — the two columns must stay in sync." Also add a backlog entry
   for "Extend update_manager + admin PATCH endpoint to accept V2 fields +
   auto-derive `manager_type`."

2. **[C3]** Correct the task doc
   `docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md` around line 162.
   Remove the claim that "second click returns 409 via the job system." Replace
   with the accurate description: the synchronous endpoint has no application-
   layer lock; two concurrent calls both hit Rate Guard (which serializes its
   own egress), both return a valid diff, and both complete safely. The code's
   own comment at endpoint line 463 is already accurate — the task doc must
   match it.

---

## Deferrable findings (backlog candidates)

| ID | Severity | Finding | Suggested action |
|---|---|---|---|
| D1 | low | `capital_structure` index has no current query; forward-looking only. | Add a comment in the migration explaining the anticipated query pattern. |
| D2 | medium | `quant` manager_type is not derivable from any V2 `style_primary`. Confirm with PO that no confirmed manager should resolve to `quant`. | Verify `confirmed_managers.json` has no entry intended to be `manager_type=quant`. |
| D3 | medium | `add_dataroma_candidates` may create a duplicate manager row for a manager already confirmed without a `dataroma_code`. No UNIQUE constraint on `dataroma_code`. | Add to backlog: "V2 Dataroma sync — no guard against duplicate rows when confirmed manager lacks `dataroma_code`." |
| D4 | low | Auth test missing for `POST /admin/13f/managers/dataroma-sync` and `/add`. | Add a test asserting 401/403 for unauthenticated callers in a follow-up. |
| D5 | low | `test_bootstrap_whitelist_job_type_uses_offline_seed_path` does not assert the seeded count is >0. | Strengthen the assertion to `result["managers_seeded"] >= 80` in a follow-up. |
| D6 | low | `to_summary_dict()` sample truncation at 25 is untested. | Add a test with a >25-entry fake payload confirming `new_count` > `len(new_sample)`. |
| D7 | low | Three overlapping backlog entries for test isolation should be consolidated into one GitHub Issue. | Create one GH issue linking all three backlog entries. |
| D8 | low | Task doc should note that "Bootstrap whitelist" label in the frontend UI is an acknowledged follow-up rename. | Already mentioned in task doc line 157 — ensure the backlog has an entry. |

---

## Approval status

**Approved pending the two required pre-merge actions (C2 comment/backlog, C3
task doc correction).** No critical invariants from `AGENTS.md` are violated.
The schema is sound, the downgrade path is clean, the core contract tests are
in place, and the bootstrap / sync separation achieves its stated goal. The
deferrable items are all low- or medium-severity and correctly scoped for
follow-up work.
