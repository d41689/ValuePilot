# Quant Alpha Roadmap — Data Sources, Research Canon, Strategy Candidates

**Status:** working roadmap (companion to `quant_trading_system_architecture_plan.md` v10).
**Purpose:** the proactive master inventory — which authoritative data/papers we use, what each one builds, and the ranked strategy-candidate portfolio for the goal of **sustained net-of-tax profitability** for a personal account (IBKR primary, Texas federal-only tax).
**Discipline:** everything here is subject to the v10 governance — Edge Thesis prerequisite, pre-frozen parameter families, 1-R4 statistical protocol, kill rules. A candidate listed here is a *hypothesis*, not a commitment.

---

## 1. Data source matrix

| Tier | Source | What it gives us | Role | Cost |
|---|---|---|---|---|
| **In-house (unique)** | Parsed VL weekly archive (2025+, growing weekly) | Proprietary opinion signals with true `report_date` PIT lineage | **H2** raw material — accrues weekly, never backfillable | sunk |
| **In-house (unique)** | EDGAR 13F pipeline + Oracle's Lens (built) | Institutional holdings, conviction/crowding scores | **H3** — our only data asset with no commodity equivalent | sunk |
| **Free** | SEC EDGAR (XBRL Financial Statement Data Sets; Form 4) | Fundamentals cross-check; insider transactions | Enrichment; future insider-signal candidate | 0 |
| **Free** | **Ken French Data Library** | FF3/FF5 + momentum factor returns, industry portfolios | The **null model** for every spanning test — never rebuild what the author publishes | 0 |
| **Free** | **Open Source Asset Pricing** (Chen & Zimmermann) | 200+ published anomaly factor return series | Benchmark our factor implementations; sanity-check H1 construction | 0 |
| **Free** | FRED | Rates, spreads, inflation, recession indicators | Regime features; 1256/financing modeling | 0 |
| **Cheap** | **Sharadar (Nasdaq Data Link) SF1/SEP** — or equivalent | **Survivorship-free** US fundamentals + prices incl. delisted tickers | **The required 1-R0 backbone purchase** (H1/H3 universe + generic null inputs) | ~$50/mo |
| **Cheap** | **Norgate Data** — or equivalent | Survivorship-free prices + **historical index constituent membership** (incl. NDX) | Required for any NDX-universe strategy (S3 breadth, constituent history) | ~$40/mo |
| **Cheap** | Tiingo / Polygon / EODHD | Daily OHLCV APIs, corporate actions | `price_bars` feed redundancy | ~$10–30/mo |
| **Premium (not now)** | CRSP/Compustat (WRDS), IBES, Bloomberg | Gold-standard PIT fundamentals, analyst estimates | Only if the project outgrows Sharadar-class data; IBES would upgrade the SUE factor | $$$ |

**Rule of thumb:** in-house data is for *differentiated* hypotheses (H2/H3); commodity data is for *backbones and nulls*. Never spend parsing effort replicating what $50/mo buys with delisted names included.

## 2. Research canon → what each paper builds here

### Factor construction (1-R3 library)
| Paper | What we implement |
|---|---|
| Jegadeesh & Titman (1993) | `momentum_12_1` |
| Bernard & Thomas (1989/1990) — PEAD | **SUE factor** (standardized unexpected earnings + drift) — the documented core of VL Timeliness |
| Novy-Marx (2013) | gross profitability (quality leg) |
| Sloan (1996) | accruals (quality leg, negative sign) |
| Piotroski (2000) | F-score — **already built** in ValuePilot |
| Frazzini & Pedersen (2014) BAB; Blitz & van Vliet (2007) | low-beta / low-vol leg |
| Asness, Moskowitz & Pedersen (2013) *Value and Momentum Everywhere* | rationale for negatively-correlated composite construction |
| Fama & French (1993; 2015) + Carhart (1997) | the **fixed generic null** in every spanning regression |

### Value Line specifically
| Paper | Takeaway we act on |
|---|---|
| Black (1973) | the original VL-effect claim |
| Copeland & Mayers (1982) | effect shrinks when properly measured |
| Affleck-Graves & Mendenhall (1992) | VL rank changes cluster on earnings surprises — **Timeliness ≈ PEAD** → justifies the H1 proxy design and the H2 residual framing |

