# PR #33 Review — Backend

**Reviewer role**: Backend Engineer (MEDIUM priority — scoring correctness + migration safety)
**Reviewer date**: 2026-05-14
**PR**: https://github.com/d41689/ValuePilot/pull/33
**Branch**: `docs/13f-automation-prd`
**Method**: Read `dashboard.py` end-to-end, `signal_weighted_score.py` end-to-end, `stocks_13f.py`, `stocks_13f_snapshot.py`, `ingestion_service._reconcile_parsed_fact_current_slot`, MVP8-01 phase-flip ticket, AGENTS.md Data Layer, the 23 alembic migrations on this branch, and spot-checked test files.

---

## Verdict

**APPROVE WITH NOTES**

Scoring service is correct end-to-end. Schemas are typed at the boundary. Migrations all have `downgrade()` defined. Three notes warrant attention; none are merge-blockers.

---

## B1 — Scoring service correctness post-Phase-3 flip

**Phase 1 comparison evidence (2025-Q3, v1.0):**
- `total_stocks_compared=240`, `top10_swap_count=0`, `persisted_only_count=0`, `legacy_only_count=36` (all ≤2 unique common-stock holders — correctly excluded by `min_holders=3`), `magnitude_diff_count=59` (all ~70% scale shift, documented as the base-formula divergence MVP8-02 will resolve).
- Top-9 ranking parity. Position-10 swap within tolerance. **Sufficient for a single-quarter flip.**

**Multi-quarter regression risk:**

One quarter is not zero. The observation-window contract (2025-Q4) is correctly gated; Phase 4 retirement is correctly queued. The risk shape:

- The legacy and persisted formulas agreed for 2025-Q3 because the manager-classification + holding-set characteristics were within the "rank-stable" envelope. A future quarter where (a) several First Eagle-style co-attribution clusters emerge, or (b) Kahn Brothers-style unit-mismatch filers are added to the universe, or (c) manager_type curation flips a manager from `unknown` to a non-unknown type — could surface rank divergence the 2025-Q3 evidence missed.
- The observation window is the right mitigation. The flip is reversible (one-line `Query(True)` → `Query(False)` revert). Acceptable.

**Per-(manager, stock) aggregation in all scoring paths — verified:**

- `_eligible_stock_ids` (signal_weighted_score.py:530) groups by `Holding13F.stock_id` and counts `func.count(func.distinct(Holding13F.manager_id))`. Distinct manager count, not row count. Correct.
- `_top_n_stock_ids_per_manager` (line 562) pre-aggregates per `(manager_id, stock_id)` BEFORE ranking. Comment explicitly calls out the multi-SOLE-row case. Correct.
- `_contributions_for_stock` (line 618) groups rows per `manager_id` and sums `value_thousands` for the portfolio_weight numerator, picks the representative with the largest `value_thousands` for per-holder caveats. Correct.
- `_derive_manager_profile` (line 402) groups rows per `stock_id` for the manager's portfolio. Correct.

The aggregation is consistent across all four eligibility paths. First Eagle's 117-CUSIP co-attribution case is handled.

---

## B2 — `_fact_value` fallback correctness

```python
def _fact_value(fact: MetricFact | None) -> float | None:
    if fact is None: return None
    if fact.value_numeric is not None: return float(fact.value_numeric)
    if isinstance(fact.value_json, dict):
        raw = fact.value_json.get("partial_score")
        if raw is not None:
            try: return float(raw)
            except (TypeError, ValueError): return None
    return None
```

**Defensive types — additional surfaces worth thinking about:**

1. **`bool` is the silent footgun.** `float(True) == 1.0`, `float(False) == 0.0`. If a future parser writes `value_json={'partial_score': True}` (intent: "indicator was met"), the function silently returns 1.0 as if it were a numeric score. **Hardening**: add `isinstance(raw, bool)` check before the `float()` call and return None (or coerce explicitly if booleans should be score-bearing). Cheap; bug class is real because bools subclass ints in Python.

