# Quant Trading System — Event Ordering & Parity Contract
*Promoted from quant_trading_system_architecture_plan.md §8; synced to **v9 (accepted)** on 2026-07-02 (content verified current — enum CHECKs, per-mode indexes, 11 ordering rules).*

## 1. Position States Schema

The database table `position_states` tracks stateful positions. Multiple versions, backtest runs, and accounts are scoped to prevent clobbering:

```
position_states(
  id                 PK,
  strategy_key       NOT NULL,
  strategy_version   NOT NULL,
  mode               NOT NULL,        -- 'backtest' | 'paper' | 'live'
  backtest_run_id    NULL FK backtest_runs(id),   -- set iff mode='backtest'
  account_id         NULL,            -- set iff mode in ('paper','live')
  instrument_id      NOT NULL,
  status             NOT NULL,        -- 'open' | 'closed'
  entry_price, base_qty, high_water_mark, trailing_stop_level, adds_used,
  opened_at,
  last_event_id      NOT NULL,        -- monotonic; rejects stale/replayed events
  last_processed_ts  NOT NULL,        -- bar/event as-of; sequencing anchor
  revision           NOT NULL,        -- optimistic-concurrency counter
  created_at, updated_at
)
```

## 2. Mutual Exclusion

To guarantee exactly one open position per instrument per run/account, and eliminate PostgreSQL's NULL-distinctness unique constraint loophole (where NULLs are treated as distinct and allow duplicate rows), Postgres enforces:

1. **Enum Domain CHECK Constraints**:
   - `mode IN ('backtest', 'paper', 'live')`
   - `status IN ('open', 'closed')`
2. **Mode-Scope CHECK Constraints**:
   - `mode = 'backtest'` ⇒ `backtest_run_id NOT NULL AND account_id NULL`
   - `mode IN ('paper', 'live')` ⇒ `account_id NOT NULL AND backtest_run_id NULL`
3. **Per-Mode Partial Unique Indexes**:
   ```sql
   -- backtest: backtest_run_id is non-null in this mode; account_id excluded from the key
   CREATE UNIQUE INDEX uq_posn_open_backtest ON position_states
     (strategy_key, strategy_version, backtest_run_id, instrument_id)
     WHERE status = 'open' AND mode = 'backtest';

   -- paper/live: account_id is non-null in this mode; backtest_run_id excluded from the key
   CREATE UNIQUE INDEX uq_posn_open_live ON position_states
     (strategy_key, strategy_version, account_id, instrument_id)
     WHERE status = 'open' AND mode IN ('paper','live');
   ```

## 3. Concurrency & Stream Discipline

- **Optimistic Concurrency**: Live updates must use optimistic locking: `UPDATE position_states SET ... WHERE id = :id AND revision = :revision`, incrementing `revision` on each write.
- **Event-Id Namespace**: `last_event_id` is monotonic within a single stream identified by `(mode, backtest_run_id | account_id)`.
- **Replay Policy**: Idempotent processing. If `last_event_id <= stored_event_id`, the event is silently ignored (no-op).
- **Out-of-Order Guards**: Drop any incoming event with an ID/timestamp older than the stored watermark.

## 4. Event Ordering Rules (Parity between Backtest & Live)

1. **Bar Close Signals**: Signals are calculated strictly on bar close using data $\le$ that close (PIT).
2. **Next-Bar Execution**: Orders execute at the **next bar open**; same-bar-close fills are prohibited.
3. **Risk-First Evaluation**: Within a bar, trailing stop/exit rules are evaluated **before** entry or add signals.
4. **Gap-Through Fills**: If a bar opens beyond a stop level, the position is filled at the gap open plus slippage, not at the trigger price.
5. **Intrabar Path Assumption**: Test stop triggers against bar high/low using a worst-case intrabar path assumption (always assume the stop level was hit before any favorable extreme).
6. **Same-Bar Conflict**: If a stop triggers and an add signal occurs on the same bar, the stop takes precedence and the add is cancelled.
7. **Regime Cap Binding**: Exposure limits are evaluated at bar close. Any forced de-risk executes next executable window. Positions exceeding the cap are immediately flagged as over-limit.
8. **State Updates**: Position metadata (`high_water_mark`, `trailing_stop_level`, `adds_used`) is updated only after fills are confirmed and stamped with `last_event_id` and `last_processed_ts`.
9. **Incremental Partial Fills**: Each fill is a distinct event. `base_qty` accumulates, `entry_price` is updated to a quantity-weighted average, and `revision` bumps. A position is marked `open` upon the first fill.
10. **Deterministic Multi-Adds**: When multiple adds trigger on the same bar, process them in a deterministic order (ascending `instrument_id`, then rule order in the spec).
11. **Corporate Action Adjustment**: Splits/dividends adjust `base_qty`, `entry_price`, `high_water_mark`, and `trailing_stop_level` *before* evaluating signals or stops for that bar.
