# 2026-09-04 — Versioned industry and method applicability gates

## Goal

Deliver FT-07 as a fail-closed, replayable method-applicability boundary so a
complete set of financial facts cannot be mistaken for permission to publish an
economically inapplicable Owner Earnings, ROIC, per-share trend, or system
valuation conclusion.

This advances ValuePilot's business-quality, normalized-owner-earnings,
margin-of-safety, and disconfirmation jobs. Success is observable when every
covered analytical consumer returns either an approved method decision with its
reviewed classification/version lineage or a typed unsupported result with no
partial numeric conclusion.

## Acceptance criteria

- Company economic classifications are human-reviewed, append-only,
  effective-dated, knowledge-dated, and supersession-aware for ordinary
  operating companies, banks, insurers, REITs, and other/unclassified cases.
- High-SBC, acquisitive, cyclical, and commodity-exposed attributes are likewise
  reviewed and versioned; missing required attribute reviews fail closed rather
  than silently defaulting to false.
- A migration-owned approved policy explicitly covers every combination of the
  four governed methods and every supported economic class. It approves only
  methods supported by existing normative formulas and records required
  evidence/adjustment contracts; it does not invent financial-sector, REIT, or
  commodity formulas from the non-normative Vision.
- Gate decisions deterministically resolve policy, classification, attribute
  reviews, and applicability at an effective date and knowledge cutoff. Results
  include stable policy identity, reviewed company state, required evidence,
  required outputs/adjustments, typed reasons, and replay inputs.
- Unreviewed/ambiguous classification, unavailable policy/rule, unsupported
  class, and absent or unmet required attribute evidence return typed
  `unsupported`; no blocked path exposes a partial numeric conclusion.
- Owner Earnings, ROIC, per-share trend, and system valuation consumers use the
  same shared gate without bypassing `metric_facts`, tenant/auth, point-in-time,
  currentness, source-reconciliation, or evidence-lineage guards.
- Golden and negative tests cover ordinary, bank, insurer, REIT, high-SBC,
  acquisitive, cyclical, and commodity strata, classification supersession and
  historical replay, missing reviews, and attempts to use an ordinary-company
  method for financials/REITs.

## Scope

### In scope

- The existing SEC economic-classification/risk-review and method-policy schema,
  extended by a fresh migration from the current `main` head as required.
- ORM projections and one shared method-gate service/contract.
- All current backend generation, read, research-workspace, trend, and DCF/system
  valuation consumers of governed outputs.
- Focused schema/service/consumer tests plus exact full in-container gates.

### Out of scope

- New bank, insurer, REIT, cyclical, commodity, high-SBC, or acquisitive
  financial formulas not already approved by normative contracts.
- Issuer-name, ticker, sector-label, SIC, or foreign-filing inference as
  classification authority.
- User-authored valuation authority, portfolio decisions, price-volatility or
  beta signals, UI redesign, data acquisition, or storage lifecycle changes.

## Authoritative contracts

- `docs/BACKLOG.md` FT-07.
- `docs/prd/value-pilot-prd-v0.1.md`, especially canonical publication,
  point-in-time visibility, source reconciliation, and industry applicability.
- `docs/metric_facts_mapping_spec.yml` for input and source semantics.
- `docs/architecture/data-layer.md`,
  `docs/architecture/metric-facts-is-current.md`, and
  `docs/architecture/research-decision-support.md`.
- GitHub issue #136. Frozen PR #128 is read-only background for requirements and
  test ideas; its implementation and migration chain are not reused.

## Files expected to change

- `backend/alembic/versions/<new>-method-applicability-gates.py`
- `backend/app/models/sec_publication.py`
- `backend/app/services/canonical_financials.py` and/or a focused shared gate
  module chosen after consumer inventory
- Current governed consumers under `backend/app/services/`
- Focused tests under `backend/tests/unit/`
- `docs/prd/value-pilot-prd-v0.1.md` for the reviewed lifecycle and fail-closed
  publication contract
- This task record and `docs/BACKLOG.md` when FT-07 is completed

## Test plan

Test-first focused iterations, always inside Docker:

1. `docker compose up -d --build`
2. `docker compose exec -T api pytest -q tests/unit/test_analysis_method_gate.py`
3. Targeted consumer suites identified during inventory.

Closing gate, verbatim and in order:

