# Coverage-source and automation policy

Status: P0 decision record  
Decision date: 2026-07-20

Implementation status (2026-07-20): the canonical EOD reader, US-equity
session calendar, source priority, currency validation, fail-closed provider
selection, batched refresh job, user coverage projection and admin coverage
queue are implemented. Commercial activation still requires an operator to
record authorization and explicitly enable the configured provider; no such
activation is implied by this repository state.

This policy governs what ValuePilot may fetch, retain and expose while building
the Research Decision Loop. Configuration is permission, not evidence of a
license; operators remain responsible for the provider terms attached to their
credentials and account.

| Source | Permitted acquisition | Retention/provenance | Automation and limits | Current production decision |
| --- | --- | --- | --- | --- |
| SEC EDGAR | Public filing/index retrieval through the existing rate-guarded client | Retain raw document, URL, timestamps, hash, accession, parse run and lineage | SEC identity, bounded retries, conditional requests and configured rate guard; never bypass blocks | Authorized for 13F ingestion |
| Value Line | Explicit user upload, or a separately contracted integration whose terms permit the exact use | User-owned raw document and immutable extraction lineage; access remains user-scoped | No crawler, credential sharing or inferred redistribution right; forward archive only after operator records authorization | Upload-only; automated acquisition blocked |
| Twelve Data | API use only with an operator-provided key and terms suitable for the deployment | Store normalized EOD observation, provider, date, currency when supplied, retrieval time and request/job evidence | Batched jobs, provider timeout, bounded retry and provider quota; no per-row render fetch | Adapter supported; production activation requires configured key and operator authorization |
| Yahoo/yfinance endpoint | Development and deterministic/manual fallback only; not an exchange-authorized production feed | Same EOD lineage, visibly labeled provider | Best-effort, low-rate batches; never the basis for a production completeness claim | Development only; not approved as canonical production coverage |
| User-entered valuation | Explicit authenticated user action | User-owned versioned manual fact/research revision with currency and as-of date | No external acquisition | Authorized |

## Canonical rules

- `metric_facts` remains the only queryable fundamentals source. Parsed facts
  always retain document/page/snippet provenance; manual corrections never
  mutate extraction history.
- Proprietary coverage may enter `in_progress` only from an explicit upload or
  an operator-configured authorized source. Missing authorization is
  `blocked`, never “covered”.
- EOD price refresh is batched and job-scoped. A page render reads stored bars
  and may request one deduplicated refresh job; it does not call providers for
  each row.
- Provider responses without a validated price currency cannot satisfy the
  Research Decision Loop's value-comparison readiness gate.
- The current Value Line freshness policy is 120 calendar days and is a
  ValuePilot workflow threshold, not a claim about the publisher's cadence.
  Coverage results persist the policy version and evaluation time.
- Raw/proprietary artifacts and user-authored facts are never exposed across
  users. Public 13F facts may be shared only through the authoritative active
  filing/current successful parse contract.
- Source secrets are configuration only: redacted in logs and API responses,
  excluded from audit payloads, and disabled when unreadable or absent.

## Historical Value Line decision

Historical expansion is not authorized to proceed on token-count alignment.
The modern supported V1 fixture corpus remains usable for product research, but
pre-era backfill and backtest claims stay blocked until representative
non-calendar-fiscal-year and historical-layout samples exist and annual table
values are aligned to year headers by x-coordinate. Existing parsed rows are
not mass-rewritten. The parser backlog items remain open, high visibility, and
must be resolved before any historical efficacy claim.
