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
- 2026-09-05: Strict Terra R16 found that caller-controlled parsed-fact
  timestamps could still manufacture historical visibility. Fresh migration
  `20260904180000` leaves applied migrations 150/160/170 unchanged, stamps every
  new parsed fact's creation/knowledge time and creating transaction in
  PostgreSQL, and makes the row immutable except for the existing one-way
  `is_current=true` to `false` demotion. Retained rows receive only a
  conservative migration observation time and no invented creation-transaction
  identity. Cross-transaction timestamp/transaction backfill and later content
  mutation are rejected at the database boundary.
- 2026-09-05: Quant coverage now derives publication dates and stock ownership
  from each parsed fact's exact bound report-identity revision. It intentionally
  retains facts visible before a later currentness demotion, while unbound,
  pre-authority, identity-mismatched, or cutoff-unverifiable evidence produces
  typed `historical_report_identity_unverifiable` with no quantitative coverage
  claim. Mutable document metadata is no longer audit authority.
- 2026-09-05: Research Workspace documents are now derived only from the final
  bounded, visible, method-gated and reconciliation-safe fact set. Exact
  revision resolution is limited to those fact IDs and supports a shared
  multi-company PDF whose document stock is NULL while each fact retains its
  own stock identity. Reparse propagates the stable report-identity error and
  the HTTP boundary maps it to 409 rather than a generic 500.
- 2026-09-05: Active report resolution no longer hydrates every matching
  `MetricFact`. One bounded sentinel query detects unbound authority and a
  projected, distinct SQL query returns only stock/document/revision/report-date
  candidates. A 250-fact/one-document regression observes zero MetricFact ORM
  loads. R16 tests-first began with five expected failures; the new migration
  suite is `4 passed`, migration compatibility is `37 passed`, the focused
  identity/consumer set is `42 passed`, and the wider 23-file consumer set is
  `417 passed` in 196.03 seconds. One intervening run after earlier failed test
  sessions showed non-reproducible cross-suite failures; its exemplars passed
  independently and the exact full set then passed from a fresh pytest session.
  The shared development database was upgraded forward from 170 to sole head
  180 and contained zero parsed facts, so no retained row was rewritten there.
  Exact canonical closing gates remain pending.
- 2026-09-05: Strict Terra R17 found that the projected active-report query was
  still unbounded over distinct stock/document/identity-revision candidates.
  The resolver now applies one explicit limit of 500 to distinct requested
  document IDs, stock IDs, shared tenant IDs, and authority candidates. The
  candidate SQL reads at most 501 rows and raises the stable typed
  `active_report_authority_bound_exceeded` error when a complete choice cannot
  be made; it never returns a partial active-report map.
- 2026-09-05: `GET /documents` retains its list response and legacy unpaged
  behavior for accounts with at most 500 documents, adds `offset`/`limit`
  pagination plus total/page headers, and returns typed 409 rather than silently
  truncating an unpaged larger account. Active status for a page is resolved
  across the page companies' complete tenant-visible stock history, so an older
  page does not become active merely because the newer report is on another
  page. Company discovery is also tenant-filtered and bounded.
- 2026-09-05: All production callers were re-audited. Documents, duplicate
  ticker selection/stock summary, and Research Workspace map the new bound to a
  controlled typed 409 (Workspace via `ResearchCaseError`). The quant coverage
  audit does not call the active-report resolver and therefore has no resolver
  exception path to map. Focused tests cover oversized document, stock, shared
  tenant, and true distinct multi-stock/document/revision candidates; explicit
  failure instead of partial selection; tenant isolation; cross-page active
  ranking; pagination; and every HTTP mapping. The four directly affected test
  files are `88 passed`. The wider 11-file identity-migration, documents,
  stocks, Workspace, method-consumer, quant-audit, and reconciliation set is
  `210 passed` in 72.80 seconds. Canonical closing gates remain pending.
