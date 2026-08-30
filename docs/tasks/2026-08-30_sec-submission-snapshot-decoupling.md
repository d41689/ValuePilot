# SEC submissions snapshot decoupling

Status: Step B PASS — independently reviewed by Terra; ready to commit

Owner: Product / Engineering

Date: 2026-08-30

## Step A trust-boundary reset

The backend application, PostgreSQL application/admin roles, Rate Guard,
deployment host/admins, and authorized developers are trusted. This step covers
ordinary external-data and operational failures: malformed or identity-
conflicting SEC payloads, limits/outages/partial fetches, stale cache, content
corrections and duplicates, normal concurrency/crash/commit-finalize behavior,
small clock skew, coverage gaps, PIT/supersession, and a controlled retained
file that is missing, truncated, or same-size corrupted. Arbitrary trusted-
database writes, arbitrary backend code execution, malicious admins, internal
key theft/signature forgery, penetration testing, and security auditing are out
of scope.

Retained mechanisms and tests:

- Rate Guard remains the sole SEC path. Reuse forces a normal authenticated
  fetch with `max_cache_age_s=0`, while the allowlist, aggregate limiter,
  retries, and global pause remain active.
- The backend verifies canonical SEC URLs plus actual returned byte size and
  SHA-256. Same-length corrections append new content lineage.
- Append-only rows, exact operation/filing/input ownership, transaction stamps,
  separate finalization, PIT/supersession, bounded typed failures, idempotency,
  and exact correction/resolution lineage remain enforced.
- Submission source validation is deterministic: reread controlled storage,
  verify SHA/size, parse, check canonical role/URL and reviewed CIK, and verify
  historical references against the retained main payload.
- Product selectors and replay reread every retained input. Missing, truncated,
  or same-size corrupted files are ineligible and surface
  `retained_artifact_integrity_failure` instead of falling back silently.
- A two-run same-filing correction regression proves that corrupting the newest
  finalized run cannot expose the older run through success selection, earliest
  replay calculation, failure projection, or the operator CLI.
- Local tests retain ordinary invariant violations, concurrency/finalize/PIT,
  malformed/partial/stale/correction/idempotency cases, exact URL guards,
  no-`metric_facts` publication, and all three retained-file corruption modes.

Removed mechanisms and tests:

- Rate Guard HMAC receipts, request-context UUIDs, receipt signing/verifier
  keyrings, receipt tables/FKs/triggers, signature revalidation, receipt cutoff
  boundaries, and FSS-021/FSS-023/FSS-024 privileged-forgery simulations.
- Backend HMAC source-validation attestations, attestation keyrings/tables/FKs/
  triggers, one-use cryptographic authority, and FSS-025/FSS-026 tests aimed only
  at arbitrary code or privileged database callers.
- FSS-027 remains in scope as an ordinary local-storage integrity failure; it
  is implemented without adding a new security authority.

## Step B acceptance evidence

- Immutable main/historical retention, malformed payloads, and bounded typed
  failures: `test_malformed_fetched_submissions_are_retained_and_audited_before_failure`,
  `test_historical_fetch_outage_retains_all_prior_payloads_and_finalizes`, and
  `test_lineage_tables_reject_update_and_delete_at_database_boundary`.
- Initial main-resource outage before any bytes:
  `test_initial_main_outage_is_durable_pending_idempotent_and_later_resolved`
  proves a canonical no-bytes anchor, bounded failure, zero downstream
  publication, post-commit finalization/crash recovery, PIT visibility,
  repeated-outage idempotency, and exact-resource later resolution. The CLI
  terminal-failure regression proves commit then finalize before typed exit 2;
  `test_no_bytes_anchor_cannot_make_no_eligible_operation_finalizable` proves
  the anchor cannot legitimize a fabricated empty result.
- Earlier successful payloads survive a later fetch failure:
  `test_historical_fetch_outage_retains_all_prior_payloads_and_finalizes`
  verifies the retained main and first historical files after the second
  historical fetch returns a typed 503 failure.
- Parse-input decoupling and unrelated issuer churn:
  `test_ingestion_is_idempotent_pit_safe_and_does_not_publish_metric_facts`
  proves the snapshot is not a parse input, while
  `test_unrelated_submissions_churn_does_not_duplicate_filing_lineage` proves
  churn appends only a snapshot.
- Exact rerun and corrected-byte behavior:
  `test_ingestion_is_idempotent_pit_safe_and_does_not_publish_metric_facts`
  proves identical content reuse; `test_same_index_retained_byte_correction_appends_new_lineage`
  proves normal Rate Guard revalidation appends artifacts, a run, and facts for
  a same-length correction with unchanged index bytes.
- Retained-file selection/replay integrity:
  `test_selection_and_replay_fail_closed_on_retained_file_integrity_failure`
  covers missing, wrong-size, and wrong-SHA single-run inputs; the two-run
  `test_newest_corrected_run_storage_failure_never_falls_back_to_older_run`
  additionally proves no older success/earliest/CLI fallback and identifies the
  newer run in bounded failure projection.
