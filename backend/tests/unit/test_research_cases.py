from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.exc import DBAPIError

from app.models.artifacts import PdfDocument, ValueLineParseRun
from app.models.facts import MetricFact
from app.models.research import (
    ResearchCase,
    ResearchCaseEvent,
    ResearchCaseOrigin,
    ResearchCaseRevision,
)
from app.models.stocks import Stock
from app.services.ingestion_service import IngestionService


def _stock(db_session, ticker: str = "CASE") -> Stock:
    stock = Stock(
        ticker=ticker,
        exchange="NASDAQ",
        market_country="US",
        company_name=f"{ticker} Incorporated",
        is_active=True,
    )
    db_session.add(stock)
    db_session.commit()
    db_session.refresh(stock)
    return stock


def _create(client, headers, stock_id: int, *, origin_key: str = "manual"):
    return client.post(
        "/api/v1/research/cases",
        headers=headers,
        json={
            "stock_id": stock_id,
            "origin": {
                "origin_type": "manual",
                "origin_key": origin_key,
                "source_version": "user-action-v1",
                "source_ref": {"entry_point": "ticker_search"},
            },
        },
    )


def _monitoring_revision(expected_head: int = 0) -> dict:
    return {
        "expected_head_revision_number": expected_head,
        "target_state": "monitoring",
        "thesis": "Recurring revenue and switching costs can sustain returns.",
        "variant_view": "Consensus may overestimate durable pricing power.",
        "decision_reason": "Watch while evidence on retention develops.",
        "assumptions": [{"label": "organic growth", "value": "8%"}],
        "risks": [{"risk": "Customer concentration", "monitor": "Top-10 share"}],
        "evidence": [
            {
                "source_type": "external_url",
                "url": "https://example.com/investor-relations",
                "label": "Investor relations",
                "source_date": "2026-07-18",
                "claim": "Management reported retention above 90%.",
            }
        ],
        "valuation_low": "80.00",
        "valuation_base": "100.00",
        "valuation_high": "120.00",
        "valuation_currency": "USD",
        "valuation_as_of_date": "2026-07-20",
        "decision": "watch",
        "next_review_on": "2026-10-20",
    }


def _researching_revision(expected_head: int = 0) -> dict:
    return {
        "expected_head_revision_number": expected_head,
        "target_state": "researching",
        "thesis": "Initial research question.",
        "variant_view": "The initial signal may not survive fundamental review.",
        "assumptions": [],
        "risks": [],
        "evidence": [],
    }


def test_create_is_idempotent_and_preserves_distinct_origins(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="case-create@example.com")
    stock = _stock(db_session)
    headers = auth_headers(user)

    first = _create(client, headers, stock.id, origin_key="ticker:CASE")
    duplicate = _create(client, headers, stock.id, origin_key="ticker:CASE")
    another_origin = _create(client, headers, stock.id, origin_key="manual:idea-2")

    assert first.status_code == 201, first.text
    assert first.json()["created"] is True
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["created"] is False
    assert another_origin.status_code == 200, another_origin.text
    assert another_origin.json()["case"]["id"] == first.json()["case"]["id"]
    assert db_session.query(ResearchCase).count() == 1
    assert db_session.query(ResearchCaseOrigin).count() == 2
    assert [
        row.event_type
        for row in db_session.query(ResearchCaseEvent)
        .order_by(ResearchCaseEvent.id)
        .all()
    ] == ["case_created", "origin_added", "origin_added"]


