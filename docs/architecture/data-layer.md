# Data layer — detail

Detail behind **AGENTS.md → "Data layer"** and Critical invariants #1 and #3.
For `is_current` semantics see
[`metric-facts-is-current.md`](./metric-facts-is-current.md).

## Stock identity resolution

Stocks are global master data. Ingestion logic:

1. Match by `ticker` + `exchange`.
2. If matched, compare `company_name` similarity.
3. If similarity is low, set `pdf_documents.identity_needs_review = true`.
   **DO NOT** auto-link without confirmation.

## Data integrity + manual corrections

- **Immutability**: parsed records in `metric_extractions` are immutable.
- **Manual corrections** (user edits a parsed value):
  1. DO NOT update `metric_extractions`.
  2. Insert a NEW row into `metric_facts` with `source_type = 'manual'` and
     `is_current = true`.
  3. Demote the prior row scoped to the same `(stock_id, metric_key,
     period_type, period_end_date, source_type='manual')` to
     `is_current = false`. Match the reconciliation pattern in
     `_reconcile_parsed_fact_current_slot`. **DO NOT** demote rows that differ in
     `period_end_date` — per-period currency is the contract (see
     [`metric-facts-is-current.md`](./metric-facts-is-current.md)).

## Schema changes — no band-aids

When runtime code hits a DB constraint violation (column too short, wrong type,
missing index, etc.), the correct fix is **always a migration**, not a
code-level workaround.

**Wrong:**
```python
source = source[:20]                    # silently truncates data
source = "sec_co_tickers"               # renamed to sneak under a 20-char limit
```

**Right:**
1. Alembic migration: `op.alter_column("table", "column", existing_type=sa.String(20), type_=sa.String(50), existing_nullable=True)`.
2. Update the SQLAlchemy model to match.
3. Remove every code-level guard/truncation introduced as a workaround.
4. Apply with `alembic upgrade head`.

**Why:** band-aids hide root causes, silently truncate data, and leave the
system in a state where any new value longer than the limit will fail again — or
worse, succeed silently with corrupted data.

## Alembic conventions

- Filename: `backend/alembic/versions/YYYYMMDDHHMMSS-<slug>.py`. Use the
  `Create Date` timestamp from the revision header. Keep `<slug>` readable.
- `down_revision` must match the **`revision` variable** inside the parent file,
  not the filename.
- Never change `revision` / `down_revision` identifiers when renaming a file.
- Always verify applied state with `\d <table>` in psql after
  `alembic upgrade head`.

## Write-conflict handling: upsert vs IntegrityError

Two distinct patterns; the choice between them is **semantic**, not stylistic.

**Use ORM upsert (`INSERT ... ON CONFLICT (...) DO UPDATE`) when:**

- The write is idempotent: re-running with the same inputs is supposed to
  produce the same row.
- "Last writer wins" is the correct semantics — there's no domain meaning to
  "I lost the race."
- Example: `oracles_lens_signals` recompute. Two concurrent scoring runs against
  the same `(stock_id, report_quarter, score_version)` should agree on the
  result; one overwriting the other is fine.

**Use `IntegrityError → typed error translator` when:**

- The conflict carries domain meaning — "another instance is already active" —
  that callers must distinguish from success.
- The unique index is a mutual-exclusion lock, not a deduplication hint.
- Example: `JobRun.lock_key` races (MVP3-05 batch reparse, MVP3-07 historical
  backfill). The losing caller must abort with a typed error so the API returns
  409, not silently latches onto the winner's run.

**Anti-pattern:** upserting a JobRun row to "steal" an active lock destroys the
mutual-exclusion guarantee. Similarly, raising `IntegrityError` for idempotent
score writes spams logs with non-events.

When adding a new table with a unique constraint, write the rationale next to
the constraint definition in the model so the choice survives a future refactor.
