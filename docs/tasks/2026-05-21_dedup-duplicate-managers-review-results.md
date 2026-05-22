# Review results — Dedup duplicate institution managers

**PR:** #89, branch `claude/dedup-managers`  
**Reviewer:** Claude Sonnet 4.6 (agent review)  
**Date:** 2026-05-21  
**Prompt:** `docs/tasks/2026-05-21_dedup-duplicate-managers-review-prompts.md`

---

## Overall verdict: **APPROVE**

The hard delete was safe: FK coverage is complete (all 8 referencing tables
checked), the operation was transactional, and nothing of value was lost beyond
the user-accepted machine audit rows for phantom managers. The right row of
every pair survived. The seed fix closes the root cause — a future re-seed
resolves to update, not create. All mandatory gates A1–A3, B4–B5, C6–C7 pass.

---

## A. Delete safety

### A1. FK coverage — **PASS**

Evidence: `backend/scripts/dedup_managers.py:43–54`; grep of `backend/app/models/`

Complete grep of `ForeignKey("institution_managers` across all model files reveals
exactly **8** FK references into `institution_managers.id`:

| Table | Model class | File:line | Covered by |
|---|---|---|---|
| `filings_13f` | `Filing13F.manager_id` | `institutions.py:306` | `_deps()` → `"filings"` |
| `holdings_13f` | `Holding13F.manager_id` | `institutions.py:543` | `_deps()` → `"holdings"` |
| `ownership_changes` | `OwnershipChange13F.manager_id` | `institutions.py:605` | `_deps()` → `"ownership_changes"` |
| `institution_manager_cik_review_events` | `InstitutionManagerCikReviewEvent.manager_id` | `institutions.py:178` | `_deps()` → `"cik_review_events"` |
| `institution_manager_type_review_events` | `InstitutionManagerTypeReviewEvent.manager_id` | `institutions.py:208` | **explicitly counted & deleted** (not in `_deps()`) |
| `institution_managers` (self) | `InstitutionManager.parent_manager_id` | `institutions.py:99` | `_deps()` → `"children"` |
| `oracles_lens_score_components` | `OraclesLensScoreComponent.manager_id` | `oracles_lens.py:155` | `_deps()` → `"score_components"` |
| `quality_findings_13f` | `QualityFinding13F.manager_id` | `institutions.py:778` | `_deps()` → `"quality_findings"` |

`_deps()` blocks on 7 tables; `institution_manager_type_review_events` is the
8th and is handled separately — explicitly counted (`dedup_managers.py:73–75`)
and deleted before the manager row (`lines 96–98`). No FK table is missed. ✓

No FK references to `institution_managers` exist outside `institutions.py` and
`oracles_lens.py`. The grep against `backend/app/models/` was exhaustive. ✓

### A2. Abort-on-block, transactional — **PASS**

Evidence: `dedup_managers.py:61–103`

**Pre-flight abort:** `_deps()` is called for every delete target before any
write (lines 61–83). Any non-zero count in those 7 tables sets `blocked = True`
(line 78); after checking all pairs, `if blocked: sys.exit(1)` (line 87) aborts
with no write. ✓

**Single transaction:** The apply loop (lines 92–101) calls
`session.commit()` exactly **once**, after all four deletes complete (line 102).
The loop does not commit per-row. If a surprise FK violation fires mid-loop
(e.g. a row created between the pre-flight check and the apply), the DB rolls
back the entire batch. ✓

**Delete order:** Audit rows (`InstitutionManagerTypeReviewEvent`) are deleted
before the manager row (lines 96–99), respecting the FK constraint. ✓

### A3. What was destroyed — **PASS**

Evidence: task doc lines 25–38; `dedup_managers.py:73–75, 96–98`

Each delete removed:
- 1 `institution_managers` row (the duplicate, with no data of value)
- 1 `institution_manager_type_review_events` row (the machine first-pass
  classification written 2026-05-21)

**Acceptability of the lost audit row:**
1. User explicitly chose hard delete over `status='ignored'` soft-retire. ✓
2. The audit row classified a phantom manager that never should have existed —
   its machine provenance is intact in the surviving row of each pair. ✓
3. No other data was lost: the task doc and `_deps()` pre-flight confirm **zero
   filings, zero holdings, zero ownership changes, zero CIK review events, zero
   score components, zero quality findings, zero child managers** for all four
   delete targets. ✓

---

## B. Keep / delete correctness

### B4. Abrams / Akre / Himalaya — **PASS**

Evidence: task doc lines 22–26

| Firm | Keep (id) | CIK | Data | Delete (id) | CIK | Data |
|---|---|---|---|---|---|---|
| Abrams Capital | 18 | `…358706` | 4 filings / 49 holdings | 84 | `…229555` | empty |
| Akre Capital | 15 | `…112520` | 4 filings / 76 holdings | 81 | `…115850` | empty |
| Himalaya Capital | 46 | `…709323` | 5 filings / 50 holdings | 83 | `…402474` | empty |

In every case the row with 13F data is kept and the empty seed-created twin is
deleted. This is unambiguous: the data-bearing row is the canonical one. ✓

### B5. Baupost — the non-obvious call — **PASS**

Evidence: task doc lines 26, 52–57

Both Baupost rows were empty (no filings or holdings on either). The choice
required reasoning about which CIK represents the active filer:

