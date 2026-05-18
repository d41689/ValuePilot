# PR #33 Review — Production Readiness

**Reviewer role**: Production Readiness Reviewer (HIGH priority — merge-now-vs-stage decision)
**Reviewer date**: 2026-05-14
**PR**: https://github.com/d41689/ValuePilot/pull/33
**Branch**: `docs/13f-automation-prd` — ~171 commits, ~270 files changed, +70k/-2.4k LOC
**Method**: Read open-work snapshot, MVP8-01 phase-flip ticket, MVP8-02 base-divergence ticket, AGENTS.md Verification Discipline + Minimal per-PR checklist. Confirmed branch scale via `git log --oneline main..HEAD | wc -l` (171) and `git diff main..HEAD --stat` (270 files, +70,411 / -2,460).

---

## Verdict

**APPROVE WITH NOTES — merge is acceptable; deploy is gated.**

The codebase is functionally ready, has internally consistent observation gates, and has rollback paths for every behavior change. **Merging to main is safe.** Two production gating items below must be resolved BEFORE the merged code reaches production traffic:

1. The migration round-trip test against a prod-like data dump (P4).
2. An operator-visible release note covering the Phase 3 flip + watchlist surface (P6).

Without those two, **don't deploy** even though the PR can merge. With them, ship it.

---

## P1 — What's safe to ship TODAY vs gated

**Already shipped and SHOULD reach prod:**
- MVP3 ingestion + EDGAR pipeline
- MVP4 scoring service (signal-weighted, conviction, distinctive)
- MVP5 amendment exclusion + manager-type taxonomy
- MVP6 admin operations console (8 routes)
- MVP7 Watchlist × 13F surface (columns + drawer + sort)
- MVP8-A2 Drawer M3 quality/valuation overlay
- MVP8-03A/B SME flag cluster
- MVP7-06 click-to-sort
- Track-E sweep + post-MVP8-A2 hardening
- All 23 alembic migrations

**Shipped but BEHAVIORALLY GATED on observation window:**
- **MVP8-01 Phase 3 server-default flip** (`use_persisted_scores=True` by default at 3 endpoints). Reaches production users as soon as code merges. Phase 1 comparison evidence: `top10_swap_count=0`, `total_stocks_compared=240`, all on 2025-Q3 / v1.0.
- Observation window is **post-2025-Q4 scoring cycle**.
- Rollback path: per-request `?persisted=0` escape hatch (operator) or one-line code revert (deploy).

**Is the Phase 3 flip safe to ship NOW?**

For the dev DB universe (240 stocks, 2025-Q3): yes, with the comparison evidence as gate.

For production: **the gate is not symmetric**. The Phase 1 comparison ran against a dev DB hydrated from real EDGAR data; whether dev's universe of 240 superinvestors is identical to production's universe was not explicitly verified in the MVP8-01 task file. If production has additional managers (or different `manager_type_admin_classified` curation state) that weren't in dev when Phase 1 ran, the divergence could differ. **Probable but not verified.**

**Recommendation**:
- Before deploy, run the Phase 1 comparison utility against the production DB (or a fresh staging clone). The utility is `build_formula_comparison` + admin endpoint. Same gates: `top10_swap_count == 0`, `total_stocks_compared ≥ 200`, `persisted_only_count ≤ 10`. If all green, deploy.
- If not green, hold deploy and investigate the divergence. The flip is reversible.

**`?persisted=0` escape hatch documentation:**

The MVP8-01 task file lists the escape hatch in three places (D3, D4, post-flip Operator Runbooks). The `oracles_lens.py` docstring on the endpoint describes the query parameter. **But there is no operator-facing runbook in `docs/` or top-level README** explaining "if the persisted scoring path produces a regression, hit `?persisted=0` to force legacy."

**Recommendation**: add a short operator runbook (`docs/runbooks/phase3-scoring-rollback.md` or similar) before deploy. Topics:
- How to detect a Phase 3 regression (look at signal_weighted scores for top-N stocks; compare to expected manual list).
- How to flip the user-facing surface back via query param.
- How to revert in code if the query-param escape doesn't suffice (one-line `Query(True)` → `Query(False)`).
- Who decides to revert vs investigate.