### 13F / institutional holdings (H3)
| Paper | Signal we test |
|---|---|
| Cohen, Polk & Silli (2010) *Best Ideas* | managers' most-concentrated positions outperform → **conviction-clone** factor |
| Cremers & Petajisto (2009) | active share → manager selection for clones |
| 13F replication literature (clone-portfolio studies) | quarterly-lagged clone viability net of the 45-day filing delay — the delay must be modeled exactly (we already track filing deadlines) |

### Trend / leverage rotation (S3)
| Paper | What we take |
|---|---|
| Moskowitz, Ooi & Pedersen (2012) TSMOM; Hurst, Ooi & Pedersen (2017) *A Century of Evidence* | time-series momentum is real at asset-class level; long flat stretches expected |
| Faber (2007) | 10-month SMA tactical framework |
| **Gayed (2016) *Leverage for the Long Run*** (Dow Award) | **the S3 blueprint**: MA regime filter works for *leveraged* equity because above-MA regimes have systematically **lower realized volatility** — leverage + low vol is the only regime where daily-rebalance decay math works |

### Methodology (already codified in v10 §14, cite-for-implementation)
| Paper | Where it lives |
|---|---|
| Harvey, Liu & Zhu (2016) | the `t ≥ 3` bar |
| Bailey & López de Prado (2014) | Deflated Sharpe Ratio inputs |
| Benjamini & Hochberg (1995) | FDR q=0.05 |
| Politis & Romano (1994) | stationary bootstrap |
| Newey & West (1987) | HAC standard errors |
| López de Prado (2018) *Advances in Financial ML* | walk-forward / purged CV hygiene for 1-R3 |

## 3. Strategy candidate portfolio (ranked by edge-honesty × implementability)

| # | Strategy | Archetype | Hypothesis | Account | Status |
|---|---|---|---|---|---|
| S1 | **VL-proxy cross-sectional composite** (momentum+SUE+quality+low-vol+earnings-predictability) | cross_sectional | H1 | IRA (turnover shielded) | Phase 1 primary |
| S2 | **13F conviction/crowding overlay** — quarterly clone tilt on Oracle's Lens scores | cross_sectional | H3 | taxable-friendly (low turnover) | Phase 1 co-primary |
| S3 | **Regime-gated leverage rotation (NDX)** — see §4 | time_series | own Edge Thesis (risk-premium timing, not moat) | IRA preferred | candidate — needs full §4 kill-tests |
| S4 | PEAD event tilt (earnings-date driven) | event overlay on S1 | extension of H1 | IRA | v-next (needs earnings-calendar data) |
| S5 | Cross-asset futures trend + Section 1256 | time_series | TSMOM (documented) | taxable (60/40) | v-next (original Phase 2 pathfinder content) |

Portfolio shape when live: S1 as IRA core; S2 as taxable satellite; S3 as a **risk-budgeted sleeve ≤ 15% NAV with a hard sleeve-level stop**; S4/S5 later. Every strategy passes its own gates independently — no strategy inherits another's validation.

## 4. S3 deep-dive: "analyze NDX, trade 3x QQQ" — the honest math

**User's proposal:** use Nasdaq-100 indicators for the signal, execute with 3x long (TQQQ) or 3x short (SQQQ). Verdict: **the long side is a legitimate, literature-backed strategy family (Gayed 2016) IF regime-gated and vol-gated; the short side via holding SQQQ is structurally broken and is replaced by cash.**

### 4.1 Why naive 3x buy-and-hold fails — volatility decay
A daily-rebalanced L× fund compounds approximately at
`g_L ≈ L·g_1 + (L − L²)/2 · σ²`
so for L=3 the structural drag is **−3σ² per year**. At NDX vol σ=20% → −12%/yr drag; at σ=35% (bear regimes) → **−37%/yr** — direction can be right and the position still bleeds to death. 2022 is the canonical case: grinding decline + high vol chewed both TQQQ *and* SQQQ holders.

### 4.2 Why regime gating changes the math (Gayed's insight)
The 200-DMA filter is not a return-timing signal — it is a **volatility regime classifier**: above-MA days have historically materially lower realized vol than below-MA days (vol clustering is the most robust stylized fact in equity data). Leverage is applied only in the low-vol regime where the −3σ² drag is small relative to 3× the drift; in the high-vol regime the position is **cash, not short**.

