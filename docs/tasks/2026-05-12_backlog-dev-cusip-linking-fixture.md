# Backlog: Dev Environment CUSIP Linking / Linked-CUSIP Fixture

## Status

**Non-blocking backlog.** Not on the MVP5 critical path; filed
so MVP5-03 Phase 3 sign-off has a reproducible local path
when needed. Track E (cross-track engineering debt) per
`docs/tasks/2026-05-12_post-mvp4-roadmap.md`.

Triggering observation: 2026-05-12 MVP5-03 Phase 1 utility
validation revealed that dev DB has 4022 holdings with
`cusip_mapping_status="pending_mapping"` and
`holding_attribution_status=None`, meaning:

- Persisted scoring writes zero `oracles_lens_signals` rows in
  dev.
- Comparison utility cannot produce real legacy-vs-persisted
  ranking data on dev.
- PO sign-off for Phase 3 server-default flip requires
  staging/prod.

This is not blocking GA — the MVP5-03 Phase 3 path is
explicitly staging/prod-only — but it does mean any future
engineer wanting to **reproduce the Phase 1 → Phase 3 flow
locally** has to do so against staging/prod data, not dev.

## Goal / Acceptance Criteria

Make Oracle's Lens scoring reproducible in dev for the
purpose of formula reconciliation observation, comparison-
utility verification, and any future scoring-pipeline change.

Acceptance criteria (one of the following two paths, PO
choice):

### Path A — Run the real OpenFIGI pipeline in dev

- Document the steps for running the CUSIP enrichment job
  against dev. Likely already exists; this ticket is mostly
  about confirming the path still works and recording the
  invocation.
- After running, dev should have a non-trivial fraction of
  holdings with `cusip_mapping_status="linked"` so
  `compute_signal_weighted_scores` produces some rows.
- Requires an OpenFIGI API key (or equivalent) configured in
  dev `.env`. If the key is unavailable, fall back to Path B.

### Path B — Ship a dev / CI fixture seeder

- A pytest fixture or admin script that seeds the dev DB
  with a small synthetic universe shaped like production:
  - 5-10 stocks with `stock_id`s linked.
  - 30-50 managers across the canonical 8-value taxonomy.
  - 200-500 holdings with
    `cusip_mapping_status="linked"` and
    `holding_attribution_status="direct"`.
- The seeder should be idempotent and runnable via a
  Makefile target / docker compose recipe.
- After seeding, `compute_signal_weighted_scores` should
  produce ≥ 1 `oracles_lens_signals` row per quarter, and the
  Phase 1 comparison utility should return a non-empty
  `items` array.

## Scope In

- Either documenting + invoking the real OpenFIGI pipeline
  in dev, or shipping a synthetic-fixture seeder. Engineer's
  choice — both are acceptable acceptance paths.
- A short runbook in this task file recording the chosen
  approach so it doesn't have to be re-discovered.

## Scope Out

- Any change to production CUSIP linking.
- Any change to the Phase 1 comparison utility itself.
- Any change to MVP5-03 Phase 3 / 4 trackers — those are
  still gated on real staging/prod data even if dev becomes
  reproducible.
- New scoring features, new admin endpoints, new schema.

## PRD / Decision References

- `docs/tasks/2026-05-12_13f-mvp5-end-to-end-verification.md`
  — MVP5-07 Conditional GA Gate section recording the dev
  validation outcome.
- `docs/tasks/2026-05-12_mvp5-03-formula-reconciliation.md`
  — Phase 1 Validation Outcome.
- `docs/tasks/2026-05-12_post-mvp4-roadmap.md` Track E
  engineering debt entries.

## Files Expected To Change

- `backend/tests/fixtures/` or similar — new seeder script
  (Path B) OR runbook documentation (Path A).
- `docker-compose.yml` / `Makefile` — new target (Path B).
- This task file.

## Priority

**Low / non-blocking.** Open when:

- A future MVP wants to iterate on the scoring formula and
  needs a fast local feedback loop, OR
- A future engineer is trying to reproduce a Phase 3 sign-off
  divergence flagged in production and needs a sandbox.

## Progress Notes

- 2026-05-12: Filed per PO direction after the MVP5-03 Phase 1
  validation outcome documented the dev-DB data gap. Not on
  the MVP5 critical path; revisit when a future use case
  drives demand.