---

## P2 — Coverage limitations + missing-data honesty

**Dev VL coverage**: 7 stocks with VL data; 5 overlap with 13F holdings (ADBE, FICO, FNV, GOOG, MTDR).

**Production VL coverage**: not surfaced in any task file I read on this branch. Open-work snapshot N2 acknowledges "Production coverage is unknown but the gap is the bottleneck."

**Asymmetry risk:**

- All ~240 stocks in the universe show 13F columns (Conviction / Δ Holders / Distinctiveness / Caveats).
- ~5 stocks in dev show the M3 quality/valuation panel.
- If production has similar ratio (≤5%), users open 95% of drawers and see "Value Line data is not available for this stock in the current dataset."

**Should the M3 panel be feature-flagged off until coverage improves?**

**No, for two reasons:**

1. **Removing it makes the 5 covered stocks invisible too.** Operators who curated those 5 stocks lose the surface they're already using on `/13f/oracles-lens`.
2. **Honest missing-data state IS the V1 product**: the explicit "Value Line data is not available for this stock in the current dataset" copy tells users the truth. Per memory `financial_data_unknown_vs_zero`: "missing/unavailable/unlinked/pending/zero are distinct states; never display unavailable as 0 or infer absence from missing data." The current implementation respects this.

**But the asymmetry IS a real UX risk for V1.** A user clicking 20 watchlist rows and seeing "not available" 19 times will conclude "ValuePilot doesn't have quality data."

**Recommendation (operator side, not engineering):**

- File the VL coverage track (N2) as a high-priority follow-on. The drawer is honest; the bottleneck is upstream ingestion. Don't deploy expecting "M3 covers everything" — communicate "M3 covers a curated subset, expanding."
- **Audit production VL coverage before deploy.** Run a `SELECT stock_id, COUNT(DISTINCT metric_key) FROM metric_facts WHERE metric_key IN (... _M3_METRIC_KEYS ...) GROUP BY stock_id` query against production. If coverage matches dev (≤5%), the release note must call this out explicitly.

**Asymmetry between 13F columns and M3 panel:**

The watchlist row shows 13F signals (universal) and the drawer is where the asymmetry surfaces. This is **acceptable** because:
- 13F data has its own justification — knowing whether a stock is owned by superinvestors is valuable even without VL quality data.
- The M3 panel is one section of the drawer; the rest (Summary, Top Holders, Caveats) renders for every stock.

A user sees: "13F is great → Quality data is sometimes there." That's an honest product story.

---

## P3 — Rollback plan for Phase 3 regression

**Scenario**: Production user reports "stock X ranks top-10 under legacy but I see it at #15 now."

**Recovery path:**

1. **Immediate mitigation (per-user / per-query)**: pass `?use_persisted_scores=false`. Forces legacy formula on that request. No deploy. **Verified the param is exposed on all three flipped endpoints** (`/oracles-lens`, `/stocks/13f-snapshots`, `/stocks/{id}/13f-detail`).

2. **Tenant-wide / cohort mitigation**: there is **no config-flag-based rollback today**. The default flip is in code (`Query(True)`). To revert traffic without redeploying, every consumer would need to pass `?use_persisted_scores=false`. This works for the admin dashboard (`frontend/oraclesLens.js` could be patched to pass the param) but not for direct API consumers (curl / Postman / programmatic).

3. **Full rollback**: revert the three `Query(False)` → `Query(True)` flips in `oracles_lens.py` and `stocks_13f.py`. One-line revert per endpoint, three endpoints. ~1 hour to apply + test + redeploy.

**Is one quarter of evidence enough?**

The MVP8-01 task file gates Phase 4 retirement on **post-2025-Q4 observation showing zero `TOP10_RANK_SWAP`**. That's the gate for *deleting* the legacy formula. The gate for *flipping the default* is satisfied by the 2025-Q3 comparison.

**This is the right gating shape**:
- Flip with one-quarter evidence + observation window + per-request escape hatch.
- Delete legacy formula only after a second clean quarter.

**Recommendation for production gating before deploy:**

