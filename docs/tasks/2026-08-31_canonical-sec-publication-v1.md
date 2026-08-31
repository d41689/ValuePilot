# Canonical Financial Truth — SEC Publication V1

Status: contract approved; implementation not started

Owner: Product / Engineering

Date: 2026-08-31

## Goal

Publish a deliberately small set of SEC as-filed financial actuals into the
existing canonical `metric_facts` contract with exact, point-in-time provenance.
The product must make missing, conflicting, dimensioned, unsupported, or
incomparable evidence visible rather than manufacture a clean history.

This work advances the product north star by giving a serious long-term
investor source-traceable inputs for business quality and normalized owner
earnings while withholding conclusions that the evidence, source policy, or
industry method does not support. It does not author an investment decision.

## Product jobs advanced

1. **Circle of competence:** typed coverage, currency, period, and method gaps
   show what the investor still cannot responsibly understand.
2. **Business quality:** canonical revenue, profitability, balance-sheet,
   dilution, and cash-flow actuals provide an auditable operating history.
3. **Normalized owner earnings:** CFO, capex, SBC, debt, cash, and diluted-share
   inputs are distinguished from estimates and retain exact source lineage.
4. **Margin of safety:** unsupported methods and incomparable inputs block
   dependent valuation instead of producing false precision.
5. **Disconfirmation:** amendments, conflicts, rejected mappings, and missing
   periods remain visible evidence rather than being silently overwritten.
6. **Thesis monitoring:** knowledge time, mapping version, and supersession make
   later changes explainable without rewriting what was knowable before.

Success is observed when every requested gold-set issuer/year/metric is either
an idempotent canonical SEC fact or a bounded typed disposition, and every
published value can be traced to its filing, parse run, raw fact or exact
derived inputs, mapping version, and knowledge time.

## Scope

### In

- Close the FT-03 dependencies needed for publication:
  - resumable, bounded historical-submissions traversal for JPM and GS;
  - retained standalone XBRL instance documents and a versioned parser path for
    pre-inline-XBRL history.
- The approved `sec-us-gaap-v1` mapping in
  `docs/metric_facts_mapping_spec.yml`, including currency, period, dimensions,
  conflicts, and derived-quarter semantics.
- Append-only SEC publication decisions, ordered exact parse-authority sets and
  exact input lineage; canonical shared `metric_facts` publication with
  per-period current-slot behavior.
- Point-in-time selection, amendments, parser/mapping supersession, atomic
  publication, crash recovery, concurrency control, and exact replay.
- Canonical authenticated product reads of published SEC facts and their
  permitted evidence metadata; no raw-XBRL product read path.
- A reviewed industry-method gate that blocks unsupported Owner Earnings,
  ROIC, per-share trends, formula/screener mixing, and system valuation. The
  gate does not invent new industry formulas.
- A new isolated gold-set acquisition/reparse/publication evidence package and
  an immediate idempotency pass.

### Out

- FT-05 corporate-action, ADR-ratio, translation, and full historical
  comparability; non-comparable series remain typed unavailable.
- FT-06 SEC/Value Line reconciliation or source precedence. Until FT-06, no
  consumer may silently mix or choose between those sources.
- New Owner Earnings, ROIC, bank, insurer, REIT, cyclical, commodity, or
  valuation formulas; FT-09 valuation UX; AI investment conclusions.
- Foreign exchange conversion. A valid source-reported ISO-4217 currency is
  retained; it is never relabeled USD.
- Market-price provider work, trading rails, broker actions, or order routing.
- Any 13F acquisition, replay, mutation, or scheduler change.

## Dependencies and constraints

- Metric semantics are owned only by
  `docs/metric_facts_mapping_spec.yml`; publication storage/API behavior is
  owned by PRD §H; source permission is owned by
  `docs/architecture/coverage-source-policy.md`.
- `metric_facts` remains the only product-queryable fundamentals truth. Raw SEC
  tables and publication-decision tables are lineage/review inputs.
- `is_current` remains per period and source. No global deduplication is valid.
- The locked 24-case manifest and its denominator cannot be edited to remove a
  failure. A foreign filing regime is not an economic-method classification.
- The retained Step-D database proves FT-03 and has zero `metric_facts`; it is
  not mutated into FT-04 evidence. Publication acceptance starts from a new,
  empty, preflight-validated database and isolated storage.
