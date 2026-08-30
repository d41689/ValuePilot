# Parsing — detail

Detail behind **AGENTS.md → "Parsing"**.

## Parser fixture alignment workflow (required)

When asked to align a parser to an expected fixture, use project scripts inside
Docker. Do NOT use OS-level `diff` for JSON comparisons.

- Generate `*.parser.json`: `docker compose exec api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/<name>.pdf --out tests/fixtures/value_line/<name>_v1.parser.json`
- Key-by-key JSON diff: `docker compose exec api python -m scripts.json_diff tests/fixtures/value_line/<name>_v1.expected.json tests/fixtures/value_line/<name>_v1.parser.json tests/fixtures/value_line/<name>_v1.diff.json`
- Iterate: use the diff JSON as the source of truth for mismatched paths/values.
  Adjust parser code minimally (TDD), regenerate, re-run, repeat until the diff
  is `{}`.
- Verify with `docker compose exec api pytest -q` (or the targeted fixture test)
  during iteration; full suite at the closing gate per the Verification section
  of `AGENTS.md`.

## EDGAR / 13F pipeline gotchas

- `shrsOrPrnAmt` is a wrapper element in infotable XML; unwrap it to read
  `sshPrnamt` / `sshPrnamtType`.
- `xslForm13F_X02/` paths in EDGAR filing index are XSLT-rendered HTML, not
  machine-readable XML — skip them when scanning for infotable URLs.
- `cusip_ticker_map.source` is VARCHAR(50); valid source strings: `"openfigi"`,
  `"sec_co_tickers"`, `"manual"`. Dataroma is not a CUSIP or security-identity
  source.
- Kahn Brothers (`0001039565-*`) reports values in dollars, not thousands —
  reconciliation warnings for this filer are True Positives, not bugs.

## EDGAR financial-filing lineage gotchas

- Read the permission and product boundary in
  `docs/architecture/coverage-source-policy.md` and PRD §H before expanding the
  form set, coverage universe, retention policy, or consumers.
- An accession `index.json` item's `type` may describe the index icon (for
  example `text.gif`) rather than the SEC exhibit type. Retention therefore
  uses the reviewed primary-document name and approved XBRL filename suffixes;
  the complete index remains retained as evidence of the manifest.
- Retain both the issuer-wide submissions payload that discovered the filing and
  the accession index. A hash column alone is not a replayable raw artifact.
  Submissions snapshots are immutable discovery lineage, not a per-filing parse
  input: their changing content identity must not alter an unchanged accession's
  artifact manifest or parse-run identity. The accession index and retained
  filing artifacts remain the exact per-filing inputs.
  A fetched payload that cannot be decoded or parsed is still retained and
  linked to a bounded typed acquisition-failure audit row; it must not create a
  filing, parse run, raw fact, or queryable metric fact.
  If the initial canonical `CIK<CIK>.json` request fails before any bytes exist,
  the operation instead retains a canonical no-bytes main-resource anchor and
  a typed `submissions_fetch` failure. The anchor is not a snapshot and cannot
  make `no_eligible_filings` finalizable; it exists only to make the legitimate
  outage durable, separately finalizable, PIT-visible, and exactly resolvable
  by a later successful fetch of that same main resource.
  Once the main payload is retained, a later historical or accession-index
  fetch outage follows the same terminal contract and must not strand an
  unfinalizable pending operation. Every earlier successful payload remains
  retained. Failure ownership follows the operation's explicit snapshot link,
  so a byte-identical historical snapshot may be reused by a later operation
  without changing its immutable creation lineage.
  Acquisition failures and their resolutions are scoped durably rather than
  cleared by any later issuer operation. Submissions failures use the exact
  normalized main/historical source URL and resource role; accession failures
  retain accession plus acquisition phase/resource. Only a finalized exact
  source validation, or a terminal parse for the same accession, resolves that
  scope. A different accession, different historical URL, or unrelated
  no-filings operation does not. PIT projection also requires the failure's
  reviewed identity to remain the terminal effective identity at the cutoff.
  Finalize order is not causal order: a resolution and its database-stamped
  accession attempt must have been created no earlier than the failure it
  resolves. Each accession attempt belongs to the current operation and records
  the index resource/hash, input-manifest hash, outcome, terminal run or index
  failure, and exact retained artifact links. Reusing an identical prior run is
  explicit attempt evidence, not an empty operation borrowing an old result.
  Artifact failures are likewise evidence-backed: the typed reason must match
  the same filing's unavailable/rejected artifact observation. A retained URL
  cannot represent failure, and a source-less synthetic key is accepted only
  when the database recomputes its filename hash exactly.
