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
