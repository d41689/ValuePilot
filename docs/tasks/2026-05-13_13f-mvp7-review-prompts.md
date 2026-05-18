# 13F MVP 7 End-to-End Review Prompts

Four reviewer prompts for the MVP 7 closing review. Each is
self-contained — drop the prompt into a fresh chat or hand it to a
human reviewer without needing the rest of this repository's
history. Verification baseline is in
`docs/tasks/2026-05-13_13f-mvp7-end-to-end-verification.md`.

Roles:

1. Staff Engineer — cross-ticket contract / decision-gate
   correctness.
2. Financial Data Product Reviewer (13F Domain SME) — signal
   density on the watchlist row, MOS × 13F threshold sanity,
   drawer detail accuracy.
3. Product Owner — closing-gate sign-off, scope-freeze
   confirmation, Post-MVP7 ranking.
4. Frontend / UX (optional) — responsive flow, drawer ARIA +
   focus, click affordance.

---

## 1. Staff Engineer Prompt

You are the Staff Engineer conducting the MVP 7 cross-ticket
review for the ValuePilot 13F automation track. MVP 7 is the
**Watchlist × 13F Insight** product-fusion milestone — five
sub-tickets shipped on branch `docs/13f-automation-prd`:

- `Pre-MVP7-01` Decision gate (D1–D5 locked) (`9bc08d0`).
- `MVP7-01` Backend `/stocks/13f-snapshots` batch endpoint
  (`560c394`).
- `MVP7-02` Watchlist row data plumbing (`a5d3442`).
- `MVP7-03` Four columns + group header (`e0753a6`).
- `MVP7-04` Responsive collapse + MOS × 13F glyph (`6559951`).
- `MVP7-05` Per-row drawer + `/stocks/{stock_id}/13f-detail`
  endpoint (`52c2243`).

Verification baseline: 806 backend tests / 0 warnings; alembic
head `20260512130000` (unchanged from MVP5-05 — no MVP7
migrations); 17 frontend `oraclesLens.test.js` cases (unchanged);
production build successful with `/watchlist` at 20.5 kB / 199 kB
First Load.

Review these cross-cutting concerns and return a verdict plus
pre-merge action items vs follow-up items:

1. **D1 hold: four V1 columns rendered.** Open
   `frontend/components/watchlist/Watchlist13FColumns.tsx` and
   confirm exactly four `<TableCell>` outputs per row (Conviction
   / Δ Holders / Distinctiveness / Caveats) with the chip-tone
   mapping documented in Pre-MVP7-01 D1. Confirm MVP7-03 SR0
   (no click-to-sort UX) is consistent with the pre-MVP7
   `/watchlist` Table behavior (which also has no per-column
   sort).

2. **D2 hold: group header format.** Open
   `frontend/lib/watchlist13f.ts:groupHeaderLabel` and confirm
   it returns `"13F (YYYY-Qn, as of YYYY-MM-DD)"`,
   `"13F (YYYY-Qn)"` for the deadline-null case, and `"13F (no
   data)"` for the period-null case. Confirm
   `period_filing_deadline` = `period_end + 45 days` per
   `_period_filing_deadline` in `backend/app/api/v1/endpoints/stocks_13f.py`.

3. **D3 hold: three unavailable-reason taxonomy.** Confirm the
   backend distinguishes `no_holders` from `below_min_holders`
   via a per-stock `Filing13F` count query when the stock isn't
   in the ranked universe. Confirm the frontend
   `unavailableTooltip(reason, period)` renders distinct V1 copy
   per reason. Confirm pytest covers all three branches in
   `test_mvp7_01_stocks_13f_snapshots.py` + matching coverage
   in `test_mvp7_05_stock_13f_detail.py`.

