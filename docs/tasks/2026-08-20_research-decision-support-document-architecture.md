# Research Decision Support document architecture

Date: 2026-08-20

Owner: Product / Engineering

Status: complete

## Goal

Separate ValuePilot's non-normative investment-research philosophy from its
normative Research Decision Support architecture so agents and engineers have
one clear authority for ownership, publication, point-in-time behavior, and
integration boundaries.

The existing 7,056-line `docs/Investment_Decision_Support_System.md` is first
preserved unchanged in commit `626f797`. A short architecture contract will be
written and adversarially reviewed before that snapshot is reduced and renamed
as a non-normative Vision.

## Acceptance criteria

- The original document is preserved unchanged in a dedicated first commit.
- A concise architecture document defines only the ten approved contract areas:
  authority, research ownership, AI/human authority, canonical financial truth,
  canonical valuation truth, point-in-time/supersession, orthogonal states, no
  trading rails, authorization/source visibility, and multi-source case origins.
- The architecture references existing authoritative contracts instead of
  restating metric or storage semantics.
- Repeated adversarial review finds no remaining valid issue in those ten areas;
  findings and dispositions are recorded.
- The original document becomes a clearly labeled non-normative Investment
  Research Vision with normative architecture, schema, state, roadmap, MVP, and
  acceptance content removed.
- The detailed EXLS material moves to an explicitly illustrative case study.
- All local Markdown links added by this task resolve, superseded filenames are
  absent from new normative references, and `git diff --check` is clean for the
  task's final diff.

## Scope

### In

- Documentation authority and precedence.
- Research ownership and publication boundaries.
- Integration with existing Value Line, 13F, Oracle's Lens, Watchlist, screener,
  stock summary, and manual discovery surfaces.
- Vision reduction and EXLS example extraction.
- Documentation-only adversarial review and mechanical verification.

### Out

- Database, API, parser, frontend, job, or migration implementation.
- Redefining canonical metric keys, units, period semantics, or
  `metric_facts.is_current` behavior.
- Broker execution, order routing, margin management, tax accounting, or
  portfolio reconciliation.
- Changing existing PRD, roadmap, mapping, coverage, 13F, or data-layer
  contracts owned by other work.

## Authoritative references

- `docs/metric_facts_mapping_spec.yml`
- `docs/prd/value-pilot-prd-v0.1.md`
- `docs/prd/README.md`
- `docs/architecture/data-layer.md`
- `docs/architecture/metric-facts-is-current.md`
- `docs/architecture/coverage-source-policy.md`
- `docs/13f/oracles_lens_signal_policy.md`
- `docs/plans/research_decision_loop_product_roadmap.md`

## Files to change

- `docs/architecture/research-decision-support.md`
- `docs/tasks/2026-08-20_research-decision-support-architecture-review.md`
- `docs/Investment_Decision_Support_System.md` (rename/remove after architecture
  sign-off)
- `docs/Investment_Research_Vision.md`
- `docs/examples/exls-investment-research-case-study.md`
- `AGENTS.md` (architecture discovery link only)
- this task record

## Test plan

Documentation-only verification:

1. Validate all Markdown links added by this task resolve locally.
2. Search the architecture for forbidden redefinitions and ambiguous authority.
3. Search the Vision for normative schema/API/state/roadmap/acceptance language.
4. Verify the frozen snapshot commit contains only the original document.
5. Run `git diff --check` over the task commits.

The Docker application suites are not required because this task changes only
Markdown and introduces no executable behavior. If any executable file is
changed, run the complete canonical Docker gate before sign-off.

## Decisions and sign-off trail

- 2026-08-20: Original 7,056-line document frozen unchanged in commit
  `626f797` before any restructuring.
- 2026-08-20: Work proceeds architecture-first; Vision reduction is blocked
  until the architecture adversarial review passes.
- 2026-08-20: Architecture adversarial review Rounds 1–2 found and resolved
  eight valid boundary issues. Round 3 passed all ten declared decisions; Vision
  extraction is now unblocked, with a final link/conformance repeat required.
- 2026-08-20: Replaced the active 7,056-line mixed-purpose document with a
  678-line non-normative Vision and a 304-line illustrative EXLS case study. The
  frozen source remains recoverable from `626f797`.
- 2026-08-20: Post-extraction Round 4 repeated the architecture matrix and link/
  boundary checks with no new valid finding. Documentation contract signed off.
- Dependency note: the referenced coverage-source policy, Oracle's Lens policy,
  Research Decision Loop roadmap, and PRD §G were pre-existing workspace
  authorities owned by other work. They were intentionally not staged into
  these commits. This branch must be integrated with the change that commits
  those authorities; the task does not appropriate unrelated dirty-worktree
  changes merely to make a standalone diff.