- The backend application, PostgreSQL application/admin roles, Rate Guard,
  deployment host/admins, and authorized developers are trusted infrastructure.
  This ingestion contract handles malformed or identity-conflicting SEC bytes,
  upstream limits/outages, stale cache, ordinary corrections and duplicates,
  concurrency/crash/finalize behavior, small clock skew, and missing or corrupt
  retained files. It does not try to defend against arbitrary writes or code
  execution inside that trusted boundary, malicious administrators, stolen
  internal keys, or signature forgery. Accordingly, transport receipts,
  backend signing authorities, validation keyrings, and cryptographic replay
  gates are not part of the design.
- A submissions resolution is established by ordinary deterministic validation:
  reread the controlled content-addressed file, verify its recorded byte size
  and SHA-256, parse it, verify the canonical role/URL and reviewed CIK, and for
  historical payloads verify its exact reference in the retained main payload.
  The resolution remains operation/snapshot scoped and PIT-visible only after
  normal commit and finalize boundaries.
- Treat an SEC-declared artifact size as an integrity assertion: the fetched
  byte length must match exactly or the observation is rejected and excluded
  from parsing. Reuse also verifies stored length and SHA-256.
- Before reuse, revalidate the accession index and every retained parser input
  through the authorized Edgar client and Rate Guard. The manifest identity
  includes the actual fetched content SHA and byte size, not only index metadata;
  a same-length upstream correction therefore appends a new observation and run.
  The revalidation request may bypass a stale response-cache entry, but it never
  bypasses Rate Guard's SEC allowlist, aggregate limiter, retries, or global
  pause.
- Forced revalidation uses Rate Guard's normal authenticated fetch path with
  `max_cache_age_s=0`. Rate Guard remains the sole SEC transport path and still
  applies its allowlist, aggregate limiter, retries, and global pause. The API
  verifies actual returned SHA-256/size and uses those bytes for manifest
  identity; no separate receipt authority is needed inside the trusted boundary.
- Success, failure, suppression, earliest-boundary, and operator replay use the
  same attempt/resolution/input ownership checks. Each selector rereads every
  controlled retained input and verifies file existence, byte size, any
  SEC-declared size, and SHA-256. A missing, truncated, or same-size corrupted
  file makes the evidence ineligible and surfaces the typed
  `retained_artifact_integrity_failure`; it cannot silently fall back to older
  evidence for that filing.
- A non-NULL `sec_filing_artifacts.source_url` is byte-for-byte the canonical
  SEC Archives URL reconstructed from reviewed CIK integer form, dashless
  accession, and a strict safe filename; the synthetic accession-index row maps
  to `index.json`. URL parser equivalence is intentionally insufficient.
- A parse-run checksum is not its input lineage. Persist every retained input
  through `sec_financial_parse_run_artifacts`; raw facts must reference one of
  those exact inputs. Commit a terminal run, its knowledge-timestamped input
  relationships, and its raw facts atomically under an immutable ingestion
  operation. The operation remains PIT-invisible until a separately committed,
  database-timestamped availability marker exists. Operator reruns recover
  committed pending operations idempotently; replay fails closed while any
  operation remains pending. The deferred database check makes
  the terminal `fact_count` agree with the evidence rows and prevents a later
  transaction from manufacturing either the relationship or the facts. Do not
  infer atomicity from caller-supplied timestamps: the database overwrites the
  run/link/fact creation metadata and requires one transaction identity across
  the group.
- A NULL parse-run operation is legacy state, not a general compatibility
  bypass. Only IDs captured in the immutable migration allowlist are eligible;
  the database rejects every new NULL-operation run and PIT selectors exclude
  any unmarked row.
- PIT selection validates the filing's own reviewed identity and cuts off both
  knowledge time and database creation time for every parse-input relationship.
- Exact failed-run replay remains a typed failure. Historical submissions
  discovery is separately request-bounded even when its filing-result limit has
  not yet been met. Preserve referenced filenames until service validation;
  preserve array index plus a fixed invalid-record code when a reference is not
  an object or has a missing, non-string or empty `name`. Unsafe paths,
  malformed names and cross-CIK references remain typed failures rather than
  silently becoming “no filing found”.
- Inline-XBRL concept prefixes are document-local. Preserve the resolved
  namespace URI, transformation format, language/continuation reference, and
  structured unit meaning (including divided units) before FT-04 mapping.
- Raw XBRL is never canonical financial truth. Only an approved FT-04 mapping
  may publish it into `metric_facts`; product consumers must not query the raw
  lineage tables.
