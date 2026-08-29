from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models.artifacts import PdfDocument
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.research import (
    ResearchCase,
    ResearchCaseEvent,
    ResearchCaseOrigin,
    ResearchCaseRevision,
)
from app.models.stocks import Stock
from financial_truth_fixtures import authorize_parsed_facts


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
    from app.models.coverage import ResearchCoverageRequirement

    coverage = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(user_id=user.id, stock_id=stock.id, is_current=True)
        .order_by(ResearchCoverageRequirement.kind)
        .all()
    )
    assert [row.kind for row in coverage] == [
        "eod_price",
        "method_applicability",
        "value_line_current_report",
    ]
    assert {row.kind: row.state for row in coverage} == {
        "eod_price": "missing",
        "method_applicability": "unsupported",
        "value_line_current_report": "missing",
    }
    assert (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(user_id=user.id, stock_id=stock.id)
        .count()
        == 3
    )
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
        source="Value Line",
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


def test_evidence_retains_authorized_archived_document_and_fact_lineage(
    db_session, user_factory
):
    from app.services.research_cases import evidence_is_available

    owner = user_factory(email="evidence-archived-owner@example.com")
    stock = _stock(db_session, "EVARCH")
    document = PdfDocument(
        user_id=owner.id,
        stock_id=stock.id,
        file_name="archived.pdf",
        source="Value Line",
        file_storage_key="private/archived.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    document.lifecycle_state = "archived"
    document.retired_at = datetime.now(timezone.utc)
    document.retired_by_user_id = owner.id
    document.retirement_reason = "user_removed"
    db_session.flush()
    fact = MetricFact(
        user_id=owner.id,
        stock_id=stock.id,
        metric_key="is.net_income",
        value_numeric=100,
        source_type="parsed",
        source_document_id=document.id,
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        is_current=False,
    )
    authorize_parsed_facts(db_session, document=document, facts=[fact])
    db_session.commit()
    for source_type, source_id in [
        ("pdf_document", document.id),
        ("metric_fact", fact.id),
    ]:
        assert evidence_is_available(
            db_session,
            user_id=owner.id,
            stock_id=stock.id,
            source_type=source_type,
            source_id=source_id,
        )


def test_metric_fact_evidence_rejects_rows_without_exact_source_authority(
    db_session, user_factory
):
    from app.services.research_cases import evidence_is_available

    owner = user_factory(email="evidence-quarantine-owner@example.com")
    stock = _stock(db_session, "EVQUAR")
    document = PdfDocument(
        user_id=owner.id,
        stock_id=stock.id,
        file_name="quarantined.pdf",
        source="Value Line",
        file_storage_key="private/quarantined.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    legacy_rows = [
        MetricFact(
            user_id=owner.id,
            stock_id=stock.id,
            metric_key="is.revenue",
            value_numeric=999,
            source_type="parsed",
            source_document_id=document.id,
            period_type="FY",
            period_end_date=date(2025, 12, 31),
            is_current=False,
        ),
        MetricFact(
            user_id=owner.id,
            stock_id=stock.id,
            metric_key="score.piotroski_f",
            value_numeric=9,
            value_json={"method": "legacy"},
            source_type="calculated",
            period_type="FY",
            period_end_date=date(2025, 12, 31),
            is_current=False,
        ),
        MetricFact(
            user_id=owner.id,
            stock_id=stock.id,
            metric_key="val.fair_value",
            value_numeric=100,
            source_type="manual",
            period_type="AS_OF",
            period_end_date=date(2026, 1, 1),
            is_current=False,
        ),
    ]
    db_session.add_all(legacy_rows)
    db_session.flush()

    for fact in legacy_rows:
        assert not evidence_is_available(
            db_session,
            user_id=owner.id,
            stock_id=stock.id,
            source_type="metric_fact",
            source_id=fact.id,
        )


def test_multi_company_document_evidence_requires_exact_stock_authority(
    db_session, user_factory
):
    from app.services.research_cases import evidence_is_available

    owner = user_factory(email="evidence-multi-company@example.com")
    included_stock = _stock(db_session, "EVMULTI")
    unrelated_stock = _stock(db_session, "EVOTHER")
    document = PdfDocument(
        user_id=owner.id,
        stock_id=None,
        file_name="multi-company.pdf",
        source="Value Line",
        file_storage_key="private/multi-company.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    fact = MetricFact(
        user_id=owner.id,
        stock_id=included_stock.id,
        metric_key="is.revenue",
        value_numeric=100,
        source_type="parsed",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        is_current=True,
    )
    authorize_parsed_facts(db_session, document=document, facts=[fact])
    db_session.commit()

    assert evidence_is_available(
        db_session,
        user_id=owner.id,
        stock_id=included_stock.id,
        source_type="pdf_document",
        source_id=document.id,
    )
    assert not evidence_is_available(
        db_session,
        user_id=owner.id,
        stock_id=unrelated_stock.id,
        source_type="pdf_document",
        source_id=document.id,
    )


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
    case = ResearchCase(
        user_id=user.id,
        stock_id=stock.id,
        state="researching",
        head_revision_number=2,
    )
    db_session.add(case)
    db_session.flush()
    numeric_revision = ResearchCaseRevision(
        case_id=case.id,
        revision_number=1,
        case_state="researching",
        valuation_low=100,
        valuation_base=100,
        valuation_high=100,
        valuation_currency="USD",
        valuation_as_of_date=date(2026, 7, 19),
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        created_by_user_id=user.id,
    )
    unavailable_revision = ResearchCaseRevision(
        case_id=case.id,
        revision_number=2,
        case_state="researching",
        valuation_unavailable_reason="evidence_insufficient",
        valuation_as_of_date=date(2026, 7, 20),
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        created_by_user_id=user.id,
    )
    db_session.add_all([numeric_revision, unavailable_revision])
    db_session.flush()
    publish_user_intrinsic_value(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=100,
        as_of_date=date(2026, 7, 19),
        source_ref_id=numeric_revision.id,
    )
    publish_user_intrinsic_value(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=None,
        as_of_date=date(2026, 7, 20),
        unavailable_reason="evidence_insufficient",
        source_ref_id=unavailable_revision.id,
    )
    db_session.commit()

    selected = read_valuation_facts_by_stock(
        db_session, user_id=user.id, stock_ids=[stock.id]
    )[stock.id]["val.fair_value"]

    assert selected.value_numeric is None
    assert selected.value_json["reason"] == "evidence_insufficient"


def test_valuation_readers_reject_target_without_exact_active_parsed_lineage(
    db_session, user_factory
):
    from app.services.valuation import (
        read_valuation_context,
        read_valuation_facts_by_stock,
    )

    user = user_factory(email="forged-system-reference@example.com")
    stock = _stock(db_session, "FORGEDREF")
    unknown_source = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="target.price_18m.mid",
        value_numeric=999,
        unit="USD",
        period_type="TARGET_HORIZON",
        period_end_date=date(2027, 12, 31),
        source_type="untrusted",
        is_current=True,
    )
    db_session.add(unknown_source)
    with pytest.raises(DBAPIError, match="ck_metric_facts_source_type"):
        db_session.flush()
    db_session.rollback()

    documentless_manual = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="target.price_18m.mid",
        value_numeric=999,
        unit="USD",
        period_type="TARGET_HORIZON",
        period_end_date=date(2027, 12, 31),
        source_type="manual",
        is_current=True,
    )
    db_session.add(documentless_manual)
    with pytest.raises(DBAPIError, match="ck_metric_facts_manual_authority"):
        db_session.flush()
    db_session.rollback()

    context = read_valuation_context(
        db_session, user_id=user.id, stock_id=stock.id
    )
    batch = read_valuation_facts_by_stock(
        db_session, user_id=user.id, stock_ids=[stock.id]
    )

    assert context.system_reference_value is None
    assert context.system_reference_fact_id is None
    assert "target.price_18m.mid" not in batch[stock.id]