- 2026-09-05: Strict Terra R18 found that actual-conflict detection still
  hydrated every tenant-visible parsed actual fact even when active-report
  candidates were bounded. The service now validates exact fact-bound report
  identity with a one-row sentinel, projects only the eight columns needed for
  conflict comparison, and reads at most 501 observations. More than 500
  observations, including duplicate values or facts spanning multiple identity
  revisions, raises stable typed
  `actual_conflict_authority_bound_exceeded`; no partial conflict list is
  returned. The shared-tenant input is bounded by the same limit. Stock overview
  and Research Workspace translate the error to a generic typed 409 without
  identifiers or counts. The only production call sites are those two surfaces;
  the adjacent active-report and Workspace fact materializations already have
  their own max-plus-one bounds.
- 2026-09-05: R18 also made `GET /documents` pagination and response order one
  contract: `upload_time DESC NULLS LAST, id DESC`. The API no longer re-sorts
  each SQL page by derived ticker/report metadata, so concatenating pages cannot
  overlap or omit rows. The no-parameter list response remains compatible for
  accounts at or below 500 documents and continues to publish total, offset and
  effective-limit headers; global active-report selection remains independent
  of page membership.
- 2026-09-05: R18 tests-first stopped at the expected missing typed-error import.
  The six new focused regressions then passed, the four directly affected files
  are `93 passed`, and a 12-file identity-migration, documents, stocks,
  Workspace, method-consumer, quant-audit and reconciliation set is
  `256 passed` in 88.41 seconds. These tests cover 501 repeated observations
  with zero `MetricFact` ORM hydration, tenant isolation, duplicate facts across
  multiple identity revisions, both HTTP error mappings, stable cross-page
  concatenation, equal-upload-time ID tie-breaking, paging headers, no-argument
  behavior and global active status. Canonical closing gates remain pending.
- 2026-09-05: Strict Terra R19 found two remaining authority defects. First,
  an active report retained only a document ID, so an older fact bound to a
  prior report-identity revision of that same document was incorrectly labelled
  active. Conflict projection also kept every retained reparse fact and could
  silently let ascending fact ID choose an old value. `ActiveReportSelection`
  now retains the exact identity revision. Actual observations carry the exact
  fact and revision IDs, compare active authority by revision, and collapse one
  `(document, revision, metric, period)` slot only through a unique current fact
  from the canonical `metric_facts` projection. Parse-run timestamps and row
  IDs are not supersession edges; same-run, separate-run, or runless duplicates
  without a unique canonical winner therefore fail closed as typed
  `actual_conflict_authority_ambiguous`; fact ID is never a winner rule. Stock
  provenance and conflict responses expose the exact revision, and stock and
  Workspace HTTP boundaries map ambiguity to identifier-free 409 responses.
- 2026-09-05: R19 replaced offset as the authoritative document traversal
  protocol. `limit` without `offset` starts a signed HMAC keyset snapshot whose
  token binds the user, database cutoff and MVCC visibility snapshot, fixed
  maximum document ID, initial total, page size and last `(upload_time, id)`
  key. Snapshot membership uses both PostgreSQL tuple visibility and the latest
  database-owned report-identity revision at that cutoff. Consequently, an
  insert that allocated an ID before page one but committed afterward, as well
  as a pre-existing document transferred into the tenant later, is excluded.
  Continuations preserve
  `upload_time DESC NULLS LAST, id DESC`, exclude later inserts, tolerate
  deletions without shifting rows, and reject token tampering, cross-tenant
  replay, page-size changes and cursor/offset mixing. Cursor response headers
  are CORS-exposed. Explicit `offset` remains compatible but is documented as
  best-effort only and is not used for internal complete traversal.
- 2026-09-05: R19 began test-first with the expected missing authority type and
  cursor behavior. The directly affected identity/documents files are
  `55 passed`; the wider stock, Workspace, identity and documents set was
  `99 passed`. After MVCC snapshot hardening, all six directly affected
  identity, documents, cursor/CORS, stock and Workspace files are `106 passed`.
  A 17-file method, identity/migration, documents, stock, Workspace, quant,
  reconciliation, pool and calculation regression set is `332 passed` in
  98.57 seconds after final self-review added a separate-successful-reparse
  ambiguity regression and canonical-base64/oversized-cursor rejection. The
  six directly affected files are `110 passed` in 33.62 seconds.
  Exact canonical closing gates remain pending for the post-review gate.
