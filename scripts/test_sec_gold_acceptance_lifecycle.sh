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
        exit "${FAKE_PREFLIGHT_STATUS:-9}"
        ;;
    *"acceptance-pass-report-status"*)
        exit "${FAKE_REPORT_STATUS:-0}"
        ;;
    *"import yaml;"*)
        printf '%s\n' "${FAKE_CASE_IDS:-aapl-primary}"
        exit 0
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
        set -- "$action" "$run_id" aapl-primary 1
    elif [ "$action" = "snapshot" ]; then
        set -- "$action" "$run_id" before
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
assert_preflight_stops snapshot "acceptance-snapshot"
assert_preflight_stops audit "acceptance-audit"

assert_storage_prepare_precedes_database_and_acceptance_mounts() {
    run_id=prepare-first
    : >"$record_file"
    set +e
    FAKE_DOCKER_RECORD="$record_file" \
    FAKE_DATABASE_EXISTS=0 \
    DOCKER_BIN="$fake_docker" \
    VALUEPILOT_INFRA_COMPOSE="$test_root/infra.yml" \
        "$test_root/repo/scripts/sec_gold_acceptance.sh" \
        create "$run_id" >/dev/null 2>&1
    result=$?
    set -e
    [ "$result" -ne 0 ]
    prepare_line=$(grep -n 'prepare-storage /trusted-repo prepare-first' "$record_file" | head -1 | cut -d: -f1)
    createdb_line=$(grep -n 'createdb .*valuepilot_acceptance_prepare_first' "$record_file" | head -1 | cut -d: -f1)
    [ "$prepare_line" -lt "$createdb_line" ]
    if grep -F '/acceptance-root' "$record_file" >/dev/null; then
        echo "create bound the acceptance storage parent before descriptor preparation" >&2
        exit 1
    fi
}

assert_storage_prepare_precedes_database_and_acceptance_mounts

assert_invalid_report_stops_resume() {
    run_id=stale-report
    mkdir -p "$test_root/repo/storage/sec_gold_acceptance/$run_id/reports/pass-1"
    : >"$record_file"
    set +e
    FAKE_DOCKER_RECORD="$record_file" \
    FAKE_DATABASE_EXISTS=1 \
    FAKE_PREFLIGHT_STATUS=0 \
    FAKE_REPORT_STATUS=7 \
    DOCKER_BIN="$fake_docker" \
    VALUEPILOT_INFRA_COMPOSE="$test_root/infra.yml" \
        "$test_root/repo/scripts/sec_gold_acceptance.sh" \
        run-pass "$run_id" 1 >/dev/null 2>&1
    result=$?
    set -e
    [ "$result" -eq 7 ]
    grep -F "acceptance-pass-report-status" "$record_file" >/dev/null
    if grep -F "acceptance-bootstrap-stocks" "$record_file" >/dev/null || \
       grep -F "ingest-gold-case" "$record_file" >/dev/null; then
        echo "run-pass mutated state after stale report validation" >&2
        exit 1
    fi
}

assert_validated_report_is_only_then_skipped() {
    run_id=validated-skip
    report_dir="$test_root/repo/storage/sec_gold_acceptance/$run_id/reports/pass-1"
    mkdir -p "$report_dir"
    printf '{}\n' >"$report_dir/aapl-primary.json"
    : >"$record_file"
    set +e
    FAKE_DOCKER_RECORD="$record_file" \
    FAKE_DATABASE_EXISTS=1 \
    FAKE_PREFLIGHT_STATUS=0 \
    FAKE_REPORT_STATUS=0 \
    DOCKER_BIN="$fake_docker" \
    VALUEPILOT_INFRA_COMPOSE="$test_root/infra.yml" \
        "$test_root/repo/scripts/sec_gold_acceptance.sh" \
        run-pass "$run_id" 1 >/dev/null 2>&1
    result=$?
    set -e
    [ "$result" -ne 0 ]
    grep -F "acceptance-pass-report-status" "$record_file" >/dev/null
    if grep -F "ingest-gold-case" "$record_file" >/dev/null; then
        echo "run-pass ingested a report after successful read-only validation" >&2
        exit 1
    fi
}

