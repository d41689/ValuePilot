#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

dev_compose="$REPO_ROOT/docker-compose.yml"
prod_compose="$REPO_ROOT/docker-compose.prod.yml"
deploy_script="$REPO_ROOT/scripts/deploy_prod_from_main.sh"

if grep -Eq '^[[:space:]]{2}rate-guard:' "$dev_compose" "$prod_compose"; then
  echo "dev/prod Compose must not define a second central rate-guard service" >&2
  exit 1
fi

grep -Eq 'RATE_GUARD_URL: https://rate-guard\.richmom\.vip' "$dev_compose"
grep -Eq '^[[:space:]]{2}rate-guard-local:' "$dev_compose"
grep -Eq 'RATE_GUARD_ALLOW_LOCAL_FALLBACK: "true"' "$dev_compose"
grep -Eq 'RATE_GUARD_FALLBACK_URL: http://rate-guard-local:9000' "$dev_compose"
grep -Eq 'RATE_GUARD_EDGAR_RPS: "1\.0"' "$dev_compose"
grep -Eq 'RATE_GUARD_URL: http://rate-guard:9000' "$prod_compose"
grep -Eq 'RATE_GUARD_EXPECTED_INSTANCE_ID:' "$prod_compose"
if grep -Eq 'RATE_GUARD_(ALLOW_LOCAL_FALLBACK|FALLBACK_URL)' "$prod_compose"; then
  echo "production must never configure the development fallback" >&2
  exit 1
fi
grep -Eq 'RATE_GUARD_EDGAR_RPS: "8\.0"' "$REPO_ROOT/docker-compose.rateguard.yml"
grep -Eq 'public_rate_guard_identity' "$deploy_script"
grep -Eq 'internal_rate_guard_identity' "$deploy_script"
grep -Eq 'do not expose the same instance' "$deploy_script"

echo "Central Rate Guard plus bounded development fallback contract is present."