def test_database_rejects_forged_document_manual_correction_lineage(
    db_session, user_factory
):
    user = user_factory(email="forged-manual-lineage@example.com")
    stock = _stock(db_session, "FORGEDMAN")
    document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="forged-manual-lineage.pdf",
        source="value_line",
        file_storage_key="tests/forged-manual-lineage.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    slot = {
        "period_type": "FY",
        "period_end_date": date(2025, 12, 31),
    }
    parsed = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="revenue",
        value_numeric=100,
        unit="USD",
        currency="USD",
        source_type="parsed",
        is_current=True,
        **slot,
    )
    authorize_parsed_facts(db_session, document=document, facts=[parsed])
    db_session.flush()
    extraction = db_session.get(MetricExtraction, parsed.source_ref_id)
    assert extraction is not None
    db_session.commit()

    forged_metric = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="cogs",
        value_numeric=1,
        value_json={"correction": True},
        unit="USD",
        currency="USD",
        source_type="manual",
        source_document_id=document.id,
        source_ref_id=extraction.id,
        is_current=True,
        **slot,
    )
    db_session.add(forged_metric)
    with pytest.raises(DBAPIError, match="exact current parsed fact lineage"):
        db_session.flush()
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db_session.rollback()

    forged_currency = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="revenue",
        value_numeric=1,
        value_json={"correction": True},
        unit="USD",
        currency="EUR",
        source_type="manual",
        source_document_id=document.id,
        source_ref_id=extraction.id,
        is_current=True,
        **slot,
    )
    db_session.add(forged_currency)
    with pytest.raises(DBAPIError, match="exact current parsed fact lineage"):
        db_session.flush()
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db_session.rollback()


