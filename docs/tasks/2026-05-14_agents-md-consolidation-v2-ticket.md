# AGENTS.md Consolidation v2 — Promote Cross-Agent Rules from Memory

## Status

**Open 2026-05-14.** Filed as a follow-up to PR #33 Documentation reviewer (D1 #1-5, D5).

The 2026-05-14 workbook consolidation (CLAUDE.md → AGENTS.md) covered the 5 data contracts that were in CLAUDE.md. The Documentation reviewer identified TWO additional gaps:

1. **5 cross-agent rules currently live in Claude-Code-only memory** (`~/.claude/projects/<repo>/memory/`). Other agents (Cursor, Aider, Copilot) don't see them. They should be in AGENTS.md.
2. **5 documented project rules are scattered across memory + code comments + task files** but not in AGENTS.md. They should be hoisted.

## Goal

Make AGENTS.md the **single source of truth for every cross-agent rule** in the codebase. Memory becomes Claude-Code-specific reinforcement / project-state notes only, never a canonical contract.

## D1 — Promote cross-agent feedback rules from memory to AGENTS.md

**Source**: Documentation D5.

The Documentation reviewer audited 9 memory entries. 5 are cross-agent rules misfiled in memory:

| Memory entry | Promote to AGENTS.md section |
|---|---|
| `feedback_tool_validation_vs_product_signoff` | New "Validation discipline" sub-section (relates to Verification Discipline) |
| `feedback_phased_tickets_need_explicit_trackers` | "Task logging" sub-section |
| `feedback_no_stub_routes_for_ctas` | New "UI / product surface rules" or under "Frontend UI Standard" |
| `feedback_strict_mvp_scope_discipline` | "Development workflow" — new "Scope discipline" sub-section |
| `feedback_financial_data_unknown_vs_zero` | Under "Data Layer" — new "Missing-data states" sub-section |

For each:
- Lift the rule body into AGENTS.md.
- Keep the memory entry but rewrite it as a thin reinforcement pointer (matching the pattern of `feedback_local_green_vs_ci_green.md`).
- OR delete the memory entry entirely (Staff A4 argued for this; Documentation D5 argued for keeping reinforcements). Decide per-entry.

## D2 — Add 5 missing project rules to AGENTS.md

**Source**: Documentation D1 #1-5.

5 rules documented in memory `project_13f_prd.md` or code comments that are project-level (any contributor working in the codebase needs them) but absent from AGENTS.md:

| Rule | Section in AGENTS.md |
|---|---|
| First Eagle co-attribution audit ("Before expanding the superinvestor universe past 72 managers, re-run the audit query and verify exact share-count matches stay at 0.") | "Parsing → EDGAR/13F gotchas" |
| Options exclusion in scoring paths ("All four scoring-eligibility paths must filter `Holding13F.put_call.is_(None)`.") | New "Scoring service contracts" section |
| Test helper FK-deletion ordering ("Any `_clear_13f` helper must delete `OraclesLensScoreComponent` then `OraclesLensSignal` before `InstitutionManager`.") | New "Testing conventions" sub-section under Development Workflow |
| Score confidence normalization shim ("Any new endpoint reading `score_confidence` from a persisted dashboard item must call `_normalize_score_confidence()`.") | New "API surface conventions" section OR under "Scoring service contracts" |
| `Holding13F.value_thousands_override` precedent ("Any new scoring primitive that takes a `Holding13F` and computes a per-row metric must accept a `value_thousands_override` kwarg.") | Under "Scoring service contracts" |

## D3 — Audit and tighten existing AGENTS.md rules

**Source**: Documentation D1 spot-checks.

- "Screeners MUST filter on `value_numeric` for numeric comparisons (not JSON)" — tighten to clarify that composite scores stored in `value_json` are read via `_fact_value` at the service layer, NOT in screener rule evaluation. The current wording reads as contradictory with the Piotroski `value_json` fallback in `_fact_value`.
- "Use Tailwind classes for layout and component-specific adjustments only" — add a note that shadcn component reuse takes precedence over visual fidelity at edge cases (e.g., the Conviction Badge wrapped in `Button variant="ghost" className="h-auto p-0 hover:bg-transparent"` is intentional).

## D4 — Update memory entries to reflect canonical relocation

After D1 lifts rules to AGENTS.md, memory entries fall into three states:

- **Deleted**: the rule is in AGENTS.md and the memory copy adds no Claude-Code-specific value.
- **Thin pointer**: the rule is in AGENTS.md and the memory entry adds Claude-Code-specific reinforcement (e.g., a phrasing aimed at session-resume).
- **Kept canonical-in-memory**: the entry is genuinely Claude-Code-specific (e.g., `project_13f_prd` is project state, not a contract).

Make the deletion decision per-entry. Document the choice in this ticket's sign-off trail.

## D5 — Filename convention going forward

**Source**: Documentation D4.

New tickets created post-2026-05-14 should use suffixed filenames so the type is distinguishable without opening the file:

| Suffix | Type |
|---|---|
| `-ticket.md` | Implementation work |
| `-decision-gate.md` | Design / product decision pending |
| `-review-prompts.md` | Multi-agent review prompts |
| `-end-to-end-verification.md` | Closing verification doc |
| `-snapshot.md` | Open-work status |

No retroactive rename of 130+ existing files (that's churn). Apply forward only.

**Deliverable**: add the convention to AGENTS.md under "Task logging" so new contributors follow it.

## Scope Out

- Retroactive rename of existing `docs/tasks/*.md` files.
- Restructuring `docs/tasks/` into sub-directories (e.g., `docs/tasks/mvp8/...`). Discussed elsewhere; not part of this ticket.
- OpenAPI-generated frontend types (separate Track-E follow-up).

## Verification

- AGENTS.md grows by ~50-80 lines (per Documentation D5 estimate).
- Memory entries either deleted or reframed as thin pointers; index in `MEMORY.md` reflects current state.
- `lib/uiStandard.test.js` and full canonical CI suite still green.
- A new contributor reading only AGENTS.md should see every cross-agent rule. No need to also read memory.

## Files Expected to Change

- `AGENTS.md` (+~80 lines)
- Several files under `~/.claude/projects/<repo>/memory/` (deletions / rewrites)
- `~/.claude/projects/<repo>/memory/MEMORY.md` (index updates)

## Sign-Off Trail

- [ ] D1 5 cross-agent rules promoted from memory to AGENTS.md.
- [ ] D2 5 project rules added to AGENTS.md (First Eagle audit, options exclusion, FK deletion order, score_confidence shim, `value_thousands_override`).
- [ ] D3 existing rules tightened (screener `value_numeric` clarification, shadcn override edge cases).
- [ ] D4 memory entries audited; per-entry decision recorded.
- [ ] D5 filename convention added to AGENTS.md.
- [ ] AGENTS.md re-read end-to-end for coherence; lint+build+tests green.
- [ ] **AGENTS.md Consolidation v2 closed.**