- 2026-09-05: Strict Terra R20 rejected PostgreSQL tuple visibility as a
  cross-request pagination snapshot: an unrelated UPDATE replaces the visible
  tuple and could omit a retained member. Forward migration `20260904190000`
  introduces a tenant-owned, 15-minute document-list snapshot with at most
  5,000 immutable members. The first request captures membership and immutable
  `(upload_time, document_id)` order in one database statement; the signed v2
  cursor carries only an unguessable snapshot ID and the last server-validated
  ordinal/key. Continuations read persisted membership, preserve the initial
  total, exclude later inserts, and return typed errors for expiry, tampering,
  tenant/page-size mismatch, or a member whose current ownership/source became
  unavailable. Deletion is intentionally detectable because the member's
  document ID is not a foreign key. Expired snapshots are lazily deleted;
  snapshot ownership cascades if a user row is eventually deleted, while FT-02
  account-erasure work must explicitly clear still-retained user tombstones.
- 2026-09-05: R20 also removes document/revision/run-time tie-breakers from
  current Value Line report authority. A unique greatest `report_date` is the
  only active-report winner; distinct documents or identity revisions tied at
  the greatest date fail closed as `actual_conflict_authority_ambiguous`.
  Actual-value conflict ranking applies the same rule (equal values are not a
  value conflict, and duplicate observations within one report slot still
  require a unique canonical `is_current` fact). Active-report and conflict
  readers now share one current visibility gate: the present document must
  still match fact ownership/stock, an authorized upload/Value Line source,
  usable parse state, and reviewed identity. Current authorization rows are
  share-locked for the request transaction, while historical fact/report
  identity remains evaluated independently at the caller's PIT cutoff. Stock,
  document and Research Workspace consumers map ambiguity and source loss to
  generic typed 409 responses without tenant identifiers.
- 2026-09-05: R20 tests-first coverage includes unrelated tuple updates,
  concurrent/uncommitted inserts, ownership loss, expiry and cleanup, snapshot
  bounds, signed cursor isolation, migration round-trip/immutability/cascade,
  same-date 100/120 ambiguity, equal-value non-conflict, older-date tie
  boundaries, and current source/ownership loss. The latest directly affected
  cursor/documents/migration set is `55 passed`. The 21-file method, identity,
  migration, documents, stock, Workspace, quant-audit, reconciliation, pool and
  calculation regression set is `411 passed` in 193.74 seconds. Exact canonical
  closing gates remain pending for the post-review gate.
- 2026-09-05: Strict Terra R21 found five remaining authority and resource
  gaps. Forward migration `20260904200000` starts a DB-owned, append-only
  `metric_fact_currentness_revisions` timeline, freezes its conservative
  observation boundary, and backfills only the state observed at that boundary.
  A request before that boundary fails with typed
  `historical_currentness_unverifiable`; it never projects today's mutable
  `is_current` value into earlier history. The stock, pool, screener, formula,
  valuation, DCF, reconciliation, calculated-metric, Research Workspace, and
  Oracle's Lens fact readers now select the last recorded state at their common
  knowledge cutoff. Currentness flips remain normal `metric_facts` writes, but
  their time, transaction identity, prior edge, and immutable slot snapshot are
  database-owned. Tests cover conservative backfill, demotion/replacement PIT
  replay, direct-history forgery, slot mutation, and an uncommitted concurrent
  demotion.
- 2026-09-05: The R21 schema is intentionally a forward-only 200–240 chain.
  Revision 200 creates the timeline, bounded snapshot fields, exact document
  order index, and same-clock 15-minute snapshot trigger. Revision 210 changes
  timeline ownership deletion to permit only an existing parent fact cascade,
  preserving the previously supported document/fact deletion workflow.
  Revision 220 makes the authority marker and fact slot immutable and persists
  the exact PostgreSQL transaction-visibility snapshot used by cursor-derived
  reads. Revision 230 completes the immutable timeline slot with `as_of_date`,
  which was found missing only after 220 had been applied. Revision 240 removes
  220's overly broad cross-source current-slot unique index: existing canonical
  consumers deliberately retain malformed calculated duplicates so they can
  return typed ambiguity, while the narrower manual, parsed-document, and SEC
  unique contracts remain. These corrections had to be separate because every
  earlier revision had already been applied; no applied migration was edited.
