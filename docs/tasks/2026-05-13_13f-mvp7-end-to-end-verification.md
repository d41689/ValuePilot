# 13F MVP 7 End-to-End Watchlist × 13F Insight Verification

## Goal / Acceptance Criteria

Close MVP 7 (Watchlist × 13F Insight) with a Docker-based
verification pass across the five MVP7 sub-tasks and the four-role
review pattern. MVP 7 is the **product-fusion milestone** that
bridges the user-facing `/watchlist` surface with the 13F automation
engine built across MVP1–MVP6. The closing gate confirms that:

- The four V1 13F-derived columns (Conviction, Δ Holders,
  Distinctiveness, Caveats) render on `/watchlist` rows with the
  three-tier responsive collapse, MOS × 13F cross-signal glyph,
  and per-row drawer landing the full top-holder + caveat detail.
- The Pre-MVP7-01 D1–D5 decisions are held against shipped code
  with **no silent deviations**.
- One new backend endpoint pair (`POST /api/v1/stocks/13f-snapshots`
  + `GET /api/v1/stocks/{stock_id}/13f-detail`) reuses the existing
  scoring stack via `build_oracles_lens_dashboard` — no new scoring
  formulas, no schema migrations.
- Backend full suite passes at **806 / 0 warnings** (= MVP5-07
  baseline 781 + 19 MVP7-01 + 6 MVP7-05); the MVP4-10 conftest
  savepoint hardening still holds.
- Frontend lint, `node --test lib/oraclesLens.test.js`, and
  production `npm run build` all pass.
- Scope-freeze tally for MVP7 is **zero new scoring debt** —
  every Track A2 / B / C / E item from the post-MVP4 roadmap
  stays deferred. MVP5-03 Phase 3 + Phase 4 remain unchanged.
- MVP6-08 SME backlog FLAGs (manager_type evidence threshold,
  Kahn TP signal, Batch Reparse skip banner, Quality Reports
  drilldown) remain queued and **were not retro-fitted into
  MVP7**.

## Scope In

- Verification-only task log.
- Docker verification commands and results.
- Contract checklist for MVP7-01 through MVP7-05.
- Decision-gate verification for Pre-MVP7-01 D1–D5.
- Bundle-size + route-table snapshot post-MVP7.
- Four review roles, prompts filed in
  `docs/tasks/2026-05-13_13f-mvp7-review-prompts.md`.
- Minimal fixes only if verification exposes a regression.

## Scope Out

- New feature work, scoring changes, backend additions.
- MVP5-03 Phase 3 server-default flip (still gated on staging/prod
  PO sign-off — unchanged by MVP7).
- MVP5-03 Phase 4 `?persisted=0` retirement.
- MVP6-08 SME backlog FLAGs (filed for a future ticket).
- Track A2 (valuation overlay), Track B (pre-2023 backfill),
  Track C (admin G1/G9), Track E (engineering debt) — all
  deferred per the post-MVP4 roadmap.

## PRD / Decision References

- `docs/prd/watchlist/watchlist-v1.md` — existing equity-research
  watchlist V1 PRD (unchanged).
- `docs/prd/13f_automation_and_resilience_prd.md` §7 (Oracle's
  Lens scoring vocabulary that the snapshot endpoint composes).
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §7
  (V1 score surface).
- `docs/tasks/2026-05-13_pre-mvp7-01-watchlist-13f-insight-decision-gate.md`
  — D1–D5 design decisions filed and locked here.
- `docs/tasks/2026-05-12_13f-mvp6-end-to-end-verification.md` —
  MVP6 closure that authorized MVP7 kickoff.

## Docker Verification Commands

