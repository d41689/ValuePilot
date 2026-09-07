# FT-10 automatic research coverage

Status: ready for review

Issue: #133

## Goal

Connect the existing user-scoped coverage projection to the research-case and
Inbox workflows so opening a case immediately produces an explainable,
source-traceable readiness view without an admin action. This advances the
circle-of-competence, normalized-owner-earnings, valuation, and disconfirmation
jobs by keeping missing, stale, blocked, inaccessible, and unsupported evidence
visible instead of silently treating an unevaluated case as ready.

Success is observable when create/reopen, case workspace, and Inbox consumers
agree on the same current business date and canonical coverage result, repeated
evaluation is idempotent, and historical reconstruction fails closed.

## Acceptance criteria

- Creating a new case or reopening a closed/voided stock cycle materializes its
  authoritative current coverage requirements in the same authenticated
  workflow; repeated create/open and read operations do not duplicate rows.
- The case workspace and coverage-driven Inbox actions expose the requirement
  state, source/evidence identity, freshness or as-of date, reason, evaluation
  time, and permitted next action.
- Coverage incorporates the existing canonical price, source-visibility/
  reconciliation, valuation, and reviewed method-gate decisions. It preserves
  distinct `ready`, `missing`, `stale`, `blocked`, `inaccessible`, and
  `unsupported` outcomes without inventing a value or choosing a source.
- Case, Inbox, and coverage consumers derive their current date from one
  database evaluation cutoff. Historical requests return the canonical
  `historical_as_of_not_supported` result and do not mutate the projection.
- Requirements remain user-owned. Cross-user reads disclose nothing, and the
  admin endpoint remains aggregate-only without user, case, document, holding,
  or requirement detail.
- Tests cover repeat evaluation, lifecycle transitions and Inbox supersession,
  permissions, missing evidence, source-policy blocking, inaccessible evidence,
  unsupported method authority, and current/historical date behavior.

## Scope

### In scope

- Minimal wiring from research case create/open and Inbox regeneration to the
  existing coverage evaluator.
- Only coverage projection-contract changes directly required to represent the
  accepted FT-10 states and existing canonical authority results.
- Focused case/coverage/Inbox UI copy and fields needed to expose source,
  freshness/as-of, reason, and next action.
- No new persisted state or migration: inaccessible and unsupported remain
  fail-closed projections of existing persisted states. No implementation is
  copied from frozen PR #128.

### Out of scope

- Notifications, portfolio/journal, postmortem, account/privacy redesign, new
  acquisition providers, external SEC/13F fetches, or unrelated consumer
  hardening.
- New financial formulas, source precedence, generic workflow frameworks, and
  changes to retained production/shared storage.

## Authoritative contracts

- GitHub issue #133 and `docs/BACKLOG.md` FT-10.
- `docs/prd/value-pilot-prd-v0.1.md` §G.5–G.6.
- `docs/architecture/research-decision-support.md` §§5, 7, 10–11.
- `docs/architecture/coverage-source-policy.md`.
- `docs/plans/research_decision_loop_product_roadmap.md` §§7.4–7.6.

## Files expected to change

- `backend/app/services/research_coverage.py`
- `backend/app/services/research_cases.py`
- `backend/app/services/research_inbox.py`
- `backend/app/api/v1/endpoints/research.py`
- `backend/app/api/v1/endpoints/coverage.py`
- focused tests in `backend/tests/unit/test_research_coverage.py`,
  `backend/tests/unit/test_research_cases.py`, and
  `backend/tests/unit/test_research_inbox.py`
- `frontend/app/(dashboard)/research/cases/[id]/page.tsx`
- `frontend/app/(dashboard)/home/page.tsx`
- `frontend/lib/researchDecisionLoop.test.js`
- this task record and `docs/BACKLOG.md` on completion

## Test plan

All tooling runs inside Docker. Use focused red/green iterations for the
coverage, case, Inbox, and frontend contract suites. At the closing
gate run the exact canonical commands from `AGENTS.md`, once and in order:

1. `docker compose up -d --build`
2. `docker compose exec -T api alembic upgrade head`
3. `docker compose exec -T api pytest -q`
4. `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
5. `docker compose exec -T web npm run lint`
6. `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`

Also run `git diff --check`, confirm one Alembic head, and hand the pushed Draft
PR to the independent read-only reviewer before merge.

## Decisions and sign-off trail

- 2026-09-06: Fresh worktree `/Users/dane/projects/ValuePilot-ft10-coverage`
  and branch `codex/automatic-research-coverage` created at `f4c29361`, the
  requested latest `origin/main`. Frozen PR #128 code and migrations are not
  reused.
- 2026-09-06: Scope is limited to missing coverage materialization and direct
  projection/display contract gaps. Existing canonical price, reconciliation,
  valuation, and method services remain the authorities; coverage only adapts
  their typed outcomes.
- 2026-09-06: PRD §G.6 and roadmap §7.5 explicitly define
  `valuation_input` as an authoritative coverage requirement kind. It is
  materialized only for open research cases and uses the existing canonical
  user-valuation read plus reviewed `system_valuation` method gate. No new
  requirement kind or valuation formula is introduced.
- 2026-09-06: The existing persistence constraint remains unchanged. A revoked
  source is projected as `inaccessible`, and a denied canonical method is
  projected as `unsupported`, from their fail-closed persisted coverage states.
- 2026-09-06: Focused testing at the Sunday-evening UTC crossover reproduced
  one adjacent date-agreement defect in the already-touched research service:
  the metrics endpoint derived its week from New York business time but queried
  event timestamps with UTC-midnight boundaries. The minimal compatibility fix
  converts only those established New York week boundaries to UTC; no broader
  time abstraction or unrelated consumer change is included.
- 2026-09-06: Independent review found two FT-10 defects before the closing
  gate. Current coverage now recognizes the New York business date while
  retaining the exact UTC knowledge cutoff, and Inbox source versions exclude
  daily observation labels while retaining source references, actual evidence
  dates, authorization state, policy identity, and reviewed method IDs. Focused
  tests prove a post-cutoff price is excluded, unchanged multi-day gaps remain
  stable, and genuine provider-permission/method-review changes supersede prior
  actions.
- 2026-09-06: Final canonical Docker gate at `58b38802` passed:
  `docker compose up -d --build`; `alembic upgrade head`; backend `pytest -q`
  (2,727 passed, 2 dependency deprecation warnings); frontend unit tests (233
  passed); frontend lint; and the production frontend build. Alembic reports
  the single head `20260904340000`; `git diff --check` passed.
- 2026-09-06: Independent read-only re-review of `58b38802` passed with no
  remaining findings. The reviewer verified both corrections retain the exact
  cutoff and material source/policy/authorization/evidence/method-review
  identity while ignoring observation-clock labels. Per shared-database
  coordination, the reviewer ran static checks only; the implementation agent
  ran the canonical Docker gate above.