4. **D4 hold: three-tier responsive strategy.** Open
   `frontend/lib/watchlist13f.ts:responsive13FCellClass` and
   confirm the Tailwind class string composition:
   - Collapsed: `"hidden xl:table-cell"` (xl-only).
   - Expanded: `"hidden md:table-cell xl:table-cell"` (md+).
   Confirm `/watchlist/page.tsx` wires the toggle Button with
   `hidden md:flex xl:hidden` so it only renders at md
   viewports (768–1279px). Confirm the two `useEffect`s reading
   and writing `localStorage.getItem('watchlist-13f-expanded')`
   are correctly ordered (read on mount, write on every state
   change after mount).

5. **D5 hold: MOS × 13F glyph as MOS-column enhancement.**
   Open `frontend/lib/watchlist13f.ts:mosCrossSignal` and confirm
   the 4-tier logic matches Pre-MVP7-01 D5 verbatim
   (`mos ≥ 0.20 AND deltaHolders ≥ +1` → `aligned`; etc.).
   Confirm `null` inputs flatten to `neutral`. Confirm the glyph
   is rendered inline inside the existing MOS `<TableCell>` —
   NOT a new column.

6. **Batch + detail endpoint pair symmetry.** Both endpoints in
   `backend/app/api/v1/endpoints/stocks_13f.py` reuse
   `build_oracles_lens_dashboard(limit=0, use_persisted_scores=False)`.
   Confirm the column-summary fields (`conviction_score`,
   `conviction_percentile`, `delta_holders`, `adders_count`,
   `reducers_count`, `consensus_count`, `distinctiveness_tier`,
   `caveat_severity`, `score_confidence`) are byte-identical
   shape across the two endpoints — the watchlist drawer's
   header recap chips depend on this for visual continuity. The
   detail endpoint additionally exposes `top_holders[:3]` +
   structured `caveat_flags[]`; confirm the field set on
   `StockDetailTopHolder` matches the per-holder fields the
   drawer renders.

7. **Watchlist failure-isolation design.** The MVP7-02 SR1
   "frontend independent fetch" decision means the watchlist
   table renders even when the snapshot endpoint errors.
   Confirm `Watchlist13FColumns.tsx` handles the four
   `queryStatus` states (`idle` / `pending` / `error` /
   `success`) — error renders `⚠` with a tooltip, but the
   existing watchlist columns (ticker / price / MOS) are
   unaffected. Walk the failure path: kill the snapshot
   endpoint network call and confirm the main table still
   renders.

8. **Next.js route-collision fix on `/stocks/{stock_id}` vs
   `/stocks/13f-snapshots`.** Open
   `backend/app/api/v1/api.py` and confirm `stocks_13f.router`
   is registered BEFORE `stocks.router`. Without this ordering,
   FastAPI's route iteration matches `/{stock_id}` (int path
   param, GET-only) for `POST /stocks/13f-snapshots` and
   returns 405. This is documented in the MVP7-01 task spec but
   has no test guarding the order — recommend a test that
   POSTs to the endpoint and asserts non-405.

9. **`use_persisted_scores=False` still gated.** Both endpoints
   in `stocks_13f.py` pass `use_persisted_scores=False`
   explicitly. Confirm no query param exposes the persisted-read
   path on either endpoint — that's MVP5-03 Phase 3 territory.
   Confirm `stocks_13f.py` does not import anything from
   `oracles_lens_signals`.

10. **Pytest 0 warnings.** Confirm `pytest -q` ends with
    `806 passed in Xs` with NO "warnings" clause. The MVP4-10
    conftest savepoint hardening must still hold; MVP7 added 25
    new tests across two endpoints and must not have introduced
    SAWarning regressions.

11. **DrawerShell reuse from admin13f primitives (SR7).** The
    MVP7-05 `Watchlist13FDrawer` imports `DrawerShell` from
    `@/components/admin13f/Admin13FPrimitives`. The component is
    domain-agnostic but the import path is admin-prefixed.
    Decide: file as a Track-E refactor (move `DrawerShell` to
    `@/components/ui/drawer-shell` or similar) or accept as-is.
    No blocker for MVP7 closure.

