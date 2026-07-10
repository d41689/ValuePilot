# Review results — M1 manager seed lifecycle safety

Reviewer: Codex
Date: 2026-07-09
Scope: `claude/manager-seed-lifecycle-safety` working tree, prompted by
`2026-07-09_manager-seed-lifecycle-safety-review-prompts.md`.

## Verdict

**M1 is not sufficient for M2 yet.** It fixes the original "retired/revoked row
gets resurrected" class, but deploy-time execution still needs a global
seed lock / concurrency strategy, safer identity matching, and clearer handling
of `needs_review` rows before this writer is safe to run automatically on every
API startup/deploy.

Targeted verification run:

```bash
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q \
  tests/unit/test_13f_manager_seed_lifecycle.py \
  tests/unit/test_13f_manager_taxonomy_v2.py::test_seed_confirmed_managers_populates_v2_columns \
  tests/unit/test_13f_dataroma_sync.py::test_bootstrap_whitelist_job_type_uses_offline_seed_path
```

Result: `12 passed in 1.03s`.

Also checked the 82-entry seed file: there are currently **0 normalized-name
collisions inside the seed file itself**. That does not remove the risk below,
because the fallback also matches non-seed rows already present in the database.

## Findings

### P1 — Deploy-time concurrent seed can fail startup on the unique CIK constraint

File/lines:

- `backend/app/services/edgar_ingestion.py:187`
- `backend/app/services/edgar_ingestion.py:254-277`
- `backend/app/models/institutions.py:121`
- `docker-compose.prod.yml:59-61`

Exact row state:

- Fresh or partially fresh database.
- Two API processes run the future M2 startup hook concurrently.
- For the same seed entry, both sessions execute the CIK/dataroma/name lookups
  before either commit, both see no existing row, and both add a new
  `InstitutionManager(cik=<same seed cik>, match_status="confirmed")`.

What re-seed does:

- The function adds duplicate in-memory rows and relies on the database
  `institution_managers.cik` unique constraint to reject one writer.
- There is no `pg_advisory_xact_lock`, JobRun `lock_key`, `ON CONFLICT`, or
  per-row savepoint/`IntegrityError` handling in `seed_confirmed_managers`.

Wrong product/deploy consequence:

- If M2 wires this into `backend/app/main.py` startup or the prod compose
  command, one app process can abort startup during deploy. With
  `restart: unless-stopped`, this can become a crash loop until the winning
  process commits and the losing process retries into the update path. That is
  not a safe deploy-time writer.
- This is the same class already solved elsewhere with locks:
  `_acquire_period_lock()` uses `pg_advisory_xact_lock`, and admin jobs use
  visible `JobRun.lock_key` paths.

Minimum before M2:

1. Acquire a transaction-scoped global seed advisory lock around the whole seed,
   or run the deploy seed through a visible locked `JobRun` with a stable
   `lock_key`.
2. Define the deploy caller's transaction boundary explicitly: open session,
   acquire lock, seed, commit, log/report, rollback on failure.
3. Keep the bad seed JSON failure loud; a bad curated seed file should block the
   automated seed rather than silently starting with stale universe data.

### P1 — `name_normalized` fallback can attach a seed CIK to the wrong manager

File/lines:

- `backend/app/services/edgar_ingestion.py:202-208`
- `backend/app/services/edgar_ingestion.py:218-237`

Exact row state reproduced in `valuepilot_test` with rollback:

```text
existing row before:
  legal_name='Ariel Capital LLC'
  display_name='Ariel Capital'
  name_normalized='ariel'
  cik=NULL
  dataroma_code=NULL
  match_status='candidate'
  status='candidate'

seed entry:
  legal_name='ARIEL INVESTMENTS, LLC'
  cik='0000936753'
  normalized name='ariel'
```

What re-seed did:

