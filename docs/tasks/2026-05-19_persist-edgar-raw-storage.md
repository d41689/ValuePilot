# 2026-05-19 — Persist EDGAR raw storage across deploys

## Goal

Stop wiping `/code/storage/edgar_raw/` on every prod deploy. The 13F `fetch_quarter_index` job for 2025-Q4 failed with:

```
[Errno 2] No such file or directory:
'/code/storage/edgar_raw/edgar/45/458789480666fa44a7926995ef2bd81312dfa2038c64992a08c6ad5ded3e5ac1.txt'
```

surfaced as a P1 admin task on https://invest.richmom.vip/admin/13f .

## Root cause

`docker-compose.prod.yml` only bind-mounts `./storage/uploads:/code/storage/uploads` for the `api` service. The EDGAR fetcher writes raw filings to `/code/storage/edgar_raw/<source>/<sha[:2]>/<sha>.<ext>` (see `backend/app/edgar/fetcher.py:_storage_path`) and stores that absolute path in `raw_source_documents.body_path` (Text column). Because the directory is **not** bind-mounted, it lives inside the container's writable layer, which is discarded on every `docker compose up --build` (every merge to `main` via `.github/workflows/deploy.yml`).

Downstream pipeline stages (`load_body` and anything that re-reads cached bytes by `body_path`) then ENOENT on every deploy.

Dev (`docker-compose.yml`) silently masked the bug because the entire `./backend` directory is mounted at `/code`, so dev's `edgar_raw/` lives at `./backend/storage/edgar_raw/` on the host and persists automatically.

## Scope

In:
- Add `./storage/edgar_raw:/code/storage/edgar_raw` to the `api` service in both `docker-compose.prod.yml` and `docker-compose.yml` (dev/prod parity).
- Gitignore `storage/edgar_raw/`.

Out:
- Re-running the failed 2025-Q4 job (manual operator step after deploy).
- The other admin tasks (P2 historical backfill, P3 extended backfill).
- General refactor of the storage layout.
- Backfill of any other already-purged raw artifacts (DB `body_path` rows pointing into the void will heal lazily as each job re-fetches).

## Files changed

- `docker-compose.prod.yml` — add `edgar_raw` bind mount to the `api` service.
- `docker-compose.yml` — add same mount to the `api` service so dev matches prod and stops relying on the implicit `./backend:/code` cover.
- `.gitignore` — add `storage/edgar_raw/`.

## Test plan

- `docker compose up -d --build` succeeds locally; `docker compose exec api ls -la /code/storage/edgar_raw` shows the bind-mounted dir.
- `docker compose exec api pytest -q` (full backend suite) stays green; the change is config-only, no code paths altered.

## Post-deploy operator steps (out of this PR's diff, but required to clear the P1)

After merge auto-deploys via `.github/workflows/deploy.yml`:

1. Open https://invest.richmom.vip/admin/13f .
2. Set target quarter to **2025-Q4**.
3. Click **Fetch quarter index** under "Quarter pipeline".
4. Re-trigger the downstream job that originally failed (it will re-fetch the missing SHA-256 blob via the live EDGAR path because `body_path` resolution now hits a persisted directory).

Document this in the PR description so huawang has a checklist.