- Pending/finalized/crash/concurrency/PIT behavior:
  `test_ingested_lineage_is_pending_until_separate_finalize_and_recovers_idempotently`,
  `test_finalize_serializes_against_concurrent_operation_write`,
  `test_concurrent_ingestion_serializes_snapshot_and_filing_lineage`, and
  `test_lineage_visibility_requires_post_commit_availability_marker`.
- Mixed result, retry, exact resolution, and identity visibility:
  `test_replay_keeps_success_and_terminal_failure_for_different_filings`,
  `test_index_outage_is_terminal_finalizable_and_successful_retry_supersedes_failure`,
  the exact main/historical validation tests, and the parametrized
  supersession/retirement cutoff test.
- Canonical URL, exact ownership, append-only, Rate Guard-only egress, and no
  raw SEC publication are covered by the migration trigger suite,
  `test_sec_filing_artifact_urls_are_exact_canonical_archives_urls`,
  `test_sec_url_owners_do_not_import_direct_network_clients`,
  `test_edgar_revalidated_get_stays_on_rate_guard_path`, and
  `test_product_modules_do_not_read_raw_sec_financial_facts`.

## Goal

Separate issuer-wide SEC submissions discovery snapshots from the exact
per-accession inputs that determine a financial parse run. A submissions payload
must remain immutable, retained, and auditable without causing unrelated issuer
activity to manufacture duplicate artifact observations, parse runs, or raw
facts for an unchanged filing.

This advances source-traceable normalized-owner-earnings research and
disconfirmation by preserving discovery evidence while making the parse lineage
state exactly what affected the filing parser. Success is observable when a
changed issuer submissions payload appends only an issuer-wide snapshot, an
unchanged accession remains idempotent, and a real accession input change
appends a new per-filing observation and parse run.

## Acceptance criteria

- Every fetched main or historical submissions payload is retained as immutable
  issuer-wide discovery lineage with source URL, content identity, storage
  identity, and knowledge/fetch timestamps.
- Malformed fetched submissions bytes commit as retained snapshots plus bounded
  typed terminal discovery-failure audit, with no filing/parse/fact publication.
- Exact filing artifact identity and parse-run input manifests exclude issuer
  submissions snapshots. They include the accession index and retained artifacts
  that are true inputs for that filing.
- Rerunning an unchanged accession after unrelated submissions JSON churn creates
  no new `sec_filing_artifacts`, parse run, parse-input link, raw fact, or
  `metric_facts` row.
- Re-fetching an identical submissions snapshot is idempotent; a genuinely new
  snapshot appends exactly one issuer-wide observation.
- A changed accession index or retained filing artifact appends the required
  observation and parse run without mutating prior lineage.
- Every retained parser input is revalidated through Rate Guard before reuse;
  actual fetched content SHA participates in manifest identity, so a same-index,
  same-length upstream byte correction appends new lineage.
- Concurrency, content-addressed storage verification, exact-input foreign keys,
  transaction identity, PIT eligibility, and append-only database guards remain
  fail closed.
- New evidence remains pending after the ingest commit and becomes PIT-visible
  only at a separately committed, database-stamped availability marker;
  finalization and operator crash recovery are idempotent.
- Database ownership guards require every operation snapshot, parse terminal,
  and acquisition failure to belong to the operation's reviewed issuer identity;
  ordinary cross-stock and cross-operation application mistakes fail closed.
- Availability is a terminal seal. Operation writers and the finalizer serialize
  on the operation row; finalization rejects the creation transaction, requires
  retained discovery evidence plus an explicit terminal result, and prevents
  all later operation-bound lineage writes.
- Only migration-marked preexisting parse runs may omit an ingestion operation;
  every new run requires one, and PIT selectors reject arbitrary unmarked NULL
  operation lineage.
- Every submissions/index/artifact acquisition failure becomes a bounded,
  immutable terminal result. Failures after response bytes attach to a retained
  snapshot explicitly linked to the same operation and reviewed identity. An
  initial main fetch failure before bytes attaches instead to an exact canonical
  no-bytes resource anchor owned by the operation. Successfully fetched payloads
  survive a later outage, the operation finalizes, and the CLI exits nonzero.
- An acquisition failure remains visible until a later finalized operation
  records an explicit resolution for the same durable scope. Accession failures
  require a terminal parse for that accession; submissions failures require
  validation of the exact normalized source and role. Unrelated accessions,
  `no_eligible_filings`, and other resources never suppress it.
- Acquisition failures are visible only while their own reviewed issuer
  identity remains the terminal effective decision at the PIT cutoff.
- Every accession touched by an operation has immutable, database-stamped
  attempt evidence naming the filing/accession, exact index resource and hash,
  parse-input manifest, terminal outcome, and exact retained artifact links.
  An accession resolution must reference that current operation's attempt;
  idempotent reuse explicitly links and verifies the prior exact content.
