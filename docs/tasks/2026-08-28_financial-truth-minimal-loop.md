# Financial Truth Minimal Loop

## Goal

Deliver the next product increment that makes a research case fail closed on
untrustworthy evidence and exposes canonical, source-traceable financial truth
without allowing the system to author an investment decision.

This task advances the product north star by helping the user reconstruct
normalized owner economics from primary evidence, see what is missing or
unsupported, and avoid a margin-of-safety conclusion based on conflicting
prices or an inapplicable method.

## Scope

### In

- FT-02: policy-owned document retirement, authorization loss, lineage, and the
  narrow audited account-erasure exception.
- FT-03: complete the locked beta manifest's approved financial-filing
  acquisition, immutable artifact/raw-fact lineage, and PIT replay evidence.
- FT-04: approved SEC-to-`metric_facts` mapping and idempotent canonical
  publication, preserving per-period `is_current` semantics and full lineage.
- FT-01: one canonical EOD price result across product surfaces, including
  typed fail-closed states.
- FT-10: automatic, idempotent coverage materialization when a case is created
  or reopened.
- FT-07: versioned company/method applicability and typed blocking for
  unsupported analytical methods. This slice establishes the method gate; it
  does not implement FT-09 valuation models.
- FT-15 boundary work that does not require choosing or activating a provider:
  record the authorization/licensing blocker and preserve the existing
  canonical EOD contract. Production provider activation remains outside this
  task unless the user separately approves a provider and its terms.

### Out

- Any 13F discovery, polling, ingestion, backfill, parse, replay, scheduler, or
  Rate Guard operation. Another host owns 13F acquisition continuity.
- FT-05/06 comparability and source reconciliation, FT-08 workspace redesign,
  FT-09 valuation, and FT-11 through FT-14.
- Broker integration, trading rails, investment recommendations, or automated
  human-decision publication.
- Unbounded SEC crawling. SEC work is coverage-directed and limited to the
  locked acceptance manifest.

## Authoritative references

- `AGENTS.md` — product north star, critical data invariants, and closing gate.
- `docs/BACKLOG.md` — FT-01, FT-02, FT-03, FT-04, FT-07, FT-10, FT-15.
- `docs/plans/financial_truth_decision_loop_beta_acceptance.md` — locked
  manifest and trap protocols.
- `docs/architecture/research-decision-support.md` — authority, ownership,
  human decision, PIT, and source visibility.
- `docs/architecture/coverage-source-policy.md` — acquisition and retention.
- `docs/architecture/metric-facts-is-current.md` — per-period current slots.
- `docs/architecture/data-layer.md` — canonical fact and correction rules.
- `docs/metric_facts_mapping_spec.yml` — canonical metric semantics.
- `docs/prd/value-pilot-prd-v0.1.md` — normative product behavior.

## Acceptance criteria

### FT-02

- Ordinary document removal archives/tombstones rather than deleting retained
  artifacts, extraction lineage, or permitted canonical fact lineage.
- Archived content is readable only to an authorized current user; permission
  loss produces `source_unavailable` without copying protected content into
  research history.
- Account erasure applies the PRD's audited redaction exception without
  rewriting shared facts or erasing event identity.
- Archive, projection reconciliation, revocation, cross-user access, erasure,
  and referenced-history tests pass.

### FT-03 / FT-04

- The locked manifest drives bounded financial-form acquisition; no 13F
  operation is invoked.
- Approved SEC actuals publish only through `metric_facts`; no product consumer
  reads raw XBRL as financial truth.
- Publication records raw fact/accession, mapping version, knowledge cutoff,
  fact nature, context, period, dimensions policy, unit, and currency.
- Period logic covers instant/duration, YTD/discrete quarter, fiscal calendars,
  amendments, dimensions, units, and unresolved concepts with typed outcomes.
- Exact replay is idempotent and preserves per-period current slots; PIT traps
  exclude unavailable filings, artifacts, parses, mappings, and revisions.
- Locked-manifest evidence reports make incomplete issuer/form/history coverage
  visible instead of silently shrinking the denominator.

### FT-01

- Every field claiming to be current/latest market price uses the canonical EOD
  result and exposes date, source, currency, freshness, or typed reason.
- Value Line/document prices remain dated references and never substitute.
- Valid, missing, stale, unknown-currency, and unauthorized cross-surface tests
  prove one stock/as-of cannot yield conflicting current prices.
- Dependent discount/margin-of-safety output is absent when price is invalid.

### FT-10

- Creating or reopening a case idempotently materializes authoritative coverage
  requirements without an admin action.
- Case and inbox projections expose source, as-of/freshness, reason, and next
  action for ready, missing, blocked, stale, inaccessible, or unsupported state.
- Ownership and admin aggregates do not leak another user's cases, documents,
  holdings, or requirement details.
- Historical projection remains fail-closed unless reconstructed from PIT-safe
  source state.

### FT-07

