from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import hash_password
from app.main import app
from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from app.models.sec_publication import SecMetricPublication
from app.models.users import User
from app.services.sec_metric_publication import (
    finalize_sec_publication,
    publish_sec_mapping_result,
)
from test_sec_metric_publication_service_e2e import _request
from test_sec_metric_publication_service_e2e import db as publication_db
from test_sec_metric_publication_service_e2e import isolated_engine


@pytest.fixture
def reconciliation_publication_client(publication_db, monkeypatch):
    def override_get_db():
        yield publication_db

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(
        "app.main.verify_live_rate_guard",
        lambda: "11111111-1111-4111-8111-111111111111",
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_sec_as_filed_and_value_line_adjusted_are_compared_without_precedence(
    reconciliation_publication_client,
    publication_db,
    tmp_path,
    auth_headers,
):
    request = _request(publication_db, tmp_path, ticker="RECONSEC")
    receipt = publish_sec_mapping_result(publication_db, request)
    publication_db.commit()
    finalize_sec_publication(publication_db, receipt.run_id)
    publication_db.commit()
    publication = (
        publication_db.query(SecMetricPublication)
        .filter_by(publication_run_id=receipt.run_id, status="published", fact_nature="actual")
        .filter(SecMetricPublication.metric_fact_id.is_not(None))
        .order_by(SecMetricPublication.id)
        .first()
    )
    assert publication is not None
    sec_fact = publication_db.get(MetricFact, publication.metric_fact_id)
    assert sec_fact is not None
    owner = User(
        email="sec-reconciliation-owner@example.com",
        hashed_password=hash_password("x"),
    )
    publication_db.add(owner)
    publication_db.flush()
    document = PdfDocument(
        user_id=owner.id,
        stock_id=request.stock_id,
        file_name="value-line.pdf",
        source="value_line",
        file_storage_key="private/value-line.pdf",
        report_date=date(2026, 1, 9),
        parse_status="parsed",
        parser_version="value-line-v1",
        identity_needs_review=False,
    )
    publication_db.add(document)
    publication_db.flush()
    period_start = publication.period_start_date
    duration_days = (
        (publication.period_end_date - period_start).days + 1
        if period_start is not None
        else None
    )
    adjusted = MetricFact(
        user_id=owner.id,
        stock_id=request.stock_id,
        metric_key=sec_fact.metric_key,
        value_numeric=sec_fact.value_numeric + 10,
        value_json={
            "fact_nature": "actual",
            "mapping_id": f"value-line:{sec_fact.metric_key}",
            "definition_basis": "adjusted",
            "period_start_date": period_start.isoformat() if period_start else None,
            "duration_days": duration_days,
            "dimensions_identity": publication.dimensions_sha256,
        },
        unit=sec_fact.unit,
        currency=sec_fact.currency,
        period_type=sec_fact.period_type,
        period_end_date=sec_fact.period_end_date,
        source_type="parsed",
        source_document_id=document.id,
        is_current=True,
    )
    publication_db.add(adjusted)
    publication_db.commit()

    response = reconciliation_publication_client.get(
        f"/api/v1/stocks/{request.stock_id}/source-reconciliation",
        headers=auth_headers(owner),
        params=[("metric_key", sec_fact.metric_key)],
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    compared = next(item for item in payload["items"] if len(item["fact_ids"]) == 2)
    assert compared["fact_ids"] == sorted([sec_fact.id, adjusted.id])
    assert compared["status"] == "expected_definition_difference", compared
    assert compared["reason_code"] == "as_filed_vs_adjusted"
    assert compared["blocking"] is False
    assert compared["absolute_variance"] == "10"
