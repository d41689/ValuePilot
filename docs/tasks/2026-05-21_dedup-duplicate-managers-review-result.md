# Review result - Dedup duplicate institution managers

Source prompt: `docs/tasks/2026-05-21_dedup-duplicate-managers-review-prompts.md`

Reviewed branch: `claude/dedup-managers`

Overall verdict: **PASS**

No blocking findings. The hard-delete path is FK-complete for the current model graph, aborts before writes on unexpected dependencies, deletes audit rows before manager rows in a single committed transaction, and the seed-file changes close the specific re-duplication path. I also re-ran the prompt's read-only prod state check and backend pytest sanity check.

## A. Delete Safety - Mandatory

### A1. FK coverage

Verdict: **PASS**

`rg 'ForeignKey("institution_managers' backend/app/models/` shows every FK into `institution_managers.id`:

- `InstitutionManager.parent_manager_id` at `backend/app/models/institutions.py:98-99`
- `InstitutionManagerCikReviewEvent.manager_id` at `backend/app/models/institutions.py:177-178`
- `InstitutionManagerTypeReviewEvent.manager_id` at `backend/app/models/institutions.py:207-208`
- `Filing13F.manager_id` at `backend/app/models/institutions.py:305-306`
- `Holding13F.manager_id` at `backend/app/models/institutions.py:540-543`
- `OwnershipChange13F.manager_id` at `backend/app/models/institutions.py:604-605`
- `QualityFinding13F.manager_id` at `backend/app/models/institutions.py:769-778`
- `OraclesLensScoreComponent.manager_id` at `backend/app/models/oracles_lens.py:153-156`

`backend/scripts/dedup_managers.py::_deps()` checks the seven unexpected dependency surfaces: filings, holdings, ownership changes, CIK review events, Oracle's Lens score components, quality findings, and child managers (`parent_manager_id`) at `backend/scripts/dedup_managers.py:43-54`. It separately counts `InstitutionManagerTypeReviewEvent` rows at `backend/scripts/dedup_managers.py:72-75`, which matches the intended audit-row exception.

### A2. Abort-on-block and transactional behavior

Verdict: **PASS**

The script sets `blocked = True` if either the keep row is missing or `_deps()` returns any non-zero unexpected dependency, then exits before the write section at `backend/scripts/dedup_managers.py:61-90`. The default path is dry-run unless `--apply` is present at `backend/scripts/dedup_managers.py:57-59` and `backend/scripts/dedup_managers.py:88-90`.

In apply mode, all deletes run through one `SessionLocal()` and a single `session.commit()` after all pairs are processed at `backend/scripts/dedup_managers.py:92-103`. The delete order is audit rows first, then manager rows, at `backend/scripts/dedup_managers.py:96-100`. If a surprise FK blocks a manager delete before commit, the session is closed without a commit at `backend/scripts/dedup_managers.py:104-105`.

### A3. What was destroyed

Verdict: **PASS**

The task log records that each deleted row had no filings, holdings, ownership changes, CIK review events, Oracle's Lens score components, quality findings, or child managers, and only one `institution_manager_type_review_events` row at `docs/tasks/2026-05-21_dedup-duplicate-managers.md:28-33`. It also records the user-authorized hard-delete decision and why losing the machine first-pass audit row is acceptable for phantom duplicate managers at `docs/tasks/2026-05-21_dedup-duplicate-managers.md:35-38`.

## B. Keep / Delete Correctness - Mandatory

### B4. Abrams / Akre / Himalaya

Verdict: **PASS**

The task log records the intended surviving rows and data-bearing rationale:

- Abrams: keep id 18, delete id 84; id 18 has 4 filings / 49 holdings.
- Akre: keep id 15, delete id 81; id 15 has 4 filings / 76 holdings.
- Himalaya: keep id 46, delete id 83; id 46 has 5 filings / 50 holdings.

Evidence: `docs/tasks/2026-05-21_dedup-duplicate-managers.md:21-26`.

The script's hard-coded `PAIRS` exactly match those delete/keep choices at `backend/scripts/dedup_managers.py:34-40`.

### B5. Baupost active-CIK choice

Verdict: **PASS**

Baupost is intentionally the non-symmetric case: the PR keeps id 85 with CIK `...061768` and deletes id 63 with CIK `...054420`. The task log records that both rows were empty and that `...061768` is the active 13F-HR filer while `...054420` is dormant pre-2002 at `docs/tasks/2026-05-21_dedup-duplicate-managers.md:21-26`.

