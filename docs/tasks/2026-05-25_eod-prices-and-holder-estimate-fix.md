# 2026-05-25 — EOD prices backfill + holder $ estimate unit fix

## Goal

Make the Oracle's Lens candidate cards stop displaying broken price data:

1. **Holder $ estimate range** like `$483.60–$483,620.35` (MSFT) — a 1000× spread
   caused by the formula misreading the SEC 13F `<value>` field unit.
2. **`Price — · Ref —`** on every card — caused by no `StockPrice` rows for
   the 2025-Q4 universe (we have 1 of 207).

Both reduce the cards to "looks broken, can't be used for sizing decisions".

## Scope

### In scope

- **Display fix** in `app/services/oracles_lens/dashboard.py::_stock_payload`:
  replace `value_thousands * 1000 / shares` with a period-aware helper that
  matches how the parser would have normalized the value if `value_usd` had
  been populated.
- **EOD price backfill** for the ~207 stocks in `oracles_lens_signals` for
  2025-Q4 (`period_of_report = 2025-12-31`), using the existing
  `scripts.backfill_13f_period_prices` infrastructure.
- Unit tests for the helper + a single integration smoke against the dashboard
  payload.

### Out of scope (will be spawned as separate tasks)

- **`value_usd` backfill** — all existing holdings have `value_parse_rule =
  'inferred'` and `value_usd = NULL` because `Filing13F.accepted_at` isn't fed
  into the unit-inference path during the PR #96 backfill. Fixing this would
  populate the canonical column once and remove the need for the period-aware
  fallback. Separate PR.
- **`is_latest_for_period` repair for 2023-Q1 → 2025-Q3** — only 2025-Q4 has
  this flag set on ~all filings; the other 11 backfilled quarters have it on
  exactly 1 filing each, which makes Oracle's Lens nearly empty for those
  quarters even though the holdings rows exist. The harness ran ingest, but
  didn't (re)compute the latest-per-(manager, period) flag. Separate PR.
- EOD prices for pre-2025-Q4 quarters (depends on the `is_latest_for_period`
  fix landing first — otherwise we'd backfill prices for stocks that won't
  show up in those quarters' Oracle's Lens anyway).
- Quality-finding caveats for 2023 quarters (low linked-ratio).

## Why a period-aware helper + per-row peer anchor instead of "just backfill `value_usd`"

`value_usd` is the right answer, but populating it for the 12 already-ingested
quarters needs the raw infotable XML re-parsed (or at least `accepted_at`
threaded into a normalization sweep). That is a real piece of work and depends
on understanding why `accepted_at` is missing on the backfilled filings. To
avoid blocking the visible-UI fix, this PR resolves the unit at the display
layer.

The naive fix — apply `value_thousands / shares` for periods on or after
2022-12-31 and `value_thousands * 1000 / shares` for earlier periods — is
correct for most rows. But API smoke testing revealed a wrinkle: **within the
same (stock, period), some filers report in dollars and some still in
thousands**. For MSFT 2025-Q4: 29 of 32 holders use the new dollars rule, 3
still use the old thousands rule. A pure period-based helper produces
`$0.4836–$483.62` for the aggregate range — still broken, just less broken.

Resolution order in `_holder_price_estimate(...)`:

1. **Prefer `value_usd`** when populated (canonical, parser-normalized).
2. **Peer anchor** (per-row): for a single (stock, period), compute the
   per-share-price anchor from sibling holders (`_resolve_peer_anchor`).
   For each row, pick whichever of dollars-rule/thousands-rule is closer
   (in log space) to the anchor. The wrong rule is always ~1000× off, so
   the right rule wins decisively.
3. **`accepted_at` heuristic** (no anchor): `>= 2023-01-03` → dollars rule.
4. **`period_of_report` heuristic** (no `accepted_at`): `>= 2022-12-31` →
   dollars rule.
5. **Return `None`** if no unit evidence at all.

`_resolve_peer_anchor` uses density-based clustering across the union of
all-row dollars-rule + thousands-rule candidates: the per-share-price value
with the most other candidates within ±10% wins. The true per-share price gets
~N votes (one per row, from whichever rule is correct for that row); the wrong
"1000× off" price gets fewer because the two rules' wrong-direction outputs
land in different places.

`TRANSITION_ACCEPTED_DATE` is the existing constant in
`app/edgar/parsers/value_units.py` that the parser already trusts; we reuse it
verbatim. When `value_usd` is later backfilled, the helper prefers it and the
peer-anchor / period heuristics become unused.

## Files to change

- `backend/app/services/oracles_lens/dashboard.py` — extract `_holder_price_estimate(...)`
  helper, use it in the two callsites (aggregate range + `top_holders[].holder_price_estimate`).
- `backend/tests/unit/test_oracles_lens_holder_price_estimate.py` (new) —
  unit-test the helper across the unit-transition boundary, with and without
  `value_usd`.
- `backend/tests/unit/test_oracles_lens_dashboard.py` (existing, if needed) —
  if there's an integration test pinning a wrong value, update it.

No schema changes, no migrations, no new env vars.

## Ops: EOD price backfill

After the code lands, run inside the api container:

```bash
docker compose exec -T api python -m scripts.backfill_13f_period_prices \
    --period 2025-12-31
```

Existing `backfill_13f_linked_period_prices` resolves the 2025-Q4 universe via
`Holding13F → Filing13F → InstitutionManager (is_superinvestor=True)` and writes
`StockPrice` rows. Test run for `--limit 5` already returned
`processed=5 refreshed=5 skipped=0 failed=0`, so the path is wired.

## Test plan (Docker)

```bash
docker compose exec -T api pytest -q tests/unit/test_oracles_lens_holder_price_estimate.py
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

Browser smoke after backfill:

- Open `http://localhost:3001/13f/oracles-lens` → 2025-Q4 → top 5 cards now
  show plausible per-share prices (single-digit or double-digit range, not a
  1000× spread) and the `Price` line is populated.

## Sign-off

- [ ] Helper tests green.
- [ ] Full backend suite green.
- [ ] Frontend lint + build + node tests green.
- [ ] `scripts.backfill_13f_period_prices --period 2025-12-31` succeeded with
      `failed=0` for any stocks that have an actual yfinance symbol.
- [ ] Browser smoke shows plausible prices and ranges on Oracle's Lens cards.
- [ ] Spawned follow-up tasks for `value_usd` backfill and
      `is_latest_for_period` repair.
