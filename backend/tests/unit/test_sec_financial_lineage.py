from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.edgar.parsers.financial_submissions import parse_financial_submissions
from app.edgar.parsers.inline_xbrl import parse_inline_xbrl
from app.models.facts import MetricFact
from app.models.sec_financials import (
    SecFilingArtifact,
    SecFinancialFiling,
    SecFinancialParseRun,
    SecFinancialParseRunArtifact,
    SecIssuerIdentity,
    SecRawXbrlFact,
)
from app.models.stocks import Stock
from app.services.sec_financial_ingestion import (
    SecFinancialFetchError,
    SecFinancialIntegrityError,
    SecFinancialIngestionError,
    _safe_artifact_url,
    _store_content_immutable,
    _fetch_bytes,
    _discover,
    ingest_latest_financial_filings,
    register_reviewed_sec_identity,
    retire_sec_identity,
    select_sec_financial_evidence_as_of,
)
from app.rate_guard.client import RateGuardFetchError


CIK = "0000320193"
ACCESSION = "0000320193-26-000079"
ACCESSION_RAW = ACCESSION.replace("-", "")
SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"
INDEX_URL = (
    f"https://www.sec.gov/Archives/edgar/data/320193/{ACCESSION_RAW}/index.json"
)
PRIMARY_URL = (
    f"https://www.sec.gov/Archives/edgar/data/320193/{ACCESSION_RAW}/aapl-20260627.htm"
)


INLINE_XBRL = b"""<!doctype html>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025"
      xmlns:dei="http://xbrl.sec.gov/dei/2025"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
<body>
  <xbrli:context id="D2026Q3">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
      <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">aapl:ProductsMember</xbrldi:explicitMember></xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-03-29</xbrli:startDate><xbrli:endDate>2026-06-27</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <xbrli:unit id="USDperShare"><xbrli:divide>
    <xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>
    <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
  </xbrli:divide></xbrli:unit>
  <ix:nonFraction id="fact-revenue" name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
      contextRef="D2026Q3" unitRef="USD" decimals="-6" scale="6"
      format="ixt:num-dot-decimal">94,000</ix:nonFraction>
  <ix:nonNumeric id="fact-name" name="dei:EntityRegistrantName" contextRef="D2026Q3"
      xml:lang="en-US" continuedAt="name-continuation">Apple Inc.</ix:nonNumeric>
  <ix:nonFraction id="fact-eps" name="us-gaap:EarningsPerShareDiluted"
      contextRef="D2026Q3" unitRef="USDperShare" decimals="2">1.50</ix:nonFraction>
</body></html>"""
SCHEMA_XBRL = b"<schema />\n"


def _submissions_payload() -> bytes:
    return json.dumps(
        {
            "cik": "320193",
            "name": "Apple Inc.",
            "fiscalYearEnd": "0926",
            "filings": {
                "recent": {
                    "accessionNumber": [ACCESSION, "0000320193-26-000070"],
                    "filingDate": ["2026-07-31", "2026-07-15"],
                    "reportDate": ["2026-06-27", "2026-07-15"],
                    "acceptanceDateTime": ["20260731160528", "20260715120000"],
                    "form": ["10-Q", "8-K"],
                    "primaryDocument": ["aapl-20260627.htm", "aapl-20260715.htm"],
                    "primaryDocDescription": ["10-Q", "8-K"],
                }
            },
        }
    ).encode()


def _index_payload() -> bytes:
    return json.dumps(
        {
            "directory": {
                "name": f"/Archives/edgar/data/320193/{ACCESSION_RAW}",
                "item": [
                    {
                        "name": "aapl-20260627.htm",
                        "type": "10-Q",
                        "size": len(INLINE_XBRL),
                        "description": "10-Q",
                    },
                    {
                        "name": "aapl-20260627.xsd",
                        "type": "EX-101.SCH",
                        "size": len(SCHEMA_XBRL),
                        "description": "XBRL TAXONOMY EXTENSION SCHEMA",
                    },
                    {
                        "name": "logo.png",
                        "type": "GRAPHIC",
                        "size": 10,
                        "description": "logo",
                    },
                ]
            }
        }
    ).encode()


