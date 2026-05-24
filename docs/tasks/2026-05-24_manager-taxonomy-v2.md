# 2026-05-24 — Manager taxonomy V2 (two-layer + metadata)

## Goal

Replace the flat `manager_type` enum with a **two-layer label + multi-dimensional
metadata** taxonomy that lets Oracle's Lens speak in *value-investor* language
(deep-value vs quality-compounder vs growth-long-short vs activist vs
permanent-capital vs small-cap-sleuth), and **seed all 82 confirmed superinvestors
with these classifications via the existing whitelist JSON** so a fresh dev
environment comes up classified out of the box.

Background: PO acceptance review (this session) found that the production
`manager_type` taxonomy puts Tiger Cubs (Tiger Global, Lone Pine, Viking,
Maverick, Durable) into `long_term_fundamental`, which has the same signal
weight (1.00) as Berkshire and Tweedy Browne. That pollutes the "value
consensus" signal in Oracle's Lens with growth/momentum holdings. We also
have no way to filter "deep value vs quality compounder" or "small-cap value
sleuths" — both are first-class workflows for a value investor.

## Acceptance criteria

1. `institution_managers` carries seven new columns:
   - `style_primary` (NOT NULL, default `unknown`) — the primary investment DNA
   - `capital_structure` (NOT NULL, default `unknown`) — LP / permanent / mutual / endowment
   - `market_cap_focus` (nullable) — micro / small / mid / large / mega / all
   - `geo_focus` (nullable) — us / global / em / europe / asia
   - `historical_turnover` (nullable) — low / med / high
   - `position_concentration_top10_pct` (nullable, Numeric(6,2))
   - `ideology_tags` (nullable, JSONB list)
2. `manager_type` (the legacy column) is **kept** and **auto-derived from
   `style_primary`** by a deterministic mapping (single source of truth in
   `app/services/oracles_lens/manager_style.py`). Oracle's Lens signal weights
   continue to work unchanged.
3. The mapping does the value-investor-correct thing for the 7 worst current
   misclassifications, in particular:
   - Tiger Global / Lone Pine / Viking / Maverick / Durable Capital →
     `style_primary=growth_long_short` → legacy `manager_type=high_turnover`
     (weight 0.30, was 1.00).
   - TCI Fund Management → `style_primary=activist` (was value_concentrated).
   - Berkshire / Vulcan → `style_primary=value_concentrated`.
4. `backend/app/services/seed_data/confirmed_managers.json` is expanded from
   the current 20 entries to **all 82 superinvestors currently confirmed on
   production**, each enriched with the new fields plus a one-line
   `classification_rationale`.
5. `seed_confirmed_managers()` reads the new fields, derives legacy
   `manager_type`, and upserts all columns. Idempotent: re-running does not
   create duplicates or change values that haven't changed.
6. Unit tests (test-first):
   - Style → legacy `manager_type` mapping is exhaustive over `STYLE_PRIMARY`.
   - Tiger Cubs assertion: the five named managers all resolve to legacy
     `high_turnover` after seeding.
   - Seed JSON contract: every entry has the required new fields and CIK.
   - `seed_confirmed_managers()` writes all eight columns and is idempotent.
7. Canonical CI commands green in-container.

## Scope

**In:** schema migration, model columns + validators, mapping helper, seed
JSON expansion + enrichment, `seed_confirmed_managers()` update, backend
unit tests.

**Out (deferred, tracked in `docs/BACKLOG.md` if applicable):**
- Frontend dialog UI changes to surface the new fields (the existing
  `manager_type` dropdown keeps working because legacy column is auto-derived).
- Oracle's Lens consuming `style_primary` directly (next milestone — for now
  it keeps reading legacy `manager_type`, which is derived correctly).
- Audit-event coverage for the new fields (admin edits via existing UI continue
  to write `institution_manager_type_review_events` rows for `manager_type`
  only; richer audit events are a follow-up).
- Behavior-derived `style_primary` (the V1 `derive_manager_signal_profile` in
  `manager_signal.py` keeps emitting legacy `manager_type` only).

## Critical invariants — preserved

- `manager_type` stays a `String(40)` with the eight-value `MANAGER_TYPES`
  enum and its `@validates` check. Oracle's Lens weight table is not changed.
- All schema changes go through a single Alembic migration with a working
  downgrade.
- Seeding remains idempotent (per the existing upsert contract in
  `seed_confirmed_managers()`).
- New columns added with `server_default` so existing rows backfill cleanly.

## Files to change

| File | Change |
|---|---|
| `backend/alembic/versions/20260524120000-manager-taxonomy-v2.py` | NEW migration: add 7 columns, indexes for `style_primary` + `capital_structure` |
| `backend/app/models/institutions.py` | Add `STYLE_PRIMARY`, `CAPITAL_STRUCTURE`, `MARKET_CAP_FOCUS`, `TURNOVER_BUCKETS`, `GEO_FOCUS` constants + columns + validators |
| `backend/app/services/oracles_lens/manager_style.py` | NEW: `STYLE_PRIMARY_TO_LEGACY` map + `derive_legacy_manager_type()` helper |
| `backend/app/services/seed_data/confirmed_managers.json` | Expand 20 → 82, enrich every entry with new fields + rationale |
| `backend/app/services/edgar_ingestion.py` | `seed_confirmed_managers()` reads new fields, derives legacy, upserts |
| `backend/tests/unit/test_13f_manager_taxonomy_v2.py` | NEW test file (see Test plan) |

## Test plan

In-container, per AGENTS.md "Run the exact canonical CI commands":

```
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

Targeted iteration:
```
docker compose exec -T api pytest -q backend/tests/unit/test_13f_manager_taxonomy_v2.py
docker compose exec -T api pytest -q backend/tests/unit/test_13f_mvp4_manager_taxonomy.py
docker compose exec -T api pytest -q backend/tests/unit/test_13f_mvp5_05_manager_type_editor.py
```

## Decisions / gotchas

- **Why auto-derive legacy `manager_type` from `style_primary`?** Avoids a
  cross-cutting refactor of Oracle's Lens, admin endpoints, audit table,
  frontend dialog — all of which currently read the legacy column. New
  consumers (filters, screeners, "value-only" universe) will read
  `style_primary` directly. Legacy column becomes a derived view of the
  primary truth, written by the model layer.
- **Why a single migration instead of seven?** All seven columns are added to
  one table and form one logical contract change. Reviewers should see them
  together.
- **Why not extend `institution_manager_type_review_events` to cover the new
  fields?** Out of scope: seeding is the canonical write path; admin overrides
  for the new fields would require frontend UI which is also out of scope.
  Tracked as a follow-up.
- **`style_primary=endowment_passive` for Gates Foundation Trust** — it doesn't
  actively pick; it holds what Buffett donated. Mapping to legacy `index_like`
  (weight 0.10) so its signals carry near-zero weight, which matches the
  empirical reality that its trades are gifting timing, not investment views.
