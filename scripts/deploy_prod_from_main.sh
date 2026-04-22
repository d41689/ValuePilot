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
. "$REPO_ROOT/.env.prod"
set +a

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps

api_port=${HOST_API_PORT:-8101}
web_port=${HOST_WEB_PORT:-3101}

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

wait_for_url "http://127.0.0.1:${api_port}/health"
wait_for_url "http://127.0.0.1:${web_port}/login"

echo "ValuePilot prod deploy succeeded on api=${api_port} web=${web_port}"
