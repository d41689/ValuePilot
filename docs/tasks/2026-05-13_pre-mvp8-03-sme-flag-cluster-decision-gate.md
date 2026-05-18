# Pre-MVP8-03: SME Flag Cluster Decision Gate

## Status

**Authorized to open 2026-05-13** as the next 13F-track ticket
after MVP8-01 (Phase 3 flip, commit `040aa80`).

**Decision-gate ticket — not coding.** Output is a written split
contract that two child tickets (MVP8-03A + MVP8-03B) execute
against. The split + ordering is locked here so neither child
ticket re-litigates scope.

## Goal

The MVP6-08 closing review and the MVP7-06 four-role review each
surfaced SME flags that were explicitly deferred to a later
ticket (PRD reviewer trust items, not in-scope for the originating
sprint). Per the PO-locked ranking at MVP7-06 close, "SME flag
cluster" is priority #2 on the MVP8 track (priority #1 was Phase 3
flip, shipped 2026-05-13).

10 items were originally tagged; 2 were absorbed during MVP7-06
review-fix (`f20e6eb`: "Top N% conviction" suffix + "13F common
weight" terminology). **8 items remain.** This ticket clusters
them into two ship packages and locks ordering.

## D1 — Split contract (locked)

**Decision: split by surface, not by complexity.** Each child
ticket owns one consistent surface so reviewers can verify in
context.

### MVP8-03A — Admin SME fixes (4 items, admin-only surface)

| # | Item | Source | Touches |
|---|------|--------|---------|
| A1 | `manager_type` editor: `note` required for non-`unknown` transitions + `evidence_json` threading | MVP6-08 | admin manager edit UI + backend manager-update endpoint |
| A2 | Historical Backfill (`/admin/13f/jobs`): Kahn Brothers (CIK `0001039565`) True-Positive caveat block | MVP6-08 | historical backfill card backend warning logic + frontend banner copy |
| A3 | Batch Reparse: `missing_raw_infotable_count > 0` MetricTile → amber banner promotion + warning copy alignment | MVP6-08 | batch reparse card on `/admin/13f/jobs` |
| A4 | Quality Reports: V2 per-finding drilldown panel replacing JSON dump in Quarter Detail drawer | MVP6-08 | `/admin/13f/quality` (or admin-13f drawer) + possible payload reshape |

### MVP8-03B — Watchlist / scoring SME fixes (4 items, user-facing surface)

| # | Item | Source | Touches |
|---|------|--------|---------|
| B1 | `manager_type` derived-vs-admin-classified dual-display in Watchlist13FDrawer | MVP7-06 | drawer per-manager row; backend `_stock_payload.top_holders` schema field |
| B2 | Distinctiveness threshold review — `crowded` tier reachability is currently low because behavior-derivation pushes coverage high; consider gating on raw `unknown_manager_type_count` instead of derived coverage | MVP7-06 | scoring `_distinctiveness_tier` logic; possible test pinning |
| B3 | MOS × 13F threshold raise — V1 is `mos ≥ 0.20 AND delta_holders ≥ +1 → aligned`; SME suggested evaluating `0.30 / +3` or splitting into a two-tier aligned signal | MVP7-06 | MOS × 13F cross-signal glyph derivation; needs data-driven threshold sweep first |
| B4 | Δ Holders chip portfolio-weight context — chip currently shows signed integer only; add portfolio-weight context for depth | MVP7-06 | Watchlist Δ Holders chip + per-manager backend payload field |

## D2 — Ordering (locked)

**Decision: MVP8-03B first, then MVP8-03A.**

Rationale (PO-locked at this gate):

- B touches user-facing surfaces (Watchlist row + drawer). SME
  trust issues here actively affect how users read 13F signals.
  Resolving them sooner closes the product-trust gap.
- A touches admin-only surfaces. Operators already have working
  admin tools; the 4 fixes are quality-of-life + audit-trail
  hardening, not blockers for daily admin work.

Each child ticket ships independently; B does not block A and
A does not block B once authorized. The ordering applies to
*authorization sequence*, not technical dependency.

## D3 — Per-child acceptance gates (locked)

Each child ticket must hit:

- Strict scope discipline — only the 4 items in the package land.
  No retro-fitting unrelated MVP7-06 backlog items (e.g. drawer
  a11y, DrawerShell move) into either child.
- pytest -q green; for B, frontend `npm run build` clean + the
  `oraclesLens.test.js` suite still passing.
- A four-role review pass (Frontend + Backend + Staff Engineer +
  SME) recorded inline in the child ticket's Verification
  Results section.
- For data-driven items (B2 threshold review, B3 threshold
  sweep): a brief data audit appended to the child ticket
  showing the empirical basis for the chosen threshold values.

## D4 — Out-of-Scope (this cluster)

These items are **explicitly NOT** in MVP8-03A or MVP8-03B
despite originating in the same MVP6-08 / MVP7-06 reviews —
they belong in different track tickets:

- **DrawerShell move to `@/components/ui/drawer-shell`**
  (MVP7-06 Staff Engineer follow-up). Cross-cutting refactor
  across 8+ admin/13f mounts + watchlist drawer. Track-E ticket.
- **Drawer a11y suite** (Escape-close + open-autofocus +
  close-focus-return). Same cross-cutting reach as DrawerShell
  move; bundle in one a11y-track ticket.
- **Long manager name truncate in drawer** (Frontend reviewer;
  pending visual QA). Cosmetic; queue as a small frontend ticket.
- **Accession-to-filing URL** (needs CIK threaded through
  `_stock_payload.top_holders` → `StockDetailTopHolder` schema
  → `Watchlist13FDrawer` Link). Separate ticket because the
  current placeholder (plain text fallback in `f20e6eb`) is not
  user-visible-broken — just disabled-not-broken.
- **`tests/helpers/clear_13f.py` consolidation** — Pre-MVP8-01
  post-review Staff Eng follow-up; tech-debt ticket separate.
- **CUSIP re-enrichment admin path** — Pre-MVP8-01 post-review
  Staff Eng follow-up; queued under MVP8-01's "Operator
  Runbooks" today, formal admin UI deferred.
- **`_derive_manager_profile` multi-row regression test** —
  Pre-MVP8-01 post-review Staff Eng follow-up; tech-debt ticket.
- **MVP8-02 base-divergence investigation** — queued, waiting
  for observation window.

## D5 — Authorization sequence

**Decision: open MVP8-03B immediately after Pre-MVP8-03 closes.**
MVP8-03A authorization is gated on:

- MVP8-03B closing review pass, AND
- Any cross-cutting findings in B that touch admin surfaces
  rolled into A's scope (unlikely given the split, but
  acknowledged so the gate doesn't surprise either reviewer).

## Files Expected To Change

- `docs/tasks/2026-05-13_pre-mvp8-03-sme-flag-cluster-decision-gate.md`
  (this file) — the only artifact this ticket produces.

No code, no migration, no test changes. The child tickets carry
the implementation.

## Sign-Off Trail

- [x] PO confirmed split + ordering at this gate (2026-05-13).
- [ ] **Pre-MVP8-03 closed. MVP8-03B (Watchlist/scoring SME
      fixes, 4 items) authorized to open.**
- [ ] MVP8-03A authorization deferred until MVP8-03B closing
      review.

## References

- `docs/tasks/2026-05-13_13f-mvp7-end-to-end-verification.md`
  "Review Outcomes" → PO Verdict → MVP8 ranking, where SME flag
  cluster was placed at priority #2.
- `docs/tasks/2026-05-12_mvp6-08-mvp6-execution-plan-decision-gate.md`
  and the MVP7-06 four-role review for the original deferred
  SME items.
- Memory `project_13f_prd.md` for the running track state.