- `docker compose exec api alembic current`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run build`

## MVP 7 Contract Checklist

- [x] **Pre-MVP7-01** Watchlist × 13F Insight Decision Gate.
      `9bc08d0`. D1–D5 design decisions filled in: four V1
      columns, group-header format, empty-state copy, three-tier
      responsive strategy, MOS × 13F glyph as MOS-column
      enhancement. Six-ticket sequence MVP7-01..06 sequenced
      with MVP7-04 / MVP7-05 parallelizable after MVP7-03.
- [x] **MVP7-01** Backend `/stocks/13f-snapshots` batch endpoint.
      `560c394`. Reuses `build_oracles_lens_dashboard(limit=0,
      use_persisted_scores=False)` per MVP5-03 Phase 3 gating;
      computes per-stock conviction percentile + Δ holders +
      distinctiveness tier + caveat severity. Distinguishes three
      unavailable branches (`no_holders` / `below_min_holders`
      / `no_qualifying_period`). 19 pytest cases. Registered
      BEFORE `stocks.router` so the literal route matches before
      `/stocks/{stock_id}` int path-param swallows the URL.
- [x] **MVP7-02** Watchlist row data plumbing. `a5d3442`. New
      `frontend/lib/watchlist13f.ts` with discriminated-union
      types + `useWatchlist13FSnapshots` React Query hook
      (60s `staleTime`, `enabled` gate) +
      `buildSnapshotsByStockId` O(1) lookup map. `/watchlist/page.tsx`
      wires hook + map. Plumbing locked as frontend independent
      fetch (not extending `_watchlist_rows_for_memberships`) for
      failure isolation + independent loading state + clean cache
      lifecycle.
- [x] **MVP7-03** Four 13F columns + group header. `e0753a6`.
      `Watchlist13FColumns.tsx` renders the four cells per row.
      `frontend/lib/watchlist13f.ts` extended with 10 pure
      formatter / tone / tooltip / group-header helpers.
      `/watchlist` Table becomes a 2-row header
      (`colSpan={8}` spacer + `colSpan={4}` group header).
      Click-to-sort UX explicitly deferred per SR0 (existing
      watchlist has no per-column sort either; cross-cutting
      ticket).
- [x] **MVP7-04** Responsive collapse + MOS × 13F glyph.
      `6559951`. Three-tier responsive: xl (≥1280px) inline, md
      (768–1279px) toggle button + localStorage state, sm
      (<768px) hidden. New `MosCrossSignalGlyph` component with
      4-tier signal logic (`aligned` / `exit-divergence` /
      `buy-divergence` / `neutral`) injected into the existing
      MOS cell — not a new column.
- [x] **MVP7-05** Per-row 13F drawer. `52c2243`. New backend
      `GET /api/v1/stocks/{stock_id}/13f-detail` endpoint (404
      for unknown stock; 200 + reason for unavailable; 200 +
      full detail for ranked). Projects `_stock_payload.top_holders[:3]`
      + full caveat_flags. New `Watchlist13FDrawer` component
      mounts `DrawerShell` (reused from admin13f primitives).
      Conviction badge becomes a clickable button when
      `snapshot.available === true`. 6 pytest cases.

## Verification Results

- `docker compose exec api alembic current` — at head
  `20260512130000` (MVP5-05 manager_type review events). **No
  MVP7 migrations**, as expected for a product-fusion milestone
  that composes existing scoring + data tables.
- `docker compose exec api pytest -q` — **806 passed in 58.97s,
  0 warnings** (= MVP5-07 baseline 781 + 19 MVP7-01 + 6 MVP7-05).
  MVP4-10 conftest savepoint hardening still holds.
- `docker compose exec web npm run lint` — No ESLint warnings or
  errors.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  — **17 passed** (unchanged from MVP6 baseline). MVP7 added
  no frontend tests per the SR pattern across MVP7-03..05.
- `docker compose exec web npm run build` — compiled
  successfully. Relevant route table:
  ```
  ├ ○ /admin/13f                            7.19 kB         168 kB
  ├ ○ /admin/13f/filings                    5.97 kB         191 kB
  ├ ○ /admin/13f/holdings                   5.38 kB         163 kB
  ├ ○ /admin/13f/jobs                       8.08 kB         196 kB
  ├ ○ /admin/13f/managers                   2.06 kB         191 kB
  ├ ƒ /admin/13f/managers/[id]              2.7 kB          191 kB
  ├ ○ /admin/13f/readiness                  10.1 kB         195 kB
  ├ ○ /admin/13f/sync                       5.32 kB         190 kB
  ├ ○ /watchlist                            20.5 kB         199 kB
  └ ○ /watchlist/f-score-compare            5.69 kB         179 kB
  ```
  All eight admin/13f routes from MVP6 unchanged; `/watchlist`
  grew from 17.1 kB (pre-MVP7-02) → 20.5 kB across MVP7-02..05
  with First Load JS 190 → 199 kB.

### /watchlist Bundle Growth Across MVP7

| After | Route bundle | First Load JS | Δ |
| ----- | ------------ | ------------- | - |
| MVP6 (pre-MVP7) | 17.1 kB | 190 kB | — |
| MVP7-02 plumbing | 17.2 kB | 190 kB | +0.1 kB / 0 |
| MVP7-03 four columns + header | 16.1 kB | 193 kB | −1.1 kB / +3 kB (component extracted to shared chunk) |
| MVP7-04 responsive + glyph | 16.8 kB | 193 kB | +0.7 kB / 0 |
| MVP7-05 drawer + detail hook | 20.5 kB | 199 kB | +3.7 kB / +6 kB |

Total MVP7 frontend cost on `/watchlist`: **+3.4 kB route bundle
+ 9 kB First Load JS**, including all five sub-tickets'
contributions. Reasonable for the product unlock delivered.

## Decision-Gate Verification (Pre-MVP7-01 D1–D5)

| Decision | Status | Evidence |
| -------- | ------ | -------- |
| **D1** Four V1 columns (Conviction percentile / Δ Holders / Distinctiveness tier / Caveat severity) under a 13F group header | HELD | `frontend/components/watchlist/Watchlist13FColumns.tsx` renders exactly these four cells. Sort-key spec preserved in MVP7-03 SR0 for a future table-wide sort ticket; no click-to-sort shipped, matching the existing watchlist's pre-MVP7 behavior. |
| **D2** Group header `13F (YYYY-Qn, as of YYYY-MM-DD)` with SEC filing deadline format | HELD | `groupHeaderLabel(period, periodFilingDeadline)` in `frontend/lib/watchlist13f.ts` returns the exact format. Backend `period_filing_deadline` = `period_end + 45 days` per pytest test `test_snapshot_specific_period_override`. Empty fallback `"13F (no data)"` covered. |
| **D3** Empty-state copy with three reason codes | HELD | `unavailableTooltip(reason, period)` in `frontend/lib/watchlist13f.ts` returns the canonical V1 tooltip body for `no_holders` / `below_min_holders` / `no_qualifying_period`. Backend pytest covers all three reasons. Frontend renders `—` placeholder with native HTML `title` attribute carrying the body. |
| **D4** Three-tier responsive collapse (xl inline / md toggle + localStorage / sm hidden) | HELD | `responsive13FCellClass(mdExpanded)` composes the Tailwind classes; `/watchlist/page.tsx` wires `mdExpanded` state + two `useEffect`s reading/writing `localStorage['watchlist-13f-expanded']`; toggle Button uses `hidden md:flex xl:hidden`. Per-row stacked view on sm explicitly deferred per Pre-MVP7-01 D4 SR. |
| **D5** MOS × 13F cross-signal glyph as MOS-column enhancement (not a new column) | HELD | `MosCrossSignalGlyph` renders inline inside the MOS `<TableCell>` after the formatted MOS value. `mosCrossSignal({mos, deltaHolders})` returns 4-tier signal with `neutral` fallback for any null input. Pre-MVP7-01 D5 threshold table held verbatim (`mos ≥ 0.20` AND `delta_holders ≥ +1` → aligned, etc.). |

## Scope-Freeze Tally

All MVP7 scope-out items from the execution plan + Pre-MVP7-01 SR
list remain deferred:

- **Track A2** Oracle's Lens Milestone 3 (quality / valuation
  overlay) — explicitly off-limits.
- **Track A3 / A4 / A5 / A6** later Oracle's Lens milestones.
- **Track B** Pre-2023 historical backfill productionization —
  no investor demand signal, stays curated dry-run.
- **Track C** Admin G1 (email alerts) and G9 (external ticketing)
  — Slack / Discord webhooks remain sufficient.
- **Track E** Engineering debt (per-manager loader extraction,
  score-input sanity guards) — stays deferred.
- **MVP5-03 Phase 3** server-default flip — still gated on
  staging / prod PO sign-off. The MVP7-01 + MVP7-05 endpoints
  explicitly pass `use_persisted_scores=False`.
- **MVP5-03 Phase 4** `?persisted=0` retirement — post-Phase 3.
- **MVP6-08 SME backlog FLAGs**:
  - `manager_type` editor `note` required for non-`unknown`
    transitions + `evidence_json` threading.
  - Historical Backfill Kahn Brothers TP signal.
  - Batch Reparse `missing_raw_infotable_count` banner promotion.
  - Quality Reports V2 per-finding drilldown panel.
  All four queued, none retro-fitted into MVP7.
- **Watchlist click-to-sort UX** — deferred per MVP7-03 SR0.
- **Mobile per-row stacked 13F view** — deferred per MVP7-04 D4 SR.

Cumulative scope-freeze tally: **zero new backend / scoring debt
opened by MVP7**. Zero new Alembic migrations. **25 new pytest
cases** (19 MVP7-01 + 6 MVP7-05) — pure endpoint coverage, no new
scoring or schema logic.

## Post-MVP7 Decision Inputs

When MVP7-06 closes, the following candidates are ready for the
next decision gate (NOT committed yet — inputs to the next gate,
not outputs of this one):

1. **MVP5-03 Phase 3** server-default flip — still the open GA
   gate. Watchlist × 13F now exposes the same persisted-vs-
   in-memory question to a wider surface; Phase 3 unblocks both
   surfaces in one move.
2. **Track A2** Oracle's Lens Milestone 3 (quality + valuation
   overlay) — natural depth-expansion of the Watchlist 13F
   signal we just shipped. Adds valuation reference + quality
   overlay alongside the conviction/distinctiveness chips.
3. **Watchlist click-to-sort UX track** — table-wide sort across
   existing columns (MOS / Price / FV) + the four new 13F columns.
4. **MVP6-08 SME backlog FLAGs cluster** — four small admin-UX
   tickets queued from the MVP6 closing review.
5. **Mobile per-row stacked 13F view** — deferred from MVP7-04
   D4 SR. Re-open when mobile usage signal appears.
6. **Track C G1 + G9** admin email + external ticketing — only
   if production observation surfaces a Slack / Discord coverage
   gap.

## Review Pattern

Four reviewer prompts filed in
`docs/tasks/2026-05-13_13f-mvp7-review-prompts.md`:

- **Staff Engineer** — cross-ticket contract review (D1–D5 hold,
  shared-component coupling, batch + detail endpoint pair
  symmetry, Watchlist 13F failure-isolation design, Next.js
  route-collision fix on `/stocks/{stock_id}` vs
  `/stocks/13f-snapshots`).
- **Financial Data Product Reviewer (13F Domain SME)** —
  signal-density correctness (does the chip rendering match what
  a value investor actually wants on a watchlist row?), MOS × 13F
  glyph threshold sanity, top-holders card copy accuracy,
  caveat-flag surfacing on the drawer.
- **Product Owner** — closing-gate sign-off, scope-freeze
  confirmation, Post-MVP7 candidate ranking, MVP8 decision-gate
  timing.
- **Frontend / UX (optional)** — three-tier responsive flow on
  actual viewport widths, drawer ARIA + focus semantics, click
  affordance on the Conviction badge, localStorage persistence
  across reload.

## Recommendation

**MVP 7 is closed as shipped.** The Watchlist × 13F product
fusion is operational: every `/watchlist` row now exposes the
four V1 13F signals with responsive collapse + cross-signal
glyph + per-row drawer drilldown. Pre-MVP7-01 D1–D5 all held
against shipped code with no silent deviations. Verification
baseline (806 backend / 17 frontend / 0 warnings) is met.

The four-role review can run in parallel and is not blocking for
declaring MVP7 done — it is a quality gate. Any follow-up items
surfaced by reviewers should be filed as backlog tickets, not
retro-fitted into MVP7.

The next decision gate is MVP8. Inputs are listed above under
"Post-MVP7 Decision Inputs"; the PO ranks them and opens the
chosen first ticket. **MVP5-03 Phase 3** is the front-runner —
it's the open GA gate that's been waiting since MVP5-07, and
Watchlist × 13F now amplifies the cost of NOT having that
persisted-scoring contract validated. Track A2 (valuation
overlay) is the natural follow-on once Phase 3 closes.

## Review Outcomes (2026-05-13)

All four review roles ran against shipped code:

### Staff Engineer — APPROVE

D1-D5 all hold against implementation. Both endpoints explicitly
`use_persisted_scores=False` and don't import `oracles_lens_signals`.
`stocks_13f.router` correctly registered before `stocks.router`.

### 13F Domain SME — FLAG, no BLOCK

V1 acceptable. Two copy items flagged as priority pre-close fixes;
threshold items deferred to MVP8.

### Product Owner — APPROVE-WITH-CONDITIONS

Five sub-tasks reconcile with verification doc. No new migrations,
no new scoring formulas, no silent feature creep. MVP8 ranking
locked: (1) MVP5-03 Phase 3; (2) copy / SME flag cluster including
"13F common weight"; (3) Track A2 valuation + quality overlay;
(4) Watchlist click-to-sort UX; (5) Mobile stacked 13F view;
(6) Track C G1 / G9 admin gaps.

### Frontend / UX — RECOMMEND-CHANGE, no BLOCK

Responsive + click + Conviction-button focusability all OK.
A11y + accession-URL items recommended for MVP8.

### Pre-MVP8 fixes landed in this commit

Four reviewer recommendations addressed in MVP7-06 review-fix
commit (next commit after this doc edit):

1. **Conviction chip label** — `formatConvictionLabel` now returns
   `"Top N% conviction"` / `"Mid N% conviction"` / `"Bot N% conviction"`.
   SME flag: prevents misreading as overall ranking or
   signal-weighted consensus position.
2. **Top holder card terminology** — `"of portfolio"` replaced
   with `"13F common weight"` per PRD unified terminology
   requirement. SME + PO double-flag (the SME explicitly named
   this as the priority pre-close fix, and the PO ranked the
   "copy / SME cluster" as MVP8 #2 priority — landing the most
   acute term here closes the misleading reading without
   widening MVP7 scope).
3. **Route-order regression test** — new
   `test_snapshot_route_order_not_swallowed_by_stock_id_int_param`
   in `test_mvp7_01_stocks_13f_snapshots.py`. POSTs to
   `/api/v1/stocks/13f-snapshots` and asserts non-405. Documents
   the registration-order constraint and the failure mode
   (`stocks_13f.router` BEFORE `stocks.router`) so the next
   contributor can't accidentally swap them.
4. **Accession link** — the original `<Link>` pointed at an
   EDGAR browse URL with empty CIK, which lands on an unhelpful
   search page (looks clickable, isn't useful). Replaced with
   `<span>` rendering the accession number as plain text plus
   a `title` tooltip. The proper accession-to-filing URL needs
   CIK (`https://www.sec.gov/Archives/edgar/data/{CIK}/{accession-no-dashes}/`),
   which is not in the `top_holders` payload today. Queued for
   MVP8 (threads `cik` through `_stock_payload.top_holders` →
   `StockDetailTopHolder` schema → drawer Link).

