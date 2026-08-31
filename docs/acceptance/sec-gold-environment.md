# SEC financial gold-set acceptance environment

This environment is reserved for the locked SEC financial gold set. It uses a
separate disposable database on the existing shared PostgreSQL instance and a
run-specific content directory. It never uses, migrates, stamps, or cleans the
shared development `valuepilot` database.

The separate database is intentional. `AGENTS.md` and the shared-infra contract
require one shared PostgreSQL service with isolation by database and role; they
forbid starting a project-local PostgreSQL service. A schema inside `valuepilot`
would still modify the drifted development database, so it is not an acceptable
acceptance boundary.

## Lifecycle

Choose a unique lowercase run ID containing only letters, digits, and hyphens.
The script derives every target; it never accepts a raw database name or cleanup
path.

```sh
scripts/sec_gold_acceptance.sh fingerprint-shared
scripts/sec_gold_acceptance.sh create step-d-20260830
scripts/sec_gold_acceptance.sh verify step-d-20260830
scripts/sec_gold_acceptance.sh roundtrip step-d-20260830
scripts/sec_gold_acceptance.sh test step-d-20260830
```

Creation refuses existing targets, creates
`valuepilot_acceptance_step_d_20260830` from `template0`, assigns the existing
`valuepilot` role, provisions the exact storage target, and runs the shared
acceptance preflight before the first Alembic command. Only then does it run
`alembic upgrade head` in Docker and verify exactly one head. Storage is mounted only from
`storage/sec_gold_acceptance/step-d-20260830`. The acceptance Compose override
disables schedulers/workers, disables a Rate Guard fallback, and configures one
Rate Guard endpoint.

The same preflight runs before every migration roundtrip leg, focused test,
gold-case ingestion, and acceptance report. It derives the exact PostgreSQL URL
and storage path from the validated run ID and requires all of the following to
agree: explicit acceptance mode, configured run ID/database/storage, the URL's
database, PostgreSQL `current_database()`, `EDGAR_RAW_STORAGE_DIR`, and the live
non-symlink directory. Any Rate Guard fallback setting is forbidden. A standard
API container therefore cannot be turned into an acceptance writer merely by
passing a syntactically valid `--acceptance-run-id`.

Step D pins one verified Rate Guard identity for the entire run and captures
stable before/after runtime snapshots. The local Rate Guard configuration used
when the central service is operationally unavailable remains a single explicit
route: fallback settings stay disabled, EDGAR remains at 1 request/second, and
the same retry/global-pause policy applies. A central-service failure is recorded
in the source-path proof before selecting that route; operators must not probe
for alternate SEC paths.

Run one case or the complete locked manifest through the normal operator path:

```sh
scripts/sec_gold_acceptance.sh snapshot step-d-20260830 before
scripts/sec_gold_acceptance.sh run-case step-d-20260830 aapl-primary 1
scripts/sec_gold_acceptance.sh run-pass step-d-20260830 1
scripts/sec_gold_acceptance.sh run-pass step-d-20260830 2
scripts/sec_gold_acceptance.sh snapshot step-d-20260830 after
scripts/sec_gold_acceptance.sh audit step-d-20260830
```

Only `run-case` and `run-pass` request SEC data. They must not be used during
Step C. The batch command bootstraps only the 24 locked Stock rows into the
otherwise empty acceptance database, is resumable from already written case
reports, and runs cases sequentially. Exit 2 is a durable typed incomplete case
and does not stop later locked cases; any operational exit stops the batch. Each
pass writes case JSON and text under `reports/pass-1/` or `reports/pass-2/`.
After all cases, `run-pass` re-reads all 24 pass reports, validates each report's
run/case/pass identity, and derives the terminal exit from their typed gaps and
failures. Resuming from existing incomplete reports therefore still exits 2;
missing, malformed, or identity-conflicting reports fail closed. The application
still obtains every SEC byte only through the pinned Rate Guard.

Cleanup is exact and retry-safe:

```sh
scripts/sec_gold_acceptance.sh destroy step-d-20260830
scripts/sec_gold_acceptance.sh destroy step-d-20260830
scripts/sec_gold_acceptance.sh fingerprint-shared
```

It force-drops only the derived acceptance database, removes only the derived
storage directory, and removes only the run-specific Compose project resources.
The second cleanup is a no-op success. A failed or interrupted creation must be
cleaned with this exact command before the run ID can be reused.
Cleanup runs the same target/configuration validation first; when the database
still exists it also verifies its live identity. The administrative connection
must report the `postgres` control database before the exact derived database
can be dropped.

## Time and report contract

`filing_selection_as_of` is a historical eligibility question: which filings
the locked case is allowed to select. It is not evidence knowledge time.
PostgreSQL overwrites `operation_attempted_at` when the operation is inserted.
The separately committed finalization row supplies `evidence_available_at`; the
current implementation's finalization instant is that same database-stamped
boundary and is also reported as `evidence_finalized_at`. No caller timestamp
can backdate either boundary. New evidence is unavailable immediately before
that boundary and available at or after it.

Each stable JSON report includes:

- schema, run, case, stock, CIK, and operation identifiers;
- selection cutoff and operation attempted/finalized/available timestamps;
- expected completed fiscal years;
- selected accessions, report dates, accepted timestamps, and forms;
- bounded typed coverage gaps and other failures;
- filing, artifact, parse-run, raw-fact, and `metric_facts` counts.

The CLI prints the same fields as a compact human summary. A typed gap or failure
still produces the existing incomplete exit status after the report is written.
`metric_facts_published` must remain zero until a separately approved FT-04
mapping exists.

The aggregate JSON/text additionally verifies every retained submissions and
filing object by current local existence, byte size, and SHA-256; reports fiscal
year coverage, parser outcomes and raw-fact counts; compares pass-two creation
deltas; checks filing/artifact/parse-run/raw-fact duplicate identities; and
records exact cumulative Rate Guard request/403/429/503 counters. Aggregate
validation does not trust report creation counters: for each pass it resolves
the exact finalized operation and issuer, verifies selected accessions against
operation-owned attempts, counts snapshots and parse runs by direct ownership,
counts raw facts through owned parse runs, and counts append-only filings and
artifacts within the attempt scope using PostgreSQL creation transaction identity
(`xmin`) against the operation's stored `created_txid`. Snapshot/artifact link,
attempt, parse-run, and terminal-result transaction ownership is also checked.
The DB-recomputed counts must match every report field before pass-two
idempotency can pass. Validation also fails on retained integrity, duplicate
lineage, route identity, rate policy, or the zero-`metric_facts` contract. The
acceptance database and storage remain intact until review explicitly authorizes
the exact cleanup.