def test_valuation_readers_label_exact_document_correction_as_user_corrected(
    db_session, user_factory
):
    from app.services.valuation import (
        VALUE_LINE_TARGET_MANUAL_CORRECTION_REFERENCE,
        read_valuation_context,
        read_valuation_facts_by_stock,
    )

    user = user_factory(email="corrected-system-reference@example.com")
    stock = _stock(db_session, "CORRREF")
    document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="corrected-reference.pdf",
        source="value_line",
        file_storage_key="tests/corrected-reference.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    slot = {
        "period_type": "TARGET_HORIZON",
        "period_end_date": date(2027, 12, 31),
    }
    parsed = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="target.price_18m.mid",
        value_numeric=150,
        unit="USD",
        source_type="parsed",
        is_current=True,
        **slot,
    )
    authorize_parsed_facts(db_session, document=document, facts=[parsed])
    db_session.flush()
    extraction = db_session.get(MetricExtraction, parsed.source_ref_id)
    assert extraction is not None
    correction = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=parsed.metric_key,
        value_numeric=155,
        value_json={
            "correction": True,
            "corrected_from_fact_id": parsed.id,
        },
        unit="USD",
        source_type="manual",
        source_document_id=document.id,
        source_ref_id=extraction.id,
        is_current=True,
        **slot,
    )
    db_session.add(correction)
    db_session.commit()

    context = read_valuation_context(
        db_session, user_id=user.id, stock_id=stock.id
    )
    batch = read_valuation_facts_by_stock(
        db_session, user_id=user.id, stock_ids=[stock.id]
    )

    assert context.system_reference_value == 155
    assert (
        context.system_reference_type
        == VALUE_LINE_TARGET_MANUAL_CORRECTION_REFERENCE
    )
    assert batch[stock.id]["target.price_18m.mid"].id == correction.id

    conflicting_correction = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=parsed.metric_key,
        value_numeric=160,
        value_json={"correction": True},
        unit="USD",
        source_type="manual",
        source_document_id=document.id,
        source_ref_id=extraction.id,
        is_current=True,
        **slot,
    )
    db_session.add(conflicting_correction)
    with pytest.raises(
        DBAPIError, match="uq_metric_facts_current_manual_period_slot"
    ):
        db_session.flush()


