# Open-Work Snapshot — 2026-05-14

## Status

Checkpoint after MVP8-A2, post-MVP8-A2 + Track-E sweep, and MVP7-06
all closed today. Captures the project state, locked decisions, and
prioritization so deferred items don't drift into "active" by
accident and active items don't get retconned as deferred.

## Locked Decisions (2026-05-14)

### LD1 — `metric_facts.is_current` semantics: Option A

**Decision**: status quo + read-side tiebreak. Multiple
`is_current=True` rows for fiscal metrics are CORRECT by design;
opinion-metric staleness is handled at the read layer via
`_m3_facts_by_stock` in `oracles_lens/dashboard.py` (tiebreak
`period_end_date DESC NULLS LAST, created_at DESC`), surfaced in
UI as `(VL report dated YYYY-MM-DD)`.

**Why**: financial-data accuracy first principle is "do not break
the original time-series facts". Naive global dedup wipes ~99% of
fiscal time series and breaks the Piotroski calculator, screener,
formula engine, and Oracle's Lens quality overlay.

**Where it's recorded**:
- `AGENTS.md` — "`metric_facts.is_current` semantics (locked
  2026-05-14)" section with the "never" rule. Canonical for all agents.
- `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md`
  — design gate, status `CLOSED 2026-05-14 — Option A`.
- Memory: `feedback_metric_facts_is_current_semantics.md` —
  contract locked.

**Reserved option**: B (opinion-key allowlist in
`_reconcile_parsed_fact_current_slot`). Held for the case where a
future opinion-metric consumer cannot use the read-side tiebreak.
Reopen the design gate before implementing.

### LD2 — Core product direction

> 先把 13F 核心信号在 Watchlist 里稳定、准确、可解释地展示出来；
> 再扩大 Value Line 覆盖率；最后才做更炫的可视化。

Translated for sequencing:

1. Watchlist × 13F core signal surface must work on all viewports
   (mobile included) → next ticket.
2. Value Line ingestion coverage expansion → the constraint on
   Oracle's Lens M3 / A2 product value (only 5 overlap stocks in
   dev DB).
3. Visualization milestones (A3 Visual Radar, etc.) come after
   data quality + core table experience.

### LD3 — MVP8 PO ranking complete through priority #4

| # | Item | Status |
|---|---|---|
| 1 | MVP5-03 Phase 3 server-default flip | CLOSED (MVP8-01) |
| 2 | SME flag cluster | CLOSED (MVP8-03A + MVP8-03B) |
| 3 | Track A2 Oracle's Lens M3 valuation + quality overlay | SHIPPED at Watchlist drawer surface (MVP8-A2) — legacy `/13f/oracles-lens` page already has it via the dashboard service. Coverage-limited (5 overlap stocks) — see LD2. |
| 4 | Watchlist click-to-sort UX | CLOSED (MVP7-06) |
| 5 | Mobile stacked 13F view | **NEXT TICKET** |
| 6 | Track C G1 (email alerts) + G9 (external ticketing) | Deferred per LD4 below |

## Actionable Now

### N1 — Mobile stacked 13F view (next ticket)

The MVP7 D4 decision deferred a per-row stacked 13F view on narrow
viewports: `sm hidden` means small-screen users see no 13F columns
at all. The drawer works on mobile but requires opening the row
first. The core signals (Conviction / Δ Holders / Distinctiveness /
Caveats) must be readable on small screens.

**Scope shape** (locked at ticket-open time):

- Below `md` breakpoint, render the four 13F signals as a stacked
  card below the main row (or above, TBD with PO).
- Reuse existing `Watchlist13FColumns` helpers + chip components;
  no new backend, no new sort surface.
- Manual probe on a real narrow viewport (375px wide minimum).

### N2 — Value Line ingestion coverage track (follow-on)

A2 product value depends on Value Line coverage. Dev DB has 7
stocks with VL data; only 5 overlap with 13F holdings. Production
coverage is unknown but the gap is the bottleneck.

**Scope shape** (open a decision gate first, not an implementation
ticket):

- Audit production coverage (how many of the 240 ranked 13F stocks
  have any VL fact, and how many have the full M3 panel?).
- Decide whether to expand the VL ingestion list, the parser
  surface, or both.
- Define "missing-data honesty" contract for stocks that won't
  reach VL coverage (small caps, foreign filings, ADRs).
- Provenance: who owns the curation list of "stocks worth
  ingesting", how often it refreshes, who validates new parser
  outputs.

This is a real product decision, not a small refactor. Don't open
the implementation ticket until the gate closes.

### N3 — Option A Read-Path Audit (filed post-PR-#33 review)

**Status**: ticket filed at
`docs/tasks/2026-05-14_option-a-read-path-audit-ticket.md`.

The PR #33 Staff Engineer + 13F SME reviews flagged that the locked
`is_current` Option A contract is enforced as prose in AGENTS.md,
not mechanically. A future engineer can ship a screener / formula
that references an opinion metric_key and surface stale data.

Deliverable: `OPINION_METRIC_KEYS` registry + vocabulary guard on
screener_service + formula_engine (typed compile-time error) +
unify `_valuation_reference_by_stock` with `_m3_facts_by_stock` +
regression test.

