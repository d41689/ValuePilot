# `metric_facts.is_current` Semantics — Decision Gate

**Status: CLOSED 2026-05-14 — Option A selected (status quo + read-side tiebreak, locked as data contract)**
**Date: 2026-05-13 (opened), 2026-05-14 (closed)**
**Blocks**: opinion-metric staleness handling (VL targets / projections /
quality ratings) and any future "stale-fact suppression" feature.
**Does NOT block**: MVP8-A2 P2 (VL target as-of date label) — D1 of the
post-MVP8-A2 sweep ships that purely off the existing `period_end_date`
column, no schema change required.

---

## 1. Problem Statement

`metric_facts.is_current: bool` is overloaded across two metric categories
that share the same `is_current` semantics:

### Category A — Fiscal time series

Per-fiscal-period actuals or per-period calculated scores.

| Metric | Storage column | Period meaning |
|---|---|---|
| `per_share.eps` | `value_numeric` | fiscal year (FY) |
| `is.net_income` | `value_numeric` | FY |
| `score.piotroski.total` | `value_json['partial_score']` | FY |
| `bs.total_equity` | `value_numeric` | FY |
| `returns.total_capital` | `value_numeric` | FY |

For these, **each period genuinely is "current"**. ADBE has 42
`is_current=True` rows for `per_share.eps` — one per FY of VL history.
Wiping the time series would break:
- The Piotroski calculator (`piotroski_f_score.py` reads
  `is_current=True` source facts to compute year-over-year deltas).
- The screener (`screener_service.py` filters on `is_current=True`).
- The formula engine (`formula_engine.py` selects facts by
  `is_current=True`).

### Category B — Opinion / as-of facts

Analyst opinions, projected ranges, qualitative ratings.

| Metric | Storage column | Period meaning |
|---|---|---|
| `target.price_18m.mid` | `value_numeric` | VL publication date |
| `target.price_18m.low` / `.high` | `value_numeric` | VL publication date |
| `proj.long_term.high_price` / `.low_price` | `value_numeric` | VL publication date |
| `quality.earnings_predictability` | `value_numeric` | VL publication date |
| `quality.financial_strength` | `value_json` (rating string) | VL publication date |

For these, **`period_end_date` is effectively the publication / as-of
date, not a fiscal period**. A newer VL report at 2026-05-01
supersedes the older target from 2025-01-31. Keeping both
`is_current=True` lets a user see a stale target as if it were the
current opinion.

### Concrete example (ADBE, observed in dev DB 2026-05-13)

```
(stock_id=1254, metric_key='target.price_18m.mid', is_current=True, period_end_date=2026-05-01, value=$310, source_doc=2654)
(stock_id=1254, metric_key='target.price_18m.mid', is_current=True, period_end_date=2025-01-31, value=$538, source_doc=2655)
```

The M3 panel query
(`_m3_facts_by_stock` in `oracles_lens/dashboard.py`) tiebreaks on
`period_end_date DESC` and picks the $310 row — correct *for the
display layer*. But any caller using `WHERE is_current=True` without a
period tiebreak would see both, which is misleading for opinion
metrics.

---

## 2. Existing Invariant (`_reconcile_parsed_fact_current_slot`)

`backend/app/services/ingestion_service.py:953` enforces uniqueness
scoped to:
```
(stock_id, metric_key, period_type, period_end_date, source_type)
```

For fiscal facts this is correct ("one current row per period"). For
opinion facts this is **too narrow** — each publication date is its
own bucket, so multiple `is_current=True` rows coexist.

The same scoping pattern shows up in `piotroski_f_score.py:142–144`
and `value_line_ratios.py:130–132` for calculated metrics.

---

## 3. Decision Options

### Option A — Display-layer-only (status quo + tiebreak)

Accept the schema as-is. Treat opinion-metric staleness at the read
layer (drawer M3 panel + Oracle's Lens dashboard already use
`period_end_date DESC` tiebreaks).

- **Cost**: zero engineering work.
- **Risk**: every new consumer of opinion metrics must remember the
  tiebreak. SQL queries using `WHERE is_current=True` without
  per-stock-per-key dedup will surface stale opinions.

### Option B — Metric-key allowlist (lightweight)

Add a module-level constant:
```python
OPINION_METRIC_KEYS_GLOBAL_CURRENT: set[str] = {
    "target.price_18m.mid", "target.price_18m.low", "target.price_18m.high",
    "proj.long_term.high_price", "proj.long_term.low_price",
    "proj.long_term.high_total_return", "proj.long_term.low_total_return",
    "quality.earnings_predictability", "quality.financial_strength",
    "quality.stock_price_stability", "quality.price_growth_persistence",
    ...
}
```

Extend `_reconcile_parsed_fact_current_slot`: when the metric_key is in
the allowlist, demote ALL prior `is_current=True` rows for the same
`(stock_id, metric_key)` regardless of `period_end_date`. Otherwise
keep the current per-period scoping.