def test_database_rejects_isolated_current_document_correction_demotion(
    db_session, user_factory
):
    user = user_factory(email="correction-demotion@example.com")
    stock = _stock(db_session, "CORRDEM")
    document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="correction-demotion.pdf",
        source="value_line",
        file_storage_key="tests/correction-demotion.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    slot = {
        "period_type": "FY",
        "period_end_date": date(2025, 12, 31),
    }
    parsed = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="revenue",
        value_numeric=100,
        unit="USD",
        currency="USD",
        source_type="parsed",
        is_current=True,
        **slot,
    )
    authorize_parsed_facts(db_session, document=document, facts=[parsed])
    db_session.flush()
    extraction = db_session.get(MetricExtraction, parsed.source_ref_id)
    assert extraction is not None
    correction = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="revenue",
        value_numeric=101,
        value_json={"correction": True},
        unit="USD",
        currency="USD",
        source_type="manual",
        source_document_id=document.id,
        source_ref_id=extraction.id,
        is_current=True,
        **slot,
    )
    db_session.add(correction)
    db_session.commit()

    db_session.execute(
        text("UPDATE metric_facts SET is_current = false WHERE id = :fact_id"),
        {"fact_id": correction.id},
    )
    with pytest.raises(
        DBAPIError,
        match="manual current fact demotion|exact current parsed fact lineage",
    ):
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db_session.rollback()

    assert db_session.get(MetricFact, correction.id).is_current is True


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
    client, db_session, user_factory, auth_headers
):
    from datetime import datetime, timezone

    from app.models.coverage import ResearchCoverageRequirement
    from app.models.stocks import StockPrice

    owner = user_factory(email="workspace-owner@example.com")
    other = user_factory(email="workspace-other@example.com")
    stock = _stock(db_session, "WORK")
    case_id = _create(client, auth_headers(owner), stock.id).json()["case"]["id"]
    owner_doc = PdfDocument(
        user_id=owner.id,
        stock_id=stock.id,
        file_name="owner.pdf",
        source="Value Line",
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
    coverage = (
        db_session.query(ResearchCoverageRequirement)
        .filter_by(
            user_id=owner.id,
            stock_id=stock.id,
            kind="value_line_current_report",
            priority_policy_version="research-coverage-priority-v1.0",
        )
        .one()
    )
    coverage.state = "ready"
    coverage.reason = "Current report exists."
    coverage.reason_code = None
    coverage.source_type = "pdf_document"
    coverage.source_ref_id = owner_doc.id
    coverage.next_action = None
    coverage.evaluated_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    db_session.add(coverage)
    owner_fact = MetricFact(
        user_id=owner.id,
        stock_id=stock.id,
        metric_key="returns.return_on_equity",
        value_numeric=0.21,
        unit="ratio",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="parsed",
        is_current=True,
    )
    other_fact = MetricFact(
        user_id=other.id,
        stock_id=stock.id,
        metric_key="private.other_user_metric",
        value_numeric=999,
        unit="USD",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="parsed",
        is_current=True,
    )
    authorize_parsed_facts(db_session, document=owner_doc, facts=[owner_fact])
    authorize_parsed_facts(db_session, document=other_doc, facts=[other_fact])
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
                },
                unit="score_total",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="calculated",
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
    assert payload["price"]["close"] == 100
    assert payload["price"]["currency"] == "USD"
    assert payload["documents"][0]["id"] == owner_doc.id
    assert {fact["metric_key"] for fact in payload["fundamentals"]} == {
        "returns.return_on_equity",
    }
    assert payload["piotroski_f_score"] == []
    assert payload["valuation"]["display_state"] == "missing"
    coverage_by_kind = {item["kind"]: item for item in payload["coverage"]}
    assert coverage_by_kind["value_line_current_report"]["state"] == "ready"
    assert coverage_by_kind["eod_price"]["state"] == "missing"
    assert coverage_by_kind["method_applicability"]["state"] == "unsupported"
    assert payload["holders_13f"]["status"] == "unavailable"
    assert hidden.status_code == 404

    archived = client.delete(
        f"/api/v1/documents/{owner_doc.id}", headers=auth_headers(owner)
    )
    assert archived.status_code == 200, archived.text
    refreshed = client.get(
        f"/api/v1/research/cases/{case_id}/workspace",
        headers=auth_headers(owner),
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["documents"] == []
    assert "returns.return_on_equity" not in {
        fact["metric_key"] for fact in refreshed.json()["fundamentals"]
    }


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
