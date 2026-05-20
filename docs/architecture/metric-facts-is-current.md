# `metric_facts.is_current` semantics (locked 2026-05-14)

Detail behind **AGENTS.md → Critical invariant #2**. Read this before touching
anything that writes, demotes, or deduplicates `metric_facts.is_current`.

`metric_facts.is_current=True` is **per-period currency**, NOT one row per
`(stock_id, metric_key)`. Two metric categories share the column with different
uniqueness contracts:

- **Fiscal time series** — `per_share.eps`, `is.net_income`,
  `score.piotroski.total`, `bs.total_equity`,
  `leverage.long_term_debt_to_capital`, etc. Each FY/Q row is genuinely "current
  for that period". ADBE has 42 `is_current=True` rows for `per_share.eps` by
  design — one per fiscal year. The existing reconciliation
  (`_reconcile_parsed_fact_current_slot` in `ingestion_service.py`) scopes
  uniqueness to `(stock_id, metric_key, period_type, period_end_date,
  source_type)`.
- **Opinion / as-of facts** — `target.price_18m.*`, `proj.long_term.*`,
  `quality.earnings_predictability`, `quality.financial_strength`, etc.
  `period_end_date` is effectively the publication date, not a fiscal period.
  Multiple `is_current=True` rows coexist when Value Line re-publishes; older
  publications are NOT automatically demoted.

**Locked design (PO 2026-05-14, Option A):** status quo + read-side tiebreak.
Opinion-metric staleness is handled at the read layer via `_m3_facts_by_stock`
in `oracles_lens/dashboard.py` (tiebreak `period_end_date DESC NULLS LAST,
created_at DESC`), surfaced in UI as `(VL report dated YYYY-MM-DD)`. Rationale:
financial-data accuracy first principle is "do not break the original
time-series facts".

**Never** add a cleanup migration, Alembic op, or one-off script that enforces
"at most one `is_current=True` per `(stock_id, metric_key)`" without scoping by
metric category. Naive global dedup wipes ~99% of fiscal time series and breaks
the Piotroski calculator, screener, formula engine, and Oracle's Lens quality
overlay.

If a future opinion-metric consumer cannot use the read-side tiebreak pattern,
reopen `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md`
for Option B (opinion-key allowlist). Do NOT implement Option B without that
gate reopening.
