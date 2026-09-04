from datetime import date, datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import hash_password
from app.main import app
from app.models.artifacts import PdfDocument, ValueLineParseRun
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.research import ResearchCase
from app.models.sec_publication import SecMetricPublication
from app.models.users import User
from app.services.sec_metric_publication import (
    PublicationRequest,
    VerifiedPublicationSource,
    finalize_sec_publication,
    publish_sec_mapping_result,
)
from app.services.ingestion_service import IngestionService
from app.services.sec_financial_ingestion import (
    finalize_sec_financial_ingestion_operation,
    ingest_latest_financial_filings,
)
from app.services import sec_financial_ingestion as financial_ingestion
from sqlalchemy import text
from test_sec_metric_publication_service_e2e import (
    _FailedAmendmentClient,
    _request,
)
from test_sec_metric_publication_service_e2e import db as publication_db
from test_sec_metric_publication_service_e2e import isolated_engine
from test_sec_financial_lineage import (
    CIK,
    GeneratedBalanceAndCashFlowAuthorityClient,
    INDEX_URL,
    SUBMISSIONS_URL,
    _canonical_artifact_url,
)


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


def _annual_total_assets_client() -> GeneratedBalanceAndCashFlowAuthorityClient:
    client = GeneratedBalanceAndCashFlowAuthorityClient()
    submissions = json.loads(client.responses[SUBMISSIONS_URL])
    recent = submissions["filings"]["recent"]
    recent["form"][0] = "10-K"
    recent["reportDate"][0] = "2026-06-30"
    client.responses[SUBMISSIONS_URL] = json.dumps(submissions).encode()
    for url, content in list(client.responses.items()):
        if url in {SUBMISSIONS_URL, INDEX_URL} or not isinstance(content, bytes):
            continue
        client.responses[url] = (
            content.replace(b"Jun. 27, 2026", b"Jun. 30, 2026")
            .replace(b"2026-06-27", b"2026-06-30")
            .replace(b"2025-09-28", b"2025-07-01")
            .replace(b"9 Months Ended", b"12 Months Ended")
            .replace(b">Q3</ix:nonNumeric>", b">FY</ix:nonNumeric>")
        )
    index = json.loads(client.responses[INDEX_URL])
    for item in index["directory"]["item"]:
        suffix = "/" + item["name"]
        artifact = next(
            (body for url, body in client.responses.items() if url.endswith(suffix)),
            None,
        )
        if isinstance(artifact, bytes):
            item["size"] = len(artifact)
    client.responses[INDEX_URL] = json.dumps(index).encode()
    return client


def _annual_total_assets_with_failed_amendment_client():
    client = _annual_total_assets_client()
    submissions = json.loads(client.responses[SUBMISSIONS_URL])
    recent = submissions["filings"]["recent"]
    values = {
        "accessionNumber": _FailedAmendmentClient.accession,
        "filingDate": "2026-08-28",
        "reportDate": "2026-06-30",
        "acceptanceDateTime": "20260828160528",
        "form": "10-K/A",
        "primaryDocument": _FailedAmendmentClient.primary,
        "primaryDocDescription": "10-K/A",
    }
    for key, value in values.items():
        recent[key].insert(0, value)
    client.responses[SUBMISSIONS_URL] = json.dumps(submissions).encode()
    index_url = _canonical_artifact_url(
        CIK, _FailedAmendmentClient.accession, "index.json"
    )
    primary_url = _canonical_artifact_url(
        CIK, _FailedAmendmentClient.accession, _FailedAmendmentClient.primary
    )
    no_facts = b"<html><body>amendment content unavailable for classification</body></html>"
    client.responses[index_url] = json.dumps(
        {
            "directory": {
                "item": [
                    {
                        "name": _FailedAmendmentClient.primary,
                        "type": "10-K/A",
                        "size": len(no_facts),
                        "description": "10-K/A",
                    }
                ]
            }
        }
    ).encode()
    client.responses[primary_url] = no_facts
    return client


