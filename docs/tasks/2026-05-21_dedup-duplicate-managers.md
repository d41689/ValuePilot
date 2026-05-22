# 2026-05-21 — Dedup duplicate institution managers

Resolves the `docs/BACKLOG.md` item **"Duplicate institution managers (same
firm, two CIKs)"** (low, found 2026-05-21 during the manager_type run).

## The problem

Four firms existed as **two** `institution_managers` rows each, under different
CIKs. The duplicates (one per pair) were created `2026-05-20 22:04` by the
`seed-confirmed-managers` run: `seed_confirmed_managers` matches a seed entry to
an existing manager by **CIK first, then `dataroma_code`** — and for these four
firms the seed entry's CIK *and* code both differed from the existing
Dataroma-sourced row, so the seeder created a new row instead of updating.

A full prod scan confirmed exactly 4 duplicate pairs (the other 2 of the 6
seed-created rows — Daily Journal id 82, Bridgewater id 86 — are genuinely new
managers, not duplicates).

## Resolution — hard delete (user-authorized)

| Firm | Keep | Delete | Why keep that one |
|---|---|---|---|
| Abrams Capital | id 18 (CIK …358706) | id 84 (CIK …229555) | id 18 has 4 filings / 49 holdings |
| Akre Capital | id 15 (CIK …112520) | id 81 (CIK …115850) | id 15 has 4 filings / 76 holdings |
| Himalaya Capital | id 46 (CIK …709323) | id 83 (CIK …402474) | id 46 has 5 filings / 50 holdings |
| Baupost Group | id 85 (CIK …061768 `/MA`) | id 63 (CIK …054420 `/ADV`) | both rows empty; SEC shows `…061768` is the active 13F-HR filer (filings through 2025), `…054420` is a dormant pre-2002 CIK |

Each deleted row carries **no** filings / holdings / ownership changes / CIK
review events / Oracle's Lens score components / quality findings / child
managers — verified against all 8 FK tables. The only dependent row is the one
`institution_manager_type_review_events` row written by the 2026-05-21
classification pass; the dedup script deletes that audit row, then the manager,
both in one transaction.

The user chose hard delete over a soft retire (`status='ignored'`), accepting
that the duplicate's manager_type audit row is destroyed — acceptable here
because the row is a machine-written first-pass classification of a phantom
manager that should never have existed.

## Root-cause fix

`confirmed_managers.json` — the three offending entries (`AKRE`, `LI_LU`,
`ABRAMS`) are repointed to the **canonical** CIK / `dataroma_code` / `legal_name`
of the row that actually has the data. A re-run of `seed_confirmed_managers`
then matches by CIK and *updates* the canonical row instead of creating a
duplicate. The `BAUP` entry already carried the correct CIK (`…061768`, the
kept row) — left unchanged.

## Scope

**In:** delete the 4 duplicate rows + their audit rows; fix the 3 seed entries.
**Out:** the manager's CIK fields are not touched; no soft-retire path; no
broader fuzzy-dedup of the manager table (the scan found only these 4 pairs).

## Files

- `backend/scripts/dedup_managers.py` — new: pre-flight FK check + transactional
  hard delete; dry-run by default.
- `backend/app/services/seed_data/confirmed_managers.json` — 3 entries repointed.
- `docs/BACKLOG.md` — entry resolved.

## Verification

- Dry-run the dedup script (pre-flight FK check) before `--apply`.
- After apply: prod has 82 managers, ids 63/81/83/84 gone.
- Read-only re-seed check: every one of the 20 `confirmed_managers.json` entries
  resolves by CIK to exactly one surviving manager → a future
  `seed_confirmed_managers` run would update 20 / create 0.

## Sign-off trail

- 2026-05-21 — task opened; user authorized hard delete + root-cause fix.
- 2026-05-21 — applied. Dry-run pre-flight passed (all 4 targets carry only
  their 1 manager_type audit row); `--apply` deleted ids 63/81/83/84 + their
  audit rows. Verified on prod: **82 managers**, all 4 gone, the 4 kept rows
  intact. Re-seed simulation of the fixed `confirmed_managers.json`: **20
  update / 0 create** — the root cause is closed. `pytest -q` green; the new
  `dedup_managers.py` is standalone (not imported by the app or tests).
