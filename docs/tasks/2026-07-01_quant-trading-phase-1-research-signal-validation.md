# Task: Quant Trading — Phase 1: Research & Signal Validation
**ID:** `T-2026-07-01-quant-trading-phase-1`  
**Created:** 2026-07-01 · **Updated:** 2026-07-02 (synced to plan **v9**: added blocking `1-R0`; upgraded `1-R4` to the v8 statistical protocol)  
**Status:** `READY` — **start at `1-R0` (blocking)**; `1-R1…1-R4` do not start until 1-R0 passes  
**Priority:** `P1`  
**Owners:** Tech Lead / Quant PM  

---

## 1. Goal & Acceptance Criteria

### Goal
Implement Phase 1 (Research & Signal Validation) to verify that the parsed Value Line fundamental signals contain tradeable, net-of-tax, net-of-friction alpha. This is a strict gate that must be passed before any live trading rails, execution adapters, or stateful position tracking (Phase 2) are built.

### Acceptance Criteria

- **1-R0 Data-Sufficiency Audit + Power Analysis (BLOCKING — nothing else starts until this passes):**
  - Quantify actual `metric_facts` historical depth: years covered × stocks per monthly cross-section × metric coverage. *Empirical status 2026-07-02: dev and prod `metric_facts`/`pdf_documents` are both **0 rows**.*
  - Run a pre-registered **power analysis**: given the 1-R4 α threshold (≥ 2%/yr net) and a realistic tracking-error assumption (4–6%/yr), compute the minimum `T × breadth` required for one-sided `t_HAC ≥ 3` **including the holdout split**.
  - Produce a written data plan: acquire historical Value Line archives / extend accumulation window / conclude not-currently-testable. **Gate: audited data meets the power requirement, else 1-R1…1-R4 stay closed.** Running 1-R4 underpowered is forbidden (inconclusive results burn the holdout).
- **1-R1 Database PIT Read Engine**: Implement the historical Point-in-Time read contract ([quant-trading-pit-read-contract.md](../architecture/quant-trading-pit-read-contract.md), all sections incl. §5 no-global-dedup).
- **1-R2 Calculated-Metric Registry**: The pure builders already exist (`build_piotroski_f_score_facts`, `build_value_line_ratio_facts`); this task is the **registry mapping each calculated `metric_key` → its builder**, driving recompute-from-PIT-inputs with **fail-closed** on unregistered metrics (PIT contract §4).
- **1-R3 Cross-Sectional Factor Engine**: Lightweight Python/Pandas factor evaluation module:
  - Decile return analysis + IC.
  - Turnover estimations.
  - Sector/size neutralization.
  - Fama-French risk exposures.
- **1-R4 OOS Signal Gate + Differentiated-Moat Test** (plan §14 1-R4, v8/v9 protocol — run **once** on an untouched holdout; both sub-gates pre-registered in the Edge Thesis):
  - **(a) Base gate:** net-of-friction, net-of-tax OOS Sharpe > 0.6 AND beats the strategy's **risk/tax-matched** benchmark (SPY / 60-40 as default floors) by ≥ 1.5% net CAGR.
  - **(b) Moat test — controlled spanning regression:** proprietary Value Line signal portfolio excess returns regressed on FF5 + momentum + a **same-universe generic composite** (identical universe/cadence/neutralization/cost-tax model). Pass requires ALL of:
    - α > 0 with one-sided **`t_HAC ≥ 3`** (Newey–West, lag `L = ceil(1.5 × rebalance_interval_periods)`, floor 3) — or the fixed-seed stationary-bootstrap alternative (10k draws, seed = `hash(strategy_key, strategy_version, backtest_run_id, holdout_id)`, lower 5th-percentile α > 0);
    - **Benjamini–Hochberg FDR q = 0.05** across the `K` pre-registered hypotheses AND **Deflated Sharpe Ratio** P(skill) ≥ 0.95 (inputs: observed non-annualized Sharpe, `T`, skew, kurtosis, base frequency, trial-Sharpe variance; `N` = `backtest_runs` rows sharing `trial_group_id` before holdout unlock);
    - net incremental α ≥ 2%/yr surviving capacity/liquidity/turnover-tax investability checks.
  - **Kill rule:** either sub-gate fails → **Phase 2 rails are NOT built**; no tuning against the holdout. **Pre-committed fallbacks** (plan §14): (a) generic factors without moat claims as a personal tax-located allocation; (b) pivot to 13F aggregation signals and re-enter at 1-R0 with a new Edge Thesis.

---

## 2. Scope

### In Scope
- Read-only historical data loader enforcing the PIT read contract.
- Pure calculation layer for Piotroski F-score and Value Line ratios.
- Factor analysis engine (Python/Pandas).
- Transaction friction cost modeling (commissions + slippage + bid-ask spread).
- Tax-netting models (Texas federal-only tax rates: ordinary income + NIIT for daily ETF, 1256 for futures).
- Test harness validating signal alpha against the SPY benchmark.

### Out of Scope
- Event-driven live runner or backtester loops.
- `position_states` database migrations or updates.
- IBKR execution adapters or order routing.
- React UI/dashboard changes.

---

## 3. Precedence & Authority References
1. **PIT Read Contract**: [quant-trading-pit-read-contract.md](../architecture/quant-trading-pit-read-contract.md)
2. **Data Model Extensions**: [quant-trading-data-model.md](../architecture/quant-trading-data-model.md)
3. **Locked `is_current` semantics**: [metric-facts-is-current.md](../architecture/metric-facts-is-current.md) — the PIT reader must never violate it.
4. **Core semantical mapping**: `docs/metric_facts_mapping_spec.yml`
5. **Accepted design (v9) incl. statistical protocol & decision log**: [quant_trading_system_architecture_plan.md](../plans/quant_trading_system_architecture_plan.md)

---

## 4. Files to Change

### [NEW]
- `backend/app/services/quant_trading/data_audit.py`: **1-R0** — coverage audit (years × breadth × metric coverage) + power analysis; emits a written report.
- `docs/tasks/2026-07-0X_quant-trading-1-R0-data-audit-report.md`: 1-R0 findings + data plan + pass/fail against the power requirement (sign-off gate for 1-R1…1-R4).
- `backend/app/services/quant_trading/pit_reader.py`: Historical PIT fact queries.
- `backend/app/services/quant_trading/factor_engine.py`: Factor construction and decile backtest.
- `backend/app/services/quant_trading/calculators.py`: Registry and mapping of pure calculation functions (fail-closed).
- `backend/tests/unit/test_quant_trading_data_audit.py`: Unit tests for the audit/power calc.
- `backend/tests/unit/test_quant_trading_pit_reader.py`: Unit tests for PIT read rules.
- `backend/tests/unit/test_quant_trading_factor_engine.py`: Unit tests for cross-sectional factor engine and gates.

---

## 5. Test Plan & Verification
Run the backend unit test suite in container:
```bash
docker compose exec -T api pytest -q tests/unit/test_quant_trading_data_audit.py
docker compose exec -T api pytest -q tests/unit/test_quant_trading_pit_reader.py
docker compose exec -T api pytest -q tests/unit/test_quant_trading_factor_engine.py
```
Run the full CI validation suite to ensure no regressions:
```bash
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
```
