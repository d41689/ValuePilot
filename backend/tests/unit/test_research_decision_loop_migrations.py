from __future__ import annotations

import os
from pathlib import Path
import subprocess

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from test_support.database_isolation import (
    build_isolated_database_url,
    create_test_schema,
    drop_test_schema,
    new_test_schema_name,
)


BASE_REVISION = "20260720120000"
_configured_url = make_url(settings.SQLALCHEMY_DATABASE_URI)
_BASE_DATABASE_URL = _configured_url.set(
    query={key: value for key, value in _configured_url.query.items() if key != "options"}
).render_as_string(hide_password=False)


def _alembic(backend_dir: Path, database_url: str, *args: str) -> None:
    result = subprocess.run(
        ["alembic", *args],
        cwd=backend_dir,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def _alembic_failure(
    backend_dir: Path, database_url: str, *args: str
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["alembic", *args],
        cwd=backend_dir,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, "alembic command unexpectedly succeeded"
    return result


def test_research_decision_loop_migrations_round_trip_with_representative_rows():
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", BASE_REVISION)
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(email, hashed_password, role, tier, is_active) "
                    "VALUES ('migration-fixture@example.com', 'not-used', 'user', 'free', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            stock_id = connection.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('MIGR', 'NYSE', 'US', 'Migration Fixture', true) "
                    "RETURNING id"
                )
            ).scalar_one()

        _alembic(backend_dir, database_url, "upgrade", "head")
        with engine.begin() as connection:
            case_id = connection.execute(
                text(
                    "INSERT INTO research_cases (user_id, stock_id, state) "
                    "VALUES (:user_id, :stock_id, 'queued') RETURNING id"
                ),
                {"user_id": user_id, "stock_id": stock_id},
            ).scalar_one()
            revision_id = connection.execute(
                text(
                    "INSERT INTO research_case_revisions "
                    "(case_id, revision_number, thesis, case_state, snapshot_stock_id, "
                    "stock_ticker, stock_company_name, stock_exchange, created_by_user_id) "
                    "VALUES (:case_id, 1, 'fixture thesis', 'queued', :stock_id, "
                    "'MIGR', 'Migration Fixture', 'NYSE', :user_id) RETURNING id"
                ),
                {"case_id": case_id, "stock_id": stock_id, "user_id": user_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO research_coverage_requirements "
                    "(user_id, stock_id, kind, priority_policy_version, matched_rule, "
                    "priority_rank, state, reason, freshness_policy_version, evaluated_at) "
                    "VALUES (:user_id, :stock_id, 'eod_price', 'fixture-v1', "
                    "'open_case', 1, 'missing', 'fixture gap', 'fixture-v1', now())"
                ),
                {"user_id": user_id, "stock_id": stock_id},
            )
            connection.execute(
                text(
                    "INSERT INTO research_inbox_actions "
                    "(user_id, logical_key, action_family, subject_type, subject_key, "
                    "source_version, priority_policy_version, matched_rule, priority_rank, "
                    "reason, state, target_case_id, stock_id, first_observed_at, last_observed_at) "
                    "VALUES (:user_id, 'fixture-action', 'continue_research', 'case', "
                    "'fixture-case', 'one', 'fixture-v1', 'open_case', 1, 'continue', "
                    "'open', :case_id, :stock_id, now(), now())"
                ),
                {"user_id": user_id, "case_id": case_id, "stock_id": stock_id},
            )
            destination_id = connection.execute(
                text(
                    "INSERT INTO notification_destinations "
                    "(user_id, channel, label, destination_hint, secret_ciphertext, "
                    "key_version, status, consented_at) VALUES (:user_id, 'slack', "
                    "'fixture', 'hooks.slack.com/…/ture', 'ciphertext', 'v1', "
                    "'enabled', now()) RETURNING id"
                ),
                {"user_id": user_id},
            ).scalar_one()
            notification_id = connection.execute(
                text(
                    "INSERT INTO logical_notifications "
                    "(user_id, event_family, subject_type, subject_key, logical_key, "
                    "source_version, correction_type, title, body, evidence_route, severity) "
                    "VALUES (:user_id, 'research_review_due', 'research_case', 'case:fixture', "
                    "'fixture-logical', 'one', 'original', 'Fixture', 'Fixture body', "
                    "'/research/cases/1', 'info') RETURNING id"
                ),
                {"user_id": user_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO notification_delivery_attempts "
                    "(logical_notification_id, destination_id, content_version, status, "
                    "scheduled_for, next_attempt_at) VALUES (:notification_id, "
                    ":destination_id, 1, 'queued', now(), now())"
                ),
                {"notification_id": notification_id, "destination_id": destination_id},
            )
            portfolio_id = connection.execute(
                text(
                    "INSERT INTO manual_portfolios (user_id, name) "
                    "VALUES (:user_id, 'Fixture portfolio') RETURNING id"
                ),
                {"user_id": user_id},
            ).scalar_one()
            position_id = connection.execute(
                text(
                    "INSERT INTO manual_positions "
                    "(portfolio_id, user_id, stock_id, state, quantity, average_unit_cost, "
                    "currency, research_case_id, research_revision_id, opened_on) "
                    "VALUES (:portfolio_id, :user_id, :stock_id, 'open', 1, 10, 'USD', "
                    ":case_id, :revision_id, '2026-07-20') RETURNING id"
                ),
                {
                    "portfolio_id": portfolio_id,
                    "user_id": user_id,
                    "stock_id": stock_id,
                    "case_id": case_id,
                    "revision_id": revision_id,
                },
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO position_journal_events "
                    "(position_id, portfolio_id, user_id, sequence_number, event_type, "
                    "effective_on, new_quantity, new_average_unit_cost, currency, "
                    "research_case_id, research_revision_id, recorded_stock_id, "
                    "recorded_ticker, recorded_company_name, recorded_exchange) "
                    "VALUES (:position_id, :portfolio_id, :user_id, 1, 'open', '2026-07-20', "
                    "1, 10, 'USD', :case_id, :revision_id, :stock_id, 'MIGR', "
                    "'Migration Fixture', 'NYSE')"
                ),
                {
                    "position_id": position_id,
                    "portfolio_id": portfolio_id,
                    "user_id": user_id,
                    "case_id": case_id,
                    "revision_id": revision_id,
                    "stock_id": stock_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO api_rate_limit_events (user_id, operation) "
                    "VALUES (:user_id, 'document_upload')"
                ),
                {"user_id": user_id},
            )
            erased_user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(email, hashed_password, role, tier, is_active) "
                    "VALUES ('pending-erasure@example.com', 'revoked', "
                    "'user', 'free', false) RETURNING id"
                )
            ).scalar_one()
            connection.execute(
                text(
                    "UPDATE users SET email = "
                    "'erased-' || id || '@deleted.invalid' WHERE id = :user_id"
                ),
                {"user_id": erased_user_id},
            )
            connection.execute(
                text(
                    "SELECT set_config("
                    "'valuepilot.account_erasure', 'on', true)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO account_erasure_events "
                    "(user_id, content_hash, summary_json) "
                    "VALUES (:user_id, :content_hash, '{}'::jsonb)"
                ),
                {"user_id": erased_user_id, "content_hash": "a" * 64},
            )

        engine.dispose()
        result = _alembic_failure(
            backend_dir, database_url, "downgrade", BASE_REVISION
        )
        assert result.returncode != 0
        assert "erasure" in (result.stdout + result.stderr).lower()
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id}
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM stocks WHERE id = :id"), {"id": stock_id}
            ).scalar_one() == 1
            inspector = inspect(connection)
            assert inspector.has_table("research_cases")
            assert inspector.has_table("notification_delivery_attempts")
            assert inspector.has_table("manual_positions")
            assert inspector.has_table("api_rate_limit_events")
            alert_columns = {
                item["name"]
                for item in inspector.get_columns("notification_price_alert_states")
            }
            subscription_columns = {
                item["name"]
                for item in inspector.get_columns("notification_subscriptions")
            }
            subscription_checks = {
                item["name"]
                for item in inspector.get_check_constraints(
                    "notification_subscriptions"
                )
            }
            checks = {
                item["name"] for item in inspector.get_check_constraints("research_cases")
            }
            indexes = {
                item["name"] for item in inspector.get_indexes("research_cases")
            }
            assert "ck_research_cases_state_shape" in checks
            assert "uq_research_cases_active_user_stock" in indexes
            assert "last_valuation_fact_id" in alert_columns
            assert "last_research_revision_id" in alert_columns
            assert "last_threshold_ratio" in alert_columns
            assert "last_hysteresis_ratio" in alert_columns
            assert "legacy_frequency_before_in_app_normalization" in subscription_columns
            assert "ck_notification_subscriptions_in_app_immediate" in subscription_checks
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)
