# FT-06 exact source reconciliation

Status: in progress

Issue: #135

## Goal and product value

Make source disagreement visible before a fundamental fact can influence a
screen, formula, or research decision. This advances the north-star jobs to
reconstruct trustworthy owner economics and disconfirm before deciding: the
user can see whether SEC as-filed actuals, Value Line adjusted
actuals/estimates, manual corrections, and deterministic derived facts are
actually comparable, without ValuePilot silently choosing whichever row was
loaded last.

Success is observable when an authenticated user receives a deterministic,
source-traceable comparison report and every affected consumer fails closed on
an unresolved comparison even when a caller names one of the competing source
types.

## Authority and design decisions

- `docs/metric_facts_mapping_spec.yml` owns the versioned reconciliation
  semantics: source roles, comparison identity, typed outcomes, tolerances, and
  the fact attributes that must align before variance is calculated.
- PRD §H.10 owns service/API behavior and consumer failure behavior. The
  coverage-source policy continues to own acquisition and source permission.
- `metric_facts` remains the only product-queryable fundamentals store. The
  reconciliation result is a deterministic comparison/audit projection over
  exact fact IDs; it does not copy values into a new fact table or select a
  winning source.
- Exact replay is identified by policy version, resolved mapping-policy digest, requesting
  user, stock, knowledge cutoff, source-authorization state, and the ordered
  eligible fact IDs/versions. The report exposes this identity and its digest.
- A source-specific consumer selection remains explicit. Reconciliation never
  invents a global SEC/Value Line/manual/calculated precedence. Naming a source
  does not bypass an unresolved or mapping-conflict state in the same canonical
  comparison slot.
- Current non-SEC facts are eligible only when their database knowledge
  timestamps and visible source authority are at or before the cutoff. A
  historical projection that cannot prove source-current state at the cutoff
  returns a typed unavailable state rather than relabeling today's projection.
- The policy outcome vocabulary is `match`,
  `expected_definition_difference`, `restatement`, `mapping_conflict`, and
  `unresolved`. Tolerance may prioritize review and may classify a bounded
  numeric match, but it never chooses or rewrites a fact.
- `match` means definitions and every comparison-identity field aligned and
  the Decimal variance was within review tolerance; it is not source
  precedence. `expected_definition_difference` names a reviewed relationship
  such as SEC as-filed versus Value Line adjusted, actual versus estimate,
  manual correction, or direct versus derived. `restatement` identifies a
  same-source supersession. `mapping_conflict` means comparison identity could
  not be aligned. `unresolved` covers material value disagreement, duplicate
  current facts, unavailable lineage, or missing numeric evidence.
- The concrete guarded consumers are formula execution, screener evaluation,
  Value Line ratio and Piotroski calculation, DCF input assembly, stock summary
  and facts reads, Oracle's Lens quality overlay, stock-pool Piotroski cards and
  comparison, and research workspace reconciliation. A missing optional source
  never blocks a legal single source; only a conflict/unavailable state in a
  relevant slot fails closed. User-authored valuation and original manual
  inputs remain outside system-financial comparison slots.

## Acceptance criteria

1. The mapping and PRD contracts explicitly authorize FT-06 without changing
   market-price authority, valuation methodology, or FT-07 industry/method
   applicability.
2. Comparison identity aligns canonical definition/mapping version, fiscal
   period and duration, dimensions/context, normalized unit and scale, monetary
   currency, fact nature (`actual`, `estimate`, `derived_actual`, `manual`),
   source identity/authorization, effective time, and knowledge cutoff before
   any Decimal variance calculation.
3. The authenticated stock API returns a bounded, deterministic, versioned
   report with exact eligible fact IDs, source roles, typed status/reason,
   variance/tolerance when eligible, cutoff, policy/mapping identity, and no raw
   artifact path, private snippet, or cross-user fact.