1. `docker compose up -d --build`
2. `docker compose exec -T api alembic upgrade head`
3. `docker compose exec -T api pytest -q`
4. `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
5. `docker compose exec -T web npm run lint`
6. `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`

Also run `git diff --check`, verify a single Alembic head, and obtain a fresh
strict read-only Terra full-diff review with no P0–P3 findings before sign-off.

## Decisions and sign-off trail

- 2026-09-04: Worktree and branch confirmed at requested `main` commit
  `3cef5c75`; existing SEC method tables are the baseline contract, not authority
  to publish any method because their seed policy intentionally marks all rules
  unsupported.
- 2026-09-04: Added migration `20260904150000` on parent `20260904140000`.
  It preflights retained reviews before DDL, requires active-admin reviewers at
  the database boundary, preserves database-stamped knowledge/transaction time,
  and seeds semantic policy `analysis-method-applicability-v2` with a canonical
  digest that excludes deployment time.
- 2026-09-04: V2 approves only the existing ordinary-company Owner Earnings,
  Value Line return-on-total-capital proxy, and Value Line per-share-rate
  methods after all four risk reviews are explicitly false. System valuation
  remains typed unsupported pending FT-09; financials, REITs, unclassified
  companies, and every reviewed material-risk state remain fail-closed.
- 2026-09-04: The authorized operator surface is the admin-only classification
  and risk-review API backed by append-only service writes, stock-scoped
  advisory locks, exact terminal supersession, stable typed conflicts, and
  rollback. Database triggers remain the final defense against direct-SQL
  reviewer or timestamp forgery.
- 2026-09-04: Supersession resolution is effective-range-aware as well as
  knowledge-dated. A prospective review does not erase an earlier effective
  state, and a cutoff before the later review's database stamp replays the prior
  state.
- 2026-09-04: Gate decisions expose policy ID/digest, method version, class
  review, explicit attribute-to-review-ID/state snapshots, required evidence,
  adjustments/outputs, effective date, knowledge cutoff, and typed reasons.
  Generated Owner Earnings facts persist this exact snapshot under
  `value_json.analysis_method`.
- 2026-09-04: Shared gates now cover Owner Earnings generation, stock fact and
  ticker reads, per-share growth options, research workspaces, Oracle's Lens,
  DCF input manifests, and DCF save-time revalidation. An unsupported system
  valuation produces no canonical DCF model inputs or saved numeric valuation;
  an independently approved Owner Earnings series can still be shown with its
  own authority.
- 2026-09-04: Tests-first checkpoints: the core schema/service/API suite moved
  from expected red to `60 passed`; consumer tests moved from `7 failed` to
  green; the full affected 14-file backend set is `215 passed` in Docker. Exact
  canonical closing gates and independent strict review remain pending.
- 2026-09-04: Normative closeout keeps one authority per concern: the existing
  mapping entries already own canonical input semantics, PRD §H.11 now owns
  review lifecycle and fail-closed publication behavior, and the immutable
  database policy registry owns runtime permission. The mapping file remains
  unchanged because its resolved contents are also approved Value Line source-
  mapping identity; changing it merely to restate policy would invalidate that
  authority. The existing data-layer and research-decision architecture already
  supplies the required fact-truth, replay, and human-authority boundaries, so
  those documents were not duplicated or changed.
- 2026-09-04: FT-07 implementation and affected-suite verification are complete
  and its backlog entry is removed. The intentional remaining block is system
  valuation: every system DCF path stays typed
  `system_valuation_method_pending_ft09`, with no canonical model inputs or
  saved numeric conclusion, until FT-09 approves a normative method contract.
- 2026-09-04: Strict Terra R1 found two real edge cases. Tests first reproduced
  a three-level finite-range supersession conflict for classification and all
  four risk attributes, plus a reviewer deactivation between service preflight
  and the database trigger. Cutoff-aware recursive descendant resolution and a
  typed `409 reviewer_not_authorized` translation closed both; the focused set
  is `66 passed` and the affected 14-file set is `221 passed` in Docker. R1's
  policy-effective-date concern was independently rejected: policy effective
  time is operational knowledge authority, while `effective_as_of` is company
  economic/input time; applying the policy date to historical input periods
  would make reviewed historical calculation/backfill impossible.
- 2026-09-04: Strict Terra R2 found three retained-authority edge cases. Legacy
  calculated Owner Earnings now require an exact, replayable origin gate
  snapshot whose knowledge cutoff is no later than the fact's actual
  database-clock insert time; missing, malformed, forged, future, or mismatched
  snapshots are quarantined on read with no numeric output. Current authority
  must independently remain approved, so a later policy cannot retroactively
  authorize an old calculation.
- 2026-09-04: Legacy manual `val.fair_value` facts linked to a research revision
  whose assumptions identify a DCF source remain immutable audit evidence but
  project as typed `system_valuation_method_pending_ft09` with no numeric value.
  The shared valuation boundary covers workspace, stock-pool, Oracle, and
  notification consumers; ordinary human-authored intrinsic values remain
  available. This quarantine is structural and cannot be lifted merely by a
  future current policy.
- 2026-09-04: Review authority is now one explicit lineage per stock/kind. Every
  continuation after the root must supersede the exact terminal even across a
  non-overlapping interval; cutoff-aware resolution still returns an ancestor
  in uncovered gaps and before the continuation is known. Service and database
  triggers enforce the same rule, legacy multiple roots fail migration
  preflight, and the trigger locks the active-admin reviewer row so concurrent
  deactivation has a defined commit order.
- 2026-09-04: R2 verification is green: the focused gate/consumer/migration/API/
  notification set is `123 passed`; the original 14-file affected set plus the
  notification suite is `256 passed`. A fresh isolated
  upgrade/downgrade/upgrade test is green, and the local applied database was
  replayed through `20260904140000` back to head `20260904150000`; its two review
  triggers both execute the final `guard_ft07_method_review_insert` function.
  Fresh strict full-diff review and exact canonical closing gates remain
  pending.
- 2026-09-04: Strict Terra R3 found that a retained valuation fact could become
  numeric again when its linked revision was missing, tenant/stock-mismatched,
  or redacted, and that using the final user assumption as source identity
  could both misclassify an empty-assumption human replacement and permit an
  ordered-marker bypass. Tests reproduced all cases before the fix.
- 2026-09-04: New research valuation publications now carry a server-controlled
  `research-valuation-origin-v1` snapshot in `metric_facts.value_json`, binding
  the product source to the exact revision ID independently of user-authored
  assumptions. Manual/watchlist publications remain usable even with empty
  assumptions; DCF publications remain quarantined across later assumption
  markers and revision redaction.
- 2026-09-04: Legacy linked values resolve conservatively: the revision must
  match the fact tenant and stock, remain unredacted, and contain explicit
  non-DCF human provenance. Any DCF assumption remains pending FT-09;
  missing/redacted/cross-tenant/wrong-stock or otherwise unprovable lineage is
  typed `valuation_origin_unverifiable`. Direct legacy manual values with no
  revision link remain available, and no path falls back to an older numeric.
  R3 focused verification is `82 passed`; the expanded 17-file affected set is
  `269 passed`. Fresh strict full-diff review and exact canonical closing gates
  remain pending.
- 2026-09-04: Strict Terra R4 found that the batch legacy-revision query's
  stock-set filter did not prove the revision matched each individual fact. An
  A-stock fact could point at a B-stock human revision included in the same
  batch. The resolver now explicitly verifies revision creator and snapshot
  stock against every fact before considering legacy assumptions; a two-stock
  regression covers the canonical reader, stock-pool/watchlist projection, and
  Oracle valuation batch while preserving B's valid human value.
- 2026-09-04: Four full-suite compatibility failures were stale test contracts,
  not production behavior: the SEC lineage migration tests now target Alembic
  head `20260904150000`, and the direct-SQL classification conflict expects the
  FT-07 exact-terminal error. The expanded 19-file affected suite is
  `308 passed`. Fresh strict full-diff review and exact canonical closing gates
  remain pending.
- 2026-09-04: Strict Terra R5 identified two retained-authority mutation paths.
  Migration `20260904150000` now installs a database `BEFORE UPDATE` guard for
  every old or new calculated Owner Earnings fact and every old or new manual
  `val.fair_value` fact. It prevents snapshot injection, numeric/provenance/
  identity rewriting, and simultaneous key/source escape; the only semantic
  history change is current-fact demotion, plus the existing narrow unavailable-
  reason redaction whose origin is unchanged. Downgrade refuses retained V2
  method snapshots or versioned valuation origins before any schema mutation,
  and a clean roundtrip proves the fact guard is removed and restored.
- 2026-09-04: A syntactically valid server valuation-origin snapshot is not
  sufficient by itself. Reads still require the exact linked research revision
  to exist and match the fact tenant and stock. Verified server DCF origins
  remain quarantined after revision redaction; verified manual/watchlist
  publication origins remain available because redaction removes authored
  content, not the immutable server-recorded publication source. Legacy linked
  facts retain the stricter unredacted-assumption proof rule.
- 2026-09-04: User formulas can no longer publish into method-governed output
  keys. The formula engine raises typed
  `method_reserved_formula_output` before loading inputs or writing a run/fact
  for Owner Earnings aliases, ROIC/return-on-total-capital outputs, per-share
  trend/rate outputs, and system valuation; `custom.*` outputs remain usable.
  Legacy `user_authored_formula` metadata is not authority: stock, workspace,
  DCF, and Oracle reads apply the shared method gate, and calculated Owner
  Earnings still requires its exact origin snapshot.
- 2026-09-04: R5 tests-first verification is green: the final focused migration/
  formula/consumer set is `57 passed`; the serial 16-file affected set is
  `321 passed`, with three additional workspace/pool/product-boundary suites at
  `31 passed`. The shared development database had zero retained reviews,
  method snapshots, or versioned valuation origins, so it was safely replayed
  from `20260904150000` to `20260904140000` and back without reset. It is at
  head with one final fact-authority trigger and both final review-authority
  triggers. Fresh strict full-diff review and exact canonical closing gates
  remain pending.
- 2026-09-04: Strict Terra R6 found that Piotroski generation and retained-score
  consumers could use the governed `returns.total_capital` ROIC proxy without
  proving FT-07 authority. Piotroski remains a derived score, not a fifth
  applicability method: only its total-capital fallback is governed by the
  shared `roic` decision. Generation now resolves one reviewed decision at the
  same effective date and knowledge cutoff as each input period, excludes the
  proxy unless approved, and persists the exact gate snapshot on every affected
  component and total. Standard ROA inputs remain usable without ROIC proxy
  approval. Reviewed banks and other financials retain the existing no-score
  boundary; insurers retain the existing explicitly classified insurance
  variant, and no parsed field silently classifies a company.
- 2026-09-04: A shared retained-score guard now verifies every claimed input ID
  against its actual tenant, stock, key, date, numeric, source role, and fact
  nature. A total-capital proxy additionally requires a complete snapshot whose
  knowledge cutoff is no later than the database-stamped score creation time,
  an exact approved replay at origin, and current approval. Missing, malformed,
  forged, future, mismatched, cross-tenant/stock, non-calculated, and legacy
  unprovable scores are typed unavailable with no numeric or partial/component
  leakage. Stock detail, raw facts, research workspace, stock pools, Oracle,
  the 13F drawer, formulas, and screeners all use that guard; the
  `score.piotroski.*` namespace is reserved for system-derived outputs without
  being mapped to a new method.
- 2026-09-04: Fresh migration `20260904160000` (parent `20260904150000`) extends
  the OLD/NEW calculated-fact update guard to all Piotroski rows, preventing
  snapshot/lineage injection, numeric or identity rewrites, and simultaneous
  key/source escape while allowing current demotion. Its downgrade locks and
  refuses retained Piotroski authority before restoring the exact migration-150
  function. Document reconciliation now demotes old calculated projections and
  appends replacements rather than deleting their audit history. Isolated
  `160→150→160` and `160→140→160` paths, refusal-before-mutation, and direct SQL
  attacks are covered.
- 2026-09-04: R6 focused tests moved from `21 failed / 2 passed` to green. The
  final deduplicated 25-file R5+R6 affected superset is `442 passed` in Docker;
  its only warnings are the pre-existing Starlette/httpx and anyio deprecation
  notices. Before shared-database migration, read-only counts were zero for all
  `score.piotroski.*` facts, totals, total-capital lineage, and method snapshots.
  The database was upgraded without backfill to `20260904160000`; direct schema
  inspection proves one fact-authority trigger whose final function contains
  the Piotroski guard. The migration artifact SHA-256 is
  `6e4a999f114c70616dca196ae94b8bd4f1c9f346821660b805f58625ad0eec77`, and the
  final isolated migration-focused rerun is `9 passed`. Rollout policy is
  fail-closed: any legacy score without the strict versioned manifest in
  another environment remains unavailable until a later authorized
  recomputation appends a new score. The missing operator-triggered bounded
  recomputation entry point is recorded in `docs/BACKLOG.md`; this PR does not
  rewrite legacy authority or add a batch job.
- 2026-09-04: Strict Terra R7 found two remaining numeric read paths and an
  under-specified retained Piotroski manifest. Formula and screener execution
  now apply the complete shared method gate to only the facts named by the
  formula dependencies or screen conditions before evaluation or SQL predicate
  execution. Owner Earnings, ROIC aliases, per-share trends, system valuation,
  and Piotroski authority therefore fail closed with stable typed errors, while
  custom outputs and unrelated facts remain usable.
- 2026-09-04: Piotroski generation now publishes calculation version
  `piotroski_value_line_v2` with strict manifest marker
  `piotroski-strict-manifest-v1`. Every component and total records a unique,
  exact, database-stamped input manifest; the shared read guard bulk-loads those
  inputs and reconstructs the claimed component or total before exposing any
  numeric. Duplicate, extra, omitted, cross-tenant/stock, wrong-period,
  future-input, metadata-method, and output-value tampering are quarantined.
  All pre-v2 Piotroski facts are intentionally unavailable even when they do
  not claim the ROIC proxy, because their unversioned metadata cannot prove the
  complete input set. The existing non-destructive recomputation backlog item
  is the recovery path; no retained fact is rewritten.
- 2026-09-04: Piotroski publication is period-atomic. If a total-capital proxy
  component is blocked, generation demotes the prior period projection and
  appends one typed unavailable total with no component, partial-score, or
  numeric payload. Normal periods append strict components and a matching
  total; any invalid retained fact quarantines every Piotroski fact for the
  same tenant, stock, and period without crossing tenant boundaries. R7 focused
  verification is `74 passed`, the Piotroski consumer/fixture set is
  `217 passed`, and the serial 27-file R5+R6+R7 affected superset is
  `464 passed`; only the pre-existing Starlette/httpx and anyio deprecation
  warnings remain. Migration 160 was not modified and no migration 170 was
  needed because its OLD/NEW trigger already protects the complete calculated
  Piotroski payload and identity.
- 2026-09-04: Strict Terra R8 found that a caller could request only one valid
  Piotroski fact and thereby avoid validating missing, demoted, duplicate, or
  invalid current siblings from the same publication period. The central guard
  now expands every requested `(user, stock, FY, period-end)` to its current
  database siblings for validation only. It requires exactly one strict total
  and an exact one-row-per-key match between the current sibling set and the
  total's rebuilt component declaration. Any failure quarantines only the
  matching tenant/stock/period; the caller still receives only its originally
  requested objects. A component-only screener rule is therefore checked
  before its numeric SQL predicate, while a valid complete period remains
  usable.
- 2026-09-04: Piotroski authority reads are explicitly bounded before database
  work: at most 500 requested facts, 50 period groups, 32 inputs per manifest,
  and 1,000 aggregate unique input IDs. The sibling expansion uses one
  partitioned query capped at the ten valid period rows plus one sentinel per
  group, followed by one bulk input query. Violations return typed
  `piotroski_method_authority_bound_exceeded` without leaking numerics; an
  over-limit request manifest performs neither sibling nor input reads.
  Decimal inputs and outputs are also required to be finite before formatting,
  reconstruction, or comparison, so PostgreSQL `NaN` and in-memory positive or
  negative infinity fail closed as a typed invalid manifest rather than
  raising. R8 focused verification is `63 passed`; the serial 29-file R5–R8
  affected superset is `759 passed` with only the pre-existing Starlette/httpx
  and anyio deprecation warnings. No migration or retained data changed.
- 2026-09-04: Strict Terra R9 found that the central Piotroski guard could
  validate database siblings yet return a detached or stale caller object, and
  that a present-day current projection could be mistaken for a historical
  one. The guard now snapshots every positive-ID caller before any query,
  boundedly reloads the current sibling projection from PostgreSQL with
  `created_at <= knowledge_at`, and requires an exact identity, authority,
  numeric, currentness, and timestamp match. Successful reads return those
  freshly populated canonical rows in caller order; duplicate, absent,
  non-current, or mismatched callers are typed unavailable for only their own
  tenant/stock/period.
- 2026-09-04: Piotroski point-in-time reads remain deliberately conservative.
  Freshly reloaded scores and inputs must be current, created no later than the
  read cutoff, and unchanged by that cutoff; inputs must also predate their
  score. A bounded, tenant/stock/period-scoped diagnostic for a current
  replacement created after the cutoff, or future timestamps present on the
  caller itself, returns `historical_current_projection_unverifiable` rather
  than inventing a historical currentness timeline. The calculator's bulk
  demotion does not advance the old row's `updated_at`, so the future-current
  diagnostic is necessary and its rows never become canonical read authority.
- 2026-09-04: R9 tests-first started with `10 failed / 29 passed`. Detached
  tampering, missing/duplicate IDs, future score/sibling/input timestamps,
  demotion and concurrent replacement, current happy-path rebinding, and
  cross-tenant isolation now pass. Final focused verification is `74 passed`;
  the exact serial 29-file R5-R9 affected superset is `760 passed`, with only
  the pre-existing Starlette/httpx and anyio deprecation warnings. An
  additional mistakenly selected but related two-file set contributed 25
  passing tests before the exact superset was rerun. No migration or retained
  data changed.
- 2026-09-04: Strict Terra R10 found that screener SQL predicates were not
  bound to the facts approved by the pre-query source and applicability guard.
  The guard now captures one evaluation instant `T` for the entire screen,
  limits the candidate universe to 10,000 rows, and runs reconciliation, SEC
  availability, and complete method applicability for every relevant stock at
  that same cutoff. It records only the canonical rows actually returned by
  those guards, keyed by stock and canonical metric key.
- 2026-09-04: Every screener fact alias now requires an approved
  `(fact_id, value_numeric)` pair in addition to its existing stock, metric,
  tenant visibility, selected-source, and current-row predicates, and requires
  both fact timestamps to be no later than `T`. Empty authority sets never
  match. A replacement inserted after the guard cannot enter the predicate, a
  demoted approved row is conservatively excluded, and a same-ID numeric
  mutation cannot change the result. Review knowledge committed after `T` is
  intentionally not allowed to flow backward into the captured decision; all
  stocks share the same point-in-time authority rather than chasing an
  unbounded sequence of later reviews.
- 2026-09-04: The Piotroski guard no longer issues an unconstrained lookup for
  a caller ID absent from its tenant/stock/period canonical sibling query.
  Missing, demoted, foreign-tenant, wrong-stock, and wrong-period callers now
  share the stable typed
  `piotroski_current_projection_unverifiable` result unless the caller's own
  timestamps prove it is after the requested cutoff. Current replacement
  detection remains bounded by tenant, stock, fiscal period, and cutoff.
- 2026-09-04: R10 tests-first reproduced seven initial failures covering
  post-guard Owner Earnings and forged Piotroski replacement, review timing,
  and foreign identity diagnostics; same-ID numeric mutation and reviewed
  multi-stock/multi-condition controls were added before the implementation.
  Final focused verification is `115 passed`; the exact from-scratch serial
  29-file R5-R10 affected superset is `768 passed`, with only the pre-existing
  Starlette/httpx and anyio deprecation warnings. A pre-existing DCF regression
  fixture was made deterministic by deriving its cutoff from database-stamped
  input creation and using the contract's explicit America/New_York date,
  removing its one-second and container-timezone flake. No migration, retained
  data, or storage changed.
- 2026-09-04: Strict Terra R11 found that repeated screener conditions expanded
  the same approved `(fact_id, value_numeric)` pairs once per SQL alias without
  a query-wide parameter budget. Although each guarded candidate set was
  bounded, seven conditions over 10,000 pairs could exceed PostgreSQL's bind
  limit. Query construction now accounts for two binds per approved pair plus
  eight conservative per-condition binds before creating any alias. Requests
  above the explicit 12,000-bind budget fail with the existing typed
  `screener_source_guard_bound_exceeded`; empty authority remains fail-closed.
  The budget intentionally also leaves expression-stack headroom observed for
  very large tuple predicates, not merely protocol-limit headroom.
- 2026-09-04: R11 tests-first reproduced the missing pre-SQL rejection. The
  exact 12,000-bind boundary (three repeated conditions over 1,996 pairs), the
  10,000-pair/seven-condition rejection before SQL, and the empty-authority
  control are green; the full focused file is `18 passed`. A first 29-file run
  had four unrelated late-suite PIT fixture failures (`767 passed`), all four
  of which passed in a fresh targeted session. The required complete
  from-scratch rerun is `771 passed` with only the pre-existing Starlette/httpx
  and anyio deprecation warnings. No migration, retained data, or storage
  changed.
- 2026-09-04: Strict Terra R12 found that the screener rule boundary accepted
  unsupported grammar and applied its resource limits only after authority
  queries. Rules are now normalized entirely in memory before the first SQL:
  only a non-empty `AND` of bounded, well-formed numeric conditions and known
  operators is accepted. `OR`, unknown rule/operator forms, booleans,
  non-finite/non-numeric values, malformed conditions, and excessive
  complexity return a stable typed 422. Candidate and bind budgets are derived
  from the normalized condition set before source, SEC, or method guards run;
  empty authority remains fail-closed.
- 2026-09-04: R12 also exposed a real point-in-time clock split: application
  time could precede PostgreSQL trigger/default timestamps by roughly 0.1 ms,
  so a just-committed valid fact could appear to be from the future during a
  long shared-suite run. Governed entry points now capture one database-owned
  `clock_timestamp()` cutoff per operation, after pure in-memory request
  validation, and pass that exact instant through fact selection, source
  reconciliation, SEC availability, applicability, calculation, screener SQL,
  and screener hydration. Explicit caller-supplied historical cutoffs remain
  authoritative and incur no replacement clock query. No epsilon or look-ahead
  tolerance was introduced.
- 2026-09-04: R12 tests-first covers invalid grammar and API errors, zero-SQL
  rejection, empty-authority and maximum-bound behavior, exact cutoff identity,
  later SEC amendment/retirement state, and a deterministic database-ahead-of-
  application-clock regression. Focused verification is `146 passed`; the
  governed consumer compatibility set is `204 passed`. The final from-scratch
  serial 30-file R5-R12 affected superset (including both 13F panel and product
  holdings source-guard suites) is `799 passed` in 584.64 seconds. Only the
  pre-existing Starlette/httpx and anyio deprecation warnings remain. No
  migration, retained data, storage, or external source was changed.
- 2026-09-04: Strict Terra R13 found that several current-state consumers used
  the UTC/container calendar date as method-policy business time. The shared
  authority module now owns an aware-only `America/New_York` business-date
  derivation from the already captured database evaluation instant. Screener,
  Formula, current Oracle overlays, stock detail/Piotroski, stock-pool and
  watchlist projections, and the Research Workspace/API all use that one
  `(T, New York date(T))` pair. DCF retains its equivalent existing ET clock;
  calculation/ingestion gates tied to a financial input period and persisted
  retained-authority replay retain their period/snapshot dates. Explicit
  Oracle historical price/effective dates are never replaced by the current
  business date.
- 2026-09-04: Stock-pool/watchlist and Research Workspace reads now capture T
  before the first governed query and pass it through fact timestamp bounds,
  source reconciliation and SEC availability, Piotroski/method gates,
  valuation facts, and current/canonical price reads. Workspace unresolved SEC
  publications require both publication knowledge and availability no later
  than T. Direct service calls may supply an aware historical/test T; the
  service does not capture a replacement clock in that case. Current research
  workspace and inbox dates are derived from the same New York business day,
  while their existing no-false-historical-projection rejection remains.
- 2026-09-04: R13 tests-first reproduced early authorization at `00:30Z` for a
  review effective on that UTC date. Cross-consumer controls prove it remains
  unavailable until New York midnight, then becomes available; Oracle's
  explicit historical date remains blocked as requested. Additional tests
  cover aware timestamps, exact cutoff propagation, future fact/valuation
  exclusion, stock/Piotroski and pool display dates, research endpoint/service
  clocks, and the full production consumer inventory. The focused eight-file
  set is `185 passed`; the final from-scratch serial 33-file R5-R13 affected
  superset is `835 passed` in 639.86 seconds. Only the pre-existing
  Starlette/httpx and anyio deprecation warnings remain. No migration,
  retained data, storage, or external source changed.
- 2026-09-04: Strict Terra R14 found two remaining point-in-time splits. The
  complete Oracle dashboard now captures one database-owned evaluation instant
  before its first dashboard read and threads it through current or historical
  price selection, quality/M3 facts and gates, and user/Value Line valuation
  references. A historical `price_as_of_date` still controls the price business
  date only; it does not replace the knowledge cutoff. `stock_prices` has no
  update projection and is insert-only by database contract, so its applicable
  PIT boundary is `created_at`; every selected `metric_facts` row is bounded by
  both `created_at` and `updated_at`.
- 2026-09-04: Active Value Line report selection and actual-conflict detection
  now accept an optional aware knowledge cutoff and apply both fact timestamp
  bounds. Stock-by-ticker captures T before duplicate ticker selection, uses T
  for active-report evidence and candidate fact counts, and derives the DCF
  clock from that exact T rather than querying a second clock. Research
  Workspace passes its existing earliest T through active-report and conflict
  reads. Callers that do not request PIT behavior remain source-compatible;
  supplied historical/test cutoffs are preserved.
- 2026-09-04: R14 tests-first reproduced a future manual valuation and price
  replacing known Oracle values, post-T reports changing active-report and
  duplicate-ticker selection, and a post-T restatement creating a Workspace
  conflict. All four focused regressions are green; the four directly affected
  files are `89 passed`, and a from-scratch serial 39-file R5-R14 affected
  superset is `670 passed` in 339.19 seconds. A final focused clock/PIT set is
  `9 passed`. Only the existing Starlette/httpx and anyio deprecation warnings
  appeared.
- 2026-09-04: An intentionally broader 49-file diagnostic run was not counted
  as passing: it reached `1040 passed` before one unrelated Owner Earnings
  lineage test failed closed. Instrumentation proved the immutable V2 policy
  row was approved but had database `known_at=2026-09-05T04:26:28Z`, while the
  same PostgreSQL server later returned an evaluation cutoff of
  `2026-09-05T04:03:59Z` (a 22 minute 29 second external wall-clock reversal).
  The gate correctly selected V1 and returned `method_unsupported`; all company
  classification and four risk reviews were present. The test passed alone and
  with each suspected prefix. No epsilon, policy rewrite, or fail-open behavior
  was introduced for this environmental clock reversal, and all temporary
  diagnostics were removed.
- 2026-09-05: Strict Terra R15 found that report selection and provenance still
  joined retained parsed facts to mutable `pdf_documents.user_id`, `stock_id`,
  and `report_date`, so a later metadata edit could relabel earlier evidence at
  a captured cutoff. Fresh migration `20260904170000` creates one append-only,
  database-stamped report-identity revision per retained document and captures
  every later identity change. Each new parsed fact is bound by an immutable FK
  to the exact revision current while its creating transaction holds a share
  lock on the document; caller-supplied revision IDs/timestamps, top-level or
  unrelated nested revision inserts, later rebinding, and explicit tenant/stock
  mismatches are rejected at the database boundary.
- 2026-09-05: Migration backfill binds retained parsed facts only when document
  tenant and explicit stock identity agree. A NULL document stock remains the
  existing multi-company-container contract, where each already-immutable fact
  stock is authoritative; it is not treated as an identity mismatch. Retained
  mismatches remain unbound and readers return typed
  `historical_report_identity_unverifiable`. A revision first learned during
  migration likewise cannot make itself visible at a pre-migration cutoff.
- 2026-09-05: Active report ranking, actual-conflict comparison, duplicate ticker
  selection, stock provenance, Research Workspace documents/fundamentals, and
  parsed-slot reconciliation now consume the fact-bound identity rather than
  current document metadata. Parsed fact content was already immutable under
  the Value Line legacy/run triggers; those historical evidence reads therefore
  use fact creation plus exact revision knowledge, and do not erase a retained
  fact merely because a later allowed `is_current` demotion advanced its
  `updated_at`. Stock and Research Workspace HTTP boundaries translate
  unverifiable identity to a stable typed 409 instead of a server error.
- 2026-09-05: Before revising the uncommitted 170 migration, the shared
  development schema was confirmed to contain zero identity revisions and zero
  bound facts, downgraded safely to 160, and upgraded back to the final 170.
  Inspection confirmed the exact trigger-depth insert guard and document row
  lock. R15 focused identity/consumer verification is `12 passed`; the complete
  document, stock, workspace, migration and deletion set is `132 passed`; and
  the upload, reparse, multi-page, legacy-ingestion, annual/time-series and ratio
  supplement is `47 passed`. Their final combined 19-file affected superset is
  `179 passed` in 173.13 seconds. The only intermediate supplement failure was a pre-existing
  MagicMock fixture that did not return the aware database cutoff introduced in
  R12; the fixture now supplies an explicit aware timestamp without changing
  production behavior. Exact canonical closing gates remain pending.