class FakeEdgarClient:
    def __init__(self) -> None:
        schema_url = (
            f"https://www.sec.gov/Archives/edgar/data/320193/{ACCESSION_RAW}/"
            "aapl-20260627.xsd"
        )
        self.responses = {
            SUBMISSIONS_URL: _submissions_payload(),
            INDEX_URL: _index_payload(),
            PRIMARY_URL: INLINE_XBRL,
            schema_url: SCHEMA_XBRL,
        }
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        return self.responses[url]


class FlakyEdgarClient(FakeEdgarClient):
    def __init__(self) -> None:
        super().__init__()
        self.schema_url = next(url for url in self.responses if url.endswith(".xsd"))
        self.fail_schema_once = True

    def get(self, url: str) -> bytes:
        if url == self.schema_url and self.fail_schema_once:
            self.fail_schema_once = False
            raise RuntimeError("transient SEC fixture failure")
        return super().get(url)


class DeclaredSizeMismatchClient(FakeEdgarClient):
    def __init__(self) -> None:
        super().__init__()
        payload = json.loads(_index_payload())
        payload["directory"]["item"][0]["size"] = len(INLINE_XBRL) + 1
        self.responses[INDEX_URL] = json.dumps(payload).encode()


class NoFactsClient(FakeEdgarClient):
    def __init__(self) -> None:
        super().__init__()
        no_facts = b"<html><body>No inline XBRL facts.</body></html>"
        payload = json.loads(_index_payload())
        payload["directory"]["item"][0]["size"] = len(no_facts)
        self.responses[INDEX_URL] = json.dumps(payload).encode()
        self.responses[PRIMARY_URL] = no_facts


class HistoricalScanClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        recent = json.loads(_submissions_payload())
        recent["filings"]["files"] = [
            {"name": f"CIK{CIK}-submissions-{index:03d}.json"}
            for index in range(3)
        ]
        self.responses = {SUBMISSIONS_URL: json.dumps(recent).encode()}
        for index in range(3):
            self.responses[
                f"https://data.sec.gov/submissions/CIK{CIK}-submissions-{index:03d}.json"
            ] = json.dumps({"accessionNumber": []}).encode()

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        return self.responses[url]


class UnsafeHistoricalReferenceClient:
    def __init__(self, reference: object | None = None) -> None:
        self.calls: list[str] = []
        recent = json.loads(_submissions_payload())
        recent["filings"]["files"] = [
            reference
            if reference is not None
            else {"name": f"CIK{CIK}/../escaped.json"},
        ]
        self.responses = {SUBMISSIONS_URL: json.dumps(recent).encode()}

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        return self.responses[url]


class FailingRateGuardClient:
    def __init__(self, status_code: int | None) -> None:
        self.status_code = status_code

    def get(self, url: str) -> bytes:
        raise RateGuardFetchError("fixture failure", status_code=self.status_code)


@pytest.mark.parametrize(
    ("status_code", "reason_code"),
    [
        (None, "rate_guard_unavailable_or_blocked"),
        (403, "sec_forbidden"),
        (404, "sec_not_found"),
        (503, "sec_temporarily_unavailable"),
        (500, "sec_http_error"),
    ],
)
def test_rate_guard_failures_keep_typed_reason(
    status_code: int | None, reason_code: str
) -> None:
    with pytest.raises(SecFinancialFetchError) as exc:
        _fetch_bytes(FailingRateGuardClient(status_code), SUBMISSIONS_URL)

    assert exc.value.reason_code == reason_code


def test_financial_submissions_parser_filters_forms_and_preserves_acceptance_time() -> None:
    result = parse_financial_submissions(_submissions_payload(), source_url=SUBMISSIONS_URL)

    assert result.issuer.cik == CIK
    assert len(result.filings) == 1
    filing = result.filings[0]
    assert filing.accession_no == ACCESSION
    assert filing.form_type == "10-Q"
    assert filing.accepted_at.isoformat() == "2026-07-31T16:05:28-04:00"
    assert filing.primary_document == "aapl-20260627.htm"
    assert filing.discovery_payload_sha256 == hashlib.sha256(_submissions_payload()).hexdigest()