- A resource resolution can suppress a failure only when its database creation
  (and, for accessions, attempt) time is at or after the failure creation time;
  a retry begun earlier cannot erase a later failure by finalizing afterward.
- Filing-artifact failures require an exact unavailable/rejected observation
  whose reason matches the typed failure. Retained URLs and synthetic keys not
  recomputed from the matching source-less failed filename are rejected.
- Every non-NULL filing-artifact URL is the exact canonical SEC Archives URL
  reconstructed from the reviewed CIK, dashless accession, and strict safe
  filename (including the accession-index special form). URL authority,
  userinfo, port, query, fragment, case, encoding, and traversal variants fail
  at the database boundary.
- One authoritative eligibility routine governs product-facing success,
  failure, replay, suppression, and earliest-boundary decisions using exact
  attempt, resolution, operation, run, input, storage-integrity, and cutoff
  ownership.

## Scope

### In

- Issuer-wide SEC submissions snapshot schema, service persistence, and
  append-only/database integrity.
- Per-filing artifact-manifest and parse-input identity decoupling.
- Bounded Rate Guard cache revalidation for retained SEC parser inputs.
- Regression coverage for observed submissions-churn duplication, exact rerun,
  accession-content change, concurrency/idempotency, unsafe storage state, PIT,
  and no publication to `metric_facts`.
- Contract documentation for discovery lineage versus parse inputs.

### Out

- Malicious trusted-infrastructure callers, arbitrary database writes or
  backend code execution, malicious administrators, internal key compromise,
  signature-forgery resistance, penetration testing, and security auditing.
- Destructive cleanup or rewriting of existing duplicate lineage.
- Canonical SEC-to-`metric_facts` mapping.
- Changes to form-aware history selection or gold-set identity resolution.
- A broader retention-policy or general-purpose cache-control expansion.

## PRD and architecture references

- `AGENTS.md`
- `docs/architecture/data-layer.md`
- `docs/architecture/parsing.md`
- `docs/architecture/coverage-source-policy.md`
- `docs/prd/value-pilot-prd-v0.1.md` §H.3–H.7
- `backend/alembic/versions/20260827120000-sec-financial-lineage.py`

## Files changed

- `backend/app/models/sec_financials.py`
- `backend/app/services/sec_financial_ingestion.py`
- `backend/app/edgar/client.py`
- `backend/app/rate_guard/client.py`
- `backend/app/services/sec_financial_validation.py`
- `backend/alembic/versions/20260830130000-sec-submission-snapshots.py`
- `backend/tests/unit/test_sec_financial_lineage.py`
- `backend/tests/unit/test_sec_financial_cli.py`
- `backend/tests/unit/test_sec_financial_lineage_migration.py`
- `backend/tests/unit/test_rate_guard_client.py`
- `rate-guard/README.md`
- `rate-guard/app/gateway.py`
- `rate-guard/app/main.py`
- `rate-guard/tests/test_auth.py`
- `rate-guard/tests/test_gateway.py`
- `docs/tasks/2026-05-20_rate-guard-design.md`
- `docs/architecture/parsing.md`
- `docs/prd/value-pilot-prd-v0.1.md`
- `docs/tasks/2026-08-30_sec-submission-snapshot-decoupling.md`

Experiment-only untracked files removed during the reset:

- `backend/app/rate_guard/receipts.py`
- `rate-guard/app/receipts.py`
- `backend/tests/unit/test_sec_financial_validation_attestations.py`

## Test plan

1. Add failing service regressions before production changes.
2. `docker compose exec -T api pytest -q tests/unit/test_sec_financial_lineage.py tests/unit/test_sec_financial_lineage_migration.py tests/unit/test_sec_financial_source_guard.py`
3. `docker compose exec -T api pytest -q tests/unit/test_rate_guard_client.py`
4. Run the Rate Guard tests in a Docker container against `rate-guard/`.
5. `git diff --check`

The full canonical Docker gate remains required before the complete multi-step
repair is declared done.

## Decisions and gotchas

- 2026-08-30: a submissions payload establishes how an accession was discovered;
  it is not input consumed by the inline-XBRL parser. Its content identity must
  therefore not participate in either the accession artifact-manifest hash or
  the parse-run exact-input hash.
- 2026-08-30: existing duplicate rows remain immutable. This step fixes future
  identity and idempotency behavior and does not infer authority to delete or
  collapse prior lineage.
- 2026-08-30: snapshots are keyed by reviewed issuer-identity decision, source
  URL, and content SHA. The stock-scoped ingestion advisory lock serializes
  competing writes for the same identity; the database unique constraint is the
  final duplicate boundary. Identical content verifies and reuses immutable
  storage, while different content appends a new snapshot.
- 2026-08-30: `artifacts_created` continues to count per-filing artifact
  observations only. Discovery snapshots have their own table and do not inflate
  filing artifact or parse-run counts.
