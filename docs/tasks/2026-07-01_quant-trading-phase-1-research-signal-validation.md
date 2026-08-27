# Task: Quant Trading — Phase 1: Research & Signal Validation
**ID:** `T-2026-07-01-quant-trading-phase-1`  
**Created:** 2026-07-01 · **Updated:** 2026-07-21 (synced to plan **v11 / D15**: repeatable 1-R0A audit implemented; explicit NO_GO; later tasks closed)
**Status:** `BLOCKED — 1-R0A completed NO_GO on 2026-07-21`; `1-R1…1-R4` must not start
**Priority:** `P1`  
**Owners:** Tech Lead / Quant PM  

---

## 1. Goal & Acceptance Criteria

### Goal
Implement Phase 1 (Research & Signal Validation) to verify that the parsed Value Line fundamental signals contain tradeable, net-of-tax, net-of-friction alpha. This is a strict gate that must be passed before any live trading rails, execution adapters, or stateful position tracking (Phase 2) are built.

### Acceptance Criteria

- **1-R0 Data-Sufficiency Audit + Power Analysis (BLOCKING — nothing else starts until this passes; data plan revised per plan v10 D14):**
  - **2026-07-21 result:** the repeatable development audit is implemented and
    archived at `docs/audits/quant/2026-07-21_1-r0-data-sufficiency.md`.
    It returned explicit **NO_GO**. P1-A's report exists; P1-B and the overall
    1-R0 gate do not pass.
  - Quantify actual `metric_facts` historical depth: years covered × stocks per monthly cross-section × metric coverage. *Empirical status 2026-07-02: dev and prod `metric_facts`/`pdf_documents` are both **0 rows**.*
  - **Data-availability matrix (D14 constraint):** VL reports are downloadable **2025+ only**. Each carries ~10 years of *restated* fundamentals (survivors-only, reconstructed-vintage use only) but opinion signals exist **only as of each report date** (unrecoverable). Record this matrix in the audit report.
  - Run a pre-registered **power analysis per hypothesis (H1/H2/H3, see 1-R4)**: given the α threshold (≥ 2%/yr net), realistic tracking-error scenarios (4–6%/yr), target power and holdout split, compute the required return-history time for one-sided `t_HAC ≥ 3`. Cross-sectional breadth is a separate eligibility floor and is never treated as fungible with HAC time observations.
  - Execute the **v10 data plan**:
    1. **Required:** acquire a survivorship-free commodity fundamentals + prices dataset (delisted names included) — the backbone for H1/H3 and the generic null.
    2. **Immediate:** stand up the **weekly Value Line archiving program** (every downloadable report, every week; real `report_date` → natively PIT-correct). This is H2's only raw material; a missed week can never be backfilled. Automate it (scheduler job) before any engine code.
    3. **Optional:** historical VL archives (VL institutional historical products; university library holdings) — accelerates H2 only; no longer blocks anything.
    4. Define the **reconstructed-vintage mode** as a PIT-contract amendment (goes into 1-R1 scope): synthetic publication lag `period_end_date + 90d`, results stamped `vintage_mode=reconstructed` + survivor-biased, admissible for **relative judgments only** (deciles/IC/monotonicity), never for the absolute-return Go/No-Go.
  - **Gate: audited data meets the power requirement for at least H1, else 1-R1…1-R4 stay closed.** Running any hypothesis underpowered is forbidden (inconclusive results burn the holdout).
- **1-R1 Database PIT Read Engine**: Implement the historical Point-in-Time read contract ([quant-trading-pit-read-contract.md](../architecture/quant-trading-pit-read-contract.md), all sections incl. §5 no-global-dedup).
  This now includes an H3 filing/amendment selector that chooses the 13F
  version observable at T; the current product `active_hr_holdings_query` is
  not a historical PIT reader.
