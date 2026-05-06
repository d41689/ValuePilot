# PR #28 CI Oracle's Lens User Fixture

## Goal / Acceptance Criteria

- Fix PR #28 CI backend test failure.
- Oracle's Lens tests must not assume that `users.id = 1` exists.
- Full backend test suite passes in Docker.

## Scope

In:
- Test fixture repair for Oracle's Lens metric facts.
- Type repair for frontend production build failures found by PR #28 CI.
- Verification through the failing test set and full backend tests.

Out:
- Production behavior changes.
- Schema or migration changes.

## Files to Change

- `backend/tests/unit/test_oracles_lens.py`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py::test_oracles_lens_adds_value_line_quality_overlay tests/unit/test_oracles_lens.py::test_oracles_lens_adds_conservative_valuation_reference tests/unit/test_oracles_lens.py::test_oracles_lens_labels_value_line_target_as_reference_not_intrinsic_value tests/unit/test_oracles_lens.py::test_oracles_lens_uses_period_price_for_historical_snapshot`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-06: PR #28 CI failed on four Oracle's Lens tests with `metric_facts.user_id_fkey` violations.
- 2026-05-06: Root cause is `_metric_fact()` hard-coding `user_id=1`, while full CI does not guarantee that user row exists.
- 2026-05-06: Updated the Oracle's Lens fixture to create a real test user and attach that user id to metric facts.
- 2026-05-06: Follow-up CI run passed backend tests and failed production build because `row.confidenceTone` is plain `string` while `Badge.variant` is a typed union.

## Verification

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py::test_oracles_lens_adds_value_line_quality_overlay tests/unit/test_oracles_lens.py::test_oracles_lens_adds_conservative_valuation_reference tests/unit/test_oracles_lens.py::test_oracles_lens_labels_value_line_target_as_reference_not_intrinsic_value tests/unit/test_oracles_lens.py::test_oracles_lens_uses_period_price_for_historical_snapshot` - 4 passed.
- `docker compose exec api pytest -q` - 211 passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` - passed.
