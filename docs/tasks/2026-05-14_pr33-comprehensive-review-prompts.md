# PR #33 Comprehensive Review Prompts

Six reviewer prompts for the **PR-level** review of `docs/13f-automation-prd`. Each prompt is self-contained — drop into a fresh chat or hand to an external agent without prior context.

**PR**: https://github.com/d41689/ValuePilot/pull/33
**Branch**: `docs/13f-automation-prd`
**Base**: `main` (tip `d5d275d`)
**Scale**: ~170 commits, ~250 files changed, MVP3 → MVP8 + Track-E + agent workbook consolidation

**Why PR-scale review (not per-MVP):** every individual MVP already had its own four-role review pass with sign-off trail. This review catches **cross-MVP drift** — contracts that shifted between MVPs, decisions that were locked late and apply retroactively, and "is this PR-as-a-whole safe to merge" questions that per-ticket reviews can't answer.

**Reviewers do NOT need to read 170 commits.** Each prompt points to canonical artifacts (closed-ticket task files, locked decision gates, the consolidated AGENTS.md) so the reviewer reads the **outputs** of the work, not the commit history.

**Canonical artifacts for all reviewers:**

- `AGENTS.md` — consolidated project workbook (228 lines; locked data contracts, verification discipline)
- `docs/tasks/2026-05-14_open-work-snapshot.md` — what's done / deferred / gated / next
- `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md` — locked Option A
- `.claude/projects/<repo>/memory/MEMORY.md` (Claude-Code-only mirror; canonical is AGENTS.md)

Roles (priority order):

1. **13F Domain + Financial SME — HIGH.** Product semantic correctness.
2. **Staff Engineer / Architecture — HIGH.** Cross-cutting contracts + design.
3. **Backend Reviewer — MEDIUM.** Scoring correctness + migration safety.
4. **Frontend Reviewer — MEDIUM.** Watchlist surface + a11y + shadcn discipline.
5. **Documentation / Workflow Reviewer — MEDIUM.** Workbook consolidation + task file coherence.
6. **Production Readiness Reviewer — HIGH.** Merge-now-vs-stage decisions.

---

## 1. 13F Domain + Financial SME Prompt

