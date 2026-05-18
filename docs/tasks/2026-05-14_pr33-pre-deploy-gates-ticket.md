# PR #33 Pre-Deploy Gates

## Status

**Open 2026-05-14.** Filed as a follow-up to PR #33 comprehensive review (Production Readiness P1-P6 + Backend B4 + Staff A7). Status framing updated 2026-05-18 per post-review-response audit.

PR #33's codebase is correct and the canonical CI commands are green. But there are five pre-deploy gates that **must clear before the merged code reaches production traffic**. This ticket tracks them.

## Repo-specific note: merge ≡ deploy

The Production Readiness reviewer framed N4 as "blocks deploy, not merge." That framing is correct in repos where `main` is a staging branch with a manual promote-to-production step. **This repo is not configured that way.**

`.github/workflows/deploy.yml` auto-fires on every successful CI run on `main`:

```yaml
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
# ...
if: >
  github.event.workflow_run.conclusion == 'success' &&
  github.event.workflow_run.head_branch == 'main'
```

In practical terms: **merge to `main` IS production deploy.** So N4 gates **merge** for this repo, not "deploy after merge."

Three options to handle this:

1. **(Recommended) Clear N4 before merging PR #33.** Treat the auto-deploy coupling as a feature, not a bug — it forces the deploy-readiness check before the change goes live.
2. **Disable auto-deploy temporarily** (comment out the `workflow_run` trigger in `deploy.yml`, leave only `workflow_dispatch` for manual deploy). PR #33 merges to `main`; deploy runs only when manually triggered after N4 clears.
3. **Use a separate staging branch.** Bigger workflow change; not recommended for a one-off PR.

Option 1 is the cleanest unless the team has a reason to merge-but-not-deploy (e.g., wanting `main` to receive other PRs before deploy). Default to option 1.

## Why a separate ticket from the implementation work

The 5 gates below are 1-2 days of work — verification + documentation + release-note drafting, not code changes. They could have been inline in PR #33 but were kept separate to let the code review close cleanly. Now that the code review is complete, this ticket is the deploy-readiness checklist.

## Goal

