# 2026-05-20 — Restructure AGENTS.md for agent effectiveness

## Goal / Acceptance Criteria

- Make `AGENTS.md` more effective as an **always-loaded** cross-agent contract:
  higher signal density, critical guardrails front-loaded, lower context cost.
- No rule is lost: every guardrail either stays inline (tightened) or moves to a
  linked `docs/architecture/` doc with an inline pointer + a one-line danger
  summary where the stakes are high.

## Scope

In:
- Rewrite `AGENTS.md` into: Start here → Canonical commands → Critical invariants
  → Workflow → Data layer → Parsing → Coding standards → Frontend UI standard.
- Extract deep / task-specific detail into `docs/architecture/`:
  - `metric-facts-is-current.md` — the locked `is_current` design.
  - `data-layer.md` — stock identity, manual corrections, no-band-aid schema
    policy, Alembic conventions, upsert-vs-IntegrityError.
  - `parsing.md` — fixture-alignment workflow, EDGAR/13F gotchas.
- New sections: Critical invariants summary, Git/PR conventions, "When to ask",
  tiered task-logging, enforcement annotations.

Out:
- No change to `CLAUDE.md` (it imports `AGENTS.md`; the import still resolves).

**Intentional policy changes** (NOT location-only moves — all three are from the
user-approved advisory recommendations of 2026-05-20):

1. **Task logging — changed.** From "before making any code changes" to tiered
   (full task doc for substantive changes; none required for trivial ones).
2. **Git / PR conventions — new.** Branch off `main`, never commit to `main`
   directly, branch naming, check `git config user.email`, commit/push only when
   asked, required PR-body contents.
3. **"When to stop and ask" — new.** Ask before ambiguous-scope, irreversible,
   or outward-facing actions, or when contradicting a locked design.

Everything else is reorganization with no change of meaning.

## Test plan

Docs-only change — no code, no CI. Verification is human review:
- `AGENTS.md` still parses as the `@AGENTS.md` import target (plain markdown).
- Every rule in the pre-change `AGENTS.md` is traceable to either the new
  `AGENTS.md` or a `docs/architecture/` file (checklist below).

## Rule-preservation checklist (pre-change AGENTS.md → new home)

- Three-layer storage → AGENTS.md Data layer + invariant #1
- Stock identity → AGENTS.md Data layer (short) + data-layer.md (full)
- Metric normalization → AGENTS.md Data layer + invariant #5
- `is_current` semantics → invariant #2 + metric-facts-is-current.md (full)
- Manual corrections → AGENTS.md Data layer (short) + data-layer.md (full)
- Schema no-band-aids → invariant #3 + data-layer.md (full Wrong/Right)
- Alembic conventions → data-layer.md
- Write-conflict upsert/IntegrityError → data-layer.md
- Parsing scope/strategy/mapping → AGENTS.md Parsing
- Fixture-alignment workflow → parsing.md
- EDGAR/13F gotchas → parsing.md
- Frontend UI standard → AGENTS.md Frontend UI standard
- Naming / error handling → AGENTS.md Coding standards
- Task logging → AGENTS.md Workflow (tiered)
- Test-first → AGENTS.md Workflow
- Running tests / Verification Discipline → AGENTS.md Canonical commands + Verification
- Safety contract checks → AGENTS.md Critical invariants #1, #4, #5, #6
- Per-PR checklist → AGENTS.md Workflow
- Review-prompts pointer → AGENTS.md footer

## Notes

- 2026-05-20: User approved the full restructure (option "全部重构 + 拆 docs/").
- Kept verbatim: the locked-design wording, Wrong/Right examples, EDGAR gotchas
  with specific CIK numbers, Alembic identifier rules — these are precise and
  must not be paraphrased.

## Review remediation (2026-05-20)

External review (`2026-05-20_agents-md-restructure-review-result.md`) verdict was
**not approved yet** — losslessness and structure passed, but three accuracy /
honesty issues blocked. All fixed:

1. **Enforcement claim (blocker C5).** `AGENTS.md` claimed "invariants 1, 4, 5, 6
   are reviewer-enforced; 2 and 3 have no automated guard" — false. Verified
   against the models: `metric_extractions.document_id` / `page_number` are DB
   `NOT NULL`, but `original_text_snippet` and `metric_facts.source_document_id`
   are nullable. Replaced with an accurate statement: none of the invariants is
   fully automated, a few have partial guards, the agent is responsible for all.
2. **Canonical commands (blocker C6).** Verified against `.github/workflows/ci.yml`:
   CI uses `docker compose exec -T ...` for every in-container step and
   `sh -lc 'NODE_ENV=production npm run build'` for the build. The command table
   now reproduces the CI pipeline verbatim (added `-T`, fixed the build command,
   listed steps in CI order).
3. **Honest scope (blocker B3).** The task doc and review prompt claimed task
   logging was the only semantic change. Corrected: there are **three**
   intentional cross-agent policy changes — tiered task logging, new Git/PR
   conventions, new "When to stop and ask" — all from the user-approved advisory
   recommendations. See the "Intentional policy changes" list above.

Also applied the review's non-blocking advisory (C4): strengthened Critical
Invariant #1 to state `metric_extractions` must never be modified (manual
corrections insert a new `metric_facts` row), rather than adding an 8th invariant
— keeps the list focused on the genuinely catastrophic rules.
