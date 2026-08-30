#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

dev_compose="$REPO_ROOT/docker-compose.yml"
prod_compose="$REPO_ROOT/docker-compose.prod.yml"
deploy_script="$REPO_ROOT/scripts/deploy_prod_from_main.sh"

if grep -Eq '^[[:space:]]{2}rate-guard:' "$dev_compose" "$prod_compose"; then
  echo "dev/prod Compose must not define a second rate-guard service" >&2
  exit 1
fi

grep -Eq 'RATE_GUARD_URL: https://rate-guard\.richmom\.vip' "$dev_compose"
grep -Eq 'RATE_GUARD_URL: http://rate-guard:9000' "$prod_compose"
grep -Eq 'RATE_GUARD_EXPECTED_INSTANCE_ID:' "$prod_compose"
grep -Eq 'public_rate_guard_identity' "$deploy_script"
grep -Eq 'internal_rate_guard_identity' "$deploy_script"
grep -Eq 'do not expose the same instance' "$deploy_script"

echo "Singleton Rate Guard topology contract is present."
