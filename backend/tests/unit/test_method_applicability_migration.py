from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from test_support.database_isolation import (
    build_isolated_database_url,
    create_test_schema,
    drop_test_schema,
    new_test_schema_name,
)


BASE = make_url(settings.SQLALCHEMY_DATABASE_URI).set(
    query={
        key: value
        for key, value in make_url(settings.SQLALCHEMY_DATABASE_URI).query.items()
        if key != "options"
    }
).render_as_string(hide_password=False)
BACKEND = Path(__file__).resolve().parents[2]
HEAD = "20260904150000"
PARENT = "20260904140000"


def _alembic_result(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )


@pytest.fixture
def isolated():
    name = new_test_schema_name()
    url = build_isolated_database_url(BASE, name)
    create_test_schema(BASE, name)
    engine = create_engine(url)
    try:
        yield url, engine
    finally:
        engine.dispose()
        drop_test_schema(BASE, name)


def test_v2_fact_snapshot_refuses_downgrade_before_any_schema_mutation(isolated) -> None:
    url, engine = isolated
    upgraded = _alembic_result(url, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('ft07-downgrade@example.com','x',true) RETURNING id"
            )
        ).scalar_one()
        stock_id = connection.execute(
            text(
                "INSERT INTO stocks "
                "(ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('FT07DOWN','NYSE','US','FT07 Downgrade',true) RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,value_json,unit,period_type,"
                "period_end_date,source_type,is_current) "
                "VALUES (:user,:stock,'owners_earnings_per_share',1.5,"
                "CAST(:payload AS jsonb),'USD','FY','2025-12-31','calculated',true)"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "payload": json.dumps(
                    {
                        "analysis_method": {
                            "method_policy_version_id": (
                                "analysis-method-applicability-v2"
                            ),
                            "method_key": "owner_earnings",
                            "status": "approved",
                        }
                    }
                ),
            },
        )

    refused = _alembic_result(url, "downgrade", PARENT)
    assert refused.returncode != 0
    assert "cannot downgrade retained FT-07 method authority" in (
        refused.stdout + refused.stderr
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == HEAD
        assert connection.execute(
            text(
                "SELECT count(*) FROM sec_method_policy_versions "
                "WHERE id='analysis-method-applicability-v2'"
            )
        ).scalar_one() == 1
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("sec_method_policy_rules")
        }
        assert {
            "method_version_id",
            "required_risk_reviews_json",
            "required_adjustments_json",
            "unsupported_reason_code",
        } <= columns
