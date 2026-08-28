# FT-00 / FT-03 — SEC financial-truth foundation

Status: ready for review

Owner: Product / Engineering

Date: 2026-08-27

## Goal

Close FT-00 with a locked, machine-validated 24-issuer beta gold set; authorize
and specify SEC financial-filing acquisition without weakening existing source,
privacy, or canonical-truth boundaries; then deliver the first runnable FT-03
vertical slice from a reviewed stock/CIK identity through SEC discovery,
immutable raw artifact storage, XBRL lineage extraction, and point-in-time
replay.

This slice establishes lineage only. It MUST NOT publish SEC facts into
`metric_facts`; that is FT-04.

## Product value

The work advances the north-star jobs “understand business quality,” “estimate
normalized owner earnings,” “value with a margin of safety,” and “disconfirm
before deciding” by making primary-source financial evidence reproducible and
source-traceable before any calculation is allowed to rely on it.

## Acceptance criteria

### FT-00

- `docs/acceptance/financial_truth_beta_gold_set.yml` contains exactly 24
  distinct economic issuers and satisfies every stratum and cross-cutting
  requirement in the beta acceptance protocol.
- A deterministic validator rejects changed counts, duplicate issuers/listings,
  malformed CIKs, missing identity/filing/currency/history fields, and missing
  approval/cutoff metadata.
- The sample is locked before parser results are observed; failures may not be
  removed or reclassified within the evaluation cycle.

### Source policy and PRD

- `coverage-source-policy.md` explicitly authorizes the approved SEC financial
  forms and defines automation, rate limiting, raw retention, source visibility,
  and revocation behavior.
- The PRD owns issuer identity, filing/artifact/parse-run/raw-fact schemas,
  lifecycle, point-in-time selection, append-only behavior, and the HTML/XBRL
  evidence locator that replaces a fictitious PDF page number.
- Raw XBRL is lineage only. Product fundamentals, screening, formulas, and the
  research workspace continue to read only `metric_facts`.
- No key merely present in the environment activates a commercial market-data
  provider. Alpaca can be added only after its credentials and operator
  authorization are both configured and its EOD semantics are adopted by the
  source policy/PRD.

### FT-03 vertical slice

- A reviewed, effective-dated stock-to-CIK identity is required; low-confidence
  or overlapping active identity cannot auto-link or ingest.
- The service discovers approved financial forms from SEC submissions, including
  amendments, with stable accession, filed/report/accepted times and primary
  document identity.
- Fetches use the existing rate-guarded EDGAR client and construct only approved
  SEC hosts/paths.
- Filing artifacts are stored content-addressably with SHA-256, byte size,
  fetch/knowledge time, MIME/type, source URL, storage key, and a complete
  accession manifest. Replays are idempotent and never overwrite bytes.
- A versioned parse run extracts raw inline-XBRL facts with concept, context,
  unit, period, dimensions, raw value, decimals/scale/nil state, and an
  artifact/HTML locator. Raw facts are append-only and have no product read API.
- Repeating the same input is idempotent; a later parser creates a new parse run
  without deleting history.
- Point-in-time selection excludes identities, filings, artifacts, and parse
  runs not knowable at the requested cutoff. Boundary tests cover post-cutoff
  amendments and parse runs.
- A real SEC probe demonstrates the end-to-end slice for one locked ordinary US
  operating-company case without publishing `metric_facts`.

## Scope

### In

- FT-00 manifest and validation.
- SEC financial-filing policy and PRD contracts.
- SEC issuer identity, filing, artifact, parse-run, raw XBRL fact models and
  migrations.
- Discovery/acquisition/extraction/PIT services and an operator CLI.
- Deterministic fixtures, database-boundary tests, source guards, and one live
  authorized SEC probe.

### Out

- SEC-to-`metric_facts` mapping/publication (FT-04).
- SEC/Value Line reconciliation (FT-06).
- Owner Earnings, ROIC, valuation, workspace redesign, notifications, trading,
  and production market-data activation.
- Alpaca adapter or activation unless authorized credentials and a reviewed
  provider contract are actually available during this task.

## PRD and architecture references

- `AGENTS.md`
- `docs/BACKLOG.md` — FT-00 and FT-03
- `docs/plans/financial_truth_decision_loop_beta_acceptance.md`
- `docs/architecture/research-decision-support.md`
- `docs/architecture/coverage-source-policy.md`
- `docs/architecture/parsing.md`
- `docs/architecture/data-layer.md`
- `docs/architecture/metric-facts-is-current.md`
- `docs/prd/value-pilot-prd-v0.1.md`

## Planned files

- `docs/acceptance/financial_truth_beta_gold_set.yml`
- `docs/architecture/coverage-source-policy.md`
- `docs/prd/value-pilot-prd-v0.1.md`
- `docs/BACKLOG.md`
- `backend/app/models/`
- `backend/app/services/`
- `backend/app/edgar/`
- `backend/app/cli/`
- `backend/alembic/versions/`
- `backend/tests/unit/`

## Test plan

