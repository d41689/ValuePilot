# 2026-05-20 — Seed 10 confirmed-manager CIKs

## Goal / Acceptance Criteria

- Add the 10 candidate managers (status `candidate`/`seeded`, no CIK) to the
  confirmed-manager seed list with their SEC EDGAR CIKs, so re-seeding promotes
  them to `confirmed` with a CIK.
- Acceptance: `confirmed_managers.json` valid; canonical CI green; after the
  deploy, `seed-confirmed-managers` run on prod sets the 10 CIKs.

This is item #10 of `docs/tasks/2026-05-20_admin-13f-ops-audit.md`.

## Background

The 10 candidate managers were seeded from Dataroma (`bootstrap_whitelist`)
with names only — no CIK. `bootstrap_whitelist` never sets CIKs; the mechanism
that does is `seed_confirmed_managers()` (in `edgar_ingestion.py`), which reads
`backend/app/services/seed_data/confirmed_managers.json` and matches by CIK
then `dataroma_code`, setting `cik` + `match_status='confirmed'`.

## CIK research

CIKs looked up on SEC EDGAR (`browse-edgar`, filtered to `type=13F-HR`); each is
a current, active 13F-HR filer (most recent filing 2026-05):

| dataroma_code | manager | EDGAR filer | CIK |
|---|---|---|---|
| HA | Bill Nygren - Oakmark Funds | HARRIS ASSOCIATES L P | 0000813917 |
| DAV | Christopher Davis - Davis Advisors | DAVIS SELECTED ADVISERS | 0001036325 |
| DAC | Dodge & Cox Funds | DODGE & COX | 0000200217 |
| HCMAX | Hillman Value Fund | Hillman Capital Management, Inc. | 0001314620 |
| OA | Leon Cooperman | COOPERMAN LEON G | 0000898382 |
| MPF | Mairs & Power Funds | MAIRS & POWER INC | 0001070134 |
| PI | Mohnish Pabrai - Pabrai Investments | Dalal Street, LLC | 0001549575 |
| RVC | Robert Vinall - RV Capital | RV Capital AG | 0001766596 |
| RC | Ruane Cunniff LP | Ruane, Cunniff & Goldfarb L.P. | 0001720792 |
| T | Torray Funds | TORRAY INVESTMENT PARTNERS LLC | 0000098758 |

Notes: RV Capital files as the "AG" entity (the manager record said "GmbH" —
an entity-form change). Ruane Cunniff uses the **L.P.** CIK 0001720792 (active
through 2026-05) — not the older Inc CIK 0000728014 (dormant since 2018).

## Files changed

- `backend/app/services/seed_data/confirmed_managers.json` — 10 → 20 entries.

## Apply step (post-deploy, prod)

`seed_confirmed_managers()` has no admin-UI job — it is CLI only. After this PR
merges and deploys, run in the prod container (user-authorised):

    docker exec valuepilot-prod-api-1 python -m app.cli.edgar seed-confirmed-managers

It matches each entry's `dataroma_code` to the existing candidate row and sets
`cik` + `match_status='confirmed'`.

## Test plan

- `docker compose run --rm api pytest -q` — full backend suite (no test loads
  this JSON; the change is additive seed data).
- Frontend is untouched on this branch; GitHub CI runs the full canonical
  sequence on the PR regardless.

## Sign-off trail

- 2026-05-20: 10 CIKs researched on EDGAR and added to the seed list.
