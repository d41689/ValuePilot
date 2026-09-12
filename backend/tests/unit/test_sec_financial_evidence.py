"""Real publication lineage in the pytest-only schema; no external fetches."""
import json

import pytest
from sqlalchemy import text

from app.models.facts import MetricFact
from app.services.canonical_financials import resolve_sec_publication_evidence
from app.services.research_cases import evidence_is_available
from app.services.sec_metric_publication import publish_sec_mapping_result, finalize_sec_publication
from test_sec_metric_publication_service_e2e import _request, _consolidated_generated_client
from test_sec_metric_publication_service_e2e import db as db_session, isolated_engine  # noqa: F401


def _simulate_retired_policy_in_isolated_schema(db):
    # Registry withdrawal currently requires an operator migration. Simulate its
    # postcondition only in the validated disposable schema, not in dev/public.
    from test_support.database_isolation import validate_test_schema_name
    schema = db.scalar(text("SELECT current_schema()"))
    validate_test_schema_name(schema)
    quoted = db.bind.dialect.identifier_preparer.quote_identifier(schema)
    target = f"{quoted}.sec_metric_mapping_versions"
    trigger = "trg_sec_metric_mapping_versions_immutable"
    db.execute(text(f"ALTER TABLE {target} DISABLE TRIGGER {trigger}"))
    try:
        db.execute(text(f"UPDATE {target} SET retired_at=clock_timestamp() WHERE id='sec-us-gaap-v1'"))
    finally:
        db.execute(text(f"ALTER TABLE {target} ENABLE TRIGGER {trigger}"))
    db.commit()


@pytest.fixture
def published(db_session, tmp_path):
    request = _request(db_session, tmp_path, ticker="EVIDENCE", client=_consolidated_generated_client())
    receipt = publish_sec_mapping_result(db_session, request)
    db_session.commit()
    finalize_sec_publication(db_session, receipt.run_id)
    db_session.commit()
    fact = db_session.get(MetricFact, receipt.fact_ids[0])
    return request.stock_id, fact


def test_exact_retained_occurrence_readable_and_bound_to_selected_fact(db_session, published):
    stock_id, fact = published
    result = resolve_sec_publication_evidence(db_session, stock_id=stock_id,
        publication_id=fact.source_ref_id, fact_id=fact.id)
    assert result["evidence_state"] == "available", result
    assert result["metric_fact_id"] == fact.id
    assert result["value_numeric_exact"] == format(fact.value_numeric, "f")
    statement = result["inputs"][0]["statement"]
    for field in ("raw_value", "display_value", "report_name", "row_label", "column_header", "context_id"):
        assert statement[field], (field, statement)
    assert statement["locator"]["occurrence_ordinal"] >= 0
    assert statement["raw_fact_id"] > 0
    assert statement["accession"] == result["inputs"][0]["accession"]
    assert statement["form"] == result["inputs"][0]["form"]
    assert statement["sec_url"].startswith("https://www.sec.gov/Archives/")
    assert result["inputs"][0]["kind"] == "as_filed_fact_metadata"
    serialized = json.dumps(result, default=str)
    assert "storage_key" not in serialized and "report_content" not in serialized
    assert result["filings"][0]["sec_url"].startswith("https://www.sec.gov/Archives/")
    assert resolve_sec_publication_evidence(db_session, stock_id=stock_id + 10000,
        publication_id=fact.source_ref_id, fact_id=fact.id) is None
    assert resolve_sec_publication_evidence(db_session, stock_id=stock_id,
        publication_id=fact.source_ref_id, fact_id=fact.id + 10000) is None


def test_shared_sec_reference_allowed_but_wrong_stock_or_missing_fact_rejected(db_session, user_factory, published):
    stock_id, fact = published
    user = user_factory("sec-evidence-user@example.com")
    assert evidence_is_available(db_session, user_id=user.id, stock_id=stock_id,
                                 source_type="metric_fact", source_id=fact.id)
    assert not evidence_is_available(db_session, user_id=user.id, stock_id=stock_id + 10000,
                                     source_type="metric_fact", source_id=fact.id)
    assert not evidence_is_available(db_session, user_id=user.id, stock_id=stock_id,
                                     source_type="metric_fact", source_id=99999999)


def test_authorized_superseded_fact_keeps_same_evidence_identity(db_session, user_factory, published):
    stock_id, fact = published
    user = user_factory("sec-history-user@example.com")
    db_session.execute(text("UPDATE metric_facts SET is_current=false WHERE id=:id"), {"id": fact.id})
    db_session.commit()
    result = resolve_sec_publication_evidence(db_session, stock_id=stock_id,
        publication_id=fact.source_ref_id, fact_id=fact.id)
    assert result["evidence_state"] == "available"
    assert result["currentness"] == "superseded"
    assert result["metric_fact_id"] == fact.id
    assert evidence_is_available(db_session, user_id=user.id, stock_id=stock_id,
                                 source_type="metric_fact", source_id=fact.id)


