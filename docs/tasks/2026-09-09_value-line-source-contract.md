# Value Line source-contract consistency

## Goal

Make research coverage and source reconciliation recognize the same persisted
Value Line source labels as the canonical current-document policy. A normal
`process_upload` document (`source="upload"`) must satisfy coverage after a
successful parse, and a valid exact-lineage document with a normalized legacy
`Value Line` label must remain authorized for reconciliation.

## Acceptance criteria

- A current, parsed, owned `upload` document satisfies current Value Line
  coverage.
- Archive, source withdrawal, ownership mismatch, identity review, failed parse,
  and unknown-source states remain fail-closed.
- Reconciliation uses the shared Value Line source vocabulary with
  case-normalization and preserves exact parse-run lineage requirements.
- No account, retention, provider, SEC/13F, or production behavior is added.

## Scope

### In

- `research_coverage.py` removal of its contradictory source-name filter.
- One shared source-label normalization helper used by reconciliation.
- Focused coverage and reconciliation regressions.

### Out

- Account erasure and R26 inventory, locked-24 acceptance, new source/provider
  activation, broad permission workflows, data rewrites, and frozen PR #128
  implementation.

## Test plan

Tests first, in Docker:

1. Focused coverage/reconciliation tests for red and green checkpoints.
2. `docker compose up -d --build`
3. `docker compose exec -T api alembic upgrade head`
4. `docker compose exec -T api pytest -q`
5. `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
6. `docker compose exec -T web npm run lint`
7. `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`

## Decisions and sign-off trail

- 2026-09-09: final cross-delivery review found two consumers carrying narrower
  source-label rules than `current_value_line_document_predicate`. Keep the
  canonical policy authoritative; do not broaden lifecycle or lineage rules.