def test_save_revision_publishes_intrinsic_value_and_keeps_immutable_history(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="case-save@example.com")
    stock = _stock(db_session, "SAVE")
    created = _create(client, auth_headers(user), stock.id).json()
    case_id = created["case"]["id"]
    started = client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(user),
        json=_researching_revision(),
    )
    assert started.status_code == 200, started.text

    monitoring_body = _monitoring_revision(expected_head=1)
    first = client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(user),
        json=monitoring_body,
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["case"]["state"] == "monitoring"
    assert payload["case"]["decision"] == "watch"
    assert payload["case"]["head_revision_number"] == 2
    assert payload["revision"]["valuation_base"] == "100.000000"
    assert payload["revision"]["recorded_identity"]["ticker"] == "SAVE"
    assert payload["revision"]["is_qualified_decision"] is True

    fact = (
        db_session.query(MetricFact)
        .filter_by(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="val.fair_value",
            is_current=True,
        )
        .one()
    )
    assert fact.value_numeric == 100
    assert fact.period_end_date == date(2026, 7, 20)
    assert fact.source_ref_id == payload["revision"]["id"]

    second_body = _monitoring_revision(expected_head=2)
    second_body["thesis"] = "Updated thesis after reviewing retention cohorts."
    second_body["valuation_base"] = "105.00"
    second = client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(user),
        json=second_body,
    )
    assert second.status_code == 200, second.text
    assert db_session.query(ResearchCaseRevision).filter_by(case_id=case_id).count() == 3
    old = (
        db_session.query(ResearchCaseRevision)
        .filter_by(case_id=case_id, revision_number=2)
        .one()
    )
    assert old.thesis.startswith("Recurring revenue")


def test_stale_save_is_409_and_does_not_append_or_publish(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="case-stale@example.com")
    stock = _stock(db_session, "STALE")
    case_id = _create(client, auth_headers(user), stock.id).json()["case"]["id"]
    client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(user),
        json=_researching_revision(),
    )
    client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(user),
        json=_monitoring_revision(expected_head=1),
    )

    stale = client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(user),
        json=_monitoring_revision(expected_head=1),
    )

    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "stale_case_revision"
    assert db_session.query(ResearchCaseRevision).filter_by(case_id=case_id).count() == 2
    assert (
        db_session.query(MetricFact)
        .filter_by(user_id=user.id, stock_id=stock.id, metric_key="val.fair_value")
        .count()
        == 1
    )


def test_qualified_decision_metric_counts_transitions_and_explicit_reviews_not_drafts(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="qualified-metric@example.com")
    stock = _stock(db_session, "QUALIFIED")
    headers = auth_headers(user)
    case_id = _create(client, headers, stock.id).json()["case"]["id"]
    assert client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=headers,
        json=_researching_revision(),
    ).status_code == 200

    decision = _monitoring_revision(expected_head=1)
    decision["decision_action"] = "decision"
    assert client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=headers,
        json=decision,
    ).status_code == 200

    draft = _monitoring_revision(expected_head=2)
    draft["thesis"] = "A qualified content edit that is not a new decision."
    assert client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=headers,
        json=draft,
    ).status_code == 200

    review = _monitoring_revision(expected_head=3)
    review["decision_action"] = "review"
    review["decision_reason"] = "Explicit scheduled review completed."
    assert client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=headers,
        json=review,
    ).status_code == 200

    response = client.get("/api/v1/research/metrics", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["qualified_research_decisions"] == 2
    events = (
        db_session.query(ResearchCaseEvent)
        .filter_by(case_id=case_id, event_type="qualified_decision_recorded")
        .order_by(ResearchCaseEvent.id)
        .all()
    )
    assert [event.payload_json["decision_action"] for event in events] == [
        "decision",
        "review",
    ]
def test_transition_and_valuation_validation_are_typed_and_terminal_cycle_reopens(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="case-transition@example.com")
    stock = _stock(db_session, "FLOW")
    headers = auth_headers(user)
    case_id = _create(client, headers, stock.id).json()["case"]["id"]

    invalid = _monitoring_revision()
    invalid["valuation_low"] = "120"
    invalid["valuation_high"] = "80"
    rejected = client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=headers,
        json=invalid,
    )
    assert rejected.status_code == 422

    closed_body = _monitoring_revision()
    closed_body.update(
        {
            "target_state": "closed",
            "decision": "pass",
            "next_review_on": None,
            "decision_reason": "The downside is not compensated at this price.",
        }
    )
    closed = client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=headers,
        json=closed_body,
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["case"]["state"] == "closed"

    terminal = client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=headers,
        json={**closed_body, "expected_head_revision_number": 1},
    )
    assert terminal.status_code == 409
    assert terminal.json()["detail"]["code"] == "terminal_case"

    reopened = _create(client, headers, stock.id, origin_key="revisit:2027")
    assert reopened.status_code == 201, reopened.text
    assert reopened.json()["created"] is True
    assert reopened.json()["case"]["id"] != case_id


