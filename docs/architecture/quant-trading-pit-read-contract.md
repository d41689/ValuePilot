# Quant Trading System — Point-in-Time Read Contract
*Promoted from quant_trading_system_architecture_plan.md §9; synced to **v9 (accepted)** on 2026-07-02.*

This contract defines how the backtest engine reads `metric_facts` as-of a historical date **T** to prevent look-ahead bias and maintain parity with live trading.

## 1. The `is_current` Invariant
The stored `metric_facts.is_current` column represents *today's* winner, not the winner as-of date **T**. Because document reconciliation updates `is_current` as new data arrives, filtering by `is_current = True` in a backtest introduces severe look-ahead bias. 

**Contract:** Do NOT trust or filter on the stored `is_current` flag for historical reads. 

## 2. Temporal Filters
Every historical query evaluated as-of date **T** must join `metric_facts` to `pdf_documents` and apply:
1. **Publication Filter**: Join `metric_facts.source_document_id → pdf_documents.report_date` and filter where `report_date <= T`.
2. **Period Filter**: Filter where `period_end_date <= T` (ensuring the fiscal period has actually closed and is knowable).

## 3. As-of Currency Selection
To select the correct "active" parsed fact at $T$:
- **Fiscal Time Series** (e.g., `per_share.eps`, `is.net_income`, `bs.total_equity`):
  - Pick the row with the greatest `period_end_date <= T`.
  - Tiebreak: pick the greatest `report_date <= T`, then greatest `source_document_id`, then greatest `id`.
- **Opinion / As-Of Facts** (e.g., price targets, quality grades):
  - Pick the row with the latest `report_date <= T`.
  - Tiebreak: pick the greatest `created_at`, then greatest `id`.

## 4. Calculated Facts Recomputation
Stored calculated facts (`source_type = 'calculated'`) are look-ahead liabilities because they are written with `source_document_id = NULL` (no report date to bound by) and are computed relative to *today's* current slot winner.

**Contract:**
- Do NOT read stored calculated `metric_facts` in a backtest.
- **Recomputation Rule**: Recompute calculated metrics inside the backtester from PIT-correct inputs (gathered via rules 1–3 above), then run the pure calculator functions (e.g., `build_piotroski_f_score_facts` or `build_value_line_ratio_facts`).
- **Calculated Metric Registry**: The backtest engine must reference an explicit execution registry mapping calculated metric keys to their respective pure builder modules:
  - `score.piotroski.*` → `build_piotroski_f_score_facts`
  - Value Line ratios (`returns.roa`, `liquidity.current_ratio`, `leverage.long_term_debt_to_capital`, `efficiency.asset_turnover`, etc.) → `build_value_line_ratio_facts`
- If a strategy requires a calculated metric not present in the registry, the engine must **fail closed** (raise an error) rather than fall back to reading stored database rows.

## 5. No Global Dedup — Locked Invariant (plan §9 rule 6)
This contract is a **read-time as-of reconstruction**; it does NOT change the currency model. Per the locked semantics in [metric-facts-is-current.md](metric-facts-is-current.md) and AGENTS.md critical invariant #2:
- **Never** enforce or assume one `is_current=True` row per `(stock_id, metric_key)`.
- **Never** author a migration, Alembic op, or one-off script that demotes rows by `(stock_id, metric_key)` globally. Naive global dedup wipes ~99% of fiscal time series and breaks Piotroski, the screener, the formula engine, and Oracle's Lens.

## 6. Missing Data Handling
If no qualifying fact exists at date **T**, the factor is considered **missing**. The engine must never default missing values to 0. Composite scores should check for partial indicators in `value_json['partial_score']` and apply the spec's missing-value policy (e.g., sector median imputation).

## 7. 13F Filing and Amendment PIT Rule (H3)

`active_hr_holdings_query` is the authority for the **current product snapshot**;
it is not a historical PIT reader. For an H3 read as of T:

1. require `filed_at <= T` (or the more precise `accepted_at <= T` when
   populated); quarter end is never the availability timestamp;
2. select the filing/amendment version whose authority was known at T, following
   the amendment chain and coverage type as they existed then;
3. select that accession's current successful parse version, bounded to the
   parser/data version frozen for the research run;
4. never back-project today's `is_active_for_manager_period=true` filing or a
   later amendment into an earlier date;
5. an incomplete current quarter is not a complete cross-section until its
   official filing deadline/readiness policy has passed.

The 2026-07-21 audit found 1,204 versioned successful filings and 49
manager-quarters with multiple versions, so this is a material look-ahead trap,
not a theoretical edge case.
