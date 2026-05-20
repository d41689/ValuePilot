# Review prompt — AGENTS.md restructure (2026-05-20)

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the task log
`docs/tasks/2026-05-20_agents-md-restructure.md`.

---

## Reviewer brief

You are reviewing a **restructure of `AGENTS.md`** — the cross-agent contract
file every agent (Claude Code, Cursor, Aider, Copilot) loads every session.
**This is not a code change.** No behavior changes; the risk is entirely in the
*document*.

### Intent of the change

Make `AGENTS.md` more effective as an always-loaded file: front-load the
catastrophic guardrails, raise signal density, and move deep / task-specific
reference into `docs/architecture/` so a session that doesn't need it doesn't
pay for it. New structure: Start here → Canonical commands → Critical invariants
→ Workflow → Data layer → Parsing → Coding standards → Frontend UI standard.

### Deliberate policy changes

Most of this is reorganization, but **three** cross-agent policies are
intentionally added or changed (all from user-approved advisory recommendations
of 2026-05-20):

1. **Task logging — changed** from "before making any code changes" to tiered
   (full task doc for *substantive* changes; none for *trivial* ones).
2. **Git / PR conventions — new** section.
3. **"When to stop and ask" — new** section.

Everything else should be location-only, with no change of meaning.

### Files in scope

- `AGENTS.md` (rewritten)
- `docs/architecture/metric-facts-is-current.md` (new — extracted)
- `docs/architecture/data-layer.md` (new — extracted)
- `docs/architecture/parsing.md` (new — extracted)
- `docs/tasks/2026-05-20_agents-md-restructure.md` (task log, has a
  rule-preservation checklist — a *starting point*, verify it independently)

### Baseline for comparison

The pre-change file is on `main`: `git show main:AGENTS.md`. Diff it against the
branch's `AGENTS.md` plus the three new `docs/architecture/` files.

## Answer every question below with a verdict + evidence

### A. Losslessness — the core review

1. **No rule dropped.** Walk every normative statement in `git show main:AGENTS.md`
   (every MUST / NEVER / DO NOT / numbered rule / convention) and confirm each
   one appears in either the new `AGENTS.md` or a `docs/architecture/*.md`. Do
   not trust the task log's checklist — reproduce it. Flag anything missing or
   **weakened** (e.g. a "NEVER" softened to a "prefer").
2. **Moved content is faithful, not lossily paraphrased.** Spot-check that these
   precise items survived verbatim or with identical meaning:
   - the locked `is_current` design text (PO date, Option A/B, the
     `_reconcile_parsed_fact_current_slot` scope tuple, the ADBE "42 rows" fact);
   - the EDGAR gotchas — `shrsOrPrnAmt` / `sshPrnamt` / `sshPrnamtType`,
     `xslForm13F_X02/`, `cusip_ticker_map.source` is VARCHAR(50) with exactly
     `"openfigi"` / `"sec_co_tickers"` / `"manual"`, Kahn Brothers CIK
     `0001039565-*` reports dollars not thousands;
   - the Alembic identifier rules (`down_revision` matches the `revision`
     variable, never change identifiers on rename);
   - the schema-change Wrong/Right code examples.

### B. The intentional policy changes

3. Confirm the **three** deliberate policy changes above (tiered task logging,
   new Git/PR conventions, new "When to stop and ask") are the *only* semantic
   changes — nothing else quietly changed meaning while being "tightened". Then
   judge the tiered task-logging criteria: tight enough that an agent cannot
   abuse "trivial" to skip a task doc on a genuinely substantive change?

### C. New content — accuracy

4. **Critical invariants (7 items).** Each must be an accurate condensation of a
   real rule from the old file. Confirm the set is genuinely the
   highest-stakes rules — flag any catastrophic rule that is *not* in the list
   but should be.
5. **Enforcement claim — verify against the actual repo.** `AGENTS.md` asserts:
   "Invariants 1, 4, 5, 6 are reviewer-enforced; 2 and 3 have no automated
   guard." Check this against the test suite and the DB schema. In particular:
   are the provenance columns (`document_id`, `page_number`,
   `original_text_snippet`) `NOT NULL` in the model/migrations? If so, invariant
   6 is **DB-enforced**, not reviewer-enforced, and the line is wrong. Correct
   any mis-stated enforcement.
6. **Canonical commands table.** Confirm every command matches what CI actually
   runs — check the CI workflow (`.github/workflows/`). A wrong command here
   silently breaks the verification discipline for every future agent.
7. **Git / PR conventions (new section).** Confirm it is correct for *all*
   agents and does not contradict or duplicate `CLAUDE.md` (which carries
   Claude-specific commit conventions). `AGENTS.md` is the cross-agent contract;
   Claude-only mechanics belong in `CLAUDE.md`.

### D. Structural integrity

8. **Links resolve.** Every `docs/architecture/*.md` path referenced in
   `AGENTS.md` points to a file that exists; the cross-links between the
   architecture docs resolve; `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md`
   (referenced from the `is_current` doc) still exists.
9. **CLAUDE.md boundary.** `CLAUDE.md` imports `AGENTS.md` via `@AGENTS.md` —
   confirm it still resolves. Confirm nothing Claude-specific leaked into
   `AGENTS.md`, and nothing cross-agent got stranded only in `CLAUDE.md`.

### E. Effectiveness — did it meet the goal?

10. Judgement call: are the guardrails genuinely front-loaded and is the
    always-loaded file's signal density actually better? Is anything still
    buried that a fresh agent needs early? The file is ~the same length (207 vs
    229 lines) because freed space was reinvested into the new guardrail/process
    sections — assess whether that trade was right, or whether more inline
    detail should move out to `docs/architecture/`.

## Verification

Docs-only — no CI to run. Useful mechanical checks:
- `git show main:AGENTS.md` for the baseline.
- `grep -rin "<keyword>" AGENTS.md docs/architecture/` to confirm each old rule's
  keywords still resolve somewhere.

## Pass bar

Approve only if: A1–A2 show **zero** lost or weakened rules; B3 confirms the
three deliberate policy changes (tiered task logging, new Git/PR conventions,
new "When to stop and ask") are the only intentional semantic changes and the
tiered task-logging criteria are sound; C4–C7 are all accurate — especially C5
(the enforcement claim) and C6 (the command table); D8–D9 hold. E10 is advisory
and does not block.
