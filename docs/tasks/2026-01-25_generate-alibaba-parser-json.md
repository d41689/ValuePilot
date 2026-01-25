# Task: Generate Alibaba Value Line parser fixture JSON

## Goal / Acceptance Criteria
- Run the project Value Line v1 parser on `backend/tests/fixtures/value_line/alibaba.pdf`.
- Persist the resulting parsed page JSON to a fixture file (`*.parser.json`) under `backend/tests/fixtures/value_line/`.
- Output is generated via Docker Compose (no host Python execution).

## Scope
### In
- Invoking the existing Value Line v1 parser pipeline to generate a deterministic JSON artifact for the Alibaba fixture PDF.

### Out
- Changing parsing logic, schema, or metric mappings.
- Adding/adjusting expected fixtures or tests for Alibaba (not requested).

## Files To Change
- `backend/tests/fixtures/value_line/alibaba_v1.parser.json` (new)
- `docs/tasks/2026-01-25_generate-alibaba-parser-json.md` (this file)

## Execution Plan
1. Start containers: `docker compose up -d --build`
2. Generate JSON via existing dump script:
   - `docker compose exec api python scripts/value_line_dump_axs.py --pdf tests/fixtures/value_line/alibaba.pdf --out tests/fixtures/value_line/alibaba_v1.parser.json`
3. Sanity-check output (valid JSON, non-empty).
4. Run tests: `docker compose exec api pytest -q`

## Test Plan (Docker)
- `docker compose up -d --build`
- `docker compose exec api python scripts/value_line_dump_axs.py --pdf tests/fixtures/value_line/alibaba.pdf --out tests/fixtures/value_line/alibaba_v1.parser.json`
- `docker compose exec api pytest -q`

## Notes / Decisions
- Reused `scripts/value_line_dump_axs.py` because it already exercises the canonical `PdfExtractor -> ValueLineV1Parser -> build_value_line_page_json` pipeline and supports `--pdf/--out` overrides.

## Progress Log
- 2026-01-25: Task created.
- 2026-01-25: Generated `backend/tests/fixtures/value_line/alibaba_v1.parser.json` via `docker compose run --rm --no-deps api python -m scripts.value_line_dump_axs ...`.
- 2026-01-25: Verified in Docker: `docker compose run --rm --no-deps api pytest -q` (86 passed).

## Gotchas
- `docker compose up -d --build` failed because the `web` image build attempted to pull `node:20-alpine` but Docker Hub auth DNS resolution failed (`auth.docker.io: no such host`). This task used the already-built `api` image and `--no-deps` to avoid `web`/`db` pulls while still running the parser and test suite in containers.
