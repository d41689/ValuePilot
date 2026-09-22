# Agentic Investment Lab — user stories draft

Date: 2026-09-22

Status: Documentation proposal; user confirmed third-party re-review passed and
authorized a local commit; no implementation or trading approval implied.

## Goal / Acceptance Criteria

Produce one self-contained Chinese user-story document for the proposed ValuePilot
Agentic Investment Lab. It must describe investor value, testable acceptance,
research/paper/live authority, portfolio and execution safeguards, learning and
evaluation, phased delivery, dependencies, and decisions for review.

The document must explicitly reconcile the proposal with the current no-trading
boundary and distinguish existing normative contracts from proposed behavior.
Every story has a stable ID, phase, user outcome, and observable acceptance criteria.

## Scope

In: read the referenced conversation and relevant repository product documents;
verify the broker claims needed for the proposal against an official source;
write and inspect the draft and this task record.

Out: application code, schema/migrations, financial or broker account actions,
changes to normative PRD/architecture, adoption of the existing monitoring draft,
commits, pushes, PRs, and implementation of any proposed capability.

Authorized file changes: only the two new Markdown files below. Repository-required
Docker closing checks may rebuild the local development containers and run the
canonical migration/test commands. Preserve all pre-existing modified/untracked
work. Stop after draft acceptance checks and
recording validation evidence; product approval remains a later review.

## PRD references

- [Research Decision Support](../architecture/research-decision-support.md), especially §§4, 6, 7, 9, 10.
- [Authoritative PRD](../prd/value-pilot-prd-v0.1.md), especially §G.
- Working-tree background: `docs/prd/investment-memory-monitoring-prd-draft.md`,
  draft only and not yet present in this branch's main baseline.
- Working-tree background: `docs/plans/value-investor-user-story-priorities.md`,
  not yet present in this branch's main baseline.
- Referenced ChatGPT conversation: `6aab279b-b664-83ea-beee-9adac124ac65`.

## Files to change

- `docs/prd/agentic-investment-lab-user-stories-draft.md` — review artifact.
- `docs/tasks/2026-09-22_agentic-investment-lab-user-stories.md` — this record.

## Test plan

Document checks: unique story IDs, phase/dependency coverage, acceptance criteria,
relative links, explicit proposed/implemented distinction, source citations, and
`git diff --check` / whitespace checks on new files. No executable regression is
added for a prose-only proposal. Do not claim these checks validate implementation.

Repository closing commands, if run, must be exactly:

```sh
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

## Decisions / gotchas

- Current architecture expressly forbids trading rails. A draft can propose a
  separately governed Lab program; it cannot silently grant execution authority.
- The monitoring PRD is also a draft. Reuse is a proposed dependency, not evidence
  that monitoring, prediction resolution, or calibration already exists.
- Official Robinhood documentation distinguishes Agentic-only trading from wider
  account read access. Do not describe trade isolation as complete data isolation.
- Historical LLM evaluations can contain model-training knowledge of later events;
  point-in-time retrieval alone is not proof of an uncontaminated backtest.
- The existing worktree contains unrelated product and frontend changes. They are
  outside this task and will not be corrected or included in its delivery.

## Evidence / sign-off trail

- 2026-09-22: Root read the three relevant source-conversation turns and governing
  research architecture; inspected relevant PRD and adjacent product proposals.
- 2026-09-22: Official Robinhood overview checked; source and checked date appear
  in the review artifact. No account was connected.
- Draft verification: 30 unique sequential story IDs, each with four numbered
  acceptance criteria; all relative Markdown links resolve. New-file whitespace
  validation and `git diff --check` pass. The first whitespace check identified
  three Markdown hard-break spaces; these were removed and the check passed.
- Scope review: only two new documentation files authored. Existing modified
  product/frontend files were left untouched. No implementation or broker
  capability is represented as delivered.
- Docker build/start and `alembic upgrade head`: exit 0.
- `docker compose exec -T api pytest -q`: exit 1; **61 failed, 2748 passed,
  2 warnings in 1040.90s**. Failures include
  `test_authenticated_reconciliation_is_tenant_safe_and_bounded` returning
  HTTP 409 `historical_currentness_unverifiable`, and currentness-guard errors
  in reconciliation, stock lookup, and Value Line tests. This is the same
  count and signature documented in the existing
  source working tree's `docs/BACKLOG.md` entry titled
  "Local verification — database wall clock jumps during full-suite execution"
  (that entry is not yet included in this branch's main baseline).
  No contemporaneous clock sampling was performed in this run, so recurrence
  of that root cause is **not established**. No financial guard was weakened,
  no shared database was restarted, and no schema cleanup or code fix was made.
  This existing out-of-scope verification problem remains tracked there; no
  duplicate backlog item or full-suite rerun was created for this prose task.
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`: exit 0;
  **276 passed, 0 failed/cancelled/skipped**.