def test_inline_xbrl_parser_preserves_context_unit_dimensions_and_locator() -> None:
    facts = parse_inline_xbrl(INLINE_XBRL, artifact_id=77)

    assert len(facts) == 3
    revenue = facts[0]
    assert revenue.concept == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert revenue.concept_namespace_uri == "http://fasb.org/us-gaap/2025"
    assert revenue.context_id == "D2026Q3"
    assert revenue.unit_id == "USD"
    assert revenue.unit_measure == "iso4217:USD"
    assert revenue.period_start == date(2026, 3, 29)
    assert revenue.period_end == date(2026, 6, 27)
    assert revenue.dimensions == {
        "us-gaap:StatementBusinessSegmentsAxis": "aapl:ProductsMember"
    }
    assert revenue.raw_value == "94,000"
    assert revenue.transformation_format == "ixt:num-dot-decimal"
    assert revenue.decimals == "-6"
    assert revenue.scale == 6
    assert revenue.locator["artifact_id"] == 77
    assert revenue.locator["element_id"] == "fact-revenue"
    assert revenue.locator["nearby_text_sha256"]
    assert facts[1].language == "en-US"
    assert facts[1].continued_at == "name-continuation"
    assert facts[2].unit_measure == "iso4217:USD/xbrli:shares"


def test_artifact_paths_fail_closed_on_traversal_and_storage_corruption(
    tmp_path: Path,
) -> None:
    with pytest.raises(SecFinancialIngestionError, match="unsafe SEC artifact filename"):
        _safe_artifact_url(CIK, ACCESSION, "../escape.xml")

    content = b"expected bytes"
    expected_hash = hashlib.sha256(content).hexdigest()
    target = tmp_path / "financial" / expected_hash[:2] / expected_hash
    target.parent.mkdir(parents=True)
    target.write_bytes(b"corrupt bytes")
    with pytest.raises(SecFinancialIntegrityError, match="hash mismatch"):
        _store_content_immutable(tmp_path, content)


def _database_lineage_fixture(db_session, *, ticker: str, cik: str):
    stock = Stock(ticker=ticker, exchange="US", company_name=f"{ticker} Fixture")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=cik,
        effective_from=date(2020, 1, 1),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Database-boundary fixture.",
    )
    filing = SecFinancialFiling(
        issuer_identity_id=identity.id,
        accession_no=f"{cik}-26-000001",
        form_type="10-Q",
        is_amendment=False,
        filed_on=date(2026, 7, 31),
        report_date=date(2026, 6, 30),
        accepted_at=datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 1, tzinfo=timezone.utc),
        primary_document="fixture.htm",
        index_url="https://www.sec.gov/fixture/index.json",
        source_url="https://www.sec.gov/fixture/fixture.htm",
        submissions_source_url=f"https://data.sec.gov/submissions/CIK{cik}.json",
        discovery_payload_sha256="a" * 64,
    )
    db_session.add(filing)
    db_session.flush()
    artifact = SecFilingArtifact(
        filing_id=filing.id,
        sequence=1,
        filename="fixture.htm",
        source_url=filing.source_url,
        manifest_hash="b" * 64,
        state="retained",
        content_mime="text/html",
        sha256="c" * 64,
        byte_size=10,
        storage_key="financial/cc/" + "c" * 64,
        fetched_at=datetime(2026, 8, 27, 12, 2, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 2, tzinfo=timezone.utc),
    )
    db_session.add(artifact)
    db_session.commit()
    return stock, identity, filing, artifact


def _raw_fact(run_id: int, artifact_id: int, *, ordinal: int = 1) -> SecRawXbrlFact:
    return SecRawXbrlFact(
        parse_run_id=run_id,
        artifact_id=artifact_id,
        ordinal=ordinal,
        concept="us-gaap:Assets",
        raw_value="100",
        is_nil=False,
        dimensions_json={},
        locator_json={"artifact_id": artifact_id, "dom_ordinal": ordinal},
    )