def test_case_resources_are_non_disclosing_across_users(
    client, db_session, user_factory, auth_headers
):
    owner = user_factory(email="case-owner@example.com")
    other = user_factory(email="case-other@example.com")
    stock = _stock(db_session, "PRIVCASE")
    case_id = _create(client, auth_headers(owner), stock.id).json()["case"]["id"]

    detail = client.get(
        f"/api/v1/research/cases/{case_id}", headers=auth_headers(other)
    )
    revisions = client.get(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(other),
    )
    owner_list = client.get(
        "/api/v1/research/cases", headers=auth_headers(owner)
    ).json()
    other_list = client.get(
        "/api/v1/research/cases", headers=auth_headers(other)
    ).json()

    assert detail.status_code == 404
    assert revisions.status_code == 404
    assert {row["id"] for row in owner_list["items"]} == {case_id}
    assert other_list["items"] == []


def test_evidence_rejects_non_https_and_another_users_document(
    client, db_session, user_factory, auth_headers
):
    owner = user_factory(email="evidence-owner@example.com")
    other = user_factory(email="evidence-other@example.com")
    stock = _stock(db_session, "EVID")
    document = PdfDocument(
        user_id=other.id,
        stock_id=stock.id,
        file_name="private.pdf",
        source="upload",
        file_storage_key="private/other.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.commit()
    case_id = _create(client, auth_headers(owner), stock.id).json()["case"]["id"]
    client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(owner),
        json=_researching_revision(),
    )

    http_body = _monitoring_revision(expected_head=1)
    http_body["evidence"] = [
        {
            "source_type": "external_url",
            "url": "http://example.com/not-secure",
            "label": "Unsafe link",
            "claim": "Claim",
        }
    ]
    http_result = client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(owner),
        json=http_body,
    )
    assert http_result.status_code == 422

    private_body = _monitoring_revision(expected_head=1)
    private_body["evidence"] = [
        {
            "source_type": "pdf_document",
            "source_id": document.id,
            "label": "Private report",
            "claim": "A recorded claim without copied proprietary excerpt.",
        }
    ]
    private_result = client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(owner),
        json=private_body,
    )
    assert private_result.status_code == 422
    assert private_result.json()["detail"]["code"] == "evidence_unavailable"


def test_redaction_tombstones_only_authored_content_and_appends_audit_event(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="case-redact@example.com")
    stock = _stock(db_session, "REDACT")
    case_id = _create(client, auth_headers(user), stock.id).json()["case"]["id"]
    client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(user),
        json=_researching_revision(),
    )
    saved = client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=auth_headers(user),
        json=_monitoring_revision(expected_head=1),
    ).json()

    result = client.post(
        f"/api/v1/research/cases/{case_id}/revisions/2/redact",
        headers=auth_headers(user),
        json={"reason": "Accidentally saved a private credential."},
    )

    assert result.status_code == 200, result.text
    revision = db_session.get(ResearchCaseRevision, saved["revision"]["id"])
    assert revision.is_redacted is True
    assert revision.thesis == "[redacted]"
    assert revision.decision == "watch"
    assert revision.stock_ticker == "REDACT"
    assert revision.redaction_content_hash
    assert (
        db_session.query(ResearchCaseEvent)
        .filter_by(case_id=case_id, event_type="revision_redacted")
        .count()
        == 1
    )


def test_invalid_new_case_origin_rolls_back_the_partial_case(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="case-origin-rollback@example.com")
    stock = _stock(db_session, "ORIGIN")

    result = client.post(
        "/api/v1/research/cases",
        headers=auth_headers(user),
        json={
            "stock_id": stock.id,
            "origin": {
                "origin_type": "watchlist",
                "origin_key": "pool:missing",
                "source_version": "watchlist-v1",
                "source_ref": {"pool_id": 999999},
            },
        },
    )

    assert result.status_code == 422
    assert result.json()["detail"]["code"] == "origin_unavailable"
    assert db_session.query(ResearchCase).filter_by(user_id=user.id).count() == 0
    assert db_session.query(ResearchCaseEvent).count() == 0