- 2026-08-30: a read-only audit of the shared development data found eight
  accessions with two legacy manifests/runs whose true accession inputs were
  unchanged and whose only content difference was `__submissions__.json`:
  `0000070858-26-000394`, `0000320193-26-000020`,
  `0000831259-26-000036`, `0000886982-26-000297`,
  `0001053507-26-000133`, `0001108524-26-000190`,
  `0001171843-26-005715`, and `0001628280-26-054343`. No rows were changed.
  The v1 compatibility path reuses a complete legacy manifest after verifying
  that its only obsolete input is the retained submissions payload; this keeps
  the first post-fix rerun from manufacturing a third duplicate. It neither
  rewrites nor collapses existing lineage.
- 2026-08-30: legacy reuse is intentionally fail closed. The bridge recomputes
  the original v1 manifest hash, requires the canonical submissions/index/item
  metadata and exact safe URLs, verifies every retained byte count and SHA, and
  accepts a prior run only when it actually linked exactly one legacy
  `__submissions__.json` input plus the same filing-input artifact IDs.
  Ambiguous, malformed, corrupt, partial, or merely similar groups create new
  current-policy lineage instead.
- 2026-08-30: the snapshot table rejects pre-fetch knowledge timestamps and has
  both an insert guard requiring the cutoff-current reviewed issuer identity and
  the shared append-only update/delete guard. This keeps direct SQL from
  accidentally bypassing the service's identity, causal-time, and immutability
  boundaries; it is an invariant check, not a malicious-admin defense.
- 2026-08-30: retained accession inputs are not presumed immutable merely
  because their index metadata is unchanged. Acquisition revalidates the index
  and every retained parser input through `EdgarClient` and authenticated Rate
  Guard with `max_cache_age_s=0`; Rate Guard still enforces its allowlist,
  aggregate token bucket, retry, and global-pause policy, then replaces the
  cached 200 response. The override is accepted only in the bounded 0–3600
  second range. The resulting content SHA and byte size are part of the filing
  artifact-manifest identity.
- 2026-08-30: identity decisions and lineage writes share the database advisory
  keys `sec-issuer-cik:<CIK>` and `sec-issuer-stock:<stock_id>`. Snapshot and
  filing inserts recheck the reviewed identity under that boundary. A retirement
  or supersession whose `known_at` is at or before already-persisted snapshot or
  filing lineage is rejected instead of invalidating that evidence at its own
  cutoff.
- 2026-08-30: downgrade is intentionally blocked while any discovery snapshot
  exists; a `SHARE ROW EXCLUSIVE` table lock is acquired before the preflight
  and held through teardown, so an uncommitted concurrent insert cannot race the
  count. Snapshot SHA,
  content-addressed key, and canonical reviewed-CIK SEC URL shapes are enforced
  at the database boundary.
- 2026-08-30: reviewed issuer CIK is constrained, after a fail-closed migration
  preflight, to exactly ten ASCII digits. This makes the canonical submissions
  URL trigger's reviewed CIK component non-injectable while preserving existing
  valid identities.
- 2026-08-30: an ingest transaction creates an immutable operation and assigns
  every new parse run and snapshot to it. Success and terminal-failure selectors
  exclude operations lacking a separately committed availability marker. The
  finalizer inserts that append-only marker with PostgreSQL
  `clock_timestamp()` after the ingest commit. It is idempotent; an explicit
  finalize command and the next authorized operator ingestion rerun recover a
  committed pending operation after a crash. Replay reports typed
  `pit_evidence_unavailable` while any committed operation remains pending.
- 2026-08-30: successful network fetch is the retention boundary, not successful
  JSON parsing. Main and historical decode/parse exceptions become fixed typed
  failure codes. The exact fetched bytes are content-addressed and retained,
  then a terminal audit row linked to that snapshot is committed and finalized
  before the gold-case CLI exits nonzero.
- 2026-08-30: operation and availability transaction identities are
  database-forced (`txid_current()`), immutable audit fields. Caller-supplied
  timestamps or transaction IDs are overwritten. Availability cannot be added
  in the operation's creation transaction, so no same-transaction timestamp can
  claim post-commit visibility.
- 2026-08-30: operation snapshot links, operation-owned parse runs, discovery
  failures, and terminal results lock the operation row and reject an existing
  availability seal. Snapshot and filing identities must match the operation
  identity exactly; a historical accession owned by a different reviewed
  identity is therefore a fail-closed acquisition boundary even when both
  identity decisions refer to the same stock and CIK.
- 2026-08-30: finalization requires at least one retained submissions snapshot
  linked to the operation, except that an initial main request that returned no
  bytes uses one exact canonical no-bytes resource anchor. The anchor permits
  only a matching `submissions_fetch` acquisition-failure terminal; it cannot
  seal `no_eligible_filings`. Every operation still requires exactly one
  explicit terminal result, and empty operation rows cannot become visible.
  Exact parser inputs and facts retain their existing creation-transaction
  guards and therefore cannot be appended after their run transaction.
- 2026-08-30: an identical malformed discovery rerun reuses a prior audited
  operation only when every fetched payload matches the retained snapshot SHA,
  every snapshot is linked to that operation, and the typed terminal failure is
  exact. Partial, cross-operation, corrupt, or ambiguous audit state is never
  treated as idempotent.