- `docker compose exec -T web npm run lint`: exit 0.
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`:
  exit 0; production compilation, TypeScript and static page generation passed.
  Next regenerated the two type-import paths in `frontend/next-env.d.ts`; the
  exact pre-build user-owned file was restored from a temporary snapshot.
  `tsconfig.json` remained byte-identical to its pre-build snapshot.
- Repository-wide verification is **not green** because of the backend result;
  documentation validation is separate from application implementation
  readiness. The draft is saved for product review; no feature implementation,
  commit, push, broker connection, or trading authorization was performed.

## Third-party review adjudication — draft 0.2

Scope: revise only the proposal and this task record in response to the supplied
read-only review. Preserve all 30 story IDs and the four-criterion structure.
No application, normative-contract, runtime, account, or Git-state change.

Acceptance before editing:

- F-01: fix coverage authority before a run; prevent omission or downgrading from
  bypassing its action block. The fixture must explicitly make the missing item
  required rather than claiming every unknown universally blocks every action.
- F-02: contaminated/uncertain historical results cannot establish improvement or
  promotion; the claimed improvement must pass an independent prospective gate.
- F-03: fix eligible opportunities, required prediction types, scoring units and
  weights before evaluation; report omissions and failed/restarted attempts.
  Do not score unknown outcomes as false or blend different agent versions.
- F-04: narrow the first trading scope to equities and cash, keeping ETF/index
  benchmark comparisons separate from tradable assets. No new fund subsystem.
- Review question 5: distinguish an unpromoted challenger from a predesignated
  baseline; require candidate-specific prospective process/control evidence for
  any live trial. Unknown investment skill is not permission for challenger
  promotion, and no automated live transition is introduced.

Validation plan: inspect exact changed clauses and counterexamples, check story
IDs/criteria, Markdown links/whitespace and all ETF/promotion references. This is
a prose follow-up to the recorded canonical run above, not an application release
gate. Do not repeat unchanged runtime suites or represent the known backend
failure as resolved. Record document-check results after the revision.

### Adjudication and evidence

All four principal findings were independently classified as in-scope product
contract gaps. Review question 5 was treated as a related phase-admission
ambiguity. The proposed defaults are recorded in draft 0.2; they remain subject
to product approval and third-party re-review, not retroactively approved policy.

| Review item | Minimal disposition | Clauses / document-level counterexample |
| --- | --- | --- |
| F-01 | Adopt: user-approved coverage and bound actions fixed before a run; no runtime AI downgrade | AIL-01.3, AIL-04.3, D5, scenario 1 explicitly requires the missing customer-concentration input |
| F-02 | Adopt and clarify: potentially contaminated history is excluded from promotion evidence; prospective evidence must independently meet gates | AIL-24.4, AIL-25.1/3, scenario 7 |
| F-03 | Adopt: preregister opportunities, groups, weights, coverage and complete attempts; keep raw descriptive scores distinct from a promotion conclusion | AIL-10.1, AIL-21, AIL-24/25, §8.3, scenario 8 |
| F-04 | Adopt smaller scope: equities/cash; ETF benchmark is not tradable; fund contract deferred explicitly to S4 | §1/4, AIL-12.2, D2/D8, scenario 9 |
| S3 admission | Clarify: an unpromoted challenger cannot enter live; initial baseline or promoted version requires its own prospective process/control evidence and separate authorization | §4, AIL-25.3, AIL-26.1, D7, scenario 7 |

Unknown resolutions/abstentions were not converted to artificial failure labels;
different model versions were not pooled into one score. No new subsystem,
role, service or normative contract was introduced. The supplied review's
already-covered scenarios and implementation-detail questions did not become
additional requirements. Broader S3 architecture and provider-dependent
retention remain the pre-existing explicitly deferred work, not newly discovered
application defects requiring another backlog entry.

Validation performed after revision:

- Perl document checks: **PASS** — exactly AIL-01 through AIL-30, unique and in
  order; four acceptance criteria per story; draft version 0.2; all relative
  file links resolve; no trailing whitespace.
- `git diff --check`: **PASS**.
- Focused inspection of every ETF, promotion and S3 reference: narrowed scope
  and phase gate agree with the detailed stories; the three added adversarial
  scenarios map to the corresponding clauses. This is prose inspection, not
  execution of future acceptance tests.
- Only the proposal and this record were edited during this revision. No Docker
  or application checks were rerun; the initial canonical results above remain
  historical evidence, and the 61 backend failures remain unresolved.

## Re-review sign-off and local commit authorization

- 2026-09-22: The user reported that re-review passed and requested committing
  the changes. This authorizes a local commit of these two documents, not a
  push, merge, implementation, deployment or account action.
- Preserve the original working tree on `codex/s2-annual-financials-evidence`.
  Use an isolated worktree and fresh `codex/agentic-investment-lab-stories`
  branch from fetched `origin/main` (`15f4ba02`). Only the two documents belong
  in this commit. Commit identity verified as Dane / `d41689@gmail.com`.
- The original canonical run recorded above occurred in the source working
  tree at `1065f692` with its pre-existing uncommitted changes. It is not a
  green validation claim for this isolated branch. No application code is
  changed here, and the existing backend failure is not being repaired.
- Two referenced background documents and the clock-backlog entry are absent
  from the main baseline. Preserve their source paths/context as explicitly
  pending background rather than committing unrelated material or leaving
  broken relative links. Product behavior and acceptance criteria are unchanged.
- Commit-time document checks: PASS — 30 ordered unique story IDs, 120
  acceptance criteria, all retained relative file links resolve in the isolated
  branch, no trailing whitespace. `git diff --cached --check` passed and the
  staged file list contained exactly the proposal and this record.