```text
before = (id, 'Ariel Capital LLC', 'Ariel Capital', 'ariel', None, 'candidate', 'candidate')
after  = (same id, 'ARIEL INVESTMENTS, LLC', 'John Rogers - Ariel Investments',
          'ariel', '0000936753', 'candidate', 'candidate')
report = {'created': 81, 'updated': 1, 'awaiting_confirmation': 1,
          'skipped_human_decided': 0}
```

Wrong product consequence:

- The real Ariel seed row is not created as a confirmed active manager.
- An unrelated candidate now carries Ariel's CIK and curated classification.
- If the pre-existing row were already `match_status='confirmed'` /
  `status='active'` with a different CIK, seeding would overwrite that active
  manager's CIK and the wrong SEC filer would be ingested/scored.

Why likely enough to block:

- `name_normalized` has no unique constraint.
- `_normalize_name()` strips terms such as `capital`, `management`, `partners`,
  `fund`, and `investments`; many seed names collapse to single tokens
  (`ariel`, `icahn`, `tci`, `ako`, `jensen`, etc.).
- The fallback takes `.order_by(id).first()` with no similarity threshold,
  source filter, or collision report, so the oldest unrelated row wins silently.

Recommended fix:

- Do not use bare `name_normalized` as an automatic update key for identity/CIK
  writes. Use it only to classify "possible_existing_match_needs_review", or
  require a stronger predicate such as same Dataroma code, same current/prior
  CIK, explicit seed alias, or a unique reviewed mapping.

### P2 — `needs_review` is a human lifecycle state but seeding still refreshes it and reports it as `awaiting_confirmation`

File/lines:

- `backend/app/services/edgar_ingestion.py:89-97`
- `backend/app/services/edgar_ingestion.py:218-237`
- `backend/app/services/thirteenf_admin_dashboard.py:624-628`
- `backend/app/services/thirteenf_admin_dashboard.py:2427-2432`
- `backend/tests/unit/test_13f_manager_seed_lifecycle.py:107-120`

Exact row state reproduced in `valuepilot_test` with rollback:

```text
existing seeded row:
  cik='0000936753'
  match_status='needs_review'
  status='needs_review'
  display_name='HUMAN REVIEW DISPLAY'
  style_primary='unknown'
```

What re-seed did:

```text
after = cik='0000936753',
        match_status='needs_review',
        status='needs_review',
        display_name='John Rogers - Ariel Investments',
        style_primary='value_deep'
report = {'updated': 82, 'awaiting_confirmation': 1,
          'skipped_human_decided': 0}
```

Wrong product consequence:

- The lifecycle fields are preserved, but the seed still overwrites identity and
  classification while the row is explicitly parked for human review.
- The report tells an operator this row is "awaiting confirmation", which is not
  the same workflow as "human put this in needs_review".
- The test itself calls this "a human parked this one for review" but does not
  assert that it is skipped whole or reported in a distinct bucket.

Answer on classification:

`needs_review` rows are **not correctly classified today**. They should either
be treated as human-owned lifecycle rows and skipped whole, or reported in a
third bucket such as `needs_review` / `skipped_needs_review`, not mixed into
`awaiting_confirmation`.

### P2 — Admin/deploy observability drops the actionable CIK lists

File/lines:

- `backend/app/services/edgar_ingestion.py:279-286`
- `backend/app/services/thirteenf_admin_dashboard.py:3033-3043`
- `backend/app/cli/edgar.py:49-67`

Exact state:

- Seed report contains `skipped_human_decided_ciks` and
  `awaiting_confirmation_ciks`.
- CLI prints both lists.
- Admin `bootstrap_whitelist` job summary keeps only counts:
  `managers_skipped_human_decided` and `managers_awaiting_confirmation`.

Wrong product consequence:

- An operator seeing `managers_awaiting_confirmation > 0` in a job summary
  cannot identify which managers need action from the stored summary alone.
- In the M2 deploy-time shape, stdout is usually not an operator workflow. If
  these lists do not surface in a visible job, alert, admin task, or health
  signal, the exact failure M1 tries to prevent remains possible: a curator adds
  a manager to JSON, deploy runs, and the manager remains unconfirmed without an
  actionable review target.

