# Goal / Acceptance Criteria

- Create a shared infra directory under `/Users/dane/projects/infra`.
- Update `MathPilot` compose files to use shared PostgreSQL while keeping project-local Redis/Mailhog.
- Update `ValuePilot` compose files so dev and prod can run against the shared PostgreSQL instance.
- Keep `ValuePilot` frontend API access working in both dev and prod.

# Scope

In:
- Shared infra compose for PostgreSQL
- MathPilot dev/prod compose updates
- ValuePilot dev/prod compose updates
- Minimal frontend networking adjustment if required for ValuePilot

Out:
- Caddy setup
- Kubernetes or VM deployment
- Production hardening beyond local prod-like compose

# Files To Change

- `/Users/dane/projects/infra/docker-compose.yml`
- `/Users/dane/projects/infra/postgres/init/01-init-project-databases.sh`
- `/Users/dane/projects/infra/README.md`
- `/Users/dane/projects/MathPilot/docker-compose.yml`
- `/Users/dane/projects/MathPilot/docker-compose.prod.yml`
- `/Users/dane/projects/ValuePilot/docker-compose.yml`
- `/Users/dane/projects/ValuePilot/docker-compose.prod.yml`
- `/Users/dane/projects/ValuePilot/frontend/lib/api/client.ts`

# Test Plan

- `docker compose -f /Users/dane/projects/infra/docker-compose.yml config`
- `docker compose config`
- `docker compose -f docker-compose.prod.yml config`
- `cd /Users/dane/projects/ValuePilot && docker compose config`
- `cd /Users/dane/projects/ValuePilot && docker compose -f docker-compose.prod.yml config`

# Progress Notes

- Initial design: shared PostgreSQL, project-local Redis, no Caddy on the development host by default.
- Added `/Users/dane/projects/infra` with shared PostgreSQL and bootstrap script for project-specific dev/prod databases.
- Updated both project compose stacks to attach API and DB utility containers to the shared `projects-shared` network.
- Added `ValuePilot` prod compose and switched frontend API client default to same-origin `/api/v1`.
- Verified:
  - `docker compose -f /Users/dane/projects/infra/docker-compose.yml config`
  - `docker compose config` in `MathPilot`
  - `docker compose -f docker-compose.prod.yml config` in `MathPilot`
  - `docker compose config` in `ValuePilot`
  - `docker compose -f docker-compose.prod.yml config` in `ValuePilot`
