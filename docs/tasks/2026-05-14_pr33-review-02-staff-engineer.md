# PR #33 Review — Staff Engineer / Architecture

**Reviewer role**: Staff Engineer (HIGH priority — cross-cutting contracts + design)
**Reviewer date**: 2026-05-14
**PR**: https://github.com/d41689/ValuePilot/pull/33
**Branch**: `docs/13f-automation-prd` (~170 commits, 270 files, +70k/-2.4k)
**Method**: Read AGENTS.md end-to-end (228 lines), CLAUDE.md (16 lines), MVP8-01 phase-flip ticket, MVP8-A2 + MVP8-03B task files, locked `is_current` decision gate, `dashboard.py`, `stocks_13f.py`, `stocks_13f_snapshot.py`, `signal_weighted_score.py`, `ingestion_service._reconcile_parsed_fact_current_slot`. Spot-checked migrations + tests. No commit-by-commit reading.

---

## Verdict

**APPROVE WITH NOTES**

The architecture is coherent. The `is_current` contract is the most important risk; the codebase enforces it correctly at write time and reads it correctly via `_m3_facts_by_stock`. Two notes are worth resolving before merge (A4 memory framing, A6 PR cadence going forward); the rest are well-understood backlog tracked in the open-work snapshot. The branch is large but reviewable because it has been **decomposed by closing-gate task files**, not by commit count.

---

## A1 — Cross-MVP contract drift on `is_current`

**Verified by code reading:**

- `_reconcile_parsed_fact_current_slot` (ingestion_service.py:953) scopes to `(stock_id, metric_key, source_type='parsed', period_type, period_end_date)`. Correct.
- `value_line_ratios.py` ratio writer (lines ~104-147) scopes the demotion update to `(metric_key, period_type, period_end_date, source_type='calculated')` and writes the new row with the same scoping. Correct.
- `screener_service.py:77,198` filters on `is_current.is_(True)` for fiscal facts — no period tiebreak is needed because screeners join on `(metric_key, period_type, period_end_date)` implicitly via the join keys. Correct for fiscal metrics; would mis-surface stale opinion metrics IF a screener ever filtered on an opinion `metric_key`. Today, screeners don't (the rule vocabulary is fiscal-only). Future-proof: add a vocabulary guard.
- `formula_engine.py:97,144` does the same `is_current.is_(True)` filter — same caveat as screener_service.
- `_m3_facts_by_stock` (dashboard.py:790) uses the read-side tiebreak `period_end_date DESC NULLS LAST, created_at DESC`. Correct.
- `_quality_overlay_by_stock` and `_m3_panel_for_stock` both go through `_m3_facts_by_stock`. Confirmed unified.
- `_valuation_reference_by_stock` (dashboard.py:1016) **does NOT use** `_m3_facts_by_stock` — it has its own query that filters `is_current=True` and `value_numeric.isnot(None)`, ordered by `(stock_id ASC, created_at DESC)`. **No `period_end_date` tiebreak.** This is the one read path that could surface a stale opinion target if two `is_current=True` rows exist for `target.price_18m.mid` and the older row happens to have a more recent `created_at`. Audit / unify with `_m3_facts_by_stock`.

**Recommended actions:**

1. **(Should-fix-before-merge if there is appetite for a small commit)** Unify `_valuation_reference_by_stock` with `_m3_facts_by_stock`. Same opinion-metric class; same tiebreak rule should apply. Today's data probably doesn't hit the divergent ordering, but this is the kind of inconsistency that bites a year from now when re-publication creates the edge case.

2. **Vocabulary guard on screener / formula engine**: emit a warning (or fail) when a rule references an opinion `metric_key`. The opinion-metric set is small (~10 keys) and lives in the decision-gate document; lifting it to a constant in `metric_semantics.py` and asserting "screener / formula keys ∩ OPINION_METRIC_KEYS == ∅" would mechanize the contract.

3. **AGENTS.md `is_current` rule is clear and correctly worded.** The "Never add a cleanup migration..." sentence is exactly the guard a future engineer needs.

---

## A2 — `_m3_facts_by_stock` abstraction sufficiency

The shared helper is at the **right level of abstraction**. Both callers consume the same primitive (most-recent fact per (stock, key)) and shape it differently downstream. Sharing the *primitive*, not the *response shape*, is correct.

**`_fact_value` fallback narrowness — observations:**

`_fact_value` reads `value_numeric` first, then falls back to `value_json['partial_score']` for composite scores. This is Piotroski-specific today but generalizes acceptably:

- The "composite score with named sub-fields in value_json" pattern is uncommon. The only known case is Piotroski; others (`returns.total_capital`, `bs.return_on_total_capital`) store directly in `value_numeric`.
- If a second composite score lands (e.g., a multi-factor quality score), it will likely use `partial_score` as the convention. The fallback works for that case.
- If a *third* pattern lands (e.g., `value_json['confidence']` with `value_numeric` reserved for the value), this falls apart. That's the trigger to elevate to a `MetricCoercer` registry, which is on the open-work snapshot Track-E backlog (`MetricFact.numeric_value()` helper trigger: "Read paths multiply beyond 2").

**Recommendation**: keep `_fact_value` as-is. The Track-E trigger condition is sensible. Don't promote prematurely.

**The narrower question**: should the metric-key → response-shape mapping be moved out of `_m3_panel_for_stock` into a `ResponsePayloadBuilder`? **No.** The mapping is endpoint-specific. Two callers want different field names (`piotroski_score` vs `piotroski_total`) for the same fact. A shared builder would need a config table that's bigger than the inline code. YAGNI.

---

## A3 — Phase 3 / Phase 4 server-default-flip safety

**Verified:**

- `oracles_lens.py:23-31` flipped `Query(False)` → `Query(True)`. Confirmed.
- `stocks_13f.py:152` and `stocks_13f.py:350` (now lines ~257 and ~468 after edits) both expose `use_persisted_scores: bool = Query(True, ...)`. Tests updated to pass `?use_persisted_scores=false` for legacy-path coverage.
- `formula_comparison.py:113,134` hard-codes `use_persisted_scores=False` — **this is correct**. The comparison utility's job is to build the legacy and persisted reports side-by-side; it must call the legacy path explicitly. No regression risk here.
- No other `use_persisted_scores=False` in `backend/app/` outside tests. Confirmed via `grep -rn "use_persisted_scores=False" backend/app/`.

**Phase 4 retirement deletability:**

The legacy `_stock_payload` formula in `dashboard.py` (line 512) is called only via `build_oracles_lens_dashboard` when `use_persisted_scores=False`. Once `?persisted=0` is retired, the entire `_apply_persisted_scores` branch + the legacy formula can be deleted, with the dashboard service becoming a thin pass-through over `OraclesLensSignal` reads. The deletion is **mechanically blockable** by:

- The legacy-path tests (`test_oracles_lens.py:test_signal_score_*`) that pass `?use_persisted_scores=false`. Removing the parameter means rewriting those tests against persisted fixtures.
- The `formula_comparison.py` utility itself, which must be deleted or rewritten as a persisted-vs-persisted-baseline diff after Phase 4.

So the deletion is **safe in principle, painful in test refactor**. Acceptable. Phase 4 should land its test refactor in the same commit so the legacy formula's last consumer dies with the formula.

**One concern**: the comparison report in MVP8-01 is single-quarter (2025-Q3). The contract says "one full scoring cycle observation window (post-2025-Q4) showing zero TOP10_RANK_SWAP." This is correctly gated. Just confirming the gate is in code, not in vibes — yes, the MVP8-01 task file documents the trigger condition and the queued Phase 4 ticket has not yet been opened.

---

## A4 — Agent workbook consolidation correctness

**Verified:**

- `@AGENTS.md` import on line 1 of CLAUDE.md is the documented Claude Code feature. AGENTS.md is loaded into the system prompt verbatim.
- CLAUDE.md is **16 lines, all Claude-Code-specific** (memory directory + "memory is not canonical" rule). Correctly minimal.
- AGENTS.md is **228 lines**, contracts merged, aspirational Phase 0-7 content removed. Concise.

**The fallback for non-Claude-Code agents**: AGENTS.md is the canonical workbook. Cursor, Aider, Copilot read AGENTS.md directly (per the project convention). The 16 lines in CLAUDE.md don't apply to them; they don't need to.

**Concern (memory framing maintenance hazard):**

The new memory entry `feedback_local_green_vs_ci_green.md` says "canonical version in AGENTS.md → Verification Discipline." This creates two sources of truth that can drift:

- **Scenario**: a future PR tightens the Verification Discipline rule in AGENTS.md (e.g., adds a "must include migrations test"). The memory entry isn't updated. Next Claude Code session reads the stale memory version, doesn't see the new rule.

**Mitigation options:**