Recommended fix:

- Preserve bounded identifier lists in the admin job summary, or create explicit
  admin tasks/alerts for `awaiting_confirmation` and `skipped_human_decided`.

### P3 — README Day-0 instructions still describe the old bootstrap/match flow

File/lines:

- `README.md:64-74`

Problem:

- README still says `bootstrap-whitelist` parses Dataroma and inserts ~80
  superinvestors, then `match-cik` searches EDGAR and marks high-confidence
  managers confirmed.
- Current `bootstrap-whitelist` is a deprecated alias for the offline JSON seed,
  and new seed rows already have `match_status='confirmed'` and CIKs.
- `match_cik_candidates()` only scans `cik IS NULL` and
  `match_status IN ('seeded', 'candidate')`, so it will not process the fresh
  confirmed seed rows.

Wrong operator consequence:

- On a fresh database the README's command order still basically works because
  seed rows are already confirmed, but the explanation is false.
- On a partially bootstrapped database, rows reported as
  `awaiting_confirmation` require admin confirmation; README does not tell the
  operator to inspect that bucket.

## Missing Tests

Highest-value missing tests:

1. **Wrong normalized-name match**: create an unrelated row with
   `name_normalized='ariel'`, no `cik`, no `dataroma_code`; run seed; assert the
   seed does not overwrite that row with Ariel's CIK/name/classification and
   instead reports an ambiguous match.
2. **`needs_review` classification**: put a seeded row into
   `match_status='needs_review'`, `status='needs_review'`; run seed; assert the
   row is skipped whole or reported in a distinct `needs_review` bucket, not
   `awaiting_confirmation`, and identity/classification are not refreshed unless
   that is explicitly chosen.
3. **Concurrent create path**: simulate two sessions seeding an empty database
   and prove either the second waits on a global advisory lock or exits cleanly
   without an uncaught `IntegrityError`. This is the regression test that gates
   M2 startup/deploy wiring.

Useful additional tests:

- Rejected row with no `dataroma_code` and no CIK, found only by
  `name_normalized`, is skipped whole.
- `_echo_seed_report()` prints all buckets, and admin job summary preserves
  enough identifiers for operator action.
- If the ORM listener stops deriving `status='active'` for new confirmed rows,
  the characterization test fails with a message naming the listener dependency.

## Lifecycle Outcome Map

Observed or reachable states after re-seed:

| State | Current outcome | Review judgment |
|---|---|---|
| new seed row | create `match_status='confirmed'`, listener derives `status='active'` | OK, but implicit listener dependency remains load-bearing |
| existing `confirmed` / `active` | identity/classification refreshed; lifecycle unchanged | OK if identity match is strong |
| existing `candidate` / `candidate` | identity/classification refreshed; `awaiting_confirmation` | Deliberate, but risky under weak name fallback |
| existing `inactive` / `inactive` | skipped whole; listed in `skipped_human_decided` | OK |
| existing `rejected` / derived `ignored` | skipped whole; listed in `skipped_human_decided` | OK |
| existing `revoked` / derived `needs_review` | skipped whole via `match_status='revoked'`; listed in `skipped_human_decided` | OK |
| existing `needs_review` / `needs_review` | identity/classification refreshed; listed as `awaiting_confirmation` | Not OK; needs distinct semantics |
| all three keys miss after human rename/re-key | create duplicate confirmed row or collide on unique CIK | Still unsafe without stronger matching/locking |

## Downstream / Recompute Notes

If a future deploy-time seed genuinely adds a manager to the universe, no
downstream recompute is triggered by this change. Existing `ownership_changes`,
Oracle's Lens scores/signals, and readiness metrics may have been computed under
the old manager universe. M2 needs an explicit policy: either seeding is
guaranteed not to change the active universe automatically, or a universe-change
diff queues the affected recomputation jobs and surfaces that in ops.