### 4.3 The SQQQ rule
Holding an inverse-leveraged ETF beyond days fights three headwinds at once: the same −3σ² decay (worse — bear regimes are high-σ), the index's positive long-run drift, and financing/ER costs. **Bear regime = de-risk to cash/T-bills.** If short exposure is ever wanted, it is expressed with defined-risk options or futures in v-next — never by holding SQQQ.

### 4.4 Draft Edge Thesis (S3) — parameters PRE-FROZEN before any backtest
```jsonc
{
  "strategy_key": "ndx_leverage_rotation",
  "archetype": "time_series",
  "universe": { "list": ["TQQQ", "QQQ", "CASH"] },          // NO SQQQ
  "regime": {
    "indicator": { "key": "above_sma_200", "on": "NDX/QQQ total-return", "confirm_days": 5 },
    "states": {
      "bull":  { "hold": "TQQQ" },
      "bear":  { "hold": "CASH" }
    }
  },
  "vol_gate": {                                              // second, principled gate
    "measure": "realized_vol_20d_annualized",
    "rule": "leverage = min(3, target_vol / realized_vol)",  // vol-targeted de-lever
    "hard_cap": "realized_vol > 30% → max 1x (QQQ) or cash"
  },
  "execution": { "signal": "close", "trade": "next_open", "broker": "ibkr" },
  "risk": { "sleeve_max_nav": 0.15, "sleeve_hard_stop_dd": 0.35, "restart": "manual re-validation" }
}
```
Edge classification: **risk-premium timing / convexity harvesting**, not informational alpha — priced accordingly (benchmark = risk-matched, not SPY flat).

### 4.5 Pre-registered kill-tests (must survive ALL, in reconstructed backtest)
1. **Synthetic 3x reconstruction** — TQQQ launched 2010-02; pre-2010 series must be built as daily `3 × NDX-TR − financing(FFR + spread) − ER(0.95%)/252`, validated ≥0.99 correlation vs actual TQQQ 2010+ before use.
2. **2000–2002**: NDX −83%; the gate must exit early enough that the sleeve survives (this period kills most naive variants).
3. **2008** and **2020-03**: gap-through behavior — regime exit at next open after signal, with realistic overnight gaps.
4. **2011, 2015–16, 2018Q4, 2022**: whipsaw clusters — count round-trips; net-of-cost, net-of-tax drag of false signals must leave the strategy ahead of buy-and-hold QQQ on risk-matched terms.
5. **Tax location test**: signal frequency × short-term rates in taxable vs IRA — expected conclusion: IRA sleeve.
6. Standard v10 protocol: holdout, deflated Sharpe, parameter plateau (200±40 DMA, confirm 3–10d must all be profitable — a knife-edge 200/5 config is a fail).

### 4.6 Creative extensions (pre-registered as separate spec versions, NOT tuned in)
- **Breadth confirm:** % of NDX constituents above their own 200-DMA (needs Norgate constituent history) as a second regime vote.
- **VIX/VXN term structure:** backwardation as an early de-risk trigger (faster than price MA).
- **Continuous vol-targeting** (already in the spec) instead of binary 3x/0x — more Sharpe-efficient than the pure Gayed switch, at slightly higher turnover.

## 5. Forward-accumulation programs (start now; each week missed is unrecoverable)
1. **Weekly VL report archive** (H2) — automated scheduler job + missed-week alert (in Phase 1 ticket 1-R0).
2. **NDX constituent snapshots** (S3 breadth) — weekly membership + per-constituent 200-DMA state (cheap once Norgate is live; snapshot ours anyway).
3. **VXN / VIX term-structure daily closes** (S3 extension) — free from CBOE.

## 6. What we deliberately do NOT do
- No options market-making, no HFT, no crypto sleeve (horizon/infrastructure mismatch).
- No ML-first alpha mining (feature soup on 18 months of moat data is p-hacking with extra steps); ML is admissible later for *combining* validated signals, per López de Prado hygiene.
- No SQQQ holding, no unhedged single-name leverage, no margin beyond the sleeve budget.
- No strategy skips the Edge Thesis / 1-R4-class gate because it "obviously works".
