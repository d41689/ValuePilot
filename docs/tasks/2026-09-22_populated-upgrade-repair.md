# Populated upgrade repair — 2026-09-22

## Goal / acceptance

Unblock the existing production upgrade from revision 20260904140000 without losing retained facts or bypassing authority checks. A populated synthetic database must upgrade in one Alembic invocation to head, preserving fact IDs, exact values, separate fiscal-period currentness, immutable extraction provenance, report identity bindings, and conservative knowledge-time metadata. The SEC reciprocal trigger must remain enabled and initially deferred after commit. Invalid authority must still fail and migrations remain atomic.

## Scope / authorization

The user explicitly included this migration repair in the current branch consolidation and authorized continuing the merges after repair. Use a separate focused PR before S2 #149, MCO #148, Lab #150 and Business Economics. No manual production data repair, deletion, trigger disabling, revision stamping, clock changes or acquisition. Production receives the reviewed repair through the existing automatic deployment only. This protects trustworthy historical economics and source-traceable investor research.

The failure is observed in deploy34502087251 and reproduced with two synthetic FY facts in a disposable Docker PostgreSQL. Migration170000 updates retained facts and queues the initially deferred SEC reciprocal trigger; migration180000 then attempts table DDL. Migration120000's immediate-constraint setting belonged to an earlier committed invocation and cannot protect the deployed140000 starting point.

## Files / design

- `backend/alembic/versions/20260904180000-value-line-fact-time-authority.py`: drain only the named reciprocal constraint before DDL. Keep the same schema/data semantics and one atomic upgrade transaction. This changes an existing migration's execution ordering because a later migration cannot repair an earlier failing upgrade.
- `backend/tests/unit/test_value_line_fact_time_authority_migration.py`: populated deployed-baseline regression using isolated test schemas and synthetic data; test first.
- `.github/workflows/ci.yml`: the same bounded30→45minute allowance already reviewed in S2/MCO, needed for the full suite; no gates changed.
- This task record: root owns delivery evidence and sign-off.

## Test plan / stop rule

Prove new regression fails on original migration, then passes with named-constraint drain. Verify populated140000→head and relevant existing migration tests in an explicitly disposable Docker database, not shared development or production. Independent adversarial review checks atomicity, validation timing, upgrade paths and invariant preservation. Final CI executes exactly:

```sh
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

CI also runs Rate Guard tests/topology. Merge only after final-tree gates and review pass; inspect main CI and automatic deployment. Stop after this prerequisite is delivered and continue the authorized consolidation. Known local clock instability remains separately recorded; do not weaken cutoff/currentness guards or use backdating.

## Evidence

Prior diagnostic probe: original upgrade failed with pending-trigger ObjectInUse and rolled back to140000; temporary one-line repair passed140000→180000 and one-pass140000→head, preserving two current fiscal periods. This is synthetic evidence, not a production-data rehearsal or full CI certificate. Repository regression and final gates pending.

Repository test-first evidence: new populated140000→head regression failed at the original180000 ALTER with the exact pending-trigger error. With the named constraint drain it passes; the whole migration test file passes **5 tests, 2 existing warnings**, in10.28s using a private disposable PostgreSQL18 container. Checks cover two distinct current fiscal periods, exact values, extraction/parse lineage, report identities, conservative known-at stamps, null retained-row transaction IDs, and enabled/initially-deferred trigger enforcement. The existing empty-schema upgrade/downgrade test remains intact. A test-fixture correction made the deliberately invalid SEC fact owner NULL, so the negative reaches the intended publication-reciprocity guard instead of failing an unrelated owner constraint. No production/shared database touched. Independent review and canonical CI follow in the PR.