2. **NumPy / Pandas types.** `value_json` is JSONB. A parser that writes via pandas could end up with `numpy.int64` / `numpy.float64` shapes — these survive serialization but `float(numpy.int64(7))` works. Probably non-issue today; future-proof if needed.

3. **`str` numeric coercion is intentional**: `float("7.5")` works. The current code accepts string-typed scores. That's defensive but means a `value_json={'partial_score': '7 of 9'}` would raise ValueError (caught) and return None. Correct.

**`value_numeric` precedence vs `value_json` recency**:

The current contract is "column wins when populated." This is the right product semantics for Piotroski because:
- The `value_numeric` write is the *canonical* numeric score (most fresh parser runs populate both).
- `value_json['partial_score']` is the *fallback* when `value_numeric` is null (composite scores that pre-date the column populate).
- Choosing `value_numeric` first prevents a stale value_json from overriding a newer value_numeric write.

If two writers ever populate both fields inconsistently in the same row, you have a write-side problem, not a read-side problem. The current ordering is correct. The test `test_oracles_lens_value_numeric_takes_precedence_over_partial_score` documents this. **Keep.**

---

## B3 — `QualityOverlay` Pydantic shape

**Status of `piotroski_status` open vocabulary:**
- Known values in dev DB: `"partial"` (72 rows), `"calculated"` (2 rows).
- The Pydantic `Optional[str]` typing is the right call **today** because `Literal["partial", "calculated"]` would 500 on any unexpected value, which is exactly the failure mode AGENTS.md says to avoid (silently corrupted data is worse than a typed schema crashing, but a 500 in production for a one-off legacy row is also a real product cost).

**Recommended audit (future-backlog, not blocking):**
- The 2 `"calculated"` rows are almost certainly a stale calculator artifact. Find them, decide whether they should be reset to `"partial"` or `"complete"`. Then either:
  - (a) Tighten the typing to `Literal["partial", "calculated", "complete"]` once the producer-side vocabulary is consolidated.
  - (b) Leave it open and add a frontend defensive render (already partially done: drawer only specially renders `"partial"`; other values render with no qualifier).

**Schema drift detectability — backend Pydantic vs frontend TypeScript:**

`QualityOverlay` (Pydantic) has 12 fields; `Watchlist13FAvailableDetail.quality_overlay` (TS) has 12 fields. They mirror each other manually. **No automated check that they stay in sync.**

The MVP8-A2 D1 hardening added 2 fields (`vl_target_period_end`, `vl_target_source_document_id`) on both sides in the same commit — discipline-based sync. The Track-E backlog has "OpenAPI-generated frontend types" gated on "Schema drift becomes an active problem (third field-misalignment incident)." Currently at zero or one incidents (the post-Phase-3 `score_confidence` Literal mismatch counts as one), so the trigger is **not** yet hit. Accept the convention.

**Mitigation today**: when adding/removing a field from any of the 13F response schemas, the contributor must update both sides in the same commit. The PR review process should call this out. No mechanical check.

---

## B4 — Migration sequence reversibility

**Verified by `grep -n "def downgrade" backend/alembic/versions/2026*.py | wc -l`: 23 of 23 migrations define `downgrade()`.**

**Spot-checked the schema-impactful migrations:**

| Migration | Downgrade op | Idempotent on re-run? | Notes |
|---|---|---|---|
| `20260423000000-add_13f_ingestion_tables.py` | `drop_table` for cusip_ticker_map + holdings_13f + filings_13f + institution_managers | Yes (DROP IF EXISTS pattern via Alembic) | Cleanest case |
| `20260423120000-widen_cusip_ticker_map_source.py` | `alter_column` to VARCHAR(20) | Yes, **conditional on no row exceeds 20 chars** | If prod has `"sec_co_tickers"` rows (16 chars), fine. If a future "manual-curated-set-A" source gets stored, downgrade fails. |
| `20260513140000-pre_mvp8_01_widen_cusip_ticker_map_ticker.py` | `alter_column` to VARCHAR(10) | Yes, conditional on no row >10 chars | Today's tickers are short; the migration was driven by parser surface, not data. Safe in practice. |
| `20260509120000-13f_mvp1a_schema_foundation.py` | `drop_index` + `drop_table` × multiple | Yes | Clean. |
| `20260511140000-mvp4_01_oracles_lens_score_schema.py` | `drop_table` for `oracles_lens_signals` + `oracles_lens_score_components` | Yes | Persisted scoring data is lost on downgrade. That's the design — downgrade is a rollback, not a backup. |

