# MVP8-A2: Watchlist 13F Drawer — M3 Quality & Valuation Overlay

## Status

**Open 2026-05-13.** Gated on Pre-MVP8-A2 decision gate (closed Option B
2026-05-13). Child of the Oracle's Lens M3 track.

## Goal

Add a compact **Quality & Valuation** panel to the Watchlist 13F drawer
(`Watchlist13FDrawer.tsx`) so users see Value Line quality signals and
valuation reference alongside the 13F consensus data without leaving the
Watchlist page.

Strict scope (D1–D4 from decision gate):
- **Only the Watchlist 13F drawer** — no changes to Oracle's Lens page, no
  persisted scoring path changes.
- **Minimum viable overlay** — compact panel reusing existing DB facts, no
  new schema, no full Oracle's Lens dashboard reproduction inside the drawer.
- **Explicit missing-data state** — never silent omission; "Value Line data
  not yet available for this stock" when no VL facts exist.
- **Not blocked by thin coverage** — ship with dev coverage of ~5 stocks;
  the panel is honest about its data scope.

## Data Sources (no new tables, no schema changes)

Quality and valuation facts already in `metric_facts`:

| Signal | Metric key | Storage |
|---|---|---|
| Piotroski F-Score | `score.piotroski.total` | `value_json['partial_score']` / `value_json['max_available_score']` |
| Earnings predictability | `quality.earnings_predictability` | `value_numeric` |
| VL 18-month target (mid) | `target.price_18m.mid` | `value_numeric` |
| VL 18-month target (low) | `target.price_18m.low` | `value_numeric` |
| VL 18-month target (high) | `target.price_18m.high` | `value_numeric` |
| VL 3–5 year low | `proj.long_term.low_price` | `value_numeric` |
| VL 3–5 year high | `proj.long_term.high_price` | `value_numeric` |

**Note**: `quality.financial_strength` is excluded — its `value_json` contains
only `{"fact_nature": "opinion"}` with no usable rating value.

## D1 — Backend: `_m3_panel_for_stock` + endpoint enrichment

**New private function** in `backend/app/api/v1/endpoints/stocks_13f.py`:

```python
_M3_METRIC_KEYS = [
    "score.piotroski.total",
    "target.price_18m.mid",
    "target.price_18m.low",
    "target.price_18m.high",
    "proj.long_term.low_price",
    "proj.long_term.high_price",
    "quality.earnings_predictability",
]

def _m3_panel_for_stock(db: Session, stock_id: int) -> dict:
    """Compact M3 quality/valuation overlay for the drawer.
    Returns {has_value_line: False} when no VL facts exist for the stock."""
    ...
```

- Queries `metric_facts` where `stock_id == stock_id`, `metric_key in _M3_METRIC_KEYS`, `is_current=True`.
- Takes the most recent row per metric key (order by `period_end_date DESC NULLS LAST`, `created_at DESC`).
- Extracts Piotroski score from `value_json['partial_score']` (not `value_numeric` which is NULL).
- Returns `{"has_value_line": False}` when no facts found.
- Returns populated dict when facts found (see response shape below).

**Schema change**: `AvailableStockDetail` in
`backend/app/schemas/stocks_13f_snapshot.py` gains:
```python
quality_overlay: Optional[dict] = None
```

**Endpoint**: `read_stock_13f_detail` passes `quality_overlay=_m3_panel_for_stock(db, stock_id)` to the `AvailableStockDetail` constructor.

**Response shape (new field on `AvailableStockDetail`):**
```json
// When no VL data:
"quality_overlay": {"has_value_line": false}

// When VL data exists:
"quality_overlay": {
  "has_value_line": true,
  "piotroski_score": 7,
  "piotroski_max": 8,
  "piotroski_status": "partial",
  "earnings_predictability": 75.0,
  "vl_target_mid": 538.0,
  "vl_target_low": 355.0,
  "vl_target_high": 721.0,
  "vl_3y_low": 405.0,
  "vl_3y_high": 885.0
}
```