def test_sec_as_filed_and_value_line_adjusted_are_compared_without_precedence(
    reconciliation_publication_client,
    publication_db,
    tmp_path,
    auth_headers,
):
    request = _request(
        publication_db,
        tmp_path,
        ticker="RECONSEC",
        client=_annual_total_assets_client(),
        concept_like="%Assets",
        rule_id="sec.total_assets",
    )
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
    page_json = {
        "meta": {"report_date": "2026-08-20"},
        "annual_financials": {
            "meta": {
                "currency": sec_fact.currency,
                "actual_years": [publication.fiscal_year],
                "estimate_years": [],
                "fiscal_year_end_month": 6,
            },
            "balance_sheet_and_returns_usd_millions": {
                "total_assets": {
                    str(publication.fiscal_year): (
                        float(sec_fact.value_numeric) / 1_000_000 + 1
                    )
                }
            },
        },
    }
    ingestion = IngestionService(publication_db)
    mapped = ingestion.mapping_spec.generate_facts(page_json)[0]
    generated = next(
        fact
        for fact in mapped
        if fact["metric_key"] == sec_fact.metric_key
        and fact["period_type"] == "FY"
        and fact["period_end_date"] == publication.period_end_date
    )
    parse_run = ValueLineParseRun(
        user_id=owner.id,
        document_id=document.id,
        parser_version="value-line-v1",
        source_mapping_version=generated["value_json"]["source_mapping_version"],
        status="running",
    )
    publication_db.add(parse_run)
    publication_db.flush()
    source_extraction = MetricExtraction(
        user_id=owner.id,
        document_id=document.id,
        page_number=1,
        field_key="tables_time_series",
        raw_value_text="Total Assets",
        original_text_snippet="Total Assets annual series",
        parser_version="value-line-v1",
        value_line_parse_run_id=parse_run.id,
    )
    publication_db.add(source_extraction)
    publication_db.flush()
    source_extraction_ids = ingestion._mapping_source_extraction_ids(
        generated,
        extraction_ids_by_key={"tables_time_series": [source_extraction.id]},
    )
    assert source_extraction_ids == (source_extraction.id,)
    ingestion._insert_metric_fact_from_mapping(
        user_id=owner.id,
        stock_id=request.stock_id,
        metric_key=generated["metric_key"],
        value_numeric=generated["value_numeric"],
        value_text=generated["value_text"],
        value_json=generated["value_json"],
        unit=generated["unit"],
        currency=generated["currency"],
        period_type=generated["period_type"],
        period_end_date=generated["period_end_date"],
        source_document_id=document.id,
        value_line_parse_run_id=parse_run.id,
        source_extraction_ids=source_extraction_ids,
    )
    parse_run.status = "succeeded"
    publication_db.flush()
    publication_db.commit()
    adjusted = publication_db.query(MetricFact).filter_by(
        user_id=owner.id,
        stock_id=request.stock_id,
        metric_key=sec_fact.metric_key,
        source_document_id=document.id,
    ).one()

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
    assert compared["absolute_variance"] == "1000000"
    assert adjusted.currency == sec_fact.currency
    assert adjusted.value_json["period_duration_kind"] == "fiscal_year"

    facts_response = reconciliation_publication_client.get(
        f"/api/v1/stocks/{request.stock_id}/facts",
        headers=auth_headers(owner),
    )
    assert facts_response.status_code == 200, facts_response.text
    facts_payload = facts_response.json()
    assert not any(
        row.get("status") == "published"
        and row.get("metric_key") == sec_fact.metric_key
        for row in facts_payload
    )
    blocked_slot = next(
        row
        for row in facts_payload
        if row.get("status") == "unavailable"
        and row.get("metric_key") == sec_fact.metric_key
    )
    assert blocked_slot["reason_code"] == "source_conflict"
    assert blocked_slot["source_types"] == ["parsed", "sec"]

    peer = User(
        email="sec-reconciliation-peer@example.com",
        hashed_password=hash_password("x"),
    )
    second_peer = User(
        email="sec-reconciliation-second-peer@example.com",
        hashed_password=hash_password("x"),
    )
    publication_db.add_all([peer, second_peer])
    publication_db.commit()
    peer_report = reconciliation_publication_client.get(
        f"/api/v1/stocks/{request.stock_id}/source-reconciliation",
        headers=auth_headers(peer),
        params=[("metric_key", sec_fact.metric_key)],
    ).json()
    second_peer_report = reconciliation_publication_client.get(
        f"/api/v1/stocks/{request.stock_id}/source-reconciliation",
        headers=auth_headers(second_peer),
        params=[("metric_key", sec_fact.metric_key)],
    ).json()
    assert peer_report["eligible_fact_ids"] == [sec_fact.id]
    assert second_peer_report["eligible_fact_ids"] == [sec_fact.id]
    assert peer_report["requesting_user_id"] == peer.id
    assert second_peer_report["requesting_user_id"] == second_peer.id
    assert peer_report["report_digest"] != second_peer_report["report_digest"]

    pre_policy = reconciliation_publication_client.get(
        f"/api/v1/stocks/{request.stock_id}/source-reconciliation",
        headers=auth_headers(peer),
        params={
            "metric_key": sec_fact.metric_key,
            "knowledge_cutoff": "2026-09-03T23:59:59Z",
        },
    )
    assert pre_policy.status_code == 200, pre_policy.text
    assert pre_policy.json()["status"] == "unavailable"
    assert pre_policy.json()["reason_code"] == (
        "reconciliation_policy_unavailable_at_cutoff"
    )
    assert pre_policy.json()["consumer_gate_status"] == "blocked"
    assert pre_policy.json()["point_in_time_status"] == (
        "policy_unavailable_at_cutoff"
    )