def test_database_rejects_zero_fact_success_and_fact_count_mismatch(db_session) -> None:
    _, _, filing, artifact = _database_lineage_fixture(
        db_session, ticker="COUNT", cik="0000000021"
    )
    zero = SecFinancialParseRun(
        filing_id=filing.id,
        parser_name="fixture",
        parser_version="zero",
        input_manifest_hash="d" * 64,
        status="succeeded",
        started_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        fact_count=0,
    )
    db_session.add(zero)
    with pytest.raises(DBAPIError):
        db_session.commit()
    db_session.rollback()

    mismatch = SecFinancialParseRun(
        filing_id=filing.id,
        parser_name="fixture",
        parser_version="mismatch",
        input_manifest_hash="e" * 64,
        status="succeeded",
        started_at=datetime(2026, 8, 27, 12, 4, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 27, 12, 4, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 4, tzinfo=timezone.utc),
        fact_count=1,
    )
    db_session.add(mismatch)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=mismatch.id,
            artifact_id=artifact.id,
            known_at=mismatch.known_at,
        )
    )
    db_session.flush()
    with pytest.raises(DBAPIError, match="fact count mismatch"):
        db_session.execute(
            text("SET CONSTRAINTS trg_sec_financial_parse_runs_fact_count IMMEDIATE")
        )
    db_session.rollback()


def test_database_overwrites_parse_link_transaction_metadata(db_session) -> None:
    _, _, filing, artifact = _database_lineage_fixture(
        db_session, ticker="LATE", cik="0000000022"
    )
    failed_run = SecFinancialParseRun(
        filing_id=filing.id,
        parser_name="fixture",
        parser_version="failed",
        input_manifest_hash="f" * 64,
        status="failed",
        started_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        fact_count=0,
        error_code="fixture_failure",
    )
    db_session.add(failed_run)
    db_session.commit()
    db_session.refresh(failed_run)

    spoofed_created_at = failed_run.created_at + timedelta(seconds=1)
    link = SecFinancialParseRunArtifact(
        parse_run_id=failed_run.id,
        artifact_id=artifact.id,
        known_at=failed_run.known_at,
        created_at=spoofed_created_at,
        created_txid=failed_run.created_txid - 1,
    )
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)

    assert link.created_at >= failed_run.created_at
    assert link.created_at != spoofed_created_at
    assert link.created_txid == failed_run.created_txid


def test_database_rejects_filing_bound_to_needs_review_identity(db_session) -> None:
    stock, reviewed, _, _ = _database_lineage_fixture(
        db_session, ticker="REVIEW", cik="0000000023"
    )
    needs_review = SecIssuerIdentity(
        stock_id=stock.id,
        cik=reviewed.cik,
        status="needs_review",
        confidence=None,
        review_reason=None,
        effective_from=date(2020, 1, 1),
        known_at=datetime(2026, 8, 27, 13, 0, tzinfo=timezone.utc),
    )
    db_session.add(needs_review)
    db_session.flush()
    unreviewed_filing = SecFinancialFiling(
        issuer_identity_id=needs_review.id,
        accession_no="0000000023-26-000002",
        form_type="10-Q",
        is_amendment=False,
        filed_on=date(2026, 8, 1),
        report_date=date(2026, 6, 30),
        accepted_at=datetime(2026, 8, 1, 16, 0, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 13, 1, tzinfo=timezone.utc),
        primary_document="unreviewed.htm",
        index_url="https://www.sec.gov/unreviewed/index.json",
        source_url="https://www.sec.gov/unreviewed/unreviewed.htm",
        submissions_source_url="https://data.sec.gov/submissions/CIK0000000023.json",
        discovery_payload_sha256="f" * 64,
    )
    db_session.add(unreviewed_filing)
    with pytest.raises(DBAPIError, match="reviewed SEC issuer identity"):
        db_session.commit()
    db_session.rollback()


def test_declared_artifact_size_mismatch_is_rejected(db_session, tmp_path: Path) -> None:
    stock = Stock(ticker="SIZE", exchange="US", company_name="Size Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Declared-size fixture.",
    )
    db_session.commit()

    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=DeclaredSizeMismatchClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()

    primary = db_session.scalar(
        select(SecFilingArtifact).where(
            SecFilingArtifact.filename == "aapl-20260627.htm"
        )
    )
    assert primary.state == "rejected"
    assert primary.reason_code == "declared_size_mismatch"
    assert report.raw_facts_created == 0
    assert any("declared_size_mismatch" in failure for failure in report.failures)


