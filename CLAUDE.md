# ValuePilot — Claude Code Guidelines

## Database schema changes

### Rule: schema constraints must be fixed at the schema level

When runtime code hits a DB constraint violation (column too short, wrong type, missing index, etc.), the correct fix is **always a migration**, not a code-level workaround.

**Wrong (band-aid):**
```python
# Silently truncates data to fit the column
source=source[:20]
```
```python
# Renaming a string constant to sneak under the limit
source = "sec_co_tickers"   # was "edgar_company_tickers" (21 chars → 20 limit)
```

**Right:**
1. Write an Alembic migration to fix the column definition:
   ```python
   op.alter_column("table", "column",
       existing_type=sa.String(20),
       type_=sa.String(50),
       existing_nullable=True)
   ```
2. Update the SQLAlchemy model (`String(20)` → `String(50)`).
3. Remove every code-level guard/truncation introduced as a workaround.
4. Apply with `alembic upgrade head`.

**Why:** band-aids hide the root cause, silently truncate data, and leave the system in a state where any new value longer than the limit will fail again — or worse, succeed silently with corrupted data.

---

## Alembic conventions

- Migration filename: `YYYYMMDDHHMMSS-<slug>.py`
- `down_revision` must match the **`revision` variable** inside the parent file, not the filename.
- Always verify applied with `\d <table>` in psql after running `alembic upgrade head`.

---

## EDGAR / 13F pipeline

- `shrsOrPrnAmt` is a wrapper element in infotable XML; unwrap it to read `sshPrnamt` / `sshPrnamtType`.
- `xslForm13F_X02/` paths in EDGAR filing index are XSLT-rendered HTML, not machine-readable XML — skip them when scanning for infotable URLs.
- `cusip_ticker_map.source` is VARCHAR(50); valid source strings: `"openfigi"`, `"sec_co_tickers"`, `"manual"`. Dataroma is not a CUSIP or security-identity source.
- Kahn Brothers (`0001039565-*`) reports values in dollars, not thousands — reconciliation warnings for this filer are True Positives, not bugs.

---

## Write-conflict handling: upsert vs IntegrityError

ValuePilot uses two distinct patterns for handling write conflicts, and the choice between them is **semantic**, not stylistic. Recorded here per MVP5-06 so the next contributor doesn't re-litigate it.

**Use ORM upsert (`INSERT ... ON CONFLICT (...) DO UPDATE`) when:**

- The write is idempotent: re-running it with the same inputs is supposed to produce the same row.
- "Last writer wins" is the correct semantics — there's no domain meaning to "I lost the race."
- Example: `oracles_lens_signals` recompute (MVP4-01 / MVP4-03). Two concurrent scoring runs against the same `(stock_id, report_quarter, score_version)` should agree on the result; one overwriting the other is fine.

**Use `IntegrityError → typed error translator` when:**

- The conflict carries domain meaning — "another instance is already active" — that callers must distinguish from success.
- The unique index is a mutual-exclusion lock, not a deduplication hint.
- Example: `JobRun.lock_key` races (MVP3-05 batch reparse, MVP3-07 historical backfill). The losing caller must abort with a typed `HistoricalBackfillError("already running")` so the API returns a 409, not silently latches onto the winner's run.

**Anti-pattern to avoid:** upserting a JobRun row to "steal" an active lock. That destroys the lock's mutual-exclusion guarantee and lets two workers stomp the same job. Similarly, raising `IntegrityError` for idempotent score writes spams logs with non-events.

When adding a new table with a unique constraint, write the rationale next to the constraint definition in the model so the choice survives a future refactor.

---

## `metric_facts.is_current` semantics (locked 2026-05-14)

`metric_facts.is_current=True` is **per-period currency**, NOT one row per `(stock_id, metric_key)`. Two metric categories share the column and have different uniqueness contracts:

**Fiscal time series** — `per_share.eps`, `is.net_income`, `score.piotroski.total`, `bs.total_equity`, `leverage.long_term_debt_to_capital`, etc. Each FY/Q row is genuinely "current for that period". ADBE has 42 `is_current=True` rows for `per_share.eps` by design — one per fiscal year. The existing reconciliation (`_reconcile_parsed_fact_current_slot` in `ingestion_service.py`) scopes uniqueness to `(stock_id, metric_key, period_type, period_end_date, source_type)`.

**Opinion / as-of facts** — `target.price_18m.*`, `proj.long_term.*`, `quality.earnings_predictability`, `quality.financial_strength`, etc. `period_end_date` is effectively the publication date, not a fiscal period. Multiple `is_current=True` rows coexist when Value Line re-publishes; older publications are NOT automatically demoted.

**Locked design (PO 2026-05-14, Option A):** status quo + read-side tiebreak. Opinion-metric staleness is handled at the read layer via `_m3_facts_by_stock` in `oracles_lens/dashboard.py` (tiebreak `period_end_date DESC NULLS LAST, created_at DESC`), surfaced in UI as `(VL report dated YYYY-MM-DD)`. Rationale: financial-data accuracy first principle is "do not break the original time-series facts".

**Never** add a cleanup migration, Alembic op, or one-off script that enforces "at most one `is_current=True` per `(stock_id, metric_key)`" without scoping by metric category. Naive global dedup wipes ~99% of fiscal time series and breaks the Piotroski calculator, screener, formula engine, and Oracle's Lens quality overlay — all of which read per-period `is_current=True` rows intentionally.

If a future opinion-metric consumer cannot use the read-side tiebreak pattern, reopen the design gate (`docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md`) for Option B (opinion-key allowlist in `_reconcile_parsed_fact_current_slot`). Do not implement Option B without that gate reopening.