- 2026-09-05: Revision 250 is a final forward compatibility correction after
  240 was already applied. It keeps tenant, stock, metric, source, reference,
  period and as-of slot identity immutable, and keeps parsed-document identity
  immutable, while allowing the established dedupe workflow to relocate a
  manual fact's provenance document (the manual canonical slot never includes
  document ID). Its trigger sorts after the existing stock-lock and Value Line
  lineage guards, so rejected stock/source mutations still honor their earlier
  concurrency and typed-integrity contracts. Revisions 200 through 250 were
  never edited after being applied; each discovered compatibility correction
  was added as a new forward revision.
- 2026-09-05: Document cursor creation now takes a per-user PostgreSQL advisory
  transaction lock, reuses only an unexpired snapshot with the same page limit
  and exact membership/report-date fingerprint, caps each user at eight active
  traversals, retains at most 5,000 members, and deletes at most 16 expired rows
  per request. Capacity and collection overflow are typed 409 outcomes. Cursor
  membership, order, report date, currentness, and active-report authority use
  the initial cutoff plus its MVCC visibility snapshot; later report
  transactions cannot enter a continuation. Other file/page display metadata
  is explicitly current, not historical evidence, and the response advertises
  that scope. The database overwrites caller-supplied past/future cutoff,
  creation, expiry and transaction values from one clock, enforces exactly 15
  minutes, and rejects mutation. Tests cover concurrent first-page reuse,
  different-limit capacity, 5,000-member reuse, post-capture report commit,
  report-date mutation, exact index planning, and all timestamp override forms.
- 2026-09-05: R21 focused verification includes `55 passed` for the
  complete document API file, `42 passed` for the screener/applicability files,
  `15 passed` for ingestion files, and passing currentness plus full isolated
  `190 -> 250 -> 190 -> 250` migration tests. Shared development and the unique
  Alembic head are revision 250. Exact closing gates are green: container build,
  migration upgrade, `2669` backend tests, `233` frontend unit tests, frontend
  lint, production frontend build, and `git diff --check`. Only the pre-existing
  Starlette/httpx and anyio deprecation warnings remain in backend pytest.
- 2026-09-05: Strict Terra R22 identified three remaining boundaries. Ordinary
  current-truth reads now begin with one PostgreSQL statement that returns both
  `clock_timestamp()` and `txid_current_snapshot()` after allocating the
  evaluator's transaction identity. The exact pair is retained across nested
  canonical, currentness, active-report, method-policy, unresolved-SEC,
  screener, formula, valuation, Oracle, Workspace, stock/pool/ticker,
  conflict, document and quant fact reads. Read-your-writes is recognized only
  by equality with `txid_current()`; a writer that commits after capture is
  excluded even when its database timestamp is no later than the cutoff. Tests
  use separate committed PostgreSQL transactions and no clock epsilon.
- 2026-09-05: Forward revision `20260904260000` freezes manual, calculated and
  derived fact content/provenance and rejects false-to-true reactivation or
  direct deletion. A correction remains append-new then demote-old. The only
  narrow content exception is the existing one-way manual privacy tombstone;
  the only provenance relocation is FT-06 manual document relocation.
  Calculated/derived outputs remain immutable and are regenerated after a legal
  parent document cascade. Source-document and report-identity foreign keys now
  make those existing parent cascades the database-owned deletion boundaries;
  the currentness timeline cascades only from the fact as before. Trigger order
  remains after the existing FT-07, Value Line and canonical-slot guards.
- 2026-09-05: Currentness resolution now requires an explicit candidate scope,
  applies stock/metric/user/source/document/period filters before its window,
  and refuses oversized fact, stock, document, metric or tenant input with
  typed `metric_fact_currentness_scope_bound_exceeded`; an absent usable scope
  is typed `metric_fact_currentness_scope_required`. Every production call site
  was AST-audited to provide both its explicit scope and the retained
  transaction-visibility snapshot. Revision 260 adds stock+metric, metric, and
  document currentness indexes; isolated `EXPLAIN` regressions prove each
  representative plan selects the expected index. Focused migration,
  currentness, document-dedupe, quant, method, SEC-publication and amendment
  coverage is `291 passed` with only the existing framework deprecations.
  Shared development and the unique Alembic head are revision 260. Exact
  closing gates are green: container build, migration upgrade, `2681` backend
  tests, `233` frontend unit tests, frontend lint, production frontend build,
  and `git diff --check`. Only the pre-existing Starlette/httpx and anyio
  deprecation warnings remain in backend pytest.
