"""The annual view and detail pages must describe one guarded response."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.financial_history import FinancialHistory, FinancialHistoryRow, WorkspaceResponse
from app.services.financial_history import CORE_METRIC_KEYS, project_financial_history


NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def observation(identifier, key="is.revenue", year=2025, **changes):
    fields = dict(
        row_kind="fact", row_key=f"fact:{identifier}", status="available",
        metric_key=key, fact_id=identifier, publication_id=identifier + 1000,
        value_numeric_exact="9007199254740993.000000000001", unit="currency",
        currency="USD", period_type="FY", period_basis="duration",
        period_start=date(year - 1, 9, 29), period_end=date(year, 9, 28),
        fiscal_year=year, source_type="sec", source_role="primary_as_filed_actual",
        fact_nature="actual", comparison_identity={"identity_complete": True},
        evidence_capability="sec_statement",
    )
    fields.update(changes)
    return FinancialHistoryRow(**fields)


def project(rows):
    return project_financial_history(stock_id=66, evaluated_at=NOW, rows=rows)


def test_retained_matrix_is_87_facts_plus_three_stable_expected_states():
    rows = [observation(i * 10 + year, key, year)
            for i, key in enumerate(CORE_METRIC_KEYS)
            for year in range(2016, 2026)
            if not (key == "bs.cash_and_equivalents" and year < 2019)]
    history = project(rows)
    assert history.annual_window.years == list(range(2016, 2026))
    assert (history.available_fact_count, history.state_count, history.total_rows) == (87, 3, 90)
    missing = [r for r in history.rows if r.row_kind != "fact"]
    assert {r.row_key for r in missing} == {
        f"expected:66:bs.cash_and_equivalents:FY:{year}:not_returned"
        for year in (2016, 2017, 2018)
    }
    assert all(r.fact_id is None and r.period_end is None and
               r.value_numeric_exact is None for r in missing)
    assert history == project(list(reversed(rows)))
    assert [len(history.rows[n:n + 50]) for n in range(0, 90, 50)] == [50, 40]


def test_no_fiscal_authority_means_no_guessed_window_or_expected_rows():
    for changes in ({"fiscal_year": None}, {"fact_nature": "estimate"},
                    {"period_type": "Q"}, {"period_end": date(2027, 1, 1)},
                    {"comparison_identity": None}, {"period_basis": None}):
        history = project([observation(1, **changes)])
        assert history.annual_window.status == "undetermined"
        assert history.total_rows == 1


def test_metric_state_covers_its_scope_without_ten_fake_missing_rows():
    state = FinancialHistoryRow(
        row_kind="metric_state", row_key="metric:net-income:bound", status="unavailable",
        reason_code="reconciliation_bound_exceeded", metric_key="is.net_income",
        evidence_capability="unavailable",
    )
    history = project([observation(1), state])
    assert not any(r.metric_key == "is.net_income" and r.reason_code == "not_returned"
                   for r in history.rows)
    assert state in history.rows


def test_observations_are_not_overwritten_by_year_value_or_source():
    rows = [observation(1), observation(2, source_role="comparative_actual"),
            observation(3, period_start=date(2025, 1, 1)),
            observation(4, fact_nature="estimate"),
            observation(5, unit="shares", currency=None)]
    history = project(rows)
    assert history.available_fact_count == 5
    assert {r.fact_id for r in history.rows if r.row_kind == "fact"} == {1, 2, 3, 4, 5}
    assert all(r.value_numeric_exact == "9007199254740993.000000000001"
               for r in history.rows if r.row_kind == "fact")


def test_schema_preserves_old_workspace_fields_and_rejects_invalid_projection():
    history = project([observation(1)])
    response = WorkspaceResponse(financial_history=history, fundamentals=[{"id": 1, "value_numeric": Decimal("1.2")}],
                                 case={"id": 7}, holders_13f={"status": "unavailable"})
    payload = response.model_dump(mode="json")
    assert payload["fundamentals"] and payload["case"] == {"id": 7}
    assert payload["holders_13f"] == {"status": "unavailable"}
    assert payload["fundamentals"][0]["value_numeric"] == "1.2"
    invalid = history.model_dump()
    invalid["total_rows"] += 1
    with pytest.raises(ValidationError):
        FinancialHistory.model_validate(invalid)
    for fields in (
        dict(row_kind="fact", row_key="fact:1", status="available"),
        dict(row_kind="slot_state", row_key="state:1", status="unavailable", fact_id=1),
        dict(row_kind="slot_state", row_key="state:1", status="unavailable", value_text="secret"),
    ):
        with pytest.raises(ValidationError):
            FinancialHistoryRow(**fields)


def test_endpoint_binds_schema_and_rejects_malformed_history(client, db_session, user_factory, auth_headers, monkeypatch):
    from fastapi.exceptions import ResponseValidationError
    from app.api.v1.endpoints import research

    user = user_factory("history-model@example.com")
    db_session.commit()
    payload = dict(financial_history=project([observation(1)]).model_dump(),
                   case={"id": 7}, fundamentals=[{"id": 1, "value_numeric": Decimal("1.25")}])
    monkeypatch.setattr(research, "build_research_workspace", lambda *a, **k: payload)
    path = "/api/v1/research/cases/7/workspace"
    response = client.get(path, headers=auth_headers(user))
    assert response.status_code == 200
    # Baseline response_model=dict already serializes Decimal as a string.
    assert response.json()["fundamentals"][0]["value_numeric"] == "1.25"
    assert response.json()["financial_history"]["rows"][0]["value_numeric_exact"] == "9007199254740993.000000000001"
    payload["financial_history"]["total_rows"] += 1
    with pytest.raises(ResponseValidationError):
        client.get(path, headers=auth_headers(user))


def test_text_facts_are_guarded_and_states_cannot_restore_their_text(db_session, user_factory):
    from app.models.facts import MetricFact
    from app.models.stocks import Stock
    from app.services.evaluation_snapshot import database_evaluation_snapshot
    from app.services.research_workspace import _reconciled_workspace_facts
    from app.services.financial_history import build_financial_history

    user = user_factory("history-text@example.com")
    stock = Stock(ticker="HISTXT", exchange="NYSE", company_name="History Text")
    db_session.add(stock)
    db_session.flush()
    safe = MetricFact(user_id=user.id, stock_id=stock.id, metric_key="notes.safe",
                      value_text="owned text", source_type="manual", is_current=True,
                      value_json={"manual_role": "original_input"})
    blocked = MetricFact(user_id=user.id, stock_id=stock.id, metric_key="notes.revoked",
                         value_text="revoked secret", source_type="manual", is_current=True,
                         value_json={"manual_role": "original_input", "authorization_state": "revoked"})
    db_session.add_all([safe, blocked])
    db_session.commit()
    snapshot = database_evaluation_snapshot(db_session)
    facts, states = _reconciled_workspace_facts(db_session, facts=[safe, blocked], user_id=user.id,
                                              evaluation_snapshot=snapshot)
    history = build_financial_history(db_session, stock_id=stock.id, user_id=user.id,
                                     facts=facts, states=states, evaluation_snapshot=snapshot)
    assert history.available_fact_count == 1
    assert history.state_count == 1
    assert "revoked secret" not in history.model_dump_json()
    assert [row.value_text for row in history.rows if row.row_kind == "fact"] == ["owned text"]