- 2026-08-30: a parsed main submissions CIK that differs from the locked reviewed
  CIK is retained under the expected identity and recorded as bounded typed
  `main_submissions_cik_mismatch`. It finalizes as failed discovery evidence,
  exits the operator workflow nonzero, and creates no filing, parse, raw-fact,
  or metric-fact lineage.
- 2026-08-30: only parse runs that existed before this migration may have no
  operation. Upgrade atomically copies their IDs into the immutable
  `sec_financial_legacy_parse_runs` allowlist before installing the new-run
  guard. All new NULL-operation runs are rejected at the database boundary;
  PIT selectors require either a cutoff-visible finalized operation or that
  exact legacy marker. An arbitrary unmarked NULL row is never replayable.
- 2026-08-30: acquisition failures use one bounded immutable schema across
  initial/subsequent submissions fetch, submissions parsing/identity,
  historical fetch/parse, accession-index fetch, and retained-artifact
  acquisition. Each row names a fixed stage and error code plus optional
  validated accession. It has exactly one evidence source: an operation-linked
  retained snapshot, or for the initial pre-byte main outage, the matching
  canonical resource anchor. The terminal result makes these operations
  finalizable and operator-visible instead of leaving dead pending operations.
- 2026-08-30: acquisition-failure ownership is established by the exact
  `(operation_id, snapshot_id)` link plus matching reviewed identity, not by the
  operation that first created an immutable snapshot. This permits a changed
  main payload to link a byte-identical historical snapshot retained earlier,
  while unlinked or cross-identity references remain rejected. Availability
  revalidates the same link.
- 2026-08-30: once the main submissions payload is retained, later historical
  fetch outages are converted to bounded `historical_submissions_*` failures.
  The main payload and every earlier successfully fetched historical payload
  remain in the operation before it commits and finalizes. An index revalidation
  outage follows the same terminal contract.
- 2026-08-30: failure suppression is resource scoped, never issuer-wide. Every
  failure stores an immutable normalized resource role/key. Every successful
  submissions parse stores an exact source validation resolution, and every
  accession acquisition stores its succeeded or failed terminal parse
  resolution. A later finalized resolution suppresses only the matching
  resource failure; a parse failure replaces the acquisition failure but
  remains visible through the ordinary failed-parse projection. Different
  accessions, different historical URLs, unrelated `no_eligible_filings`
  results, and fabricated resolution rows do not resolve the audit.
- 2026-08-30: acquisition-failure PIT projection applies the same terminal
  reviewed/effective issuer decision used by parse evidence. Visibility is
  anchored to the operation attempt and still requires the failure creation and
  separately committed availability timestamps by the cutoff; a superseding or
  retiring reviewed decision hides the old identity's failure without
  backdating either decision.
- 2026-08-30: an operation's accession attempt is a durable causal bridge
  between acquisition and resolution. PostgreSQL overwrites attempted/created
  time and transaction identity, verifies operation/identity/filing ownership,
  and records the accession index hash, current parse-input manifest, terminal
  parse or acquisition outcome, and exact retained artifact links. A newly
  created parse must belong to the operation. An idempotently reused run must
  already be PIT-visible (or be migration-allowlisted legacy lineage) and its
  retained input set must equal the attempt set; the narrow legacy bridge may
  differ only by its one obsolete submissions input. Empty operations cannot
  borrow old runs, cross-own attempts, or seal a no-filings result after an
  accession was attempted.
- 2026-08-30: ordering uses database evidence time, not finalize order. Across
  operations, a resolution's database-created time—and an accession attempt's
  database-attempted time—must be at or after the failure creation time, while
  availability must still be later. A transaction that records a resolution,
  waits for a later failure, and finalizes last therefore does not erase that
  failure.
- 2026-08-30: artifact failure scope is evidence-backed at the database
  boundary. Direct URLs must identify the same filing's unavailable/rejected
  artifact and exact reason code. A source-less unsafe item uses a synthetic key
  whose SHA-256 token PostgreSQL recomputes from that exact filename. A retained
  artifact, reason mismatch, unrelated URL, or mismatched token cannot back a
  terminal failure.
- 2026-08-30 Step A reset: Rate Guard performs the forced normal fetch and the
  backend deterministically validates source meaning after rereading controlled
  storage and checking SHA/size, parse success, canonical role/URL, reviewed
  CIK, and historical main-reference linkage. Operation/snapshot ownership and
  PIT finalization provide the durable resolution contract; no cryptographic
  authority or key lifecycle is part of this trusted-infrastructure boundary.

## Sign-off trail

This is a historical implementation log. Earlier “adversarial”, “attack”, or
raw-SQL wording does not expand the current threat model. Retained direct-insert
tests exercise database invariants against ordinary application/migration bugs;
tests whose sole purpose was a malicious privileged-caller model were removed
in Step A.