- Each affected output records an approved method/version and effective company
  classification, or returns typed `unsupported`.
- Banks, insurers, REITs, ordinary companies, high-SBC/acquisitive businesses,
  and cyclical/commodity businesses have approved evidence requirements or an
  explicit unsupported result.
- An ordinary-company method cannot publish Owner Earnings, ROIC, per-share
  trend, or valuation for a financial, insurer, or REIT.
- Price volatility and beta cannot satisfy permanent-impairment evidence.

### Closing gate

- `docker compose up -d --build`
- `docker compose exec -T api alembic upgrade head`
- `docker compose exec -T api pytest -q`
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
- `docker compose exec -T web npm run lint`
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`
- `git diff --check`
- Repeated adversarial review, preferably with GPT-5.6 Terra, finds no new
  valid issue. Every accepted finding is fixed and re-verified.

## Files expected to change

- Normative PRD/source/mapping documents only where an existing authority must
  define missing behavior.
- SQLAlchemy models and Alembic migrations for durable lifecycle/publication
  state.
- SEC ingestion/publication, market-data, research-case, coverage, and method
  applicability services.
- API schemas/endpoints and product consumers that expose affected contracts.
- Backend/frontend tests and fixed acceptance fixtures.
- `docs/BACKLOG.md` only when an FT item is fully resolved or a discovered
  out-of-scope problem must be recorded.

## Test plan

Tests are written or tightened before production behavior. Iteration uses
targeted in-container pytest/frontend tests; the exact full closing gate above
is mandatory before readiness.

No test or verification step may call SEC 13F ingestion or a 13F scheduler.
Targeted SEC financial-filing live probes, if needed, must be bounded to the
locked financial-filing manifest and use the shared Rate Guard.

## Sign-off trail

- 2026-08-28: scope opened on `codex/financial-truth-minimal-loop`; explicit
  user constraint recorded that this work must not fetch 13F data.
- 2026-08-28: implemented the fail-closed financial-truth foundation for
  document retirement and erasure, SEC publication and PIT lineage, canonical
  EOD consumption, automatic case coverage, and versioned analysis-method
  applicability. Product reads now require database-verifiable exact authority
  for parsed, manual, SEC, and formula facts.
- 2026-08-28: adversarial review found that legacy Piotroski and Value Line
  fixed-method outputs lack protected exact runs, inputs, arithmetic, and
  invalidation. The current slice does not invent that separate authority
  protocol: all canonical product reads hide those legacy rows, and the
  restoration work is recorded as `Trusted fixed-method derived metrics` in
  `docs/BACKLOG.md`.
- 2026-08-28: adversarial review FTR-030 proved that treating every admin-owned
  Value Line upload as shared leaked proprietary facts and report metadata to
  ordinary users. Removed the generic shared-parsed-user bypass from canonical
  fact visibility, active-report selection, actual-conflict selection, stock
  reads, and screening. Admin-owned exact parsed facts now remain private, with
  endpoint and screener attack regressions.
- 2026-08-28: the final rebuild-first closing gate passed after the last review
  remediation: Alembic upgraded to the single `20260828500000` head, backend
  `1603 passed`, frontend `222 passed`, lint had no warnings or errors, the
  production build succeeded, and `git diff --check` passed. The build emitted
  only the already-recorded stale Browserslist data warning.
- 2026-08-28: `coverage-gold-set` observed all 24 locked cases and exited 2 with
  all 24 incomplete. This is the required fail-closed denominator report, not a
  beta-completion claim: the shared database contains no reviewed financial-
  filing identity or eligible pre-cutoff parse for the locked 2026-08-26 PIT
  cycle. The implementation does not backdate newly fetched evidence or shrink
  the manifest to fabricate completion. No SEC or 13F acquisition was invoked
  during this audit.
- 2026-08-28: adversarial review found two document projections that still
  trusted retained pre-rollout parsed rows without exact extraction authority.
  Document comparison and the document-list company projection now require the
  database-owned `parsed_metric_fact_has_exact_authority` predicate. Negative
  quarantine fixtures and authorized positive fixtures pass; no legacy row is
  silently promoted to product evidence.
- 2026-08-28: case evidence admission no longer treats a durable
  `metric_facts.id` as proof of truth. Parsed evidence requires exact extraction
  authority; manual and calculated evidence must pass their protected current
  publication contract; SEC evidence retains its exact public-publication
  checks. Archived exact parsed evidence remains accessible, while legacy
  calculated/manual rows are typed unavailable. Multi-company document
  evidence now derives its stock binding only from an exact parsed projection.
- 2026-08-28: final independent adversarial review with GPT-5.6 Terra returned
  PASS with no new valid P0/P1/P2. The reviewer independently re-ran tenant
  isolation, exact evidence authority, multi-company binding, account erasure,
  reparse/dedupe, coverage/method gates, and SEC lineage/migration paths. No
  network, SEC acquisition, or 13F operation ran during review or closing.