- 2026-09-05: Strict Terra R23 found that R22 bounded only caller-provided
  filter dimensions, not the facts or revision history those filters matched.
  Currentness now first selects at most 1,001 IDs from compact
  `metric_facts`, returns typed overflow at 1,001, and ranks timeline state only
  for the resulting exact IDs. Legitimately large stock-set consumers traverse
  complete results with indexed keyset pages and fact/currentness chunks of at
  most 1,000 while reusing one `EvaluationSnapshot`; no prefix is returned as a
  complete result. Tenant/source filters are pushed into candidate selection.
  Forward revision `20260904280000` adds `(stock_id,id)`, `(metric_key,id)`,
  and `(source_document_id,id)` candidate indexes. Isolated `EXPLAIN` tests
  prove the three candidate plans use those indexes; 1,001-stock valuation and
  201-revision history-inflation regressions prove complete traversal and
  exact-ID-only timeline ranking. API-sized reads return typed 409 overflow
  instead of silently truncating.
- 2026-09-05: Source reconciliation now requires one explicit
  `EvaluationSnapshot` for every database-backed call. Seed materialization,
  same-slot competitors, transitive lineage, currentness state, and unresolved
  SEC availability all reuse its cutoff and transaction-visibility snapshot.
  Currentness is projected exclusively from the retained timeline; mutable
  live `is_current` and demotion-advanced `updated_at` are not PIT authority.
  Separate-transaction regressions cover a fact committed after the stock
  reconciliation GET boundary and a Piotroski input demoted after capture.
  Formula, screener, stock facts, pool, Workspace, DCF, ratio and Oracle
  consumers pass the captured snapshot through the shared source guard.
- 2026-09-05: Forward revision `20260904270000` makes the manual-reason privacy
  tombstone strictly one-way without changing applied revision 260. An
  unredacted user-authored `value_json.reason` may become `[redacted]` exactly
  once with its valid SHA-256 content hash; an existing tombstone permits only
  a byte-for-byte no-op, so replacing hash A with hash B is rejected. Account
  erasure applies that audited path to both numeric and unavailable manual
  facts, includes the erased text in the account digest, and leaves numeric
  economics and all other provenance unchanged. Mixed reason/no-reason tests
  prove complete account erasure without leakage or fact rewriting; downgrade
  refuses to weaken a retained tombstone.
- 2026-09-05: Because manual corrections also carry a user-authored `note`,
  applied revision 270 was left unchanged and forward revision
  `20260904290000` extends the same single-transition rule to both rationale
  fields. Account erasure hashes and tombstones `reason` and `note` together.
  The manual `raw`/`value_text` payload and numeric value remain the economic
  observation, and server provenance remains immutable. Once either rationale
  hash exists, any later content or hash change is rejected; only an exact JSON
  no-op remains legal.
- 2026-09-05: R23 tests-first focused reconciliation/currentness/privacy set is
  `58 passed`; the first 380-test affected run exposed eight compatibility or
  deterministic-order assertions, all independently reproduced and corrected
  without weakening PIT authority. Shared development was upgraded forward
  from 260 through revision 290.
- 2026-09-05: Piotroski caller/sibling projection and every manifest input now
  use the same explicit `EvaluationSnapshot` and exact-ID currentness timeline.
  Mutable `is_current`/`updated_at` fields are excluded from the immutable
  caller projection. A derived replacement or input demotion committed after
  capture does not change the retained decision; a fresh snapshot sees the new
  state. The production stock, pool, formula, screener, DCF, Workspace and
  Oracle method-gate paths explicitly pass their already-captured snapshot.
  The focused Piotroski/source suite is `97 passed`.
- 2026-09-05: The final read-side `MetricFact.is_current` audit found two
  legacy reads outside reconciliation: document review ranking and repeat
  manual-correction eligibility. Both now use a compact document/exact-fact
  timeline scope. Remaining occurrences are currentness-revision authority,
  writer-side demotions/inserts, or write-response serialization. The focused
  document/source suite is `72 passed`.