- Shared development PostgreSQL contains an orphan migration from unmerged PR
  #128. It is not a valid migration or acceptance target for this branch.
- The development 13F hot-reload repeat-work defect is handled in a separate
  PR. This task only disables all 13F workers, schedulers, and seeds in isolated
  SEC acceptance environments.

## Delivery sequence and small commits

1. **Approve contracts.** Update this task, mapping spec, PRD, source policy,
   backlog progress, and focused contract tests. No production implementation.
2. **Complete publication-grade raw lineage.** Add validated historical cursor
   continuation, retain standalone XBRL instances, and append parser-v2 runs.
3. **Add publication and method-gate schema.** Add version registry, runs,
   ordered run-source lineage, publication decisions and exact derived inputs;
   directly migrate `metric_facts.value_numeric` to `NUMERIC(38,12)` and
   `user_id` to nullable with source ownership checks; enforce reciprocal SEC
   publication references, the SEC-only partial current-slot constraint, and
   reviewed effective/knowledge-dated method classification.
4. **Implement the pure mapping engine.** Normalize exact decimals, units,
   currency, periods, dimensions, duplicates/conflicts, and derived quarters
   into published or typed-unresolved candidates.
5. **Implement PIT-safe publication.** Publish only finalized verified lineage,
   atomically reconcile the same SEC period slot, recover safely, and prove
   concurrency and replay idempotency.
6. **Expose canonical facts and enforce gates.** Extend shared visibility and
   evidence resolution without raw-table/storage disclosure; block silent
   cross-source mixing and unsupported analytical methods.
7. **Run locked acceptance and close.** Acquire/reparse/publish in a fresh
   isolated environment, run pass two, audit every denominator and lineage
   invariant, run the canonical Docker gate, and complete adversarial review.

Each implementation step is test-first and committed separately. GPT-5.6 Sol
performs modifications; GPT-5.6 Terra performs a read-only adversarial review
after each step. Accepted findings are fixed and reviewed again until no new
valid issue remains before proceeding.

## Acceptance criteria

- Every product fundamental read uses `metric_facts`; a source guard rejects a
  raw-XBRL consumer or local storage-path disclosure.
- Every SEC fact is shared/public-source (`source_type='sec'`, no user owner),
  points to an exact publication decision rather than a PDF document, and
  exposes accession, form, accepted/known times, raw or derived inputs, parser
  and mapping versions, context, period, unit/currency, fact nature, and locator.
- Namespace URI plus local name—not prefix—selects a mapping. Unknown/custom,
  dimensioned, unit/currency/period-invalid, or conflicting candidates produce
  typed unresolved outcomes.
- Taxonomy authority is the mapping version's persisted exact-URI allowlist,
  not a year-shaped regex. Concept priority validates one group at a time;
  same-priority conflicts never fall through, while every skipped lower raw
  candidate receives a bounded audit decision.
- Instant, FY, discrete-quarter, YTD, 52/53-week, direct-quarter, YTD-derived,
  and FY-minus-nine-month cases pass. A `6-K` is never assumed to be a 10-Q.
- Every run has an immutable ordered exact source set; Q4 derivation may cross
  its selected annual and quarterly parse authorities, but all operands meet
  the same stock/metric/fiscal-cycle/unit/currency/context/cutoff contract.
- Valid ISO-4217 reporting currencies are preserved in normalized source units;
  raw numerator/denominator QName shape is validated without trusting prefixes,
  target units belong to the global enum, and V1 replay uses only the pinned
  ordered `[DKK, EUR, TWD, USD]` list and digest regardless of external-library
  drift. No FX conversion or USD inference occurs.
- Amendments and newer parser/mapping versions become eligible only after their
  own knowledge/effective boundary. Amendment effects are slot-level;
  nonfinancial amendments preserve original slots, while parse failures and
  mapped conflicts return typed unavailable rather than stale originals.
- Exact replay produces zero new facts/decisions and the same current slots.
  Concurrent publication cannot create two current SEC facts for one period.
- FT-06 absence never becomes implicit source precedence. Mixed-source formula,
  screener, ratio, Piotroski, or valuation inputs fail closed.
- Raw actual publication is not blocked by company class, but every dependent
  analytical output has an approved method/version/classification or returns
  typed `unsupported`. User-authored valuation remains distinct and permitted.