### Deferred to MVP8 backlog

Not retro-fitted into MVP7; filed for MVP8 candidate ordering:

- **DrawerShell → `@/components/ui/`** (Staff Engineer follow-up).
  Cross-cutting refactor affecting 8+ admin/13f route mounts
  plus the new watchlist mount. Track-E ticket.
- **Drawer Escape close + open-autofocus + close-focus-return**
  (Frontend reviewer; reviewer themselves marked as MVP8 a11y
  fix). Same cross-cutting reach as the DrawerShell move.
- **Long manager name truncate** (Frontend reviewer; pending
  visual QA decision).
- **manager_type derived vs admin-classified dual-display in
  drawer** (SME flag; design question, not a defect).
- **Distinctiveness threshold review** — V1 ships at
  `consensus_count ≤ 8 AND coverage ≥ 0.7 → distinctive`;
  `crowded` tier reachability noted as low because behavior-
  derivation pushes coverage high on simple fixtures. SME
  recommended MVP8 floor review (potentially gate on raw
  `unknown_manager_type_count` instead of derived coverage).
- **MOS × 13F threshold review** — V1 ships at
  `mos ≥ 0.20 AND delta_holders ≥ +1 → aligned`. SME recommended
  MVP8 evaluation of raising to `0.30 / +3` or splitting into a
  two-tier aligned signal.
- **Δ Holders chip portfolio-weight context** — non-blocker
  (the drawer's per-manager magnitude already covers depth).

### Post-fix verification

- `docker compose exec api pytest -q tests/unit/test_mvp7_01_stocks_13f_snapshots.py`
  → **20 passed** (= 19 + 1 new route-order regression test).
- `docker compose exec api pytest -q` → **807 passed**, 0
  warnings (= 800 MVP6-08 baseline + 19 MVP7-01 + 6 MVP7-05 +
  1 route-order regression test).
- `docker compose exec web npm run lint` → No ESLint warnings or
  errors.
- `docker compose exec web npm run build` → compiled successfully.
  `/watchlist` bundle 20.5 → 20.4 kB (tiny shrink from the
  removed broken Link wrapper); First Load JS 199 kB unchanged.

**MVP 7 is closed.** PO sign-off applied 2026-05-13 with the
four review-fix items landed in the same branch. The five
MVP8-backlog FLAGs are queued for the next decision gate
alongside the six Post-MVP7 candidate inputs.
