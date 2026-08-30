#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
INFRA_COMPOSE=${VALUEPILOT_INFRA_COMPOSE:-/Users/dane/projects/infra/docker-compose.yml}
ADMIN_USER=${VALUEPILOT_INFRA_ADMIN_USER:-infra_admin}
DOCKER_BIN=${DOCKER_BIN:-docker}

usage() {
    echo "usage: $0 {create|verify|roundtrip|test|run-case|destroy|fingerprint-shared} <run-id> [case-id]" >&2
    exit 64
}

action=${1:-}
run_id=${2:-}

if [ "$action" = "fingerprint-shared" ]; then
    [ -z "$run_id" ] || usage
    exec "$DOCKER_BIN" compose -f "$INFRA_COMPOSE" exec -T postgres \
        psql -X -v ON_ERROR_STOP=1 -U "$ADMIN_USER" -d valuepilot -Atc \
        "SELECT json_build_object(
            'database', current_database(),
            'revision', COALESCE((SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version), 'missing'),
            'table_count', (SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'),
            'inserts', COALESCE((SELECT sum(n_tup_ins) FROM pg_stat_user_tables), 0),
            'updates', COALESCE((SELECT sum(n_tup_upd) FROM pg_stat_user_tables), 0),
            'deletes', COALESCE((SELECT sum(n_tup_del) FROM pg_stat_user_tables), 0)
        )::text"
fi

[ -n "$action" ] && [ -n "$run_id" ] || usage
case "$run_id" in
    -* | *[!a-z0-9-]* | ? | "" | valuepilot | postgres | template0 | template1)
        echo "invalid acceptance run ID" >&2
        exit 64
        ;;
esac
[ "${#run_id}" -le 32 ] || {
    echo "acceptance run ID is longer than 32 characters" >&2
    exit 64
}

database_name="valuepilot_acceptance_$(printf '%s' "$run_id" | tr '-' '_')"
storage_parent="$REPO_ROOT/storage/sec_gold_acceptance"
storage_root="$storage_parent/$run_id"
project_name="valuepilot-acceptance-$run_id"

case "$database_name" in
    valuepilot_acceptance_[a-z0-9_]*) ;;
    *) echo "derived acceptance database name is unsafe" >&2; exit 64 ;;
esac
case "$storage_root" in
    "$REPO_ROOT"/storage/sec_gold_acceptance/"$run_id") ;;
    *) echo "derived acceptance storage path is unsafe" >&2; exit 64 ;;
esac
[ ! -L "$storage_parent" ] && [ ! -L "$storage_root" ] || {
    echo "acceptance storage must not use symlinks" >&2
    exit 64
}

admin_psql() {
    "$DOCKER_BIN" compose -f "$INFRA_COMPOSE" exec -T postgres \
        psql -X -v ON_ERROR_STOP=1 -U "$ADMIN_USER" -d postgres "$@"
}

database_exists() {
    result=$(admin_psql -Atc \
        "SELECT 1 FROM pg_database WHERE datname = '$database_name'")
    [ "$result" = "1" ]
}

acceptance_run() {
    VALUEPILOT_ACCEPTANCE_DATABASE="$database_name" \
    VALUEPILOT_ACCEPTANCE_RUN_ID="$run_id" \
    VALUEPILOT_ACCEPTANCE_STORAGE="$storage_root" \
    "$DOCKER_BIN" compose \
        --project-name "$project_name" \
        -f "$REPO_ROOT/docker-compose.yml" \
        -f "$REPO_ROOT/docker-compose.acceptance.yml" \
        run --rm --no-deps api "$@"
}

runtime_preflight() {
    acceptance_run python -m app.acceptance.sec_gold_environment \
        preflight "$run_id"
}

destroy_preflight() {
    if database_exists; then
        acceptance_run python -m app.acceptance.sec_gold_environment \
            destroy "$run_id" database-present
    else
        acceptance_run python -m app.acceptance.sec_gold_environment \
            destroy "$run_id"
    fi
}

create_storage() {
    "$DOCKER_BIN" compose \
        --project-name "$project_name" \
        -f "$REPO_ROOT/docker-compose.yml" \
        run --rm --no-deps \
        -v "$storage_parent:/acceptance-root" \
        api sh -eu -c \
        'target="/acceptance-root/$1"; [ ! -e "$target" ]; mkdir -p "$target/reports"' \
        sh "$run_id"
}

destroy_storage() {
    [ -e "$storage_root" ] || return 0
    "$DOCKER_BIN" compose \
        --project-name "$project_name" \
        -f "$REPO_ROOT/docker-compose.yml" \
        run --rm --no-deps \
        -v "$storage_parent:/acceptance-root" \
        api sh -eu -c \
        'target="/acceptance-root/$1"; case "$target" in /acceptance-root/[a-z0-9][a-z0-9-]*) ;; *) exit 64 ;; esac; [ ! -L "$target" ]; find "$target" -depth -delete' \
        sh "$run_id"
}