**Data-backfill migrations:**

I see no migration in this branch that backfills data (all changes are schema-only). The CUSIP enrichment + score backfill operations happen via **separate `JobRun`-driven scripts** (`backfill_stock_ids`, `enrich_unmapped_holdings`, `enqueue_signal_weighted_backfill`). These are NOT Alembic migrations and are NOT in the migration chain. **Correct separation.** Migrations alter shape; jobs populate data. The downgrade chain doesn't need to undo data operations because data operations are idempotent re-runnable scripts.

**Missing: round-trip test against full dev DB.**

I see no record in any task file of running `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head` against the populated dev DB on this branch. The closing-gate verifications all run `alembic upgrade head`. The down-chain is plausible (each migration has a `downgrade()`) but unverified end-to-end.

**Recommendation**: before production deploy, run the round-trip. If the down-then-up sequence succeeds against the current dev DB, you have high confidence in the migration chain. **Not a merge-blocker** — recommend running pre-deploy.

---

## B5 — `_normalize_score_confidence` shim placement

**Current placement** (stocks_13f.py:147): translates `"high_confidence"` → `"high"` at the API boundary.

**The architectural choice**: shim at the API or in the persisted scorer?

**Arguments for keeping the shim at the API:**
- The persisted scorer writes a domain-meaningful vocabulary (`OWNERSHIP_SIGNAL_CONFIDENCE_LEVELS`) used across the readiness service, admin dashboards, and other consumers that already speak that vocabulary. Mutating the scorer's vocabulary would require auditing every consumer.
- The watchlist surface uses the shorter `"high" | "medium" | "low"` because the API's Pydantic schema enforces it via `Literal`. Translating at the boundary keeps the contract enforced where it matters.

**Arguments for normalizing at the scorer write-time:**
- Every NEW endpoint that consumes `OraclesLensSignal.score_confidence` will hit the same trap (`ValidationError` when its schema expects `"high"`). The current shim catches it only at THIS endpoint.
- A consistent vocabulary across consumers reduces the cognitive load.

**Verdict**: keep the shim at the API. The regression risk for a new endpoint is real but the architectural cost of mutating the persisted scorer's vocabulary is higher. **Mitigation for the regression risk**: add a constant `WATCHLIST_API_CONFIDENCE_VOCABULARY = ("high", "medium", "low")` and a shared `_normalize_score_confidence` helper exported from a service module. New endpoints import the helper instead of re-implementing.

**Regression test exists?** Yes — per the MVP8-03B sign-off trail, commit `bdd132a` added 3 regression tests for the post-Phase-3 default path. Confirmed by reading the test file names. The tests are doing their job.

---

## B6 — Test coverage meaningfulness

**pytest -q reports 822 passed (post-MVP7-06 + MVP8 + Track-E).**

**Critical paths spot-checked:**

- `_contributions_for_stock` with multi-row holdings: covered by `test_13f_mvp4_base_primitives.py` + `test_13f_mvp4_signal_weighted_score.py`. Tests exercise the per-`(manager, stock)` aggregation, the SOLE-row dedup, and the option-row exclusion.
- `_reconcile_parsed_fact_current_slot`: covered by `test_ingestion_service*.py` for parsed facts; the per-period scoping is asserted.
- `_m3_panel_for_stock`: covered by `test_13f_mvp8_a2_m3_panel.py` (has-data + no-data paths per the MVP8-A2 sign-off trail).
- `_normalize_score_confidence` post-Phase-3 regression: covered by 3 new tests added in commit `bdd132a`.

**Test quality spot-check (5-minute sweep):**