def test_historical_discovery_has_request_budget(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.sec_financial_ingestion.MAX_HISTORICAL_SUBMISSION_FILES", 2
    )
    client = HistoricalScanClient()

    result = _discover(
        client,
        CIK,
        max_filings=1,
        as_of=datetime(2010, 1, 1, tzinfo=timezone.utc),
    )

    assert len(client.calls) == 3
    assert result.failures == ("history_scan_limit_exceeded",)


def test_historical_discovery_reports_unsafe_reference() -> None:
    client = UnsafeHistoricalReferenceClient()

    result = _discover(
        client,
        CIK,
        max_filings=1,
        as_of=datetime(2010, 1, 1, tzinfo=timezone.utc),
    )

    assert client.calls == [SUBMISSIONS_URL]
    assert result.filings == ()
    assert result.failures == (
        f"unsafe_historical_submission_reference:CIK{CIK}/../escaped.json",
    )


@pytest.mark.parametrize(
    ("reference", "failure_detail"),
    [
        pytest.param("not-an-object", "index=0:non_object", id="non-object"),
        pytest.param({}, "index=0:missing_name", id="missing-name"),
        pytest.param({"name": ""}, "index=0:empty_name", id="empty-name"),
        pytest.param(
            {"name": 123}, "index=0:name_not_string", id="non-string-name"
        ),
    ],
)
def test_historical_discovery_reports_malformed_reference(
    reference: object,
    failure_detail: str,
) -> None:
    client = UnsafeHistoricalReferenceClient(reference)

    result = _discover(
        client,
        CIK,
        max_filings=1,
        as_of=datetime(2010, 1, 1, tzinfo=timezone.utc),
    )

    assert client.calls == [SUBMISSIONS_URL]
    assert result.filings == ()
    assert result.failures == (
        f"unsafe_historical_submission_reference:{failure_detail}",
    )


def test_exact_failed_parse_replay_remains_a_failure(db_session, tmp_path: Path) -> None:
    stock = Stock(ticker="NOFACT", exchange="US", company_name="No Facts Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="No-facts fixture.",
    )
    db_session.commit()
    client = NoFactsClient()

    first = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()
    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert first.failures == (f"{ACCESSION}:no_inline_xbrl_facts",)
    assert second.failures == first.failures