Deliverable: APPROVE / APPROVE-WITH-FIXES / REJECT plus a
pre-merge action list (must-fix-before-MVP7-closes) vs follow-up
list (file as MVP8 backlog).

---

## 2. Financial Data Product Reviewer (13F Domain SME) Prompt

You are the 13F Domain SME reviewing MVP 7 — the
**Watchlist × 13F Insight** product fusion. MVP 7 is signal-
rendering on top of the existing scoring stack (no formula
changes), but the **operator-facing surfaces** need an SME pass
to confirm the column compression and threshold copy don't
mislead a value investor making a buy/sell decision.

Verification baseline:
`docs/tasks/2026-05-13_13f-mvp7-end-to-end-verification.md`.

Your goal: confirm the watchlist's per-stock 13F render
faithfully expresses the underlying scoring stack to a value
investor.

1. **Conviction percentile chip semantics.** Open
   `frontend/lib/watchlist13f.ts:formatConvictionLabel` and
   confirm the three-bucket compression (`Top 15%` if percentile
   > 0.85; `Mid X%` if > 0.5; `Bot X%` otherwise) is the right
   compression for the watchlist row. Does "Top 15%" mean what a
   value investor expects — that this stock is in the top 15%
   of CONVICTION across the ranked universe (not top 15% of
   ranking by signal-weighted consensus)? If conviction is
   what's measured here, is the label readable as that? Or
   should it say "Top 15% conviction" / "Top 15% by smart-money
   weight"?

2. **Δ Holders integer compression.** A signed integer like
   `+3` is high-density but loses the magnitude — `+3` could mean
   three small adds totaling 0.2% or three top-10 new positions.
   For a watchlist scan, does the integer alone tell the right
   story? Should the chip include a portfolio-weight signal
   (e.g. `+3 / 12% AUM`)? Or does the drawer's per-manager
   magnitude breakdown handle that depth-question correctly?

3. **Distinctiveness tier thresholds.** Open the backend
   `_distinctiveness_tier` function in
   `backend/app/api/v1/endpoints/stocks_13f.py`:
   - `distinctive`: `manager_signal_quality_coverage ≥ 0.7` AND
     `consensus_count ≤ 8`.
   - `crowded`: `consensus_count ≥ 20` AND
     `manager_signal_quality_coverage < 0.5`.
   - `mixed`: everything else.
   Are these the right cutoffs? In particular, is a 7-holder
   stock with 100% coverage truly "Distinctive" — or is 7 too
   small for confidence?
   Also: the dashboard's `_apply_manager_signal_profiles`
   overrides stored `manager_type` to behavior-derived at
   runtime, so coverage is usually high. This effectively makes
   the `crowded` tier hard to hit on simple inputs. Is this
   acceptable, or should the tier definition be rewritten to use
   different inputs (e.g. `unknown_manager_type_count > N`)?

4. **MOS × 13F cross-signal thresholds.** Pre-MVP7-01 D5:
   - `aligned`: `mos ≥ 0.20` AND `delta_holders ≥ +1`.
   - `exit-divergence`: `mos ≥ 0.20` AND `delta_holders ≤ −1`.
   - `buy-divergence`: `mos ≤ 0` AND `delta_holders ≥ +1`.
   Is `0.20` MOS the right "value setup" threshold? Some value
   investors might call `0.30` the threshold for "strong
   margin of safety". Should the glyph use `0.30` for
   `aligned` and `0.20` for a softer "Aligned (modest MOS)"
   variant? Or is one chip enough for V1?
   Is `delta_holders ≥ +1` the right "smart money adding"
   threshold? +1 could be a single small new position; +3 is
   more meaningful. Flag if you'd recommend a higher floor.