def test_batch_valuation_reader_respects_newest_unavailable_tombstone(
    db_session, user_factory
):
    from app.services.valuation import (
        publish_user_intrinsic_value,
        read_valuation_facts_by_stock,
    )

    user = user_factory(email="case-tombstone@example.com")
    stock = _stock(db_session, "TOMB")
    publish_user_intrinsic_value(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=100,
        as_of_date=date(2026, 7, 19),
        source_ref_id=1,
    )
    publish_user_intrinsic_value(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=None,
        as_of_date=date(2026, 7, 20),
        unavailable_reason="evidence_insufficient",
        source_ref_id=2,
    )
    db_session.commit()

    selected = read_valuation_facts_by_stock(
        db_session, user_id=user.id, stock_ids=[stock.id]
    )[stock.id]["val.fair_value"]

    assert selected.value_numeric is None
    assert selected.value_json == {
        "status": "unsupported",
        "reason_code": "valuation_origin_unverifiable",
    }
    assert selected.source_ref_id == 2


def test_append_only_tables_reject_normal_update_and_delete(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="case-append-only@example.com")
    stock = _stock(db_session, "APPEND")
    case_id = _create(client, auth_headers(user), stock.id).json()["case"]["id"]
    origin = db_session.query(ResearchCaseOrigin).filter_by(case_id=case_id).one()
    event = (
        db_session.query(ResearchCaseEvent)
        .filter_by(case_id=case_id, event_type="case_created")
        .one()
    )

    origin.origin_key = "mutated"
    with pytest.raises(DBAPIError):
        db_session.flush()
    db_session.rollback()

    event = db_session.get(ResearchCaseEvent, event.id)
    db_session.delete(event)
    with pytest.raises(DBAPIError):
        db_session.flush()
    db_session.rollback()