- **Cost**: ~1 day. ~30 lines of code + one-time cleanup migration +
  regression tests for both branches.
- **Risk**: the allowlist must be maintained as new VL metrics are
  added. Easy to forget — but at least it's a single registry.

### Option C — Schema column for "as-of vs fiscal" classification

Add a new column to `metric_facts`:
```sql
ALTER TABLE metric_facts ADD COLUMN period_semantics TEXT
  CHECK (period_semantics IN ('fiscal', 'as_of'));
```

The reconciliation reads the column to decide scope. Opinion metrics
get `period_semantics='as_of'`; fiscal metrics stay `fiscal` (default
or backfilled).

- **Cost**: ~2–3 days. Schema migration + parser changes to set the
  column on write + backfill migration for existing rows + RLS /
  permission considerations.
- **Risk**: schema change is harder to roll back. Forcing the
  classification on every write is more intrusive than an allowlist.

### Option D — Split column: `as_of_date` separate from `period_end_date`

Stop overloading `period_end_date`. Add `as_of_date: date | None` and
require opinion metrics to set it (with `period_end_date` null or
sentinel). Reconciliation for opinion metrics uses `as_of_date` for
"newest wins" logic.

- **Cost**: ~3–5 days. Schema migration + parser rewrites + every
  read-path query that touches opinion metrics needs to swap to the
  new column.
- **Risk**: most invasive option. High blast radius across the
  metric_facts read paths. Probably overkill unless the data model
  needs the distinction for other reasons (e.g., displaying both "VL
  target as published on X" and "VL target effective for Q Y").

---

## 4. PO Decision Points

| # | Question | Notes |
|---|---|---|
| D1 | Which option (A / B / C / D)? | See cost/risk table above. |
| D2 | If B / C / D — is the cleanup migration required, or do we accept the existing duplicate rows as historical noise that the new ingestion path won't reproduce? | Cleanup is ~50 affected stocks in dev DB; prod size unknown. |
| D3 | If B — who owns the allowlist registry? Is it in `oracles_lens/dashboard.py` near `QUALITY_METRIC_KEYS` / `VALUATION_REFERENCE_KEYS`, or a new dedicated module like `app/services/metric_semantics.py`? | Affects future maintenance. |
| D4 | Is there any consumer today that needs both the historical AND current opinion (i.e., showing analyst revision history)? If yes, Option B/C breaks that without an explicit `is_current=False` historical query. | Likely no, but worth confirming. |

---

## 5. Recommended Path (Engineering View)

**Option A** as a deliberate decision documented in CLAUDE.md, paired
with hardening reads. Rationale:

- The schema overload is real but small (~10 opinion metric_keys vs ~80
  fiscal/calc keys).
- The display layer already handles it correctly via
  `_m3_facts_by_stock` tiebreak ordering — the only known consumer of
  opinion metrics in the M3 path is the drawer panel, and that's
  fixed.
- Every other read path (`screener_service`, `formula_engine`,
  `piotroski_f_score`) consumes fiscal metrics only — none would
  benefit from B / C / D today.
- B is a reasonable middle ground if/when a second opinion-metric
  consumer lands. Defer until then.

If the PO disagrees and wants a write-side fix, **Option B** is the
right level of investment. Skip C / D unless they unlock other
product needs (e.g., showing analyst revision history on Oracle's
Lens).

---

## 6. Files That Would Change (Option B reference)

- `backend/app/services/ingestion_service.py` —
  `_reconcile_parsed_fact_current_slot` extension for opinion keys.
- `backend/app/services/metric_semantics.py` (new) —
  `OPINION_METRIC_KEYS_GLOBAL_CURRENT` registry.
- `backend/migrations/versions/<ts>-dedup-opinion-metric-is-current.py`
  (cleanup migration).
- `backend/tests/unit/test_<vl_parser>.py` — regression for both
  branches.
- `CLAUDE.md` — short note recording the chosen semantics.

## 7. Sign-Off

- [x] **PO selects Option A 2026-05-14** (status quo + read-side
      tiebreak). Rationale: financial-data accuracy first principle is
      "do not break the original time-series facts". Multiple
      `is_current=True` rows for fiscal metrics are CORRECT by design.
      Opinion-metric staleness is handled at the read layer via
      `_m3_facts_by_stock` tiebreak + `(VL report dated YYYY-MM-DD)` UI
      label. Option B opinion-key allowlist is reserved for the case
      where a second opinion-metric consumer arrives that cannot use
      the read-side tiebreak pattern.
- [x] CLAUDE.md updated with the locked contract + read-side guard
      expectations.
- [x] Memory updated (`feedback_metric_facts_is_current_semantics`)
      to reflect the locked decision.
- [x] No implementation ticket needed (Option A is the existing state).
