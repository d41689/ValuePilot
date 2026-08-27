# Task: 13F investor workflow 02 — quarterly new-buys cluster view

**Created:** 2026-07-03 · **Origin:** PO review `2026-07-03_13f-po-review-value-investor.md` (§3 gap #2)
**Status:** COMPLETE (2026-07-18)

## Goal / Acceptance Criteria

The highest-alpha 13F view is **cluster formation**: multiple independent, quality managers opening NEW positions in the same name in the same quarter (Cohen-Polk-Silli "Best Ideas" evidence; the PO review's structural insight — the 45-day lag does not kill low-turnover managers' new-position signal). Today this is only indirectly approachable via add-intensity sorting.

- **Backend — one aggregation endpoint** (consumer router): for a given quarter, group `ownership_changes` rows with `change_status='new_position'` AND `is_primary_signal_eligible=true` by stock; per cluster return:
  - stock (ticker/name), cluster size (distinct managers), **quality-weighted cluster score** = Σ manager_signal_weight over the new buyers (reuse `MANAGER_SIGNAL_WEIGHTS` / taxonomy resolution — no new weight table);
  - per-buyer detail: manager, style badge, position portfolio-weight, value, confidence, caveat codes;
  - filters: `min_cluster_size` (default 2), `superinvestors_only` (default true), quarter selector.
  - Low-confidence rows and caveated deltas are **excluded from score but visible** in the drilldown (marked) — consistent with existing caveat honesty rules.
- **Frontend — "New buys this quarter" section** on the Oracle's Lens page (or sibling tab): cluster-ranked table (stock, cluster size, weighted score, buyer chips, caution), row → existing candidate drilldown drawer; buyer chip → manager page (ticket 01).
- Quarter with open filing window shows the existing "filing window open — data incomplete" banner.

## Scope

**In:** one read-only aggregation endpoint + service function with unit tests; one frontend section; wiring to existing drilldown.
**Out:** exits-cluster view (symmetric, later); alerts (ticket 03); persistence of cluster scores (compute-on-read is fine at 86 managers × 1 quarter).

## Files to change (indicative)

- `backend/app/services/oracles_lens/new_buys_clusters.py` [NEW — pure aggregation over `active_hr_holdings_query` / `ownership_changes`, honoring PRD §7.3 query contract]
- consumer route in the 13F user router (same pattern as `/13f/stocks/{id}/holders`)
- `backend/tests/unit/test_13f_new_buys_clusters.py` [NEW — incl. caveat-exclusion and NT/combination edge cases]
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx` + new section component

## Test plan (Docker)

```bash
docker compose exec -T api pytest -q tests/unit/test_13f_new_buys_clusters.py
docker compose exec -T api pytest -q          # full backend at closing gate
# frontend lint/test/build per canonical CI
```

PO acceptance: on seeded dev data, the view surfaces a known cluster (fixture: ≥2 featured managers newly buying the same stock) ranked above single-buyer rows, with a low-confidence buyer visibly excluded from the score.

**Quant-track note:** this endpoint's output is the raw material for hypothesis **H3** (plan v10 D14) — keep the service function pure/importable so the factor engine can reuse it.

## 2026-07-18 implementation decisions / sign-off trail

- Added `GET /13f/new-buys/clusters` and the pure/importable `build_new_buys_clusters` service. Default scope is reviewed Value DNA; activists and all tracked managers are opt-in.
- `cluster_size` counts distinct, score-eligible managers. Low-confidence, non-primary or caveated buyers remain in `buyers` with explicit exclusion reasons but cannot manufacture a cluster or increase its score.
- The read model requires the ownership-change row's referenced current filing to remain the active HR-family filing. Stale rows and NT filings are excluded.
- Missing stored portfolio weights are computed from complete normalized common-stock filing denominators; incomplete coverage stays unavailable.
- The synthetic fixture now materializes ownership changes and guarantees a two-manager Value DNA new-position cluster in `DEVSEED3`, while retaining the caveat cases.
- Targeted backend tests, frontend normalization tests, lint and production build are green. Seeded browser acceptance showed `DEVSEED3` ranked with 2 independent buyers and score `2.00`; manager chips and the existing research drawer worked.
- Canonical closing gate: backend `1291 passed`; frontend `193 passed`; lint and production build green.
