# Watchlist Piotroski F-Score Display

## Goal / Acceptance Criteria
- Show each watchlist stock's latest three fiscal-year Piotroski F-Score totals on `http://localhost:3001/watchlist`.
- Use `metric_facts` rows with `metric_key = score.piotroski.total`, `source_type = calculated`, and `is_current = true`.
- Include complete numeric totals and partial diagnostic totals without making partial rows look like complete scores.
- Keep the display compact enough for repeated watchlist scanning.

## Scope
In:
- Backend watchlist members API payload.
- Frontend watchlist table rendering.
- Piotroski FY-only guard needed to keep non-annual snapshot facts out of the 3-year watchlist series.
- Value Line `Return on Total Cap'l` mapping needed so ROA-based Piotroski proxy fallback can use the report field.
- Value Line annual `Long-Term Debt` mapping and debt-to-capital ratio needed so leverage-declining can use a more stable fallback than absolute debt.
- Value Line annual `Long-Term Debt` blank cells should be stored as zero only when the annual debt row exists and the per-year cell is blank/null.
- Value Line `Current Position` totals needed to calculate current ratio improvement when annual current assets/liabilities are not in the annual table.
- Value Line capital-turnover proxy needed for asset-turnover improvement when total assets are unavailable.
- Focused backend/frontend tests where existing test harness supports it.

Out:
- New UI routes or detailed component drilldowns.
- Screener changes.

## Files to Change
- `backend/app/api/v1/endpoints/stock_pools.py`
- `backend/app/services/calculated_metrics/piotroski_f_score.py`
- `backend/app/services/calculated_metrics/value_line_ratios.py`
- `backend/tests/unit/test_metric_facts_mapping_spec.py`
- `backend/tests/unit/test_piotroski_f_score.py`
- `backend/tests/unit/test_stock_pools_api.py`
- `backend/tests/unit/test_value_line_ratios.py`
- `docs/metric_facts_mapping_spec.yml`
- `frontend/app/(dashboard)/watchlist/page.tsx`
- `frontend/components/layout/AppShell.tsx`
- `frontend/lib/watchlistState.js`
- `frontend/lib/watchlistState.d.ts`
- `frontend/lib/watchlistState.test.js`
- This task log

## Test Plan
- `docker compose exec api pytest -q tests/unit/test_stock_pools_api.py`
- `docker compose exec api pytest -q tests/unit/test_metric_facts_mapping_spec.py`
- `docker compose exec api pytest -q tests/unit/test_piotroski_f_score.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_ratios.py`
- `docker compose exec web node --test lib/watchlistState.test.js`
- Broader targeted checks if touched code requires it.

## Progress Notes
- 2026-04-27: Created task log before code changes.
- 2026-04-27: Added `piotroski_f_scores` to watchlist member API rows from current calculated `score.piotroski.total` facts.
- 2026-04-27: Added compact 3-year F-Score display to the watchlist table, including partial diagnostic scores.
- 2026-04-27: Added backend and frontend helper tests.
- 2026-04-27: Replaced per-row Piotroski total lookup with one batched query per watchlist member request.
- 2026-04-27: Browser-checked `/watchlist`; fixed narrow-viewport horizontal overflow by constraining dashboard flex/grid children and keeping the wide table scroll inside its card.
- 2026-04-27: Moved F-Score next to Company so the requested signal stays visible before lower-priority price/fair-value columns on narrower screens.
- 2026-04-27: Restricted watchlist F-Score rows to historical/non-estimate totals so future Value Line estimates do not appear as "past 3 years".
- 2026-04-27: Added a Piotroski calculator guard so non-FY snapshot/opinion facts cannot produce FY score rows.
- 2026-04-27: Changed the F-Score cell formatter to render one fiscal year per line for cleaner table scanning.
- 2026-04-27: Added mapping for Value Line `Return on Total Cap'l` to `returns.total_capital`, stored as a normalized ratio and used as a documented ROA proxy.
- 2026-04-27: Added Piotroski regression coverage for `returns.total_capital` fallback on ROA positive/improving components.
- 2026-04-27: Backfilled `returns.total_capital` from existing watchlist documents and recalculated current watchlist F-Scores so `roa_improving` is now included in the displayed partial totals.
- 2026-04-27: Added mapping for annual Value Line `Long-Term Debt` to FY `cap.long_term_debt`.
- 2026-04-27: Added `leverage.long_term_debt_to_capital = cap.long_term_debt / (bs.total_equity + cap.long_term_debt)` as a Value Line proxy ratio.
- 2026-04-27: Updated `score.piotroski.leverage_declining` priority to use standard debt/assets first, then debt/capital, then absolute debt.
- 2026-04-27: Backfilled annual `cap.long_term_debt` from existing watchlist documents and recalculated current watchlist F-Scores so leverage-declining is now included where enough debt/equity history exists.
- 2026-04-27: Started adding Current Position current-ratio inputs and a capital-turnover proxy for asset-turnover improvement.
- 2026-04-27: Added `Current Position` mappings for `bs.current_assets` and `bs.current_liabilities`; only four-digit annual labels are treated as FY inputs.
- 2026-04-27: Added `efficiency.capital_turnover = is.sales / (bs.total_equity + cap.long_term_debt)` as a documented Value Line proxy for asset-turnover improvement.
- 2026-04-27: Updated `score.piotroski.asset_turnover_improving` priority to use standard asset turnover first, then capital turnover for non-insurance companies.
- 2026-04-27: Backfilled Current Position facts for current watchlist documents and recalculated ratio/Piotroski facts.
- 2026-04-27: Confirmed reviewer N+1 finding is already addressed by `_piotroski_scores_for_stocks`, which batches watchlist F-Score totals in one query.
- 2026-04-27: Started implementing blank annual `Long-Term Debt` cells as zero-valued facts with explicit method metadata.
- 2026-04-27: Added `null_as_zero` mapping support and applied it only to annual Value Line `Long-Term Debt`; zero-filled facts include `method = blank_value_line_debt_cell_as_zero`.
- 2026-04-27: Backfilled long-term debt facts for current watchlist documents and recalculated ratio/Piotroski facts.