PR #33 included the minimal fix (`_valuation_reference_by_stock`
period_end_date tiebreak). Full audit is this ticket.

### N4 — PR #33 Pre-Deploy Gates (filed post-PR-#33 review)

**Status**: ticket filed at
`docs/tasks/2026-05-14_pr33-pre-deploy-gates-ticket.md`.

PR #33 is merge-safe but not deploy-safe. Four gates must clear
before production traffic hits the merged code:

- D1: migration round-trip test against prod-like data dump.
- D2: Phase 1 formula comparison against production data.
- D3: operator runbook for Phase 3 rollback + observation monitoring.
- D4: release note for users + API consumers.
- D5: production VL coverage audit (informs D4 copy).

1-2 days of work. Hold deploy until gates clear.

### N5 — AGENTS.md Consolidation v2 (filed post-PR-#33 review)

**Status**: ticket filed at
`docs/tasks/2026-05-14_agents-md-consolidation-v2-ticket.md`.

PR #33 Documentation reviewer identified 5 cross-agent rules
currently in Claude-Code-only memory + 5 project rules scattered
across memory / code comments that should be in AGENTS.md.

Deliverable: AGENTS.md grows ~80 lines; memory becomes Claude-Code-
specific only; filename convention added for new task files.

Not a deploy blocker. Quality-of-life for cross-agent contributors.

## Gated on Observation Window (2025-Q4 cycle)

| Item | Trigger |
|---|---|
| **MVP8-01 Phase 4** — retire legacy `_stock_payload` formula + `?persisted=0` escape hatch | One full scoring cycle with zero `TOP10_RANK_SWAP` under the new persisted default |
| **MVP8-02 base divergence investigation** | Same observation window; PO then picks legacy→persisted (~70% scale change) or persisted→legacy normalization |

Both are queued task files; do NOT open before the observation
window data lands.

## LD4 — Explicitly Deferred (do not work on these)

| Item | Why deferred |
|---|---|
| **A3 Visual Radar** (bubble chart / cluster viz) | Below mobile + ingestion priority per LD2. Not the highest ROI right now. |
| **A4 Historical Expansion** (M5, EOD price backfill + period timeline) | Bigger track, needs its own gate. |
| **A5/A6** later VL overlay + historical price context | V1.1 / V2 scope. |
| **B Pre-2023 historical backfill productionization** | No PO demand signal. Stays at "curated dry-run only" indefinitely. |
| **C G1 (email alerts) + G9 (external ticketing)** | Slack / Discord webhooks suffice. Reopen only if production observation surfaces a gap. |
| **D Watchlist V1 non-13F scope** (sidebar / main table / MOS column expansion) | Decision gate not opened; partly covered by MVP7-01..06. |

## Backlog (Track-E, trigger-gated)

These are real items but should NOT be opened proactively. They
fire when their trigger lands:

| Item | Trigger |
|---|---|
| **DrawerShell** move to `@/components/ui/drawer-shell` + cross-cutting drawer a11y | Next drawer-touching feature (e.g., mobile stacked 13F view changes drawer layout) |
| **`_HolderContribution` data-loading abstraction** | 4th scoring algorithm needing >2 new fields on the dataclass |
| **Score-input sanity guards** (generic weight clamps) | Observed corruption case (NOT theoretical) |
| **`score_version` query param** for shadow compute | Shadow pipeline lands |
| **`vl_target_source_document_id` tooltip / click-through** to VL doc | UI enhancement when drawer evolves |
| **OpenAPI-generated frontend types** | Schema drift becomes an active problem (third field-misalignment incident) |
| **`_M3_METRIC_KEYS` relocation** to service module | 2nd consumer of the constant arrives |
| **Multi-doc per-field provenance** in `_m3_panel_for_stock` | Mixed-source M3 panels appear in real data |
| **`MetricFact.numeric_value()` helper** (encapsulate value_numeric → value_json.partial_score fallback) | Read paths multiply beyond 2 |

## Next Action

PR #33 is open and merge-safe. Order:

1. **Address PR #33 comprehensive review findings** (DONE 2026-05-14).
   Backend defensive parsing, `_valuation_reference_by_stock` Option A
   tiebreak, dual-chip tooltip wording, doc drift cleanup, CLAUDE.md
   tightening. Three follow-up tickets filed: N3 / N4 / N5.
2. **Clear PR #33 pre-deploy gates (N4)** before promoting merged
   commit to production traffic.
3. **Merge PR #33 to `main`** once N4 gates clear.
4. **Open the Mobile stacked 13F view ticket** as the next product
   work item (Section N1) — bundle with DrawerShell focus trap +
   move per Track-E gating.
5. **Open the Value Line ingestion coverage decision gate (N2)**
   after N1 lands.
6. **Ship the Option A read-path audit (N3)** before opening any
   surface that screens / formulas on opinion metrics.
7. **Ship AGENTS.md Consolidation v2 (N5)** when convenient — no
   ordering dependency, quality-of-life cross-agent improvement.

Everything else is either closed, deferred, observation-gated, or
trigger-gated.