- The locked gold-set report accounts for every expected fiscal year and every
  V1 metric with `published` or a reviewed typed disposition. It does not hide
  JPM/GS continuation gaps or pre-inline-XBRL limitations.

## Test and acceptance plan

### Focused iteration

- Contract/YAML tests validate versions, exact persisted namespace URI
  allowlists (including plausible but unlisted rejection), unique
  concept/metric identities, the five concept-priority paths, non-equivalent
  concept isolation, pinned currency-list digest and external-list drift,
  unit/currency rules, form-first period truth tables, derived-operand
  compatibility, consumer gates, and PRD/source-policy invariants.
- Parser fixtures include inline XBRL and retained standalone instance XBRL,
  malformed units/contexts, dimensions, nils, custom concepts, and duplicate
  and conflicting observations.
- Migration tests start from an empty database, upgrade/downgrade/upgrade the
  new revision, preserve safe legacy and EUR-per-share values, reject downgrade
  when SEC facts or precision-sensitive Numerics exist, and attempt raw-SQL
  owner-nullability, reciprocal source-ref, ordered-source, lineage, timestamp,
  SEC partial-current-slot, mutation, and mapping-version forgeries without
  changing non-SEC current-slot behavior.
- Service tests cover atomic rollback, concurrent publishers, exact replay,
  mapping changes, parser changes, original-to-amendment replacement,
  nonfinancial amendment no-op, late-known amendment PIT, amendment
  parse/conflict fail-closed behavior, retained-file corruption, and
  failure/crash recovery.
- API tests cover authenticated public visibility, cross-user behavior,
  provenance, typed unresolved states, source conflict, and absence of raw
  content/internal storage paths.
- Method tests cover every manifest stratum and reject ordinary-company logic
  for banks, insurers, and REITs. Foreign filing regime remains orthogonal to
  reviewed economic classification.

### Locked gold set

- Use a new run-derived acceptance database and storage directory on authorized
  shared PostgreSQL; run the common safety preflight before every operation.
- Disable 13F, notification, seed, and unrelated mutation-capable workers.
- Use only the configured singleton Rate Guard; never use fallback/direct SEC.
- Run all 24 cases sequentially through bounded history continuation, parser v2,
  publication pass 1, and an immediate pass 2.
- Report issuer/year/metric outcomes, raw and publication lineage counts,
  current-slot duplicates, mapping/method versions, PIT boundaries, typed gaps,
  retained-file integrity, request counters, and zero second-pass deltas.

### Closing gate

Run the canonical commands verbatim and in order:

1. `docker compose up -d --build`
2. `docker compose exec -T api alembic upgrade head`
3. `docker compose exec -T api pytest -q`
4. `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
5. `docker compose exec -T web npm run lint`
6. `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`
7. `git diff --check`

## Sign-off trail

- 2026-08-31: delivery step 2 implemented test-first. Historical traversal now
  emits a random UUID backed by append-only database authority bound to the
  retained main-submissions snapshot/SHA, reviewed identity/CIK, cutoff, full
  history target, exact validated reference ordering and next index. Continuation
  rereads and integrity-verifies retained bytes rather than trusting a changed
  current SEC main payload; random, mismatched and corrupt cursor authority is a
  typed acquisition failure and never `no_eligible_filings`. Parser
  `xbrl-lineage-v2` retains the existing exact-input atomic lineage while adding
  standalone XBRL instance parsing and structured numerator/denominator QName
  authority. Existing v1 runs/failures remain append-only. Focused Docker and
  migration round-trip verification passed: the migration suite was 11 passed;
  the focused lineage/history/CLI/gold/contract suite was 179 passed; and
  `git diff --check` passed. The only warning was the pre-existing Starlette
  `httpx` deprecation.
- 2026-08-31: first implementation review findings were accepted. The lossy
  downgrade now refuses retained parser-v2 QName evidence; continuation and raw
  structured-unit authority have insert/append-only/no-TRUNCATE database guards;
  primary standalone instances and non-primary instances share parser-v2's
  generic `no_xbrl_facts` failure; standalone XML parsing uses element in-scope
  namespaces and rejects duplicate/unknown/malformed context, unit, QName,
  divide and dimension authority.
- 2026-08-31: post-review focused Docker suites passed 196 tests, including the
  isolated migration round trip, retained-v2-evidence downgrade refusal/value
  preservation, persisted continuation/no-current-main-read behavior, XML
  namespace rebinding and malformed-authority traps. `git diff --check` passed;
  the only warning remained the pre-existing Starlette `httpx` deprecation.
- 2026-08-31: second implementation review hardened the same step further.
  Downgrade now locks both evidence tables before observing them; cursor
  validation has its own durable terminal failure/result rather than a main-
  submissions outage; every scanned page records an immutable operation-owned
  consumption claim used by the database to authorize child continuation;
  inline v2 QName resolution is element-scope aware; and structured explicit/
  typed dimensions are persisted with QName authority and typed-content hash.
- 2026-08-31: second-review focused Docker verification passed 197 tests plus
  the isolated 12-test migration suite; `git diff --check` passed. The only
  warning remained the pre-existing Starlette `httpx` deprecation.
- 2026-08-31: downgrade race verification now uses a real pending writer on an
  independent isolated-database connection and a concurrent Alembic process;
  downgrade waits, observes the committed claim, refuses, and preserves both
  head and evidence. Raw-SQL child-without-claim and forged claim/reference
  attacks are also rejected by the database continuation guard.
- 2026-08-31: final continuation attack coverage proves that a finalized
  foreign operation cannot authorize a child, a child's index cannot differ
  from its immutable claim end, and two independent transactions racing to
  advance the same parent serialize so exactly one commits. The winning child
  remains addressable by its stable random authority ID for exact replay. The
  final SEC financial focused Docker suite passed 155 tests, the explicit
  continuation attack test passed independently, and `git diff --check`
  passed; the only warning was the pre-existing Starlette `httpx` deprecation.
- 2026-08-31: third review replaced free claim assertions with database-
  verified evidence. Claims are database-stamped, operation-transaction owned,
  parent/cutoff/target bounded, and each ordered reference/outcome must resolve
  to that operation's retained historical snapshot or acquisition failure.
  Continuation failures and their operation results are reciprocal and
  transaction/identity/cursor guarded. Typed dimensions now retain a bounded
  namespace-aware element/attribute/text/tail tree plus canonical serialization
  and a database-recomputed SHA-256; strict JSON shapes and duplicate axes fail
  closed. Focused Docker verification passed 157 tests before the final raw-SQL
  reciprocal-result additions; those targeted continuation/typed-dimension
  tests subsequently passed 3 tests. Exact retry of the same parent cursor now
  proves its attempt from the operation-to-snapshot junction (including reused
  immutable content) and remains idempotent; the retry plus real downgrade race
  passed together in a final 2-test run and `git diff --check` passed.
- 2026-08-31: fourth review removed BeautifulSoup as typed-dimension authority
  for parser v2 inline filings. Typed contexts are now parsed from the retained
  XHTML bytes with namespace-aware XML events and rejoined to tolerant HTML
  facts by exact context ID; malformed or ambiguous XHTML fails closed while
  parser v1 remains tolerant. The canonical tree preserves case, namespaced
  attributes, local prefix rebinding, and mixed text/child/tail order. Parser
  construction enforces global node/attribute/text/depth budgets, and the DB
  checks the whole JSONB storage size and recursive object count before its
  strict recursive validator. The final focused Docker suite passed 159 tests,
  including the 13 isolated migration/real-race tests; `git diff --check`
  passed and only the pre-existing Starlette warning remained.
- 2026-08-31: fifth review made the raw XML event stream the complete parser-v2
  structural selector. Protected XBRLI, XBRLDI and authorized 2013/2020 inline
  elements require exact namespace URI plus local name; facts are reconciled to
  HTML locators by ordered ID, expanded taxonomy QName, context and unit
  signature, so a tolerant HTML-only or fake-namespace fact cannot enter v2.
  Custom taxonomy concepts retain their raw lexical name and namespace for
  later unresolved publication handling. DTD/DOCTYPE/entity declarations are
  rejected before parsing. The full XML event loop applies element, namespace,
  attribute, text, depth and byte budgets immediately, clears completed nodes,
  and retains only bounded typed-member subtrees. Focused Docker verification
  passed 167 tests, including isolated migration and the real downgrade race;
  `git diff --check` passed with only the existing Starlette warning.
- 2026-08-31: sixth review removed every service `ET.fromstring` dispatch and
  introduced one shared safe expanded-root detector. It rejects encoding-aware
  DTD/DOCTYPE/entity declarations before XML parsing, then enforces whole-file
  byte/event/namespace/attribute/text/depth budgets while clearing completed
  elements. Service primary/candidate dispatch and direct standalone parsing
  now use this preflight; a bounded second standalone pass is permitted only
  after it succeeds. Standalone dimensions require exact XBRLDI URI/local
  identity. Inline strict protection now systematically covers scenario,
  segment, forever, all period/unit/divide members, XBRLDI dimensions and IX
  structures, with a parameterized foreign-URI trap for every protected local.
  Focused Docker verification passed 193 tests, including isolated migration
  and the real downgrade race; `git diff --check` passed with only the existing
  Starlette warning.
- 2026-08-31: seventh review bound standalone selection to a frozen verified
  artifact/content/root authority. Candidate and primary parsing consume those
  exact bytes, and a final storage-integrity read before run creation rejects
  replacement or corruption without publishing a run or facts. XML declaration
  rejection now uses Expat token callbacks rather than lexical regex: actual
  doctype, internal/external entity declarations and external references abort
  before expansion, while identical text in comments, CDATA and processing
  instructions remains legal. UTF-8/16/32 BOM inputs are covered. The focused
  suite reached 198 passing tests before one expected typed error-name assertion
  was updated; that assertion and the real race then passed together, and
  `git diff --check` passed. The only warning remained Starlette's existing
  httpx deprecation.
- 2026-08-31: eighth review made safe XML preflight return both the expanded
  root and the exact bytes all downstream authority parsers must consume.
  UTF-8 and UTF-16 LE/BE remain original; UTF-32 LE/BE is strictly decoded and
  only the XML-declaration token's encoding value is normalized before UTF-8
  parsing, without rewriting comments or processing instructions. BOM,
  directional encoding and declaration contradictions fail closed. Legal root,
  standalone XBRL and inline XHTML fixtures cover UTF-8/16/32 declarations.
  The full focused run reached 201 passes with five stale expected error-name
  assertions; after updating those assertions, all 12 affected encoding/safety
  tests and the real pending-writer race passed, and `git diff --check` passed.
- 2026-08-31: ninth review removed the public standalone preflight-skip flag
  and every caller-controlled bypass. Direct, primary and fallback standalone
  parsing now always executes safe XML preflight again on its downstream bytes;
  normalized UTF-32 and original UTF-8/16 remain valid while DTD/entity and
  whole-document resource attacks cannot opt out. Repository backend search
  contains no former skip-token reference. The complete focused Docker suite,
  including isolated migration and the real race, passed 208 tests with the
  single pre-existing Starlette warning; `git diff --check` passed.

- 2026-08-31: contract step approved. Production implementation, migrations,
  live acquisition, and publication remain incomplete.
- 2026-08-31: initial focused read-only contract suites passed before
  adversarial review. Review then required stricter taxonomy authority,
  semantic isolation, multi-source publication, form-first periods, exact
  numerics and amendment behavior; final verification is recorded only after
  those accepted findings pass the revised suite. No database migration, SEC
  request, production code, commit, or acceptance-storage mutation occurred.
- 2026-08-31: all accepted contract-review findings were incorporated. The
  revised Docker contract/mapping/taxonomy/Watchlist suites passed 18 tests;
  `git diff --check` passed. The only warning was the pre-existing Starlette
  `httpx` deprecation. Implementation remains unstarted.
- 2026-08-31: second-round findings added exact raw-unit QName shapes,
  adjacent-quarter time identities, canonical global unit enums, guarded
  NUMERIC downgrade cases, and the observed US-GAAP/DEI namespace variants.
  The revised Docker suites passed 19 tests and `git diff --check` passed; the
  same pre-existing Starlette warning remains. Implementation remains unstarted.
- 2026-08-31: third-round findings replaced taxonomy patterns with evidence-
  locked exact URI registries, defined the grouped concept-priority pipeline,
  and pinned the ordered gold-set currency list plus canonical digest. The
  revised Docker suites passed 20 tests and `git diff --check` passed; the same
  pre-existing Starlette warning remains. Implementation remains unstarted.