- Confirm the `?use_persisted_scores=false` escape hatch works against production data (smoke test post-deploy).
- Define "what counts as a regression": e.g., `TOP10_RANK_SWAP > 0` against the next quarter's comparison run, or a user-reported stock-ranking complaint that the comparison utility confirms.
- Define rollback owner: who runs the revert command, who notifies users.

**Without a config flag**: the rollback path is "redeploy a one-line revert." If the deploy cadence is slow (e.g., once a week), the regression window is up to a week. **Consider adding a feature flag** (environment variable `ORACLES_LENS_DEFAULT_PERSISTED=true|false`) to enable per-environment toggles without code changes. Cost: ~30 lines. Benefit: instant rollback. **Recommended but not blocking** if deploy cadence is fast.

---

## P4 — Migration safety for production data

**Alembic head**: `20260513140000` (cusip_ticker_map.ticker VARCHAR(10) → VARCHAR(50)).

**23 migrations on the branch, all with `downgrade()` defined.**

**Production-shape testing status:**

The Backend review verified all migrations define `downgrade()` and the spot-checked migrations have non-trivial ops. **However, no record exists of running `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head` against a prod-like data dump.** The closing-gate verifications all run the forward direction only.

**Risks:**
- A `downgrade()` that works against an empty schema may fail against populated tables if the downgrade DDL conflicts with foreign-key constraints. Example: dropping `oracles_lens_signals` while `oracles_lens_score_components.score_id` still references it.
- Schema-widening migrations (`cusip_ticker_map.ticker` VARCHAR(10) → VARCHAR(50)) have asymmetric reversibility: the upgrade always works; the downgrade fails if any row has a value too long for the narrower type.

**Idempotence on partial failure:**
- All migrations on this branch are pure schema changes (no data backfills inside migrations). If a deploy fails mid-migration, Alembic's transactional behavior (within a single migration's `upgrade()`) means the partial state is rolled back. **Re-running the deploy is safe.**
- Data operations (CUSIP enrichment, score backfill) live in standalone scripts (`enrich_cusips_from_openfigi`, `enqueue_signal_weighted_backfill`). These are JobRun-driven and idempotent by design (upsert pattern + lock_key uniqueness).

**Pre-deploy gate (RECOMMENDED, this is the P4 blocker):**

1. Take a sanitized dump of the production DB (current state, pre-this-branch).
2. Apply this branch's migration chain (`alembic upgrade head` from whatever the current prod head is).
3. Verify schema matches expected via `\d <table>` in psql for the 6-8 most-changed tables.
4. Verify `pytest -q` passes against the migrated DB.
5. Run the Phase 1 comparison utility against the migrated DB and confirm gates (`total_stocks_compared ≥ 200`, `top10_swap_count == 0`).
6. If all green, deploy.

**This is the single most important pre-deploy gate.** If the dev DB is not shape-equivalent to production, the migrations could fail at deploy time with the same effect as a bad deploy. Run the round-trip.

---

## P5 — Observation-window gate clarity

**MVP8-01 Phase 4 trigger**: "One full scoring cycle (post-2025-Q4) showing zero `TOP10_RANK_SWAP` under the new persisted default."

**Where would an ops person look to know the window has closed?**

- Today: nowhere automated. The trigger is "run the Phase 1 comparison utility against 2025-Q4 + 2025-Q3, look at the `top10_swap_count` field."
- The admin endpoint `GET /api/v1/admin/13f/oracles-lens/formula-comparison` is the mechanism. Ops would call it manually.

**Is there a runbook?**

- The MVP8-01 task file has "Operator Runbooks" but only for the CUSIP re-enrichment path. **No runbook for "how to determine if Phase 4 is unblocked."**

**Recommendation**:

- Add an `Operator Runbooks` section to the MVP8-02 ticket (the queued ticket) describing the explicit query / endpoint call that determines if the observation window has closed.
- Or: add a top-level `docs/runbooks/observation-window.md`.
- Either way, **someone needs to know the literal command to run** when 2025-Q4 data lands.

**Regression response runbook:**