Test-first targeted runs during implementation, followed by the exact closing
gate:

1. `docker compose up -d --build`
2. `docker compose exec -T api alembic upgrade head`
3. `docker compose exec -T api pytest -q`
4. `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
5. `docker compose exec -T web npm run lint`
6. `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`
7. `git diff --check`

## Decisions and gotchas

- 2026-08-27: no Alpaca credential was present in the host environment, project
  `.env`, running API container, or shared-infra `.env`; values were never
  printed. SEC work proceeds independently. Credential presence alone would not
  constitute source-policy authorization.
- 2026-08-27: the first vertical slice intentionally stops before canonical
  publication. Allowing workspace/formula consumers to query raw XBRL would
  create a forbidden second financial truth.
- 2026-08-27: SEC accession-index `type` values are not a reliable XBRL
  retention discriminator. The approved retention rule combines the primary
  document identity with reviewed XBRL filename suffixes and retains the full
  index manifest for replay.
- 2026-08-27: identity withdrawal and re-review are append-only decisions.
  PIT selection resolves the terminal decision known at the cutoff; it does not
  treat an older `reviewed` row as perpetually active.
- 2026-08-27: parse checksums are not accepted as proof of exact input. Durable
  parse-run/artifact links, database cross-filing/knowledge guards and a raw-fact
  composite foreign key enforce the lineage boundary.
- 2026-08-27: an exact replay verifies every reused retained file's path, size
  and SHA-256. Corruption is an integrity exception and cannot be downgraded to
  a parse/fetch warning.
- 2026-08-27: inline-XBRL lineage preserves resolved concept namespace,
  transformation format, language/continuation reference and divided-unit
  meaning; it still performs no canonical normalization or publication.
- 2026-08-27: Rate Guard failures retain a bounded typed reason, including SEC
  HTTP status classes when the shared client supplies one.
- 2026-08-27: PR #127 follow-up review findings VP-127-01 through VP-127-06
  were independently reproduced with red tests and accepted. Remediation makes
  parse runs, input relationships and facts transactionally consistent; rejects
  zero-fact or count-mismatched success; requires the filing's own reviewed
  identity; verifies SEC-declared byte size; caps each historical-manifest scan
  at 20 requests; and preserves the typed outcome of exact failed-run replay.
- 2026-08-27: follow-up findings VP-127-RR-01 and VP-127-RR-02 were both
  independently reproduced with red tests. Database-forced transaction IDs now
  prevent a later committed transaction from forging a parse-input relationship
  by backfilling timestamps. Unsafe historical-submissions references are
  retained through parsing for bounded service validation, never fetched, and
  reported as typed incomplete outcomes.
- 2026-08-27: VP-127-RR-02B was independently reproduced for non-object,
  missing-name and empty-name history entries. Parser output now retains every
  array position as a valid or typed-invalid reference; the service reports
  bounded indexed failures without issuing a request.

## Live probe evidence

After a final downgrade/upgrade round trip of revision `20260827120000`, the
operator CLI ingested locked case `aapl-primary` through Rate Guard:

- accession `0000320193-26-000020`, form `10-Q`;
- 1 filing, 67 complete-manifest artifact observations, 9 retained exact parse
  inputs, 1 succeeded parse run and 860 raw inline-XBRL facts;
- 0 SEC-published `metric_facts`;
- exact second execution created 0 filings, artifacts, runs and facts;
- replay at `2026-08-26T23:59:59Z` returned 0 filings, while replay at
  `2026-08-28T23:59:59Z` returned the one eligible filing.

This proves only the first AAPL vertical slice. The backlog deliberately keeps
FT-03 open for the remaining locked issuers, forms and ten-year coverage.

## Adversarial review trail

Successive review loops found and fixed: unreliable SEC index type metadata;
missing raw discovery artifacts; checksum-only parse lineage; unavailable-file
retry ambiguity; false success on zero extracted facts; unresolved concept
namespaces and divided units; post-cutoff artifact inputs; identity
retirement/re-review PIT leakage; corrupt stored-byte reuse; cross-filing parse
inputs; invalid amendment links; raw facts attached to failed runs; malformed
manifest-item skipping; collapsed Rate Guard/SEC fetch failures; post-cutoff
parse-input relationships; database fact-count drift; unreviewed filing
identity bypass; SEC-declared-size mismatch; unbounded historical manifest
scans; failed-run replay presented as success; and a deferred-check ordering
bypass that could otherwise append facts beyond the declared run count;
backfilled parse-input timestamps; and silently discarded unsafe historical
references, including non-object and missing/empty-name entries. The final
contract, static-consumer, targeted, migration-round-trip and live-probe review
found no additional actionable issue within this slice.

## Sign-off trail

- Targeted foundation suite: `39 passed`.
- Canonical backend suite: `1500 passed`.
- Canonical frontend unit suite: `216 passed`.
- Frontend lint: no warnings or errors.
- Production build: passed; the pre-existing Browserslist data-age warning is
  informational and outside this backend/documentation slice.
- `git diff --check`: passed.
