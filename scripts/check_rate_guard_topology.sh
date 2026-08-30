#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

dev_compose="$REPO_ROOT/docker-compose.yml"
prod_compose="$REPO_ROOT/docker-compose.prod.yml"
deploy_script="$REPO_ROOT/scripts/deploy_prod_from_main.sh"

if rg -q '^[[:space:]]{2}rate-guard:' "$dev_compose" "$prod_compose"; then
  echo "dev/prod Compose must not define a second rate-guard service" >&2
  exit 1
fi

rg -q 'RATE_GUARD_URL: https://rate-guard\.richmom\.vip' "$dev_compose"
rg -q 'RATE_GUARD_URL: http://rate-guard:9000' "$prod_compose"
rg -q 'RATE_GUARD_EXPECTED_INSTANCE_ID:' "$prod_compose"
rg -q 'public_rate_guard_identity' "$deploy_script"
rg -q 'internal_rate_guard_identity' "$deploy_script"
rg -q 'do not expose the same instance' "$deploy_script"

echo "Singleton Rate Guard topology contract is present."