## Verification
- `docker compose exec api pytest -q tests/unit/test_stock_pools_api.py` -> pass (`2 passed`).
- `docker compose exec api pytest -q tests/unit/test_metric_facts_mapping_spec.py::test_mapping_spec_maps_value_line_return_on_total_capital_proxy` -> pass (`1 passed`).
- `docker compose exec api pytest -q tests/unit/test_metric_facts_mapping_spec.py::test_mapping_spec_uses_value_line_fiscal_year_end_month_for_fy_facts tests/unit/test_value_line_ratios.py::test_build_value_line_ratio_facts_calculates_standard_ratios_with_lineage tests/unit/test_piotroski_f_score.py::test_build_piotroski_f_score_facts_uses_debt_to_capital_for_leverage_proxy` -> pass (`3 passed`).
- `docker compose exec api pytest -q tests/unit/test_metric_facts_mapping_spec.py tests/unit/test_piotroski_f_score.py tests/unit/test_stock_pools_api.py` -> pass (`12 passed`).
- `docker compose exec api pytest -q tests/unit/test_metric_facts_mapping_spec.py tests/unit/test_value_line_ratios.py tests/unit/test_piotroski_f_score.py tests/unit/test_stock_pools_api.py` -> pass (`16 passed`).
- `docker compose exec api pytest -q tests/unit/test_piotroski_f_score.py tests/unit/test_stock_pools_api.py` -> pass (`8 passed`).
- `docker compose exec api pytest -q tests/unit` -> pass (`145 passed`).
- `docker compose exec web node --test lib/watchlistState.test.js` -> pass (`4 passed`).
- `git diff --check` -> pass.
- Browser check at `http://localhost:3001/watchlist` after login -> pass; F-Score column is visible next to Company, and current watchlist rows show historical 2024/2023/2022 partial F-Score values after local recalculation.
- Browser check after `returns.total_capital` backfill -> pass; FICO shows `6/6 partial`, ASML shows `5/6 partial`, and FNV shows `4/6 partial` for 2024/2023/2022.
- Browser check after leverage-declining backfill -> pass; FICO shows `6/7`, `7/7`, `6/7`; ASML shows `6/7` for all three years; FNV remains `4/6` because recent annual debt history is missing.
- `docker compose exec api pytest -q tests/unit/test_metric_facts_mapping_spec.py::test_mapping_spec_maps_current_position_totals_for_current_ratio tests/unit/test_value_line_ratios.py::test_build_value_line_ratio_facts_calculates_standard_ratios_with_lineage tests/unit/test_piotroski_f_score.py::test_build_piotroski_f_score_facts_uses_capital_turnover_for_asset_turnover_proxy` -> first run failed as expected before implementation, then pass (`3 passed`).
- `docker compose exec api pytest -q tests/unit/test_metric_facts_mapping_spec.py tests/unit/test_value_line_ratios.py tests/unit/test_piotroski_f_score.py tests/unit/test_stock_pools_api.py` -> pass (`18 passed`).
- Browser check after Current Position/capital-turnover backfill -> pass; watchlist shows FICO `2024: 7/8 partial`, `2023: 7/8 partial`, `2022: 6/8 partial`; ASML `2024: 7/9`, `2023: 6/8 partial`, `2022: 7/8 partial`; FNV `2024: 4/7 partial`, `2023: 4/6 partial`, `2022: 4/6 partial`.
- `docker compose exec api pytest -q tests/unit` -> pass (`147 passed`); rerun after adding the annual-label guard for Current Position.
- `docker compose exec api pytest -q tests/unit/test_metric_facts_mapping_spec.py::test_mapping_spec_maps_blank_value_line_long_term_debt_cells_as_zero` -> first run failed as expected before implementation, then pass (`1 passed`).
- `docker compose exec api pytest -q tests/unit/test_metric_facts_mapping_spec.py tests/unit/test_value_line_ratios.py tests/unit/test_piotroski_f_score.py tests/unit/test_stock_pools_api.py` -> pass (`19 passed`).
- Recalculation after blank-debt backfill -> FNV shows `2024: 4/9`, `2023: 5/8 partial`, `2022: 4/8 partial`; FICO remains `2024: 7/8 partial`, `2023: 7/8 partial`, `2022: 6/8 partial`.
- `docker compose exec api pytest -q tests/unit` -> pass (`148 passed`).
- `git diff --check` -> pass.
- `docker compose exec web npm run build` -> fails on existing `/404` prerender issue: `<Html> should not be imported outside of pages/_document`; compile and type-check completed before the existing prerender failure.