5. **Top holders card — value-investor read.** Open the drawer
   in browser (or read `Watchlist13FDrawer.tsx:TopHolderCard`).
   The card shows: manager_name link → admin / manager_type
   badge / action chip + share_delta_pct magnitude /
   position_weight % / holding_streak / accession_no. Is this
   the right set? Missing fields that an SME would want at a
   glance:
   - Fund AUM (would help distinguish "Klarman 5%" from "Random
     fund 5%").
   - Filer's portfolio rank for this position (e.g. "Top 5 of
     50 holdings" vs "65 of 100").
   - Latest filing date vs current date (to flag stale data).
   Flag if any are blockers for a value-investor's confidence in
   the conviction chip.

6. **Caveats panel completeness.** The drawer lists caveat
   flags with key / group / severity / label. Confirm the four
   group labels (`signal_quality` / `conviction` / `data_coverage`
   / `timing`) cover the right operational concerns. The
   dashboard's `_caution_flags` emits seven flag types — are any
   missing on the watchlist read-path that should be there?
   Specifically:
   - `partial_period` — what's the user-facing read if the
     selected period has limited manager coverage?
   - `old_period_selected` — does the user-facing watchlist
     ever surface an older period?

7. **manager_type override on derivation.** The dashboard's
   `_apply_manager_signal_profiles` derives `manager_type` from
   behavior heuristics (concentration / holding streak /
   turnover) at runtime, overriding the stored admin-classified
   `manager_type` column. The drawer's "manager_type badge"
   shows the DERIVED type, not the admin-classified type. Is
   this the right reading for a value investor? Or should the
   badge surface BOTH the derived AND the admin-classified
   types if they disagree (analogous to the MVP4-07b unknown-
   priority queue concept)?

8. **`use_persisted_scores=False` still gated on Phase 3.** The
   watchlist now exposes the same persisted-vs-in-memory
   ranking divergence as the admin Oracle's Lens dashboard.
   When MVP5-03 Phase 3 closes, the snapshot + detail endpoints
   will need to flip to `use_persisted_scores=True` in lockstep
   with the dashboard default. Flag this dependency in your
   review — it's a coordinated release, not two independent
   flips.

Deliverable: per-item APPROVE / FLAG / BLOCK verdict. BLOCKs
require a pre-MVP7-close fix; FLAGs can be filed as MVP8 backlog.
Pay extra attention to copy that could mislead a value investor
into believing the watchlist 13F signal is stronger or weaker
than the underlying scoring stack actually justifies.

---

## 3. Product Owner Prompt

You are the Product Owner reviewing MVP 7 closure for the
ValuePilot 13F automation track. MVP 7 is the
**Watchlist × 13F Insight** product fusion — five sub-tickets
shipped on branch `docs/13f-automation-prd`; verification
baseline is captured in
`docs/tasks/2026-05-13_13f-mvp7-end-to-end-verification.md`.

Your goal is to confirm that:

1. **All MVP7 sub-tasks closed against shipped code.** Walk each
   row of the MVP 7 Contract Checklist in the verification doc
   and open the cited commits. For each, confirm:
   - The task spec's acceptance criteria are met.
   - The scope refinements (SR list) accurately describe what
     was deferred.
   - No silent feature creep beyond the SR list.

2. **Scope-freeze tally is zero new scoring debt.** Verify by
   reading the post-MVP4 roadmap deferral entries — each should
   still trace to an explicit backlog line. If any has silently
   slipped into MVP7 scope, reopen it as a defect. Especially:
   zero new Alembic migrations, zero new scoring formulas, zero
   modified existing scoring formulas.

3. **D1–D5 decisions held against shipped code.** The
   Decision-Gate Verification table in the verification doc
   claims all five Pre-MVP7-01 decisions held. Spot-check one
   in the actual product:
   - Open `/watchlist` in a browser.
   - Confirm the 13F group header reads
     `"13F (YYYY-Qn, as of YYYY-MM-DD)"` with a real period.
   - Add a ticker with no 13F coverage; confirm the chips are
     `—` with hover tooltips.
   - Resize the browser between 1280px / 1000px / 600px;
     confirm the three-tier responsive collapse + toggle button
     work as D4 specifies.
   - Click the Conviction badge on a row with coverage; confirm
     the drawer slides in with the four sections.

4. **Watchlist UX is the right product shape for V1.** The four
   columns + group header + drawer is the V1 surface. Decide:
   - Is the click-to-sort omission (MVP7-03 SR0) acceptable for
     V1? Should it be promoted to a near-term Post-MVP7 ticket
     or stay deferred until a user signal appears?
   - Is the Conviction badge the right click target for opening
     the drawer? Or should there be a more explicit "Details"
     link / chevron in a fifth cell?
   - Should the drawer's "manager name → /admin/13f/managers/{id}"
     deep-link be admin-only (current state: any logged-in user
     can navigate there but the admin route gates further
     mutations)?

5. **MVP5-03 Phase 3 dependency.** MVP7 amplified the cost of
   NOT having Phase 3 closed — the watchlist now exposes the
   same persisted-vs-in-memory divergence as the admin dashboard.
   Decide:
   - Should MVP8-01 be opening MVP5-03 Phase 3 sign-off path?
   - Do you have staging/prod access for the comparison report
     run? If not, what's blocking it?

6. **Post-MVP7 candidate ordering.** Six candidates surfaced in
   the verification doc:
   - MVP5-03 Phase 3 server-default flip
   - Track A2 Oracle's Lens M3 valuation + quality overlay
   - Watchlist click-to-sort UX
   - MVP6-08 SME backlog FLAGs cluster
   - Mobile per-row stacked 13F view
   - Track C G1 + G9 admin gaps
   Rank these. State whether MVP8 opens immediately after MVP7-06
   commits, or whether you want a release window in between.

7. **GA messaging decision.** Once MVP7 ships, the watchlist
   has a meaningfully different product story — every row now
   carries per-stock 13F context. Is there a user-facing
   changelog / release note that should ship alongside? Draft a
   one-paragraph note if yes.

8. **Reviewer follow-up handling.** The Staff Engineer / SME /
   Frontend prompts may surface action items. Decide upfront:
   - Must-land-before-MVP7-closes — fix in this branch.
   - Should-fix-in-MVP8 — file as backlog ticket.
   - Could-fix-later — note but do not file.
   State your threshold.

Deliverable: MVP7 close sign-off verdict (APPROVE /
APPROVE-WITH-CONDITIONS / REJECT), Post-MVP7 candidate ranking,
MVP8 decision-gate timing, and a recommendation on reviewer
follow-up triage.

---

## 4. Frontend / UX Reviewer Prompt (Optional)

You are the Frontend / UX reviewer for the MVP 7
Watchlist × 13F Insight surface. MVP 7 adds four columns + a
responsive collapse + a MOS-column glyph + a click-into drawer to
the existing `/watchlist` page.

Files in scope:

- `frontend/lib/watchlist13f.ts` — types + helpers (formatters,
  tone variants, tooltip copy, responsive class composer).
- `frontend/components/watchlist/Watchlist13FColumns.tsx` —
  four per-row `<TableCell>`s.
- `frontend/components/watchlist/MosCrossSignalGlyph.tsx` —
  small ✓ / ⚠ icon on the MOS cell.
- `frontend/components/watchlist/Watchlist13FDrawer.tsx` —
  per-row drawer using `DrawerShell` from admin13f primitives.
- `frontend/app/(dashboard)/watchlist/page.tsx` — wire-up.

Review:

1. **Three-tier responsive flow.** Sign in. Open `/watchlist`.
   Resize the browser:
   - **≥ 1280px (xl)**: four 13F columns + group header always
     visible inline. No toggle button rendered.
   - **768–1279px (md)**: 13F columns + header hidden by
     default. "Show 13F" toggle button visible above the table.
     Click → columns expand, button label flips to "Hide 13F".
     Reload → expanded state persists via
     `localStorage['watchlist-13f-expanded']`.
   - **< 768px (sm)**: 13F columns + toggle both hidden; main
     watchlist columns scroll horizontally.

2. **Click affordance on Conviction badge.** On a row with
   `snapshot.available === true`, hover the Conviction chip —
   cursor changes to pointer; the tooltip suffix reads
   "(click for detail)". On a row with `—` placeholder, no
   click target. Tab into the row; Conviction button is focusable
   and activatable via Enter / Space.

3. **DrawerShell ARIA + focus.** Click Conviction chip → drawer
   slides in from the right. Confirm:
   - Drawer has `role="dialog"` and `aria-labelledby` pointing
     at the title element.
   - Focus moves into the drawer on open (close button).
   - Backdrop click closes the drawer.
   - Escape key closes the drawer (note: current `DrawerShell`
     implementation does not bind escape — flag if missing).
   - On close, focus returns to the originating Conviction
     button.

4. **MOS × 13F glyph rendering.** Find a row where `mos ≥ 20%`
   AND `delta_holders ≥ +1`. Confirm a green Check (✓) icon
   renders next to the MOS value with hover tooltip "Aligned…".
   Find a row where `mos ≥ 20%` AND `delta_holders ≤ −1`.
   Confirm an amber TriangleAlert (⚠) icon renders with
   "Re-examine…" tooltip. Rows without snapshot data render no
   glyph.

5. **Caveat severity icon on chip.** A row with `caveat_severity:
   high-caution` has an AlertTriangle icon prepended to the
   Caution chip. Tooltip lists the caveat codes
   (`flag.key.join(', ')`). Confirm the icon is decorative
   (`aria-hidden="true"`) and the chip's `title` attribute
   carries the readable description.

6. **Drawer content layout.** Open the drawer for a stock with
   coverage. Confirm:
   - Header recap: four summary chips matching the row.
   - Top Holders: 3 cards, each with manager name link,
     manager_type badge, position_weight %, action chip + Δ
     magnitude (when applicable), holding streak, accession_no.
     Manager link → `/admin/13f/managers/{id}` (note: opens
     admin route — flag if admin-only audience).
   - Caveats: structured cards with severity icon + label + group
     badge. Empty state copy is "No caveat flags on this signal."
   - Loading state during fetch: spinner + "Loading 13F
     detail..." message.
   - Error state: rose alert "Failed to load 13F detail. Try
     closing and reopening."

7. **Conviction percentile bucket boundary cases.** Find a
   stock where the percentile is in the boundary regions:
   - `> 0.85` → "Top X%" where X is the distance from top.
   - Exactly `0.85` → "Mid 15%" (falls into the mid bucket).
   - `> 0.5` → "Mid X%".
   - `≤ 0.5` → "Bot X%".
   Confirm the labels read naturally.

8. **Manager card overflow on long names.** Find a stock with
   a holder whose name is > 40 chars. Confirm the card layout
   doesn't break — the `min-w-0 flex-1` should truncate or wrap
   gracefully.

9. **Empty-state copy with three reason codes.** Force each:
   - `no_holders`: a stock with no 13F coverage at all.
   - `below_min_holders`: a stock with 1-2 ranked managers.
   - `no_qualifying_period`: a far-future period where the
     universe is empty.
   Confirm the tooltip body for each reason reads correctly
   when hovering the `—` cell.

10. **localStorage cleanup.** Toggle expand → collapse multiple
    times. Confirm `localStorage['watchlist-13f-expanded']`
    flips between `"true"` and `"false"` correctly. Clear
    localStorage; reload; confirm the default-collapsed state
    on first visit at md viewport.

Deliverable: per-item APPROVE / RECOMMEND-CHANGE / BLOCK with
specific copy / spacing / interaction notes.
RECOMMEND-CHANGEs are MVP8 backlog candidates unless they
materially affect operator trust (in which case escalate to the
PO before MVP7 closes).