- Red tests: the observed unrelated-submissions churn regression failed at the
  missing issuer-wide snapshot model before implementation. Existing code also
  counted and linked `__submissions__.json` as a per-filing artifact. The legacy
  bridge also initially accepted a corrupt manifest hash, noncanonical extra
  metadata, and a run that never linked the legacy submissions input; the new
  fail-closed regressions demonstrated each issue before hardening.
- Adversarial repair red tests: nonempty downgrade previously dropped retained
  rows; malformed hash/key/URL shapes were accepted; retirement bypassed an
  uncommitted later-known snapshot; and same-index/same-length corrected bytes
  reused stale lineage. Each regression failed before its repair.
- Targeted Docker tests after FSS-005 through FSS-008: lineage + CLI `56
  passed`; isolated migration/round-trip/concurrency `9 passed`; broader SEC
  history/CLI/gold-set/lineage/security/Rate-Guard-client `152 passed`; Rate
  Guard service `41 passed`.
- Alembic repo head: `20260830130000`. Isolated upgrade/downgrade and dirty-data
  preflights pass. The shared development database currently reports unrelated
  revision `20260828500000`, which is absent from this branch, so it was not
  rewritten or stamped to force the shared upgrade gate.
- `git diff --check`: clean after FSS-005 through FSS-008 repairs.
- Adversarial review: FSS-001 through FSS-008 changes requested; second
  re-review pending.
- Second adversarial repair red tests: downgrade raced an uncommitted insert;
  arbitrary ten-character CIK could reach the URL regex; same-transaction
  timestamps could make post-commit evidence appear replayable too early; and a
  malformed fetched submissions payload rolled back without retained audit.
  FSS-005 through FSS-008 tests cover the locked downgrade, raw-SQL CIK boundary,
  real two-session commit/finalize cutoffs and idempotent recovery, pending replay
  failure, and malformed main/historical retention.
- Third adversarial repair red tests: cross-stock operation links were accepted;
  operation/finalization transaction IDs were caller-controlled; an empty
  operation could be considered recoverable without a terminal shape; a
  finalizer could race a later writer; and a parsed main CIK mismatch was not a
  retained typed terminal audit. FSS-009 through FSS-012 now cover raw-SQL
  ownership attacks, database-forced transaction stamps, same-transaction
  finalize rejection, post-commit finalization, finalized-then-write and real
  two-session finalize/write races, fabricated-empty rejection, legitimate
  no-filings finalization, exact malformed rerun idempotency, and the main-CIK
  mismatch boundary.
- Targeted Docker verification after FSS-009 through FSS-012: SEC gold-set,
  history selection, lineage, isolated migration/round-trip/concurrency, CLI,
  source guard, Rate Guard client/startup `171 passed`; Rate Guard service `41
  passed`; `git diff --check` clean.
- Adversarial review: FSS-001 through FSS-012 changes requested; FSS-009 through
  FSS-012 re-review pending. No Step 3 commit has been created.
- Fourth adversarial repair red tests: arbitrary post-head NULL-operation runs
  were treated as legacy; index and historical fetch outages escaped without a
  terminal result; and a reused immutable historical snapshot was incorrectly
  required to have been created by the current operation. FSS-013 through
  FSS-015 now cover pre-head allowlist backfill and immutability, raw NULL-run
  rejection plus PIT exclusion, index-outage finalization/retry/supersession,
  ordered historical payload retention before a later outage, and changed-main
  reuse of an operation-linked malformed historical snapshot.
- Targeted Docker verification after FSS-013 through FSS-015: SEC gold-set,
  history selection, lineage, isolated migration/round-trip/concurrency, CLI,
  source guard, Rate Guard client/startup `176 passed`; standalone Rate Guard
  service `41 passed`; CLI-only `18 passed`; `git diff --check` clean.
- Operator regression: a terminal acquisition failure commits first, receives
  its availability seal in a second transaction, prints the bounded failure,
  and only then exits `2`. No dead pending operation is left by this path.
- Adversarial review: FSS-001 through FSS-015 changes requested; FSS-013 through
  FSS-015 are ready for re-review. No Step 3 commit has been created.
- Fifth adversarial repair red tests: any later finalized operation—including
  unrelated `no_eligible_filings` and a failed parse for another accession—hid
  an unresolved accession-index failure, while identity supersession and
  retirement left old-identity acquisition failures visible. FSS-016 and
  FSS-017 now cover exact main and historical source validation, different-URL
  and different-accession negatives, same-accession succeeded/failed parse
  resolution across cutoffs, canonical raw-SQL scope guards, and I1→I2 plus
  retirement PIT transitions.
- Targeted Docker verification after FSS-016 and FSS-017: SEC gold-set, history
  selection, lineage, isolated migration/round-trip/concurrency, CLI, source
  guard, Rate Guard client/startup `183 passed`; standalone Rate Guard service
  `41 passed`; `git diff --check` clean.
- Adversarial review: FSS-001 through FSS-017 changes requested; FSS-016 and
  FSS-017 are ready for re-review. No Step 3 commit has been created.