def test_evidence_endpoint_rejects_fact_mismatch_and_preserves_legacy_call(client, db_session, user_factory, auth_headers, published):
    stock_id, fact = published
    user = user_factory("sec-evidence-api@example.com")
    db_session.commit()
    path = f"/api/v1/stocks/{stock_id}/sec-publications/{fact.source_ref_id}/evidence"
    headers = auth_headers(user)
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers, params={"fact_id": fact.id + 10000}).status_code == 404
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.json()["evidence_state"] == "available"


def test_retired_mapping_removes_access_including_old_references(db_session, user_factory, published):
    stock_id, fact = published
    user = user_factory("sec-withdrawal@example.com")
    _simulate_retired_policy_in_isolated_schema(db_session)
    assert resolve_sec_publication_evidence(db_session, stock_id=stock_id,
        publication_id=fact.source_ref_id, fact_id=fact.id) is None
    assert not evidence_is_available(db_session, user_id=user.id, stock_id=stock_id,
                                     source_type="metric_fact", source_id=fact.id)


def test_missing_retained_labels_are_typed_unavailable_not_guessed(db_session, tmp_path):
    request = _request(db_session, tmp_path, ticker="OLDLOCATOR")
    receipt = publish_sec_mapping_result(db_session, request)
    db_session.commit()
    finalize_sec_publication(db_session, receipt.run_id)
    db_session.commit()
    fact = db_session.get(MetricFact, receipt.fact_ids[0])
    result = resolve_sec_publication_evidence(db_session, stock_id=request.stock_id,
        publication_id=fact.source_ref_id, fact_id=fact.id)
    assert result["evidence_state"] == "unavailable"
    assert result["evidence_reason_code"] == "evidence_text_unavailable"
    assert result["status"] == "published"
    assert result["metric_fact_id"] == fact.id
    assert result["inputs"] == []
    assert result["value_numeric"] is None
    assert result["value_numeric_exact"] is None
    assert not result["locator"]


@pytest.mark.parametrize("failure_stage,reason", [
    ("unpublished", "publication_not_published"),
    ("authority", "evidence_input_authority_unavailable"),
    ("statement", "evidence_locator_unavailable"),
    ("statement", "evidence_text_unavailable"),
    ("statement", "unsafe_evidence_text"),
    ("statement", "evidence_input_bound_exceeded"),
])
def test_unavailable_response_removes_all_partial_value_and_input_proof(monkeypatch, failure_stage, reason):
    from decimal import Decimal
    from app.services import canonical_financials, sec_financial_evidence as service

    publication = {"id": 8, "metric_fact_id": 7,
                   "status": "unresolved" if failure_stage == "unpublished" else "published",
                   "value_numeric": Decimal("123.45"), "is_current": True}
    monkeypatch.setattr(service, "database_evaluation_snapshot", lambda _session: None)
    monkeypatch.setattr(service, "authorized_publication", lambda _session, **kwargs: publication)
    monkeypatch.setattr(canonical_financials, "_legacy_sec_publication_evidence", lambda _session, **kwargs: {
        "publication_id": 8, "metric_fact_id": 7, "status": publication["status"],
        "value_numeric": Decimal("123.45"),
        "inputs": [{"canonical_operand": {"value_numeric": Decimal("77")}}],
        "locator": {"ordered_input_occurrences": [{"raw_fact_id": 123}]},
        "filings": [{"accession": "partial-filing-proof"}],
    })

    def graph(_session, *, include_statements, **kwargs):
        if failure_stage == "authority" or (failure_stage == "statement" and include_statements):
            raise service.EvidenceUnavailable(reason)
        return []

    monkeypatch.setattr(service, "_graph", graph)
    result = service.resolve_evidence(None, stock_id=66, publication_id=8, fact_id=7)
    assert result["evidence_state"] == "unavailable"
    assert result["evidence_reason_code"] == reason
    assert result["publication_id"] == 8 and result["metric_fact_id"] == 7
    assert result["status"] == publication["status"]
    assert result["value_numeric"] is None and result["value_numeric_exact"] is None
    assert result["inputs"] == []
    assert not result["locator"] and result["filings"] == []


@pytest.mark.parametrize("bad_text", ["<script>alert(1)</script>", "/Users/private/secret", "file:///tmp/x", "x" * 8001])
def test_unsafe_retained_text_never_becomes_evidence_html_or_internal_path(bad_text):
    from app.services.sec_financial_evidence import safe_evidence_text, EvidenceUnavailable
    with pytest.raises(EvidenceUnavailable):
        safe_evidence_text(bad_text, required=True)


def test_input_bound_is_failure_not_partial_evidence(db_session, published, monkeypatch):
    from app.services import sec_financial_evidence
    stock_id, fact = published
    monkeypatch.setattr(sec_financial_evidence, "MAX_EVIDENCE_INPUTS", 0)
    result = resolve_sec_publication_evidence(db_session, stock_id=stock_id,
        publication_id=fact.source_ref_id, fact_id=fact.id)
    assert result["evidence_reason_code"] == "evidence_input_bound_exceeded"
    assert result["inputs"] == [] and result["value_numeric_exact"] is None


