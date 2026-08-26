# Research Decision Loop roadmap and delivery

Date: 2026-07-20  
Branch: `codex/research-decision-loop-roadmap`  
Status: complete

## Goal

Turn ValuePilot's verified 13F discovery capability into a complete,
auditable value-investing workflow:

```text
trusted 13F discovery -> fundamental coverage -> independent valuation
-> written decision -> monitoring -> review
```

Create the authoritative delivery roadmap, adversarially review it until every
identified real issue is resolved, implement every in-scope phase, repeat the
adversarial review on the implementation, and pass the repository's complete
closing gates.

## Acceptance criteria

- [x] A new branch is created from the current `main` commit without losing the
      already-verified uncommitted 13F work.
- [x] `docs/plans/research_decision_loop_product_roadmap.md` records the product
      thesis, scope, sequencing, data contracts, migrations, security and
      privacy boundaries, measurable gates, rollback strategy, and explicit
      non-goals.
- [x] The roadmap is reviewed from PO/value-investor, financial-data SME,
      backend/data, frontend/UX, security/privacy, operations, and test/QA
      perspectives. Every valid finding is resolved or removed from scope with
      an explicit product decision; no known real issue is left unrecorded.
- [x] The authoritative v0.1 PRD and current-state documentation agree with the
      approved roadmap before implementation changes its product contracts.
- [x] Research cases, immutable revisions, state transitions, evidence links,
      valuation ranges, decisions, and review dates are durable, user-owned,
      and fully authorized.
- [x] Coverage prioritization turns Watchlist, Oracle's Lens, and open research
      cases into an explainable queue without performing unlicensed document
      acquisition.
- [x] Active research stocks have freshness-aware EOD price coverage and
      explicit missing/stale states; no UI implies that sparse data is current.
- [x] The home page is a research inbox that surfaces the highest-value next
      actions and preserves ticker search.
- [x] Oracle's Lens and Watchlist can create or open a research case without
      duplicate active cases or loss of source context.
- [x] The stock research workspace supports the complete workflow without
      misrepresenting 13F timing, Value Line targets, user intrinsic value, or
      system-derived valuation references.
- [x] User-scoped manager follows and notification subscriptions support
      in-app delivery and safely configured external channels, with dedupe,
      cooldown, audit history, failure visibility, and test adapters.
- [x] A manual portfolio and position-decision linkage support review and
      post-mortem workflows without broker execution or tax-lot claims.
- [x] All migrations upgrade and downgrade safely on representative fixtures;
      critical new constraints and indexes are verified after upgrade.
- [x] Targeted tests are written before each production change, and every exact
      canonical CI command is green at the closing gate.
- [x] Browser acceptance covers desktop and narrow layouts for the principal
      research loop, including empty, missing-data, stale-data, loading, error,
      permission, and duplicate-action states.
- [x] A final requirement-by-requirement completion audit proves every roadmap
      deliverable from current code, database state, test coverage, and rendered
      runtime behavior.

## Scope

### In

- Product-governance reconciliation and roadmap review evidence.
- User-owned research workflow and immutable decision history.
- Coverage-priority/readiness services and EOD freshness.
- Research Inbox and unified company research workspace.
- Oracle's Lens / Watchlist integration.
- Manager follows, notification rules, delivery audit, and configured channel
  adapters.
- Manual portfolio linkage and investment-decision review.
- Required migrations, APIs, UI, tests, documentation, and operational
  visibility.

### Out

- Real-time or intraday market data.
- Automated investment recommendations, unsupported cost-basis estimates, or
  language implying that 13F positions are current trades.
- Broker connectivity, order placement, tax-lot accounting, or automatic
  portfolio synchronization.
- Unauthorized scraping or redistribution of Value Line content.
- Full-market fundamentals acquisition as a prerequisite for the targeted
  research loop.
- Quant execution/cockpit work. Only the already-approved data-sufficiency gate
  and forward archive dependency may be connected to this program.
- Production deployment, external messages, commits, pushes, or pull requests
  unless separately authorized by the user.

