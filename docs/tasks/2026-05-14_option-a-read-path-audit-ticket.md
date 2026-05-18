# Option A Read-Path Audit — Opinion-Metric Vocabulary Guard

## Status

**Open 2026-05-14.** Filed as a follow-up to PR #33 comprehensive review (Staff Engineer A1 #2, 13F SME Q1 #1, Backend B1). The immediate inconsistency (`_valuation_reference_by_stock` missing the `period_end_date` tiebreak) was fixed in the PR #33 review-response commit; this ticket covers the broader audit + mechanical guard.

## Goal

Mechanize the `metric_facts.is_current` Option A contract (locked 2026-05-14) so a future engineer cannot accidentally ship a screener / formula / new endpoint that reads opinion metrics without the per-period tiebreak.

The locked contract: fiscal metrics keep multiple `is_current=True` rows per `(stock_id, metric_key)`; opinion metrics (`target.price_18m.*`, `proj.long_term.*`, `quality.*`) need the read-side `period_end_date DESC NULLS LAST, created_at DESC` tiebreak.

Today the contract lives in `AGENTS.md` as prose. A new contributor who doesn't read end-to-end can ship a violation that passes review.

## Scope In

### D1 — Opinion-metric registry

New module `backend/app/services/metric_semantics.py`:

```python
OPINION_METRIC_KEYS: frozenset[str] = frozenset({
    "target.price_18m.mid",
    "target.price_18m.low",
    "target.price_18m.high",
    "proj.long_term.low_price",
    "proj.long_term.high_price",
    "quality.earnings_predictability",
    "quality.financial_strength",
    # ... full list from dashboard.py / stocks_13f.py
})
```

The set is the authoritative list of metric_keys for which "most recent publication wins" is the read-side rule.

### D2 — Vocabulary guard on screener + formula engine

`backend/app/services/screener_service.py` and `backend/app/services/formula_engine.py`:

- At the point where a screener rule or formula references a `metric_key`, assert the key is NOT in `OPINION_METRIC_KEYS`.
- If it is, raise a typed error (`OpinionMetricInScreenerError` / `OpinionMetricInFormulaError`) explaining: "Opinion metrics require period-aware reads. Use `_m3_facts_by_stock` from `oracles_lens.dashboard` instead of screener/formula evaluation."

The screener rule_json compiler is the cleanest enforcement point — reject the rule at compile time, not at evaluate time.

### D3 — Unify `_valuation_reference_by_stock` with `_m3_facts_by_stock`

The PR #33 hotfix added the `period_end_date` tiebreak inline. Full unification:

- Migrate `_valuation_reference_by_stock` to call `_m3_facts_by_stock(session, stock_ids, list(VALUATION_REFERENCE_KEYS))` for the fetch.
- Apply the `MANUAL_VALUATION_REFERENCE_KEY` + `source_type == "manual"` post-fetch filter.
- Add `source_type_filter` kwarg to `_m3_facts_by_stock` if cleaner than post-fetch filtering.
- Delete the inline ORM query.

### D4 — Regression test

`backend/tests/unit/test_<TBD>.py`:

- Seed two `is_current=True` rows for `target.price_18m.mid` for the same stock at different `period_end_date` values.
- Assert: legacy Oracle's Lens dashboard, Watchlist 13F detail endpoint, and any other opinion-metric consumer return the **most recent publication's value**, not the most recently inserted row's value.
- Assert: a screener rule referencing an opinion metric_key is rejected at compile time with the typed error.

## Scope Out

- Schema migration (Option B opinion-key allowlist in `_reconcile_parsed_fact_current_slot`) — the design gate is closed at Option A; Option B reopens only if a future opinion-metric consumer cannot use the read-side tiebreak.
- Repointing existing screeners / formulas — the rule audit (D2) will surface violations; remediation happens per-rule via the screener UI, not in this ticket.

## Verification

- `docker compose exec api pytest -q` — full suite green.
- New regression test passes the two-rows-per-key fixture.
- Manual probe: define a screener rule referencing `target.price_18m.mid` → expect compile-time rejection with the typed error.

## Files Expected to Change

- `backend/app/services/metric_semantics.py` (new)
- `backend/app/services/screener_service.py` — vocabulary guard at rule compile
- `backend/app/services/formula_engine.py` — vocabulary guard at formula compile
- `backend/app/services/oracles_lens/dashboard.py` — unify `_valuation_reference_by_stock`
- `backend/tests/unit/test_<opinion_metric_vocabulary_guard>.py` (new)
- `AGENTS.md` — cross-reference the registry from the `is_current` semantics section.

## Sign-Off Trail

- [ ] D1 `OPINION_METRIC_KEYS` registry shipped.
- [ ] D2 screener + formula vocabulary guards + typed errors shipped.
- [ ] D3 `_valuation_reference_by_stock` unified with `_m3_facts_by_stock`.
- [ ] D4 regression test asserting most-recent-publication wins + screener compile-time rejection.
- [ ] pytest -q green; lint + build clean.
- [ ] **Option A Read-Path Audit closed.**
