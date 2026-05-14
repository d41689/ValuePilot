# Project Context

**ValuePilot v0.1** is a financial analysis engine designed to parse, store, and analyze equity reports. The v0.1 scope is strictly limited to **Value Line equity report PDFs** (single-page standard layout). The system focuses on precise data extraction, strict data lineage (audit trails), and normalized storage for screening and formulas.

The 13F automation track (parallel to the v0.1 PRD) adds EDGAR ingestion + Oracle's Lens scoring + Watchlist × 13F surface; its contracts are merged into this workbook below.

# Tech Stack

- **Language**: Python (backend), TypeScript / React (frontend)
- **Database**: PostgreSQL (relational, strictly typed)
- **ORM**: SQLAlchemy (screening rules compile to SQLAlchemy expressions)
- **Parsing**: Template-based extraction (PDF text layer first, OCR fallback)
- **Data Exchange**: JSON for semi-structured data (`parsed_value_json`, `rule_json`)
- **Frontend UI**: shadcn/ui + Tailwind + lucide-react icons

# Development Environment (Docker Compose)

All tooling runs inside containers. Agents MUST assume the local runtime is containerized.

Canonical commands:

- Start services: `docker compose up -d --build`
- View logs: `docker compose logs -f`
- Run inside a service: `docker compose exec <service> <command>` (e.g., `docker compose exec api pytest -q`)

Do NOT run Python tooling directly on the host when a containerized alternative exists.

# Data Layer

## Three-layer storage pattern

We strictly separate raw artifacts, extraction lineage, and queryable facts:

1. **`pdf_documents`** — stores the file and metadata.
2. **`metric_extractions`** — the **audit trail**. Stores exactly what the parser found (raw text, snippets, page numbers). **NEVER** query this table for screeners.
3. **`metric_facts`** — the **source of truth**. Stores normalized, queryable data (numeric values, canonical keys). **ALWAYS** use this table for screeners, formulas, and UI display.

## Stock identity resolution

Stocks are global master data. Ingestion logic:

1. Match by `ticker` + `exchange`.
2. If matched, compare `company_name` similarity.
3. If similarity is low, set `pdf_documents.identity_needs_review = true`. **DO NOT** auto-link without confirmation.

## Metric normalization

All data written to `metric_facts.value_numeric` MUST be normalized to base units:

- **Currency**: absolute amounts (e.g., "1.2 bil" → `1,200,000,000`).
- **Percentages**: ratios between 0 and 1 (e.g., "5.2%" → `0.052`).
- **Prices / per-share**: absolute currency (e.g., EPS 3.25 → `3.25`).
- **Scale tokens**: handle `k`, `m`/`mil`, `b`/`bil`, `t`/`tril` case-insensitively.

## `metric_facts.is_current` semantics (locked 2026-05-14)

`metric_facts.is_current=True` is **per-period currency**, NOT one row per `(stock_id, metric_key)`. Two metric categories share the column with different uniqueness contracts:

- **Fiscal time series** — `per_share.eps`, `is.net_income`, `score.piotroski.total`, `bs.total_equity`, `leverage.long_term_debt_to_capital`, etc. Each FY/Q row is genuinely "current for that period". ADBE has 42 `is_current=True` rows for `per_share.eps` by design — one per fiscal year. The existing reconciliation (`_reconcile_parsed_fact_current_slot` in `ingestion_service.py`) scopes uniqueness to `(stock_id, metric_key, period_type, period_end_date, source_type)`.
- **Opinion / as-of facts** — `target.price_18m.*`, `proj.long_term.*`, `quality.earnings_predictability`, `quality.financial_strength`, etc. `period_end_date` is effectively the publication date, not a fiscal period. Multiple `is_current=True` rows coexist when Value Line re-publishes; older publications are NOT automatically demoted.

**Locked design (PO 2026-05-14, Option A):** status quo + read-side tiebreak. Opinion-metric staleness is handled at the read layer via `_m3_facts_by_stock` in `oracles_lens/dashboard.py` (tiebreak `period_end_date DESC NULLS LAST, created_at DESC`), surfaced in UI as `(VL report dated YYYY-MM-DD)`. Rationale: financial-data accuracy first principle is "do not break the original time-series facts".

**Never** add a cleanup migration, Alembic op, or one-off script that enforces "at most one `is_current=True` per `(stock_id, metric_key)`" without scoping by metric category. Naive global dedup wipes ~99% of fiscal time series and breaks the Piotroski calculator, screener, formula engine, and Oracle's Lens quality overlay.

If a future opinion-metric consumer cannot use the read-side tiebreak pattern, reopen `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md` for Option B (opinion-key allowlist). Do NOT implement Option B without that gate reopening.