## Authoritative references

- `AGENTS.md`
- `docs/prd/README.md`
- `docs/prd/value-pilot-prd-v0.1.md`
- `docs/metric_facts_mapping_spec.yml`
- `docs/architecture/data-layer.md`
- `docs/architecture/metric-facts-is-current.md`
- `docs/prd/13f_automation_and_resilience_prd.md`
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md`
- `docs/prd/watchlist/watchlist-v1.md`
- `docs/plans/quant_product_definition_acceptance.md`
- `docs/tasks/2026-07-19_13f-current-code-zero-db-rehearsal.md`

## Files expected to change

The exact implementation list is phase-dependent and will be kept current in
the roadmap. Expected areas:

- `docs/plans/research_decision_loop_product_roadmap.md`
- `docs/prd/value-pilot-prd-v0.1.md`
- `docs/prd/README.md`
- `docs/BACKLOG.md`
- `README.md`
- `backend/alembic/versions/*`
- `backend/app/models/*`
- `backend/app/schemas/*`
- `backend/app/services/*`
- `backend/app/api/v1/endpoints/*`
- `backend/app/api/v1/router.py`
- `backend/tests/unit/*`
- `frontend/app/(dashboard)/*`
- `frontend/components/*`
- `frontend/lib/*`

## Test plan

Each phase starts with failing targeted tests. The final closing gate runs,
verbatim and in order:

```bash
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

Additional completion evidence:

- migration upgrade/downgrade/upgrade rehearsal against an isolated PostgreSQL
  schema or database;
- API authorization and idempotency tests for every user-owned resource;
- delivery-adapter tests with network calls mocked, plus explicit
  unconfigured-channel behavior;
- browser acceptance on seeded happy-path and all material failure states;
- `git diff --check` and an audit confirming no accidental changes to existing
  user work.

## Decision and sign-off log

- 2026-07-20: Created `codex/research-decision-loop-roadmap` from the same
  commit as `main` (`2c085cf`) and retained all 79 pre-existing modified or
  untracked paths from the verified 13F worktree.
- 2026-07-20: The program's product objective is a defensible research decision,
  not another 13F parity page and not an automated buy signal.
- 2026-07-20: The first implementation milestone must address targeted data
  coverage and the research workflow together. Building either an empty
  workflow or unused broad data inventory would not satisfy the goal.
- 2026-07-20: External delivery is fail-closed when configuration or consent is
  absent. Test adapters may prove behavior; this task does not authorize sending
  a real external message.

## Progress log

- 2026-07-20: Baseline inspection confirmed the branch starts at `main` while
  preserving the uncommitted 13F implementation and evidence. No production or
  external state was changed.
- 2026-07-20: The roadmap reached v1.0 after eight adversarial rounds. Rounds
  1–7 found and resolved 61 real contract, financial-semantics, feasibility,
  privacy, concurrency, migration, workflow, and testability issues. Round 8
  repeated the full review matrix and found no new valid issue; mechanical
  reference/stale-term/invariant checks and `git diff --check` passed.
- 2026-07-20: Reconciled the authoritative PRD, Watchlist PRD, historical
  development plan, PRD index, and repository README with the approved
  research-decision-loop contracts and verified 13F current state.
- 2026-07-20: Corrected Fair Value semantics test-first: user intrinsic value
  now has per-date currentness, Value Line targets remain a separately labeled
  valuation reference, and Watchlist no longer computes user margin of safety
  from a system target.
- 2026-07-20: Closed the Value Line percentage-normalization backlog item
  test-first. Parser/page JSON now uses percentage points consistently for
  industrial and insurance layouts; `MappingSpec` performs the sole base-ratio
  normalization. Insurance operating statistics are mapped into queryable
  facts, and the previously advertised Oracle's Lens net-margin/ROE facts are
  now actually generated.
- 2026-07-20: Published separate Consensus and Distinctive investment theses
  and version contracts. Reviewed all 82 curated managers, persisted a
  versioned 13F-representativeness projection, and made score components retain
  the base manager weight, representativeness factor and policy version.
- 2026-07-20: Added the coverage-source/license decision record. EDGAR remains
  rate-guarded and authorized; Value Line automation is upload-only until a
  separately recorded license exists; yfinance remains development-only; a
  configured commercial EOD provider is required for production completeness.
- 2026-07-20: Chose the safe historical-parser disposition: modern V1 product
  use remains supported, while historical expansion/backtest claims stay
  blocked until representative-era fixtures and x0 column alignment exist.
- 2026-07-20: Added the canonical valuation source guard and found/fixed a
  cross-user leak in Oracle's Lens. Manual intrinsic values and user-owned
  Value Line quality/target facts are now selected only for the authenticated
  user; anonymous legacy reads receive no private overlay.
- 2026-07-20: Proved the full quarterly 13F chain with real stage bodies over
  stored SEC evidence for three managers across two consecutive quarters. The
  test reaches active/current holdings, persisted quality reports, ownership
  changes and versioned Oracle's Lens components; only network acquisition and
  external identifier enrichment are replaced at their boundaries.
- 2026-07-20: Root-caused the daily-sync red/no-op ambiguity. A valid SEC index
  containing no filings for tracked managers is a successful no-op, an expected
  no-index day is `no_data`, and an unexpected fetch failure remains failed for
  retry. Added an explicit regression test and removed the resolved backlog
  item.
- 2026-07-20: Upgraded manager representativeness from a mutable projection to
  a projection backed by append-only, policy-versioned review decisions. Seed
  reruns are idempotent and fail loudly if an answer changes without a version
  bump; score component evidence now retains the review's effective timestamp.
- 2026-07-20: Implemented the targeted coverage foundation. Canonical EOD reads
  now use an explicit trading-session/freshness policy, deterministic source
  priority and required currency evidence; all product surfaces were migrated
  off direct `stock_prices` selection and a static guard prevents regression.
  Production provider selection fails closed unless the operator explicitly
  authorizes and enables it.
- 2026-07-20: Added user-scoped, explainable coverage requirements for
  Watchlists and the top-30 selected Oracle lens, plus an admin aggregate queue.
  Missing/stale EOD requirements are refreshed as one observable, deduplicated
  batch job and re-evaluated from stored evidence. Value Line gaps remain an
  upload action and are never auto-acquired.
- 2026-07-20: Delivered Research Cases, immutable revisions/origins/events,
  qualified-decision measurement, the ranked Research Inbox, discovery-surface
  create/open actions, and the unified company research workspace.
- 2026-07-20: Delivered user follows, logical notifications, immediate and
  digest delivery policy, quiet hours/cooldown, encrypted Slack and verified
  email destinations, retry/ambiguous-outcome audit, filing-season bridging,
  independent scheduling, and aggregate-only admin operations. No real external
  message was sent.
- 2026-07-20: Delivered manual long-only portfolios, versioned positions,
  immutable decision-journal events, case/revision links, review/post-mortem
  comparison, and explicit no-broker/no-tax/no-FX boundaries.
- 2026-07-20: Implementation review found and fixed alert boundary versioning,
  shared threshold policy, valuation-to-research lifecycle transitions,
  resumed-monitoring initialization, multi-replica alert locking, and
  development/production Next artifact isolation.
- 2026-07-20: The first full backend gate exposed incomplete cleanup in the
  committed-session manager-seed concurrency test plus an evidence-read source
  guard violation. Both root causes were fixed; the entire canonical sequence
  was restarted from container rebuild.
- 2026-07-20: Final canonical gate passed: migrations at head; backend
  `1433 passed`; frontend `216 passed`; ESLint had no warnings/errors; production
  Next build compiled, type-checked, and generated all 27 App Router pages.
- 2026-07-20: Post-build browser smoke passed for Research Inbox, MSFT case
  Revision 1, 13F timing caveat, notification audit, and in-app immediate policy.
  The 1280px viewport had no horizontal overflow or runtime/chunk error.