- 2026-09-05: Revision 290's intentionally conservative first implementation
  froze all rationale once either hash existed. Forward revision
  `20260904300000` narrows this to the correct per-field rule: plaintext
  `reason` and `note` may each make one independently hashed transition, while
  every already-redacted value/hash remains immutable. This lets account
  erasure complete for a mixed legacy row whose reason was already redacted but
  note was not. Downgrade refuses to weaken retained note tombstones. The
  isolated migration/account suite is `8 passed`; shared development and the
  sole head are revision 300. The final 21-file affected suite is `367 passed`
  with only the existing framework deprecations.
- 2026-09-05: The post-R23 exact container build, forward migration to the sole
  revision-300 head, `233` frontend unit tests, frontend lint, production
  frontend build, and `git diff --check` are green. Two exact backend-suite
  attempts could not establish a valid closing-gate result because the host,
  API container, and PostgreSQL wall clock moved backward while pytest was
  running. The first attempt completed with `2635 passed, 58 failed`; every
  failure was the intended conservative
  `HistoricalCurrentnessUnverifiableError` after the now-earlier clock crossed
  behind the test schema's authority marker. The second attempt reached about
  90 percent with no failures before the same system-wide rollback and was
  stopped after the identical fail-closed cascade began. Targeted and affected
  suites remain green; PIT authority was not relaxed to mask this environment
  fault. A stable-clock CI run is therefore still required for the exact
  backend closing gate.
- 2026-09-05: Final one-way audit found that revision 300 correctly froze an
  already-redacted rationale/hash pair but an initially inserted legacy row
  containing hash A and plaintext could still replace it with hash B while
  making its first text-to-redacted transition. A red test reproduced both the
  reason and note variants. Because revision 300 was already applied, forward
  revision `20260904310000` adds a separate per-field guard: once that field's
  hash exists, its text/hash pair is immutable, while the other rationale field
  may still make its own independent legal transition. Downgrade refuses when
  it would weaken a retained pre-hashed plaintext row. The migration/account
  suite is now `10 passed`; shared development and the sole head are revision
  310. The eight directly modified backend test files are `150 passed` after
  this final migration. No migration at or below revision 300 was edited after
  application. The exact backend full-suite gate remains the stable-clock CI
  requirement described immediately above; it is not recorded as green.
- 2026-09-05: Terra R24 identified four remaining fail-open boundaries. The
  remediation is tests-first and forward-only at revision `20260904320000`;
  no applied revision at or below 310 was edited. Parsed ingestion now treats
  the immutable report-identity revision as its current-slot uniqueness
  boundary. Within one exact identity a reparse has one current append; equal
  observations from separate identities collapse to one deterministic current
  projection; materially different observations at the same highest report
  date retain one current representative per canonical value so reconciliation
  returns typed `ambiguous_current_duplicate` instead of inventing an ID-based
  winner. Older report dates remain superseded.
- 2026-09-05: Metric-fact candidate and keyset queries now prove fact creation
  visibility before `LIMIT` using the database-owned initial currentness
  revision `(known_at, created_txid)` and the caller's exact
  `EvaluationSnapshot`. Caller-controlled `created_at` is never visibility
  authority. Regressions cover direct 1,001-row post-cutoff inflation with
  backdated timestamps, 1,001-stock keyset traversal, current-transaction
  read-your-writes, and revision-history inflation.
- 2026-09-05: Revision 320 adds a narrow account-erasure transition for legacy
  manual rationale that already has a retained hash but still contains
  plaintext. PostgreSQL keeps the hash immutable and verifies it against the
  plaintext. A mismatch does not strand the user's deletion request: the text
  is still tombstoned, the original hash is preserved, and a database-owned,
  append-only `retained_hash_mismatch` anomaly is recorded. Hash replacement,
  economic/provenance mutation, direct anomaly forgery, and plaintext recovery
  remain forbidden. The real account endpoint reports the anomaly count and a
  mixed matching/mismatching integration test proves one-transaction erasure.