4. SEC facts are eligible only through their canonical publication and active
   mapping/source authority. Value Line facts with durable document provenance
   validate an owned, parsed, stock-matched document; a legacy owned parsed row
   without that provenance remains comparison-identity-incomplete and can never
   establish a cross-source match. Manual and calculated facts require the
   requesting owner; calculated facts require bounded exact input lineage.
5. Conflicting SEC and Value Line actuals, actual-versus-estimate, manual
   corrections, and derived facts remain separate roles. Mixed currency, unit,
   dimensions, duration/period, mapping identity, ambiguous duplicate,
   partial/missing, post-cutoff, and revoked/retired authority cases produce a
   typed non-match/unavailable result before variance where applicable.
6. Formula, ratio, Piotroski, screener, research workspace, and canonical fact
   reads cannot use query order, dictionary overwrite, row ID, newest-row, or a
   caller-selected source to bypass an unresolved comparison. Per-period
   `is_current` semantics remain unchanged.
7. Tests cover deterministic replay; exact match; material SEC/Value Line
   conflict; expected definition difference; restatement; actual/estimate;
   manual and derived roles/lineage; mixed currency/unit/dimension/period;
   post-cutoff evidence; retired authority; duplicates; partial/missing;
   authorization; safe serialization; and affected consumer guards.
8. All exact Docker closing gates pass and an independent read-only
   adversarial review finds no valid P0-P3 issue.

## Scope

In scope:

- mapping-spec and PRD FT-06 contracts;
- a shared canonical reconciliation service and typed errors;
- authenticated, bounded stock reconciliation API;
- shared consumer guard integration and source-order regression tests;
- documentation and test evidence.

Out of scope:

- market/current-price authority (FT-01);
- valuation or investing-method formulas;
- economic classification/applicability gates (FT-07/#136);
- a replacement fact store or cross-source current-slot deduplication;
- new SEC/Value Line acquisition, FX conversion, or licensed redistribution;
- evidence retirement/account erasure (#137).

## Expected files

- `docs/metric_facts_mapping_spec.yml`
- `docs/prd/value-pilot-prd-v0.1.md`
- `backend/app/services/canonical_financials.py`
- `backend/app/services/source_reconciliation.py` (new)
- `backend/app/api/v1/endpoints/stocks.py`
- affected formula/screener/calculated/research services only where the shared
  guard must replace a bypass
- focused backend unit/integration and source-guard tests
- this task record and, if needed, `docs/BACKLOG.md` for genuinely deferred
  findings

No migration is planned because FT-06 comparison state is a reproducible audit
projection, not a second persisted financial store. If implementation evidence
shows that durable review state is required, work pauses for a PRD/schema
decision and a tested migration rather than storing JSON opportunistically.

## Test-first plan

1. Contract tests pin the mapping-policy version/digest inputs, exact alignment
   fields, typed statuses, and PRD/API boundary.
2. Service tests first fail for cross-source conflicts, alignment mismatches,
   PIT/authorization failures, duplicates, missing inputs, manual/derived roles,
   safe output, and deterministic ordering/digest.
3. Consumer tests first prove an explicit source selection cannot bypass an
   unresolved comparison and that identical source order permutations do not
   change the decision.
4. API tests prove authentication/ownership, bounds, typed responses, no
   internal paths/snippets, and stable replay.
5. Iterate with focused tests inside Docker, then run the exact repository
   closing gates from `AGENTS.md`.

## Sign-off trail

- 2026-09-04: Fresh branch `codex/source-reconciliation` created from main
  `cf5af9846e6aaf132790b9a9a3a272b00a61925b`; frozen PR #128 was consulted only
  for its stated requirements/file inventory and no code, commit, migration, or
  file was copied.
- 2026-09-04: Tests-first checkpoint established focused service/API red cases
  before the DB projection and consumer guard existed. The implementation
  remains migration-free: reports are computed from `metric_facts` plus
  source-authority lineage. Explicit historical cutoffs over mutable non-SEC
  current state return `partial / historical_current_projection_unverifiable`.
- 2026-09-04: Terra adversarial review R1 found five valid gaps: definition and
  source-mapping identity could be bypassed, fiscal endpoint drift escaped the
  slot, singleton manual/derived lineage was unchecked (including stock-pool
  display), unresolved SEC amendments were absent from the report, and retired
  non-SEC authority was not typed. Sol remediation now persists Value Line
  mapping identity, uses authoritative fiscal identity without inferring a
  quarter ordinal, validates bounded recursive lineage with cycle/cross-stock/
  visibility/cutoff guards, reuses canonical SEC amendment partitioning, emits
  typed retired/revoked exclusions, and returns typed unavailable stock-pool
  states. Original manual inputs/valuations pass through consumer guards
  without entering a system-source comparison slot.
- 2026-09-04: Remediation-focused Docker suite is green: 185 tests covering
  reconciliation, SEC publication integration, mapping generation, all listed
  consumers, document correction lineage, and stock-pool behavior. Full
  closing gates and Terra R2 remain pending.
- 2026-09-04: Terra adversarial review R2 found three additional consumer
  bypasses. Sol remediation now guards the by-ticker Piotroski card and returns
  no partial numbers with typed unavailable state, builds every stock-summary
  field and provenance entry only from the guard-returned fact set at the same
  evaluation cutoff, and fetches the research-workspace bound plus one so a
  truncated prefix is reported `partial / reconciliation_bound_exceeded`
  instead of `complete / clear`. Original manual-input passthrough also now
  respects cutoff and authority state before it can reach a consumer.
- 2026-09-04: Terra adversarial review R3 found three additional PIT/identity
  gaps. Sol remediation now persists only source-authoritative Value Line
  currency and fiscal-year duration semantics (never a guessed period start or
  fixed 365-day duration), treats the policy's `known_at` and `effective_from`
  as prerequisites before candidate materialization, and includes the
  authenticated `requesting_user_id` in the report digest so replay/cache
  identity cannot cross principals. A production-path integration test now
  exercises `MappingSpec` generation through `IngestionService`, persisted
  `MetricFact`, approved SEC publication, and reconciliation with an expected
  as-filed-versus-adjusted difference.
- 2026-09-04: R3 remediation-focused Docker suite is green: 199 tests across
  reconciliation, mapping/ingestion, SEC publication, formula/screener,
  ratio/Piotroski, DCF, stock summary/pool, Oracle's Lens, research workspace,
  and document reparse consumers. A valid in-transaction ingestion edge was
  also pinned: owned documents may authorize facts while `parsing`, and
  successfully parsed partial documents remain usable, while persisted
  `failed` documents remain unavailable. Terra R4 and full closing gates remain
  pending.
- 2026-09-04: Terra adversarial review R4 found four additional authority
  gaps. Sol remediation makes unresolved SEC amendment and same-filing recovery
  state fully cutoff-aware across mapping, run, publication availability,
  audit, parse, filing, and resolution timestamps; wraps every uploaded company
  page in a database savepoint so failed-page extractions, facts, calculated
  writes, and identity mutations cannot survive a later successful page; and
  makes the canonical `/facts` read reconcile each fiscal/as-of slot before it
  emits either published facts or a typed unavailable state.
- 2026-09-04: Value Line `source_mapping_version` is now an immutable canonical
  digest of the fully resolved mapping policy, including both mapping-spec and
  taxonomy semantic inputs. The report exposes that resolved-policy digest, so
  a taxonomy-only semantic revision cannot silently reinterpret old facts under
  the same identity. New red-to-green tests cover taxonomy-only revision,
  failed-page post-write rollback, `/facts` conflict/authority behavior, an SEC
  amendment before its failure becomes known, and a same-filing recovery both
  before and after its PIT resolution cutoff. Terra R5 and exact closing gates
  remain pending.
- 2026-09-04: R4 remediation-focused Docker consumer suite is green at 206
  tests. The amendment/recovery database scenarios and the changed canonical
  facts read also pass their focused regressions. A prior 302-test expansion
  found only the intentionally changed `/facts` expectation; that assertion
  now requires typed fail-closed output and passes. No blocker is deferred.