def test_ingestion_is_idempotent_pit_safe_and_does_not_publish_metric_facts(
    db_session, tmp_path: Path
) -> None:
    stock = Stock(ticker="AAPL", exchange="US", company_name="Apple Inc.")
    db_session.add(stock)
    db_session.flush()
    registered_at = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=registered_at,
        review_reason="Locked FT-00 AAPL identity verified against SEC company tickers.",
    )
    db_session.commit()

    client = FakeEdgarClient()
    first = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
        parser_version="inline-xbrl-v1",
    )
    db_session.commit()
    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
        parser_version="inline-xbrl-v1",
    )
    db_session.commit()

    assert identity.status == "reviewed"
    assert first.filings_discovered == 1
    assert first.parse_runs_created == 1
    assert first.raw_facts_created == 3
    assert second.parse_runs_created == 0
    assert second.raw_facts_created == 0
    assert db_session.scalar(select(func.count()).select_from(SecFinancialFiling)) == 1
    assert db_session.scalar(select(func.count()).select_from(SecFilingArtifact)) == 5
    assert db_session.scalar(select(func.count()).select_from(SecFinancialParseRun)) == 1
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialParseRunArtifact)
    ) == 4
    assert db_session.scalar(select(func.count()).select_from(SecRawXbrlFact)) == 3
    assert db_session.scalar(select(func.count()).select_from(MetricFact)) == 0

    retained = db_session.scalars(
        select(SecFilingArtifact).where(SecFilingArtifact.state == "retained")
    ).all()
    assert len(retained) == 4
    for artifact in retained:
        stored = tmp_path / artifact.storage_key
        assert stored.is_file()
        assert hashlib.sha256(stored.read_bytes()).hexdigest() == artifact.sha256
    manifest_only = db_session.scalar(
        select(SecFilingArtifact).where(SecFilingArtifact.filename == "logo.png")
    )
    assert manifest_only is not None
    assert manifest_only.state == "manifest_only"
    assert manifest_only.storage_key is None
    discovery_names = {
        item.filename
        for item in retained
        if item.filename.startswith("__")
    }
    assert discovery_names == {"__submissions__.json", "__accession_index__.json"}
    first_run = db_session.scalar(select(SecFinancialParseRun))
    first_link_created_at = db_session.scalar(
        select(func.max(SecFinancialParseRunArtifact.created_at)).where(
            SecFinancialParseRunArtifact.parse_run_id == first_run.id
        )
    )
    after_ingestion_cutoff = max(first_run.known_at, first_link_created_at) + timedelta(
        seconds=1
    )

    before_identity = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=datetime(2026, 8, 27, 11, 59, tzinfo=timezone.utc),
    )
    after_ingestion = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=after_ingestion_cutoff,
    )
    assert before_identity == []
    assert len(after_ingestion) == 1
    assert after_ingestion[0].accession_no == ACCESSION
    assert after_ingestion[0].parser_version == "inline-xbrl-v1"

    retained_inputs = db_session.scalars(
        select(SecFilingArtifact).where(SecFilingArtifact.state == "retained")
    ).all()
    later_known_at = after_ingestion_cutoff + timedelta(minutes=10)
    later_run = SecFinancialParseRun(
        filing_id=first_run.filing_id,
        parser_name="valuepilot-inline-xbrl-lineage",
        parser_version="inline-xbrl-v2",
        input_manifest_hash="b" * 64,
        status="succeeded",
        started_at=later_known_at,
        completed_at=later_known_at,
        known_at=later_known_at,
        fact_count=1,
    )
    db_session.add(later_run)
    db_session.flush()
    db_session.add_all(
        [
            SecFinancialParseRunArtifact(
                parse_run_id=later_run.id,
                artifact_id=artifact.id,
                known_at=later_run.known_at,
            )
            for artifact in retained_inputs
        ]
    )
    primary_input = next(
        artifact
        for artifact in retained_inputs
        if artifact.filename == "aapl-20260627.htm"
    )
    db_session.add(_raw_fact(later_run.id, primary_input.id))
    db_session.commit()

    before_later_parser = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=later_known_at - timedelta(minutes=1),
    )
    after_later_parser = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=later_known_at + timedelta(minutes=1),
    )
    assert before_later_parser[0].parser_version == "inline-xbrl-v1"
    assert after_later_parser[0].parser_version == "inline-xbrl-v2"

    late_input = SecFilingArtifact(
        filing_id=first_run.filing_id,
        sequence=99,
        filename="late-input.xml",
        source_url="https://www.sec.gov/late-input.xml",
        manifest_hash="f" * 64,
        state="retained",
        content_mime="application/xml",
        sha256=retained_inputs[0].sha256,
        byte_size=retained_inputs[0].byte_size,
        storage_key=retained_inputs[0].storage_key,
        fetched_at=later_known_at + timedelta(minutes=10),
        known_at=later_known_at + timedelta(minutes=10),
    )
    db_session.add(late_input)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=later_run.id,
            artifact_id=late_input.id,
            known_at=later_run.known_at,
        )
    )
    with pytest.raises(DBAPIError, match="invalid SEC parse-run artifact link"):
        db_session.commit()
    db_session.rollback()

    amendment_accepted_at = later_known_at + timedelta(days=1)
    amendment_known_at = amendment_accepted_at + timedelta(days=1)
    amendment = SecFinancialFiling(
        issuer_identity_id=identity.id,
        accession_no="0000320193-26-000080",
        form_type="10-Q/A",
        is_amendment=True,
        filed_on=amendment_accepted_at.date(),
        report_date=date(2026, 6, 27),
        accepted_at=amendment_accepted_at,
        known_at=amendment_known_at,
        primary_document="aapl-20260627a.htm",
        primary_doc_description="10-Q/A",
        index_url="https://www.sec.gov/amendment-index.json",
        source_url="https://www.sec.gov/amendment.htm",
        submissions_source_url=SUBMISSIONS_URL,
        discovery_payload_sha256="c" * 64,
        amends_filing_id=first_run.filing_id,
    )
    db_session.add(amendment)
    db_session.flush()
    amended_artifact = SecFilingArtifact(
        filing_id=amendment.id,
        sequence=1,
        filename="aapl-20260627a.htm",
        source_url="https://www.sec.gov/amendment.htm",
        manifest_hash="d" * 64,
        state="retained",
        content_mime="text/html",
        sha256=retained_inputs[0].sha256,
        byte_size=retained_inputs[0].byte_size,
        storage_key=retained_inputs[0].storage_key,
        fetched_at=amendment_known_at,
        known_at=amendment_known_at,
    )
    db_session.add(amended_artifact)
    db_session.flush()
    amendment_run_known_at = amendment_known_at + timedelta(minutes=1)
    amendment_run = SecFinancialParseRun(
        filing_id=amendment.id,
        parser_name="valuepilot-inline-xbrl-lineage",
        parser_version="inline-xbrl-v1",
        input_manifest_hash="e" * 64,
        status="succeeded",
        started_at=amendment_run_known_at,
        completed_at=amendment_run_known_at,
        known_at=amendment_run_known_at,
        fact_count=1,
    )
    db_session.add(amendment_run)
    db_session.flush()
    db_session.refresh(amendment_run)
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=amendment_run.id,
            artifact_id=amended_artifact.id,
            known_at=amendment_run.known_at,
        )
    )
    db_session.flush()
    db_session.add(_raw_fact(amendment_run.id, amended_artifact.id))
    db_session.commit()

    before_amendment = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=amendment_accepted_at - timedelta(seconds=1),
    )
    after_amendment = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=amendment_run_known_at + timedelta(minutes=1),
    )
    assert [row.form_type for row in before_amendment] == ["10-Q"]
    assert {row.form_type for row in after_amendment} == {"10-Q", "10-Q/A"}

    retired_known_at = amendment_run_known_at + timedelta(days=1)
    retired = retire_sec_identity(
        db_session,
        identity_id=identity.id,
        known_at=retired_known_at,
        review_reason="Temporarily withdraw the issuer mapping.",
    )
    db_session.commit()
    assert select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=retired_known_at - timedelta(seconds=1),
    )
    assert select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=retired_known_at + timedelta(seconds=1),
    ) == []

    restored_known_at = retired_known_at + timedelta(days=1)
    restored = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=restored_known_at,
        review_reason="Explicitly re-approve the same stock-to-CIK mapping.",
        supersedes_identity_id=retired.id,
    )
    db_session.commit()
    restored_evidence = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=restored_known_at + timedelta(seconds=1),
    )
    assert restored.status == "reviewed"
    assert {row.form_type for row in restored_evidence} == {"10-Q", "10-Q/A"}

    replay_after_restore = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=restored_known_at + timedelta(minutes=1),
    )
    db_session.commit()
    assert replay_after_restore.filings_created == 0
    assert replay_after_restore.parse_runs_created == 0

    primary = db_session.scalar(
        select(SecFilingArtifact).where(
            SecFilingArtifact.filename == "aapl-20260627.htm",
            SecFilingArtifact.state == "retained",
        )
    )
    assert primary is not None and primary.storage_key
    (tmp_path / primary.storage_key).write_bytes(b"corrupted after first ingestion")
    with pytest.raises(SecFinancialIntegrityError, match="mismatch"):
        ingest_latest_financial_filings(
            db_session,
            stock_id=stock.id,
            client=client,
            storage_root=tmp_path,
            max_filings=1,
            now=restored_known_at + timedelta(minutes=2),
        )