def test_workspace_combines_user_owned_fundamentals_valuation_coverage_and_public_13f(
    client, db_session, user_factory, auth_headers, monkeypatch
):
    from datetime import datetime, timezone

    from app.models.coverage import ResearchCoverageRequirement
    from app.models.stocks import StockPrice
    from app.services import market_data_service

    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_PRIMARY", "twelvedata")
    monkeypatch.setattr(market_data_service.settings, "TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_COMMERCIAL_ENABLED", True)

    owner = user_factory(email="workspace-owner@example.com")
    other = user_factory(email="workspace-other@example.com")
    stock = _stock(db_session, "WORK")
    case_id = _create(client, auth_headers(owner), stock.id).json()["case"]["id"]
    owner_doc = PdfDocument(
        user_id=owner.id,
        stock_id=stock.id,
        file_name="owner.pdf",
        source="upload",
        file_storage_key="workspace/owner.pdf",
        parse_status="parsed",
        report_date=date(2026, 6, 1),
    )
    other_doc = PdfDocument(
        user_id=other.id,
        stock_id=stock.id,
        file_name="private-other.pdf",
        source="Value Line",
        file_storage_key="workspace/other.pdf",
        parse_status="parsed",
        report_date=date(2026, 7, 1),
    )
    db_session.add_all([owner_doc, other_doc])
    db_session.flush()
    owner_run = ValueLineParseRun(
        user_id=owner.id,
        document_id=owner_doc.id,
        parser_version="value-line-v1",
        source_mapping_version=IngestionService(
            db_session
        ).mapping_spec.source_mapping_version,
        status="running",
    )
    db_session.add(owner_run)
    db_session.flush()
    owner_metric = MetricFact(
        user_id=owner.id,
        stock_id=stock.id,
        metric_key="returns.return_on_equity",
        value_numeric=0.21,
        value_json={
            "mapping_id": "returns.return_on_equity.fy",
            "source_mapping_version": "value-line-spec-v2",
            "definition_basis": "adjusted",
            "dimensions_identity": "empty",
            "fact_nature": "actual",
            "fiscal_year": 2025,
            "period_duration_kind": "fiscal_year",
        },
        unit="ratio",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="parsed",
        source_document_id=owner_doc.id,
        value_line_parse_run_id=owner_run.id,
        is_current=True,
    )
    db_session.add(owner_metric)
    db_session.flush()
    owner_run.status = "succeeded"
    db_session.flush()
    db_session.add_all(
        [
            MetricFact(
                user_id=owner.id,
                stock_id=stock.id,
                metric_key="score.piotroski.total",
                value_numeric=8,
                value_json={
                    "status": "calculated",
                    "variant": "standard",
                    "fiscal_year": 2025,
                    "fact_nature": "derived_actual",
                    "calculation_version": "piotroski_value_line_v1",
                    "definition_basis": "derived",
                    "dimensions_identity": "empty",
                    "period_duration_kind": "fiscal_year",
                    "inputs": [
                        {
                            "fact_id": owner_metric.id,
                            "metric_key": owner_metric.metric_key,
                            "source_type": "parsed",
                        }
                    ],
                },
                unit="score_total",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="calculated",
                is_current=True,
            ),
            MetricFact(
                user_id=other.id,
                stock_id=stock.id,
                metric_key="private.other_user_metric",
                value_numeric=999,
                unit="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_document_id=other_doc.id,
                is_current=True,
            ),
            StockPrice(
                stock_id=stock.id,
                price_date=date(2026, 7, 17),
                open=90,
                high=101,
                low=89,
                close=100,
                volume=1000,
                currency="USD",
                source="twelvedata",
                created_at=datetime(2026, 7, 17, 22, tzinfo=timezone.utc),
            ),
            ResearchCoverageRequirement(
                user_id=owner.id,
                stock_id=stock.id,
                kind="value_line_current_report",
                priority_policy_version="research-coverage-priority-v1.0",
                matched_rule="open_case_queued",
                priority_rank=40,
                state="ready",
                reason="Current report exists.",
                freshness_policy_version="value-line-120d-v1.0",
                evaluated_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/research/cases/{case_id}/workspace",
        headers=auth_headers(owner),
    )
    hidden = client.get(
        f"/api/v1/research/cases/{case_id}/workspace",
        headers=auth_headers(other),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["case"]["id"] == case_id
    assert payload["current_price"]["observation_value"] == 100
    assert payload["current_price"]["currency"] == "USD"
    assert payload["documents"][0]["id"] == owner_doc.id
    assert {fact["metric_key"] for fact in payload["fundamentals"]} == {
        "returns.return_on_equity",
        "score.piotroski.total",
    }
    assert payload["piotroski_f_score"] == [
        {
            "fiscal_year": 2025,
            "period_end_date": "2025-12-31",
            "score": 8.0,
            "status": "calculated",
            "variant": "standard",
        }
    ]
    assert payload["valuation"]["display_state"] == "missing"
    assert payload["coverage"][0]["state"] == "ready"
    assert payload["holders_13f"]["status"] == "unavailable"
    assert hidden.status_code == 404


def test_workspace_reports_bounded_reconciliation_as_unavailable_instead_of_clear(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="workspace-reconciliation-bound@example.com")
    stock = _stock(db_session, "RECONBOUND")
    case_id = _create(client, auth_headers(user), stock.id).json()["case"]["id"]
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key=f"bounded.metric_{index:03d}",
                value_numeric=index,
                value_json={"manual_role": "original_input"},
                unit="ratio",
                period_type="AS_OF",
                period_end_date=date(2026, 9, 4),
                source_type="manual",
                is_current=True,
            )
            for index in range(251)
        ]
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/research/cases/{case_id}/workspace",
        headers=auth_headers(user),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_reconciliation"] == {
        "status": "partial",
        "reason_code": "reconciliation_bound_exceeded",
        "consumer_gate_status": "blocked",
        "limit": 250,
    }
    assert payload["piotroski_f_score"] == []
    assert payload["fundamentals"] == [
        {
            "id": None,
            "status": "unavailable",
            "reason_code": "reconciliation_bound_exceeded",
            "metric_key": None,
            "value_numeric": None,
            "value_text": None,
            "unit": None,
            "currency": None,
            "period_type": None,
            "period_end_date": None,
            "source_type": None,
            "source_document_id": None,
            "source_ref_id": None,
            "original_evidence_route": None,
        }
    ]