- **(a) Trust AGENTS.md primacy** — when AGENTS.md changes, manually update the memory entry. Burden is on the person editing AGENTS.md to grep memory for cross-references. Today: tribal.
- **(b) Mechanize the cross-reference** — store the AGENTS.md rule's hash or a short identifier in the memory entry, and add a CI check that the hash matches. Heavyweight.
- **(c) Don't have a memory reinforcement at all** — if AGENTS.md is auto-loaded for Claude Code (via `@AGENTS.md`), the memory entry is duplicative. Delete it; trust the AGENTS.md path. Today the import IS auto-loaded, so this option is viable.

**Recommendation**: **(c)** — delete `feedback_local_green_vs_ci_green.md` from memory. It's redundant with AGENTS.md, and the user/agent prompt context already shows AGENTS.md content. The memory entry adds maintenance cost without buying coverage. The OTHER memory entries (financial_data_unknown_vs_zero, metric_facts_is_current_semantics, etc.) are similarly worth auditing for "is this a reinforcement of AGENTS.md or a Claude-Code-only lesson?" Lessons stay; reinforcements go.

The `metric_facts_is_current_semantics` memory entry in particular **is canonical-style content** (the locked contract). It should be in AGENTS.md (it is) and removed from memory, since AGENTS.md import covers the Claude Code path.

---

## A5 — `_M3_METRIC_KEYS` placement

The constant lives in `backend/app/api/v1/endpoints/stocks_13f.py:44`. The previous review suggested moving it to `oracles_lens/dashboard.py` near `QUALITY_METRIC_KEYS`.

**Verdict**: current placement is **acceptable** because:

1. There is exactly one consumer (`_m3_panel_for_stock` in the same module).
2. The Track-E backlog has a trigger condition ("2nd consumer of the constant arrives"), and that's the right time to elevate.
3. Moving it now is an architecturally satisfying but practically wasteful refactor — the constant has no current need to live in `dashboard.py`, and moving it would force the endpoint module to import service-layer constants for one variable.

If a SECOND consumer arrives that's outside the endpoint module, **move it then**. Until then, keep the constant where it's used. This is the right kind of restraint and matches the AGENTS.md "Don't add abstractions beyond what the task requires" principle.

---

## A6 — Branch size and PR strategy

170 commits, 270 files, +70k/-2.4k LOC. This is **at the upper bound of reviewable as a single PR**. Two things made this work:

1. **Each MVP has its own task file with sign-off trail and four-role review record.** A reviewer can read the closing task file to understand what shipped, without reading 170 commits.
2. **The decision gates are documented separately** (`metric-facts-current-semantics`, `pre-mvp7-01-watchlist-13f-insight`, `pre-mvp8-a2-oracles-lens-m3`, `pre-mvp8-03-sme-flag-cluster`, etc.). Reviewers read the gate, not the commits.

**Going forward, what's the right PR cadence?**

- **Per-MVP push** is the right cadence for this project. Each MVP-closure commit (~5-15 commits) should be a separate PR. CI fires on every push, which catches the uiStandard.test.js class of regression at the right time, not at the end of a 170-commit branch.
- **Per-decision-gate push** is the right granularity for design changes. The locked `is_current` gate is a 1-commit PR by nature; bundling it with implementation churn dilutes the design signal.
- **Long-lived feature branches** should still exist for *unfinished, experimental* work. But once an MVP closes, push it.

**Is THIS branch reviewable as a single PR?** Marginally yes, because the task files do the heavy lifting. The lesson per `feedback_local_green_vs_ci_green.md` (the uiStandard.test.js failure that surfaced only at push time) is the correct one to internalize: **the branch HAS already incurred CI debt that the per-MVP cadence would have caught earlier.** That debt was paid (commit `817144a`) but the pattern is fragile.

**Should the next track (mobile stacked 13F view, VL coverage expansion) open a new branch and push per-milestone?** Yes.

**Should this PR be split before merge?** I lean **no, with reservations**:

- Splitting now means cherry-picking 170 commits into 6-8 sub-PRs, which is itself a multi-day exercise prone to merge conflicts.
- The work IS coherent — MVP3 → MVP8 is one product arc (EDGAR ingest → scoring → admin → Watchlist surface). Splitting on MVP boundaries would create dependent PRs that can't merge in parallel.
- The risk reduction from splitting is modest given the task-file decomposition.

Merge as one. Internalize the cadence lesson for the next track.

---

## A7 — Migration sequence + reversibility

Alembic head: `20260513140000`. 23 migrations on the branch, all dated 2026-01-17 through 2026-05-13.

