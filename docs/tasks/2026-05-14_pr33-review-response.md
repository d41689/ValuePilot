# PR #33 Review Response — Action Disposition

**Date**: 2026-05-14
**Source reviews**:
- `2026-05-14_pr33-comprehensive-review-report.md` (executive)
- `2026-05-14_pr33-review-01-13f-sme.md`
- `2026-05-14_pr33-review-02-staff-engineer.md`
- `2026-05-14_pr33-review-03-backend.md`
- `2026-05-14_pr33-review-04-frontend.md`
- `2026-05-14_pr33-review-05-documentation.md`
- `2026-05-14_pr33-review-06-production-readiness.md`

**Verdict across all 6 reviewers + executive**: APPROVE WITH NOTES. No merge blockers. Deploy gated (separate ticket).

**This document** is the disposition of every finding: APPLIED (fixed in PR #33 response commit) / FILED-AS-TICKET (in a follow-up) / DEFERRED-WITH-RATIONALE (recorded but not actioned).

---

## APPLIED (fixed in PR #33 response commit)

| # | Finding | Source | Change |
|---|---|---|---|
| 1 | `_valuation_reference_by_stock` missing `period_end_date` tiebreak — could surface stale opinion targets | Staff A1 #1, Exec P1 | Added `MetricFact.period_end_date.desc().nullslast()` to the `order_by` in `dashboard.py`. Comment cross-references the follow-up ticket for full unification. |
| 2 | `_m3_panel_for_stock` direct `int()` casts on Piotroski `value_json` could 500 on malformed data | Exec P2, Backend B2 #1 | Extracted `_coerce_int()` helper with try/except + explicit bool rejection. Applied to `partial_score` + `max_available_score`. `status` defensively coerced to `str` only. |
| 3 | `_fact_value` bool footgun: `float(True) == 1.0` silently coerces | Backend B2 #1 | Added `isinstance(raw, bool)` rejection before `float()` call in `dashboard.py:_fact_value`. |
| 4 | `build_oracles_lens_dashboard` service default still legacy (`use_persisted_scores=False`) while API endpoints default to `True` | Staff A1 #2, Exec P2 | Documented the divergence as intentional in the docstring. The service default stays legacy because `formula_comparison.py` calls it explicitly with `False` and legacy-path tests pass without extra kwargs. Phase 4 retirement will delete the parameter. Not flipping the service default — flagged as intentional. |
| 5 | Manager type dual-chip tooltip wording: "Behavior-derived (overrides admin classification)" + "Admin-classified ... curated record" reads as contradictory; doesn't tell the user which is canonical | 13F SME Q5 | Reworded tooltips. Derived: "Manager profile derived from holding behavior. This is the canonical value used for scoring." Admin: "Admin-curated classification (currently overridden by the behavior-derived profile)." |
| 6 | `watchlist13f.ts` has no source-of-truth direction comment — TS types hand-mirror Pydantic schemas with no drift check | Frontend F4 | Added a top-of-file comment documenting: "Pydantic is canonical; when a backend field is added/renamed/removed, update this file in the same commit. OpenAPI codegen is a Track-E follow-up triggered by the third schema-drift incident." |
| 7 | CLAUDE.md "Adding Claude-specific rules" paragraph too passive about the cross-agent direction | Documentation D2 | Rewrote with active voice + bolded canonical-direction statement: "Everything else — coding rules, data contracts, workflow rules — goes in AGENTS.md so all agents see the same contract." |
| 8 | `open-work-snapshot.md` line 27 still references CLAUDE.md as canonical for `is_current` semantics | Documentation D5, Exec P2 | Updated to "AGENTS.md — canonical for all agents." |
| 9 | `metric-facts-current-semantics-decision-gate.md` references "CLAUDE.md updated" in 3 places after the workbook consolidation moved the contract to AGENTS.md | Documentation D5, Exec P2 | Updated all 3 references to point to AGENTS.md with the explicit note that CLAUDE.md is now a thin pointer importing AGENTS.md via `@AGENTS.md`. |

**Verification after applying**:
- `docker compose exec api pytest -q` → 823 passed in 67.27s
- `docker compose exec web sh -lc 'node --test lib/*.test.js'` → 143 passed
- `docker compose exec web npm run lint` → clean
- `docker compose exec web npm run build` → clean

---

## FILED AS FOLLOW-UP TICKETS

### N3 — Option A Read-Path Audit
**File**: `2026-05-14_option-a-read-path-audit-ticket.md`

Covers:
- Staff A1 #2: vocabulary guard on screener / formula
- 13F SME Q1 #1: mechanical regression test for opinion-metric staleness (replaces the AGENTS.md tribal contract with a fixture-driven assertion)
- Staff A1 #1 follow-on: full unification of `_valuation_reference_by_stock` with `_m3_facts_by_stock` (only the immediate tiebreak inconsistency was fixed in this PR)
- Backend B1: enforces the locked Option A contract before any opinion-metric screener / alerting consumer arrives

### N4 — PR #33 Pre-Deploy Gates
**File**: `2026-05-14_pr33-pre-deploy-gates-ticket.md`

Covers:
- Production P1, P3, P4: migration round-trip test against prod-like data
- Production P1, P2: Phase 1 comparison against production data
- Production P3, P5: operator runbook for Phase 3 rollback + observation-window monitoring
- Production P6: release note for users + API consumers
- Production P2, 13F SME Q2: production VL coverage audit (informs release note)
- Staff A7: migration round-trip test (deferred to deploy gate, not merge gate)

### N5 — AGENTS.md Consolidation v2
**File**: `2026-05-14_agents-md-consolidation-v2-ticket.md`

Covers:
- Documentation D5: promote 5 cross-agent memory rules to AGENTS.md (`tool_validation_vs_product_signoff`, `phased_tickets_need_explicit_trackers`, `no_stub_routes_for_ctas`, `strict_mvp_scope_discipline`, `financial_data_unknown_vs_zero`)
- Documentation D1 #1-5: add 5 missing project rules to AGENTS.md (First Eagle audit, options exclusion, FK deletion order, `_normalize_score_confidence` shim, `value_thousands_override` precedent)
- Documentation D3: tighten existing AGENTS.md wording on `value_numeric` / `value_json` reads + shadcn override edge cases
- Documentation D4: filename suffix convention for new task files
- Staff A4: audit which memory entries to delete vs keep as reinforcements

---

## DEFERRED WITH RATIONALE (recorded; not actioned in this commit or follow-up tickets)

| Finding | Source | Rationale for deferring |
|---|---|---|
| Track-E DrawerShell move + focus trap | Frontend F2 #3, Exec P3 | Bundle with the Mobile stacked 13F view ticket (N1). Per the Track-E backlog trigger "Next drawer-touching feature." |
| Dividend yield / payout ratio in M3 panel | 13F SME Q2 #2 | V1.1 product expansion. Filed as future-backlog in the snapshot. |
| `discount_to_reference` field in drawer | 13F SME Q2 #2, Q6 #1 | Cross-surface consistency improvement. V1.1; coverage is the higher-priority bottleneck. |
| Score confidence chip on watchlist row | 13F SME Q3 #3 | Buried in drawer today; V1.1 polish. |
| Three-state click-to-sort discoverability tooltip | Frontend F1 | V1.1 polish; pattern is common (GitHub / Linear) so users will figure it out. |
| Tooltip primitive migration (replace `title` attributes) | Frontend F6 | V1.1 a11y polish. MVP7-03 SR5 explicitly punted on this. |
| Dual manager-type chip a11y (single-chip with tooltip alternative) | 13F SME Q5 | Wording fix was applied; the structural alternative is V1.1 polish. |
| `_fact_value` numpy/pandas type defensiveness | Backend B2 #2 | Non-issue today (no pandas writes to value_json). Future-proof if it becomes real. |
| `piotroski_status` vocabulary audit + Literal tightening | Backend B3, 13F SME Q2 #3 | Find the 2 `"calculated"` rows in dev, decide intent, tighten Pydantic Literal. Not blocking. |
| Filer-level reporting override mechanism (`manager_reporting_overrides` table) replacing Kahn Brothers hardcode | 13F SME Q4 | V1.1+ refactor when a 2nd non-standard filer surfaces. |
| Shared `_normalize_score_confidence` helper module | Backend B5 | Promote when 2nd consumer arrives. Today's single-callsite shim is sufficient. |
| Three-state sort on Price / MOS / Δ Today columns | Frontend F1 | Scope was deliberately narrow in MVP7-06 ("only 13F columns"). Half-day's work; file as follow-up. |
| Periodic audit of "shadcn with overrides that defeat the design system" | Frontend F3 | Quarterly maintenance; no immediate action. |
| Per-MVP push cadence going forward | Staff A6 | Process change; first test is the Mobile stacked 13F view ticket. |
| Migration round-trip CI check (when `backend/alembic/versions/` is touched) | Staff A7 | CI infrastructure work; defer until N1 / N5 land. |
| Feature flag (env var) for Phase 3 default | Production P3 | Recommended for instant rollback without redeploy. Defer to a separate enhancement ticket; current per-request escape + code revert is sufficient at this scale. |
| Memory entry `feedback_local_green_vs_ci_green.md` deletion (Staff argued it's redundant with AGENTS.md auto-import) | Staff A4 | Documentation D5 disagreed (memory still serves as Claude-Code reinforcement). Deferring the call to N5 (consolidation v2). |
| Coverage-limitations extended copy on the empty M3 drawer panel | 13F SME Q2 #1 | Suggested 2-line copy: "Quality & valuation overlay coverage is currently limited to a curated set of large- and mid-cap U.S. equities." Defer — wording is fine for V1; revisit when N2 VL coverage track decides the actual scope. |
| Test refactor for legacy `?use_persisted_scores=false` paths | Backend B6 | Documented as Phase 4 scope. Pre-Phase-4 test refactor will rewrite ~20+ legacy-path test cases at the same time as the legacy formula deletion. |
| `_HolderContribution` data-loading abstraction | Track-E | Trigger: 4th scoring algorithm needing >2 new fields on the dataclass. |
| Score-input sanity guards (generic weight clamps) | Track-E | Trigger: observed corruption case (NOT theoretical). |

---

## Net

Reviewers found no merge blockers. The PR was net-strengthened by the review — 9 small fixes shipped in the response commit, 3 follow-up tickets opened, 22 items explicitly deferred with rationale. The most important deferred concern (production deploy readiness) is captured in the N4 ticket and gates production traffic, not merge.