- Sixth adversarial repair red tests: an empty operation could borrow a prior
  run to fabricate an accession resolution; a resource resolution recorded
  before a later failure erased it when finalized last; and retained artifact
  URLs plus arbitrary syntactically valid filename-hash URNs could back false
  failures. FSS-018 through FSS-020 now cover current-operation attempt/run
  ownership, exact idempotent input reuse, cross-operation attempt rejection,
  no-filings attempt exclusion, real two-session creation/finalize ordering,
  retained/reason-mismatch/forged-URN negatives, and unavailable/rejected
  direct-URL and recomputed-URN positives.
- Targeted Docker verification after FSS-018 through FSS-020: SEC gold-set,
  history selection, lineage, isolated migration/round-trip/concurrency, CLI,
  source guard, Rate Guard client/startup `186 passed`; standalone Rate Guard
  service `41 passed`; `git diff --check` clean.
- Adversarial review: FSS-001 through FSS-020 changes requested; FSS-018 through
  FSS-020 are ready for re-review. No Step 3 commit has been created.

### Superseded FSS-021 through FSS-025 experiment log

The entries below record the discarded cryptographic-authority experiment for
review traceability only. Step A removed those mechanisms and their privileged-
actor tests under the trust boundary above. They are not current requirements,
verification results, or deferred work. FSS-022 canonical URL enforcement is
the exception and remains part of the current contract.

- FSS-021 replaces a freely declarable revalidation claim with a Rate Guard
  HMAC receipt bound to a UUIDv4 ingestion operation, exact canonical URL,
  returned content SHA-256/size, authoritative fetch time, and upstream
  revalidation disposition. The API verifies the versioned signature before
  use/persistence, immutable attempt links bind every retained input to its
  receipt, and failure-resolution selection verifies every persisted signature
  again. Missing keys, copied receipts, cross-operation replay, tampering, and
  raw-SQL fabricated signatures fail closed. V1/V2 rotation keeps the prior
  verifier key until its immutable evidence is outside required replay windows.
- FSS-022 reconstructs every non-NULL filing-artifact URL in the database from
  reviewed CIK integer form, dashless accession, and a strict ASCII-safe
  filename (with the accession `index.json` special form). Host, userinfo,
  port, query, fragment, case, encoding, and traversal variants cannot enter
  lineage. Preexisting explicitly allowlisted legacy submissions-coupled parse
  inputs remain auditable, but the insert guard cannot create new ones.
- Seventh adversarial repair red tests: a raw-SQL operation could freely claim
  it had revalidated unchanged inputs, and filing artifacts accepted off-SEC or
  noncanonical URL variants. FSS-021 and FSS-022 now cover signed receipt
  issuance and verification, missing/tampered fields and signatures,
  cross-operation replay, immutable receipt/input ownership, a raw-SQL fake
  receipt that cannot suppress a real failure, exact canonical primary/index
  URLs, and host/userinfo/port/query/fragment/case/encoding/traversal attacks.
- Targeted Docker verification after FSS-021 and FSS-022: SEC gold-set, history
  selection, lineage, isolated migration/round-trip/concurrency, CLI, source
  guard, Rate Guard client/startup `197 passed`; standalone Rate Guard service
  `43 passed`; Python compile check and `git diff --check` clean.
- Adversarial review: FSS-001 through FSS-022 changes requested; FSS-021 and
  FSS-022 are ready for re-review. No Step 3 commit has been created.
- FSS-023 centralizes operation receipt eligibility for successful and failed
  parse evidence, accession-failure resolution, earliest replay calculation,
  and CLI replay. It independently verifies the persisted signature/version,
  operation/context, exact index and retained-input URLs/content, current
  attempt/resolution/run ownership and PIT cutoff. A migration-marked legacy run
  is the only receipt-free path.
- FSS-024 enforces the same five-second maximum future skew in service and
  PostgreSQL. Receipt eligibility requires every signed fetch time at or before
  cutoff, and the conservative boundary takes the maximum across availability,
  all exact receipts and the remaining lineage timestamps. No timestamp is
  rewritten, clamped, or backdated.
- Eighth adversarial repair red tests: a structurally valid run with forged
  receipt signatures appeared as successful evidence; selectors ignored signed
  future receipt times; and both service and PostgreSQL accepted a receipt one
  day beyond their clock. FSS-023/FSS-024 now cover forged success plus unchanged
  failure visibility, exact before/equal receipt cutoffs, mixed receipt times,
  conservative earliest replay, CLI PIT-unavailable-to-visible transition, and
  service/database future rejection.
- Targeted Docker verification after FSS-023 and FSS-024: SEC gold-set, history
  selection, lineage, isolated migration/round-trip/concurrency, CLI, source
  guard, Rate Guard client/startup `202 passed`; standalone Rate Guard service
  `43 passed`; Python compile check and `git diff --check` clean.
- Adversarial review: FSS-001 through FSS-024 changes requested; FSS-023 and
  FSS-024 are ready for re-review. No Step 3 commit has been created.