def test_reconciliation_api_fails_closed_for_unresolved_sec_amendment(
    reconciliation_publication_client,
    publication_db,
    tmp_path,
    auth_headers,
):
    original = _request(
        publication_db,
        tmp_path,
        ticker="RECONAMEND",
        client=_annual_total_assets_client(),
        concept_like="%Assets",
        rule_id="sec.total_assets",
    )
    initial = publish_sec_mapping_result(publication_db, original)
    publication_db.commit()
    finalize_sec_publication(publication_db, initial.run_id)
    publication_db.commit()

    sec_fact = publication_db.query(MetricFact).filter_by(
        stock_id=original.stock_id,
        source_type="sec",
        is_current=True,
    ).first()
    assert sec_fact is not None
    sec_publication = publication_db.get(SecMetricPublication, sec_fact.source_ref_id)
    assert sec_publication is not None
    owner = User(
        email="sec-reconciliation-amendment@example.com",
        hashed_password=hash_password("x"),
    )
    publication_db.add(owner)
    publication_db.flush()
    document = PdfDocument(
        user_id=owner.id,
        stock_id=original.stock_id,
        file_name="amendment-comparison.pdf",
        source="value_line",
        file_storage_key="private/amendment-comparison.pdf",
        parse_status="parsed",
        parser_version="value-line-v1",
        report_date=original.sources[0].available_at.date(),
        identity_needs_review=False,
    )
    publication_db.add(document)
    publication_db.flush()
    page_json = {
        "meta": {"report_date": "2026-08-20"},
        "annual_financials": {
            "meta": {
                "currency": sec_fact.currency,
                "actual_years": [sec_publication.fiscal_year],
                "estimate_years": [],
                "fiscal_year_end_month": 6,
            },
            "balance_sheet_and_returns_usd_millions": {
                "total_assets": {
                    str(sec_publication.fiscal_year): (
                        float(sec_fact.value_numeric) / 1_000_000 + 1
                    )
                }
            },
        },
    }
    ingestion = IngestionService(publication_db)
    generated = next(
        fact
        for fact in ingestion.mapping_spec.generate_facts(page_json)[0]
        if fact["metric_key"] == sec_fact.metric_key
        and fact["period_type"] == "FY"
        and fact["period_end_date"] == sec_publication.period_end_date
    )
    parse_run = ValueLineParseRun(
        user_id=owner.id,
        document_id=document.id,
        parser_version="value-line-v1",
        source_mapping_version=generated["value_json"]["source_mapping_version"],
        status="running",
    )
    publication_db.add(parse_run)
    publication_db.flush()
    source_extraction = MetricExtraction(
        user_id=owner.id,
        document_id=document.id,
        page_number=1,
        field_key="tables_time_series",
        raw_value_text="Total Assets",
        original_text_snippet="Total Assets annual series",
        parser_version="value-line-v1",
        value_line_parse_run_id=parse_run.id,
    )
    publication_db.add(source_extraction)
    publication_db.flush()
    source_extraction_ids = ingestion._mapping_source_extraction_ids(
        generated,
        extraction_ids_by_key={"tables_time_series": [source_extraction.id]},
    )
    assert source_extraction_ids == (source_extraction.id,)
    ingestion._insert_metric_fact_from_mapping(
        user_id=owner.id,
        stock_id=original.stock_id,
        metric_key=generated["metric_key"],
        value_numeric=generated["value_numeric"],
        value_text=generated["value_text"],
        value_json=generated["value_json"],
        unit=generated["unit"],
        currency=generated["currency"],
        period_type=generated["period_type"],
        period_end_date=generated["period_end_date"],
        source_document_id=document.id,
        value_line_parse_run_id=parse_run.id,
        source_extraction_ids=source_extraction_ids,
    )
    parse_run.status = "succeeded"
    publication_db.flush()
    publication_db.commit()
    parsed_fact = publication_db.query(MetricFact).filter_by(
        user_id=owner.id,
        stock_id=original.stock_id,
        metric_key=sec_fact.metric_key,
        source_document_id=document.id,
    ).one()

    report = ingest_latest_financial_filings(
        publication_db,
        stock_id=original.stock_id,
        client=_annual_total_assets_with_failed_amendment_client(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 17, tzinfo=timezone.utc),
        parser_version=financial_ingestion.PARSER_V2,
    )
    publication_db.commit()
    finalize_sec_financial_ingestion_operation(
        publication_db, operation_id=report.operation_id
    )
    publication_db.commit()
    failed = publication_db.execute(
        text(
            """
            SELECT pr.id, pr.filing_id, pr.parser_version,
                   pr.input_manifest_hash, f.accession_no, a.available_at
            FROM sec_financial_parse_runs pr
            JOIN sec_financial_filings f ON f.id=pr.filing_id
            JOIN sec_financial_lineage_availabilities a
              ON a.operation_id=pr.operation_id
            WHERE f.accession_no=:accession AND pr.status='failed'
            ORDER BY pr.id DESC LIMIT 1
            """
        ),
        {"accession": _FailedAmendmentClient.accession},
    ).mappings().one()
    failed_source = VerifiedPublicationSource(
        failed.id,
        failed.filing_id,
        failed.accession_no,
        failed.parser_version,
        failed.input_manifest_hash,
        failed.available_at,
    )
    amendment_request = PublicationRequest(
        original.stock_id,
        original.issuer_identity_id,
        original.mapping_version_id,
        failed.available_at,
        original.amendment_policy,
        original.sources + (failed_source,),
    )
    amended = publish_sec_mapping_result(publication_db, amendment_request)
    publication_db.commit()
    finalize_sec_publication(publication_db, amended.run_id)
    publication_db.commit()
    research_case = ResearchCase(
        user_id=owner.id,
        stock_id=original.stock_id,
        state="queued",
    )
    publication_db.add(research_case)
    publication_db.commit()

    response = reconciliation_publication_client.get(
        f"/api/v1/stocks/{original.stock_id}/source-reconciliation",
        headers=auth_headers(owner),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["consumer_gate_status"] == "blocked"
    assert payload["sec_unavailable_states"], payload
    assert any(
        row["reason_code"] == "unresolved_amendment_parse_failure"
        for row in payload["excluded"]
    )
    assert payload["sec_unavailable_states"][0]["reason_code"] == (
        "unresolved_amendment_parse_failure"
    )
    workspace_response = reconciliation_publication_client.get(
        f"/api/v1/research/cases/{research_case.id}/workspace",
        headers=auth_headers(owner),
    )
    assert workspace_response.status_code == 200, workspace_response.text
    workspace_facts = workspace_response.json()["fundamentals"]
    assert not any(
        row.get("id") == parsed_fact.id and row.get("value_numeric") is not None
        for row in workspace_facts
    )
    blocked_workspace_slot = next(
        row
        for row in workspace_facts
        if row.get("metric_key") == sec_fact.metric_key
        and row.get("status") == "unavailable"
    )
    assert blocked_workspace_slot["reason_code"] == "unresolved_source_reconciliation"
    assert blocked_workspace_slot["value_numeric"] is None
    failure_known_at = datetime.fromisoformat(
        payload["sec_unavailable_states"][0]["known_at"]
    )
    before_failure = reconciliation_publication_client.get(
        f"/api/v1/stocks/{original.stock_id}/source-reconciliation",
        headers=auth_headers(owner),
        params={"knowledge_cutoff": (failure_known_at - timedelta(microseconds=1)).isoformat()},
    )
    assert before_failure.status_code == 200, before_failure.text
    assert before_failure.json()["consumer_gate_status"] == "clear"
    assert before_failure.json()["sec_unavailable_states"] == []