def test_unavailable_required_artifact_retries_without_mutating_lineage(
    db_session, tmp_path: Path
) -> None:
    stock = Stock(ticker="RETRY", exchange="US", company_name="Retry Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Retry fixture identity.",
    )
    db_session.commit()
    client = FlakyEdgarClient()

    first = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()
    first_run = db_session.scalar(select(SecFinancialParseRun))
    assert first_run.status == "failed"
    assert first_run.error_code == "required_artifact_unavailable"
    assert first.raw_facts_created == 0
    linked_artifact_id = db_session.scalar(
        select(SecFinancialParseRunArtifact.artifact_id).where(
            SecFinancialParseRunArtifact.parse_run_id == first_run.id
        )
    )
    with pytest.raises(DBAPIError, match="requires succeeded run"):
        db_session.execute(
            text(
                "INSERT INTO sec_raw_xbrl_facts "
                "(parse_run_id, artifact_id, ordinal, concept, locator_json) "
                "VALUES (:run_id, :artifact_id, 1, 'us-gaap:Assets', '{}'::jsonb)"
            ),
            {"run_id": first_run.id, "artifact_id": linked_artifact_id},
        )
        db_session.commit()
    db_session.rollback()

    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.commit()
    runs = db_session.scalars(
        select(SecFinancialParseRun).order_by(SecFinancialParseRun.id)
    ).all()
    schema_observations = db_session.scalars(
        select(SecFilingArtifact)
        .where(SecFilingArtifact.filename == "aapl-20260627.xsd")
        .order_by(SecFilingArtifact.id)
    ).all()
    assert [run.status for run in runs] == ["failed", "succeeded"]
    assert [item.state for item in schema_observations] == ["unavailable", "retained"]
    assert second.artifacts_created == 1
    assert second.raw_facts_created == 3