- **1-R2 Calculated-Metric Registry**: The pure builders already exist (`build_piotroski_f_score_facts`, `build_value_line_ratio_facts`); this task is the **registry mapping each calculated `metric_key` → its builder**, driving recompute-from-PIT-inputs with **fail-closed** on unregistered metrics (PIT contract §4).
- **1-R3 Cross-Sectional Factor Engine**: Lightweight Python/Pandas factor evaluation module:
  - Decile return analysis + IC.
  - Turnover estimations.
  - Sector/size neutralization.
  - Fama-French risk exposures.
  - **Factor library = the VL-proxy recipes (v10 D14)** — each factor is the reconstructable, better-documented equivalent of a VL proprietary indicator:
    | VL indicator | Proxy factor to implement | Source data |
    |---|---|---|
    | Timeliness | `momentum_12_1` + **SUE/PEAD** + 10-yr earnings trend | prices + commodity fundamentals |
    | Safety / Price Stability | **low-volatility** (5-yr weekly vol rank) + beta | prices |
    | Financial Strength | **gross profitability** + **accruals** + Piotroski F (already built) + leverage/coverage | fundamentals (partly parsed already) |
    | Earnings Predictability | YoY-EPS-change stability / log-EPS trend R² | the parsed 10-yr annual table |
    | (composite) | **"VL-proxy" rank** = weighted composite of the above | — |
- **1-R4 OOS Signal Gate + Moat Hypothesis Set** (plan §14 1-R4, v10 protocol — run **once** on an untouched holdout; all pre-registered in the Edge Thesis):
  - **(a) Base gate:** net-of-friction, net-of-tax OOS Sharpe > 0.6 AND beats the strategy's **risk/tax-matched** benchmark (SPY / 60-40 as default floors) by ≥ 1.5% net CAGR.
  - **(b) Moat hypothesis set — controlled spanning regressions** against the same fixed null (FF5 + momentum + same-universe generic composite; identical universe/cadence/neutralization/cost-tax model):
    - **H1 — VL-proxy composite** (blocking, designed but not currently powered): after a survivorship-free commodity backbone passes 1-R0, does the VL-style combination add α beyond the null?
    - **H2 — VL actual-vs-proxy residual** (NON-blocking forward bonus): does the published VL rank add α beyond our proxy (analyst-override value)? Evaluated on the weekly-archived 2025+ corpus at a pre-registered future date once 1-R0's power calc says it is testable.
    - **H3 — 13F aggregation signals** (blocking-eligible candidate, not currently powered): conviction clones / crowding / 13F momentum vs the same null, using the filing/amendment version observable at T.
    Each hypothesis passes only with ALL of:
    - α > 0 with one-sided **`t_HAC ≥ 3`** (Newey–West, lag `L = ceil(1.5 × rebalance_interval_periods)`, floor 3) — or the fixed-seed stationary-bootstrap alternative (10k draws, seed = `hash(strategy_key, strategy_version, backtest_run_id, holdout_id)`, lower 5th-percentile α > 0);
    - **Benjamini–Hochberg FDR q = 0.05** across the `K` pre-registered hypotheses AND **Deflated Sharpe Ratio** P(skill) ≥ 0.95 (inputs: observed non-annualized Sharpe, `T`, skew, kurtosis, base frequency, trial-Sharpe variance; `N` = `backtest_runs` rows sharing `trial_group_id` before holdout unlock);
    - net incremental α ≥ 2%/yr surviving capacity/liquidity/turnover-tax investability checks.
  - **Kill rule:** sub-gate (a) fails, or **both H1 AND H3 fail** → **Phase 2 rails are NOT built**; no tuning against the holdout. H2 never blocks. **Pre-committed fallback** (plan §14): generic factors without moat claims as a personal tax-located allocation.

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
0. **PO acceptance standard (sign-off basis)**: [quant_product_definition_acceptance.md](../plans/quant_product_definition_acceptance.md) — Phase 1 closes only when checklist items **P1-A…P1-H** are executed by the PO personally (esp. P1-F pre-registration timestamp check).
1. **PIT Read Contract**: [quant-trading-pit-read-contract.md](../architecture/quant-trading-pit-read-contract.md)
2. **Data Model Extensions**: [quant-trading-data-model.md](../architecture/quant-trading-data-model.md)
3. **Locked `is_current` semantics**: [metric-facts-is-current.md](../architecture/metric-facts-is-current.md) — the PIT reader must never violate it.
4. **Core semantical mapping**: `docs/metric_facts_mapping_spec.yml`
5. **Accepted design (v9) incl. statistical protocol & decision log**: [quant_trading_system_architecture_plan.md](../plans/quant_trading_system_architecture_plan.md)

---

## 4. Files to Change

### [NEW]
- `backend/app/services/quant_trading/data_audit.py`: **1-R0** — coverage audit (years × breadth × metric coverage) + power analysis; emits a written report.
- **1-R0 weekly VL archiving job** (scheduler task + runbook note): ingest every downloadable Value Line report weekly; alert on a missed week (H2 data is unrecoverable).
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