assert_invalid_report_stops_resume
assert_validated_report_is_only_then_skipped

assert_missing_report_runs_db_checkpoint_recovery_path() {
    run_id=after-checkpoint-report-missing
    case_ids="case-01 case-02 case-03 case-04 case-05 case-06 case-07 case-08 case-09 case-10 case-11 case-12 case-13 case-14 case-15 case-16 case-17 case-18 case-19 case-20 case-21 case-22 case-23 case-24"
    mkdir -p "$test_root/repo/storage/sec_gold_acceptance/$run_id"
    : >"$record_file"
    FAKE_DOCKER_RECORD="$record_file" \
    FAKE_DATABASE_EXISTS=1 \
    FAKE_PREFLIGHT_STATUS=0 \
    FAKE_REPORT_STATUS=0 \
    FAKE_CASE_IDS="$case_ids" \
    DOCKER_BIN="$fake_docker" \
    VALUEPILOT_INFRA_COMPOSE="$test_root/infra.yml" \
        "$test_root/repo/scripts/sec_gold_acceptance.sh" \
        run-pass "$run_id" 1 >/dev/null 2>&1
    [ "$(grep -c 'acceptance-pass-report-status' "$record_file")" -eq 2 ]
    [ "$(grep -c 'ingest-gold-case --case-id case-' "$record_file")" -eq 24 ]
}

assert_missing_report_runs_db_checkpoint_recovery_path

assert_after_snapshot_follows_both_audited_passes() {
    run_id=snapshot-order
    mkdir -p "$test_root/repo/storage/sec_gold_acceptance/$run_id"
    : >"$record_file"
    FAKE_DOCKER_RECORD="$record_file" \
    FAKE_DATABASE_EXISTS=1 \
    FAKE_PREFLIGHT_STATUS=0 \
    FAKE_REPORT_STATUS=0 \
    DOCKER_BIN="$fake_docker" \
    VALUEPILOT_INFRA_COMPOSE="$test_root/infra.yml" \
        "$test_root/repo/scripts/sec_gold_acceptance.sh" \
        snapshot "$run_id" after >/dev/null 2>&1
    pass_one_line=$(grep -n 'acceptance-pass-report-status.*--acceptance-pass 1' "$record_file" | cut -d: -f1)
    pass_two_line=$(grep -n 'acceptance-pass-report-status.*--acceptance-pass 2' "$record_file" | cut -d: -f1)
    snapshot_line=$(grep -n 'acceptance-snapshot.*--phase after' "$record_file" | cut -d: -f1)
    [ "$pass_one_line" -lt "$pass_two_line" ]
    [ "$pass_two_line" -lt "$snapshot_line" ]
}

assert_after_snapshot_follows_both_audited_passes

grep -F 'RATE_GUARD_ALLOW_LOCAL_FALLBACK: "false"' \
    "$SOURCE_DIR/../docker-compose.acceptance.yml" >/dev/null
grep -F 'EDGAR_FETCH_MODE: "rate_guard"' \
    "$SOURCE_DIR/../docker-compose.acceptance.yml" >/dev/null
grep -F 'RATE_GUARD_EXPECTED_INSTANCE_ID:' \
    "$SOURCE_DIR/../docker-compose.acceptance.yml" >/dev/null
grep -F 'THIRTEENF_JOB_WORKER_ENABLED: "false"' \
    "$SOURCE_DIR/../docker-compose.acceptance.yml" >/dev/null
grep -F 'EDGAR_SCHEDULER_ENABLED: "false"' \
    "$SOURCE_DIR/../docker-compose.acceptance.yml" >/dev/null
grep -F 'MANAGER_SEED_ON_STARTUP: "false"' \
    "$SOURCE_DIR/../docker-compose.acceptance.yml" >/dev/null
grep -F 'NOTIFICATION_DELIVERY_ENABLED: "false"' \
    "$SOURCE_DIR/../docker-compose.acceptance.yml" >/dev/null
grep -F 'RESEARCH_NOTIFICATION_SCHEDULER_ENABLED: "false"' \
    "$SOURCE_DIR/../docker-compose.acceptance.yml" >/dev/null

echo "acceptance lifecycle preflight ordering passed"
