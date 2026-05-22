# Review prompt — Dedup duplicate institution managers

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the task log
`docs/tasks/2026-05-21_dedup-duplicate-managers.md` and the diff on branch.

---

## Reviewer brief

You are reviewing **PR #89**, branch `claude/dedup-managers`. It **hard-deletes
4 duplicate `institution_managers` rows from the production database** and fixes
the seed file that created them.

The prod write **has already happened** (a user-authorized operational step —
the user explicitly chose hard delete over a soft `status='ignored'` retire).
You cannot block it; you *can* (a) confirm the delete was safe and lost nothing
of value, (b) confirm the right row of each pair was kept, (c) confirm the
root-cause fix actually prevents re-duplication.

### What changed and why

- Four firms each existed as **two** `institution_managers` rows under different
  CIKs. The duplicate of each pair was created `2026-05-20` by the
  `seed-confirmed-managers` run: `seed_confirmed_managers` matches a seed entry
  to an existing manager by **CIK first, then `dataroma_code`**, and for these
  four firms the seed entry's CIK *and* code both differed from the existing
  Dataroma-sourced row — so it created a new row.
- The PR deletes the 4 duplicates and repoints the 3 wrong seed entries.

### Files in scope

- `backend/scripts/dedup_managers.py` — new: pre-flight FK check + transactional
  hard delete; dry-run by default.
- `backend/app/services/seed_data/confirmed_managers.json` — 3 entries repointed.
- `docs/tasks/2026-05-21_dedup-duplicate-managers.md`, `docs/BACKLOG.md`.

### Baseline

`git diff main...HEAD`. The prod DB is local — `valuepilot-prod-api-1`.

## Answer every question below with a verdict (PASS / FAIL / advisory) + evidence

### A. Delete safety — MANDATORY

1. **FK coverage.** `dedup_managers.py::_deps()` checks 7 FK tables — filings,
   holdings, ownership_changes, cik_review_events, Oracle's Lens score
   components, quality_findings, child managers (`parent_manager_id`) — and
   separately counts `institution_manager_type_review_events`. Grep
   `ForeignKey("institution_managers` across `backend/app/models/` and confirm
   those are **every** FK reference into `institution_managers.id`. A missed
   table would mean either an orphaned row or a delete that should have failed.
2. **Abort-on-block, transactional.** Confirm the script aborts with no write
   if any delete target carries an unexpected dependent row, and that the
   delete (audit rows first, then manager rows) is one committed transaction —
   so a surprise FK rolls the whole thing back.
3. **What was destroyed.** Each delete removed the manager row plus its single
   `institution_manager_type_review_events` row (a machine first-pass
   classification from the 2026-05-21 run). Confirm this is acceptable:
   (a) the user explicitly chose hard delete over soft-retire; (b) the lost
   audit row classified a phantom manager that should never have existed;
   (c) nothing else was lost — the delete targets had zero filings / holdings /
   scores.

### B. Keep / delete correctness — MANDATORY

4. **Abrams / Akre / Himalaya.** Kept ids 18 / 15 / 46 (the rows with ingested
   13F filings), deleted the empty seed-created twins 84 / 81 / 83. Confirm the
   kept rows genuinely hold the filings/holdings and the deleted ones were
   empty.
5. **Baupost — the non-obvious call.** Kept id 85 (the `2026-05-20`
   seed-created row, CIK `…061768` `/MA`), deleted id 63 (the `2026-05-08`
   *original*, CIK `…054420` `/ADV`) — the opposite of the other three. Both
   Baupost rows were empty. The rationale: SEC shows `…061768` is the active
   13F-HR filer (filings through 2025) and `…054420` is a dormant pre-2002 CIK.
   Confirm keeping the active-CIK row is the right call.

### C. Root-cause fix — MANDATORY

6. **The seed-file repoint.** `confirmed_managers.json` — the Abrams / Akre /
   Himalaya entries are repointed to the canonical CIK / `dataroma_code` /
   `legal_name`. Trace `seed_confirmed_managers`
   (`backend/app/services/edgar_ingestion.py`): it matches CIK-first. Confirm
   the 3 new CIKs (`…358706`, `…112520`, `…709323`) equal the surviving rows'
   CIKs, so a re-run *updates* them instead of creating duplicates. The author's
   re-seed simulation reported 20 update / 0 create.
7. Confirm the `BAUP` entry was correctly left unchanged — its CIK `…061768`
   already equals the kept Baupost row (id 85).

### D. Dedup script

8. Review `backend/scripts/dedup_managers.py` — dry-run default / `--apply` to
   write, the hard-coded `PAIRS`, the delete order (audit rows before manager
   rows). Confirm it is standalone (not imported by the app or tests; name does
   not match `test_*`), so CI is unaffected. `pytest -q` was green (902).

### E. Scope / completeness

9. Confirm the dedup found **every** duplicate, not just 4 of more. The author
   ran a name-grouping over all 86 managers + listed the 6 rows the seed run
   created — 4 duplicates plus Daily Journal (id 82) and Bridgewater (id 86),
   which are genuinely new managers, not duplicates. Re-run the scan if in
   doubt.

### F. Deferred

10. Confirm `docs/BACKLOG.md` — the "Duplicate institution managers" entry is
    removed, and the manager_type human-review entry's count is updated
    (86 → 82).

## Verification

The prod stack runs locally. Re-check the result:

```
docker exec -i valuepilot-prod-api-1 python - <<'PY'
from collections import defaultdict
from app.core.db import SessionLocal
from app.models.institutions import InstitutionManager
s = SessionLocal()
mgrs = s.query(InstitutionManager).all()
print("managers:", len(mgrs), "(expect 82)")
print("deleted ids present:", [i for i in (63,81,83,84) if s.get(InstitutionManager,i)])
norm = lambda x: ''.join(c for c in (x or '').lower() if c.isalnum())
g = defaultdict(list)
for m in mgrs: g[norm(m.canonical_name)].append(m.id)
print("remaining exact-name dup groups:", {k:v for k,v in g.items() if len(v)>1})
s.close()
PY
```

`pytest -q` for CI sanity.

## Pass bar

Approve only if: **A1–A3** confirm the delete was FK-complete, transactional,
and lost nothing beyond the user-accepted machine audit rows; **B4–B5** confirm
the right row of every pair survived (especially Baupost); **C6–C7** confirm the
seed fix genuinely closes the root cause (re-seed = update, not create);
**D/E/F** findings recorded. The bar is: "the 4 duplicates are gone, prod is
consistent at 82 managers, nothing of value was lost, and the seed file can no
longer re-create them."