def test_workspace_redacts_only_blocked_reconciliation_slot(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="workspace-reconciliation-redaction@example.com")
    stock = _stock(db_session, "REDACT")
    case_id = _create(client, auth_headers(user), stock.id).json()["case"]["id"]
    documents = [
        PdfDocument(
            user_id=user.id,
            file_name=f"redact-{index}.pdf",
            source="upload",
            file_storage_key=f"private/redact-{index}.pdf",
            parse_status="parsed",
            stock_id=stock.id,
            identity_needs_review=False,
            report_date=date(2026, 1, 2),
        )
        for index in range(2)
    ]
    db_session.add_all(documents)
    db_session.flush()
    common_metadata = {
        "mapping_id": "returns.return_on_equity.fy",
        "source_mapping_version": "value-line-legacy-test",
        "definition_basis": "adjusted",
        "dimensions_identity": "empty",
        "fact_nature": "actual",
        "fiscal_year": 2025,
        "period_duration_kind": "fiscal_year",
    }
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="returns.return_on_equity",
                value_numeric=value,
                value_json=common_metadata,
                unit="ratio",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_document_id=document.id,
                is_current=True,
            )
            for document, value in zip(documents, (0.2, 0.3), strict=True)
        ]
        + [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="research.user_note_score",
                value_numeric=0.75,
                value_json={"manual_role": "original_input"},
                unit="ratio",
                period_type="AS_OF",
                period_end_date=date(2026, 9, 4),
                source_type="manual",
                is_current=True,
            )
        ]
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/research/cases/{case_id}/workspace",
        headers=auth_headers(user),
    )

    assert response.status_code == 200, response.text
    fundamentals = response.json()["fundamentals"]
    blocked = [
        item
        for item in fundamentals
        if item["metric_key"] == "returns.return_on_equity"
    ]
    assert len(blocked) == 1
    assert blocked[0]["status"] == "unavailable"
    assert blocked[0]["reason_code"] == "unresolved_source_reconciliation"
    assert blocked[0]["value_numeric"] is None
    assert [
        item["value_numeric"]
        for item in fundamentals
        if item["metric_key"] == "research.user_note_score"
    ] == ["0.750000000000"]


def test_workspace_rejects_historical_as_of_until_pit_reconstruction_exists(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="workspace-no-false-pit@example.com")
    stock = _stock(db_session, "NOPIT")
    case_id = _create(client, auth_headers(user), stock.id).json()["case"]["id"]
    historical_day = date.today() - timedelta(days=1)

    response = client.get(
        f"/api/v1/research/cases/{case_id}/workspace?as_of={historical_day.isoformat()}",
        headers=auth_headers(user),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "historical_as_of_not_supported"


def test_workspace_marks_last_published_value_under_review_after_monitoring_reopens(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(email="workspace-under-review@example.com")
    stock = _stock(db_session, "REVIEWING")
    headers = auth_headers(user)
    case_id = _create(client, headers, stock.id).json()["case"]["id"]
    assert client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=headers,
        json=_researching_revision(),
    ).status_code == 200
    assert client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=headers,
        json=_monitoring_revision(expected_head=1),
    ).status_code == 200
    assert client.post(
        f"/api/v1/research/cases/{case_id}/revisions",
        headers=headers,
        json=_researching_revision(expected_head=2),
    ).status_code == 200

    response = client.get(
        f"/api/v1/research/cases/{case_id}/workspace",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    valuation = response.json()["valuation"]
    assert valuation["user_intrinsic_value"] == 100
    assert valuation["display_state"] == "under_review"