verify_head() {
    database_identity=$(runtime_preflight)
    heads=$(acceptance_run alembic heads)
    current=$(acceptance_run alembic current)
    [ "$(printf '%s\n' "$heads" | grep -c '(head)')" -eq 1 ] || {
        echo "acceptance environment does not have exactly one Alembic head" >&2
        exit 1
    }
    printf '%s\n' "$current" | grep -F "(head)" >/dev/null || {
        echo "acceptance database is not at the Alembic head" >&2
        exit 1
    }
    printf 'acceptance_run_id=%s database=%s storage=%s\n' \
        "$run_id" "$database_name" "$storage_root"
    printf '%s\n' "$database_identity"
    printf 'alembic_heads=%s\nalembic_current=%s\n' "$heads" "$current"
}

case "$action" in
    create)
        [ "$#" -eq 2 ] || usage
        if database_exists; then
            echo "acceptance database already exists; destroy the exact run before retry" >&2
            exit 1
        fi
        [ ! -e "$storage_root" ] || {
            echo "acceptance storage already exists; destroy the exact run before retry" >&2
            exit 1
        }
        "$DOCKER_BIN" compose -f "$INFRA_COMPOSE" exec -T postgres \
            createdb -U "$ADMIN_USER" --owner valuepilot --template template0 \
            "$database_name"
        create_storage
        runtime_preflight
        acceptance_run alembic upgrade head
        verify_head
        ;;
    verify)
        [ "$#" -eq 2 ] || usage
        database_exists || {
            echo "acceptance database does not exist" >&2
            exit 1
        }
        [ -d "$storage_root" ] || {
            echo "acceptance storage does not exist" >&2
            exit 1
        }
        verify_head
        ;;
    roundtrip)
        [ "$#" -eq 2 ] || usage
        database_exists || {
            echo "acceptance database does not exist" >&2
            exit 1
        }
        [ -d "$storage_root" ] || {
            echo "acceptance storage does not exist" >&2
            exit 1
        }
        runtime_preflight
        acceptance_run alembic downgrade 20260830130000
        runtime_preflight
        current=$(acceptance_run alembic current)
        printf '%s\n' "$current" | grep -F "20260830130000" >/dev/null || {
            echo "acceptance database did not reach the roundtrip parent" >&2
            exit 1
        }
        acceptance_run alembic upgrade head
        verify_head
        ;;
    test)
        [ "$#" -eq 2 ] || usage
        database_exists || {
            echo "acceptance database does not exist" >&2
            exit 1
        }
        [ -d "$storage_root" ] || {
            echo "acceptance storage does not exist" >&2
            exit 1
        }
        runtime_preflight
        acceptance_run pytest -q \
            tests/unit/test_sec_gold_acceptance.py \
            tests/unit/test_sec_financial_cli.py \
            tests/unit/test_sec_financial_lineage.py \
            tests/unit/test_sec_financial_lineage_migration.py \
            tests/unit/test_sec_financial_source_guard.py \
            tests/unit/test_sec_egress_guard.py \
            tests/unit/test_rate_guard_client.py \
            tests/unit/test_edgar_client.py
        ;;
    run-case)
        [ "$#" -eq 3 ] || usage
        case_id=$3
        case "$case_id" in
            *[!a-z0-9-]* | "") echo "invalid gold-set case ID" >&2; exit 64 ;;
        esac
        database_exists || {
            echo "acceptance database does not exist" >&2
            exit 1
        }
        [ -d "$storage_root" ] || {
            echo "acceptance storage does not exist" >&2
            exit 1
        }
        runtime_preflight
        acceptance_run python -m app.cli.sec_financials ingest-gold-case \
            --case-id "$case_id" \
            --acceptance-run-id "$run_id" \
            --report-json "/code/storage/sec_gold_acceptance/$run_id/reports/$case_id.json"
        ;;
    destroy)
        [ "$#" -eq 2 ] || usage
        destroy_preflight
        if database_exists; then
            [ "$(admin_psql -Atc 'SELECT current_database()')" = "postgres" ] || {
                echo "administrative connection is not the postgres control database" >&2
                exit 1
            }
            "$DOCKER_BIN" compose -f "$INFRA_COMPOSE" exec -T postgres \
                dropdb -U "$ADMIN_USER" --force "$database_name"
        fi
        destroy_storage
        VALUEPILOT_ACCEPTANCE_DATABASE="$database_name" \
        VALUEPILOT_ACCEPTANCE_RUN_ID="$run_id" \
        VALUEPILOT_ACCEPTANCE_STORAGE="$storage_root" \
        "$DOCKER_BIN" compose \
            --project-name "$project_name" \
            -f "$REPO_ROOT/docker-compose.yml" \
            -f "$REPO_ROOT/docker-compose.acceptance.yml" \
            down --volumes --remove-orphans
        echo "acceptance run removed: $run_id"
        ;;
    *) usage ;;
esac