## D2 — Frontend: Compact M3 panel in `Watchlist13FDrawer.tsx`

New **"Quality & Valuation"** `<section>` inserted between the existing
Summary section and Top Holders section.

**When `quality_overlay.has_value_line = false` or `quality_overlay = null`:**
```
Quality & Valuation
Value Line data not yet available for this stock.
```

**When `quality_overlay.has_value_line = true`:**
```
Quality & Valuation
[Piotroski 7/8*] [Earnings Predictability 75%]
VL 18-month target  $355 – $721  (mid $538)
VL 3–5 year range   $405 – $885
* partial score (missing 1 indicator)
```

- Piotroski badge: tone based on score/max: ≥7/9 → success, 5–6 → secondary, ≤4 → outline. Label: `"Piotroski {score}/{max}"` + `"*"` when status = "partial".
- Earnings predictability: single-line percentage label, no badge color logic (value is interpretive context, not a buy/sell signal).
- VL targets: formatted as `$N` using `toLocaleString()`, two rows (18-month and 3–5 year). Omitted entirely when values are null.
- "partial score" footnote only when `piotroski_status === 'partial'`.

## D3 — Types: `watchlist13f.ts`

Add `quality_overlay` to `Watchlist13FAvailableDetail`:
```typescript
quality_overlay: {
  has_value_line: boolean;
  piotroski_score: number | null;
  piotroski_max: number | null;
  piotroski_status: string | null;
  earnings_predictability: number | null;
  vl_target_mid: number | null;
  vl_target_low: number | null;
  vl_target_high: number | null;
  vl_3y_low: number | null;
  vl_3y_high: number | null;
} | null;
```

## Scope Out

- Oracle's Lens page changes — already has M3, no regression.
- Persisted scoring path — D1 decision: not in scope.
- `quality.financial_strength` — no usable value in DB.
- New metric ingestion — depends on Value Line parser, separate track.
- Backend tests for `_m3_panel_for_stock` — one unit test for the
  has-data path and one for the no-data path.

## Verification

- `docker compose exec api pytest -q` — full suite green.
- `docker compose exec web npm run lint` — clean.
- `docker compose exec web npm run build` — clean.
- Manual probe:
  1. Open `/watchlist` → click a row for a stock WITH VL data (e.g., ADBE,
     FICO, FNV, GOOG, or MTDR in dev) → drawer shows Quality & Valuation
     panel with Piotroski + earnings predictability + VL targets.
  2. Click a row for a stock WITHOUT VL data → drawer shows
     "Value Line data not yet available for this stock."
  3. Oracle's Lens page at `/13f/oracles-lens` renders without regression.

## Files Expected to Change

- `backend/app/api/v1/endpoints/stocks_13f.py`
- `backend/app/schemas/stocks_13f_snapshot.py`
- `frontend/lib/watchlist13f.ts`
- `frontend/components/watchlist/Watchlist13FDrawer.tsx`
- `backend/tests/unit/` — new `test_13f_mvp8_a2_m3_panel.py`
- `docs/tasks/2026-05-13_mvp8-a2-watchlist-m3-overlay.md` (this file)

## Sign-Off Trail

- [x] Backend `_m3_panel_for_stock` + endpoint enrichment shipped.
- [x] Frontend compact M3 panel shipped (has-data + no-data paths).
- [x] pytest -q → 819 passed (2 pre-existing isolation-flaky failures pass in
      isolation); lint clean; build clean.
- [x] curl probe passed 2026-05-13:
      FICO (757) → has_value_line=true, piotroski 6/7, EP 100%, VL $1125–$2489 mid $1807;
      ADBE (1254) → has_value_line=true, piotroski 5/7, EP 75%, VL $203–$417 mid $310;
      AAPL (1237, no VL data) → has_value_line=false (explicit empty state).
- [x] **MVP8-A2 closed 2026-05-13.**