You are the 13F domain SME conducting a PR-level review of `docs/13f-automation-prd` (PR #33 on GitHub). The branch is large (~170 commits, MVP3 → MVP8) and you should NOT read it commit-by-commit. Per-MVP reviews already happened; your job is to catch **product semantic drift across MVPs** and verify the final user-facing surfaces are correct.

**Read these in order (≈30 min):**

1. `docs/tasks/2026-05-14_open-work-snapshot.md` — what shipped / deferred / gated.
2. `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md` — locked `is_current` design (Option A).
3. `AGENTS.md` — `## Data Layer` section, especially `is_current` semantics + `Frontend UI Standard` enforcement note.
4. `docs/tasks/2026-05-13_mvp8-a2-watchlist-m3-overlay.md` — drawer M3 overlay (Watchlist Quality & Valuation panel).
5. `docs/tasks/2026-05-13_mvp8-03b-watchlist-scoring-sme-fixes.md` — SME flag cluster shipped (4 watchlist/scoring fixes).
6. `frontend/components/watchlist/Watchlist13FDrawer.tsx` — drawer rendering the 13F signals.
7. `frontend/components/watchlist/Watchlist13FColumns.tsx` — the four 13F columns.

**Six product questions:**

### Q1 — `is_current` Option A long-term durability

The decision gate closed at Option A (status quo + read-side tiebreak). For VL opinion metrics, multiple `is_current=True` rows coexist and the M3 panel picks the most recent via `period_end_date DESC` tiebreak.

- Are there opinion-metric consumers we haven't anticipated that can't use read-side tiebreak? (e.g., a future alerting service that queries `WHERE is_current=true` and would mis-fire on stale targets)
- The CLAUDE.md / AGENTS.md contract says "reopen the gate if a second opinion-metric consumer cannot use the tiebreak." Is this trigger condition discoverable enough, or will a future engineer just ship a consumer that mis-reads stale opinions?

### Q2 — Watchlist drawer M3 coverage limitations

The dev DB has 7 stocks with VL data; 5 overlap with 13F holdings. The drawer's Quality & Valuation panel shows `Value Line data is not available for this stock in the current dataset.` for the ~99% of stocks lacking VL.

- Is the "not available in the current dataset" copy honest enough about why? Specifically, does it correctly avoid implying "coming soon" for stocks that may never be ingested (small caps / foreign filings / ADRs)?
- Are the displayed signals (Piotroski `X/Y*`, earnings predictability %, VL 18-month target range with `VL report dated YYYY-MM-DD`) the right cut for V1, or is something missing that investors actually use (e.g., dividend yield, payout ratio, debt coverage)?

### Q3 — The four 13F columns on /watchlist

Conviction percentile / Δ Holders / Distinctiveness / Caveats. These are the at-a-glance row signals.

- Is this the right V1 cut for "what makes a 13F-informed research candidate worth deeper analysis"? What would you ADD if you could only add one column?
- The Caveats sort default is `desc` (worst-first). Is this the right UX for someone scanning a watchlist, or does it disproportionately scare users who would otherwise click into clean rows?

### Q4 — Kahn Brothers True Positive caveat

`AGENTS.md` Parsing → EDGAR/13F gotchas records: "Kahn Brothers (`0001039565-*`) reports values in dollars, not thousands — reconciliation warnings for this filer are True Positives, not bugs." The MVP8-03A admin Historical Backfill card adds an amber banner when Kahn is in the quarter range.

- Is hardcoding one filer's reporting convention the right pattern, or should the system have a more general "filer-level reporting override" mechanism (e.g., a `manager_value_unit` column) so future similar filers can be flagged without code changes?
- Are there OTHER known filers in your domain knowledge with non-standard reporting that should be flagged the same way?

### Q5 — Manager type taxonomy + admin classification (MVP8-03B B1)

The drawer surfaces both `manager_type` (behavior-derived) and `manager_type_admin_classified` (curated). Dual chip fires only when admin has set a non-unknown value that diverges from derived.

- Is this dual-display the right pattern for transparency about how the manager profile was assigned, or is it confusing for users who don't know the difference between "derived" and "admin-classified"?
- For research users specifically (not admins), would you prefer the dual chip to be a tooltip rather than a permanent UI element?

### Q6 — Cross-MVP signal coherence

Read both the legacy Oracle's Lens page (`/13f/oracles-lens`) AND the new Watchlist 13F drawer. The two surfaces both show 13F signals for the same stocks but with different framings.

- For the 5 overlap stocks (ADBE, FICO, FNV, GOOG, MTDR in dev), would a research user reach the SAME conclusion from both surfaces, or do they tell conflicting stories?
- Specifically check: does the legacy page's caveats panel align with the watchlist drawer's caveats list? Does the Piotroski score show the same value? (D2 should have unified these post-2026-05-13.)

**Verdict format:**

```
APPROVE / APPROVE WITH NOTES / REJECT

Q1: ...
Q2: ...
Q3: ...
Q4: ...
Q5: ...
Q6: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

Be terse — this is a PR-level review, not a per-MVP one.

---

## 2. Staff Engineer / Architecture Reviewer Prompt

You are the Staff Engineer reviewing PR #33. The branch contains ~170 commits across MVP3 → MVP8 + Track-E + an agent workbook consolidation. Per-MVP architectural decisions have already been reviewed; your job is to verify the **cross-MVP contracts** still hold and the **locked design decisions** are mechanically enforceable.

**Read these in order (≈45 min):**

1. `AGENTS.md` end-to-end — this is the canonical workbook, recently consolidated from CLAUDE.md.
2. `CLAUDE.md` — should be minimal (16 lines), `@AGENTS.md` import pattern.
3. `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md` — Option A locked.
4. `docs/tasks/2026-05-13_mvp8-01-mvp5-03-phase3-flip.md` — Phase 3 server-default flip; Phase 4 retirement gated.
5. `backend/app/services/oracles_lens/dashboard.py` — find `_m3_facts_by_stock`, `_quality_overlay_by_stock`, `_fact_value` (D2 unification).
6. `backend/app/api/v1/endpoints/stocks_13f.py` — `_m3_panel_for_stock`, `_M3_METRIC_KEYS`.
7. `backend/app/schemas/stocks_13f_snapshot.py` — `QualityOverlay` typed model.
8. Spot-check 3-4 closing-gate task files (pick from MVP4-12, MVP5-06, MVP6-08, MVP7-06) to verify sign-off trails are consistent.

**Seven architectural questions:**

### A1 — Cross-MVP contract drift on `is_current`

The contract was locked retroactively (2026-05-14) after MVP8-A2 D4 investigation revealed the naive interpretation would wipe ~99% of data. Earlier MVPs (MVP3, MVP4, MVP5) wrote code under an unclear contract.

- Verify: does ANY pre-MVP8 code path enforce "one `is_current=True` per `(stock_id, metric_key)`" implicitly? Check `piotroski_f_score.py`, `value_line_ratios.py`, `ingestion_service._reconcile_parsed_fact_current_slot`, `document_dedupe_service.py`. Per AGENTS.md these should all scope by `(stock_id, metric_key, period_type, period_end_date, source_type)` — confirm.
- Are there read paths anywhere that filter `WHERE is_current=true` without a period tiebreak and would surface stale VL opinions? Grep for `is_current` filters across `backend/app/`.

### A2 — `_m3_facts_by_stock` abstraction sufficiency

D2 unified the M3 read path: legacy `_quality_overlay_by_stock` and new `_m3_panel_for_stock` both call `_m3_facts_by_stock`. `_fact_value` falls back to `value_json['partial_score']` for composite scores.

- Is the shared helper the right abstraction, or did D2 leave cross-cutting structure on the table? Specifically: should the metric-key → response-shape mapping logic be moved into a shared "ResponsePayload" builder, or is keeping that per-caller correct?
- `_fact_value` reads `value_numeric` first then falls back to `value_json['partial_score']`. Is this fallback too narrow (Piotroski-specific)? Should it be a configurable per-metric-key transformation (e.g., a `MetricCoercer` registry)?

### A3 — Phase 3 / Phase 4 server-default-flip safety

`use_persisted_scores` server default flipped `False` → `True` for `/oracles-lens`, `/stocks/13f-snapshots`, `/stocks/{id}/13f-detail`. The `?persisted=0` escape hatch remains. Phase 4 (retire the escape hatch + delete legacy formula) is gated on observation window.

- The flip happened mid-branch. Is there any code path that still hardcodes `use_persisted_scores=False` and would silently regress to the legacy formula? Search for `use_persisted_scores=False` outside tests.
- Phase 4 will delete `_stock_payload` formula in `dashboard.py`. Is the deletion mechanically blockable by a missing dependency (e.g., a test that exercises only the legacy path), or could it be deleted accidentally without anyone noticing?

### A4 — Agent workbook consolidation correctness

CLAUDE.md was 86 lines of project-level contracts; AGENTS.md was 365 lines with ~190 lines of aspirational Phase 0-7 process content. Post-consolidation: AGENTS.md is 228 lines (contracts merged in, aspirational content deleted), CLAUDE.md is 16 lines (Claude-Code-only).

- Is `@AGENTS.md` import on line 1 of CLAUDE.md mechanically correct? (Claude Code documentation says `@filename` imports file content into the system prompt.)
- The consolidation moved 5 contracts from CLAUDE.md → AGENTS.md without changing wording. Verify any cross-references (e.g., the old "see CLAUDE.md" pointers in commit messages, task files, or memory) still resolve correctly.
- Memory file `feedback_local_green_vs_ci_green.md` says "canonical version in AGENTS.md → Verification Discipline." Is the memory framing (Claude-Code-only reinforcement, not canonical) correct, or does it create a maintenance hazard if AGENTS.md changes but memory doesn't?

### A5 — `_M3_METRIC_KEYS` placement

The constant lives in `backend/app/api/v1/endpoints/stocks_13f.py` (endpoint module). The previous review suggested moving it to `oracles_lens/dashboard.py` near `QUALITY_METRIC_KEYS` for consistency.

- Is the current placement acceptable given there's one consumer, or is this an architecture violation that should block? The Track-E backlog defers this until a second consumer arrives.

### A6 — Branch size and PR strategy

This PR has ~170 commits. Per `feedback_local_green_vs_ci_green.md`, long-lived unpushed branches mask CI failures (PR #33 itself hit this with `uiStandard.test.js`).

- What's the right PR cadence for this codebase going forward? Per-MVP? Per-decision-gate-closure? The current pattern is "long-lived branch, single mega-PR" — does that scale, or should the next track open a new branch and push per-milestone?
- Is the 168-commit branch reviewable as a SINGLE PR, or should it be split before merge?

### A7 — Migration sequence + reversibility

Alembic head is `20260513140000` (cusip_ticker_map.ticker VARCHAR widening). The branch contains many migrations.

- Trace the migration sequence: are all migrations reversible (`downgrade()` defined and tested)?
- Is the migration ordering causally correct (no migration assumes data shape from a later migration)?
- Has the full sequence been applied against a prod-like data shape, or only dev?

**Verdict format:**

```
APPROVE / APPROVE WITH NOTES / REJECT

A1: ...
A2: ...
A3: ...
A4: ...
A5: ...
A6: ...
A7: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

---

## 3. Backend Reviewer Prompt

You are the Backend Engineer reviewing PR #33. Per-MVP backend reviews already passed. Your job is to verify the **end-state correctness** of the scoring service, API contracts, and data persistence.

**Read these in order (≈45 min):**

1. `AGENTS.md` → `## Data Layer` (is_current semantics, schema rules, write-conflict patterns).
2. `backend/app/services/oracles_lens/dashboard.py` — `_m3_facts_by_stock`, `_quality_overlay_by_stock`, `_fact_value`, `_stock_payload`, `_contributions_for_stock`, `_derive_manager_profile`.
3. `backend/app/services/oracles_lens/signal_weighted_score.py` — scoring computation.
4. `backend/app/api/v1/endpoints/stocks_13f.py` — `_m3_panel_for_stock`, `_normalize_score_confidence`, `read_stock_13f_detail`.
5. `backend/app/schemas/stocks_13f_snapshot.py` — `QualityOverlay`, `AvailableStockDetail`, `StockDetailTopHolder` (with `cik` from Track-E).
6. `backend/app/services/ingestion_service.py` — `_reconcile_parsed_fact_current_slot`.
7. `backend/alembic/versions/` — newest 5-10 migrations.
8. Spot-check `backend/tests/unit/test_oracles_lens.py` + `test_13f_mvp8_a2_m3_panel.py`.

**Seven backend questions:**

### B1 — Scoring service correctness post-Phase-3 flip

`use_persisted_scores=True` is the server default. The persisted path uses `OraclesLensSignal` rows; the legacy path computes on-the-fly. Phase 1 comparison report (recorded in MVP8-01 task file) showed `top10_swap_count=0` against 2025-Q3 / v1.0.

- Is the comparison report's 2025-Q3 evidence sufficient, or could the Phase 3 flip introduce regressions for other quarters / score_versions?
- The persisted scorer aggregates `Holding13F` rows per `(manager, stock)` to handle First Eagle's 117 co-attribution groups. Is the aggregation correctly applied in ALL scoring paths (`_eligible_stock_ids`, `_top_n_stock_ids_per_manager`, `_contributions_for_stock`, `_derive_manager_profile`)?

### B2 — `_fact_value` fallback correctness

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

- Is the fallback chain (`value_numeric` → `value_json['partial_score']`) safe across all consumers? The post-review hardening added try/except for TypeError/ValueError. Are there other types we should defensively handle (e.g., `value_json={'partial_score': True}` → `float(True) == 1.0` silently)?
- The test `test_oracles_lens_value_numeric_takes_precedence_over_partial_score` asserts the column wins when both are populated. Is this the right product semantics, or should `value_json` win when more recent than the column write?

### B3 — `QualityOverlay` Pydantic shape

`piotroski_status: Optional[str]` is open vocabulary because dev DB has `"partial"` (72 rows) and `"calculated"` (2 rows), and Literal would 500 on the unexpected value.

- Should the producer-side parsers be audited and the vocabulary tightened to a closed Literal? (The 2 `"calculated"` rows are likely a stale calculator artifact.) This is a long-term maintenance question.
- The 10-field response shape mirrors a hand-maintained TypeScript type in `frontend/lib/watchlist13f.ts`. Is schema drift detectable, or could backend field renames break the frontend silently?

### B4 — Migration sequence reversibility

Alembic head is `20260513140000`. The branch contains many migrations including:
- `cusip_ticker_map.ticker` VARCHAR(10) → VARCHAR(50) (MVP8-01)
- 13F schema foundation (MVP3 era)
- Quality reports persistence
- Ownership changes schema

Trace these (`git log backend/alembic/versions/ | head -40`):

- Are `downgrade()` operations defined and idempotent for the schema-altering migrations?
- Are there migrations that backfill data? If yes, can they be rolled back?
- Is there a migration test (e.g., apply head → downgrade → re-apply head) that would catch a broken `downgrade()` chain?

### B5 — `_normalize_score_confidence` shim placement

The persisted scorer writes `"high_confidence"` / `"medium_confidence"` / `"low_confidence"` (OWNERSHIP_SIGNAL_CONFIDENCE_LEVELS); the watchlist API surface uses `"high"` / `"medium"` / `"low"`. `_normalize_score_confidence` shim translates at the API boundary.

- Is the shim placement (API boundary) correct, or should the persisted scorer write the normalized form so all consumers see the same vocabulary? This would close the regression risk that a NEW endpoint reads from persisted dashboard items without the shim.
- Is there a regression test that exercises the post-Phase-3 default path and would catch a missing-shim 500?

### B6 — Test coverage meaningfulness

pytest reports 822 passed. The recent MVP8-A2 + Track-E + MVP7-06 work added ~30 tests.

- Are critical paths exercised? Specifically: scoring service `_contributions_for_stock` with multi-row holdings, `_reconcile_parsed_fact_current_slot` for manual corrections, `_m3_panel_for_stock` with mixed-source provenance.
- Spot-check 3-4 test files for "test quality" — are tests asserting actual behavior or just "didn't throw"?

### B7 — Write-conflict patterns post-MVP3

AGENTS.md locks the upsert-vs-IntegrityError contract:
- Upsert for idempotent recomputes (`oracles_lens_signals`)
- IntegrityError translator for mutual-exclusion locks (`JobRun.lock_key`)

- Verify: do all `INSERT ... ON CONFLICT` sites match the "idempotent recompute" semantics? Any case where upsert is used as a lock-steal anti-pattern?
- Verify: do all `JobRun.lock_key` writes correctly translate `IntegrityError` to typed errors (not silent latching)?

**Verdict format:**

```
APPROVE / APPROVE WITH NOTES / REJECT

B1: ...
B2: ...
B3: ...
B4: ...
B5: ...
B6: ...
B7: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

---

## 4. Frontend Reviewer Prompt

You are the Frontend Engineer reviewing PR #33. Per-MVP frontend reviews already passed. Your job is to verify the **Watchlist × 13F end-state surface** is coherent and meets accessibility + shadcn discipline standards.

**Read these in order (≈30 min):**

1. `AGENTS.md` → `## Frontend UI Standard` (shadcn + Tailwind + uiStandard.test.js enforcement).
2. `frontend/app/(dashboard)/watchlist/page.tsx` — find `SortableHeader`, sort state, the 13F columns wiring.
3. `frontend/components/watchlist/Watchlist13FDrawer.tsx` — drawer with M3 quality/valuation panel.
4. `frontend/components/watchlist/Watchlist13FColumns.tsx` — four 13F columns + responsive collapse.
5. `frontend/components/admin13f/Admin13FPrimitives.tsx` — DrawerShell (focus management + Escape listener).
6. `frontend/lib/watchlistSort.js` + `watchlistSort.test.js` — three-state sort cycle.
7. `frontend/lib/watchlist13f.ts` — type definitions mirroring backend Pydantic.
8. `frontend/lib/uiStandard.test.js` — the regex source-scanner.

**Six frontend questions:**

### F1 — Click-to-sort UX (MVP7-06)

Three-state toggle: default direction → flipped → cleared back to default sort. Six sortable columns (Ticker / Company / Conviction / Δ Holders / Distinctiveness / Caveats). Non-13F columns (Price / MOS / etc.) stay non-sortable.

- Is the three-state cycle discoverable? When a user clicks Conviction twice and then clicks it a third time, the table reverts to MOS-desc default — is this expected behavior or surprising?
- The default direction per column is "natural" (Conviction desc = best-first, Caveats desc = worst-first, Ticker asc = alphabetical). The Caveats default diverges from the Pre-MVP7-01 spec which said "severity asc." Is the divergence justified?
- Should non-13F columns ALSO be sortable (Price / MOS / Δ Today)? Scope was deliberately narrow but is this a UX hole?

### F2 — DrawerShell focus management (D3)

```tsx
const onCloseRef = useRef(onClose);
useEffect(() => { onCloseRef.current = onClose; }, [onClose]);
useEffect(() => {
  const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onCloseRef.current(); };
  document.addEventListener('keydown', handler);
  return () => document.removeEventListener('keydown', handler);
}, []);

const closeBtnRef = useRef<HTMLButtonElement>(null);
useEffect(() => {
  const previouslyFocused = document.activeElement as HTMLElement | null;
  closeBtnRef.current?.focus();
  return () => { previouslyFocused?.focus(); };
}, []);
```

- Edge case: drawer opened by clicking a row, then row is filtered out of the watchlist mid-drawer-open (e.g., user types in a sibling filter input). On close, `previouslyFocused?.focus()` is a no-op since the row is detached. Acceptable, or should we fall back to a known focus target?
- React StrictMode runs effects twice in dev. Trace what happens: first mount captures `previouslyFocused = row-button`, focuses close. First cleanup focuses `row-button`. Second mount captures `row-button` again. On real unmount: focuses `row-button`. Correct?
- Should DrawerShell ALSO implement focus trap (Tab cycles inside the drawer, not out to the page behind)? Currently focus can Tab out to the page.

### F3 — shadcn discipline (post-uiStandard.test.js)

The PR #33 CI initially failed because 4 files had raw HTML primitives accumulated across MVP5-04 → MVP7-06. Fix commit `817144a` swapped raw `<button>` / `<input>` / `<details>` for shadcn Button / Checkbox / custom `RuleCodeDisclosure` component.

- Spot-check the 4 fixed files. Are the shadcn replacements visually equivalent to the raw versions, or did the swap introduce subtle UX regressions (e.g., default button padding affecting Badge alignment)?
- Are there OTHER files (not flagged by the test) that use shadcn components but with class overrides that defeat the design system (e.g., `Button` with `bg-transparent hover:bg-transparent` to look like a raw button)?

### F4 — TypeScript type drift risk

`Watchlist13FAvailableDetail.quality_overlay` is a hand-maintained TypeScript mirror of the backend Pydantic `QualityOverlay` model. Same for `Watchlist13FTopHolder` (12 fields) and `Watchlist13FCaveatFlag`.

- Is there ANY automated check that frontend types match backend Pydantic shapes? If a backend field is renamed without updating the frontend type, what catches it?
- For the post-MVP8-A2 sweep, `quality_overlay` gained `vl_target_period_end` and `vl_target_source_document_id` fields. Is the source-of-truth direction (backend Pydantic → frontend manual type) documented anywhere?

### F5 — Mobile responsiveness (current state)

Per MVP7-04, the 13F columns use a responsive cutoff: `xl inline / md toggle + localStorage / sm hidden`. Below `sm` (e.g., 375px width), the four 13F columns disappear entirely.

- Is "sm hidden" acceptable for V1, or is it an unacceptable mobile UX gap that should block merge? (Open-work snapshot lists Mobile stacked 13F view as the NEXT ticket.)
- The drawer DOES work on mobile (full-screen overlay) — but users have to know to click a row. Is the discoverability gap a real product risk?

### F6 — a11y compliance summary

- `aria-sort` on sortable headers, `aria-label` on close buttons, `role="dialog"` + `aria-modal` on drawer, `aria-required` on Note Textarea, `aria-invalid` on evidence URL input.
- Run through the Watchlist × 13F surface as a keyboard-only user. Identify any path where keyboard navigation gets stuck or skips an interactive element.
- Run through the surface with a screen reader (NVDA / VoiceOver). Identify any element that's announced incorrectly or not at all.

**Verdict format:**

```
APPROVE / APPROVE WITH NOTES / REJECT

F1: ...
F2: ...
F3: ...
F4: ...
F5: ...
F6: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

---

## 5. Documentation / Workflow Reviewer Prompt

You are reviewing PR #33 from the perspective of "is the project's documentation + workflow coherent and maintainable?" Per-MVP reviews don't check this; it accumulates as drift.

**Read these in order (≈30 min):**

1. `AGENTS.md` — entire file (228 lines). This is the canonical workbook post-consolidation.
2. `CLAUDE.md` — 16 lines, `@AGENTS.md` import + Claude-Code-specific conventions only.
3. `docs/tasks/2026-05-14_open-work-snapshot.md` — what's done / deferred / gated.
4. `docs/tasks/` listing — `ls docs/tasks/ | sort` and look at the May 2026 entries.
5. Spot-check 4-5 task files: one closed (e.g., MVP8-A2), one design gate (e.g., metric-facts-current-semantics), one deferred (e.g., MVP8-02), one review prompts file (e.g., 2026-05-13_mvp8-a2-track-e-review-prompts.md), one snapshot doc (open-work-snapshot).
6. Memory: `.claude/projects/-Users-dane-projects-ValuePilot/memory/MEMORY.md` index + spot-check 2-3 entries.

**Six documentation questions:**

### D1 — AGENTS.md completeness

Project-level rules now live in AGENTS.md. The consolidation moved 5 contracts from CLAUDE.md, added 1 (Verification Discipline), removed ~190 lines of aspirational process content.

- Are there project-level rules NOT captured in AGENTS.md that should be? Scan `docs/`, top-level `README.md`, code comments with "rule:" / "MUST" / "NEVER" / "always" for contracts that should be hoisted.
- Are there rules in AGENTS.md that are stale or contradicted by current code? Pick 3 random rules and verify against the codebase.

### D2 — CLAUDE.md minimalism

CLAUDE.md is 16 lines: `@AGENTS.md` import + Claude-Code-only conventions (memory directory + "memory is not canonical" rule).

- Is the `@AGENTS.md` import documented anywhere as a Claude Code feature, or is this an undocumented convention? If a future agent doesn't honor `@import`, what's the fallback?
- Should CLAUDE.md have an explicit one-line statement that "any rule here that other agents need ALSO goes in AGENTS.md"? (Currently the file says this but the wording could be tighter.)

### D3 — Task file coherence

`docs/tasks/` contains 130+ files spanning MVP1 → MVP8. Sign-off trails follow a pattern: `- [x] D1 shipped ... - [x] **MVP closed**`.

- Pick 5 random closed-ticket files. Are their sign-off trails actually consistent, or has the pattern drifted across MVPs?
- Are there closed tickets whose closure should be REOPENED because a subsequent decision (e.g., the locked `is_current` semantics) changed the contract they were closed against?

### D4 — Decision gate distinction

Three kinds of files in `docs/tasks/`:
- Implementation tickets (e.g., `2026-05-13_mvp8-a2-watchlist-m3-overlay.md`)
- Decision gates (e.g., `2026-05-13_metric-facts-current-semantics-decision-gate.md`)
- Review prompts (e.g., `2026-05-13_mvp8-a2-track-e-review-prompts.md`)
- Snapshots (e.g., `2026-05-14_open-work-snapshot.md`)

- Is the distinction between these file types clear from the filename alone? Or do new readers have to open each to figure out the type?
- Are OPEN decision gates clearly distinguished from CLOSED ones at a glance? The status section convention is `**Status: Open, awaiting PO direction**` or `**Status: CLOSED YYYY-MM-DD — Option X selected**`. Spot-check 3-4 gates to confirm.

### D5 — Memory vs AGENTS.md split correctness

Memory is Claude-Code-only; AGENTS.md is the cross-agent canonical workbook. The new `feedback_local_green_vs_ci_green.md` declares "canonical version is in AGENTS.md → Verification Discipline" in its opening lines.

- Are ALL existing memory entries either (a) genuinely Claude-Code-specific (e.g., session conventions, slash command behavior) OR (b) labeled as a reinforcement of an AGENTS.md rule? Spot-check the 7 entries in MEMORY.md index.
- Is there an entry that should be promoted from memory-only to AGENTS.md because it's actually a cross-agent rule?

### D6 — Open-work snapshot accuracy

`2026-05-14_open-work-snapshot.md` was filed at the checkpoint after today's three closures. It has four sections: Locked Decisions / Actionable Now / Gated on Observation Window / Explicitly Deferred / Track-E backlog.

- Cross-check with `docs/tasks/` listing: are there OPEN tickets the snapshot doesn't mention? Or items the snapshot lists as "next" that are actually blocked?
- The snapshot says "Mobile stacked 13F view" is the next ticket. Is this consistent with the MVP8 PO ranking and with the user's stated direction ("先把核心信号在 Watchlist 里稳定准确地展示出来；再扩大 VL 覆盖率；最后才做更炫的可视化")?

**Verdict format:**

```
APPROVE / APPROVE WITH NOTES / REJECT

D1: ...
D2: ...
D3: ...
D4: ...
D5: ...
D6: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

---

## 6. Production Readiness Reviewer Prompt

You are reviewing PR #33 from a production-deployment perspective. The PR has ~170 commits spanning weeks of work. Per-MVP reviews verified correctness; your job is to answer "**is this safe to merge to main and ship to users TODAY?**"

**Read these in order (≈30 min):**

1. `docs/tasks/2026-05-14_open-work-snapshot.md` — what's done / deferred / gated.
2. `docs/tasks/2026-05-13_mvp8-01-mvp5-03-phase3-flip.md` — Phase 3 server-default flip; the observation window is in progress.
3. `docs/tasks/2026-05-13_mvp8-02-base-divergence-investigation.md` — observation-window-gated.
4. `AGENTS.md` → `## Verification Discipline (closing gates)`.
5. `AGENTS.md` → `## Minimal per-PR checklist`.
6. Git diff summary: `git log --oneline main..HEAD | wc -l` (expect ~170) and `git diff main..HEAD --stat | tail -1`.

**Six production-readiness questions:**

### P1 — What's safe to ship TODAY vs gated

The branch contains both fully-shipped work (MVP3 ingestion, MVP4 scoring, MVP6 admin, MVP7 Watchlist surface, MVP8-A2 drawer, Track-E sweep) AND observation-window-gated work (Phase 3 server-default flip is shipped but Phase 4 retirement is gated, MVP8-02 base divergence is queued).

- Is the Phase 3 server-default flip safe to ship to production NOW, or should there be a separate "flip" deploy step that can be rolled back independently from the rest of the PR? (The flip happens at code merge; there's no feature flag.)
- The `?persisted=0` escape hatch lets users force the legacy formula. Is this documented anywhere users (admins / operators) can find it, or is it an undocumented escape that requires reading commit history?

### P2 — Coverage limitations + missing-data honesty

Dev DB has 7 stocks with VL data; 5 overlap with 13F holdings. The drawer M3 panel displays full quality/valuation overlay for those 5 and "Value Line data is not available for this stock in the current dataset." for the rest.

- What's the PRODUCTION VL data coverage? Is it materially different from dev? (Open-work snapshot lists Value Line ingestion coverage track as a follow-on after Mobile stacked view.)
- If production coverage is similarly thin (≤10 stocks with VL data), should the M3 panel be feature-flagged off entirely until coverage improves, to avoid users assuming the M3 panel is the norm rather than the exception?
- The Watchlist drawer shows the 13F columns for ALL stocks, but M3 panel for almost none. Is this asymmetry confusing in production?

### P3 — Rollback plan for Phase 3 regression

If Phase 3 (`use_persisted_scores=True` default) causes a production regression (e.g., a stock that ranked top-10 under legacy now ranks 12th under persisted), what's the recovery path?

- Verify the Phase 1 comparison report (in MVP8-01 task file): `top10_swap_count=0` against 2025-Q3 / v1.0. Is one quarter's evidence enough for "safe to flip"?
- The `?persisted=0` escape hatch is per-query. Is there a way to flip the default BACK without redeploying (e.g., a config flag), or does rollback require a code change?

### P4 — Migration safety for production data

Alembic head is `20260513140000`. The branch contains migrations spanning MVP3 → MVP8.

- Has the migration sequence been applied against a prod-like data dump? If only dev, what's the production data shape risk?
- Migrations that backfill or transform data: are they idempotent on re-run? If the deploy fails partway, can it be safely retried?

### P5 — Observation-window gate clarity

MVP8-01 Phase 4 (legacy formula retirement) and MVP8-02 (base divergence) are gated on "one full scoring cycle observation window (post-2025-Q4 cycle) showing zero TOP10_RANK_SWAP."

- Is this gate condition documented in a way that ops/PO can verify? Where would an ops person look to know "the observation window has closed and we can ship Phase 4"?
- Is there a runbook for "what to do if the observation window surfaces a regression"? (Specifically: who decides to revert vs investigate, what does "revert" mean given the default flip is in code?)

### P6 — PR mergeability vs follow-on work

The open-work snapshot lists three categories of follow-on:
- N1 Mobile stacked 13F view (next ticket)
- N2 Value Line ingestion coverage track
- Observation-window-gated items (MVP8-01 Phase 4, MVP8-02)

- Is PR #33 mergeable to main NOW with these follow-ons tracked separately, or is there a follow-on that's actually a prerequisite for PR #33 to be safe in production?
- After merging PR #33, what's the operator-visible CHANGE? (E.g., does `/watchlist` look different in production? Does `/13f/oracles-lens` rank stocks differently?) Has anyone written a release note for users?

**Verdict format:**

```
APPROVE / APPROVE WITH NOTES / REJECT (do NOT merge yet)

P1: ...
P2: ...
P3: ...
P4: ...
P5: ...
P6: ...

Should-block items (REJECT only) — must resolve before merge: ...
Future backlog (not blocking): ...
```

Be honest. This is the last review before merge; if you have a real concern that merging would be premature, REJECT and say why.
