# 13F MVP4-10: Conftest Savepoint Hardening

## Status

Authorized as a parallel pre-MVP4-03 prerequisite per the MVP4
decision gate's revised task sequence. No external deps; pure test
infrastructure.

## Goal / Acceptance Criteria

Eliminate the four
`SAWarning("transaction already deassociated from connection")`
events that the test suite currently emits at teardown. They are
structurally benign (no data leak between tests) but indicate the
test fixture's connection-level transaction is being mishandled
when production-code paths call `session.rollback()` /
`session.commit()` mid-test. MVP4-03 onward will introduce more
write-path services (`oracles_lens_score_backfill`), which will
multiply the same pattern; cleaning the fixture up now stops the
noise from compounding.

Acceptance criteria:

- `backend/tests/conftest.py` `db_session` fixture wraps the test
  in a SAVEPOINT-based nested transaction (PG `SAVEPOINT` semantics
  via SQLAlchemy `connection.begin_nested()`).
- Each `session.commit()` / `session.rollback()` inside production
  code under test stays scoped to the savepoint; the outer
  connection-level transaction remains intact for teardown.
- The fixture **API is unchanged** — it still yields the same
  `Session` instance to test functions. Tests do not need
  modification.
- After the change, `pytest -q` reports **zero**
  `SAWarning("transaction already deassociated")` events
  (currently 4).
- Total backend test count stays at 669 with no regressions. Any
  test that fails because it relied on the old leaky-commit
  behavior must be diagnosed before being adjusted.
- MVP4-09's "rollback-inside-IntegrityError-translator" pattern
  (used by MVP3-05 batch reparse, MVP3-07 historical backfill,
  MVP4-01 unique-constraint test) works under the new fixture
  without emitting warnings.

## Scope In

- `backend/tests/conftest.py` only — the `db_session` fixture.
- No production-code changes.
- No test-file changes (existing tests must work unchanged).

## Scope Out

- Frontend test infrastructure.
- Production-code transaction patterns.
- Refactoring production services to remove the explicit
  `session.rollback()` calls in the IntegrityError translators —
  those are correct in production where there is no outer
  connection-level transaction.
- PRD edits, schema migrations.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D6: this is the
  promoted-to-MVP4-backlog ticket flagged by the Tech Lead end-to-end
  review.
- Tech Lead end-to-end review item 7 (SME C2 follow-on): "structurally
  benign... the correct fix is to restructure conftest to use
  connection.begin_nested() (savepoints) so service-level rollbacks
  don't reach the outer connection transaction. Defer to a focused
  conftest hardening task in the MVP4 backlog, not a merge blocker."

## Files Expected To Change

- `backend/tests/conftest.py` — fixture rewrite.
- This task file.

## Test Plan

- `docker compose exec api pytest -q` (full suite — confirm 669
  passed, zero target SAWarning).
- `docker compose exec api pytest -q tests/unit/test_13f_holdings_parser.py::test_duplicate_fingerprint_within_same_parse_run_raises tests/unit/test_13f_mvp3_batch_reparse.py::test_enqueue_translates_unique_index_race_into_scope_error tests/unit/test_13f_mvp3_historical_backfill.py::test_enqueue_translates_unique_index_race tests/unit/test_13f_mvp4_score_schema.py::test_unique_constraint_on_stock_quarter_version`
  (targeted — these were the 4 emitting the warning).

## Progress Notes

- 2026-05-11: Started after MVP4-09 landed. SQLAlchemy 2.0.49 in
  the container — both `join_transaction_mode="create_savepoint"`
  and the `after_transaction_end` listener pattern available;
  picking the listener pattern for clarity and to match the
  historically-documented SQLAlchemy testing recipe.
- 2026-05-11: First implementation used the `after_transaction_end`
  listener pattern. Reduced the warning count from 4 to 2, but the
  remaining 2 (in `test_duplicate_fingerprint_within_same_parse_run_raises`
  and `test_enqueue_translates_unique_index_race_into_scope_error`)
  surfaced a different warning: `SAWarning('nested transaction
  already deassociated from connection')` — the production code
  itself calls `session.begin_nested()` (e.g. the holdings ingest
  savepoint at `thirteenf_holdings_ingest.py:119`), creating a
  multi-level nesting the listener's `trans._parent.nested` check
  didn't handle correctly.
- 2026-05-11: Switched to the simpler SQLAlchemy 2.0 recipe
  `join_transaction_mode='create_savepoint'` on the Session. Every
  Session-level `commit()` / `rollback()` operates on a SAVEPOINT
  instead of touching the outer connection-level transaction;
  production-side `begin_nested()` stacks as nested SAVEPOINTs as
  it would in production. No after_transaction_end listener needed.
  The fixture is now 8 lines shorter than the prior version and
  emits zero SAWarning events.
- 2026-05-11: Scope guard — no production-code change, no test-file
  change, no schema, no API, no frontend, no PRD edit.

## Verification Results

- Targeted (the 4 previously-warning tests):
  `docker compose exec api pytest -q tests/unit/test_13f_holdings_parser.py::test_duplicate_fingerprint_within_same_parse_run_raises tests/unit/test_13f_mvp3_batch_reparse.py::test_enqueue_translates_unique_index_race_into_scope_error tests/unit/test_13f_mvp3_historical_backfill.py::test_enqueue_translates_unique_index_race tests/unit/test_13f_mvp4_score_schema.py::test_unique_constraint_on_stock_quarter_version`
  → 4 passed, 0 warnings.
- Full suite:
  `docker compose exec api pytest -q` → 669 passed in 53.93s,
  **0 warnings**. Down from 4 SAWarnings; the "warnings summary"
  section of the pytest output is gone entirely.
- No production-code regressions; same 669 tests pass that passed
  pre-MVP4-10.
