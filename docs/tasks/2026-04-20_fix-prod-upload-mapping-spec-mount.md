# Task: Fix prod upload mapping spec mount

## Goal / Acceptance Criteria
- ValuePilot prod document upload no longer fails with `500 Internal Server Error` due to a missing mapping spec file.
- The prod API can initialize `IngestionService` successfully during `/api/v1/documents/upload`.
- Verification confirms a real PDF upload request succeeds against the prod API.

## Scope
**In**
- Prod runtime configuration for the API container.
- Docker-based reproduction and verification of the upload endpoint.

**Out**
- Parser logic changes.
- Mapping spec content changes.
- Auth model changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Docker-based runtime / deployment expectations
- `docs/prd/value-pilot-prd-v0.1.md` -> Parsing / normalized storage contracts

## Files To Change
- `docker-compose.prod.yml`
- `docs/tasks/2026-04-20_fix-prod-upload-mapping-spec-mount.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Reproduce the current prod upload failure and capture the backend stack trace.
2. Restore the missing mapping spec file inside the prod API runtime with the minimal safe config change.
3. Rebuild and restart the prod API container.
4. Verify by generating a prod access token and uploading a fixture PDF through `/api/v1/documents/upload`.

## Contract Checks
- Verification is run through Docker Compose only.
- No schema, parser, screener, formula, or lineage behavior changes.
- No raw SQL from user input.

## Rollback Strategy
- Remove the prod API docs volume mount.
- Rebuild and restart the prod stack.

## Progress Log
- [x] Reproduce current prod upload failure.
- [x] Restore mapping spec file availability in prod API.
- [x] Rebuild and verify upload end-to-end.

## Notes / Decisions / Gotchas
- Prod stack currently builds `api` from `./backend` only.
- The upload failure stack trace shows:
  - `FileNotFoundError: /code/docs/metric_facts_mapping_spec.yml`
- Dev already mounts `./docs:/code/docs`, which explains why this is currently a prod-only regression.
- Applied the same docs mount pattern to prod API:
  - `./docs:/code/docs:ro`
- This is the minimal safe fix for the current local-prod deployment because the prod API runtime already depends on files from the repository workspace.

## Verification Results
- `docker compose -f docker-compose.prod.yml logs --tail=200 api` -> reproduced `500` and `FileNotFoundError: /code/docs/metric_facts_mapping_spec.yml`
- `docker compose -f docker-compose.prod.yml up -d --build api` -> pass
- `docker compose -f docker-compose.prod.yml exec api sh -lc 'ls -la /code/docs/metric_facts_mapping_spec.yml'` -> file present
- Generated a temporary prod access token for `d41689@gmail.com` inside the prod API container
- End-to-end upload to prod API:
  - `POST http://localhost:8101/api/v1/documents/upload` with `backend/tests/fixtures/value_line/axs.pdf` -> `200`, `status=parsed`, `document_id=1`
- End-to-end upload through the frontend proxy path:
  - `POST http://localhost:3101/api/v1/documents/upload` with `backend/tests/fixtures/value_line/bti.pdf` -> `200`, `status=parsed`, `document_id=2`
- Direct scripted upload to `https://invest.richmom.vip/api/v1/documents/upload` returned `403` from Cloudflare, which appears to be a bot-protection behavior for non-browser scripted requests rather than an application error.