def test_revision_save_and_reopen_uses_original_sec_identity(client, db_session, user_factory, auth_headers, published):
    stock_id, fact = published
    user = user_factory("sec-revision@example.com")
    db_session.commit()
    headers = auth_headers(user)
    created = client.post("/api/v1/research/cases", headers=headers, json={
        "stock_id": stock_id, "origin": {"origin_type": "manual", "origin_key": "s2",
        "source_version": "user-action-v1", "source_ref": {"entry_point": "ticker_search"}}})
    assert created.status_code in (200, 201), created.text
    case_id = created.json()["case"]["id"]
    evidence = {"source_type": "metric_fact", "source_id": fact.id, "label": "Reviewed revenue", "claim": "I reviewed the original revenue statement."}
    saved = client.post(f"/api/v1/research/cases/{case_id}/revisions", headers=headers, json={
        "expected_head_revision_number": 0, "target_state": "researching", "evidence": [evidence]})
    assert saved.status_code in (200, 201), saved.text
    db_session.execute(text("UPDATE metric_facts SET is_current=false WHERE id=:id"), {"id": fact.id})
    db_session.commit()
    reopened = client.get(f"/api/v1/research/cases/{case_id}", headers=headers)
    assert reopened.status_code == 200, reopened.text
    item = reopened.json()["head_revision"]["evidence"][0]
    assert item["access_status"] == "available" and item["source_id"] == fact.id
    assert item["financial_fact"]["fact_id"] == fact.id
    assert item["financial_fact"]["publication_id"] == fact.source_ref_id
    assert item["financial_fact"]["value_numeric_exact"] == format(fact.value_numeric, "f")
    stored = db_session.execute(text("SELECT evidence_json FROM research_case_revisions WHERE case_id=:id"), {"id": case_id}).scalar_one()
    assert "financial_fact" not in stored[0]  # projection, never a persistent numeric snapshot
    _simulate_retired_policy_in_isolated_schema(db_session)
    item = client.get(f"/api/v1/research/cases/{case_id}", headers=headers).json()["head_revision"]["evidence"][0]
    assert item["claim"] == evidence["claim"] and item["source_id"] == fact.id
    assert item["access_status"] == "source_unavailable" and "financial_fact" not in item


def test_derived_graph_requires_every_operand_and_preserves_sign_and_identity(monkeypatch):
    from decimal import Decimal
    from app.services import sec_financial_evidence as service
    root = {"id": 30}
    children = {10: {"id": 10, "status": "published", "metric_fact_id": 110, "value_numeric": Decimal("15")},
                20: {"id": 20, "status": "published", "metric_fact_id": 120, "value_numeric": Decimal("6")}}
    def inputs(_db, publication, _snapshot):
        if publication["id"] == 30:
            return [{"input_ordinal": 1, "arithmetic_sign": 1, "source_publication_id": 10},
                    {"input_ordinal": 2, "arithmetic_sign": -1, "source_publication_id": 20}]
        return [{"input_ordinal": 1, "arithmetic_sign": 1, "source_publication_id": None}]
    monkeypatch.setattr(service, "_inputs", inputs)
    monkeypatch.setattr(service, "authorized_publication", lambda _db, **kw: children.get(kw["publication_id"]))
    monkeypatch.setattr(service, "_raw_binding", lambda *a: {})
    monkeypatch.setattr(service, "_statement", lambda _db, publication, *a: {"raw_fact_id": publication["id"]})
    result = service._graph(None, stock_id=1, publication=root, snapshot=None,
                           include_statements=True, lock_authority=False)
    assert [item["arithmetic_sign"] for item in result] == [1, -1]
    assert [item["metric_fact_id"] for item in result] == [110, 120]
    assert [item["value_numeric_exact"] for item in result] == ["15", "6"]
    assert [item["inputs"][0]["statement"]["raw_fact_id"] for item in result] == [10, 20]
    del children[20]
    with pytest.raises(service.EvidenceUnavailable, match="evidence_input_authority_unavailable"):
        service._graph(None, stock_id=1, publication=root, snapshot=None,
                       include_statements=True, lock_authority=False)


def test_reference_does_not_share_other_users_nonsec_fact(db_session, user_factory, published):
    stock_id, _ = published
    owner = user_factory("sec-ref-owner@example.com")
    viewer = user_factory("sec-ref-other@example.com")
    fact = MetricFact(stock_id=stock_id, user_id=owner.id, metric_key="user.note", source_type="manual",
                      is_current=True, value_text="private", value_json={"manual_role": "original_input"})
    db_session.add(fact)
    db_session.flush()
    assert not evidence_is_available(db_session, stock_id=stock_id, user_id=viewer.id,
                                     source_type="metric_fact", source_id=fact.id)


def test_reference_does_not_share_legacy_null_owner_nonsec_fact():
    from types import SimpleNamespace
    # New NULL-owner manual inserts are already forbidden by the privacy DB
    # guard. The read branch must also reject a retained legacy NULL owner.
    row = SimpleNamespace(stock_id=66, user_id=None, source_type="manual")
    session = SimpleNamespace(get=lambda *args: row)
    assert not evidence_is_available(session, stock_id=66, user_id=1,
                                     source_type="metric_fact", source_id=12)
