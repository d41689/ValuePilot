# PR #33 Pre-Deploy Gates

## Status

**Open 2026-05-14.** Filed as a follow-up to PR #33 comprehensive review (Production Readiness P1-P6 + Backend B4 + Staff A7).

PR #33 is mergeable to `main` — the codebase is correct and the canonical CI commands are green. But there are four pre-deploy gates that **must clear before the merged code reaches production traffic**. This ticket tracks them.

## Why a separate ticket

The Production Readiness reviewer explicitly distinguished:
- **Merge-safe**: the code is internally consistent + CI green. ✓
- **Deploy-safe**: requires verification against production data shape + an operator runbook + a release note.

The 4 gates below are 1-2 days of work and should NOT block PR #33 merge but DO block deploy.

## Goal

Clear all four gates before promoting the merged commit to production. If a gate fails, hold deploy until the gate is satisfied (do not let `main` and prod diverge for long — that's its own risk class).

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
- How to mitigate per-request (`?persisted=0`) vs full-code-revert.
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

- [ ] D1 migration round-trip green against prod-like data.
- [ ] D2 Phase 1 comparison green against production data.
- [ ] D3 operator runbook drafted, reviewed by PO + backend.
- [ ] D4 release note drafted, reviewed, distributed at deploy.
- [ ] D5 production VL coverage audited, number recorded in D4.
- [ ] All gates clear → deploy authorized.
- [ ] **PR #33 Pre-Deploy Gates closed (= production deploy complete).**