Clear all five gates before promoting the merged commit to production. If a gate fails, hold deploy until the gate is satisfied (do not let `main` and prod diverge for long — that's its own risk class).

## D1 — Migration round-trip test against prod-like data

**Source**: Backend B4, Staff A7, Production P4.

**Why**: The branch has 23 Alembic migrations. All define `downgrade()`. None have been tested via `upgrade head → downgrade base → upgrade head` against a populated dev DB or a prod-shape data dump. The schema-widening migrations (`cusip_ticker_map.source` VARCHAR(20)→(50), `cusip_ticker_map.ticker` VARCHAR(10)→(50)) have asymmetric reversibility — downgrade fails if any row's value exceeds the narrower type.

**Steps**:

1. Take a sanitized dump of production (or fresh staging clone). 
2. Apply: `alembic upgrade head` from the current prod head to `20260513140000`.
3. Verify schema via `\d <table>` in psql for the 6-8 most-changed tables.
4. Apply: `alembic downgrade base` then `alembic upgrade head` (full round-trip).
5. Verify pytest still passes against the migrated DB.
6. Record results in this ticket.

**Gate**: zero failures across the round-trip.

### D1 results (2026-05-18, dev DB)

Round-trip executed against the populated dev DB (1686 cusip_ticker_map rows + 4022 holdings_13f rows; the same shape MVP8-01 used for the Phase 1 comparison).

**Round 1**:
- `alembic upgrade head` (already at head — no-op). ✓
- `alembic downgrade base` → **FAILED** at the very first reverse step (`20260513140000-pre_mvp8_01_widen_cusip_ticker_map_ticker`) with `psycopg2.errors.StringDataRightTruncation: value too long for type character varying(10)`. The transactional DDL rolled back; DB state intact.

**Root cause**: 110 rows in `cusip_ticker_map.ticker` exceed VARCHAR(10) — OpenFIGI's `mapCusips` response legitimately returns bond / preferred / warrant identifiers > 10 chars for some CUSIPs (e.g. `"UBER 0.875 12/01/28 2028"` = 24 chars). The migration's upgrade was driven by exactly this data; the naive `alter_column` downgrade always fails against any populated DB that triggered the upgrade in the first place.

**Fix applied**: patched `20260513140000-pre_mvp8_01_widen_cusip_ticker_map_ticker.py:downgrade()` to pre-check for offending rows and raise an actionable `RuntimeError` instead of letting the cryptic SQL truncation surface:

```
cusip_ticker_map has {N} rows with ticker length > 10 (OpenFIGI bond /
preferred / warrant identifiers). Narrowing to VARCHAR(10) would
truncate them and corrupt the mapping. Resolve the offending rows
BEFORE downgrading — delete them or archive to a separate table —
then re-run `alembic downgrade -1`.
```

The forward path is unaffected (the upgrade still works identically). The downgrade is now honest about being structurally one-way for any DB that hit the original constraint.

**Round 2 (after the fix)**:
- Confirmed actionable error fires on populated dev DB (110 rows reported). ✓
- Manually deleted the offending bond / preferred rows from `cusip_ticker_map` (simulating the operator-side prerequisite the error message describes).
- `alembic downgrade base` → **succeeded** end-to-end, all 23 migrations reversed cleanly. ✓
- `alembic upgrade head` → **succeeded**, all 23 migrations re-applied. ✓
- Dev DB restored from `/tmp/valuepilot-n4-d1/dev-before-roundtrip.sql` (1686 + 4022 row counts restored). ✓
- Post-restore canonical CI: `pytest -q` 823 passed; `node --test lib/*.test.js` 143 passed; lint+build clean.

**Sister migration verified safe**: `20260423120000-widen_cusip_ticker_map_source.py` narrows VARCHAR(50)→(20). Dev DB has zero `source` values > 20 chars (only `"openfigi"` / `"sec_co_tickers"` / `"manual"` are valid per AGENTS.md). Downgrade would succeed against any compliant DB.

**Net for production deploy**: the forward chain is fully tested and clean. The reverse chain works for 22/23 migrations cleanly; the 23rd (cusip_ticker_map.ticker widening) now fails with a clear actionable message when offending data is present. Rollback for THIS specific schema change requires operator intervention (decide what to do with the bond / preferred rows) and cannot be fully automated — that's the structural reality, not a regression.

**Production caveat NOT covered by dev round-trip**: the `widen_cusip_ticker_map_source` downgrade could still fail in production if any prod row has `source` > 20 chars. Confirm during D2 against the staging clone.

## D2 — Phase 1 comparison against production data

**Source**: Production P1, Production P3.

**Why**: MVP8-01 closed with `top10_swap_count=0` against 2025-Q3 dev DB. Production may have different manager curation state, different universe size, or different superinvestor membership. The Phase 3 server-default flip is at code merge — no feature flag — so first prod traffic hits the persisted formula by default.

**Steps**:

1. Hydrate staging from a fresh production data dump.
2. Run the formula comparison utility: `GET /api/v1/admin/13f/oracles-lens/formula-comparison?period=2025-Q4` (or current quarter).
3. Confirm gates: `total_stocks_compared ≥ 200`, `top10_swap_count == 0`, `persisted_only_count ≤ 10`.
4. If gates green → deploy.
5. If gates red → hold deploy and investigate the divergence. The flip is reversible.

**Gate**: zero TOP10_RANK_SWAP against production data.

## D3 — Operator runbook for Phase 3 rollback + observation-window monitoring

**Source**: Production P3, P5.

**Why**: Today the `?use_persisted_scores=false` escape hatch exists but is documented only in code docstrings + the MVP8-01 task file. There is no operator-facing runbook describing:

- How to detect a Phase 3 regression in production.
- Who decides revert vs investigate.
- How to determine when the observation window has closed and Phase 4 retirement is unblocked.
- What "regression" means (`TOP10_RANK_SWAP > 0`, user-reported ranking complaint, etc.).

**Deliverable**:

- New file: `docs/runbooks/phase3-scoring-rollback.md` (or similar location).
- Topics:
  1. Detection: which metric / endpoint to query, what triggers a "regression" diagnosis.
  2. Per-request mitigation: pass `?use_persisted_scores=false` on the three flipped endpoints.
  3. Code rollback: one-line `Query(True)` → `Query(False)` revert at three sites; ~1 hour to apply + test + redeploy.
  4. Observation-window monitoring: how to call the formula comparison utility, what counts as a clean quarter.
  5. Decision tree: who owns revert (PO), who owns investigation (backend engineer), how to notify users.
  6. **Critical clarification: application code revert (`git revert`) is THIS deployment's rollback path. `alembic downgrade` is NOT.** The cusip_ticker_map.ticker widening migration now intentionally fails its `downgrade()` with an actionable `RuntimeError` when offending rows exist (bond / preferred identifiers > 10 chars; dev had 110 such rows). An operator under pressure who attempts `alembic downgrade` as the rollback path will lose time. The widening is a one-way schema change for any populated DB; only the application code (the three `Query(True)` flips) reverts cleanly. Recovery path for a Phase 3 regression is: per-request `?persisted=0` for immediate mitigation → application code revert + redeploy for full restore. (Added per PR #33 Production P3 review.)

**Gate**: runbook exists, reviewed by PO + backend lead.

## D4 — Release note for users + API consumers

**Source**: Production P6.

**Why**: This PR introduces user-visible changes (Watchlist × 13F columns + drawer, Oracle's Lens scoring uses persisted formula by default) but no release note has been written. Users / API consumers seeing the change without context will assume bugs.

**Deliverable**:

Short release note covering:

- **New**: 13F Insight columns + drawer on Watchlist (Conviction / Δ Holders / Distinctiveness / Caveats; click-to-sort; per-row 13F drawer with Quality & Valuation overlay).
- **Changed**: Oracle's Lens scoring uses persisted formula by default. Rankings should be stable but absolute scores will look ~70% of pre-change values (`magnitude_diff_count=59` from the Phase 1 comparison; documented as the base-formula divergence MVP8-02 will resolve).
- **Limitations**: VL quality data shown for a curated subset of stocks (~5 in dev; production coverage TBD by D5 below). Mobile users see watchlist without 13F columns (parity coming in the Mobile stacked 13F view ticket).
- **Escape hatch**: `?use_persisted_scores=false` query param forces legacy formula during the observation window.

Distribute to: internal users (Slack), API consumers (changelog page), anyone with a watchlist (in-app banner / email if applicable).

**Gate**: release note drafted, reviewed by PO, distributed at deploy time.

## D5 — Production VL coverage audit (informational; informs D4)

**Source**: 13F SME Q2 + Production P2.

**Why**: Dev has 7 stocks with VL data; 5 overlap with 13F. Production coverage unknown. The watchlist drawer's M3 panel will show "Value Line data is not available for this stock in the current dataset" for ~95% of stocks if production coverage matches dev. This needs to be communicated honestly in the release note (D4).

**Steps**:

1. Against production: `SELECT stock_id, COUNT(DISTINCT metric_key) FROM metric_facts WHERE metric_key IN (...) GROUP BY stock_id` for the M3 metric set.
2. Compute: how many of the ~240 ranked 13F stocks have any VL fact / the full M3 panel.
3. Record the number in the release note (D4) so users know the coverage scope.

**Gate**: number recorded; D4 release note copy reflects it accurately.

## Scope Out

- Phase 4 legacy formula retirement — observation-window-gated, separate ticket.
- MVP8-02 base divergence investigation — observation-window-gated, separate ticket.
- VL ingestion coverage expansion (N2) — separate decision gate.
- Feature flag for instant Phase 3 rollback — recommended by Production reviewer but deferred to a separate enhancement ticket.

## Sign-Off Trail

- [x] D1 (dev) migration round-trip executed 2026-05-18 against populated dev DB.
      Surfaced a structural one-way constraint in the cusip_ticker_map.ticker
      widening migration (downgrade can't narrow back when OpenFIGI bond /
      preferred identifiers > 10 chars are present). Patched the migration
      with a pre-check + actionable error. Full chain (22/23 migrations
      reversible cleanly; 23rd requires operator intervention to clear
      offending rows first, by design). pytest 823 passed post-restore.
  - [ ] D1 (prod) — run the same round-trip against a production data dump
        or fresh staging clone. Specifically confirm `cusip_ticker_map.source`
        narrowing doesn't surface the same structural issue (dev has zero
        source values > 20 chars per the closed source-vocabulary contract
        in AGENTS.md; prod TBD).
- [ ] D2 Phase 1 comparison green against production data.
- [ ] D3 operator runbook drafted, reviewed by PO + backend.
- [ ] D4 release note drafted, reviewed, distributed at deploy.
- [ ] D5 production VL coverage audited, number recorded in D4.
- [ ] All gates clear → deploy authorized.
- [ ] **PR #33 Pre-Deploy Gates closed (= production deploy complete).**
