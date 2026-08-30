#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

cd "$REPO_ROOT"

if [ ! -f .env ]; then
  echo "Missing required file: $REPO_ROOT/.env" >&2
  exit 1
fi

if [ ! -f .env.prod ]; then
  echo "Missing required file: $REPO_ROOT/.env.prod" >&2
  exit 1
fi

if ! docker network inspect projects-shared >/dev/null 2>&1; then
  docker network create projects-shared >/dev/null
fi

set -a
. "$REPO_ROOT/.env"
rate_guard_deploy_api_key=${RATE_GUARD_API_KEY:-}
. "$REPO_ROOT/.env.prod"
# Rate Guard reads only .env. Keep its primary credential authoritative even if
# a stale .env.prod happens to contain a variable with the same name.
RATE_GUARD_API_KEY=$rate_guard_deploy_api_key
set +a

wait_for_url() {
  url=$1
  max_attempts=${2:-30}
  attempt=1

  while [ "$attempt" -le "$max_attempts" ]; do
    if curl --fail --silent --location "$url" >/dev/null 2>&1; then
      return 0
    fi

    sleep 2
    attempt=$((attempt + 1))
  done

  echo "Timed out waiting for $url" >&2
  return 1
}

rate_guard_identity() {
  base_url=$1
  if [ -z "${rate_guard_deploy_api_key:-}" ]; then
    echo "RATE_GUARD_API_KEY is required to verify authenticated identity" >&2
    return 1
  fi
  printf 'header = "Authorization: Bearer %s"\n' "$rate_guard_deploy_api_key" |
    curl --fail --silent --show-error --max-time 10 --config - \
      "${base_url}/v1/identity"
}

wait_for_public_rate_guard_identity() {
  expected=$1
  max_attempts=${2:-30}
  attempt=1
  while [ "$attempt" -le "$max_attempts" ]; do
    actual=$(rate_guard_identity "https://rate-guard.richmom.vip" 2>/dev/null || true)
    if [ "$actual" = "$expected" ]; then
      return 0
    fi
    sleep 2
    attempt=$((attempt + 1))
  done
  echo "Public and internal Rate Guard routes do not expose the same instance" >&2
  return 1
}

# Rate Guard is the shared egress limiter for dev + prod. Bring it up first
# and confirm it is healthy before the prod stack: once the api depends on it
# (Rate Guard PR 2/4), a prod deploy must not proceed past a broken limiter.
# `up -d --build` recreates the container only when something changed — the
# rate-guard/ sources, docker-compose.rateguard.yml, or an interpolated env
# value; an otherwise-unchanged deploy leaves the running container as-is.
rate_guard_port=${RATE_GUARD_HOST_PORT:-9099}
docker compose -f docker-compose.rateguard.yml up -d --build
wait_for_url "http://127.0.0.1:${rate_guard_port}/healthz"
echo "Rate Guard healthy on port ${rate_guard_port}"

internal_rate_guard_identity_document=$(
  rate_guard_identity "http://127.0.0.1:${rate_guard_port}"
)
internal_rate_guard_identity=$(
  printf '%s\n' "$internal_rate_guard_identity_document" |
    sed -n 's/.*"instance_id":"\([^"]*\)".*/\1/p'
)
internal_rate_guard_process=$(
  printf '%s\n' "$internal_rate_guard_identity_document" |
    sed -n 's/.*"process_id":"\([^"]*\)".*/\1/p'
)
if ! printf '%s\n' "$internal_rate_guard_identity" |
  grep -Eq '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'; then
  echo "Internal Rate Guard returned an invalid instance identity" >&2
  exit 1
fi
if ! printf '%s\n' "$internal_rate_guard_process" |
  grep -Eq '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'; then
  echo "Internal Rate Guard returned an invalid process identity" >&2
  exit 1
fi

wait_for_public_rate_guard_identity "$internal_rate_guard_identity_document"
public_rate_guard_identity_document=$(
  rate_guard_identity "https://rate-guard.richmom.vip"
)
if [ "$public_rate_guard_identity_document" != "$internal_rate_guard_identity_document" ]; then
  echo "Public and internal Rate Guard routes do not expose the same instance" >&2
  exit 1
fi
export RATE_GUARD_EXPECTED_INSTANCE_ID=$internal_rate_guard_identity
echo "Verified singleton Rate Guard instance ${internal_rate_guard_identity}, process ${internal_rate_guard_process}"

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps

api_port=${HOST_API_PORT:-8101}
web_port=${HOST_WEB_PORT:-3101}

wait_for_url "http://127.0.0.1:${api_port}/health"
wait_for_url "http://127.0.0.1:${web_port}/login"

echo "ValuePilot prod deploy succeeded on api=${api_port} web=${web_port}"