- FSS-025 separates authorized transport proof from semantic source-validity
  authority. The ingestion service reads content-addressed storage and passes
  those bytes into a signing boundary that cannot issue until exact content
  SHA/size, deterministic parse, canonical
  source role/URL, reviewed CIK, and historical main-reference validation pass.
  Its independent V1/V2 HMAC covers operation, source, snapshot, validator
  contract, CIK, time, and valid outcome. PostgreSQL binds it immutably and
  one-use to the exact operation/snapshot/resolution; selectors reverify the
  signature and cutoff before a source resolution can suppress failure.
- Ninth adversarial repair red tests: a valid Rate Guard fetch receipt plus a
  raw-SQL `resource_validated` declaration suppressed malformed main and
  historical failure evidence. FSS-025 now covers both exact attacks, malformed
  content, storage identity corruption, tampered/cross-operation/cross-role/
  cross-snapshot/replayed authority, validation-time cutoff, V1/V2 rotation,
  missing verifier keys, valid later retries, and a database-rejected one-day
  future attestation. Compose strips the backend authority from Rate Guard even
  though the services share an environment file.
- Targeted Docker verification after FSS-025: SEC gold-set, history selection,
  lineage, isolated migration/round-trip/concurrency, CLI, source guard,
  validation authority, Rate Guard client/startup, and Edgar client `212
  passed`; standalone Rate Guard service `43 passed`; both Compose files
  validate and `git diff --check` is clean.
- Adversarial review: FSS-001 through FSS-025 changes requested; FSS-025 is
  ready for re-review. No Step 3 commit has been created.

## Step A sign-off trail

- Scope-reset focused backend verification in Docker: lineage, isolated
  migration/round-trip/concurrency, source guard, Rate Guard client, SEC CLI,
  and Edgar client `143 passed`.
- Standalone Rate Guard service verification in Docker: `41 passed` (the two
  removed receipt-signing tests account for the reduction from the superseded
  experiment's `43 passed`).
- Backend and Rate Guard compile checks passed; both Compose configurations and
  `git diff --check` passed.
- No real SEC request, external probe, credential test, production database, or
  commit was used. Step A is ready for independent Terra review.
- Terra Step A P2 follow-up: the new two-run regression first failed because
  earliest replay still found the older finalized run after the newest
  correction's retained input disappeared. Earliest-boundary calculation now
  treats a storage-corrupt latest finalized success as blocking all older
  candidates for that filing. Missing, truncated, and same-size SHA corruption
  cases pass, identify the newer run in failure projection, and make real CLI
  replay exit nonzero with zero selected filings.
- Post-fix focused Docker verification covering lineage, isolated migration,
  source guard, Rate Guard client, and SEC CLI: `139 passed`; compile and
  `git diff --check` passed. Step A is ready for Terra re-review.
- Step B main-resource-outage follow-up: the initial fake 503 regression first
  failed because `_discover` raised before an operation existed. Initial
  503, 429-limit, and Rate-Guard-timeout/no-status cases now append one canonical
  main-resource anchor, one bounded
  `submissions_fetch` failure, and one acquisition-failure terminal. The
  database enforces the anchor/stage pairing, operation ownership, append-only
  sealing, and rejects anchor-backed `no_eligible_filings` at result insertion.
  Repeated identical outages reuse pending/finalized unresolved evidence;
  post-crash finalization makes it PIT-visible, and only a later finalized
  exact-main validation resolves it.
- Step B broad related backend verification in Docker after the follow-up:
  lineage, migration, source guard, history selection, CLI, SEC-egress guard,
  Rate Guard client and startup, and Edgar client `193 passed`.
- Step B standalone Rate Guard verification in Docker: `41 passed`.
- A disposable PostgreSQL schema upgraded from empty to head, downgraded from
  `20260830130000` to `20260830120000`, upgraded back to the single head, and
  reported `20260830130000 (head)` before being dropped.
- Step B used only fakes, temporary local storage, Docker, and isolated database
  schemas. No clean acceptance tooling, real SEC pull, external probe,
  credential test, production mutation, or commit was performed. Compile,
  Compose validation, and `git diff --check` passed.
- Terra Step B independent review: PASS. The trust-boundary reset, retained
  lineage contract, initial no-bytes main-resource outage handling, PIT and
  supersession behavior, storage-integrity failure visibility, migration, and
  local verification evidence are accepted for the self-contained Step3 commit.

## Commit assessment

After Terra PASS, one self-contained Step3 commit is the coherent unit. The
snapshot schema/model, ingestion and replay contracts, Rate Guard cache-age
override, trust-boundary simplification, migration, tests, and authoritative
documentation are mutually dependent. Splitting the scope reset from the
functional implementation would create an intermediate commit whose schema and
tests refer to discarded receipt/attestation mechanisms or whose documentation
does not describe the implemented contract. Terra has passed Step B, so the
single local commit is now authorized; pushing remains out of scope.