The tests I spot-checked assert actual behavior (specific score values, specific row counts, specific code paths), not just "doesn't throw." This is the right discipline. The codebase's pattern of "one test asserts the happy path + one test asserts each documented edge case" is consistent across the 13F suite.

**One coverage gap I'd flag:**

The legacy `?use_persisted_scores=false` path tests run against fixture data that may not mirror the production-shape legacy formula behavior (the legacy formula amplifies small weights via `*4` and applies `min(*, 1.0)` cap; the persisted formula uses raw weights). The tests pin specific score values for the legacy formula. **This means Phase 4 retirement will require rewriting ~20+ test cases**, and the rewrites have to land at the same time as the legacy formula deletion. That's not a bug — it's the cost of Phase 4. Just calling it out so Phase 4 scope includes test refactor explicitly.

---

## B7 — Write-conflict patterns post-MVP3

**Upsert sites:**

- `_upsert_signal` in `signal_weighted_score.py:909` — `INSERT ... ON CONFLICT (stock_id, report_quarter, score_version) DO UPDATE`. **Idempotent recompute**: two concurrent scoring runs against the same `(stock, quarter, version)` should agree. Last-writer-wins is correct. Matches AGENTS.md upsert pattern.
- `oracles_lens_score_components` "replace": `delete + bulk insert`, not an ON CONFLICT upsert. This is fine because the unique constraint `uq_oracles_lens_score_components_per_score_component_manager` is enforced on `(score_id, component_name, manager_id)` and the delete clears all prior rows before the bulk insert. Idempotent on re-run.
- I see no other upsert sites in the scoring path.

**IntegrityError translator sites:**

- `enqueue_signal_weighted_backfill` (signal_weighted_score.py:1128) catches `IntegrityError` and raises `SignalWeightedBackfillError`. The unique index on `JobRun.lock_key` is a mutual-exclusion lock (a single active scoring job per `(quarter, version)` allowed). **Correct pattern.**
- Same translator pattern used for MVP3-05 batch reparse and MVP3-07 historical backfill. Confirmed consistent.

**Anti-pattern audit:**

- I see no case where upsert is used to "steal" an active lock. The `JobRun.lock_key` writes all go through the `_active_job_for_lock_key` pre-check + `IntegrityError` race translator. Correct.
- I see no case where idempotent score writes raise `IntegrityError` to the caller. The `_upsert_signal` flow doesn't expose race failures upstream. Correct.

**One nit (not a bug):**

The `OraclesLensScoreComponent` "delete + bulk insert" in `_replace_components` is a non-transactional sequence inside a transaction. If the bulk insert fails mid-flight, the delete is rolled back with it (same transaction). Acceptable today. If you ever want zero-downtime score updates, an ON CONFLICT pattern on `(score_id, component_name, manager_id)` would let the new rows write before the old ones go away. **Premature optimization** — keep delete+insert.

---

## Should-block items (none → APPROVE WITH NOTES, not REJECT)

No merge-blockers. Two notes worth a small follow-up commit:

1. **`_fact_value` bool defensiveness** (B2 #1) — 3 lines of code, prevents a real bug class. Optional but cheap.
2. **Pre-deploy migration round-trip test** (B4) — run before push, not strictly before merge.

---

## Future backlog

- **Audit + consolidate `piotroski_status` vocabulary** (B3) — find the 2 `"calculated"` rows, decide intent, tighten the Literal.
- **Shared `_normalize_score_confidence` helper module** (B5) — make the shim composable for future endpoints.
- **Pre-Phase-4 test refactor scope** (B6) — the legacy-path tests are an explicit cost of Phase 4 retirement.
- **OpenAPI-generated TypeScript types** (B3) — Track-E backlog item; trigger is "third field misalignment incident." We're at one (`score_confidence` Literal); count the next one.

---

## Net

Scoring is correct, persisted path is the right canonical, migrations all have `downgrade()`, write-conflict patterns are disciplined and consistent. The MVP8-01 Phase 3 flip is gated correctly. Phase 4 is queued correctly. Ship it.
