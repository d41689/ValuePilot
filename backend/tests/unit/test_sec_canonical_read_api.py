import pytest
from fastapi.testclient import TestClient

from app.models.facts import MetricFact
from app.models.facts import Formula
from app.models.users import User
from app.services.sec_metric_publication import (
    finalize_sec_publication,
    publish_sec_mapping_result,
)
from test_sec_metric_publication_service_e2e import _request
from test_sec_metric_publication_service_e2e import db as publication_db
from test_sec_metric_publication_service_e2e import isolated_engine
from app.api.deps import get_db
from app.main import app
from app.core.security import hash_password
from app.services.canonical_financials import (
    CanonicalSourceConflictError,
    apply_reviewed_method_gates,
    reviewed_method_gate,
)
from app.services.formula_engine import FormulaEngine


FORBIDDEN_EVIDENCE_KEYS = {
    "raw_value",
    "raw_xml",
    "storage_key",
    "storage_path",
    "file_path",
    "signed_url",
    "artifact_id",
}


@pytest.fixture
def publication_client(publication_db, monkeypatch):
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


def _assert_safe(value):
    if isinstance(value, dict):
        assert not (set(value) & FORBIDDEN_EVIDENCE_KEYS)
        for nested in value.values():
            _assert_safe(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_safe(nested)
    elif isinstance(value, str):
        assert not value.startswith("file://")
        assert "/financial/" not in value


def test_authenticated_reads_share_sec_but_keep_private_facts_private(
    publication_client, publication_db, tmp_path, auth_headers
):
    request = _request(publication_db, tmp_path, ticker="READSEC")
    receipt = publish_sec_mapping_result(publication_db, request)
    publication_db.commit()
    finalize_sec_publication(publication_db, receipt.run_id)
    publication_db.commit()
    owner = User(email="sec-read-owner@example.com", hashed_password=hash_password("x"))
    viewer = User(email="sec-read-viewer@example.com", hashed_password=hash_password("x"))
    publication_db.add_all([owner, viewer])
    publication_db.commit()
    sec_fact = publication_db.query(MetricFact).filter_by(
        stock_id=request.stock_id, source_type="sec", is_current=True
    ).first()
    private = MetricFact(
        user_id=owner.id,
        stock_id=request.stock_id,
        metric_key=sec_fact.metric_key,
        value_numeric=sec_fact.value_numeric + 1,
        unit=sec_fact.unit,
        currency=sec_fact.currency,
        period_type=sec_fact.period_type,
        period_end_date=sec_fact.period_end_date,
        source_type="parsed",
        is_current=True,
    )
    publication_db.add(private)
    publication_db.commit()

    viewer_response = publication_client.get(
        f"/api/v1/stocks/{request.stock_id}/facts", headers=auth_headers(viewer)
    )
    owner_response = publication_client.get(
        f"/api/v1/stocks/{request.stock_id}/facts", headers=auth_headers(owner)
    )

    assert viewer_response.status_code == 200, viewer_response.text
    assert owner_response.status_code == 200, owner_response.text
    viewer_ids = {row["id"] for row in viewer_response.json() if row["id"] is not None}
    owner_ids = {row["id"] for row in owner_response.json() if row["id"] is not None}
    assert sec_fact.id in viewer_ids and private.id not in viewer_ids
    assert {sec_fact.id, private.id} <= owner_ids

    mixed_parsed = MetricFact(
        user_id=owner.id,
        stock_id=request.stock_id,
        metric_key="mixed_source_probe",
        value_numeric=1,
        source_type="parsed",
        is_current=True,
    )
    mixed_manual = MetricFact(
        user_id=owner.id,
        stock_id=request.stock_id,
        metric_key="mixed_source_probe",
        value_numeric=2,
        source_type="manual",
        is_current=True,
    )
    formula = Formula(
        user_id=owner.id,
        name="Mixed Source Result",
        expression="mixed_source_probe + 1",
        dependencies_json=["mixed_source_probe"],
    )
    publication_db.add_all([mixed_parsed, mixed_manual, formula])
    publication_db.commit()
    with pytest.raises(CanonicalSourceConflictError):
        FormulaEngine(publication_db).run_formula(formula.id, request.stock_id, owner.id)
    sec_payload = next(row for row in viewer_response.json() if row["id"] == sec_fact.id)
    evidence = publication_client.get(sec_payload["evidence_route"], headers=auth_headers(viewer))
    assert evidence.status_code == 200, evidence.text
    payload = evidence.json()
    assert payload["status"] == "published"
    assert payload["mapping_version"] == "sec-us-gaap-v1"
    assert payload["filings"][0]["accession"]
    assert payload["filings"][0]["form"] in {"10-Q", "10-K"}
    assert payload["filings"][0]["accepted_at"]
    assert payload["filings"][0]["parser_version"] == "xbrl-lineage-v2"
    assert payload["context_id"]
    assert payload["period"]["end"]
    assert payload["fact_nature"] in {"actual", "derived_actual"}
    assert payload["inputs"]
    _assert_safe(payload)

    conflict = publication_client.post(
        "/api/v1/screener/run",
        headers=auth_headers(owner),
        json={
            "type": "AND",
            "conditions": [
                {"metric": "mixed_source_probe", "operator": ">", "value": 0}
            ],
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "source_conflict"


def test_typed_unresolved_sec_state_is_observable_without_retained_content(
    publication_client, publication_db, tmp_path, auth_headers
):
    request = _request(publication_db, tmp_path, ticker="READGAP", normalize=False)
    receipt = publish_sec_mapping_result(publication_db, request)
    publication_db.commit()
    finalize_sec_publication(publication_db, receipt.run_id)
    publication_db.commit()
    user = User(email="sec-unresolved-reader@example.com", hashed_password=hash_password("x"))
    publication_db.add(user)
    publication_db.commit()

    response = publication_client.get(
        f"/api/v1/stocks/{request.stock_id}/facts", headers=auth_headers(user)
    )

    assert response.status_code == 200, response.text
    unresolved = [row for row in response.json() if row.get("status") == "unresolved"]
    assert unresolved
    assert all(row["reason_code"].startswith("unresolved_") for row in unresolved)
    evidence = publication_client.get(unresolved[0]["evidence_route"], headers=auth_headers(user))
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["status"] == "unresolved"
    assert evidence.json()["inputs"]
    _assert_safe(evidence.json())


def test_reviewed_method_policy_defaults_system_outputs_to_typed_unsupported(
    db_session, user_factory
):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import text

    reviewer = user_factory("method-gate-reader@example.com")
    from app.models.stocks import Stock
    from datetime import date

    company = Stock(ticker="METHOD", exchange="US", company_name="Method Gate")
    db_session.add(company)
    db_session.commit()
    decision = reviewed_method_gate(
        db_session,
        stock_id=company.id,
        method_key="owner_earnings",
        effective_as_of=date(2026, 8, 31),
    )
    assert decision.status == "unsupported"
    assert decision.reason_code == "classification_unreviewed"
    assert decision.method_policy_version_id == "sec-method-gate-v1"

    review_id = db_session.execute(
        text(
            """
            INSERT INTO sec_economic_classification_reviews
              (stock_id, economic_class, effective_from, reviewer_user_id, review_reason)
            VALUES (:stock_id, 'ordinary', '2026-01-01', :reviewer, 'reviewed test class')
            RETURNING id
            """
        ),
        {"stock_id": company.id, "reviewer": reviewer.id},
    ).scalar_one()
    db_session.commit()
    reviewed = reviewed_method_gate(
        db_session,
        stock_id=company.id,
        method_key="owner_earnings",
        effective_as_of=date(2026, 8, 31),
        knowledge_at=datetime.now(timezone.utc) + timedelta(seconds=1),
    )
    assert reviewed.status == "unsupported"
    assert reviewed.reason_code == "method_unsupported"
    assert reviewed.economic_class == "ordinary"
    assert reviewed.classification_review_id == review_id

    raw_actual = MetricFact(
        user_id=reviewer.id,
        stock_id=company.id,
        metric_key="per_share.eps",
        value_numeric=1,
        source_type="parsed",
        is_current=True,
    )
    unsupported_system = MetricFact(
        user_id=reviewer.id,
        stock_id=company.id,
        metric_key="owners_earnings_per_share",
        value_numeric=1,
        source_type="calculated",
        is_current=True,
    )
    user_formula = MetricFact(
        user_id=reviewer.id,
        stock_id=company.id,
        metric_key="owners_earnings_per_share_custom",
        value_numeric=1,
        value_json={"user_authored_formula": True},
        source_type="calculated",
        is_current=True,
    )
    kept, blocked, _ = apply_reviewed_method_gates(
        db_session,
        stock_id=company.id,
        facts=[raw_actual, unsupported_system, user_formula],
        effective_as_of=date(2026, 8, 31),
    )
    assert kept == [raw_actual, user_formula]
    assert blocked[0]["status"] == "unsupported"
    assert blocked[0]["method_key"] == "owner_earnings"
