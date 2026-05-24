# 2026-05-24 — Decouple bootstrap from Dataroma; add admin "Sync with Dataroma" diff UI

## Goal

Untangle two distinct admin actions that used to share the
`bootstrap_whitelist` button:

1. **Bootstrap manager universe** — should be **offline**, deterministic,
   one-button, and shipped via `confirmed_managers.json` (already V2-enriched
   with 82 superinvestors as of `2026-05-24_manager-taxonomy-v2`).
2. **Sync with Dataroma** — a separate, on-demand check that diffs the
   current Dataroma manager list against ours and surfaces additions /
   drops for admin review **without** auto-inserting anything.

The current `bootstrap_whitelist()` does both (fetches Dataroma, inserts
seeded rows without CIK), which:

- Makes CI flaky on Dataroma outages / rate limits.
- Pollutes the manager universe with un-classified `seeded` rows that the
  V2 taxonomy work just spent a PR cleaning up.
- Hides the "discover new Dataroma names" workflow from admin — the diff
  only ever happens implicitly inside the same button that also writes.

## Acceptance criteria

### Backend

1. `bootstrap_whitelist()` is renamed and refactored. The new symbol is
   `sync_dataroma_managers(session) -> DataromaSyncDiff`:
   - Calls `DataromaClient`.
   - Returns a `DataromaSyncDiff` dataclass with three lists:
     - `new`: Dataroma codes we don't know about (anywhere in our DB).
     - `known`: Dataroma codes that already match one of our managers.
     - `dropped`: Our managers whose `dataroma_code` is no longer in
       Dataroma's current list (excluding those without a `dataroma_code`).
   - **Does NOT write to `institution_managers`.**
2. New `add_dataroma_candidates(session, items)`:
   - Takes a list of `{dataroma_code, name}` pairs.
   - Inserts each as `match_status='candidate'`, `is_superinvestor=True`,
     no CIK, V2 fields default to `unknown`, `review_note` records the
     sync origin and date.
   - Idempotent: skips entries whose `dataroma_code` already exists.
3. Existing admin job `job_type='bootstrap_whitelist'` keeps its name for
   backward compat with the deployed UI button, but its handler now calls
   `seed_confirmed_managers()` (offline, JSON-driven). Summary key changes
   from `managers_seen` to `managers_seeded`.
4. New admin job `job_type='dataroma_sync'`:
   - Runs `sync_dataroma_managers()`, stores the diff in
     `JobRun.summary_json` (counts + first-N samples).
   - Lock key `dataroma_sync` (single concurrent run).
5. New REST endpoints (admin-only):
   - `POST /admin/13f/managers/dataroma-sync` — runs the sync synchronously
     (DataromaClient + Rate Guard takes a few seconds; synchronous keeps the
     UI shape simple). Returns the full diff JSON.
   - `POST /admin/13f/managers/dataroma-sync/add` — accepts
     `{items: [{dataroma_code, name}, …]}`, calls `add_dataroma_candidates`,
     returns `{added: n, skipped: n}`.

### CLI

6. `app/cli/edgar.py`:
   - `bootstrap-whitelist` command stays callable but prints a deprecation
     hint and runs `seed_confirmed_managers()` (same behavior as the renamed
     admin job).
   - New `sync-dataroma` command runs the sync and prints the diff.

### Frontend

7. Managers page (`/admin/13f/managers`) gets a **"Sync with Dataroma"**
   button in the top-of-card toolbar (next to the match_status filter).
8. Clicking it opens a dialog/sheet listing three sections (NEW, KNOWN,
   DROPPED) with counts; the NEW section has per-row checkboxes plus an
   "Add selected as candidates" footer button that POSTs to
   `/admin/13f/managers/dataroma-sync/add`.
9. After "Add selected" succeeds, manager list refetches and dialog closes.

### Tests (test-first per AGENTS.md)

10. New `backend/tests/unit/test_13f_dataroma_sync.py`:
    - `sync_dataroma_managers` returns expected diff for a fake Dataroma
      payload, classifies by `dataroma_code`, never writes to the table.
    - `add_dataroma_candidates` creates rows with `match_status='candidate'`,
      no CIK, V2 defaults, and is idempotent.
    - Admin endpoints require auth (admin role).
    - Job dispatch for `bootstrap_whitelist` no longer calls DataromaClient
      (asserts on a monkeypatched DataromaClient that would raise if hit).
    - Job dispatch for `dataroma_sync` calls DataromaClient and returns
      diff in summary.