If the observation window surfaces a regression (e.g., `top10_swap_count > 0`):
- Who decides revert vs investigate? Not documented.
- What does "revert" mean given the default flip is in code? Documented in MVP8-01 D4: "one-line revert of the three default sites."

**Recommendation**: extend the rollback runbook (P3) to cover this case. Decision owner = PO; investigation lead = backend engineer; mitigation = per-request `?persisted=0` while investigating.

---

## P6 — PR mergeability vs follow-on work

**Follow-ons listed in open-work snapshot:**

| Item | Prerequisite for THIS PR? |
|---|---|
| N1 Mobile stacked 13F view | No — phased rollout, mobile parity comes later |
| N2 VL ingestion coverage | No — drawer is honest about missing VL data |
| MVP8-01 Phase 4 retirement | No — observation-window-gated |
| MVP8-02 base divergence | No — observation-window-gated |

**No follow-on is a prerequisite for THIS PR to merge safely.** Phased rollout is the design.

**Operator-visible CHANGE post-merge:**

1. **`/watchlist` page**: 13F columns (Conviction / Δ Holders / Distinctiveness / Caveats) visible on `md` viewport and above. Click-to-sort on those columns. Click Conviction badge → 13F drawer opens with M3 quality/valuation panel (when VL data exists) or "not available" state.
2. **`/13f/oracles-lens` page**: uses persisted scores by default. Visible difference: top-10 ranking parity vs pre-merge (per Phase 1 comparison); position-10 may swap one stock; absolute score magnitudes ~70% of pre-merge values (the magnitude_diff_count=59 observation).
3. **`/admin/13f/*` routes**: unchanged behaviorally; MVP8-03A admin items shipped during this PR (Kahn Brothers banner, etc.).

**Release note: has anyone written one?**

**No release note exists.** The closest is the open-work snapshot, which is a project status doc, not a user-facing announcement.

**Recommendation (blocking for deploy, not merge):**

Write a short release note covering:
- New: 13F Insight columns + drawer on Watchlist.
- Changed: Oracle's Lens scoring uses persisted formula by default; rankings should be stable but absolute scores will look ~70% of pre-change values.
- Limitations: VL quality data shown for a curated subset of stocks. Mobile users see watchlist without 13F columns (parity coming).
- Workaround: `?use_persisted_scores=false` query param forces legacy formula for the observation window.

Distribute to: internal users (Slack), API consumers (changelog page on the product site), anyone with a watchlist (in-app banner / email if applicable).

---

## Should-block items (for deploy, not for merge)

These do NOT block merging the PR to main. They DO block reaching production traffic:

1. **Run the Phase 1 comparison utility against production data (or a fresh staging clone)** and confirm `top10_swap_count == 0`. (P1, P4)
2. **Run the migration round-trip test (`upgrade head → downgrade base → upgrade head`) against a prod-like data dump.** (P4)
3. **Write the operator-visible release note** covering the watchlist surface + Phase 3 flip + escape hatch. (P6)
4. **Add a rollback runbook** documenting `?persisted=0` escape, code-revert path, and decision owner. (P3, P5)

These are 1-2 days of work, not weeks. Do them before pushing to prod.

---

## Future backlog (post-deploy)

- Feature flag for Phase 3 default (P3) — environment variable for instant rollback without redeploy.
- Observation-window runbook (P5) — explicit "how to know the window closed."
- Production VL coverage audit (P2) — drives N2 (VL ingestion expansion) priority.
- N1 Mobile stacked view — next ticket after deploy.

---

## Net

This is a large, well-decomposed PR. The work is internally consistent: every decision has a gate file, every flip has a rollback path, every gap is acknowledged in the open-work snapshot. **Merging is safe.** Deploying without the four pre-deploy gates above is **not safe** — the gates are reasonable, fast to satisfy, and protect against the realistic failure modes (migration surprise on prod-shape data, Phase 3 regression on a stock not seen in dev).

If you can complete the four gates today or tomorrow, ship it. If they slip, hold deploy and don't let the merge sit on main for too long — long-lived `main`-vs-prod divergence is its own risk class.

The right pattern going forward is **per-MVP push + per-MVP deploy gate**, not 170-commit branches. Internalize the lesson; this is the last one of these.
