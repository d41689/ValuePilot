# 13F MVP 6 Execution Plan — Admin Operations Console

## Status

**DRAFT — not yet opened.** This plan becomes active once
Pre-MVP6-02 (`docs/tasks/2026-05-12_pre-mvp6-02-admin-ia-split-plan.md`)
gets PO sign-off. Until then, treat this file as a preview of the
MVP6 task sequence; **do not start any MVP6 ticket yet**.

Authoritative source for the seven D1–D7 design decisions that
shape this plan is Pre-MVP6-02. This file is the execution-side
mirror.

## Goal

Decompose the current 3300-line `/admin/13f/page.tsx` into the eight
PRD §11.1 admin routes (Overview hub + 7 functional pages) so the
13F admin track is operationally usable. Theme: **Admin Operations
Console.** No new user-facing investor features in MVP6.

## Non-Goals

- **Track A2** Oracle's Lens Milestone 3 (quality / valuation
  overlay). Stays deferred per the Post-MVP4 roadmap.
- **Track D** Watchlist V1. Re-open after MVP6.
- **Track B** Pre-2023 historical backfill productionization.
  Still no investor demand signal.
- **Track C** Admin G1 (email) / G9 (external ticketing). Stays
  deferred.
- **MVP5-03 Phase 3** server-default flip + **Phase 4**
  `?persisted=0` retirement. Both still gated on staging/prod
  comparison + PO sign-off; out of MVP6 scope.
- Any new scoring formula, new backend service, new schema.
  MVP6 is a **frontend information-architecture** track; the
  backend API surface is already complete (PRD §11 verified
  end-to-end in MVP5-07).

## Task Sequence (locked by Pre-MVP6-02 D7)

Each row is one ticket. Each ticket follows the standard pattern:
task file → tests first → Docker-only verification → commit with
`Co-Authored-By: Claude Opus 4.7` footer → per-task verification
log appended.

| # | Title | Scope (one-line) | Depends |
| - | ----- | ---------------- | ------- |
| MVP6-01 | Overview Hub + Layout Shell | Extract shared Tier 2 (`AdminPageLayout` / `AdminEmptyState` / `AdminLoadingState` / `AdminErrorState` / dialog primitives) + Tier 3 (`useXQuery` hooks); `/admin/13f` becomes Overview-only with health summary + navigation cards. | — |
| MVP6-02 | Managers + Manager Detail | `/admin/13f/managers` (list + filters + bulk import) + `/admin/13f/managers/[id]` (CIK history + manager_type history + linked filings + backfill history). Flip MVP4-07b priority Card deep links from `#manager-row-{id}` anchor to the new route. | MVP6-01 |
| MVP6-03 | Daily Sync + No-index Calendar | `/admin/13f/sync` route. Sync-history table + retry action + no-index date CRUD UI. | MVP6-01 |
| MVP6-04 | Filings + Amendments | `/admin/13f/filings` route. Filings table with status / quarter / form_type filters; amendment resolve dialog; filing detail drawer or sub-route. | MVP6-01 |
| MVP6-05 | Holdings Coverage + CUSIP Workflow | `/admin/13f/holdings` route. Coverage summary + unresolved CUSIP queue + corporate-action confirm UI. | MVP6-01 |
| MVP6-06 | Jobs Page Hardening | `/admin/13f/jobs` route. Jobs table with PRD §11.3 filter dimensions; cancel + release-stale-lock + retry actions; worker status + EDGAR rate limit panel. | MVP6-01 |
| MVP6-07 | Readiness + Quality Findings | `/admin/13f/readiness` route. Readiness-level detail + blockers list + quality-finding drill-throughs + needs-validation queue. | MVP6-01, soft on MVP6-04 |
| MVP6-08 | Admin E2E Verification | Closing gate: every section's old in-page surface either fully moved or replaced by a navigation card; four-role review (Staff Engineer / SME / PO / Frontend-UX). | MVP6-01..07 |

Parallelism: MVP6-02..07 are mutually independent (each consumes
MVP6-01 only). Sequential execution is fine; parallel is fine if
the team has capacity. Only MVP6-07 has a soft dependency on
MVP6-04 for cross-page deep links — can ship earlier with the
links short-circuited.

## Per-Ticket Minimum V1 Capability (from Pre-MVP6-02 D4)

Each ticket ships the minimum operational shape, NOT a full
admin redesign. The Pre-MVP6-02 D4 mapping:

- **Managers**: list + filters + detail link + manager_type edit
  (already shipped by MVP5-05; just relocate) + CIK status.
- **Sync**: sync history + failed-sync retry + no-index calendar.
- **Filings**: filters + parse_status + amendment_status + detail
  link.
- **Holdings**: coverage summary + unresolved CUSIP queue.
- **Jobs**: job list + cancel / release-stale-lock.
- **Readiness**: blocker list + caveats + latest_usable_quarter.
- **Overview**: health summary + navigation cards.

## Verification Pattern

Each MVP6 ticket carries its own:

- Per-ticket Docker verification (`pytest -q` regression-baseline
  + frontend `lint` + `build` + `node --test lib/oraclesLens.test.js`).
- Manual probe of the new route with the dev seeder running
  (Pre-MVP6-01 produced 8 stocks + 32 managers + 252 holdings;
  each new page must render non-empty against this data).
- For destructive-action pages: at least one happy-path
  end-to-end test demonstrating the action persists +
  invalidates the relevant queries.

MVP6-08 (closing gate) follows the MVP3 / MVP4 / MVP5 end-to-end
pattern:

- Contract checklist mapping MVP6-01..07 to commits.
- Four-role review prompts in
  `docs/tasks/YYYY-MM-DD_13f-mvp6-review-prompts.md`.
- Scope-freeze tally confirming zero new backend / scoring
  changes (frontend-only milestone).
- Decision-gate verification for the Pre-MVP6-02 D1–D7
  decisions: each held against shipped code, no silent
  deviations.

## Post-MVP6 Decision Inputs

When MVP6-08 closes, the following candidates are ready for the
next decision gate (NOT committed yet, just queued):

1. **Track D Watchlist V1** — eligible to open since the admin
   surface is now operable.
2. **MVP5-03 Phase 3** server-default flip — still gated on
   staging/prod comparison + PO sign-off (no change).
3. **Track A2** Oracle's Lens Milestone 3 (quality + valuation
   overlay).
4. **Phase 4** `?persisted=0` retirement — still gated on
   Phase 3 + one observation cycle.
5. **Track C G1 + G9** admin email + external ticketing — only
   if production observation surfaces a Slack/Discord coverage
   gap.

None of these are committed; they are inputs to MVP7's decision
gate, not outputs of MVP6.

## Out-of-Scope Reminders

- No backend API additions in MVP6. If a new admin page wants
  a field the existing API doesn't expose, **stop** and decide
  whether that's a real PRD gap or a UX over-reach. The Post-MVP4
  roadmap's "Track E" engineering-debt items remain deferred
  during MVP6.
- No frontend lib additions outside `frontend/components/admin13f/`
  and `frontend/lib/admin13f/`. Keeps the blast radius isolated
  to the admin track.
- No CI changes. The dev seeder
  (`backend/scripts/seed_13f_dev_fixture.py`) stays a manual
  dev tool through MVP6; CI integration is a separate ticket.

## Open Until PO Sign-Off

- [ ] PO signs off on Pre-MVP6-02 D1–D7 decisions.
- [ ] PO authorizes MVP6 kickoff (i.e. MVP6-01 opens).
- [ ] This file flips from **DRAFT** to **active** when the
      above two close.
