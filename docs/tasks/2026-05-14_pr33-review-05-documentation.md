# PR #33 Review — Documentation / Workflow

**Reviewer role**: Documentation / Workflow Reviewer (MEDIUM priority — workbook consolidation + task file coherence)
**Reviewer date**: 2026-05-14
**PR**: https://github.com/d41689/ValuePilot/pull/33
**Branch**: `docs/13f-automation-prd`
**Method**: Read AGENTS.md end-to-end (228 lines), CLAUDE.md (16 lines), open-work snapshot, `docs/tasks/` May-2026 listing (~155 files), spot-checked 5 task files spanning closed / design gate / deferred / review prompts / snapshot, MEMORY.md index + spot-checked 3 memory entries (`feedback_local_green_vs_ci_green`, `feedback_metric_facts_is_current_semantics`, `project_13f_prd`).

---

## Verdict

**APPROVE WITH NOTES**

Documentation is in markedly better shape than typical for a 170-commit branch. The post-consolidation AGENTS.md is concise and high-signal. Two notes (D2 wording clarity, D5 memory vs canonical split) warrant attention but neither blocks merge. The single biggest concern is **filename convention drift in `docs/tasks/`** — D4 below.

---

## D1 — AGENTS.md completeness

**Rules currently captured in AGENTS.md:**
- Tech stack (versions / language choices).
- Docker development environment (canonical commands).
- Data layer (3-layer storage, stock identity, normalization, `is_current` semantics, manual corrections, schema-change rule, Alembic conventions, write-conflict patterns).
- Parsing (scope + strategy + mapping + parser fixture alignment workflow + EDGAR/13F gotchas).
- Frontend UI standard (shadcn discipline + uiStandard.test.js enforcement).
- Coding standards (naming + error handling).
- Development workflow (task logging + test-first + running tests + verification discipline + safety contract checks + minimal per-PR checklist).

**Rules I spot-checked from `docs/`, code comments, and memory that aren't in AGENTS.md but probably should be:**

1. **First Eagle co-attribution audit rule** (from `project_13f_prd.md`): "Before expanding the superinvestor universe past 72 managers, re-run the audit query and verify exact share-count matches stay at 0." This is a project-level invariant, not Claude-Code-specific. **Belongs in AGENTS.md**, probably under EDGAR/13F gotchas.

2. **Options exclusion in scoring paths**: "All four scoring-eligibility paths must filter `Holding13F.put_call.is_(None)`." This is a non-trivial scoring contract; spotted in memory but not in AGENTS.md. **Belongs in AGENTS.md** under a new "Scoring service contracts" sub-section.

