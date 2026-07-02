# Quant Trading System Architecture — v8 Final Confirmation (1-R4 M3/M6 close-out)

Single-reviewer, close-out pass. The v7 micro-confirmation left exactly two reproducibility gaps and **prescribed the minimal edits**. **v8 applied them.** This pass confirms only that v8 matches the prescription and that no unstated judgment call remains — then Phase 1 opens.

**Under review:** `docs/plans/quant_trading_system_architecture_plan.md` (DRAFT **v8**), §14 1-R4 Statistical protocol block, §11 `backtest_runs`, §2 D12. Nothing else.

**Do NOT re-review** anything else — every other item (Part A engineering blockers, Part B artifacts, M1/M5/M4, A2/A3/A4, HAC/bootstrap + BH-FDR + DSR framing) was CLOSED at v6/v7. Flag only a regression.

**This is the make-or-break gate's close-out.** Confirm the two edits are correct and reproducible; do not raise new scope.

---

## Profitability & Edge Reviewer (Quant Methodologist) — v8 close-out

You prescribed the two v8 edits. Verify they landed correctly.

**Read:** `docs/plans/quant_trading_system_architecture_plan.md` §14 1-R4 (α significance + multiple-testing bullets), §11 `backtest_runs`, §2 D12.

**M6 — directionality + determinism. CLOSED / NEEDS-FIX:**
- Is the HAC test now **one-sided** and directional: pass requires **α > 0 AND `t_HAC ≥ 3`** (not `|t|`)?
- Does the bootstrap now carry a **fixed seed** (`seed = hash(strategy_key, strategy_version, backtest_run_id, holdout_id)`) and a **one-sided pass rule** (lower 5th percentile of bootstrapped α > 0)?

**M3 — DSR reproducibility + N scope. CLOSED / NEEDS-FIX:**
- Does the **Deflated Sharpe Ratio** now name all inputs — observed (non-annualized) Sharpe, sample length `T`, return skew, return kurtosis, base frequency, and the trial-Sharpe variance / expected-maximum from the pre-registered trial family?
- Is **`N`** now an exact query — `backtest_runs` rows sharing `trial_group_id` recorded **before holdout unlock** — and are `trial_group_id` / `trial_index` present in the §11 `backtest_runs` schema?
- Is the BH-**AND**-DSR conjunction unchanged and correct?

**Verdict:**
```
M6: CLOSED / NEEDS-FIX (exact remaining item)
M3: CLOSED / NEEDS-FIX (exact remaining item)
Overall: APPROVE (→ open Phase 1 tickets 1-R1…1-R4 only; Phase 2 gated on 1-R4) / NEEDS-FIX (one-line edit)
```

---

*If APPROVE: promote the §8 (event/parity), §9 (PIT read), and §11 (data) contracts to `docs/architecture/`, then open Phase 1 tickets (`1-R1 … 1-R4`) only. Phase 2 is not opened until a strategy clears the 1-R4 gate. If NEEDS-FIX: it should be a single named line — apply and close.*