- 2026-09-05: `HistoricalCurrentnessUnverifiableError` now has one application
  wide HTTP 409 contract and explicit precedence before generic `ValueError` or
  `Exception` handling in source reconciliation, stock facts, screener,
  Oracle's Lens, upload and reparse routes. The initial R24 focused set is
  `9 passed`; the ingestion/currentness/reconciliation/account/migration
  affected set is `89 passed`, plus the 1,001-stock keyset and migration
  round-trip pair at `2 passed`. Shared development is forward-upgraded to the
  sole revision-320 head.
- 2026-09-05: The final R21-R24 migration combination is `23 passed`, and the
  directly affected R24 currentness, ingestion, reconciliation, erasure and
  migration suite is `72 passed`. The exact canonical closing gate is green:
  container rebuild; upgrade to the sole revision-320 head; backend
  `2707 passed`; frontend `233 passed`; frontend lint; and the production
  frontend build. `git diff --check` is recorded at the final commit gate.
- 2026-09-05: Terra R25 found that the R24 transaction-local GUC was a
  caller-controlled privacy bypass, that FT-07's valuation guard blocked the
  legitimate account-erasure transition, and that the actual-conflict reader
  did not carry its captured candidate universe into every later statement.
  Forward-only revision `20260904330000` leaves all applied revisions through
  320 untouched. It records one database-stamped privacy operation per
  transaction, bound to one target user and one purpose. The live FT-07,
  governed-fact, pre-hash, anomaly and append-only guards authorize from that
  row; none reads `valuepilot.account_erasure`. Numeric and unavailable manual
  `val.fair_value` rows may tombstone only plaintext `reason` and `note`, each
  with its one-way hash. Numeric/text values, raw observation, valuation origin,
  source linkage, slot identity and all remaining JSON stay byte-for-byte
  unchanged; recovery, hash replacement and other fact mutations are rejected.
- 2026-09-05: The database authorization boundary reflects today's deployment
  topology rather than claiming a role split that does not exist. Local/shared
  infrastructure supplies one non-superuser `valuepilot` role which is both
  migration/table owner and runtime role and cannot create roles. The
  application therefore proves possession of an HMAC capability derived from
  `SECRET_KEY`; PostgreSQL retains only its SHA-256 verifier, then creates the
  target/kind/current-transaction operation under a locked, guarded
  `SECURITY DEFINER` function. A session with only the database credential
  cannot authorize via `SET`, direct operation-row DML or a direct function
  call without that application capability, and an authorized transaction
  cannot retarget another tenant or purpose. A principal with the shared DB
  owner's DDL authority can replace functions or disable triggers and is
  explicitly outside this repository-enforceable boundary. Defending against
  that principal requires infrastructure administrators to provision separate
  owner/migrator and runtime login roles, change deployment database URLs, and
  grant the runtime only normal application DML plus EXECUTE on the erasure
  function; no external infra or production secret was changed in this PR.
  `SECRET_KEY` rotation must coordinate a forward verifier rotation before the
  application cutover, or privacy erasure will fail closed.
- 2026-09-05: Actual-conflict identity, unverifiable-authority, source-document,
  availability and observation queries now all share the exact
  `MetricFact.id IN (captured fact_ids)` predicate. The empty candidate set
  returns immediately. A real two-connection READ COMMITTED regression proves
  a pre-cutoff write committed after snapshot T cannot enter later statements,
  while a fresh snapshot and same-transaction read-your-writes see the expected
  conflicts. The initial R25 migration/account/research/conflict affected suite
  is `138 passed`.
- 2026-09-05: The first exact R25 backend closing run found two compatibility
  failures after `2708 passed`: the shared append-only trigger referenced
  `OLD.user_id` when invoked for a 13F representativeness row whose table has no
  such column. The function now projects generic trigger records through
  `to_jsonb` and reads journal-only fields solely in the exact
  `position_journal_events` erasure predicate. Other append-only tables again
  fail with the intended typed append-only rejection. The focused retry is
  `5 passed`; shared development completed `330 -> 320 -> 330`, and remains at
  the sole revision-330 head.
- 2026-09-05: The final exact canonical closing gate is green: container
  rebuild; forward migration to revision 330; backend `2710 passed`; frontend
  `233 passed`; frontend lint; production frontend build; and
  `git diff --check`. Only the pre-existing Starlette/httpx and anyio
  deprecation warnings remain in backend pytest.
