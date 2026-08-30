# Adaptive development Rate Guard fallback

## Goal

Keep development SEC/13F access available when the production Mac or its
public Rate Guard route is unavailable, without weakening production's
single-instance fail-closed contract or exceeding SEC's aggregate request
budget.

## Acceptance criteria

- Development prefers the authenticated public central Rate Guard.
- Only transport/origin-unavailable failures may select a local fallback;
  authentication, malformed identity, or pinned-identity mismatch fail loud.
- New clients automatically use the selected route, and development probes the
  primary route and switches back after recovery.
- The local fallback is private to the development Compose network and is
  capped at 1 request/second; production has no fallback configuration.
- Replay mode performs no identity probes.
- Route selection, failover, failback, unsafe failure behavior, and topology
  are covered by tests.

## Scope

In scope: backend Rate Guard route selection, development Compose fallback,
startup/monitor lifecycle, tests, and operator documentation. Out of scope:
upstream ingestion behavior, production Rate Guard topology, and data models.

## References

- `docs/tasks/2026-08-29_rate-guard-singleton-enforcement.md`
- `rate-guard/README.md`

## Files to change

- `backend/app/core/config.py`
- `backend/app/main.py`
- `backend/app/rate_guard/`
- `backend/tests/unit/`
- `docker-compose.yml`
- `scripts/check_rate_guard_topology.sh`
- `.github/workflows/ci.yml`
- `rate-guard/README.md`

## Test plan

Use targeted backend and topology tests while iterating, followed by every
canonical Docker closing-gate command from `AGENTS.md`, Rate Guard tests, and
`git diff --check`.

## Decisions and sign-off

- Failover eligibility is a typed transport/gateway-origin failure. HTTP auth,
  malformed identity, and instance mismatch are never treated as offline.
- Existing clients read an atomically replaced route per operation, so a job
  already in progress follows failover/failback between requests.
- If monitoring detects an unsafe identity on the active primary, the route is
  quarantined until a later successful probe; a previously verified private
  fallback may continue.
- Central EDGAR is pinned at 8 requests/second and local fallback at 1. The
  fallback has no published port and production has no fallback setting.
- An actual-container probe selected `rate-guard-local`, verified its identity,
  and reported `edgar_rps=1.0` when the primary origin was unreachable.