The script encodes that choice as `(63, 85, "Baupost Group")` at `backend/scripts/dedup_managers.py:35-40`. This is the right decision because, with both rows empty, keeping the active SEC filer CIK is the only row choice that preserves future ingestion correctness.

## C. Root-Cause Fix - Mandatory

### C6. Seed-file repoint

Verdict: **PASS**

`seed_confirmed_managers` matches by CIK first, then falls back to `dataroma_code`, at `backend/app/services/edgar_ingestion.py:102-110`. If it finds an existing row, it updates that row instead of creating a new one at `backend/app/services/edgar_ingestion.py:112-121`; creation only happens when neither lookup finds an existing row at `backend/app/services/edgar_ingestion.py:122-132`.

The three previously bad seed entries now point to the canonical surviving CIKs/codes:

- Akre: `AC`, CIK `0001112520` at `backend/app/services/seed_data/confirmed_managers.json:14-19`
- Himalaya: `HC`, CIK `0001709323` at `backend/app/services/seed_data/confirmed_managers.json:32-37`
- Abrams: `ABC`, CIK `0001358706` at `backend/app/services/seed_data/confirmed_managers.json:38-43`

Those CIKs match the surviving rows documented in the task log (`...112520`, `...709323`, `...358706`) at `docs/tasks/2026-05-21_dedup-duplicate-managers.md:21-26`, so a future seed run will update the survivor by CIK instead of creating a duplicate. The task log also records the author's re-seed simulation result of 20 update / 0 create at `docs/tasks/2026-05-21_dedup-duplicate-managers.md:64-68` and `docs/tasks/2026-05-21_dedup-duplicate-managers.md:73-78`.

### C7. BAUP unchanged

Verdict: **PASS**

The BAUP seed entry remains `BAUP`, legal name `BAUPOST GROUP LLC /MA`, CIK `0001061768` at `backend/app/services/seed_data/confirmed_managers.json:44-49`. That matches the kept Baupost row id 85 documented in `docs/tasks/2026-05-21_dedup-duplicate-managers.md:21-26`, so no seed change was needed.

## D. Dedup Script

### D8. Script behavior and CI isolation

Verdict: **PASS**

The script is standalone, guarded by `if __name__ == "__main__"` at `backend/scripts/dedup_managers.py:108-109`, and its filename does not match the test collector pattern. The hard-coded delete/keep pairs are explicit at `backend/scripts/dedup_managers.py:34-40`, dry-run is default at `backend/scripts/dedup_managers.py:57-59` and `backend/scripts/dedup_managers.py:88-90`, and writes require `--apply`. Delete order is audit rows before manager rows at `backend/scripts/dedup_managers.py:96-100`.

## E. Scope / Completeness

### E9. Every duplicate found

Verdict: **PASS**

The task log records that a full prod scan found exactly four duplicate pairs and that the other two seed-created rows, Daily Journal id 82 and Bridgewater id 86, are genuinely new managers at `docs/tasks/2026-05-21_dedup-duplicate-managers.md:15-17`.

I also re-ran the prompt's read-only prod check. Result:

```text
managers: 82 (expect 82)
deleted ids present: []
remaining exact-name dup groups: {}
```

That confirms the current local prod state has the expected manager count, none of ids 63/81/83/84 remain, and no exact-name duplicate manager groups remain.

## F. Deferred

### F10. Backlog update

Verdict: **PASS**

`docs/BACKLOG.md` removes the "Duplicate institution managers (same firm, two CIKs)" entry and updates the manager_type human-review entry from a hard 86-manager statement to "all managers in prod - 86 at the time, now 82 after the duplicate-manager dedup." Evidence: `git diff main...HEAD -- docs/BACKLOG.md` shows the count update and removal at `docs/BACKLOG.md` around the manager_type backlog section.

## Verification Run

Ran:

```text
docker exec -i valuepilot-prod-api-1 python - <<'PY'
...
PY
```

Result:

```text
managers: 82 (expect 82)
deleted ids present: []
remaining exact-name dup groups: {}
```

Ran:

```text
docker compose exec -T api pytest -q
```

Result:

```text
902 passed, 3 warnings in 53.54s
```

The warnings are existing SQLAlchemy `Query.get()` legacy warnings in `edgar_ingestion.py` / related tests and are unrelated to this PR.