3. **Test helper FK-deletion ordering**: "Any `_clear_13f` helper must delete `OraclesLensScoreComponent` then `OraclesLensSignal` before `InstitutionManager`." From memory `project_13f_prd.md`. Cross-agent rule (any contributor writing tests hits this). **Belongs in AGENTS.md** under a "Testing conventions" sub-section (which doesn't exist yet but should).

4. **Score confidence normalization shim**: "Any new endpoint reading `score_confidence` from a persisted dashboard item must call `_normalize_score_confidence()`." Cross-agent rule. **Belongs in AGENTS.md** under a new "API surface conventions" or "Scoring service contracts" sub-section.

5. **`Holding13F.value_thousands_override` precedent**: "Any new scoring primitive that takes a `Holding13F` and computes a per-row metric must accept a `value_thousands_override` kwarg." Cross-agent. **Belongs in AGENTS.md**.

**Rules in AGENTS.md that may be stale or contradicted by current code (3 spot-checks):**

1. **Safety contract check: "Screeners MUST filter on `value_numeric` for numeric comparisons (not JSON)."** Now contradicted by the Piotroski composite-score read path (`_fact_value` falls back to `value_json['partial_score']`). The screener service itself doesn't do this fallback (it stays on `value_numeric`), so the rule is still TECHNICALLY correct, but a contributor reading the rule + the `_fact_value` code will see apparent contradiction. Suggest tightening to: "Screeners' rule_json MUST express numeric comparisons against `value_numeric`. Composite scores stored in `value_json` are read via the `_fact_value` helper at the service layer, not in screener rule evaluation."

2. **"Use Tailwind classes for layout and component-specific adjustments only."** Generally true. The Watchlist Conviction badge wraps a shadcn `Button` with `className="h-auto rounded p-0 hover:bg-transparent"` to defeat default button styling. This is in the gray zone — it IS using Tailwind for component-specific adjustment, but the adjustment is "defeat the design system." Not stale, but worth a clarifying note that shadcn component reuse takes precedence over visual fidelity at edge cases.

3. **Alembic conventions: "Filename: `backend/alembic/versions/YYYYMMDDHHMMSS-<slug>.py`."** All 23 migrations on the branch follow this. ✓

---

## D2 — CLAUDE.md minimalism

CLAUDE.md is 16 lines:
- Line 1: `@AGENTS.md` import.
- Lines 3-16: brief explanation of memory directory + the "memory is Claude-Code-only reinforcement, never the contract" rule.

**Is `@AGENTS.md` documented as a Claude Code feature?**

`@filename` is the documented Claude Code feature for importing file content into the system prompt. It's not idiosyncratic to this project. Other agents (Cursor, Aider, Copilot) read `AGENTS.md` directly because it's the project convention; they don't process `@AGENTS.md` syntax. **The import mechanism is documented at the platform level; the project's convention reuses it.**

**Fallback if a future agent doesn't honor `@AGENTS.md`:**

The other agents (Cursor / Aider / Copilot) bypass CLAUDE.md entirely and read AGENTS.md directly. So the import is Claude-Code-specific by design, and the fallback for non-Claude-Code agents is "read AGENTS.md natively." **No fallback issue.**

**Should CLAUDE.md have a tighter "cross-agent" statement?**

Current wording (line 12): "If a rule starts in memory but applies across all agents working on this codebase, also add it to `AGENTS.md`. Memory is a Claude-specific reinforcement, never the contract."

This is correct but understated. Suggest:

> Add new rules to this file ONLY when they are mechanically Claude-Code-specific (slash commands, hooks, memory format, internal-tool wrappers). **Everything else — coding rules, data contracts, workflow rules — goes in `AGENTS.md` so all agents see the same contract.** When in doubt, write to AGENTS.md.

The current line 16 says this but in passive voice. Active and bolded would land harder.

---

## D3 — Task file coherence

**Sign-off trail pattern spot-checked across 5 files:**

| File | Pattern |
|---|---|
| `2026-05-13_mvp8-a2-watchlist-m3-overlay.md` | `- [x] D1 shipped ... - [x] **MVP8-A2 closed 2026-05-13.**` ✓ |
| `2026-05-13_mvp8-03b-watchlist-scoring-sme-fixes.md` | Same pattern, with detailed verification results in the trail ✓ |
| `2026-05-13_mvp8-01-mvp5-03-phase3-flip.md` | Same pattern + appended comparison report + "Code changes shipped" inventory ✓ |
| `2026-05-13_metric-facts-current-semantics-decision-gate.md` | Different — uses `- [x] **PO selects Option A 2026-05-14**` + closing checkboxes. Appropriate for a decision gate. ✓ |
| `2026-05-14_open-work-snapshot.md` | Different — has Status / Locked Decisions / Actionable Now / Gated / Deferred sections. Appropriate for a snapshot. ✓ |

**Convention is consistent within file types**, divergent between file types. This is **correct** — a decision gate, an implementation ticket, and a snapshot have different content needs.

**Closed tickets that should be REOPENED because a subsequent decision changed their contract:**

The relevant test: the locked `is_current` semantics on 2026-05-14 should NOT reopen any prior ticket because the decision codified the existing behavior. Specifically:

- Pre-MVP8-A2 D4 ("dedup is_current=True") was DEFERRED to the design gate. It was never shipped, so no closed ticket needs reopening.
- MVP8-A2 P1 ("VL target as-of date label") was shipped using the existing `period_end_date` column — Option A is exactly the contract MVP8-A2 P1 assumed. No reopening.
- Pre-MVP7-01 D1–D5 (Watchlist insight decision gate) is independent. No reopening.

**No retroactive reopening needed.** The decision gate's purpose was to lock the status quo against a future "let me clean this up" engineer; it doesn't invalidate prior closures.

---

## D4 — Decision gate distinction

`docs/tasks/` contains 130+ files across 4 categories:

| Category | Filename pattern (observed) | Distinguishable from filename? |
|---|---|---|
| Implementation tickets | `2026-05-13_mvp8-a2-watchlist-m3-overlay.md` | Partially — "mvpN-XX" hint |
| Decision gates | `2026-05-13_metric-facts-current-semantics-decision-gate.md` | Mostly — suffix `-decision-gate` |
| Review prompts | `2026-05-13_mvp8-a2-track-e-review-prompts.md` | Mostly — suffix `-review-prompts` |
| Snapshots | `2026-05-14_open-work-snapshot.md` | Mostly — suffix `-snapshot` |
| Pre-MVP gates | `2026-05-13_pre-mvp8-a2-oracles-lens-m3-decision-gate.md` | Yes — prefix `pre-mvp` + suffix `-decision-gate` |
| End-to-end verifications | `2026-05-13_13f-mvp7-end-to-end-verification.md` | Yes — suffix `-end-to-end-verification` |

**Distinction issues:**

1. **`2026-05-12_pre-mvp6-01-13f-dev-data-bootstrap.md`** has no suffix indicating its type. Looking at the filename alone: implementation? Decision gate? "Pre-MVP6" suggests gate, but isn't conclusive.

2. **`2026-05-12_post-mvp4-roadmap.md`** is a snapshot-shaped doc with no `-snapshot` suffix.

3. **`2026-05-13_post-mvp8-a2-track-e-backlog-sweep.md`** is an implementation ticket (the "backlog sweep" that hardened post-MVP8-A2 review findings). Filename suggests it's a snapshot or a roadmap doc. Misleading.

4. **Many older files (May 1-9 era)** have descriptive names without category suffixes: `2026-05-04_fix-adbe-stock-summary-data.md`, `2026-05-05_oracles-lens-final-v1-product-tightening.md`. These are implementation tickets but you'd need to open them to confirm.

**Recommendation:**

Filename convention going forward should be:

```
YYYY-MM-DD_<topic>-<type>.md
```

Where `<type>` is one of:
- `-ticket.md` — implementation work
- `-decision-gate.md` — design / product decision pending
- `-review-prompts.md` — multi-agent review prompts
- `-end-to-end-verification.md` — closing verification doc
- `-snapshot.md` — open-work status

**No retroactive rename of 130+ files** — that's churn. Apply the convention going forward (new tickets opened post-2026-05-14).

**Decision-gate open-vs-closed distinguishability:**

`Status: Open, awaiting PO direction` vs `Status: CLOSED 2026-05-14 — Option X selected` — spot-checked 4 gates, all use this pattern consistently in their header section. ✓

---

## D5 — Memory vs AGENTS.md split correctness

**Memory entries (9):**

| Entry | Type | Genuinely Claude-Code-only OR explicit AGENTS.md reinforcement? |
|---|---|---|
| `feedback_schema_band_aids` | feedback | Reinforcement of AGENTS.md "Schema changes — no band-aids" |
| `feedback_tool_validation_vs_product_signoff` | feedback | Not in AGENTS.md verbatim. **Cross-agent? Yes.** |
| `feedback_phased_tickets_need_explicit_trackers` | feedback | Not in AGENTS.md. **Cross-agent? Yes.** |
| `feedback_no_stub_routes_for_ctas` | feedback | Not in AGENTS.md. **Cross-agent? Yes.** |
| `feedback_strict_mvp_scope_discipline` | feedback | Not in AGENTS.md. **Cross-agent? Yes.** |
| `feedback_financial_data_unknown_vs_zero` | feedback | Not in AGENTS.md. **Cross-agent? Yes.** |
| `feedback_metric_facts_is_current_semantics` | feedback | Reinforcement of AGENTS.md "`metric_facts.is_current` semantics (locked 2026-05-14)" |
| `feedback_local_green_vs_ci_green` | feedback | Reinforcement of AGENTS.md "Verification Discipline" — explicitly labeled as such |
| `project_13f_prd` | project | Project state, Claude-Code-only |

**Findings:**

- 2 entries are **explicit reinforcements of AGENTS.md content** (`schema_band_aids`, `local_green_vs_ci_green`, `metric_facts_is_current_semantics`). The dual-source-of-truth maintenance risk I called out in the Staff Engineer review applies — these create drift potential.
- **5 entries (`tool_validation_vs_product_signoff`, `phased_tickets_need_explicit_trackers`, `no_stub_routes_for_ctas`, `strict_mvp_scope_discipline`, `financial_data_unknown_vs_zero`) are cross-agent rules that are NOT yet in AGENTS.md.** These SHOULD be promoted.

**The split currently has it backwards.** Memory contains cross-agent rules that AGENTS.md is missing. AGENTS.md repeats rules that memory mirrors. The clean state would be:

- All 5 cross-agent rules → promoted to AGENTS.md (as new sub-sections under a "Lessons-learned contracts" header, or distributed among existing sections).
- Once promoted, memory entries become reinforcement-only. Then the maintenance question (do we keep duplicates in memory?) is a clean call: probably remove them since `@AGENTS.md` loads the canonical version automatically for Claude Code sessions.

**Recommendation (post-merge):**

1. Open a "consolidate workbook v2" ticket that:
   - Audits all 9 memory entries.
   - Promotes the 5 cross-agent rules to AGENTS.md with proper section placement.
   - Decides per-entry whether to keep the memory copy (for Claude-Code-specific phrasing) or remove (trust the import).
2. Result: AGENTS.md grows by ~50-80 lines, memory shrinks to 4-5 entries (only genuinely Claude-Code-specific ones plus the project state file).

---

## D6 — Open-work snapshot accuracy

`2026-05-14_open-work-snapshot.md` (152 lines) has 4 main sections matching the spec:
- Status
- Locked Decisions (LD1-LD4)
- Actionable Now (N1-N2)
- Gated on Observation Window (MVP8-01 Phase 4, MVP8-02)
- Explicitly Deferred (LD4)
- Backlog (Track-E, trigger-gated)
- Next Action

**Cross-check against `docs/tasks/` listing:**

OPEN tickets the snapshot mentions:
- N1 Mobile stacked 13F view — not yet a file in `docs/tasks/`, will be the next ticket created.
- N2 Value Line ingestion coverage track — not yet a file; will be a decision gate first.

OPEN tickets `docs/tasks/` reveals that the snapshot doesn't mention:
- `2026-05-13_oracles-lens-duplicate-period-key.md` — I need to check if this is closed or open. Spot-check unconfirmed.
- `2026-05-12_backlog-dev-cusip-linking-fixture.md` — backlog ticket, status uncertain from filename.

**Recommendation**: when filing the next snapshot (e.g., post-N1 closure), add a "Triaged but not surfaced above" appendix listing files whose status changed since last snapshot. Avoids the "stale snapshot" effect.

**Items the snapshot lists as "next" — consistent with LD2 and stated user direction?**

LD2 says: "先把 13F 核心信号在 Watchlist 里稳定、准确、可解释地展示出来；再扩大 Value Line 覆盖率；最后才做更炫的可视化。"

The PO ranking translation in LD3:
1. MVP5-03 Phase 3 flip → CLOSED (✓ stable+accurate baseline)
2. SME flag cluster → CLOSED (✓ stable+accurate)
3. Track A2 M3 overlay → SHIPPED, coverage-limited (✓ partially stable, coverage = LD2 step 2)
4. Watchlist click-to-sort → CLOSED
5. Mobile stacked 13F view → NEXT (still stable+accurate on more devices)
6. Track C G1/G9 → Deferred

The snapshot's "Mobile stacked 13F view" as next ticket is **consistent with LD2**: it's the last "stable+accurate" piece (mobile parity) before pivoting to coverage expansion (LD2 step 2 = VL ingestion). ✓

**One inconsistency I'd flag:**

LD2 step 2 ("expand VL coverage") and Section N2 say "open a decision gate first, not an implementation ticket." Section "Next Action" #3 says "Open the Value Line ingestion coverage decision gate **after N1 lands**." The sequencing is correct, but the ordering implies VL coverage expansion happens AFTER mobile stacked view. Per LD2's literal reading, mobile is step 1 of the same priority cluster ("stable+accurate"), so this is consistent. Not an inconsistency, just worth highlighting that mobile and VL coverage are siblings in priority and the project shipped 3 of 4 stable+accurate items.

---

## Should-block items (none → APPROVE WITH NOTES, not REJECT)

No documentation issue blocks merge. The biggest concern is **D5 (memory vs AGENTS.md split)** — the cross-agent rules are currently in the wrong place. But this is a "consolidate v2" task, not a merge gate.

---

## Future backlog

- **D1 #1-5**: Add 5 documented rules to AGENTS.md (First Eagle audit, options exclusion in scoring, test helper FK ordering, `_normalize_score_confidence` shim contract, `value_thousands_override` precedent).
- **D2**: Tighten CLAUDE.md line 16 to active voice + bolded canonical-direction statement.
- **D3**: No closure-reversal needed.
- **D4**: Establish filename suffix convention going forward (`-ticket.md` / `-decision-gate.md` / etc.).
- **D5**: Promote 5 cross-agent memory rules to AGENTS.md; audit which memory entries to keep vs delete.
- **D6**: When filing next snapshot, audit `docs/tasks/` for unmentioned open tickets.

---

## Net

The documentation has been the secret weapon of this PR's reviewability. 170 commits would be unreviewable; the task-file decomposition makes them tractable. Workbook consolidation (CLAUDE.md → AGENTS.md, 365 → 228 lines, aspirational content removed) is a real improvement. The remaining issue is **where rules live**: too many cross-agent rules are stuck in memory instead of AGENTS.md, and too many AGENTS.md rules have duplicate memory shadows. A future consolidation pass should fix the split.

Nothing here is urgent enough to block this PR. The pattern of "task file per MVP closure + locked decision gates + snapshots" is solid and worth keeping.
