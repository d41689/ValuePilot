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