## Data integrity + manual corrections

- **Immutability**: parsed records in `metric_extractions` are immutable.
- **Manual corrections** (user edits a parsed value):
  1. DO NOT update `metric_extractions`.
  2. Insert a NEW row into `metric_facts` with `source_type = 'manual'` and `is_current = true`.
  3. Demote the prior row scoped to the same `(stock_id, metric_key, period_type, period_end_date, source_type='manual')` to `is_current = false`. Match the reconciliation pattern in `_reconcile_parsed_fact_current_slot`. **DO NOT** demote rows that differ in `period_end_date` — per-period currency is the contract (see `is_current` semantics above).

## Schema changes — no band-aids

When runtime code hits a DB constraint violation (column too short, wrong type, missing index, etc.), the correct fix is **always a migration**, not a code-level workaround.

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

**Why:** band-aids hide root causes, silently truncate data, and leave the system in a state where any new value longer than the limit will fail again — or worse, succeed silently with corrupted data.

## Alembic conventions

- Filename: `backend/alembic/versions/YYYYMMDDHHMMSS-<slug>.py`. Use the `Create Date` timestamp from the revision header. Keep `<slug>` readable.
- `down_revision` must match the **`revision` variable** inside the parent file, not the filename.
- Never change `revision` / `down_revision` identifiers when renaming a file.
- Always verify applied state with `\d <table>` in psql after `alembic upgrade head`.

## Write-conflict handling: upsert vs IntegrityError

Two distinct patterns; the choice between them is **semantic**, not stylistic.

**Use ORM upsert (`INSERT ... ON CONFLICT (...) DO UPDATE`) when:**

- The write is idempotent: re-running with the same inputs is supposed to produce the same row.
- "Last writer wins" is the correct semantics — there's no domain meaning to "I lost the race."
- Example: `oracles_lens_signals` recompute. Two concurrent scoring runs against the same `(stock_id, report_quarter, score_version)` should agree on the result; one overwriting the other is fine.

**Use `IntegrityError → typed error translator` when:**

- The conflict carries domain meaning — "another instance is already active" — that callers must distinguish from success.
- The unique index is a mutual-exclusion lock, not a deduplication hint.
- Example: `JobRun.lock_key` races (MVP3-05 batch reparse, MVP3-07 historical backfill). The losing caller must abort with a typed error so the API returns 409, not silently latches onto the winner's run.

**Anti-pattern:** upserting a JobRun row to "steal" an active lock destroys the mutual-exclusion guarantee. Similarly, raising `IntegrityError` for idempotent score writes spams logs with non-events.

When adding a new table with a unique constraint, write the rationale next to the constraint definition in the model so the choice survives a future refactor.

# Parsing

## Scope, strategy, mapping

- **Scope**: only support "Value Line" templates for v0.1. Mark others as `unsupported_template`.
- **Strategy**: try native text layer; fall back to OCR if density is low.
- **Mapping**: map template-specific field names (e.g., `18_month_target_low`) to **canonical metric keys** (e.g., `target_18m_low`). Authoritative mappings live in `value_line_v1_field_map.json`.

## Parser fixture alignment workflow (required)

When asked to align a parser to an expected fixture, use project scripts inside Docker. Do NOT use OS-level `diff` for JSON comparisons.

- Generate `*.parser.json`: `docker compose exec api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/<name>.pdf --out tests/fixtures/value_line/<name>_v1.parser.json`
- Key-by-key JSON diff: `docker compose exec api python -m scripts.json_diff tests/fixtures/value_line/<name>_v1.expected.json tests/fixtures/value_line/<name>_v1.parser.json tests/fixtures/value_line/<name>_v1.diff.json`
- Iterate: use the diff JSON as the source of truth for mismatched paths/values. Adjust parser code minimally (TDD), regenerate, re-run, repeat until the diff is `{}`.
- Verify with `docker compose exec api pytest -q` (or the targeted fixture test) during iteration; full suite at the closing gate per the Verification Discipline section.

## EDGAR / 13F pipeline gotchas

- `shrsOrPrnAmt` is a wrapper element in infotable XML; unwrap it to read `sshPrnamt` / `sshPrnamtType`.
- `xslForm13F_X02/` paths in EDGAR filing index are XSLT-rendered HTML, not machine-readable XML — skip them when scanning for infotable URLs.
- `cusip_ticker_map.source` is VARCHAR(50); valid source strings: `"openfigi"`, `"sec_co_tickers"`, `"manual"`. Dataroma is not a CUSIP or security-identity source.
- Kahn Brothers (`0001039565-*`) reports values in dollars, not thousands — reconciliation warnings for this filer are True Positives, not bugs.

# Frontend UI Standard

