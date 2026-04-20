# Task: Bind ValuePilot prod to invest.richmom.vip

## Goal / Acceptance Criteria
- `invest.richmom.vip` routes through the existing local `cloudflared` tunnel to the ValuePilot prod web service.
- ValuePilot prod is reachable on the host port expected by the tunnel configuration.
- The ValuePilot prod frontend continues to proxy `/api/v1/*` requests to the prod API correctly.
- Verification is performed with Docker Compose and local tunnel configuration checks.

## Scope
**In**
- Local `cloudflared` ingress configuration for the existing tunnel.
- ValuePilot prod stack startup / verification.
- Minimal repo changes only if needed to make the prod binding work reliably.

**Out**
- PRD changes.
- Cloudflare dashboard-only manual documentation outside the machine and repo.
- Unrelated application feature changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Docker-based runtime / deployment expectations

## Files To Change
- `docs/tasks/2026-04-20_bind-prod-domain-invest-richmom-vip.md` (this file)
- `/Users/huawang/.cloudflared/config.yml`
- `.env` (local runtime file, gitignored)

## Execution Plan (Assumed approved per direct deployment request)
1. Inspect the existing `study.richmom.vip` tunnel mapping and confirm the ValuePilot prod host port.
2. Add the required `invest.richmom.vip` ingress entry to the local `cloudflared` config.
3. Ensure the DNS route exists for `invest.richmom.vip` on the active tunnel.
4. Start or verify the ValuePilot prod stack with Docker Compose.
5. Validate local reachability on the bound host port and confirm the tunnel config is ready to serve the new hostname.

## Contract Checks
- Verification commands use Docker Compose for the application runtime.
- No schema, parser, screening, formula, or lineage behavior changes.
- No raw SQL or eval/exec changes are introduced.

## Rollback Strategy
- Remove the `invest.richmom.vip` ingress entry from `~/.cloudflared/config.yml`.
- Delete the tunnel DNS route for `invest.richmom.vip` if it was created.
- Stop the ValuePilot prod stack if it was started only for this binding.

## Progress Log
- [x] Inspect existing local tunnel config and ValuePilot prod compose port mapping.
- [x] Add `invest.richmom.vip` ingress entry and DNS route.
- [x] Start / verify ValuePilot prod stack.
- [x] Confirm local reachability and record results.

## Notes / Decisions / Gotchas
- Existing tunnel config already routes:
  - `api.richmom.vip` -> `http://localhost:8080`
  - `study.richmom.vip` -> `http://localhost:3080`
- Current `docker-compose.prod.yml` exposes ValuePilot web on `${HOST_WEB_PORT:-3101}:3000`, so the new hostname should target `http://localhost:3101`.
- `docker compose -f docker-compose.prod.yml config` currently fails unless a root `.env` file exists because the compose file lists `.env` under `env_file` for both `web` and `api`.
- Added local tunnel ingress:
  - `invest.richmom.vip` -> `http://localhost:3101`
- Added the tunnel DNS route with:
  - `cloudflared tunnel route dns mathpilot-tunnel invest.richmom.vip`
- Restarted the existing LaunchAgent-managed tunnel process with:
  - `launchctl kickstart -k gui/501/com.huawang.cloudflared.mathpilot-tunnel`
- Added a minimal local `.env` file so the prod compose stack can start on this machine.
- The prod frontend still logs a pre-existing Next.js warning:
  - `"next start" does not work with "output: standalone" configuration. Use "node .next/standalone/server.js" instead.`
  - This did not block startup; the app reached `Ready`.

## Verification Results
- `cloudflared tunnel ingress validate` -> `OK`
- `cloudflared tunnel route dns mathpilot-tunnel invest.richmom.vip` -> CNAME created for the active tunnel
- `docker compose -f docker-compose.prod.yml config` -> pass
- `docker compose -f docker-compose.prod.yml up -d --build` -> pass
- `docker compose -f docker-compose.prod.yml ps` -> `api` and `web` both `Up`
- `curl -sS http://localhost:8101/health` -> `{"status":"ok"}`
- `curl -I http://localhost:3101` -> `307 Temporary Redirect` to `/home`
- `curl -I https://invest.richmom.vip` -> `307 Temporary Redirect` to `/home`
- `curl -d '{}' https://invest.richmom.vip/api/v1/auth/login` -> `422` with missing `email` / `password`, confirming the domain reaches the frontend and the frontend proxies to the prod API correctly
