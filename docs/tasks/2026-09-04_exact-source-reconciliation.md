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
- Exact replay is identified by policy version, mapping-spec digest, requesting
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
   mapping/source authority. Value Line facts require an owned, parsed,
   stock-matched document. Manual and calculated facts require the requesting
   owner; calculated facts require bounded exact input lineage.
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
