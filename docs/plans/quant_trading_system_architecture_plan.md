# Quant Trading System — Framework / Architecture (v10 — ACCEPTED; D14 data-constraint amendment)

**Status:** ACCEPTED design (2026-07-02). Pre-implementation; no production code changed yet. Phase 1 tickets may open.
**Review state:** v2–v7 → iterative REJECT/NEEDS-FIX cycles, all closed. **v8 → APPROVE by two independent close-out reviews** (M6/M3 statistical protocol confirmed implementation-grade). A final comprehensive master review (2026-07-02) affirmed the engineering and added **one blocking precondition: 1-R0 data-sufficiency audit + power analysis** — empirically, the local dev & prod `metric_facts` are both **empty**, so 1-R4 has no statistical power on current data; see [§2 Decision log](#2-decision-log) D13 and [§14](#14-phased-build-order-small-gated-tasks) 1-R0. Contracts promoted to `docs/architecture/quant-trading-*.md`; Phase 1 ticket: `docs/tasks/2026-07-01_quant-trading-phase-1-research-signal-validation.md`.
**Purpose:** Framework design for a multi-strategy quant trading platform built on the ValuePilot foundation. Two strategy archetypes on shared rails; sequenced so the first validates the hard infrastructure and the second brings the ValuePilot fundamental-data moat online.
**Author context:** designed across a Claude Code session on 2026-07-01.

> **Reviewers:** read [§2 Decision log](#2-decision-log) first, then the three should-block sections. Remaining open questions are in [§15](#15-review-outcome--open-questions).

---

## 1. Scope & intent

Design (not yet build) a **multi-strategy quant trading platform**. A "strategy" is a versioned, declarative config (a `StrategySpec`) that a generic engine compiles and runs in both backtest and live.

Fixed parameters:
- **Horizon:** medium/low frequency (weeks–months). NOT HFT.
- **Broker:** **IBKR primary** (real API, futures + Section 1256, shorting, leverage, multi-asset). Fidelity retained as a manual-execution fallback adapter.
- **Tax domicile:** Texas → only federal tax. Account location and (for futures) Section 1256 are the levers ([§12](#12-tax-design-texas-resident)).
- **Foundation to reuse (precise — see review note):**
  - **Real, direct reuse:** `metric_facts` (source of truth), the React/shadcn frontend, the `score_version` versioning pattern (→ `strategy_version`).
  - **Indirect / inspiration only (do NOT overclaim):** `metric_extractions` lineage helps trading PIT only indirectly (it documents provenance, not as-of trading state); `rule_json → SQLAlchemy` is a *design inspiration* for "config compiles to executable," **not** literal reuse — `StrategySpec` does **not** reuse the screener rule compiler.

**Two archetypes** ([§6](#6-strategy-archetypes)): time-series/regime-trigger, and cross-sectional factor (the moat).

**Build sequencing (moat-first — revised after the profitability review; supersedes the earlier "trend-pathfinder-first" plan):**
- **Phase 1 = edge validation of the moat first** (cross-sectional fundamental factors on ValuePilot Value Line data). A *lightweight, offline* research backtester proves — net of friction and tax, versus a tax-adjusted passive benchmark — whether the fundamental signal has tradeable alpha. **No execution rails are built until a strategy clears the OOS signal gate ([§14](#14-phased-build-order-small-gated-tasks) 1-R4).**
- **Phase 2 = stateful execution rails** (the time-series/event-driven engine, position management, IBKR adapter) — built **only for strategies that passed Phase 1**, not speculatively.
- Rationale: durable edge plausibly lives in the fundamental data moat, not in crowded cross-asset daily trend; it is irrational to build heavy event-driven plumbing before any edge is validated (principle #5, [§2](#2-decision-log) D9).

---

## 2. Decision log

| # | Decision | Rationale |
|---|---|---|
| D1 | Strategy = declarative, versioned `StrategySpec`; engine generic. | Multi-strategy. Inspired by (not reusing) `rule_json → SQLAlchemy`. |
| D2 | IBKR primary; Fidelity manual fallback adapter. | API, futures/1256, shorting, leverage, multi-asset. |
| D3 | Two archetypes on shared rails. | Time-series regime/trigger ≠ cross-sectional factor. |
| D4 | Cut Bayesian per-position scaling from v1; reserve Bayes for **regime probability** (v-next). | Sizing value hierarchy: base bet-size ≫ exit ≫ scale-in. Bayesian adds optimize the weakest lever with the most overfit surface. |
| D5 | *(ordering superseded by D9)* When the trend archetype IS built, it is cross-asset ETF/futures trend, NOT single-stock candlestick/KDJ. | Trend has documented edge at asset-class level (TSMOM); candlestick/oscillator entries thin OOS. (Content still valid; it is now Phase 2, not first.) |
| D6 | ~~Fundamental moat deferred to MVP-2~~ → **reversed by D9: moat is validated FIRST (Phase 1).** | v4 review: building rails before validating the moat is backwards; edge validation gates rails. |
| **D7** | **2026-07-01 review → REJECT (design-level). v3 resolves 3 should-blocks:** (1) position/event-state model under-scoped → [§8](#8-stateful-position--event-state-model-should-block-1); (2) MVP-2 PIT read contract too vague → [§9](#9-point-in-time-read-contract-for-fundamental-facts-phase-1-moat-validation-should-block-2); (3) `StrategySpec` single union → split into base + siblings → [§5](#5-strategyspec-shared-base--archetype-siblings-should-block-3). Reviewer notes folded into §5–§14. | Prevent look-ahead / `is_current` violation / research-live parity loss before any code is written. |
| **D8** | **v3 re-review → REJECT. Two blockers fixed in v4:** (1) `position_states` nullable-column UNIQUE is not mutually exclusive in PostgreSQL (NULLs are distinct) → replaced with **per-mode partial unique indexes** ([§8](#8-stateful-position--event-state-model-should-block-1)); (2) PIT contract silently look-ahead on `calculated` facts (Piotroski has no `source_document_id` and no populated `as_of_date`, and is computed from `is_current` inputs) → **calculated facts get a recompute-from-PIT-inputs rule** ([§9](#9-point-in-time-read-contract-for-fundamental-facts-phase-1-moat-validation-should-block-2)). Partial-closure items (event-id namespace/replay, partial fills, corp-action mid-position, `signal_values.data_version`) also closed. | Nullable UNIQUE and un-lineaged calculated facts each silently corrupt the invariant they were meant to protect. |
| **D9** | **2026-07-01 re-review → REJECT (profitability-level). v4 resolves engineering blockers, but Part B requires edge gates:** (1) Per-strategy edge thesis; (2) Pre-committed profitability gate (net-of-tax/friction benchmarking); (3) Live edge-decay/drawdown kill-switches; (4) Re-sequenced signals (factor validation first). | Avoid building complex event-driven execution/position plumbing for strategies with no validated edge or negative tax-adjusted net expectancies. |
| **D14** | **2026-07-02 data-constraint amendment (v10).** User can only download Value Line reports **published 2025+**; each report carries a ~10-year restated fundamentals table but **opinion signals (Timeliness/Safety/targets/projections) exist only as of each report date — unrecoverable historically**. Consequences: (1) strict-PIT backtests before 2025 are empty *by design* (the contract correctly exposes this); any use of the 10-year tables runs in an explicit **reconstructed-vintage mode** (synthetic publication lag `period_end_date + 90d`, survivor-stamped, **relative judgments only** — never the absolute-return Go/No-Go, because the corpus contains only 2025 survivors). (2) The VL proprietary signals are **largely reconstructable** from commodity data (Timeliness ≈ 12-1 momentum + SUE/PEAD + earnings trend, per Copeland-Mayers 1982 / Affleck-Graves-Mendenhall 1992; Safety/Fin-Strength/Earnings-Predictability/Price-Stability are mechanical), so **1-R4 is restructured into hypothesis set H1/H2/H3** — H1 VL-proxy composite (testable NOW on full history), H2 VL-actual-vs-proxy residual (forward-only, non-blocking bonus), H3 13F aggregation signals (in-house EDGAR/Oracle's Lens data, testable now). Phase 2 unlocks if **any** of H1/H3 passes the full protocol. (3) Data plan: survivorship-free commodity dataset = **required purchase**; historical VL archive = **optional** (only accelerates H2); **weekly VL archiving starts immediately** (H2's raw material accrues one week at a time and can never be backfilled). | The project must not hinge on the weakest-prior hypothesis (H2); reconstructability converts the moat test from a decade-long wait into a now-runnable experiment plus a forward bonus. |
| **D13** | **v8 → APPROVE (two independent close-out reviews); comprehensive master review adds 1-R0 (blocking).** Empirical check (2026-07-02): dev and prod `metric_facts`/`pdf_documents` are both **0 rows**. With monthly rebalance, `t_HAC ≥ 3` on a 2%/yr incremental α at 4–6%/yr tracking error needs on the order of decades × hundreds-of-stocks cross-sections — a user-uploaded-PDF corpus cannot reach it. Without a data audit + power analysis first, 1-R4 would be **underpowered: unable to pass, unable to falsify** (the worst outcome — months spent, nothing learned). v9 adds **1-R0** as the first, blocking Phase 1 task, and adds an explicit **post-kill fallback path** to the 1-R4 kill rule. | An edge test without statistical power is not a test; data sufficiency must be proven before the moat experiment is run. |
| **D12** | **v7 micro-confirmation → NEEDS-FIX (two reproducibility gaps).** M6: `|t_HAC| ≥ 3` was two-sided vs a directional hypothesis, and the bootstrap lacked a seed policy → v8: **one-sided `t_HAC ≥ 3` with α > 0**, fixed seed `hash(strategy_key, strategy_version, backtest_run_id, holdout_id)`, pass = **lower-5th-percentile α > 0**. M3: DSR inputs + `N` scope were unstated → v8: DSR from observed Sharpe/`T`/skew/kurtosis/base-freq/trial-Sharpe variance, `N` = `backtest_runs` rows sharing `trial_group_id` before holdout unlock; added `trial_group_id`/`trial_index` to §11. | A make-or-break edge test must be reproducible by an independent implementer with zero unstated judgment calls. |
| **D11** | **v6 confirmation → NEEDS-FIX on M3/M6 only.** "Deflation haircut" and "t ≥ 3" were not reproducible for a make-or-break test. v7 fixes the 1-R4 **statistical protocol** to implementation grade: **Newey–West (HAC)** t-stat with a specified lag rule (overlap-robust), or a fully-defined **stationary bootstrap** (joint-vector resample, block length, 10k draws, CI rule); multiple testing via **Benjamini–Hochberg FDR (q=0.05) + Deflated Sharpe Ratio** with the logged trial count. | For overlapping/serially-correlated returns, OLS SEs are biased and a vague "haircut" is unfalsifiable; the one test the whole project hinges on must be reproducible. |
| **D10** | **v5 re-review split (one APPROVE, one REJECT); sided with the stricter review.** The lenient review rubber-stamped a **gameable moat test**; the strict review correctly flagged that "positive IC in isolation" proves nothing and "re-evaluate" is an escape hatch. v6 makes 1-R4 a **controlled spanning regression vs a fixed strong generic null**, with significance + net-of-tax magnitude + investability thresholds, multiple-testing controls, and a **numeric kill rule** (fail → no Phase 2). Also firmed the A2/A3/A4 partials (per-strategy risk/tax-matched benchmark; specified friction/tax model; precise kill-switch drift/window/restart). | The project's core is *sustainable profit*; whether that is real hinges entirely on the moat test being fair and non-gameable. On a split, rigor wins. |

---

## 3. Design principles

1. **Research–live parity.** Signal, position-management, and construction code written once; backtest and live differ only in data feed and in the **run/account scope** of persisted state ([§8](#8-stateful-position--event-state-model-should-block-1)).
2. **Point-in-time strict; missing ≠ 0.** Historical reads reconstruct as-of-T knowledge from **immutable** fields, never the mutable `is_current` flag ([§9](#9-point-in-time-read-contract-for-fundamental-facts-phase-1-moat-validation-should-block-2)).
3. **Layered decoupling + versioning.** Every `StrategySpec` carries `strategy_version`; every backtest run is reproducible.
4. **Configurability demands research integrity.** Guardrails (walk-forward, holdout, run ledger, **pre-frozen parameter families**, plateau-not-peak) are mandatory ([§13](#13-validation--overfitting-discipline)).
5. **No trading rails without validated edge.** Infrastructure development is strictly gated by signal validation. Prioritize cross-sectional factor backtesting (the ValuePilot fundamental moat) before engineering complex event-driven execution/position rails. Every strategy must start with an explicit, falsifiable Edge Thesis.

---

## 4. Strategy-as-config (overview)

Shared signal/factor library → many `StrategySpec` configs → one generic engine (backtest + live) → allocator (v-next) → execution adapter (IBKR / Fidelity). A strategy is data; adding one writes a spec, not engine code.

---

## 5. `StrategySpec`: shared base + archetype siblings (should-block 3)

**Resolved:** a single union schema is split into a shared base plus two archetype-specific sibling schemas. JSON is stored in one column, but **validation, UI, and engine dispatch branch on `archetype`.**

```
StrategySpecBase   { strategy_key, strategy_version, archetype, universe, rebalance, execution }
   ├── TimeSeriesSpec     extends base { regime, filters, entry, position_management }   // event-driven
   └── CrossSectionalSpec extends base { factors, combine, neutralize, sizing, turnover_buffer }  // periodic
```

- **Dispatch:** engine routes on `archetype` to the matching runner ([§10](#10-layered-architecture)).
- **Validation:** each sibling schema validated independently; base fields shared.
- **First schema task's acceptance criterion:** the base/sibling split exists and is enforced; no single validator tries to cover both modes.

Two concrete specs follow in [§6](#6-strategy-archetypes).

---

## 6. Strategy archetypes

### 6.1 Time-series / regime-trigger (Phase 2 — built only if validated) — `TimeSeriesSpec`

Two-level control: a **regime filter** sets a book-level **exposure envelope** (top-down); a **per-holding lifecycle** manages entries/exits within it (bottom-up).

**Arbitration (reviewer-tightened):** the regime envelope is a **hard risk cap that binds immediately**. On a bull→bear flip, forced de-risk to the envelope executes at the **next executable bar / order window**; batching is permitted only as a liquidity/cost tactic and **does not relax the cap** — while a position is above cap it is flagged over-limit until flattened. The cap is never waited-out via natural position-signal exit.

```jsonc
{
  "strategy_key": "cross_asset_trend",
  "strategy_version": 1,
  "archetype": "time_series",
  "universe": { "list": ["SPY","EFA","EEM","TLT","IEF","GLD","DBC"] },
  "regime": {
    "indicator": { "key": "above_sma_200", "params": { "consecutive_days": 20 } },   // params PRE-FROZEN (§13)
    "states": {
      "bull": { "when": "true",  "exposure": { "long_min": 0.80, "gross_long_max": 1.0, "short_allowed": false } },
      "bear": { "when": "false", "exposure": { "long_max": 0.20, "short_allowed": true } }
    }
  },
  "filters": [ { "key": "ema_50_slope", "role": "medium_trend" } ],
  "entry": { "any_of": [
    { "key": "donchian_breakout", "params": { "lookback": 50 } },
    { "key": "sma_cross", "params": { "fast": 20, "slow": 100 } }
  ] },
  "position_management": {
    "base_size":     { "method": "vol_target", "target_vol": 0.10,
                       "kelly_cap": "half_kelly",         // only with credible OOS edge est. — else omit (§7)
                       "gross_cap": 1.0, "per_asset_cap": 0.25, "portfolio_vol_target": 0.10 },
    "pyramid":       { "method": "deterministic", "add_on": "new_high", "max_adds": 3 },
    "trailing_stop": { "method": "chandelier", "atr_mult": 3.0 }
  },
  "rebalance": { "mode": "event_driven", "bar": "1d" },
  "execution": { "broker": "ibkr", "instrument": "etf" }
}
```

### 6.2 Cross-sectional factor (Phase 1 — the moat, validated first) — `CrossSectionalSpec`

```jsonc
{
  "strategy_key": "value_momentum_quality",
  "strategy_version": 1,
  "archetype": "cross_sectional",
  "universe": { "top_mcap": 1500, "exclude": ["micro_cap","recent_ipo"] },
  "factors": [
    { "factor_key": "momentum_12_1", "weight": 0.40, "direction": 1, "transform": "zscore", "winsorize": 0.01 },
    { "factor_key": "fcf_yield",     "weight": 0.35, "direction": 1, "transform": "zscore" },
    { "factor_key": "piotroski_f",   "weight": 0.25, "direction": 1, "transform": "rank" }
  ],
  "combine": "weighted_zscore",
  "neutralize": ["sector","size"],
  "sizing": { "method": "equal_weight", "params": { "n_names": [30,60], "max_position": 0.05 } },
  "turnover_buffer": { "enter_pct": 0.20, "exit_pct": 0.40 },
  "rebalance": { "mode": "periodic", "signal": "monthly", "full": "quarterly" },
  "execution": { "broker": "ibkr", "instrument": "stock" }
}
```

---

## 7. Position sizing & management

By real impact: **base bet-size ≫ exit ≫ scale-in.**

1. **Base size** — `vol_target` per position. **`half_kelly` cap is valid ONLY with a credible, out-of-sample edge estimate**; without it, half-Kelly institutionalizes backtest noise → **omit it and rely on explicit caps.** In all cases specify: `gross_cap` / net leverage cap, `per_asset_cap`, **correlation-aware portfolio-vol target** (not per-asset vol summed), and a **gap-through stress** assumption (stops can fill worse than level).
2. **Exit** — trailing stop (chandelier/ATR/percent), path-dependent, in the stateful layer ([§8](#8-stateful-position--event-state-model-should-block-1)).
3. **Scale-in** — deterministic pyramiding, `max_adds` bounded. **No Bayesian.**

**Bayesian** reserved for a v-next regime upgrade (HMM/Kalman/changepoint → `P(bull | history)` scaling the envelope continuously), not per-position scaling.

---

## 8. Stateful position & event-state model (should-block 1)

**Resolved.** The v2 `position_states(strategy_key, instrument_id, …)` key was under-scoped — multiple versions / backtest runs / accounts would clobber each other and break parity + reproducibility. Revised model:

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

**Mutual exclusion — v4 fix.** A single partial UNIQUE over `(…, backtest_run_id, account_id, instrument_id)` does **not** enforce one open position in PostgreSQL: UNIQUE treats NULLs as *distinct*, so live rows (`backtest_run_id=NULL`) and backtest rows (`account_id=NULL`) can duplicate freely. Use **two per-mode partial unique indexes whose key columns are all non-null in that mode:**

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

Add CHECK constraints so the mode↔scope invariant holds: `mode='backtest'` ⇒ `backtest_run_id NOT NULL AND account_id NULL`; `mode IN ('paper','live')` ⇒ `account_id NOT NULL AND backtest_run_id NULL`. Also add **enum CHECKs** pinning the value domains at the DB level — `mode IN ('backtest','paper','live')` and `status IN ('open','closed')` — so no row can slip both partial indexes via an out-of-domain `mode`/`status` (reviewer A1 bulletproofing). (PostgreSQL 18 is available, so a single index with `NULLS NOT DISTINCT` is a valid alternative, but the per-mode indexes are preferred — all-non-null keys, no reliance on NULL-handling semantics, and they document the two scopes explicitly.)

**Concurrency (NOT last-writer-wins):** live updates use optimistic concurrency — `UPDATE … WHERE id=? AND revision=?`, bump `revision`. Event stream discipline:
- **Event-id namespace:** `last_event_id` is monotonic **within one stream** = `(mode, backtest_run_id | account_id)`. Ids are not comparable across streams (backtest run A's ids say nothing about live account B's).
- **Replay policy:** idempotent — an event whose `last_event_id <= stored` for that stream is a no-op (already applied), not an error.
- **Out-of-order:** the monotonic guard drops any event older than the stored watermark; the runner must feed each stream in order (backtest is naturally ordered; live uses the broker/event-bus sequence).

**Event ordering rules (deterministic; shared by backtest & live):**
1. Signals computed on **bar close** from data ≤ that close (PIT).
2. Orders execute at **next bar** open — never same-bar-close fill.
3. Within a bar, **stop/exit evaluated before entries/adds** (risk before risk-on).
4. **Gap-through:** if the bar opens beyond the stop, fill at the gap open + slippage, not the stop price.
5. **Intrabar stop:** test trigger against bar high/low with a **worst-case intrabar path** assumption (no favorable-extreme-first optimism).
6. **Same-bar stop + add:** stop wins; the add is cancelled.
7. **Regime flip:** evaluated at bar close; forced de-risk executes next executable bar/order window; the risk cap binds immediately (over-cap positions flagged).
8. State (`high_water_mark`, `trailing_stop_level`, `adds_used`) updates **after** fills are known, stamped with `last_event_id` / `last_processed_ts`.
9. **Partial fills:** each fill is its own event and updates state incrementally — `base_qty` accumulates, `entry_price` becomes the **quantity-weighted average**, `revision`/`last_event_id` bump per fill. A position is `open` from the first fill; an unfilled remainder is a resting order, not extra state.
10. **Multi-add ordering:** when several adds qualify on one bar, process them in a **deterministic order** (ascending instrument_id, then rule order in the spec), each stamped; `max_adds` is checked against `adds_used` *as incremented*, so the cap binds mid-bar.
11. **Corporate actions mid-position:** on a split/reverse-split, adjust `base_qty`, `entry_price`, `high_water_mark`, and `trailing_stop_level` by the split ratio **before** that bar's signal/stop evaluation (so the stop isn't spuriously triggered by the raw price jump); cash dividends reduce `high_water_mark`/stop by the ex-dividend amount if the price series is not total-return-adjusted. `price_bars.adj_close` vs raw `close` usage must be explicit in the runner.

---

## 9. Point-in-time read contract for fundamental facts (Phase 1 moat validation; should-block 2)

**Resolved.** Precise contract for reading `metric_facts` in a backtest evaluated as-of date **T**. Grounded in the real code: write-side `_reconcile_parsed_fact_current_slot` (`ingestion_service.py:953`) and read-side `_m3_facts_by_stock` (`dashboard.py:974`); locked semantics in `docs/architecture/metric-facts-is-current.md` and AGENTS.md invariant #2.

1. **Do NOT trust the stored `is_current` flag for historical reads.** `is_current` is **mutable** — reconciliation flips it as newer documents arrive, so its stored value reflects *today's* winner, not knowledge at T. Filtering on `is_current=true` (as `_m3_facts_by_stock` does for the live dashboard) yields **look-ahead** in a backtest.
2. **Publication filter:** join `metric_facts.source_document_id → pdf_documents.report_date`; require `report_date <= T` (fact was published/knowable by T).
3. **Period filter (fiscal series):** require `period_end_date <= T` (the fiscal period had actually closed by T).
4. **As-of currency selection for PARSED facts (`source_type='parsed'`), by category (mirrors locked semantics):**
   - *Fiscal time series* (`per_share.eps`, `is.net_income`, `bs.total_equity`, …): pick the greatest `period_end_date <= T`; tiebreak greatest `report_date <= T`, then `source_document_id`/`id` — the **same winner logic as `_reconcile_parsed_fact_current_slot`, but bounded by `<= T`.**
   - *Opinion / as-of facts* (`target.price_18m.*`, `quality.*`): `period_end_date` is the publication date → pick the latest `report_date <= T`; tiebreak `created_at`/`id`.
5. **Calculated facts (`source_type='calculated'`) — v4 fix. Do NOT read stored calculated `metric_facts` in a backtest.** They are written with `source_document_id=NULL` (no `report_date` to bound by), no populated `as_of_date` / `calculated_run_id` lineage, and are computed from `is_current=True` inputs (`piotroski_f_score.py:112`) — i.e., relative to *today*, not T. `score.piotroski.total` is exactly this case (it was wrongly listed as a fiscal example in v3). **PIT rule: recompute calculated metrics inside the backtest from PIT-correct inputs** — gather the input facts via rules 1–4 (bounded by T), then run the pure calculator (e.g. `build_piotroski_f_score_facts(inputs)`). A stored calculated fact may be read directly **only** if it carries a populated as-of lineage (`calculated_runs.as_of_date` = max input `report_date`), read by `as_of_date <= T`. That lineage is **not** populated today, so Phase 1 recomputes. Never consume a lineage-less calculated fact directly in a historical read. **Calculated-metric execution registry (v5, reviewer B2c):** the backtest engine holds an explicit map from calculated `metric_key` → its pure builder, so recompute works for *every* calculated metric, not just Piotroski — `score.piotroski.*` → `build_piotroski_f_score_facts`; the Value Line ratios (`returns.roa`, `liquidity.current_ratio`, `leverage.long_term_debt_to_capital`, …) → `build_value_line_ratio_facts` (both confirmed lineage-less: `source_document_id=None` at `piotroski_f_score.py:158` and `value_line_ratios.py:146`). A calculated metric that a strategy consumes but that is not in the registry must **fail closed** (error), never fall through to a stored-row read.
6. **Never** enforce or assume one `is_current=True` per `(stock_id, metric_key)`, and **never** author a migration/script demoting by `(stock_id, metric_key)` — forbidden by the locked semantics. This contract is a **read-time as-of reconstruction**, not a change to the currency model.
7. **Missing ≠ 0:** no qualifying fact at T ⇒ factor is *missing* (drop / sector-median impute per the composite's missing policy), never 0. Composite scores may live in `value_json['partial_score']` with `value_numeric=NULL` — extract via the `_fact_value` fallback; don't assume `value_numeric`.

This contract will be promoted to `docs/architecture/` on acceptance ([§15](#15-review-outcome--open-questions)).

---

## 10. Layered architecture

```
DATA           OHLCV / corp actions  |  metric_facts*  StockMaster*  |  benchmark/FF
                         ↓
SIGNAL/FACTOR  indicators (regime/trend/entry)  |  value* quality* momentum lowvol  → signal_values
LIBRARY                  ↓
ENGINE CORE    shared: spec compile, PIT read (§9), cost model, run ledger
                 ↓ dispatch on archetype ↓
   ┌───────────── time_series runner (event-driven, §8) ─────────────┐
   └───────────── cross_sectional runner (periodic) ─────────────────┘
                         ↓  (same core in backtest & live)
ALLOCATOR (v-next)  net N strategies → one book
                         ↓
EXECUTION      IBKR API (+ human-approval gate)  |  Fidelity manual basket
                         ↓
MONITORING     regime/exposure, position lifecycle, drift, attribution | React dashboard*
```

**Engine = shared core + sibling runners** (reviewer note): the two archetypes have different time semantics; do NOT force both into one loop. One core (spec compile, PIT read, costs, ledger) + two runners.

---

## 11. Data model additions (Alembic, repo conventions)

`snake_case` plural, no leading-number keys.

- `price_bars(stock_id, date, open, high, low, close, adj_close, volume)` — split/div adjusted.
- `corporate_actions(stock_id, ex_date, type, ratio_or_amount)`.
- `signal_values(instrument_id, as_of_date, signal_key, signal_family, source, value_numeric, value_json, run_scope, data_version, strategy_version)` — PIT indicator/factor snapshots. `signal_family`/`source` + `run_scope`/`data_version` keep research cache separate from production signals (`data_version` is now an explicit column, not just prose).
- `strategies(strategy_key, strategy_version, archetype, strategy_spec_json, edge_thesis_json, created_at)` — unique `(strategy_key, strategy_version)`; **IntegrityError → typed error** (versions never silently overwritten). `edge_thesis_json` is a **required, non-empty prerequisite** (why the edge exists / persists, capacity, expected decay, turnover + tax drag, benchmark, falsification criteria — [§13](#13-validation--overfitting-discipline)); a spec with no edge thesis cannot be backtest-reviewed.
- `position_states(...)` — see [§8](#8-stateful-position--event-state-model-should-block-1); **optimistic concurrency**, not upsert.
- `broker_holdings(...)` — live positions (renamed from `holdings`, which was too generic).
- `tax_lots(instrument_id, lot_id, open_date, quantity, cost_basis, section_1256_flag)` — LTCG timing, wash-sale, 1256 tagging.
- `target_portfolios(strategy_key, strategy_version, rebalance_date, instrument_id, target_type, target_quantity, target_weight)` — **split** the old `target_weight_or_qty` into typed columns (avoid a mixed-type column).
- `backtest_runs(strategy_key, strategy_version, trial_group_id, trial_index, params_json, metrics_json, net_of_tax_metrics_json, benchmark_json, gate_passed, holdout_flag)` — run ledger. `net_of_tax_metrics_json` + `benchmark_json` + `gate_passed` record the Go/No-Go profitability-gate evaluation ([§13](#13-validation--overfitting-discipline)) so the pass/fail decision is auditable. `trial_group_id`/`trial_index` make the multiple-testing **trial family** and its count `N` an **exact query** (all rows sharing `trial_group_id` before holdout unlock), not a guess — required by the 1-R4 Deflated-Sharpe-Ratio step ([§14](#14-phased-build-order-small-gated-tasks) 1-R4, reviewer M3).

**Write-conflict semantics per table** (per AGENTS.md guidance): `strategies` → IntegrityError→typed (mutual-exclusion on version); research `signal_values`/derived snapshots → idempotent **upsert**; live `position_states` → **optimistic concurrency / event-id guard** (not last-writer-wins).

---

## 12. Tax design (Texas resident)

- **State 0%; only federal.**
- **Equities/ETFs:** short-term ordinary (≤37%); long-term 0/15/20%; **NIIT 3.8%** above MAGI thresholds; wash-sale 30d. IRA vs taxable is the location lever.
- **Futures (via IBKR):** **Section 1256** — 60/40 regardless of holding period, year-end mark-to-market. Blended top federal ≈ 26.8% vs 40.8% short-term equity — a structural edge for a TX resident. Backtester must model 1256 separately from 1099 equity.
- **Reviewer recommendation (pending user confirmation):** **IRA-first** for whatever goes live first. Phase 1 (factor validation) is a US-equity cross-section, so the ETF-vs-futures choice is a **Phase 2** concern; when the trend rails are built, **ETF-only first** (defer futures roll/margin/1256 to a later futures-expansion phase).
- **No Trader Tax Status / no trading entity** (would invite TX franchise tax).
- References: IRS Form 6781 (60/40 + MTM) — https://www.irs.gov/forms-pubs/about-form-6781 , https://www.irs.gov/pub/irs-pdf/f6781.pdf ; NIIT — https://www.irs.gov/individuals/net-investment-income-tax .

---

## 13. Validation & overfitting discipline

Mandatory for the technical archetype:
- **Per-Strategy Edge Thesis:** Every strategy specification must document its economic or behavioral rationale, capacity limit, and expected decay profile *before* backtest results are considered.
- **Pre-freeze the parameter families** before backtesting (200-MA window, confirm days, breakout lookback, ATR multiple, etc.). No peak-hunting across them; changes require a new logged spec version.
- PIT signals ([§9](#9-point-in-time-read-contract-for-fundamental-facts-phase-1-moat-validation-should-block-2)); survivorship-bias-free universe.
- Event-driven realism per [§8](#8-stateful-position--event-state-model-should-block-1) (next-bar fill, gap-through, intrabar worst-case, costs, futures roll + 1256).
- **Walk-forward + out-of-sample holdout**; new specs clear an untouched period before live.
- **Run ledger** (`backtest_runs`, `holdout_flag`): every config tried is recorded (deflated-Sharpe mindset).
- **Parameter plateau, not peak.**
- **Friction & Tax Netting (model must be specified, not just "required" — reviewer A3):** commissions (IBKR schedule); **slippage** = a stated model (e.g. fraction of bid-ask spread + a market-impact term scaled by participation vs ADV); explicit **bid/ask** assumption; **tax-lot holding-period logic** (short vs long, spec-ID lot selection per [§12](#12-tax-design-texas-resident)) so realized short-term vs long-term rates + NIIT are applied per lot; **futures 1256** 60/40 MTM modeled separately; explicit **turnover tax drag**. The **benchmark is computed on the same after-tax basis** (after-tax buy-and-hold), so the comparison is apples-to-apples.
- **Go/No-Go Profitability Gate (pre-LIVE — before any execution adapter is activated; distinct from the 1-R4 research gate that precedes rails).** Thresholds are **pre-registered per strategy in its Edge Thesis** and recorded in `backtest_runs` (`gate_passed`); a strategy that misses any is **killed, not tuned**:
  - Net (of friction + tax) OOS Sharpe > 0.6.
  - Net-of-tax, net-of-friction CAGR beats the strategy's **risk- and tax-matched** passive benchmark by ≥ 1.5%. The benchmark is set **per strategy in the Edge Thesis** (matched on volatility/exposure); SPY buy-and-hold or tax-efficient 60/40 are defaults/floors, not a universal yardstick (reviewer A2).
  - OOS/live max drawdown within the strategy's pre-registered tolerance (set in the Edge Thesis), not merely "≤ in-sample".
  - Positive net-of-tax expectancy confirmed under bootstrap; stable across sub-periods/regimes.
- Metrics: CAGR, Sharpe, **max drawdown**, turnover; time-series → exposure-by-regime + stop behavior; cross-sectional → decile monotonicity + Fama-French regression.

---

## 14. Phased build order (small, gated tasks)

### Phase 1 — Research & Signal Validation (Moat first)
*Goal: Prove that our Value Line fundamental signals contain tradeable, net-profitable alpha BEFORE building execution plumbing.*
- **1-R0 Data-sufficiency audit + power analysis (BLOCKING — added v9 D13; data plan revised v10 D14).** Before any engine code: (a) quantify the actual historical depth and breadth of `metric_facts` (years covered × stocks per monthly cross-section × metric coverage; empirical status 2026-07-02: dev and prod are **empty**); (b) run a pre-registered **power analysis** — given the 1-R4 α threshold (≥2%/yr) and a realistic tracking-error assumption, compute the minimum `T × breadth` needed for `t_HAC ≥ 3` including the holdout split, **per hypothesis H1/H2/H3**; (c) execute the **v10 data plan**: ① **required** — acquire a survivorship-free commodity fundamentals + prices dataset (delisted names included) as the backbone for H1/H3 and the generic null; ② **immediate** — stand up the **weekly Value Line archiving program** (every downloadable report, every week, real `report_date` → natively PIT-correct; this is H2's only raw material and cannot be backfilled); ③ **optional** — historical VL archives (VL institutional historical products; university library holdings) accelerate H2 only; ④ define the **reconstructed-vintage mode** for the 10-year-table data (synthetic publication lag, survivor-stamped, relative-judgments only) as a PIT-contract amendment in 1-R1 scope. **Gate: 1-R1…1-R4 do not start until the audited data meets the power requirement for at least H1.** Running any hypothesis underpowered is forbidden — an inconclusive test burns the holdout for nothing.
- **1-R1 Database PIT Read Engine** — Implement historical PIT read contract (§9 rules 1–4, 6) for parsed facts.
- **1-R2 Calculated-metric registry** — the pure builders already exist (`build_piotroski_f_score_facts`, `build_value_line_ratio_facts`); this task is the **registry that maps each calculated `metric_key` → its builder** and drives recompute-at-read from PIT inputs (§9 rule 5). Mostly wiring, not new calculation logic.
- **1-R3 Cross-Sectional Factor Engine** — lightweight Python/Pandas factor evaluator (decile analysis, IC, turnover estimate, sector/size neutralization, Fama-French exposures). Offline, Docker-run; no execution rails. **Factor library (v10 D14 — the VL-proxy recipes):** each factor is the reconstructable, better-documented equivalent of a VL proprietary indicator — `momentum_12_1`; **SUE/PEAD** (earnings-surprise drift — the documented core of Timeliness); **earnings predictability** (10-yr YoY-EPS-change stability, directly from the parsed annual table); **low-volatility** (Price Stability's modern form); **gross profitability + accruals + Piotroski F** (Financial Strength's mechanical content, partly already computed); composite = the **"VL-proxy" rank**.
- **1-R4 OOS Signal Gate + Moat Hypothesis Set (research gate — before any rails; FAIL = halt Phase 2, do not build).** Sub-gate (a) plus a **hypothesis set (v10 D14)** replacing the single moat test — all pre-registered in the Edge Thesis, evaluated **once** on an untouched final holdout:
  - **(a) Base signal gate:** net-of-friction, net-of-tax OOS Sharpe > 0.6 AND beats the strategy's **risk/tax-matched** passive benchmark (set per strategy in the Edge Thesis; SPY / 60-40 only as a default floor) by ≥ 1.5% net-of-tax CAGR.
  - **(b) Moat hypothesis set — controlled spanning regressions (reviewer M1/M5, hard-blocking).** Each hypothesis regresses its signal portfolio's excess returns on the **same fixed, strong generic null**: FF5 + momentum + a **same-universe** generic value/quality/momentum composite built from commodity fundamentals — identical universe, rebalance cadence, sector/size neutralization, and cost/tax model (no strawman null):
    - **H1 — VL-proxy composite (testable NOW, full history on the survivorship-free commodity backbone):** does the VL-style *combination* (1-R3 library) add α beyond the standard null? Tests the construction, not the data source.
    - **H2 — VL actual-vs-proxy residual (forward-only, NON-blocking bonus):** does Value Line's *published* rank add α beyond our proxy reconstruction (i.e., the analyst-override value)? Runs on the weekly-archived 2025+ corpus at a **pre-registered future evaluation date** once power suffices; it does not gate Phase 2.
    - **H3 — 13F aggregation signals (testable NOW, in-house data):** do Oracle's-Lens-style institutional-holdings signals (conviction clones, crowding, 13F momentum) add α beyond the null? This is the in-house data asset with no commodity equivalent.
    **Phase 2 unlocks if ANY of H1/H3 passes in full.** A hypothesis passes **only if** the intercept α is:
    1. **statistically significant** per the **Statistical protocol** below (HAC t-stat ≥ 3, or a fully-specified bootstrap CI excluding zero), after the pre-registered multiple-testing adjustment (reviewer M3/M6); AND
    2. **economically meaningful net of tax + friction** — annualized net incremental α ≥ a pre-registered threshold (default **≥ 2%/yr**, overridable per strategy); AND
    3. **investable** (reviewer M4) — the incremental α survives the Value Line coverage universe's tradeable liquidity, the realized turnover, and that turnover's short-/long-term tax drag; capacity is an explicit pass/fail, not a footnote.
    **"Positive IC in isolation does NOT pass."**

    **Statistical protocol (pre-registered, reproducible — reviewer M3/M6). Run once on the untouched holdout:**
    - **α significance (overlap-robust, one-sided — the hypothesis is directional α > 0):** the spanning-regression intercept's t-stat uses **Newey–West (HAC) standard errors** with lag `L` = the return-overlap horizon in periods (non-overlapping periodic rebalance → `L = ceil(1.5 × rebalance_interval_periods)`, floor 3). **Pass requires α > 0 AND `t_HAC ≥ 3`** (one-sided, not `|t|`).
      - *Bootstrap alternative (if used instead of HAC), fully specified & deterministic:* **stationary bootstrap (Politis–Romano)** resampling the **joint vector** `(proprietary_portfolio_return, null_factor_returns)_t` to preserve cross-correlation; expected block length = `L`; **10,000** draws; **fixed seed** `seed = hash(strategy_key, strategy_version, backtest_run_id, holdout_id)`; pass only if the **lower 5th percentile of the bootstrapped α distribution is > 0** (one-sided).
    - **Multiple testing (named, fully specified):** the `K` proprietary-signal hypotheses are **pre-registered**; every variant run is logged in `backtest_runs` under a shared `trial_group_id`. Apply **Benjamini–Hochberg FDR at q = 0.05** across the `K` HAC/bootstrap p-values from the significance step; a signal must clear BH-adjusted significance **AND** a **Deflated Sharpe Ratio (Bailey & López de Prado 2014)** computed from the observed (non-annualized) Sharpe, sample length `T`, return **skew** and **kurtosis**, base return frequency, and the **variance / expected-maximum Sharpe estimated from all trial Sharpes in the same pre-registered trial family** — where `N` = count of `backtest_runs` rows sharing that `trial_group_id` **recorded before holdout unlock**. Pass requires DSR-implied **P(skill) ≥ 0.95**. Missing either (BH or DSR) fails.
    - No tuning against the holdout; the protocol executes a single time.
  - **Kill rule (replaces "re-evaluate"):** if sub-gate (a) fails, or **all blocking hypotheses (H1 AND H3) fail**, **Phase 2 rails are not built.** The project halts to rethink the signals — it does **not** tune parameters against the holdout. H2 never blocks; it matures on its own pre-registered schedule. (This research gate is distinct from and precedes the pre-live **Go/No-Go Profitability Gate** in [§13](#13-validation--overfitting-discipline).)
  - **Post-kill fallback (pre-committed, v9; v10 note):** a 1-R4 failure kills the *moat claim*, not the capital plan. The pre-registered fallback is to implement **generic factors without moat claims** as a personal, tax-located (IRA-first), discipline-enforced allocation — for personal capital the bar is beating one's own passive after-tax alternative, not beating institutions. (The former fallback (b) — "pivot to 13F" — is now **H3 inside the gate itself**, per D14.) Base-rate honesty: Value Line rank/opinion effects are among the most-arbitraged documented anomalies — **H2 failing is the likely outcome and is a legitimate, informative result; the project no longer hinges on it.**

### Phase 2 — Stateful Position & Execution Rails (built only for strategies that cleared Phase 1)
*Goal: Build the stateful engine and IBKR execution adapter on shared rails.*
*Product form + PO acceptance: `quant_product_definition_acceptance.md` — Phase 2 tickets must reference checklist P2-A…P2-E (paper mode → kill-switch drill → reconciliation → small-capital go-live); Phase 1 sign-off uses P1-A…P1-H.*
- **2-M0 Schema split** — `StrategySpecBase` + `TimeSeriesSpec`/`CrossSectionalSpec` siblings enforced ([§5](#5-strategyspec-shared-base--archetype-siblings-should-block-3)).
- **2-M1 Data** — OHLCV + corp actions for the selected strategy universe; split/div adjustments.
- **2-M2 Stateful Runner** — Implement the stateful position management model (§8 indexes + constraints, event ordering, optimistic concurrency). **Test ACs (reviewer note):** same-bar stop-then-re-entry, simultaneous cross-instrument fills, and portfolio-cap ordering must each have explicit test coverage.
- **2-M3 Sizing & Stop Logic** — Chandelier stops, deterministic pyramid, envelope hard caps, and tax-lot tracking (§11, §12).
- **2-M4 IBKR Adapter** — Execution adapter with a mandatory manual-approval dashboard gate.
- **2-M5 Monitoring & Decommission Switch** — Regime/exposure dashboard + live edge-decay monitoring. **Decommission Gate (precise — reviewer A4):**
  - **Drift metric:** rolling realized alpha vs the backtest bootstrap distribution, AND cumulative-return divergence beyond the backtest bootstrap CI; **trigger** when live drawdown OR the drift metric exceeds the 99th-percentile backtest bootstrap threshold.
  - **Observation window:** a stated rolling window (e.g. rolling N-month), not a single day.
  - **Halt semantics:** freeze **new entries** + de-risk to the regime exposure floor (not merely an alert).
  - **Restart:** **manual re-validation only** — a halted strategy does not auto-resume; it must clear a fresh gate review before re-activation.

### v-next
Allocator; Bayesian regime estimation; futures/Section 1256 expansion; `mv_optimizer` sizing with a real factor risk model.

---

## 15. Review outcome & open questions

**Review progression:** v2 → REJECT (3 should-blocks) → v3 → REJECT (2 residual blockers) → v4 → REJECT (Part B profitability) → **v5 resolves Part B blockers.**

v3 closed: `StrategySpec` split ([§5](#5-strategyspec-shared-base--archetype-siblings-should-block-3)); the parsed-fact PIT trap ([§9](#9-point-in-time-read-contract-for-fundamental-facts-phase-1-moat-validation-should-block-2) rules 1–4,6,7); engine sibling-runners; reuse precision; naming; governance; and the Quant notes (parameter freeze, sizing caps, flip timing, KPI, tax).

v4 closed:
1. ✅ `position_states` mutual exclusion — v3's nullable-column UNIQUE was not exclusive in PostgreSQL (NULLs distinct). v4 → **per-mode partial unique indexes with all-non-null keys + CHECK constraints** ([§8](#8-stateful-position--event-state-model-should-block-1)). Also closed the partials: event-id namespace/replay/out-of-order; partial fills; multi-add ordering; corporate-action mid-position adjustments.
2. ✅ Fundamental-fact PIT for **calculated facts** — v3 covered only parsed facts; `score.piotroski.total` (`source_document_id=NULL`, no as-of lineage, computed from `is_current` inputs) would silently look ahead. v4 → **recompute calculated metrics from PIT-correct inputs inside the backtest**; never read lineage-less calculated facts directly ([§9](#9-point-in-time-read-contract-for-fundamental-facts-phase-1-moat-validation-should-block-2) rule 5). `signal_values.data_version` also promoted to an explicit column ([§11](#11-data-model-additions-alembic-repo-conventions)).

**v5 closes the Profitability & Sequencing blockers:**
1. ✅ **Edge Thesis Requirement** — Added as a prerequisite to strategy specs (§13).
2. ✅ **Tax & Friction Netting** — Mandatory modeling of trading costs and ordinary/futures tax rates during backtesting (§13).
3. ✅ **Go/No-Go Profitability Gate** — Explicit OOS performance hurdles to pass before building execution adapters (§13).
4. ✅ **Live Edge-Decay Kill-Switch** — Drawdown/drift triggers in monitoring layer (§14).
5. ✅ **Re-sequencing (Moat First)** — Split sequencing into Phase 1 (Research & Signal Validation) and Phase 2 (Execution Rails), moving fundamental factors first (§14).
6. ✅ **Coherence + reviewer-actionable closes:** §1 build-sequencing flipped to moat-first (was contradicting principle #5); D5/D6 annotated as superseded by D9; **calculated-metric execution registry** covering both Piotroski AND `value_line_ratios` (reviewer B2c, §9 rule 5 / 1-R2); `strategies.edge_thesis_json` as a stored prerequisite + gate results in `backtest_runs` (§11); DB **enum CHECKs** on `mode`/`status` (reviewer A1, §8); **differentiated-moat test** in the 1-R4 research gate (proprietary Value Line signals must add incremental alpha over generic factors); Phase-2 test ACs (§14 2-M2).

**v6 closes the v5 re-review's REJECT (1-R4 moat test was gameable) + firms the partials:**
1. ✅ **1-R4 = controlled spanning regression** vs a fixed strong generic null (FF5 + momentum + same-universe generic composite; identical universe/cadence/neutralization/costs) — "positive IC in isolation" no longer passes (reviewer M1/M5, §14 1-R4).
2. ✅ **Numeric kill rule** — α significance (t≥3 / bootstrapped CI, deflation-haircut for variants) + net-of-tax magnitude (default ≥2%/yr) + investability (capacity/liquidity/turnover/tax-drag) pass/fail; **fail → no Phase 2** (replaces "re-evaluate"; reviewer M3/M4/M6).
3. ✅ **A2** — Go/No-Go benchmark is **risk/tax-matched per strategy** (Edge Thesis), SPY/60-40 only defaults (§13).
4. ✅ **A3** — friction/tax model **specified** (slippage model, bid/ask, spec-ID lot holding-period tax, 1256, turnover drag; benchmark after-tax) (§13).
5. ✅ **A4** — kill-switch **precise**: drift metric (realized-vs-backtest-bootstrap), rolling window, halt = freeze new entries + de-risk to regime floor, **manual re-validation to restart** (§14 2-M5).

*Note: the v5 re-review split (one APPROVE, one REJECT). We sided with the stricter review — see [§2](#2-decision-log) D10. On a profitability project, a gameable edge test is the one thing you cannot wave through.*

**v7 tightened the 1-R4 statistical protocol; v8 closed the last two reproducibility gaps** the v7 micro-confirmation found:
- **M6** — one-sided `t_HAC ≥ 3` with **α > 0** (directional); bootstrap now **deterministic** (fixed seed) with a **lower-5th-percentile-α > 0** pass rule.
- **M3** — **Deflated Sharpe Ratio fully specified** (observed Sharpe, `T`, skew, kurtosis, base frequency, trial-Sharpe variance/expected-max) with `N` = `backtest_runs` rows sharing `trial_group_id` before holdout unlock; `trial_group_id`/`trial_index` added to §11.

M1/M5/M4 and A2/A3/A4 were CLOSED at v6; Newey–West HAC / stationary bootstrap and BH-FDR were established at v7 ([§14](#14-phased-build-order-small-gated-tasks) 1-R4, [§2](#2-decision-log) D11/D12).

**v8 → APPROVE (final).** Two independent close-out reviews confirmed M6/M3 CLOSED. A comprehensive master review (2026-07-02) affirmed the engineering with no new defects and added one blocking precondition — **1-R0 data-sufficiency audit + power analysis** ([§2](#2-decision-log) D13) — plus a pre-committed **post-kill fallback** on the 1-R4 kill rule. **v9 = accepted design.** Contracts promoted to `docs/architecture/quant-trading-{pit-read-contract,event-ordering-parity,data-model}.md`; Phase 1 ticket opened (`docs/tasks/2026-07-01_quant-trading-phase-1-research-signal-validation.md`, scope `1-R0…1-R4` only; Phase 2 remains gated on the 1-R4 result).

**Still open (for reviewer discussion — deliberately undecided):**
- Account type IRA vs taxable — reviewer **recommends IRA-first**; confirm.
- Phase 2 (trend rails) instrument: ETF-only vs futures-from-start — reviewer **recommends ETF-only-first**; confirm.
- Cross-asset basket composition + the exact (pre-frozen) regime/trend parameter families.

**On acceptance:** promote the stable **PIT read contract ([§9](#9-point-in-time-read-contract-for-fundamental-facts-phase-1-moat-validation-should-block-2))**, **event-ordering/parity contract ([§8](#8-stateful-position--event-state-model-should-block-1))**, and the data-model contracts to `docs/architecture/` (or a governed `docs/prd/` entry); Phase 1 and 2 tickets then reference them rather than restating.

---

*End of v9 (ACCEPTED 2026-07-02). Implementation begins with Phase 1 ticket `1-R0`; Phase 2 is gated on the 1-R4 result.*