### CI

11. All canonical CI commands green in-container.

## Scope

**In:** items 1–11 above.

**Out (deferred):**
- Detecting renames (name changed but dataroma_code same) — handled
  implicitly by `known`-by-code matching.
- Fuzzy name match to bind a Dataroma code to an existing manager that
  has no `dataroma_code` — would be valuable but adds non-trivial UI and
  needs its own design (which name distance threshold? auto-suggest vs
  block?). For V1 such managers show up in `new` and the admin can
  manually attach the code via the existing edit dialog later.
- Scheduled cron sync. The admin pushes the button when they want a
  fresh check.
- Persisted sync history. JobRun rows already record each invocation
  with timestamp + summary, so per-run audit is covered; a dedicated
  sync-findings table is overkill for V1.

## Critical invariants — preserved

- No schema change: no migration needed. (Only behavior + new endpoints.)
- `seed_confirmed_managers()` contract is unchanged from the V2 PR.
- `DataromaClient` and `parse_managers()` are untouched; only the caller
  changes.
- Job dispatch table keeps its existing `bootstrap_whitelist` key (so the
  already-deployed frontend button keeps working).

## Files to change

| File | Change |
|---|---|
| `backend/app/services/edgar_ingestion.py` | Refactor `bootstrap_whitelist` → `sync_dataroma_managers` (no writes); new `add_dataroma_candidates`; new `DataromaSyncDiff` / `DataromaSyncEntry` dataclasses |
| `backend/app/services/thirteenf_admin_dashboard.py` | `bootstrap_whitelist` job_type handler now calls `seed_confirmed_managers`; new `dataroma_sync` job_type + lock key |
| `backend/app/api/v1/endpoints/thirteenf_admin.py` | Two new endpoints under `/admin/13f/managers/dataroma-sync` |
| `backend/app/cli/edgar.py` | `bootstrap-whitelist` deprecation hint + reroute; new `sync-dataroma` command |
| `backend/tests/unit/test_13f_dataroma_sync.py` | NEW test file |
| `frontend/app/(dashboard)/admin/13f/managers/page.tsx` | Toolbar button + diff dialog |
| `frontend/components/admin13f/DataromaSyncDialog.tsx` | NEW component for the diff UI |
| `docs/BACKLOG.md` | Add (if applicable) — none expected |

## Test plan

```
docker compose up -d --build
docker compose exec -T api alembic upgrade head        # no new migrations expected
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

Targeted iteration:
```
docker compose exec -T api pytest -q tests/unit/test_13f_dataroma_sync.py
```

## Gotchas / decisions

- **`bootstrap_whitelist` job_type stays for UI compatibility.** Renaming
  it would require coordinated FE+BE deploy. The handler swap is enough
  — it's the inside of the button that matters, and the user-visible
  behavior change is "no longer touches the network" + "actually seeds
  the 82 V2-classified managers". The "Bootstrap whitelist" button label
  could later be renamed to "Seed manager universe" in a small follow-up.
- **Sync is synchronous.** Dataroma fetch via Rate Guard usually returns
  in 1–3s. Synchronous endpoint keeps the FE shape trivial (no polling),
  and a slow Dataroma just looks like a slow button to admin, which is
  the correct UX.
- **Concurrency is currently un-locked.** The synchronous endpoints
  (``/managers/dataroma-sync`` and ``/managers/dataroma-sync/add``) do
  NOT go through the job system, so admin double-clicks will issue two
  concurrent Dataroma fetches / two concurrent insert batches. The
  ``dataroma_sync`` lock_key in ``_JOB_LOCK_BUILDERS`` exists for the
  parallel job-system path (currently only the CLI / scheduled-run
  shape) — it does not gate the endpoint. Rate Guard's own rate-limit
  handling still applies upstream. For ``/add`` specifically the
  per-entry SAVEPOINT + ``IntegrityError`` catch in
  ``add_dataroma_candidates`` keeps a concurrent double-click on the
  same ``dataroma_code`` from 500-ing the request *and* from creating
  a duplicate row: the partial UNIQUE index
  ``uq_institution_managers_dataroma_code`` (in migration
  ``20260423000000``) makes the second insert raise ``IntegrityError``,
  which the SAVEPOINT handler converts into a skipped-count.
- **The diff `dropped` list is information only.** We don't auto-remove
  managers that disappear from Dataroma — they often disappear because
  Dataroma rotates its tracked-investor list, not because the manager
  stopped filing 13Fs. Admin can decide per case.