**Verified:**

- `grep -n "def downgrade" backend/alembic/versions/2026*.py | wc -l` → **23**. Every migration has a `downgrade()` function defined.
- Spot-checked the schema-altering migrations: `add_13f_ingestion_tables.py`, `13f_mvp1a_schema_foundation.py`, `mvp4_01_oracles_lens_score_schema.py`, `widen_cusip_ticker_map_source.py`, `pre_mvp8_01_widen_cusip_ticker_map_ticker.py`. All have non-trivial `downgrade()` ops (`drop_table`, `drop_index`, `alter_column` back to prior type, etc.).
- `widen_cusip_ticker_map_source.py` downgrade reverts to `VARCHAR(20)` — would FAIL if any row has a `source` value longer than 20 chars at downgrade time. This is the standard reversibility caveat for "widen-then-data" migrations. Acceptable; documented in the original task file.
- `pre_mvp8_01_widen_cusip_ticker_map_ticker.py` widens `ticker` from VARCHAR(10) to VARCHAR(50). Downgrade re-narrows. Same caveat — any ticker > 10 chars at downgrade time fails. Today's data: ADRs / PLCs (e.g., "TSMC", "AON" — short) fit comfortably; international tickers might not.

**Migration ordering:**

The branch's migrations form a linear chain (each `down_revision` points to the immediately prior file's `revision`). No fanout, no merge revisions. Verified by file modification dates aligning with revision ordering. **Linear and causally consistent.**

**Production-shape testing:**

- The MVP8-01 task file documents that the comparison report ran against the 2025-Q3 dev DB (~240 stocks, 1686 CUSIP map rows from real OpenFIGI calls). This is not synthetic data — it's production-like in shape.
- However, I see **no record of running the migration chain (`alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head`) against the full data set**. This is the missing test for "does the downgrade chain actually work."
- Recommendation: **before production deploy**, run the round-trip on a copy of the dev DB. If it succeeds, you have higher confidence than today. This is also the test that should run in CI when migrations are touched.

---

## Should-block items (none → APPROVE WITH NOTES, not REJECT)

Nothing in this review is a merge-blocker for me. The closest contenders:

- **`_valuation_reference_by_stock` should also use `_m3_facts_by_stock`** (A1 #1). One small commit. Worth doing before merge.
- **Migration round-trip test against dev DB** (A7) — should be done as part of pre-deploy, not pre-merge. The migrations themselves all have `downgrade()`; reversibility is plausible.

---

## Future backlog (not blocking, file as Track-E or similar)

- **Vocabulary guard on screener / formula engine `is_current` reads** (A1 #2) — assert opinion metrics never enter rule_json.
- **Migration round-trip CI check** (A7) — when `backend/alembic/versions/` is touched in a PR.
- **`feedback_local_green_vs_ci_green` memory entry deletion** (A4) — eliminate the dual-source-of-truth maintenance hazard.
- **Per-MVP push cadence going forward** (A6) — convention shift, not code.
- **`MetricCoercer` registry trigger** (A2) — already documented in open-work snapshot Track-E. Confirm.
- **`_M3_METRIC_KEYS` relocation** (A5) — already documented. Confirm trigger.

---

## Architecture summary

The codebase has converged on a coherent three-layer pattern: (1) immutable raw extractions in `metric_extractions`, (2) reconciled per-period facts in `metric_facts` with `is_current` per-period semantics, (3) typed read services (`_m3_facts_by_stock`, `_quality_overlay_by_stock`, `compute_signal_weighted_scores`) that consume facts and emit response models. The `OraclesLensSignal` persistence layer + the `_apply_persisted_scores` projection is the right adapter for the Phase 3 flip. The Pydantic schemas at the API boundary (`QualityOverlay`, `StockDetailTopHolder`, etc.) enforce the contract at the right place.

The main architecture risk is **`is_current` semantic drift**, and that's been correctly addressed by the decision gate + the AGENTS.md hard rule + the `_m3_facts_by_stock` read pattern. Three follow-on things that would harden it further: (a) unify `_valuation_reference_by_stock` with the read primitive, (b) add a vocabulary guard on screener/formula keys, (c) mechanize the trigger for opinion-key allowlist (Option B) instead of trusting code review to catch it.

Beyond `is_current`, the codebase is in good shape. The Track-E backlog is well-curated — every item has a trigger condition, none is "we'll get to it." This is the right discipline for a small-team codebase.
