#!/bin/sh

set -eu

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test_root=$(mktemp -d)
trap 'find "$test_root" -depth -delete' EXIT HUP INT TERM
mkdir -p "$test_root/repo/scripts" "$test_root/bin"
cp "$SOURCE_DIR/sec_gold_acceptance.sh" "$test_root/repo/scripts/"

record_file="$test_root/docker-record"
fake_docker="$test_root/bin/docker"
cat >"$fake_docker" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >>"$FAKE_DOCKER_RECORD"
case "$*" in
    *"SELECT 1 FROM pg_database"*)
        [ "${FAKE_DATABASE_EXISTS:-0}" = "1" ] && printf '1\n'
        exit 0
        ;;
    *"python -m app.acceptance.sec_gold_environment preflight"*)
        exit 9
        ;;
esac
exit 0
EOF
chmod +x "$fake_docker"

assert_preflight_stops() {
    action=$1
    forbidden=$2
    run_id="ordering-$action"
    : >"$record_file"
    if [ "$action" != "create" ]; then
        mkdir -p "$test_root/repo/storage/sec_gold_acceptance/$run_id"
        database_exists=1
    else
        database_exists=0
    fi
    if [ "$action" = "run-case" ]; then
        set -- "$action" "$run_id" aapl-primary
    else
        set -- "$action" "$run_id"
    fi
    set +e
    FAKE_DOCKER_RECORD="$record_file" \
    FAKE_DATABASE_EXISTS="$database_exists" \
    DOCKER_BIN="$fake_docker" \
    VALUEPILOT_INFRA_COMPOSE="$test_root/infra.yml" \
        "$test_root/repo/scripts/sec_gold_acceptance.sh" \
        "$@" >/dev/null 2>&1
    result=$?
    set -e
    [ "$result" -ne 0 ]
    grep -F "python -m app.acceptance.sec_gold_environment preflight" \
        "$record_file" >/dev/null
    if grep -F "$forbidden" "$record_file" >/dev/null; then
        echo "$action invoked forbidden command after failed preflight: $forbidden" >&2
        exit 1
    fi
}

assert_preflight_stops create "alembic"
assert_preflight_stops test "pytest"
assert_preflight_stops run-case "app.cli.sec_financials"

echo "acceptance lifecycle preflight ordering passed"
