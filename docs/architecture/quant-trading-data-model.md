# Quant Trading System — Data Model & Tables
*Promoted from quant_trading_system_architecture_plan.md §11; synced to **v9 (accepted)** on 2026-07-02.*

This contract defines the new database schema extensions, Alembic table schemas, and table write-conflict behaviors.

## 1. Table Definitions

All table names and metric keys use `snake_case` plural names:

- **`price_bars`**: tracks split/dividend adjusted historical OHLCV data.
  - Columns: `(stock_id, date, open, high, low, close, adj_close, volume)`
- **`corporate_actions`**: tracks corporate action events.
  - Columns: `(stock_id, ex_date, type, ratio_or_amount)`
- **`signal_values`**: captures point-in-time snapshots of indicators and factors.
  - Columns: `(instrument_id, as_of_date, signal_key, signal_family, source, value_numeric, value_json, run_scope, data_version, strategy_version)`
  - Notes: `data_version` is an explicit column to isolate research caching from production signals.
- **`strategies`**: registers strategy spec configs.
  - Columns: `(strategy_key, strategy_version, archetype, strategy_spec_json, edge_thesis_json, created_at)`
  - Notes: Unique constraint over `(strategy_key, strategy_version)`. `edge_thesis_json` is a required, non-empty validation block documenting structural edge rationale, capacity, decay, and benchmark hurdles.
- **`position_states`**: tracks stateful position lifecycles.
  - See [quant-trading-event-ordering-parity.md](file:///Users/dane/projects/ValuePilot/docs/architecture/quant-trading-event-ordering-parity.md).
- **`broker_holdings`**: tracks live broker-synchronized positions.
  - Columns: `(account_id, instrument_id, quantity, avg_cost, market_value, updated_at)`
- **`tax_lots`**: logs cost basis and tax lot tracking details.
  - Columns: `(instrument_id, lot_id, open_date, quantity, cost_basis, section_1256_flag)`
  - Notes: Models Section 1256 status separately for futures vs standard equities/ETFs.
- **`target_portfolios`**: records generated rebalance targets.
  - Columns: `(strategy_key, strategy_version, rebalance_date, instrument_id, target_type, target_quantity, target_weight)`
  - Notes: Quantities and weights are split into separate typed columns (no mixed-type columns).
- **`backtest_runs`**: records backtest performance runs ledger.
  - Columns: `(strategy_key, strategy_version, trial_group_id, trial_index, params_json, metrics_json, net_of_tax_metrics_json, benchmark_json, gate_passed, holdout_flag)`
  - Notes: `net_of_tax_metrics_json`, `benchmark_json`, and `gate_passed` are required fields verifying the Go/No-Go profitability audit trail. `trial_group_id` / `trial_index` (added v8) make the multiple-testing **trial family** an exact query — the 1-R4 Deflated-Sharpe-Ratio step defines `N` = count of rows sharing `trial_group_id` recorded **before holdout unlock**.

## 2. Table Write-Conflict Semantics

To prevent dirty writes, race conditions, or duplicate configurations, the following semantics must be enforced:

1. **`strategies`**:
   - Write Conflict Strategy: **Typed Exception on IntegrityError**.
   - Rationale: Strategy spec versions are immutable. Overwriting an existing version is strictly forbidden.
2. **`signal_values`**:
   - Write Conflict Strategy: **Idempotent Upsert**.
   - Rationale: Research or caching reruns should overwrite existing calculated signal values.
3. **`position_states`**:
   - Write Conflict Strategy: **Optimistic Concurrency & event-id guards**.
   - Rationale: Never overwrite state using "last-writer-wins". State transitions are sequential and verified by optimistic locking (`revision` check).