def test_lineage_tables_reject_update_and_delete_at_database_boundary(
    db_session,
) -> None:
    stock = Stock(ticker="LOCK", exchange="US", company_name="Lock Fixture")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik="0000000001",
        effective_from=date(2020, 1, 1),
        known_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        review_reason="Database append-only fixture.",
    )
    db_session.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text("UPDATE sec_issuer_identities SET cik = '0000000002' WHERE id = :id"),
            {"id": identity.id},
        )
        db_session.commit()
    db_session.rollback()

    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text("DELETE FROM sec_issuer_identities WHERE id = :id"),
            {"id": identity.id},
        )
        db_session.commit()
    db_session.rollback()


def test_database_rejects_overlapping_reviewed_identity_even_if_service_is_bypassed(
    db_session,
) -> None:
    stock = Stock(ticker="OVLP", exchange="US", company_name="Overlap Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik="0000000011",
        effective_from=date(2020, 1, 1),
        known_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        review_reason="First reviewed identity.",
    )
    db_session.commit()

    with pytest.raises(DBAPIError, match="overlapping reviewed SEC issuer identity"):
        db_session.execute(
            text(
                "INSERT INTO sec_issuer_identities "
                "(stock_id, cik, status, review_reason, effective_from, known_at) "
                "VALUES (:stock_id, '0000000012', 'reviewed', 'bypass', "
                "'2021-01-01', '2026-08-28T00:00:00+00:00')"
            ),
            {"stock_id": stock.id},
        )
        db_session.commit()
    db_session.rollback()


def test_retirement_blocks_acquisition_until_explicit_superseding_review(
    db_session, tmp_path: Path
) -> None:
    stock = Stock(ticker="RET", exchange="US", company_name="Retirement Fixture")
    db_session.add(stock)
    db_session.flush()
    original = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc),
        review_reason="Original reviewed identity.",
    )
    retired = retire_sec_identity(
        db_session,
        identity_id=original.id,
        known_at=datetime(2026, 8, 27, 11, 0, tzinfo=timezone.utc),
        review_reason="Operator retired identity pending re-review.",
    )
    db_session.commit()

    with pytest.raises(SecFinancialIngestionError, match="reviewed SEC issuer identity"):
        ingest_latest_financial_filings(
            db_session,
            stock_id=stock.id,
            client=FakeEdgarClient(),
            storage_root=tmp_path,
            max_filings=1,
            now=datetime(2026, 8, 27, 11, 1, tzinfo=timezone.utc),
        )

    restored = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Explicit re-review after retirement.",
        supersedes_identity_id=retired.id,
    )
    db_session.commit()
    assert restored.supersedes_identity_id == retired.id
