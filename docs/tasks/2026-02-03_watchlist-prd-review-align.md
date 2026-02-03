# 2026-02-03 Watchlist PRD Review + Alignment (V1)

## Goal / Acceptance Criteria

- Review `docs/prd/watchlist/watchlist-v1.md` and align terminology/contracts with:
  - `docs/prd/value-pilot-prd-v0.1.md`
  - existing codebase schema/models/API patterns
- Remove/replace any proposed tables/endpoints that would fork the current schema without an approved migration plan.
- Keep the spec actionable for UI/Backend implementation (clear IA, columns, user flows, API contracts).

## Scope

### In Scope
- Docs-only edits to `docs/prd/watchlist/watchlist-v1.md`
- Clarify mapping from “watchlist” → existing entities (`stock_pools`, `pool_memberships`)
- Align price refresh + price semantics with `stock_prices` and `/api/v1/stocks/prices/refresh`

### Out of Scope
- Code changes
- Schema changes / migrations
- Selecting a paid market data vendor for production

## Files To Change
- `docs/prd/watchlist/watchlist-v1.md`

## Test Plan (Docker)
- Docs-only change: none required.

## Notes
- Watchlist V1 should be implemented on top of existing `stock_pools` + `pool_memberships`.
- Price data uses `stock_prices` (EOD), and on-demand refresh uses `/api/v1/stocks/prices/refresh`.

## Progress Update (2026-02-03)
- Aligned “watchlist” terminology to `stock_pools` / `pool_memberships` and corrected field lists to match current models.
- Clarified Fair Value storage to comply with PRD precedence: metric semantics are defined in `docs/metric_facts_mapping_spec.yml` (this PRD does not introduce a new `metric_key` directly).
- Updated Fair Value API contract to extend the existing `GET /api/v1/stocks/{stock_id}/facts` surface (spec-only; not yet implemented).
- Simplified Fair Value write body to `metric_key + value_numeric` (unit/period semantics sourced from mapping spec).
- Added read semantics for `stock_prices` (insert-only; pick latest `created_at`) and clarified `Δ Today` definition (EOD).
- Added deterministic Fair Value display precedence and a non-binding UI refresh sequencing note.