- id 63 (CIK `…054420 /ADV`): original Dataroma-sourced row, dormant pre-2002
  CIK, last SEC filing before 2002.
- id 85 (CIK `…061768 /MA`): seed-created 2026-05-20, the **active 13F-HR
  filer** with filings through 2025 per the SEC.

Keeping the active-CIK row (id 85) is the correct call. Future EDGAR ingestion
uses the SEC-issued CIK to pull filings; anchoring the manager to a dormant CIK
(`…054420`) would mean Baupost's current filings can never be ingested. ✓

The task doc references SEC records to confirm the `…061768` status. The
rationale is sound and not contradicted by any evidence in the codebase.

---

## C. Root-cause fix

### C6. The seed-file repoint — **PASS**

Evidence: `confirmed_managers.json` (queried); `edgar_ingestion.py:96–135`

The three repointed entries in `confirmed_managers.json`:

| Entry | New CIK | Matches surviving row |
|---|---|---|
| Akre (`AC`) | `0001112520` | id 15 (`…112520`) ✓ |
| Himalaya (`HC`) | `0001709323` | id 46 (`…709323`) ✓ |
| Abrams (`ABC`) | `0001358706` | id 18 (`…358706`) ✓ |

`seed_confirmed_managers` (lines 102–110 of `edgar_ingestion.py`) matches
CIK-first:

```python
existing = db.query(InstitutionManager).filter_by(cik=cik).one_or_none()
if existing is None and dataroma_code:
    existing = db.query(InstitutionManager).filter_by(dataroma_code=dataroma_code).one_or_none()
```

With the repointed CIKs, the CIK-first branch (`filter_by(cik=cik)`) finds the
surviving row directly — no fallback to `dataroma_code` needed. The match
resolves to `existing is not None` → UPDATE path (line 112–121) → **no new row
created**. The author's re-seed simulation reported **20 update / 0 create**,
confirming the root cause is closed. ✓

### C7. `BAUP` entry correctly left unchanged — **PASS**

Evidence: `confirmed_managers.json` (queried)

The `BAUP` entry in the seed file carries `cik: '0001061768'` — the CIK of the
kept Baupost row (id 85). A re-seed would match id 85 by CIK and UPDATE it. No
further change was needed; the entry was left as-is. ✓

---

## D. Dedup script

### D8. Script quality — **PASS**

Evidence: `backend/scripts/dedup_managers.py` (full file)

- **Dry-run default:** `apply = "--apply" in sys.argv` (line 58); without
  `--apply`, the script prints the pre-flight results and exits at line 89.
  `--apply` must be passed explicitly. ✓
- **Hard-coded `PAIRS`:** The four `(delete_id, keep_id, firm)` tuples are
  explicit constants (lines 35–40) — no dynamic query that could accidentally
  target the wrong row. ✓
- **Delete order:** `InstitutionManagerTypeReviewEvent` deleted before
  `InstitutionManager` (lines 96–99), respecting the FK. ✓
- **Idempotent guard:** `if session.get(InstitutionManager, del_id) is None: continue`
  (line 94) — a second run skips already-deleted rows. ✓
- **Standalone:** File name `dedup_managers.py` does not match `test_*`; not
  imported by the app or any test. `pytest -q` is unaffected. ✓

---

## E. Scope / completeness

### E9. All duplicates found — **PASS**

Evidence: task doc lines 15–17

The author ran a full prod scan over all 86 managers. Of the 6 rows created by
the 2026-05-20 seed run:

- **Abrams id 84, Akre id 81, Himalaya id 83** — confirmed duplicates
  (deleted). ✓
- **Baupost id 85** — confirmed duplicate (deleted). ✓
- **Daily Journal id 82** — genuinely new manager (Charlie Munger's Daily
  Journal Corp); not a duplicate of any existing row. ✓
- **Bridgewater id 86** — genuinely new manager; not a duplicate. ✓

The task doc states "A full prod scan confirmed exactly 4 duplicate pairs." The
scan method (name-grouping over all managers) is described and reproducible via
the verification script in the review prompt. No evidence of additional
duplicates beyond these four.

---

## F. Deferred

### F10. BACKLOG hygiene — **PASS**

Evidence: `docs/BACKLOG.md` (grep results)

1. **"Duplicate institution managers" entry removed.** A grep for "Duplicate
   institution managers", "Abrams", "Akre", "Himalaya", and "Baupost dup"
   returns no match — the entry is gone. ✓

2. **Human-review entry count updated 86 → 82.** The surviving human-review
   entry now reads:

   > "…applied to all managers in prod — 86 at the time, now **82 after the
   > duplicate-manager dedup**…"

   The count is accurate and the update acknowledges this PR. ✓

---

## Summary

No advisory items. All gates are clean.

| Gate | Verdict |
|---|---|
| A1 — FK coverage complete | PASS |
| A2 — Abort-on-block, single transaction | PASS |
| A3 — Nothing of value destroyed | PASS |
| B4 — Abrams/Akre/Himalaya: data-bearing row kept | PASS |
| B5 — Baupost: active-CIK row kept | PASS |
| C6 — Seed repoint closes the root cause | PASS |
| C7 — BAUP entry correctly left unchanged | PASS |
| D8 — Script: dry-run default, safe, standalone | PASS |
| E9 — All duplicates found, none missed | PASS |
| F10 — BACKLOG updated correctly | PASS |