- Use **shadcn/ui + Tailwind** for all product frontend. Shared controls live in `frontend/components/ui/` and follow the shadcn pattern: Radix primitives where appropriate, `class-variance-authority` for variants, `cn()` for class merging, Tailwind utility classes for styling.
- Do NOT render raw HTML form/control primitives directly in app, feature, or shared business components. Use shared UI components: `Button`, `Input`, `Textarea`, `Select`, `DropdownMenu`, `Checkbox`, `Table`, `Card`, `Badge`, `Toast`.
- If a needed shadcn/ui component does not exist yet, add it under `frontend/components/ui/` first, then use it from product code.
- Use Tailwind classes for layout and component-specific adjustments only. Keep reusable interaction states, focus rings, disabled states, and base sizing inside shared UI components.
- Use lucide-react icons inside controls when an icon exists. Avoid hand-rolled SVG controls in product UI.

**Enforced by** `frontend/lib/uiStandard.test.js`, which scans `app/`, `components/`, `features/` for forbidden raw HTML primitives. The scanner matches substrings **anywhere in the file, including code comments** — when writing explanatory comments about this rule, use phrasing like "raw HTML button element" instead of spelling out the literal angle-bracket form.

# Coding Standards

## Naming

- **Metric keys**: `snake_case` ONLY. NO leading numbers. (`target_18m_low`, not `18m_target`).
- **Tables**: `snake_case` plural (`metric_facts`, `stock_pools`).
- See the Alembic conventions section above for migration filename rules.

## Error handling

- **Normalization failures**: if a value cannot be normalized (e.g., unknown unit), store the `raw_value` in JSON but leave `value_numeric` as `NULL`. Flag specific error metadata.
- **Traceability**: every parsed metric MUST include `document_id`, `page_number`, and `original_text_snippet`.

# Development Workflow

## Task logging (required)

Before making any code changes, create a task entry in `docs/tasks/`:

- File naming: `YYYY-MM-DD_<short-task-name>.md`.
- Required content: Goal / Acceptance Criteria, Scope (in / out), PRD references (when applicable), Files to change, Test plan (Docker commands).
- Keep the task file updated as work progresses (notes, decisions, gotchas, sign-off trail).

## Test-first implementation

1. Write or update tests first (red).
2. Implement the minimal production code to pass (green).
3. Refactor safely while keeping tests green.

## Running tests (Docker only)

Iteration commands (during development):

- `docker compose exec api pytest -q tests/unit/test_<x>.py` (targeted)
- `docker compose exec web node --test lib/<x>.test.js` (targeted)

These are FAST signals during iteration. They do NOT substitute for the canonical CI commands at closing gates (see below).

## Verification Discipline (closing gates)

When declaring work "ready", "shipped", "closed", or otherwise green, run the **EXACT command CI runs**, not a similar or more-targeted version. A glob is not a list of files.

Canonical CI commands for this repo:

- Backend tests: `docker compose exec api pytest -q` (full suite, not specific files).
- Frontend unit tests: `docker compose exec web sh -lc 'node --test lib/*.test.js'` (the glob, not specific files — discovers source-scanner tests like `lib/uiStandard.test.js`).
- Frontend lint: `docker compose exec web npm run lint`.
- Frontend build: `docker compose exec web npm run build`.
- Migrations (when changed): `docker compose exec api alembic upgrade head`.

**Long-lived branches** mask CI failures — CI only fires on push. If a branch will accumulate >10 commits before pushing, run the canonical CI commands at each closing gate as a substitute for actual CI.

**Regex-based source scanners** (`lib/uiStandard.test.js`, similar tools) match substrings anywhere in the file, including comments. See the Frontend UI Standard section for the comment-style guidance this implies.

## Safety contract checks

- Screeners MUST query `metric_facts` and filter on `is_current = true`.
- Screeners MUST filter on `value_numeric` for numeric comparisons (not JSON).
- Rule evaluation MUST compile `rule_json` to SQLAlchemy expressions (never raw SQL).
- Formula evaluation MUST use a restricted AST engine (never eval/exec).
- Parsing MUST respect scale tokens and normalize before writing `value_numeric`.
- Every parsed metric MUST include `document_id`, `page_number`, and `original_text_snippet`.

## Minimal per-PR checklist

- [ ] `docker compose up -d --build` succeeds.
- [ ] Migrations apply cleanly (if changed).
- [ ] Canonical CI commands green inside containers (see Verification Discipline).
- [ ] No raw SQL generation from user input.
- [ ] `metric_facts` remains the only queryable source of truth (`is_current = true` for active values).

---

Role-specific review prompts live in `docs/tasks/*-review-prompts.md` and should be followed case by case.
