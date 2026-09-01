from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.edgar.parsers.financial_submissions import parse_financial_submissions
from app.edgar.parsers.inline_xbrl import parse_inline_xbrl, parse_standalone_xbrl, safe_xml_root_name
from app.acceptance.sec_gold_report import build_case_report
from app.acceptance.sec_gold_audit import (
    _operation_database_audit,
    audit_case_report_operation,
    build_case_database_audit,
)
from app.models.facts import MetricFact
from app.models.sec_financials import (
    SecFilingArtifact,
    SecFinancialAccessionAttempt,
    SecFinancialAccessionAttemptArtifact,
    SecFinancialAcquisitionFailure,
    SecFinancialAcquisitionResolution,
    SecFinancialFiling,
    SecFinancialIngestionOperation,
    SecFinancialHistoryContinuation,
    SecFinancialLineageAvailability,
    SecFinancialOperationResult,
    SecFinancialOperationSnapshot,
    SecFinancialParseRun,
    SecFinancialParseRunArtifact,
    SecFinancialResourceAnchor,
    SecIssuerIdentity,
    SecRawXbrlFact,
    SecStatementFactAuthority,
    SecStatementOccurrenceEvidence,
    SecStatementReportReference,
    SecSubmissionSnapshot,
)
from app.models.stocks import Stock
from app.core.config import settings
from app.services.sec_financial_ingestion import (
    FinancialHistoryTarget,
    MAX_ARTIFACT_BYTES,
    RetainedFinancialReplayClient,
    SecFinancialFetchError,
    SecFinancialIntegrityError,
    SecFinancialIngestionError,
    _artifact_input_hash,
    _discover,
    _fetch_bytes,
    _manifest_items,
    _retain_item,
    _safe_artifact_url,
    _standalone_instance_artifact,
    _store_content_immutable,
    _unwrap_sec_document,
    _unique_missing_instance_candidate,
    build_retained_financial_replay_client,
    earliest_replayable_sec_financial_evidence_at,
    finalize_sec_financial_ingestion_operation,
    finalize_pending_sec_financial_ingestion_operations,
    has_pending_sec_financial_lineage,
    ingest_latest_financial_filings,
    register_reviewed_sec_identity,
    retire_sec_identity,
    select_sec_financial_evidence_as_of,
    select_sec_financial_failures_as_of,
)
from app.rate_guard.client import RateGuardFetchError
from test_support.database_isolation import (
    build_isolated_database_url,
    create_test_schema,
    drop_test_schema,
    new_test_schema_name,
)


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


def test_sec_sgml_document_unwrap_is_bounded_and_preserves_text_payload() -> None:
    payload = b'<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"/>'
    wrapped = (
        b"<DOCUMENT><TYPE>XML\n<SEQUENCE>12\n<FILENAME>aapl-20150627.xml\n"
        b"<DESCRIPTION>XBRL INSTANCE DOCUMENT\n<TEXT>" + payload + b"</TEXT></DOCUMENT>"
    )

    assert _unwrap_sec_document(wrapped) == payload
    assert _unwrap_sec_document(payload) == payload
    with pytest.raises(SecFinancialIngestionError, match="ambiguous TEXT"):
        _unwrap_sec_document(
            b"<DOCUMENT><TEXT><x/></TEXT><TEXT><y/></TEXT></DOCUMENT>"
        )


def test_retention_recognizes_generic_instance_filename_despite_sec_type() -> None:
    assert _retain_item(
        {
            "name": "aapl-20150627.xml",
            "type": "text.gif",
            "size": 1_658_267,
        },
        "d927922d10q.htm",
    )


def test_retained_replay_fetches_only_missing_manifest_instance() -> None:
    retained_index = b'{"directory":{"item":[]}}'
    instance = b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"/>'
    wrapped = b"<DOCUMENT><TYPE>XML\n<TEXT>" + instance + b"</TEXT></DOCUMENT>"
    index_url = "https://www.sec.gov/Archives/edgar/data/320193/old/index.json"
    sibling_url = "https://www.sec.gov/Archives/edgar/data/320193/old/R1.htm"
    instance_url = (
        "https://www.sec.gov/Archives/edgar/data/320193/old/aapl-20150627.xml"
    )

    class Upstream:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get(self, url: str) -> bytes:
            self.calls.append(url)
            return wrapped

        def get_revalidated(self, url: str) -> bytes:
            return self.get(url)

    upstream = Upstream()
    client = RetainedFinancialReplayClient(
        retained={index_url: retained_index, sibling_url: b"retained-report"},
        missing_instances={instance_url: len(wrapped)},
        upstream_factory=lambda: upstream,
    )

    assert client.get_revalidated(index_url) == retained_index
    assert client.get_revalidated(sibling_url) == b"retained-report"
    assert client.get_revalidated(instance_url) == wrapped
    assert client.get_revalidated(instance_url) == wrapped
    assert upstream.calls == [instance_url]
    assert client.external_requests == [instance_url]


@pytest.mark.parametrize(
    "declared_size",
    (None, 0, -1, MAX_ARTIFACT_BYTES + 1, True, "12"),
)
def test_retained_replay_rejects_invalid_instance_size_before_upstream(
    declared_size,
) -> None:
    instance_url = (
        "https://www.sec.gov/Archives/edgar/data/320193/old/aapl-20150627.xml"
    )
    constructed = 0

    def upstream_factory():
        nonlocal constructed
        constructed += 1
        raise AssertionError("invalid recovery authority reached upstream")

    client = RetainedFinancialReplayClient(
        retained={},
        missing_instances={instance_url: declared_size},  # type: ignore[dict-item]
        upstream_factory=upstream_factory,
    )
    with pytest.raises(
        SecFinancialIntegrityError, match="invalid declared size"
    ):
        client.get_revalidated(instance_url)
    assert constructed == 0
    assert client.external_requests == []


def test_nonnumeric_manifest_size_cannot_authorize_recovery_request() -> None:
    payload = json.dumps(
        {
            "directory": {
                "item": [
                    {
                        "name": "aapl-20150627.xml",
                        "type": "text.gif",
                        "size": "not-a-number",
                    }
                ]
            }
        }
    ).encode()
    item = _manifest_items(payload)[0]
    assert item["size"] is None
    client = RetainedFinancialReplayClient(
        retained={},
        missing_instances={"https://sec.example/aapl-20150627.xml": item["size"]},
        upstream_factory=lambda: pytest.fail("malformed size reached upstream"),
    )
    with pytest.raises(
        SecFinancialIntegrityError, match="invalid declared size"
    ):
        client.get("https://sec.example/aapl-20150627.xml")


def test_ambiguous_generic_instance_manifest_fails_before_any_request() -> None:
    requests: list[str] = []
    candidates = [
        SecFilingArtifact(
            filing_id=1,
            sequence=ordinal,
            filename=filename,
            sec_type="text.gif",
            declared_size=100,
            source_url=_canonical_artifact_url(CIK, ACCESSION, filename),
            manifest_hash="a" * 64,
            state="manifest_only",
            known_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        )
        for ordinal, filename in enumerate(
            ("aapl-20150627.xml", "second-instance.xml"), start=1
        )
    ]

    with pytest.raises(
        SecFinancialIntegrityError, match="manifest authority is ambiguous"
    ):
        _unique_missing_instance_candidate(
            candidates,
            cik=CIK,
            accession_no=ACCESSION,
        )
    assert requests == []


@pytest.mark.parametrize(
    "filename",
    (
        "FilingSummary.xml",
        "R1000.xml",
        "R0001.XML",
        "r42.xml",
        "aapl_cal.xml",
        "aapl_def.xml",
        "aapl_lab.xml",
        "aapl_pre.xml",
        "aapl_htm.xml",
        "aapl.xsd",
    ),
)
def test_retained_instance_selector_ignores_forbidden_xml_filenames_even_with_xbrl_root(
    tmp_path: Path,
    filename: str,
) -> None:
    content = (
        b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"/>'
    )
    storage_key, sha256 = _store_content_immutable(tmp_path, content)
    artifact = SecFilingArtifact(
        id=99,
        filing_id=1,
        sequence=1,
        filename=filename,
        sec_type="XML",
        declared_size=len(content),
        source_url=_canonical_artifact_url(CIK, ACCESSION, filename),
        manifest_hash="a" * 64,
        state="retained",
        storage_key=storage_key,
        sha256=sha256,
        byte_size=len(content),
        known_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )

    assert (
        _standalone_instance_artifact(
            [artifact],
            primary_document="d927922d10q.htm",
            storage_root=tmp_path,
        )
        is None
    )


def _canonical_artifact_url(cik: str, accession: str, filename: str) -> str:
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{filename}"
    )


def _commit_and_finalize(db_session, report) -> datetime:
    db_session.commit()
    available_at = finalize_sec_financial_ingestion_operation(
        db_session, operation_id=report.operation_id
    )
    db_session.commit()
    return available_at


@pytest.fixture
def committed_db_session():
    """Use real commits for post-commit lineage availability contracts."""
    configured = make_url(settings.SQLALCHEMY_DATABASE_URI)
    base_url = configured.set(
        query={key: value for key, value in configured.query.items() if key != "options"}
    ).render_as_string(hide_password=False)
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(base_url, schema_name)
    create_test_schema(base_url, schema_name)
    backend_dir = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=backend_dir,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    engine = create_engine(database_url, pool_pre_ping=True)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        drop_test_schema(base_url, schema_name)


INLINE_XBRL = b"""<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025"
      xmlns:dei="http://xbrl.sec.gov/dei/2025"
      xmlns:aapl="http://www.apple.com/20250628"
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
        self.revalidated_calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        return self.responses[url]

    def get_revalidated(self, url: str) -> bytes:
        self.revalidated_calls.append(url)
        return self.get(url)


class GeneratedReportXmlClient(FakeEdgarClient):
    def __init__(self, filename: str) -> None:
        super().__init__()
        report = (
            b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"/>'
        )
        payload = json.loads(_index_payload())
        payload["directory"]["item"].append(
            {
                "name": filename,
                "type": "XML",
                "size": len(report),
                "description": "Generated report XML",
            }
        )
        self.responses[INDEX_URL] = json.dumps(payload).encode()
        self.responses[_canonical_artifact_url(CIK, ACCESSION, filename)] = report


class StatementAuthorityClient(FakeEdgarClient):
    def __init__(self) -> None:
        super().__init__()
        summary = b"""<FilingSummary><MyReports><Report><Position>1</Position><ShortName>Statements of Operations</ShortName><Role>role/IncomeStatement</Role><XmlFileName>FinancialStatements.xml</XmlFileName></Report></MyReports></FilingSummary>"""
        report = b'''<Report><Columns><Column><Labels><Label Label="Three Months Ended June 27, 2026"/></Labels></Column><Column><Labels><Label Label="Nine Months Ended June 27, 2026"/></Labels></Column></Columns><Rows><Row><ElementName>us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax</ElementName><Cells><Cell contextRef="D2026Q3" factId="fact-revenue" unitRef="USD"><NumericAmount>94,000</NumericAmount></Cell><Cell contextRef="FY2026YTD" factId="fact-revenue-ytd" unitRef="USD"><NumericAmount>250,000</NumericAmount></Cell></Cells></Row></Rows></Report>'''
        primary = INLINE_XBRL.replace(b"</body>", b'''<xbrli:context id="FY2026YTD"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2025-09-28</xbrli:startDate><xbrli:endDate>2026-06-27</xbrli:endDate></xbrli:period></xbrli:context><ix:nonFraction id="fact-revenue-ytd" name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" contextRef="FY2026YTD" unitRef="USD" format="ixt:num-dot-decimal">250,000</ix:nonFraction><ix:nonNumeric id="fy-focus" name="dei:DocumentFiscalYearFocus" contextRef="FY2026YTD">2026</ix:nonNumeric><ix:nonNumeric id="fp-focus" name="dei:DocumentFiscalPeriodFocus" contextRef="FY2026YTD">Q3</ix:nonNumeric></body>''')
        payload = json.loads(_index_payload())
        payload["directory"]["item"][0]["size"] = len(primary)
        payload["directory"]["item"].extend([
            {"name": "FilingSummary.xml", "type": "XML", "size": len(summary), "description": "Filing Summary"},
            {"name": "FinancialStatements.xml", "type": "XML", "size": len(report), "description": "Statement"},
        ])
        self.responses[INDEX_URL] = json.dumps(payload).encode()
        self.responses[PRIMARY_URL] = primary
        self.responses[_canonical_artifact_url(CIK, ACCESSION, "FilingSummary.xml")] = summary
        self.responses[_canonical_artifact_url(CIK, ACCESSION, "FinancialStatements.xml")] = report


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


class MalformedMainSubmissionsClient:
    def get(self, url: str) -> bytes:
        assert url == SUBMISSIONS_URL
        return b'{"broken":'

    def get_revalidated(self, url: str) -> bytes:
        return self.get(url)


class MismatchedMainSubmissionsClient(MalformedMainSubmissionsClient):
    def get(self, url: str) -> bytes:
        assert url == SUBMISSIONS_URL
        payload = json.loads(_submissions_payload())
        payload["cik"] = "1067983"
        return json.dumps(payload).encode()


class ToggleMainPayloadClient(FakeEdgarClient):
    malformed = True

    def get(self, url: str) -> bytes:
        if self.malformed and url == SUBMISSIONS_URL:
            return b'{"broken":'
        return super().get(url)


class EmptyMainSubmissionsClient(MalformedMainSubmissionsClient):
    def get(self, url: str) -> bytes:
        assert url == SUBMISSIONS_URL
        payload = json.loads(_submissions_payload())
        for key in (
            "accessionNumber",
            "filingDate",
            "reportDate",
            "acceptanceDateTime",
            "form",
            "primaryDocument",
            "primaryDocDescription",
        ):
            payload["filings"]["recent"][key] = []
        return json.dumps(payload).encode()


class CorrectedEmptyMainSubmissionsClient(EmptyMainSubmissionsClient):
    def get(self, url: str) -> bytes:
        payload = json.loads(super().get(url))
        payload["name"] = "Apple Inc. corrected"
        return json.dumps(payload).encode()


class MalformedHistoricalSubmissionsClient:
    historical_url = (
        f"https://data.sec.gov/submissions/CIK{CIK}-submissions-001.json"
    )

    def __init__(self) -> None:
        main = json.loads(_submissions_payload())
        for key in (
            "accessionNumber",
            "filingDate",
            "reportDate",
            "acceptanceDateTime",
            "form",
            "primaryDocument",
            "primaryDocDescription",
        ):
            main["filings"]["recent"][key] = []
        main["filings"]["files"] = [
            {"name": f"CIK{CIK}-submissions-001.json"}
        ]
        self.responses = {
            SUBMISSIONS_URL: json.dumps(main).encode(),
            self.historical_url: b"not-json",
        }

    def get(self, url: str) -> bytes:
        return self.responses[url]

    def get_revalidated(self, url: str) -> bytes:
        return self.get(url)


class ToggleIndexOutageClient(FakeEdgarClient):
    unavailable = True

    def get_revalidated(self, url: str) -> bytes:
        if self.unavailable and url == INDEX_URL:
            raise RateGuardFetchError("upstream unavailable", status_code=503)
        return super().get_revalidated(url)


class ToggleInitialMainOutageClient(FakeEdgarClient):
    unavailable = True

    def __init__(self, status_code: int | None = 503) -> None:
        super().__init__()
        self.status_code = status_code

    def get(self, url: str) -> bytes:
        if self.unavailable and url == SUBMISSIONS_URL:
            raise RateGuardFetchError(
                "initial submissions outage", status_code=self.status_code
            )
        return super().get(url)


class OrderedHistoricalFetchOutageClient:
    first_url = f"https://data.sec.gov/submissions/CIK{CIK}-submissions-001.json"
    second_url = f"https://data.sec.gov/submissions/CIK{CIK}-submissions-002.json"

    def __init__(self) -> None:
        main = json.loads(_submissions_payload())
        for key in (
            "accessionNumber",
            "filingDate",
            "reportDate",
            "acceptanceDateTime",
            "form",
            "primaryDocument",
            "primaryDocDescription",
        ):
            main["filings"]["recent"][key] = []
        main["filings"]["files"] = [
            {"name": f"CIK{CIK}-submissions-001.json"},
            {"name": f"CIK{CIK}-submissions-002.json"},
        ]
        empty_history = {
            "accessionNumber": [],
            "filingDate": [],
            "reportDate": [],
            "acceptanceDateTime": [],
            "form": [],
            "primaryDocument": [],
            "primaryDocDescription": [],
        }
        self.responses = {
            SUBMISSIONS_URL: json.dumps(main).encode(),
            self.first_url: json.dumps(empty_history).encode(),
        }
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        if url == self.second_url:
            raise RateGuardFetchError("historical outage", status_code=503)
        return self.responses[url]

    def get_revalidated(self, url: str) -> bytes:
        return self.get(url)


class SwitchableHistoricalResourceClient:
    first_url = f"https://data.sec.gov/submissions/CIK{CIK}-submissions-001.json"
    second_url = f"https://data.sec.gov/submissions/CIK{CIK}-submissions-002.json"

    def __init__(self) -> None:
        self._set_main_reference("001")
        self.responses = {
            **self.responses,
            self.first_url: b"not-json",
            self.second_url: json.dumps(
                {
                    "accessionNumber": [],
                    "filingDate": [],
                    "reportDate": [],
                    "acceptanceDateTime": [],
                    "form": [],
                    "primaryDocument": [],
                    "primaryDocDescription": [],
                }
            ).encode(),
        }

    def _set_main_reference(self, suffix: str) -> None:
        main = json.loads(_submissions_payload())
        for key in (
            "accessionNumber",
            "filingDate",
            "reportDate",
            "acceptanceDateTime",
            "form",
            "primaryDocument",
            "primaryDocDescription",
        ):
            main["filings"]["recent"][key] = []
        main["filings"]["files"] = [
            {"name": f"CIK{CIK}-submissions-{suffix}.json"}
        ]
        self.responses = {SUBMISSIONS_URL: json.dumps(main).encode()}

    def resolve_same_resource(self) -> None:
        self.responses[self.first_url] = self.responses[self.second_url]

    def switch_to_different_resource(self) -> None:
        retained = {
            self.first_url: self.responses[self.first_url],
            self.second_url: self.responses[self.second_url],
        }
        self._set_main_reference("002")
        self.responses.update(retained)

    def get(self, url: str) -> bytes:
        return self.responses[url]

    def get_revalidated(self, url: str) -> bytes:
        return self.get(url)


class ChurningMainReusedMalformedHistoryClient(MalformedHistoricalSubmissionsClient):
    def churn_main(self) -> None:
        main = json.loads(self.responses[SUBMISSIONS_URL])
        main["name"] = "Changed issuer-wide metadata"
        self.responses[SUBMISSIONS_URL] = json.dumps(main).encode()


class ChangingSubmissionsClient(FakeEdgarClient):
    def add_unrelated_filing(self) -> None:
        payload = json.loads(self.responses[SUBMISSIONS_URL])
        payload["filings"]["recent"]["accessionNumber"][1] = (
            "0000320193-26-000071"
        )
        self.responses[SUBMISSIONS_URL] = json.dumps(payload).encode()

    def correct_accession_content(self) -> None:
        corrected = INLINE_XBRL.replace(b"94,000", b"95,000")
        payload = json.loads(self.responses[INDEX_URL])
        payload["directory"]["item"][0]["description"] = "10-Q corrected"
        payload["directory"]["item"][0]["size"] = len(corrected)
        self.responses[INDEX_URL] = json.dumps(payload).encode()
        self.responses[PRIMARY_URL] = corrected

    def correct_retained_bytes_without_index_change(self) -> None:
        corrected = INLINE_XBRL.replace(b"94,000", b"95,000")
        assert len(corrected) == len(INLINE_XBRL)
        self.responses[PRIMARY_URL] = corrected


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
        (429, "sec_temporarily_unavailable"),
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
    assert facts[2].unit_numerator == ({
        "namespace_uri": "http://www.xbrl.org/2003/iso4217",
        "local_name": "USD",
        "prefix": "iso4217",
    },)
    assert facts[2].unit_denominator == ({
        "namespace_uri": "http://www.xbrl.org/2003/instance",
        "local_name": "shares",
        "prefix": "xbrli",
    },)


def test_standalone_xbrl_parser_uses_namespace_authority_and_xml_locator() -> None:
    content = b'''<?xml version="1.0"?>
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2011-01-31"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
      <xbrli:context id="I"><xbrli:entity><xbrli:identifier scheme="sec">42</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:instant>2011-12-31</xbrli:instant></xbrli:period></xbrli:context>
      <xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
      <us-gaap:Assets contextRef="I" unitRef="USD" decimals="-6">123000000</us-gaap:Assets>
      <us-gaap:Liabilities contextRef="I" unitRef="USD" xsi:nil="true"/>
    </xbrli:xbrl>'''
    facts = parse_standalone_xbrl(content, artifact_id=88)
    assert len(facts) == 2
    assert facts[0].concept == "us-gaap:Assets"
    assert facts[0].concept_namespace_uri == "http://fasb.org/us-gaap/2011-01-31"
    assert facts[0].unit_numerator[0]["namespace_uri"] == "http://www.xbrl.org/2003/iso4217"
    assert facts[0].period_instant == date(2011, 12, 31)
    assert facts[0].locator["locator_type"] == "standalone_xbrl_xml"
    assert facts[1].is_nil is True


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (
            '<xbrli:context id="C"/><xbrli:context id="C"/>',
            "duplicate_xbrl_context_id",
        ),
        (
            '<xbrli:context id="C"/><xbrli:unit id="U"><xbrli:measure>bad:USD</xbrli:measure></xbrli:unit>',
            "undeclared_unit_qname_prefix",
        ),
        (
            '<xbrli:context id="C"/><xbrli:unit id="U"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator></xbrli:divide></xbrli:unit>',
            "invalid_xbrl_divide_unit",
        ),
        (
            '<us-gaap:Assets contextRef="missing" unitRef="missing">1</us-gaap:Assets>',
            "unknown_xbrl_context_ref",
        ),
    ],
)
def test_standalone_xbrl_parser_fails_closed_on_ambiguous_authority(
    body: str, error: str
) -> None:
    content = f'''<xbrli:xbrl
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">{body}</xbrli:xbrl>'''.encode()
    with pytest.raises(ValueError, match=error):
        parse_standalone_xbrl(content, artifact_id=1)


def test_standalone_xbrl_qname_uses_element_in_scope_prefix_rebinding() -> None:
    content = b'''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:u="urn:outer" xmlns:gaap="urn:gaap">
      <xbrli:context id="C"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:instant>2020-01-01</xbrli:instant></xbrli:period></xbrli:context>
      <xbrli:unit id="A"><xbrli:measure>u:outer</xbrli:measure></xbrli:unit>
      <xbrli:unit id="B" xmlns:u="urn:inner"><xbrli:measure>u:inner</xbrli:measure></xbrli:unit>
      <gaap:A contextRef="C" unitRef="A">1</gaap:A>
      <gaap:B contextRef="C" unitRef="B">2</gaap:B>
    </xbrli:xbrl>'''
    facts = parse_standalone_xbrl(content, artifact_id=1)
    assert facts[0].unit_numerator[0]["namespace_uri"] == "urn:outer"
    assert facts[1].unit_numerator[0]["namespace_uri"] == "urn:inner"


def test_typed_dimensions_preserve_structure_not_only_text() -> None:
    def parsed(fragment: str):
        return parse_standalone_xbrl(f'''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
          xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:d="urn:dimension" xmlns:t="urn:typed" xmlns:g="urn:gaap">
          <xbrli:context id="C"><xbrli:entity><xbrli:identifier>1</xbrli:identifier>
          <xbrli:segment><xbrldi:typedMember dimension="d:Axis">{fragment}</xbrldi:typedMember></xbrli:segment></xbrli:entity>
          <xbrli:period><xbrli:instant>2020-01-01</xbrli:instant></xbrli:period></xbrli:context>
          <g:Fact contextRef="C">1</g:Fact></xbrli:xbrl>'''.encode(), artifact_id=1)[0].dimensions_structured[0]

    attribute = parsed('<t:Value code="A"><t:Part>same</t:Part></t:Value>')
    nesting = parsed('<t:Value code="B"><t:Wrapper><t:Part>same</t:Part></t:Wrapper></t:Value>')
    assert attribute["typed_content_sha256"] != nesting["typed_content_sha256"]
    assert attribute["typed_structure"]["attributes"][0]["value"] == "A"
    assert nesting["typed_structure"]["children"][0]["name"]["local_name"] == "Wrapper"
    assert json.loads(attribute["typed_canonical"]) == attribute["typed_structure"]


def test_typed_dimension_structure_is_bounded() -> None:
    nested = "<t:N>" * 34 + "x" + "</t:N>" * 34
    content = f'''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:d="urn:d" xmlns:t="urn:t" xmlns:g="urn:g">
      <xbrli:context id="C"><xbrli:entity><xbrli:identifier>1</xbrli:identifier><xbrli:segment>
      <xbrldi:typedMember dimension="d:A"><t:Root>{nested}</t:Root></xbrldi:typedMember></xbrli:segment></xbrli:entity>
      <xbrli:period><xbrli:instant>2020-01-01</xbrli:instant></xbrli:period></xbrli:context>
      <g:F contextRef="C">1</g:F></xbrli:xbrl>'''.encode()
    with pytest.raises(ValueError, match="typed_dimension_resource_limit"):
        parse_standalone_xbrl(content, artifact_id=1)


def test_inline_v2_typed_dimension_uses_raw_xml_authority() -> None:
    content = b'''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:d="urn:axis" xmlns:t="urn:outer" xmlns:g="urn:gaap" xmlns:a="urn:attribute">
      <body><xbrli:context id="CustomerContext"><xbrli:entity><xbrli:identifier>1</xbrli:identifier>
      <xbrli:segment><xbrldi:typedMember dimension="d:CustomerID"><t:CustomerID a:Code="X">pre<t:Nested xmlns:t="urn:inner">child</t:Nested>tail</t:CustomerID></xbrldi:typedMember></xbrli:segment>
      </xbrli:entity><xbrli:period><xbrli:instant>2020-01-01</xbrli:instant></xbrli:period></xbrli:context>
      <ix:nonNumeric id="Fact" name="g:CustomerName" contextRef="CustomerContext">Acme</ix:nonNumeric></body></html>'''
    dimension = parse_inline_xbrl(content, artifact_id=1, strict=True)[0].dimensions_structured[0]
    structure = dimension["typed_structure"]
    assert dimension["axis"]["local_name"] == "CustomerID"
    assert structure["name"]["local_name"] == "CustomerID"
    assert structure["attributes"][0]["name"]["namespace_uri"] == "urn:attribute"
    assert structure["text"] == "pre"
    assert structure["children"][0]["name"]["local_name"] == "Nested"
    assert structure["children"][0]["name"]["namespace_uri"] == "urn:inner"
    assert structure["children"][0]["tail"] == "tail"


def test_inline_v2_typed_dimension_malformed_xhtml_fails_closed_but_v1_is_tolerant() -> None:
    malformed = b'''<html xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:d="urn:d" xmlns:t="urn:t" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:g="urn:g"><body>
      <xbrli:context id="C"><xbrli:entity><xbrli:identifier>1</xbrli:identifier><xbrli:segment>
      <xbrldi:typedMember dimension="d:A"><t:CustomerID>value</xbrldi:typedMember></xbrli:segment></xbrli:entity>
      <xbrli:period><xbrli:instant>2020-01-01</xbrli:instant></xbrli:period></xbrli:context>
      <ix:nonNumeric name="g:F" contextRef="C">1</ix:nonNumeric></body></html>'''
    with pytest.raises(ValueError, match="xml_parse_failed"):
        parse_inline_xbrl(malformed, artifact_id=1, strict=True)
    assert parse_inline_xbrl(malformed, artifact_id=1, strict=False)


@pytest.mark.parametrize(
    "mutated",
    [
        INLINE_XBRL.replace(b'<xbrli:context id="D2026Q3">', b'<fake:context xmlns:fake="urn:fake" id="D2026Q3">').replace(b'</xbrli:context>', b'</fake:context>'),
        INLINE_XBRL.replace(b'<xbrli:unit id="USD">', b'<fake:unit xmlns:fake="urn:fake" id="USD">').replace(b'</xbrli:unit>', b'</fake:unit>', 1),
        INLINE_XBRL.replace(b'<ix:nonFraction id="fact-revenue"', b'<fake:nonFraction xmlns:fake="urn:fake" id="fact-revenue"', 1).replace(b'</ix:nonFraction>', b'</fake:nonFraction>', 1),
    ],
)
def test_inline_v2_rejects_fake_namespace_structural_locals(mutated: bytes) -> None:
    with pytest.raises(ValueError, match="structural_namespace"):
        parse_inline_xbrl(mutated, artifact_id=1, strict=True)


def test_inline_v2_accepts_authorized_2020_ix_namespace_and_custom_concept() -> None:
    content = INLINE_XBRL.replace(
        b"http://www.xbrl.org/2013/inlineXBRL",
        b"http://www.xbrl.org/2020/inlineXBRL",
    ).replace(b"xmlns:aapl=", b'xmlns:custom="urn:custom" xmlns:aapl=').replace(
        b"name=\"dei:EntityRegistrantName\"", b"name=\"custom:MixedConcept\""
    )
    facts = parse_inline_xbrl(content, artifact_id=1, strict=True)
    assert facts[1].concept == "custom:MixedConcept"
    assert facts[1].concept_namespace_uri == "urn:custom"


@pytest.mark.parametrize("declaration", [
    b'<!DOCTYPE html>',
    b'<!   DOCTYPE html [<!ENTITY x "boom">]>',
    b'<!ENTITY x SYSTEM "file:///etc/passwd">',
])
def test_inline_v2_rejects_dtd_and_entity_declarations(declaration: bytes) -> None:
    with pytest.raises(ValueError, match="unsafe_xml_declaration|xml_parse_failed"):
        parse_inline_xbrl(declaration + INLINE_XBRL, artifact_id=1, strict=True)


def test_inline_v2_full_document_depth_budget_fails_early() -> None:
    content = b'<html xmlns="http://www.w3.org/1999/xhtml">' + b"<div>" * 130 + b"x" + b"</div>" * 130 + b"</html>"
    with pytest.raises(ValueError, match="xml_resource_limit"):
        parse_inline_xbrl(content, artifact_id=1, strict=True)


@pytest.mark.parametrize("local", [
    "context", "unit", "entity", "segment", "scenario", "period", "forever",
    "startDate", "endDate", "instant", "identifier", "measure", "divide",
    "unitNumerator", "unitDenominator", "explicitMember", "typedMember",
    "nonFraction", "nonNumeric", "continuation", "hidden", "references",
])
def test_inline_v2_rejects_every_protected_local_in_foreign_namespace(local: str) -> None:
    content = f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:fake="urn:fake"><body><fake:{local}/></body></html>'.encode()
    with pytest.raises(ValueError, match="structural_namespace"):
        parse_inline_xbrl(content, artifact_id=1, strict=True)


@pytest.mark.parametrize("member", ["explicitMember", "typedMember"])
def test_standalone_rejects_fake_xbrldi_dimension_members(member: str) -> None:
    content = f'''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:fake="urn:fake" xmlns:d="urn:d" xmlns:g="urn:g">
      <xbrli:context id="C"><xbrli:entity><xbrli:identifier>1</xbrli:identifier><xbrli:segment>
      <fake:{member} dimension="d:A">d:M</fake:{member}></xbrli:segment></xbrli:entity>
      <xbrli:period><xbrli:instant>2020-01-01</xbrli:instant></xbrli:period></xbrli:context>
      <g:F contextRef="C">1</g:F></xbrli:xbrl>'''.encode()
    with pytest.raises(ValueError, match="invalid_xbrldi_structural_namespace"):
        parse_standalone_xbrl(content, artifact_id=1)


@pytest.mark.parametrize("declaration", [
    '<!DOCTYPE xbrli:xbrl [<!ENTITY bomb "ha">]>',
    '<!DOCTYPE xbrli:xbrl [<!ENTITY ext SYSTEM "file:///etc/passwd">]>',
])
def test_standalone_rejects_entities_before_xml_parsing(declaration: str) -> None:
    content = (declaration + '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"/>').encode()
    with pytest.raises(ValueError, match="unsafe_xml_declaration"):
        parse_standalone_xbrl(content, artifact_id=1)


@pytest.mark.parametrize("wrapper", [
    lambda text: f"<!-- {text} -->",
    lambda text: f"<![CDATA[{text}]]>",
    lambda text: f"<?safe value='{text}'?>",
])
def test_safe_xml_preflight_does_not_confuse_lexical_text_with_declarations(wrapper) -> None:
    content = f'<root>{wrapper("<!DOCTYPE x [<!ENTITY y z>]")}</root>'.encode()
    assert safe_xml_root_name(content) == ("", "root")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_safe_xml_preflight_rejects_real_doctype_in_supported_encodings(encoding: str) -> None:
    content = '<!DOCTYPE root [<!ENTITY x "boom">]><root>&x;</root>'.encode(encoding)
    with pytest.raises(ValueError, match="unsafe_xml_declaration"):
        safe_xml_root_name(content)


@pytest.mark.parametrize("encoding, declaration", [
    ("utf-8", "UTF-8"), ("utf-16", "UTF-16"), ("utf-32", "UTF-32"),
])
def test_safe_xml_preflight_and_standalone_accept_legal_declared_encodings(
    encoding: str, declaration: str
) -> None:
    lexical = f'''<?xml version="1.0" encoding="{declaration}"?>
      <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:g="urn:g">
      <xbrli:context id="C"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:instant>2020-01-01</xbrli:instant></xbrli:period></xbrli:context>
      <g:F contextRef="C">1</g:F></xbrli:xbrl>'''
    content = lexical.encode(encoding)
    assert safe_xml_root_name(content) == ("http://www.xbrl.org/2003/instance", "xbrl")
    assert parse_standalone_xbrl(content, artifact_id=1)[0].raw_value == "1"


def test_safe_xml_preflight_rejects_bom_encoding_direction_mismatch() -> None:
    content = '<?xml version="1.0" encoding="UTF-16BE"?><root/>'.encode("utf-16le")
    content = b"\xff\xfe" + content
    with pytest.raises(ValueError, match="xml_encoding_bom_mismatch"):
        safe_xml_root_name(content)


def test_standalone_parser_has_no_caller_controlled_preflight_bypass() -> None:
    unsafe = b'<!DOCTYPE xbrli:xbrl [<!ENTITY x "boom">]><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">&x;</xbrli:xbrl>'
    bypass_keyword = "preflight" + "ed"
    with pytest.raises(TypeError, match="unexpected keyword"):
        parse_standalone_xbrl(unsafe, artifact_id=1, **{bypass_keyword: True})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unsafe_xml_declaration"):
        parse_standalone_xbrl(unsafe, artifact_id=1)


def test_standalone_parser_cannot_bypass_whole_document_resource_budget() -> None:
    content = (b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
               + b"<xbrli:scenario>" * 130 + b"x" + b"</xbrli:scenario>" * 130
               + b"</xbrli:xbrl>")
    with pytest.raises(ValueError, match="xml_resource_limit"):
        parse_standalone_xbrl(content, artifact_id=1)


@pytest.mark.parametrize("encoding, declaration", [
    ("utf-8", "UTF-8"), ("utf-16", "UTF-16"), ("utf-32", "UTF-32"),
])
def test_inline_v2_accepts_legal_declared_encodings(encoding: str, declaration: str) -> None:
    lexical = f'<?xml version="1.0" encoding="{declaration}"?>' + INLINE_XBRL.decode()
    facts = parse_inline_xbrl(lexical.encode(encoding), artifact_id=1, strict=True)
    assert facts[0].concept_namespace_uri == "http://fasb.org/us-gaap/2025"


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


def _database_lineage_fixture(
    db_session,
    storage_root: Path,
    *,
    ticker: str,
    cik: str,
):
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
    operation = SecFinancialIngestionOperation(
        id=str(uuid.uuid4()),
        issuer_identity_id=identity.id,
        attempted_at=datetime(2026, 8, 27, 12, 1, tzinfo=timezone.utc),
    )
    db_session.add(operation)
    db_session.flush()
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
        index_url=(
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{cik}26000001/index.json"
        ),
        source_url=(
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{cik}26000001/fixture.htm"
        ),
        submissions_source_url=f"https://data.sec.gov/submissions/CIK{cik}.json",
        discovery_payload_sha256="a" * 64,
    )
    db_session.add(filing)
    db_session.flush()
    index_content = b"{}"
    index_storage_key, index_sha256 = _store_content_immutable(
        storage_root, index_content
    )
    filing_artifact = SecFilingArtifact(
        filing_id=filing.id,
        sequence=0,
        filename="__accession_index__.json",
        source_url=filing.index_url,
        manifest_hash="d" * 64,
        state="retained",
        content_mime="application/json",
        sha256=index_sha256,
        byte_size=len(index_content),
        storage_key=index_storage_key,
        fetched_at=datetime(2026, 8, 27, 12, 2, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 2, tzinfo=timezone.utc),
    )
    db_session.add(filing_artifact)
    db_session.flush()
    primary_content = b"0123456789"
    primary_storage_key, primary_sha256 = _store_content_immutable(
        storage_root, primary_content
    )
    artifact = SecFilingArtifact(
        filing_id=filing.id,
        sequence=1,
        filename="fixture.htm",
        source_url=filing.source_url,
        manifest_hash="b" * 64,
        state="retained",
        content_mime="text/html",
        sha256=primary_sha256,
        byte_size=len(primary_content),
        storage_key=primary_storage_key,
        fetched_at=datetime(2026, 8, 27, 12, 2, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 2, tzinfo=timezone.utc),
    )
    db_session.add(artifact)
    db_session.commit()
    return stock, identity, filing, artifact, operation


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


def _add_current_accession_attempt_resolution(
    db_session,
    *,
    operation: SecFinancialIngestionOperation,
    filing: SecFinancialFiling,
    run: SecFinancialParseRun,
    artifacts: list[SecFilingArtifact],
    reused: bool = False,
) -> SecFinancialAccessionAttempt:
    index_artifact = db_session.scalar(
        select(SecFilingArtifact).where(
            SecFilingArtifact.filing_id == filing.id,
            SecFilingArtifact.source_url == filing.index_url,
        )
    )
    if index_artifact is not None and all(
        artifact.id != index_artifact.id for artifact in artifacts
    ):
        artifacts = [index_artifact, *artifacts]
    linked_artifact_ids = set(
        db_session.scalars(
            select(SecFinancialParseRunArtifact.artifact_id).where(
                SecFinancialParseRunArtifact.parse_run_id == run.id
            )
        ).all()
    )
    linked_has_legacy_submissions = db_session.scalar(
        select(
            func.count()
        )
        .select_from(SecFinancialParseRunArtifact)
        .join(
            SecFilingArtifact,
            SecFilingArtifact.id == SecFinancialParseRunArtifact.artifact_id,
        )
        .where(
            SecFinancialParseRunArtifact.parse_run_id == run.id,
            SecFilingArtifact.filename == "__submissions__.json",
        )
    ) > 0
    for artifact in artifacts:
        if artifact.id not in linked_artifact_ids:
            db_session.add(
                SecFinancialParseRunArtifact(
                    parse_run_id=run.id,
                    artifact_id=artifact.id,
                    known_at=run.known_at,
                )
            )
    db_session.flush()
    index_artifact = next(
        (
            artifact for artifact in artifacts
            if artifact.filename == "__accession_index__.json"
        ),
        None,
    )
    if index_artifact is None:
        index_sha256 = "a" * 64
    else:
        index_sha256 = index_artifact.sha256
    attempt = SecFinancialAccessionAttempt(
        operation_id=operation.id,
        filing_id=filing.id,
        accession_no=filing.accession_no,
        index_resource_key=filing.index_url,
        outcome=f"parse_{'reused_' if reused else ''}{run.status}",
        index_sha256=index_sha256,
        input_manifest_hash=(
            _artifact_input_hash(artifacts)
            if linked_has_legacy_submissions
            and all(item.filename != "__submissions__.json" for item in artifacts)
            else run.input_manifest_hash
        ),
        parse_run_id=run.id,
    )
    db_session.add(attempt)
    db_session.flush()
    for artifact in artifacts:
        db_session.add(
            SecFinancialAccessionAttemptArtifact(
                attempt_id=attempt.id,
                artifact_id=artifact.id,
            )
        )
    db_session.flush()
    db_session.add(
        SecFinancialAcquisitionResolution(
            operation_id=operation.id,
            resource_role="accession_terminal",
            resource_key=filing.accession_no,
            resolution_kind=f"parse_{run.status}",
            parse_run_id=run.id,
            accession_attempt_id=attempt.id,
            accession_no=filing.accession_no,
        )
    )
    db_session.flush()
    return attempt


def _seed_legacy_submission_coupled_lineage(
    db_session,
    tmp_path: Path,
    *,
    canonical_manifest_hash: bool = True,
    canonical_submission_metadata: bool = True,
    run_includes_submissions: bool = True,
    finalize_legacy: bool = False,
) -> Stock:
    stock = Stock(ticker="LEGACY", exchange="US", company_name="Legacy Fixture")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Legacy submissions-coupled fixture.",
    )
    operation = SecFinancialIngestionOperation(
        id=str(uuid.uuid4()),
        issuer_identity_id=identity.id,
        attempted_at=datetime(2026, 8, 27, 12, 1, tzinfo=timezone.utc),
    )
    db_session.add(operation)
    db_session.flush()
    filing = SecFinancialFiling(
        issuer_identity_id=identity.id,
        accession_no=ACCESSION,
        form_type="10-Q",
        is_amendment=False,
        filed_on=date(2026, 7, 31),
        report_date=date(2026, 6, 27),
        accepted_at=datetime(2026, 7, 31, 20, 5, 28, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 1, tzinfo=timezone.utc),
        primary_document="aapl-20260627.htm",
        primary_doc_description="10-Q",
        index_url=INDEX_URL,
        source_url=PRIMARY_URL,
        submissions_source_url=SUBMISSIONS_URL,
        discovery_payload_sha256=hashlib.sha256(_submissions_payload()).hexdigest(),
    )
    db_session.add(filing)
    db_session.flush()
    raw_legacy_items = json.loads(_index_payload())["directory"]["item"]
    legacy_manifest_material = {
        "retention_policy_version": "sec-financial-artifacts-v1",
        "submissions_sha256": hashlib.sha256(_submissions_payload()).hexdigest(),
        "index_sha256": hashlib.sha256(_index_payload()).hexdigest(),
        "items": [
            {
                "sequence": sequence,
                "name": item["name"],
                "type": item["type"],
                "size": item["size"],
                "description": item["description"],
            }
            for sequence, item in enumerate(raw_legacy_items, start=1)
        ],
    }
    legacy_manifest_hash = (
        hashlib.sha256(
            json.dumps(
                legacy_manifest_material,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if canonical_manifest_hash
        else "9" * 64
    )
    artifact_specs = [
        (-1, "__submissions__.json", _submissions_payload(), "application/json"),
        (0, "__accession_index__.json", _index_payload(), "application/json"),
        (1, "aapl-20260627.htm", INLINE_XBRL, "text/html"),
        (2, "aapl-20260627.xsd", SCHEMA_XBRL, "application/xml"),
    ]
    retained: list[SecFilingArtifact] = []
    for sequence, filename, content, content_mime in artifact_specs:
        storage_key, sha256 = _store_content_immutable(tmp_path, content)
        artifact = SecFilingArtifact(
            filing_id=filing.id,
            sequence=sequence,
            filename=filename,
            description=(
                (
                    "SEC submissions discovery payload"
                    if canonical_submission_metadata
                    else "untrusted extra artifact"
                )
                if sequence == -1
                else "SEC accession artifact index"
                if sequence == 0
                else "10-Q"
                if sequence == 1
                else "XBRL TAXONOMY EXTENSION SCHEMA"
            ),
            sec_type=(
                "SEC-DISCOVERY-MANIFEST"
                if sequence <= 0
                else "10-Q"
                if sequence == 1
                else "EX-101.SCH"
            ),
            declared_size=len(content),
            source_url=(
                None
                if sequence == -1
                else INDEX_URL
                if sequence == 0
                else PRIMARY_URL
                if sequence == 1
                else next(
                    url
                    for url in FakeEdgarClient().responses
                    if url.endswith(".xsd")
                )
            ),
            manifest_hash=legacy_manifest_hash,
            state="retained",
            content_mime=content_mime,
            sha256=sha256,
            byte_size=len(content),
            storage_key=storage_key,
            fetched_at=datetime(2026, 8, 27, 12, 2, tzinfo=timezone.utc),
            known_at=datetime(2026, 8, 27, 12, 2, tzinfo=timezone.utc),
        )
        db_session.add(artifact)
        retained.append(artifact)
    db_session.add(
        SecFilingArtifact(
            filing_id=filing.id,
            sequence=3,
            filename="logo.png",
            description="logo",
            sec_type="GRAPHIC",
            declared_size=10,
            source_url=(
                f"https://www.sec.gov/Archives/edgar/data/320193/{ACCESSION_RAW}/"
                "logo.png"
            ),
            manifest_hash=legacy_manifest_hash,
            state="manifest_only",
            reason_code="artifact_type_not_in_ft03_retention_scope",
            known_at=datetime(2026, 8, 27, 12, 2, tzinfo=timezone.utc),
        )
    )
    db_session.flush()
    submissions_content = _submissions_payload()
    submissions_sha = hashlib.sha256(submissions_content).hexdigest()
    submissions_key, _ = _store_content_immutable(tmp_path, submissions_content)
    snapshot = SecSubmissionSnapshot(
        issuer_identity_id=identity.id,
        operation_id=operation.id,
        source_url=SUBMISSIONS_URL,
        sha256=submissions_sha,
        byte_size=len(submissions_content),
        storage_key=submissions_key,
        fetched_at=datetime(2026, 8, 27, 12, 2, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 2, tzinfo=timezone.utc),
    )
    db_session.add(snapshot)
    db_session.flush()
    db_session.add(
        SecFinancialOperationSnapshot(
            operation_id=operation.id,
            snapshot_id=snapshot.id,
        )
    )
    run = SecFinancialParseRun(
        filing_id=filing.id,
        operation_id=operation.id,
        parser_name="valuepilot-inline-xbrl-lineage",
        parser_version="inline-xbrl-v1",
        input_manifest_hash=_artifact_input_hash(retained),
        status="succeeded",
        started_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        fact_count=1,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add_all(
        [
            SecFinancialParseRunArtifact(
                parse_run_id=run.id,
                artifact_id=artifact.id,
                known_at=run.known_at,
            )
            for artifact in retained
            if run_includes_submissions or artifact.filename != "__submissions__.json"
        ]
    )
    db_session.flush()
    primary = next(item for item in retained if item.filename == filing.primary_document)
    db_session.add(_raw_fact(run.id, primary.id))
    db_session.add(
        SecFinancialOperationResult(
            operation_id=operation.id,
            result_kind="parse_run",
            parse_run_id=run.id,
        )
    )
    _add_current_accession_attempt_resolution(
        db_session,
        operation=operation,
        filing=filing,
        run=run,
        artifacts=[
            artifact
            for artifact in retained
            if artifact.filename != "__submissions__.json"
        ],
    )
    db_session.commit()
    if finalize_legacy:
        finalize_sec_financial_ingestion_operation(
            db_session, operation_id=operation.id
        )
        db_session.commit()
    return stock


def test_database_rejects_zero_fact_success_and_fact_count_mismatch(
    db_session, tmp_path: Path
) -> None:
    _, _, filing, artifact, operation = _database_lineage_fixture(
        db_session, tmp_path, ticker="COUNT", cik="0000000021"
    )
    zero = SecFinancialParseRun(
        filing_id=filing.id,
        operation_id=operation.id,
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
        operation_id=operation.id,
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


def test_database_overwrites_parse_link_transaction_metadata(
    db_session, tmp_path: Path
) -> None:
    _, _, filing, artifact, operation = _database_lineage_fixture(
        db_session, tmp_path, ticker="LATE", cik="0000000022"
    )
    failed_run = SecFinancialParseRun(
        filing_id=filing.id,
        operation_id=operation.id,
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

    caller_supplied_created_at = failed_run.created_at + timedelta(seconds=1)
    link = SecFinancialParseRunArtifact(
        parse_run_id=failed_run.id,
        artifact_id=artifact.id,
        known_at=failed_run.known_at,
        created_at=caller_supplied_created_at,
        created_txid=failed_run.created_txid - 1,
    )
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)

    assert link.created_at >= failed_run.created_at
    assert link.created_at != caller_supplied_created_at
    assert link.created_txid == failed_run.created_txid


def test_database_rejects_filing_bound_to_needs_review_identity(
    db_session, tmp_path: Path
) -> None:
    stock, reviewed, _, _, _ = _database_lineage_fixture(
        db_session, tmp_path, ticker="REVIEW", cik="0000000023"
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
        filing_selection_as_of=datetime(2010, 1, 1, tzinfo=timezone.utc),
    )

    assert len(client.calls) == 3
    assert result.failures == ("history_scan_limit_exceeded",)


def test_historical_discovery_reports_unsafe_reference() -> None:
    client = UnsafeHistoricalReferenceClient()

    result = _discover(
        client,
        CIK,
        max_filings=1,
        filing_selection_as_of=datetime(2010, 1, 1, tzinfo=timezone.utc),
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
        filing_selection_as_of=datetime(2010, 1, 1, tzinfo=timezone.utc),
    )

    assert client.calls == [SUBMISSIONS_URL]
    assert result.filings == ()
    assert result.failures == (
        f"unsafe_historical_submission_reference:{failure_detail}",
    )


def test_exact_failed_parse_replay_remains_a_failure(
    committed_db_session, tmp_path: Path
) -> None:
    db_session = committed_db_session
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
    _commit_and_finalize(db_session, first)
    failed_replay = select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
        storage_root=tmp_path,
    )
    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    _commit_and_finalize(db_session, second)

    assert first.failures == (f"{ACCESSION}:no_inline_xbrl_facts",)
    assert second.failures == first.failures
    assert [(item.accession_no, item.error_code) for item in failed_replay] == [
        (ACCESSION, "no_inline_xbrl_facts")
    ]


def test_ingested_lineage_is_pending_until_separate_finalize_and_recovers_idempotently(
    committed_db_session, tmp_path: Path
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="PENDING", exchange="US", company_name="Pending Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Pending visibility fixture.",
    )
    db_session.commit()

    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=FakeEdgarClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()
    future = datetime.now(timezone.utc) + timedelta(seconds=5)
    assert has_pending_sec_financial_lineage(db_session, stock_id=stock.id)
    assert select_sec_financial_evidence_as_of(
        db_session, stock_id=stock.id, cutoff=future, storage_root=tmp_path
    ) == []
    assert earliest_replayable_sec_financial_evidence_at(
        db_session, stock_id=stock.id, storage_root=tmp_path
    ) is None

    recovered = finalize_pending_sec_financial_ingestion_operations(
        db_session, stock_id=stock.id
    )
    assert len(recovered) == 1
    assert recovered[0][0] == report.operation_id
    available_at = recovered[0][1]
    db_session.commit()
    second_available_at = finalize_sec_financial_ingestion_operation(
        db_session, operation_id=report.operation_id
    )
    db_session.commit()

    assert second_available_at == available_at
    assert finalize_pending_sec_financial_ingestion_operations(
        db_session, stock_id=stock.id
    ) == ()
    assert not has_pending_sec_financial_lineage(db_session, stock_id=stock.id)
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialLineageAvailability)
    ) == 1
    assert select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=available_at - timedelta(microseconds=1),
        storage_root=tmp_path,
    ) == []
    assert select_sec_financial_evidence_as_of(
        db_session, stock_id=stock.id, cutoff=available_at, storage_root=tmp_path
    )


def test_empty_fabricated_operation_cannot_finalize(committed_db_session) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="EMPTYOP", exchange="US", company_name="Empty Operation")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Empty operation fixture.",
    )
    db_session.commit()
    operation_id = str(uuid.uuid4())
    db_session.add(
        SecFinancialIngestionOperation(
            id=operation_id,
            issuer_identity_id=identity.id,
            attempted_at=datetime(2026, 8, 27, 12, 1, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    with pytest.raises(
        SecFinancialIngestionError,
        match="retained submissions snapshot or no-bytes resource anchor",
    ):
        finalize_sec_financial_ingestion_operation(
            db_session, operation_id=operation_id
        )
    db_session.rollback()


def test_no_bytes_anchor_cannot_make_no_eligible_operation_finalizable(
    committed_db_session,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="ANCHOREMPTY", exchange="US", company_name="Anchor Empty")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="No-bytes anchor terminal-shape fixture.",
    )
    db_session.commit()
    operation = SecFinancialIngestionOperation(
        id=str(uuid.uuid4()),
        issuer_identity_id=identity.id,
        attempted_at=datetime(2026, 8, 27, 12, 1, tzinfo=timezone.utc),
    )
    db_session.add(operation)
    db_session.flush()
    db_session.add(
        SecFinancialResourceAnchor(
            operation_id=operation.id,
            resource_role="main_submissions",
            resource_key=SUBMISSIONS_URL,
        )
    )
    db_session.commit()
    db_session.add(
        SecFinancialOperationResult(
            operation_id=operation.id,
            result_kind="no_eligible_filings",
        )
    )
    with pytest.raises(
        DBAPIError,
        match="no-filings result cannot use no-bytes resource anchor",
    ):
        db_session.commit()
    db_session.rollback()


def test_valid_no_eligible_filings_finalizes_and_seals_later_writes(
    committed_db_session, tmp_path: Path
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="NOELIG", exchange="US", company_name="No Eligible Filing")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="No eligible filing fixture.",
    )
    db_session.commit()
    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=EmptyMainSubmissionsClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()
    available_at = finalize_sec_financial_ingestion_operation(
        db_session, operation_id=report.operation_id
    )
    db_session.commit()
    operation = db_session.get(SecFinancialIngestionOperation, report.operation_id)
    availability = db_session.get(
        SecFinancialLineageAvailability, report.operation_id
    )
    assert report.filings_discovered == 0
    assert report.failures == ()
    assert availability.available_at == available_at
    assert availability.finalized_txid != operation.created_txid

    db_session.add(
        SecSubmissionSnapshot(
            issuer_identity_id=identity.id,
            operation_id=report.operation_id,
            source_url=SUBMISSIONS_URL,
            sha256="9" * 64,
            byte_size=2,
            storage_key="financial/99/" + "9" * 64,
            fetched_at=datetime(2026, 8, 27, 12, 6, tzinfo=timezone.utc),
            known_at=datetime(2026, 8, 27, 12, 6, tzinfo=timezone.utc),
        )
    )
    with pytest.raises(DBAPIError, match="matching unsealed SEC operation"):
        db_session.commit()
    db_session.rollback()


def test_acceptance_audit_rejects_reported_zero_for_operation_owned_snapshot(
    committed_db_session, tmp_path: Path
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="AUDIT", exchange="US", company_name="Audit Fixture")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Acceptance audit operation-ownership fixture.",
    )
    db_session.commit()

    first = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=EmptyMainSubmissionsClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()
    first_available = finalize_sec_financial_ingestion_operation(
        db_session, operation_id=first.operation_id
    )
    db_session.commit()
    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=CorrectedEmptyMainSubmissionsClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.commit()
    second_available = finalize_sec_financial_ingestion_operation(
        db_session, operation_id=second.operation_id
    )
    db_session.commit()

    def payload(report, available_at, acceptance_pass, snapshot_count):
        operation = db_session.get(
            SecFinancialIngestionOperation, report.operation_id
        )
        return {
            "schema_version": 2,
            "acceptance_pass": acceptance_pass,
            "run_id": "step-d-audit-test",
            "case_id": "audit-primary",
            "stock_id": stock.id,
            "cik": CIK,
            "filing_selection_as_of": "2026-08-26T23:59:59+00:00",
            "operation_id": report.operation_id,
            "operation_attempted_at": operation.attempted_at.isoformat(),
            "evidence_finalized_at": available_at.isoformat(),
            "evidence_available_at": available_at.isoformat(),
            "expected_completed_fiscal_years": [],
            "selected_filings": [],
            "selected_forms": [],
            "typed_gaps": [],
            "typed_failures": [],
            "filings_discovered": 0,
            "filings_created": 0,
            "submission_snapshots_created": snapshot_count,
            "artifacts_created": 0,
            "parse_runs_created": 0,
            "raw_facts_created": 0,
            "metric_facts_published": 0,
            "acquisition_operations": [
                {
                    "operation_id": report.operation_id,
                    "attempted_at": operation.attempted_at.isoformat(),
                    "finalized_at": available_at.isoformat(),
                    "available_at": available_at.isoformat(),
                    "accessions": [],
                    "filings_created": 0,
                    "submission_snapshots_created": snapshot_count,
                    "artifacts_created": 0,
                    "parse_runs_created": 0,
                    "raw_facts_created": 0,
                }
            ],
            "publication_run_id": "00000000-0000-4000-8000-000000000001",
            "publication_replayed": acceptance_pass == 2,
            "publication_requested_cutoff": "2026-09-01T12:00:00+00:00",
            "publication_attempted_at": "2026-09-01T12:00:00+00:00",
            "publication_finalized_at": "2026-09-01T12:00:01+00:00",
            "publication_available_at": "2026-09-01T12:00:01+00:00",
            "publication_run_source_ids": [1],
            "publication_source_parse_run_ids": [1],
            "publication_source_accessions": ["fixture-accession"],
            "publication_decision_ids": [1],
            "mapping_version_id": "sec-us-gaap-v1",
            "method_policy_version_id": "sec-method-gate-v1",
            "amendment_policy_id": "latest-known-v1",
            "metric_outcomes": {
                "metric_denominator": 21,
                "issuer_year_metric_denominator": 0,
                "published_count": 0,
                "typed_gap_count": 0,
                "missing_count": 0,
                "coverage_count": 0,
                "outcomes": [],
            },
            "lineage_counts": {},
            "persistent_delta": {"idempotent": acceptance_pass == 2},
        }

    pass_one = payload(first, first_available, 1, 1)
    pass_two = payload(second, second_available, 2, 0)
    with pytest.raises(ValueError, match="created counters.*pass 2"):
        _operation_database_audit(
            db_session,
            report=pass_two,
            acceptance_pass=2,
            expected_run_id="step-d-audit-test",
            case_id="audit-primary",
            identity=identity,
            stock=stock,
        )

    correct = _operation_database_audit(
        db_session,
        report=pass_one,
        acceptance_pass=1,
        expected_run_id="step-d-audit-test",
        case_id="audit-primary",
        identity=identity,
        stock=stock,
    )
    assert correct["operation_id"] == first.operation_id

    for field, invalid_value, message in (
        ("cik", "0000000001", "issuer identity mismatch"),
        ("stock_id", stock.id + 1, "issuer identity mismatch"),
        ("operation_id", second.operation_id, "operation attempt mismatch"),
    ):
        malformed = {**pass_one, field: invalid_value}
        if field == "operation_id":
            malformed["acquisition_operations"] = [
                {
                    **pass_one["acquisition_operations"][0],
                    "operation_id": invalid_value,
                }
            ]
        with pytest.raises(ValueError, match=message):
            _operation_database_audit(
                db_session,
                report=malformed,
                acceptance_pass=1,
                expected_run_id="step-d-audit-test",
                case_id="audit-primary",
                identity=identity,
                stock=stock,
            )


def test_finalize_serializes_against_concurrent_operation_write(
    committed_db_session, tmp_path: Path
) -> None:
    session_a = committed_db_session
    stock = Stock(ticker="SEALRACE", exchange="US", company_name="Seal Race")
    session_a.add(stock)
    session_a.flush()
    identity = register_reviewed_sec_identity(
        session_a,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Seal race fixture.",
    )
    session_a.commit()
    report = ingest_latest_financial_filings(
        session_a,
        stock_id=stock.id,
        client=EmptyMainSubmissionsClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    session_a.commit()
    identity_id = identity.id
    finalize_sec_financial_ingestion_operation(
        session_a, operation_id=report.operation_id
    )

    writer_done = threading.Event()
    writer_errors: list[Exception] = []

    def write_after_finalize_started() -> None:
        try:
            with Session(bind=session_a.get_bind()) as session_b:
                session_b.add(
                    SecSubmissionSnapshot(
                        issuer_identity_id=identity_id,
                        operation_id=report.operation_id,
                        source_url=SUBMISSIONS_URL,
                        sha256="8" * 64,
                        byte_size=2,
                        storage_key="financial/88/" + "8" * 64,
                        fetched_at=datetime(2026, 8, 27, 12, 6, tzinfo=timezone.utc),
                        known_at=datetime(2026, 8, 27, 12, 6, tzinfo=timezone.utc),
                    )
                )
                session_b.commit()
        except Exception as exc:
            writer_errors.append(exc)
        finally:
            writer_done.set()

    thread = threading.Thread(target=write_after_finalize_started)
    thread.start()
    assert not writer_done.wait(timeout=1.0), (
        "operation writer bypassed finalizer row lock"
    )
    session_a.commit()
    assert writer_done.wait(timeout=10.0)
    thread.join(timeout=10.0)
    assert len(writer_errors) == 1
    assert "matching unsealed SEC operation" in str(writer_errors[0])


@pytest.mark.parametrize(
    ("client", "expected_code", "expected_snapshot_count"),
    [
        (
            MalformedMainSubmissionsClient(),
            "invalid_main_submissions_payload",
            1,
        ),
        (
            MismatchedMainSubmissionsClient(),
            "main_submissions_cik_mismatch",
            1,
        ),
        (
            MalformedHistoricalSubmissionsClient(),
            "invalid_historical_submissions_payload",
            2,
        ),
    ],
)
def test_malformed_fetched_submissions_are_retained_and_audited_before_failure(
    committed_db_session,
    tmp_path: Path,
    client,
    expected_code: str,
    expected_snapshot_count: int,
) -> None:
    db_session = committed_db_session
    stock = Stock(
        ticker="BADJSON" + str(expected_snapshot_count),
        exchange="US",
        company_name="Malformed Submissions Fixture",
    )
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Malformed submissions fixture.",
    )
    db_session.commit()

    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()
    assert report.failures[0] == expected_code
    assert db_session.scalar(select(func.count()).select_from(SecFinancialFiling)) == 0
    assert db_session.scalar(select(func.count()).select_from(SecFinancialParseRun)) == 0
    assert db_session.scalar(select(func.count()).select_from(SecRawXbrlFact)) == 0
    snapshots = db_session.scalars(
        select(SecSubmissionSnapshot).order_by(SecSubmissionSnapshot.source_url)
    ).all()
    assert len(snapshots) == expected_snapshot_count
    for snapshot in snapshots:
        retained = tmp_path / snapshot.storage_key
        assert retained.is_file()
        assert hashlib.sha256(retained.read_bytes()).hexdigest() == snapshot.sha256
        assert snapshot.source_url.startswith("https://data.sec.gov/submissions/CIK")
    audit = db_session.scalar(select(SecFinancialAcquisitionFailure))
    assert audit is not None
    assert audit.error_code == expected_code
    assert audit.operation_id == report.operation_id
    assert select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=5),
        storage_root=tmp_path,
    ) == []

    finalize_sec_financial_ingestion_operation(
        db_session, operation_id=report.operation_id
    )
    db_session.commit()
    failures = select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=5),
        storage_root=tmp_path,
    )
    assert [(item.accession_no, item.error_code) for item in failures] == [
        ("submissions", expected_code)
    ]
    assert db_session.scalar(select(func.count()).select_from(MetricFact)) == 0

    rerun = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.commit()
    assert rerun.operation_id == report.operation_id
    assert rerun.failures == report.failures
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialIngestionOperation)
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialAcquisitionFailure)
    ) == 1
    assert db_session.scalar(select(func.count()).select_from(SecSubmissionSnapshot)) == (
        expected_snapshot_count
    )


def test_parser_v2_structured_evidence_blocks_destructive_downgrade(
    committed_db_session, tmp_path: Path
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="V2DOWN", exchange="US", company_name="V2 Downgrade")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 1, 1),
        known_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        review_reason="Parser v2 downgrade fixture.",
    )
    db_session.commit()
    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=StatementAuthorityClient(),
        storage_root=tmp_path,
        max_filings=1,
        parser_version="xbrl-lineage-v2",
        now=datetime(2026, 8, 27, 1, tzinfo=timezone.utc),
    )
    assert report.raw_facts_created > 0
    db_session.commit()
    before = db_session.execute(
        text(
            "SELECT unit_numerator_json FROM sec_raw_xbrl_facts "
            "WHERE unit_numerator_json IS NOT NULL ORDER BY id LIMIT 1"
        )
    ).scalar_one()
    backend_dir = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["alembic", "downgrade", "20260830140000"],
        cwd=backend_dir,
        env={
            **os.environ,
            "DATABASE_URL": db_session.bind.url.render_as_string(
                hide_password=False
            ),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    downgrade_output = result.stdout + result.stderr
    assert (
        "cannot downgrade with retained SEC parser-v2 structured QName evidence" in downgrade_output
        or "downgrade refused: retained SEC statement authority exists" in downgrade_output
    )
    db_session.expire_all()
    after = db_session.execute(
        text(
            "SELECT unit_numerator_json FROM sec_raw_xbrl_facts "
            "WHERE unit_numerator_json IS NOT NULL ORDER BY id LIMIT 1"
        )
    ).scalar_one()
    assert after == before


def test_history_continuation_is_random_persisted_and_uses_retained_main_snapshot(
    committed_db_session, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.services.sec_financial_ingestion.MAX_HISTORICAL_SUBMISSION_FILES", 1
    )
    db_session = committed_db_session
    stock = Stock(ticker="CURSOR", exchange="US", company_name="Cursor Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 1, 1),
        known_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        review_reason="Continuation fixture.",
    )
    db_session.commit()

    def arrays(year: int, sequence: int) -> dict[str, list[str]]:
        return {
            "accessionNumber": [f"{CIK}-{year % 100:02d}-{sequence:06d}"],
            "filingDate": [f"{year + 1}-02-15"],
            "reportDate": [f"{year}-12-31"],
            "acceptanceDateTime": [f"{year + 1}-02-15T12:00:00Z"],
            "form": ["10-K"],
            "primaryDocument": [f"filing-{year}.htm"],
            "primaryDocDescription": ["10-K"],
        }

    main = json.dumps(
        {
            "cik": str(int(CIK)),
            "name": "Cursor Fixture",
            "fiscalYearEnd": "1231",
            "filings": {
                "recent": arrays(2025, 1),
                "files": [
                    {"name": f"CIK{CIK}-submissions-000.json"},
                    {"name": f"CIK{CIK}-submissions-001.json"},
                ],
            },
        }
    ).encode()
    main_url = f"https://data.sec.gov/submissions/CIK{CIK}.json"
    history_urls = [
        f"https://data.sec.gov/submissions/CIK{CIK}-submissions-{index:03d}.json"
        for index in range(2)
    ]

    class CursorClient:
        def __init__(self, main_bytes: bytes) -> None:
            self.calls: list[str] = []
            self.responses = {
                main_url: main_bytes,
                history_urls[0]: json.dumps(arrays(2024, 2)).encode(),
                history_urls[1]: json.dumps(arrays(2023, 3)).encode(),
            }

        def get(self, url: str) -> bytes:
            self.calls.append(url)
            return self.responses[url]

        get_revalidated = get

    target = FinancialHistoryTarget(
        filing_regime="us_10k_10q",
        fiscal_year_end_mmdd="1231",
        available_start_on=date(2023, 1, 1),
        completed_fiscal_year_cap=3,
        filing_selection_as_of=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )
    first_client = CursorClient(main)
    first = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=first_client,
        storage_root=tmp_path,
        max_filings=3,
        filing_selection_as_of=target.filing_selection_as_of,
        history_target=target,
    )
    db_session.commit()
    assert first.next_history_cursor is not None
    uuid.UUID(first.next_history_cursor)
    authority = db_session.get(
        SecFinancialHistoryContinuation, first.next_history_cursor
    )
    assert authority is not None and authority.next_index == 1
    attack_operation_id = str(uuid.uuid4())
    db_session.add(
        SecFinancialIngestionOperation(
            id=attack_operation_id,
            issuer_identity_id=authority.issuer_identity_id,
            attempted_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    def insert_attack_child(
        operation_id: str, next_index: int, *, executor=db_session, child_id=None
    ) -> str:
        child_id = child_id or str(uuid.uuid4())
        executor.execute(
            text(
                "INSERT INTO sec_financial_history_continuations "
                "(id, issuer_identity_id, main_snapshot_id, source_operation_id, parent_id, "
                "main_sha256, manifest_identity, validated_references_json, "
                "filing_selection_as_of, history_target_json, next_index) VALUES "
                "(:id, :identity_id, :snapshot_id, :operation_id, :parent_id, :sha, "
                ":manifest, CAST(:refs AS jsonb), :cutoff, CAST(:target AS jsonb), :next_index)"
            ),
            {
                "id": child_id,
                "identity_id": authority.issuer_identity_id,
                "snapshot_id": authority.main_snapshot_id,
                "operation_id": operation_id,
                "parent_id": authority.id,
                "sha": authority.main_sha256,
                "manifest": authority.manifest_identity,
                "refs": json.dumps(authority.validated_references_json),
                "cutoff": authority.filing_selection_as_of,
                "target": json.dumps(authority.history_target_json),
                "next_index": next_index,
            },
        )
        return child_id

    nested = db_session.begin_nested()
    with pytest.raises(DBAPIError, match="consumption claim"):
        insert_attack_child(attack_operation_id, 2)
        db_session.flush()
    nested.rollback()

    bad_claim_operation_id = str(uuid.uuid4())
    db_session.add(
        SecFinancialIngestionOperation(
            id=bad_claim_operation_id,
            issuer_identity_id=authority.issuer_identity_id,
            attempted_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()
    nested = db_session.begin_nested()
    with pytest.raises(DBAPIError, match="consumption claim authority"):
        db_session.execute(text(
            "INSERT INTO sec_financial_history_consumption_claims "
            "(operation_id, parent_id, main_snapshot_id, manifest_identity, start_index, "
            "end_index, attempted_references_json, terminal_outcomes_json) VALUES "
            "(:operation_id, :parent_id, :snapshot_id, :manifest, 0, 2, "
            "'[\"forged-a\",\"forged-b\"]'::jsonb, '[{},{}]'::jsonb)"
        ), {
            "operation_id": bad_claim_operation_id,
            "parent_id": authority.id,
            "snapshot_id": authority.main_snapshot_id,
            "manifest": authority.manifest_identity,
        })
    nested.rollback()
    db_session.rollback()
    finalize_sec_financial_ingestion_operation(
        db_session, operation_id=first.operation_id
    )
    db_session.commit()
    nested = db_session.begin_nested()
    with pytest.raises(DBAPIError, match="invalid SEC history continuation authority"):
        insert_attack_child(first.operation_id, 2)
        db_session.flush()
    nested.rollback()

    mismatch_operation_id = str(uuid.uuid4())
    db_session.add(
        SecFinancialIngestionOperation(
            id=mismatch_operation_id,
            issuer_identity_id=authority.issuer_identity_id,
            attempted_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()
    nested = db_session.begin_nested()
    with pytest.raises(DBAPIError, match="consumption claim authority"):
        db_session.execute(text(
            "INSERT INTO sec_financial_history_consumption_claims "
            "(operation_id, parent_id, main_snapshot_id, manifest_identity, start_index, "
            "end_index, attempted_references_json, terminal_outcomes_json) VALUES "
            "(:operation_id, :parent_id, :snapshot_id, :manifest, 0, 1, "
            "CAST(:refs AS jsonb), '[{}]'::jsonb)"
        ), {
            "operation_id": mismatch_operation_id,
            "parent_id": authority.id,
            "snapshot_id": authority.main_snapshot_id,
            "manifest": authority.manifest_identity,
            "refs": json.dumps(authority.validated_references_json[:1]),
        })
    nested.rollback()
    db_session.rollback()

    second_client = CursorClient(b"changed current SEC main must not be read")
    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=second_client,
        storage_root=tmp_path,
        max_filings=3,
        filing_selection_as_of=target.filing_selection_as_of,
        history_target=target,
        history_cursor=first.next_history_cursor,
    )
    db_session.commit()
    assert main_url not in second_client.calls
    assert history_urls[1] in second_client.calls
    assert second.next_history_cursor is None

    retry_client = CursorClient(b"retry must still use retained main")
    retry = ingest_latest_financial_filings(
        db_session, stock_id=stock.id, client=retry_client, storage_root=tmp_path,
        max_filings=3, filing_selection_as_of=target.filing_selection_as_of,
        history_target=target, history_cursor=first.next_history_cursor,
    )
    db_session.commit()
    assert retry.next_history_cursor is None
    assert main_url not in retry_client.calls

    nested = db_session.begin_nested()
    with pytest.raises(DBAPIError, match="continuation advance"):
        insert_attack_child(second.operation_id, 1)
    nested.rollback()
    db_session.commit()
    engine = db_session.get_bind()
    connection_a = engine.connect()
    transaction_a = connection_a.begin()
    winner_id = str(uuid.uuid4())
    insert_attack_child(
        second.operation_id, 2, executor=connection_a, child_id=winner_id
    )
    contender_result: list[str] = []

    def insert_contender() -> None:
        connection_b = engine.connect()
        transaction_b = connection_b.begin()
        try:
            insert_attack_child(second.operation_id, 2, executor=connection_b)
            transaction_b.commit()
            contender_result.append("committed")
        except DBAPIError:
            transaction_b.rollback()
            contender_result.append("rejected")
        finally:
            connection_b.close()

    thread = threading.Thread(target=insert_contender, daemon=True)
    thread.start()
    thread.join(timeout=0.5)
    assert thread.is_alive(), "second child did not wait on the parent uniqueness slot"
    transaction_a.commit()
    connection_a.close()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert contender_result == ["rejected"]
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialHistoryContinuation).where(
            SecFinancialHistoryContinuation.parent_id == authority.id
        )
    ) == 1
    assert db_session.get(SecFinancialHistoryContinuation, winner_id).id == winner_id

    invalid = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=second_client,
        storage_root=tmp_path,
        max_filings=3,
        filing_selection_as_of=target.filing_selection_as_of,
        history_target=target,
        history_cursor=str(uuid.uuid4()),
    )
    db_session.commit()
    assert invalid.failures == ("history_cursor_mismatch",)
    invalid_result = db_session.get(SecFinancialOperationResult, invalid.operation_id)
    assert invalid_result is not None
    assert invalid_result.result_kind == "history_continuation_failure"
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialResourceAnchor).where(
            SecFinancialResourceAnchor.operation_id == invalid.operation_id
        )
    ) == 0
    db_session.commit()
    finalize_sec_financial_ingestion_operation(
        db_session, operation_id=invalid.operation_id
    )

    guarded_operation_id = str(uuid.uuid4())
    foreign_operation_id = str(uuid.uuid4())
    db_session.add_all([
        SecFinancialIngestionOperation(id=guarded_operation_id, issuer_identity_id=authority.issuer_identity_id, attempted_at=datetime.now(timezone.utc)),
        SecFinancialIngestionOperation(id=foreign_operation_id, issuer_identity_id=authority.issuer_identity_id, attempted_at=datetime.now(timezone.utc)),
    ])
    db_session.flush()
    guarded_failure = db_session.execute(text(
        "INSERT INTO sec_financial_history_continuation_failures "
        "(operation_id, issuer_identity_id, cursor_id, reason_code, main_snapshot_id, request_contract_json, created_at, created_txid) "
        "VALUES (:operation_id, :identity_id, :cursor_id, 'invalid_history_cursor', NULL, '{}'::jsonb, "
        "'2000-01-01T00:00:00Z', 1) RETURNING id, created_at, created_txid"
    ), {"operation_id": guarded_operation_id, "identity_id": authority.issuer_identity_id, "cursor_id": str(uuid.uuid4())}).one()
    assert guarded_failure.created_at.year != 2000
    assert guarded_failure.created_txid == db_session.scalar(text("SELECT txid_current()"))
    nested = db_session.begin_nested()
    with pytest.raises(DBAPIError, match="reciprocal history continuation failure"):
        db_session.execute(text(
            "INSERT INTO sec_financial_operation_results "
            "(operation_id, result_kind, history_continuation_failure_id) "
            "VALUES (:operation_id, 'history_continuation_failure', :failure_id)"
        ), {"operation_id": foreign_operation_id, "failure_id": guarded_failure.id})
    nested.rollback()
    nested = db_session.begin_nested()
    with pytest.raises(DBAPIError):
        db_session.execute(text(
            "INSERT INTO sec_financial_operation_results "
            "(operation_id, result_kind, history_continuation_failure_id) "
            "VALUES (:operation_id, 'history_continuation_failure', 9223372036854775807)"
        ), {"operation_id": guarded_operation_id})
    nested.rollback()
    db_session.rollback()

def test_exact_main_submissions_validation_resolves_prior_failure(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="MAINRETRY", exchange="US", company_name="Main Retry")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Main submissions retry fixture.",
    )
    db_session.commit()
    client = ToggleMainPayloadClient()
    failed = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    failed_available_at = _commit_and_finalize(db_session, failed)
    assert [item.error_code for item in select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=failed_available_at + timedelta(microseconds=1),
        storage_root=tmp_path,
    )] == ["invalid_main_submissions_payload"]

    client.malformed = False
    recovered = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    recovered_available_at = _commit_and_finalize(db_session, recovered)

    assert recovered.failures == ()
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialAcquisitionResolution).where(
            SecFinancialAcquisitionResolution.operation_id
            == recovered.operation_id,
            SecFinancialAcquisitionResolution.resource_role
            == "main_submissions",
            SecFinancialAcquisitionResolution.resource_key == SUBMISSIONS_URL,
        )
    ) == 1
    assert select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=recovered_available_at + timedelta(seconds=1),
        storage_root=tmp_path,
    ) == []


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        pytest.param(503, "sec_temporarily_unavailable", id="503"),
        pytest.param(429, "sec_temporarily_unavailable", id="limit"),
        pytest.param(None, "rate_guard_unavailable_or_blocked", id="timeout"),
    ],
)
def test_initial_main_outage_is_durable_pending_idempotent_and_later_resolved(
    committed_db_session,
    tmp_path: Path,
    status_code: int | None,
    expected_code: str,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="MAIN503", exchange="US", company_name="Main Outage")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Initial main-resource outage fixture.",
    )
    db_session.commit()
    client = ToggleInitialMainOutageClient(status_code)

    failed = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert failed.failures == (f"main_submissions:{expected_code}",)
    assert failed.filings_discovered == 0
    assert failed.filings_created == 0
    assert failed.artifacts_created == 0
    assert failed.parse_runs_created == 0
    assert failed.raw_facts_created == 0
    assert db_session.scalar(select(func.count()).select_from(SecSubmissionSnapshot)) == 0
    assert db_session.scalar(select(func.count()).select_from(SecFinancialFiling)) == 0
    assert db_session.scalar(select(func.count()).select_from(SecFilingArtifact)) == 0
    assert db_session.scalar(select(func.count()).select_from(SecFinancialParseRun)) == 0
    assert db_session.scalar(select(func.count()).select_from(SecRawXbrlFact)) == 0
    assert db_session.scalar(select(func.count()).select_from(MetricFact)) == 0
    anchor = db_session.execute(
        text(
            "SELECT operation_id, resource_role, resource_key "
            "FROM sec_financial_resource_anchors"
        )
    ).one()
    assert anchor == (failed.operation_id, "main_submissions", SUBMISSIONS_URL)
    failure = db_session.scalar(select(SecFinancialAcquisitionFailure))
    assert failure.operation_id == failed.operation_id
    assert failure.submission_snapshot_id is None
    assert failure.resource_anchor_id is not None
    assert failure.stage == "submissions_fetch"
    assert failure.error_code == expected_code
    terminal = db_session.get(SecFinancialOperationResult, failed.operation_id)
    assert terminal.result_kind == "acquisition_failure"
    assert terminal.acquisition_failure_id == failure.id
    future = datetime.now(timezone.utc) + timedelta(seconds=5)
    assert select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=future,
        storage_root=tmp_path,
    ) == []
    assert earliest_replayable_sec_financial_evidence_at(
        db_session, stock_id=stock.id, storage_root=tmp_path
    ) is None

    repeated_pending = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 6, tzinfo=timezone.utc),
    )
    db_session.commit()
    assert repeated_pending.operation_id == failed.operation_id
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialIngestionOperation)
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialAcquisitionFailure)
    ) == 1

    recovered_pending = finalize_pending_sec_financial_ingestion_operations(
        db_session, stock_id=stock.id
    )
    assert len(recovered_pending) == 1
    assert recovered_pending[0][0] == failed.operation_id
    failed_available_at = recovered_pending[0][1]
    db_session.commit()
    assert select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=failed_available_at - timedelta(microseconds=1),
        storage_root=tmp_path,
    ) == []
    assert [item.error_code for item in select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=failed_available_at,
        storage_root=tmp_path,
    )] == [expected_code]

    repeated_finalized = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 7, tzinfo=timezone.utc),
    )
    db_session.commit()
    assert repeated_finalized.operation_id == failed.operation_id
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialIngestionOperation)
    ) == 1

    client.unavailable = False
    succeeded = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    succeeded_available_at = _commit_and_finalize(db_session, succeeded)
    assert succeeded.operation_id != failed.operation_id
    assert succeeded.failures == ()
    assert succeeded.parse_runs_created == 1
    assert [item.error_code for item in select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=succeeded_available_at - timedelta(microseconds=1),
        storage_root=tmp_path,
    )] == [expected_code]
    assert select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=succeeded_available_at,
        storage_root=tmp_path,
    ) == []
    assert earliest_replayable_sec_financial_evidence_at(
        db_session, stock_id=stock.id, storage_root=tmp_path
    ) is not None


def test_index_outage_is_terminal_finalizable_and_successful_retry_supersedes_failure(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="INDEX503", exchange="US", company_name="Index Outage")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Index outage fixture.",
    )
    db_session.commit()
    client = ToggleIndexOutageClient()

    failed = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()
    failed_available_at = finalize_sec_financial_ingestion_operation(
        db_session, operation_id=failed.operation_id
    )
    db_session.commit()
    assert failed.failures == (f"{ACCESSION}:manifest:sec_temporarily_unavailable",)
    failure = db_session.scalar(select(SecFinancialAcquisitionFailure))
    terminal = db_session.get(SecFinancialOperationResult, failed.operation_id)
    assert failure.stage == "accession_index_fetch"
    assert failure.error_code == "sec_temporarily_unavailable"
    assert failure.accession_no == ACCESSION
    assert failure.resource_role == "accession_index"
    assert failure.resource_key == INDEX_URL
    assert terminal.result_kind == "acquisition_failure"
    assert terminal.acquisition_failure_id == failure.id
    assert [item.error_code for item in select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=failed_available_at + timedelta(seconds=1),
        storage_root=tmp_path,
    )] == ["sec_temporarily_unavailable"]

    client.unavailable = False
    recovered = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    recovered_available_at = _commit_and_finalize(db_session, recovered)
    assert recovered.failures == ()
    assert recovered.parse_runs_created == 1
    resolution = db_session.scalar(
        select(SecFinancialAcquisitionResolution).where(
            SecFinancialAcquisitionResolution.operation_id
            == recovered.operation_id,
            SecFinancialAcquisitionResolution.resource_role
            == "accession_terminal",
        )
    )
    assert resolution.resource_key == ACCESSION
    assert resolution.accession_no == ACCESSION
    assert resolution.resolution_kind == "parse_succeeded"
    assert select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=recovered_available_at + timedelta(seconds=1),
        storage_root=tmp_path,
    ) == []


def test_unrelated_terminal_operations_do_not_resolve_accession_failure(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="INDEXSCOPE", exchange="US", company_name="Index Scope")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Index scope fixture.",
    )
    db_session.commit()
    failed = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=ToggleIndexOutageClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    _commit_and_finalize(db_session, failed)
    snapshot = db_session.scalar(select(SecSubmissionSnapshot))

    no_eligible = SecFinancialIngestionOperation(
        id=str(uuid.uuid4()),
        issuer_identity_id=identity.id,
        attempted_at=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.add(no_eligible)
    db_session.flush()
    db_session.add(
        SecFinancialOperationSnapshot(
            operation_id=no_eligible.id,
            snapshot_id=snapshot.id,
        )
    )
    db_session.add(
        SecFinancialOperationResult(
            operation_id=no_eligible.id,
            result_kind="no_eligible_filings",
        )
    )
    db_session.commit()
    finalize_sec_financial_ingestion_operation(
        db_session, operation_id=no_eligible.id
    )
    db_session.commit()

    different_accession = f"{CIK}-26-000080"
    filing = SecFinancialFiling(
        issuer_identity_id=identity.id,
        accession_no=different_accession,
        form_type="10-Q",
        is_amendment=False,
        filed_on=date(2026, 8, 1),
        report_date=date(2026, 6, 28),
        accepted_at=datetime(2026, 8, 1, 20, 5, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 15, tzinfo=timezone.utc),
        primary_document="different.htm",
        index_url=(
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019326000080/index.json"
        ),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019326000080/different.htm"
        ),
        submissions_source_url=SUBMISSIONS_URL,
        discovery_payload_sha256=snapshot.sha256,
    )
    db_session.add(filing)
    db_session.flush()
    index_storage_key, index_sha256 = _store_content_immutable(tmp_path, b"{}")
    filing_artifact = SecFilingArtifact(
        filing_id=filing.id,
        sequence=0,
        filename="__accession_index__.json",
        source_url=filing.index_url,
        manifest_hash="d" * 64,
        state="retained",
        content_mime="application/json",
        sha256=index_sha256,
        byte_size=2,
        storage_key=index_storage_key,
        fetched_at=datetime(2026, 8, 27, 12, 15, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 15, tzinfo=timezone.utc),
    )
    db_session.add(filing_artifact)
    db_session.flush()
    parse_operation = SecFinancialIngestionOperation(
        id=str(uuid.uuid4()),
        issuer_identity_id=identity.id,
        attempted_at=datetime(2026, 8, 27, 12, 15, tzinfo=timezone.utc),
    )
    db_session.add(parse_operation)
    db_session.flush()
    db_session.add(
        SecFinancialOperationSnapshot(
            operation_id=parse_operation.id,
            snapshot_id=snapshot.id,
        )
    )
    parse_run = SecFinancialParseRun(
        filing_id=filing.id,
        operation_id=parse_operation.id,
        parser_name="fixture",
        parser_version="failed-different-accession",
        input_manifest_hash="f" * 64,
        status="failed",
        started_at=datetime(2026, 8, 27, 12, 15, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 27, 12, 15, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 15, tzinfo=timezone.utc),
        fact_count=0,
        error_code="no_inline_xbrl_facts",
    )
    db_session.add(parse_run)
    db_session.flush()
    db_session.add(
        SecFinancialOperationResult(
            operation_id=parse_operation.id,
            result_kind="parse_run",
            parse_run_id=parse_run.id,
        )
    )
    _add_current_accession_attempt_resolution(
        db_session,
        operation=parse_operation,
        filing=filing,
        run=parse_run,
        artifacts=[filing_artifact],
    )
    db_session.commit()
    parse_available_at = finalize_sec_financial_ingestion_operation(
        db_session, operation_id=parse_operation.id
    )
    db_session.commit()

    failures = select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=parse_available_at + timedelta(seconds=1),
        storage_root=tmp_path,
    )
    assert {(item.accession_no, item.error_code) for item in failures} == {
        (ACCESSION, "sec_temporarily_unavailable"),
        (different_accession, "no_inline_xbrl_facts"),
    }


def test_same_accession_parse_failure_replaces_acquisition_failure_across_cutoffs(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="INDEXPARSE", exchange="US", company_name="Index Parse")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Index parse fixture.",
    )
    db_session.commit()
    failed = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=ToggleIndexOutageClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    failed_available_at = _commit_and_finalize(db_session, failed)
    filing = db_session.scalar(
        select(SecFinancialFiling).where(
            SecFinancialFiling.accession_no == ACCESSION
        )
    )
    snapshot = db_session.scalar(select(SecSubmissionSnapshot))
    index_storage_key, index_sha256 = _store_content_immutable(tmp_path, b"{}")
    filing_artifact = SecFilingArtifact(
        filing_id=filing.id,
        sequence=0,
        filename="__accession_index__.json",
        source_url=filing.index_url,
        manifest_hash="d" * 64,
        state="retained",
        content_mime="application/json",
        sha256=index_sha256,
        byte_size=2,
        storage_key=index_storage_key,
        fetched_at=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.add(filing_artifact)
    db_session.flush()
    replacement = SecFinancialIngestionOperation(
        id=str(uuid.uuid4()),
        issuer_identity_id=identity.id,
        attempted_at=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.add(replacement)
    db_session.flush()
    db_session.add(
        SecFinancialOperationSnapshot(
            operation_id=replacement.id,
            snapshot_id=snapshot.id,
        )
    )
    parse_run = SecFinancialParseRun(
        filing_id=filing.id,
        operation_id=replacement.id,
        parser_name="fixture",
        parser_version="failed-same-accession",
        input_manifest_hash="e" * 64,
        status="failed",
        started_at=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
        fact_count=0,
        error_code="no_inline_xbrl_facts",
    )
    db_session.add(parse_run)
    db_session.flush()
    db_session.add(
        SecFinancialOperationResult(
            operation_id=replacement.id,
            result_kind="parse_run",
            parse_run_id=parse_run.id,
        )
    )
    _add_current_accession_attempt_resolution(
        db_session,
        operation=replacement,
        filing=filing,
        run=parse_run,
        artifacts=[filing_artifact],
    )
    db_session.commit()
    replacement_available_at = finalize_sec_financial_ingestion_operation(
        db_session, operation_id=replacement.id
    )
    db_session.commit()

    assert [item.error_code for item in select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=failed_available_at + timedelta(microseconds=1),
        storage_root=tmp_path,
    )] == ["sec_temporarily_unavailable"]
    assert [item.error_code for item in select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=replacement_available_at + timedelta(seconds=1),
        storage_root=tmp_path,
    )] == ["no_inline_xbrl_facts"]


@pytest.mark.parametrize("transition", ["supersede", "retire"])
def test_acquisition_failure_obeys_terminal_identity_at_cutoff(
    committed_db_session,
    tmp_path: Path,
    transition: str,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker=f"IDENT-{transition}", exchange="US", company_name="Identity")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Identity cutoff fixture.",
    )
    db_session.commit()
    failed = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=ToggleIndexOutageClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    failed_available_at = _commit_and_finalize(db_session, failed)
    assert [item.error_code for item in select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=failed_available_at + timedelta(microseconds=1),
        storage_root=tmp_path,
    )] == ["sec_temporarily_unavailable"]

    transition_known_at = datetime.now(timezone.utc)
    if transition == "supersede":
        terminal = register_reviewed_sec_identity(
            db_session,
            stock_id=stock.id,
            cik="0001067983",
            effective_from=date(1980, 12, 12),
            known_at=transition_known_at,
            review_reason="Reviewed replacement identity.",
            supersedes_identity_id=identity.id,
        )
    else:
        terminal = retire_sec_identity(
            db_session,
            identity_id=identity.id,
            known_at=transition_known_at,
            review_reason="Reviewed retirement.",
        )
    db_session.commit()
    db_session.refresh(terminal)

    assert select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=max(terminal.known_at, terminal.created_at) + timedelta(seconds=1),
        storage_root=tmp_path,
    ) == []


def test_pending_earlier_resolution_cannot_erase_later_failure_when_finalized_late(
    committed_db_session,
    tmp_path: Path,
) -> None:
    root_session = committed_db_session
    stock = Stock(ticker="ORDERING", exchange="US", company_name="Ordering")
    root_session.add(stock)
    root_session.flush()
    register_reviewed_sec_identity(
        root_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Resolution ordering fixture.",
    )
    root_session.commit()
    stock_id = stock.id

    with Session(root_session.bind) as early_session:
        early = ingest_latest_financial_filings(
            early_session,
            stock_id=stock_id,
            client=EmptyMainSubmissionsClient(),
            storage_root=tmp_path,
            max_filings=1,
            now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
        )
        early_session.commit()

        with Session(root_session.bind) as later_session:
            later = ingest_latest_financial_filings(
                later_session,
                stock_id=stock_id,
                client=MalformedMainSubmissionsClient(),
                storage_root=tmp_path,
                max_filings=1,
                now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
            )
            later_failure_created_at = later_session.scalar(
                select(SecFinancialAcquisitionFailure.created_at).where(
                    SecFinancialAcquisitionFailure.operation_id
                    == later.operation_id
                )
            )
            later_session.commit()
            later_available_at = finalize_sec_financial_ingestion_operation(
                later_session, operation_id=later.operation_id
            )
            later_session.commit()

        early_resolution_created_at = early_session.scalar(
            select(SecFinancialAcquisitionResolution.created_at).where(
                SecFinancialAcquisitionResolution.operation_id == early.operation_id,
                SecFinancialAcquisitionResolution.resource_role
                == "main_submissions",
            )
        )
        assert early_resolution_created_at < later_failure_created_at
        early_available_at = finalize_sec_financial_ingestion_operation(
            early_session, operation_id=early.operation_id
        )
        early_session.commit()

    assert early_available_at > later_available_at
    root_session.expire_all()
    assert [item.error_code for item in select_sec_financial_failures_as_of(
        root_session,
        stock_id=stock_id,
        cutoff=early_available_at + timedelta(seconds=1),
        storage_root=tmp_path,
    )] == ["invalid_main_submissions_payload"]


def test_empty_operation_cannot_incorrectly_link_an_old_parse_run(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="OLDLINK", exchange="US", company_name="Old Link Fixture")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Incorrect old-run linkage fixture.",
    )
    db_session.commit()
    original = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=FakeEdgarClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    _commit_and_finalize(db_session, original)
    prior_run = db_session.scalar(
        select(SecFinancialParseRun).where(
            SecFinancialParseRun.operation_id == original.operation_id
        )
    )
    snapshot = db_session.scalar(select(SecSubmissionSnapshot))
    empty_operation = SecFinancialIngestionOperation(
        id=str(uuid.uuid4()),
        issuer_identity_id=identity.id,
        attempted_at=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.add(empty_operation)
    db_session.flush()
    db_session.add(
        SecFinancialOperationSnapshot(
            operation_id=empty_operation.id,
            snapshot_id=snapshot.id,
        )
    )
    db_session.add(
        SecFinancialOperationResult(
            operation_id=empty_operation.id,
            result_kind="parse_run",
            parse_run_id=prior_run.id,
        )
    )
    db_session.flush()

    with pytest.raises(DBAPIError, match="current operation accession attempt"):
        with db_session.begin_nested():
            db_session.add(
                SecFinancialAcquisitionResolution(
                    operation_id=empty_operation.id,
                    resource_role="accession_terminal",
                    resource_key=ACCESSION,
                    resolution_kind="parse_succeeded",
                    parse_run_id=prior_run.id,
                    accession_no=ACCESSION,
                )
            )
            db_session.flush()


def test_artifact_failure_requires_exact_failed_artifact_observation(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="FAILSCOPE", exchange="US", company_name="Failure Scope")
    db_session.add(stock)
    db_session.flush()
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Artifact failure scope fixture.",
    )
    db_session.commit()
    original = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=FakeEdgarClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    _commit_and_finalize(db_session, original)
    filing = db_session.scalar(select(SecFinancialFiling))
    snapshot = db_session.scalar(select(SecSubmissionSnapshot))
    operation = SecFinancialIngestionOperation(
        id=str(uuid.uuid4()),
        issuer_identity_id=identity.id,
        attempted_at=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.add(operation)
    db_session.flush()
    db_session.add(
        SecFinancialOperationSnapshot(
            operation_id=operation.id,
            snapshot_id=snapshot.id,
        )
    )
    rejected_url = filing.source_url.replace(filing.primary_document, "mismatch.htm")
    rejected_direct = SecFilingArtifact(
        filing_id=filing.id,
        sequence=50,
        filename="mismatch.htm",
        source_url=rejected_url,
        manifest_hash="1" * 64,
        state="rejected",
        reason_code="declared_size_mismatch",
        known_at=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    rejected_urn = SecFilingArtifact(
        filing_id=filing.id,
        sequence=51,
        filename="../unsafe.htm",
        source_url=None,
        manifest_hash="2" * 64,
        state="rejected",
        reason_code="unsafe_filename",
        known_at=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.add_all([rejected_direct, rejected_urn])
    db_session.flush()
    retained = db_session.scalar(
        select(SecFilingArtifact).where(
            SecFilingArtifact.filename == filing.primary_document
        )
    )

    def add_failure(resource_key: str, error_code: str) -> None:
        db_session.add(
            SecFinancialAcquisitionFailure(
                operation_id=operation.id,
                submission_snapshot_id=snapshot.id,
                stage="filing_artifact_acquisition",
                error_code=error_code,
                accession_no=filing.accession_no,
                resource_role="filing_artifact",
                resource_key=resource_key,
            )
        )
        db_session.flush()

    with pytest.raises(DBAPIError, match="failed artifact observation"):
        with db_session.begin_nested():
            add_failure(retained.source_url, "fetch_failed")
    mismatched_urn = (
        "urn:valuepilot:sec-filing-artifact:"
        f"{filing.accession_no}:sha256:{'0' * 64}"
    )
    with pytest.raises(DBAPIError, match="failed artifact observation"):
        with db_session.begin_nested():
            add_failure(mismatched_urn, "unsafe_filename")

    valid_urn = (
        "urn:valuepilot:sec-filing-artifact:"
        f"{filing.accession_no}:sha256:"
        + hashlib.sha256(rejected_urn.filename.encode()).hexdigest()
    )
    add_failure(rejected_url, "declared_size_mismatch")
    add_failure(valid_urn, "unsafe_filename")


def test_historical_fetch_outage_retains_all_prior_payloads_and_finalizes(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="HIST503", exchange="US", company_name="History Outage")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Historical outage fixture.",
    )
    db_session.commit()
    client = OrderedHistoricalFetchOutageClient()

    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()
    available_at = finalize_sec_financial_ingestion_operation(
        db_session, operation_id=report.operation_id
    )
    db_session.commit()

    assert client.calls == [SUBMISSIONS_URL, client.first_url, client.second_url]
    assert report.failures == ("historical_submissions_sec_temporarily_unavailable",)
    assert report.filings_created == 0
    assert report.parse_runs_created == 0
    snapshots = db_session.scalars(
        select(SecSubmissionSnapshot).order_by(SecSubmissionSnapshot.source_url)
    ).all()
    assert {snapshot.source_url for snapshot in snapshots} == {
        SUBMISSIONS_URL,
        client.first_url,
    }
    assert all((tmp_path / snapshot.storage_key).is_file() for snapshot in snapshots)
    terminal = db_session.get(SecFinancialOperationResult, report.operation_id)
    assert terminal.result_kind == "acquisition_failure"
    assert [item.error_code for item in select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=available_at + timedelta(seconds=1),
        storage_root=tmp_path,
    )] == ["historical_submissions_sec_temporarily_unavailable"]


def test_exact_historical_resource_validation_resolves_prior_failure(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="HISTRESOLVE", exchange="US", company_name="History Resolve")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Historical resolution fixture.",
    )
    db_session.commit()
    client = SwitchableHistoricalResourceClient()
    failed = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    failed_available_at = _commit_and_finalize(db_session, failed)
    assert [item.error_code for item in select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=failed_available_at + timedelta(microseconds=1),
        storage_root=tmp_path,
    )] == ["invalid_historical_submissions_payload"]

    client.resolve_same_resource()
    resolved = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    resolved_available_at = _commit_and_finalize(db_session, resolved)

    assert resolved.failures == ()
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialAcquisitionResolution).where(
            SecFinancialAcquisitionResolution.operation_id == resolved.operation_id,
            SecFinancialAcquisitionResolution.resource_role
            == "historical_submissions",
            SecFinancialAcquisitionResolution.resource_key == client.first_url,
            SecFinancialAcquisitionResolution.resolution_kind
            == "resource_validated",
        )
    ) == 1
    assert select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=resolved_available_at + timedelta(seconds=1),
        storage_root=tmp_path,
    ) == []


def test_different_historical_resource_does_not_resolve_prior_failure(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="HISTSCOPE", exchange="US", company_name="History Scope")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Historical scope fixture.",
    )
    db_session.commit()
    client = SwitchableHistoricalResourceClient()
    failed = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    _commit_and_finalize(db_session, failed)
    client.switch_to_different_resource()
    unrelated = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    unrelated_available_at = _commit_and_finalize(db_session, unrelated)

    assert unrelated.failures == ()
    failures = select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=unrelated_available_at + timedelta(seconds=1),
        storage_root=tmp_path,
    )
    assert [(item.accession_no, item.error_code) for item in failures] == [
        ("submissions", "invalid_historical_submissions_payload")
    ]


def test_churned_main_can_link_reused_malformed_history_to_new_failure_operation(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="HISTCHURN", exchange="US", company_name="History Churn")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Historical churn fixture.",
    )
    db_session.commit()
    client = ChurningMainReusedMalformedHistoryClient()

    first = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    _commit_and_finalize(db_session, first)
    client.churn_main()
    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    _commit_and_finalize(db_session, second)

    assert second.operation_id != first.operation_id
    assert second.failures == ("invalid_historical_submissions_payload",)
    assert db_session.scalar(select(func.count()).select_from(SecSubmissionSnapshot)) == 3
    historical_snapshot = db_session.scalar(
        select(SecSubmissionSnapshot).where(
            SecSubmissionSnapshot.source_url == client.historical_url
        )
    )
    second_failure = db_session.scalar(
        select(SecFinancialAcquisitionFailure).where(
            SecFinancialAcquisitionFailure.operation_id == second.operation_id
        )
    )
    assert historical_snapshot.operation_id == first.operation_id
    assert second_failure.submission_snapshot_id == historical_snapshot.id
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialOperationSnapshot).where(
            SecFinancialOperationSnapshot.operation_id == second.operation_id,
            SecFinancialOperationSnapshot.snapshot_id == historical_snapshot.id,
        )
    ) == 1
    third = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 15, tzinfo=timezone.utc),
    )
    db_session.commit()
    assert third.operation_id == second.operation_id
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialIngestionOperation)
    ) == 2


def test_failed_evidence_replay_is_empty_without_eligible_filing_history(
    db_session,
    tmp_path: Path,
) -> None:
    stock = Stock(ticker="EMPTY", exchange="US", company_name="Empty Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik="0000000088",
        effective_from=date(1980, 1, 1),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Empty fixture.",
    )
    db_session.commit()

    assert select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
        storage_root=tmp_path,
    ) == []


def test_replay_keeps_success_and_terminal_failure_for_different_filings(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock, identity, succeeded_filing, artifact, operation = _database_lineage_fixture(
        db_session, tmp_path, ticker="MIXED", cik="0000000087"
    )
    succeeded_run = SecFinancialParseRun(
        filing_id=succeeded_filing.id,
        operation_id=operation.id,
        parser_name="fixture",
        parser_version="success",
        input_manifest_hash="d" * 64,
        status="succeeded",
        started_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 3, tzinfo=timezone.utc),
        fact_count=1,
    )
    db_session.add(succeeded_run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=succeeded_run.id,
            artifact_id=artifact.id,
            known_at=succeeded_run.known_at,
        )
    )
    db_session.flush()
    db_session.add(_raw_fact(succeeded_run.id, artifact.id))

    failed_filing = SecFinancialFiling(
        issuer_identity_id=identity.id,
        accession_no="0000000087-26-000002",
        form_type="10-Q",
        is_amendment=False,
        filed_on=date(2026, 8, 15),
        report_date=date(2026, 7, 31),
        accepted_at=datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 4, tzinfo=timezone.utc),
        primary_document="failed.htm",
        index_url=_canonical_artifact_url(
            "0000000087", "0000000087-26-000002", "index.json"
        ),
        source_url=_canonical_artifact_url(
            "0000000087", "0000000087-26-000002", "failed.htm"
        ),
        submissions_source_url=(
            "https://data.sec.gov/submissions/CIK0000000087.json"
        ),
        discovery_payload_sha256="e" * 64,
    )
    db_session.add(failed_filing)
    db_session.flush()
    failed_run = SecFinancialParseRun(
        filing_id=failed_filing.id,
        operation_id=operation.id,
        parser_name="fixture",
        parser_version="failed",
        input_manifest_hash="f" * 64,
        status="failed",
        started_at=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
        fact_count=0,
        error_code="required_artifact_unavailable",
    )
    db_session.add(failed_run)
    db_session.flush()
    failed_storage_key, failed_sha256 = _store_content_immutable(tmp_path, b"{}")
    failed_artifact = SecFilingArtifact(
        filing_id=failed_filing.id,
        sequence=0,
        filename="__accession_index__.json",
        source_url=failed_filing.index_url,
        manifest_hash="7" * 64,
        state="retained",
        content_mime="application/json",
        sha256=failed_sha256,
        byte_size=2,
        storage_key=failed_storage_key,
        fetched_at=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.add(failed_artifact)
    db_session.flush()
    snapshot = SecSubmissionSnapshot(
        issuer_identity_id=identity.id,
        operation_id=operation.id,
        source_url="https://data.sec.gov/submissions/CIK0000000087.json",
        sha256="9" * 64,
        byte_size=2,
        storage_key="financial/99/" + "9" * 64,
        fetched_at=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
        known_at=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.add(snapshot)
    db_session.flush()
    db_session.add_all(
        [
            SecFinancialOperationSnapshot(
                operation_id=operation.id,
                snapshot_id=snapshot.id,
            ),
            SecFinancialOperationResult(
                operation_id=operation.id,
                result_kind="parse_run",
                parse_run_id=failed_run.id,
            ),
        ]
    )
    _add_current_accession_attempt_resolution(
        db_session,
        operation=operation,
        filing=succeeded_filing,
        run=succeeded_run,
        artifacts=[artifact],
    )
    _add_current_accession_attempt_resolution(
        db_session,
        operation=operation,
        filing=failed_filing,
        run=failed_run,
        artifacts=[failed_artifact],
    )
    db_session.commit()
    finalize_sec_financial_ingestion_operation(db_session, operation_id=operation.id)
    db_session.commit()
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)

    successes = select_sec_financial_evidence_as_of(
        db_session, stock_id=stock.id, cutoff=cutoff, storage_root=tmp_path
    )
    failures = select_sec_financial_failures_as_of(
        db_session, stock_id=stock.id, cutoff=cutoff, storage_root=tmp_path
    )

    assert [item.accession_no for item in successes] == [succeeded_filing.accession_no]
    assert [(item.accession_no, item.error_code) for item in failures] == [
        (failed_filing.accession_no, "required_artifact_unavailable")
    ]


def test_parser_v2_writes_exact_statement_authority_in_parse_transaction(
    committed_db_session, tmp_path: Path
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="AAPL", exchange="US", company_name="Apple Inc.")
    db_session.add(stock); db_session.flush()
    register_reviewed_sec_identity(db_session, stock_id=stock.id, cik=CIK,
        effective_from=date(1980, 12, 12), known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="fixture reviewed identity")
    db_session.commit()
    report = ingest_latest_financial_filings(db_session, stock_id=stock.id,
        client=StatementAuthorityClient(), storage_root=tmp_path, max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc), parser_version="xbrl-lineage-v2")
    authority = db_session.scalar(select(SecStatementFactAuthority))
    raw_fact = db_session.get(SecRawXbrlFact, authority.raw_fact_id)
    parse_run = db_session.get(SecFinancialParseRun, authority.parse_run_id)
    assert report.parse_runs_created == 1
    assert authority.context_id == raw_fact.context_id == "D2026Q3"
    assert authority.statement_sha256 == db_session.get(SecFilingArtifact, authority.statement_artifact_id).sha256
    assert authority.created_txid == raw_fact.created_txid == parse_run.created_txid
    assert authority.presentation_class == "current_period"
    reference = db_session.get(SecStatementReportReference, authority.statement_report_reference_id)
    occurrence = db_session.get(SecStatementOccurrenceEvidence, authority.statement_occurrence_id)
    assert reference.filename == "FinancialStatements.xml"
    assert reference.report_artifact_id == authority.statement_artifact_id
    assert occurrence.statement_report_reference_id == reference.id
    assert occurrence.header_date == raw_fact.period_end
    db_session.commit()
    for statement in (
        "UPDATE sec_statement_fact_authorities SET report_name='forged'",
        "DELETE FROM sec_statement_fact_authorities",
        "TRUNCATE sec_statement_fact_authorities",
        "UPDATE sec_statement_report_references SET filename='forged.xml'",
        "DELETE FROM sec_statement_report_references",
        "TRUNCATE sec_statement_report_references",
        "UPDATE sec_statement_occurrence_evidence SET header_raw='forged'",
        "DELETE FROM sec_statement_occurrence_evidence",
        "TRUNCATE sec_statement_occurrence_evidence",
    ):
        with pytest.raises(DBAPIError), db_session.begin_nested():
            db_session.execute(text(statement))
    primary_artifact = db_session.scalar(select(SecFilingArtifact).where(SecFilingArtifact.filename == "aapl-20260627.htm"))
    forged_material = chr(31).join((reference.filing_summary_sha256, primary_artifact.filename, "1",
        reference.statement_role, reference.statement_type, reference.report_name))
    with pytest.raises(DBAPIError, match="not an exact FilingSummary reference"), db_session.begin_nested():
        db_session.execute(text("""INSERT INTO sec_statement_report_references
          (parse_run_id,filing_summary_artifact_id,filing_summary_sha256,filing_summary_byte_size,filing_summary_content,
           report_artifact_id,report_sha256,report_byte_size,filename,report_ordinal,statement_role,statement_type,report_name,
           reference_semantic_sha256,known_at)
          VALUES (:run,:summary,:summary_sha,:summary_bytes,:summary_content,:report,:report_sha,:report_bytes,:filename,1,
                  :role,:type,:name,:claim,:known_at)"""), {
            "run": authority.parse_run_id, "summary": reference.filing_summary_artifact_id,
            "summary_sha": reference.filing_summary_sha256, "summary_bytes": reference.filing_summary_byte_size,
            "summary_content": reference.filing_summary_content, "report": primary_artifact.id,
            "report_sha": primary_artifact.sha256, "report_bytes": primary_artifact.byte_size,
            "filename": primary_artifact.filename, "role": reference.statement_role, "type": reference.statement_type,
            "name": reference.report_name, "claim": hashlib.sha256(forged_material.encode()).hexdigest(),
            "known_at": reference.known_at})
    base_authority = {
        "raw": authority.raw_fact_id, "run": authority.parse_run_id, "reference": authority.statement_report_reference_id,
        "artifact": authority.statement_artifact_id, "sha": authority.statement_sha256, "bytes": authority.statement_byte_size,
        "role": authority.statement_role, "type": authority.statement_type, "report_ordinal": authority.report_ordinal,
        "name": authority.report_name, "fact_id": authority.occurrence_fact_id,
        "semantic": authority.occurrence_semantic_sha256, "context": authority.context_id,
        "presentation": authority.presentation_class, "period_end": authority.statement_period_end,
        "fy": authority.fiscal_year, "fq": authority.fiscal_quarter_ordinal, "fy_start": authority.fiscal_year_start,
        "locator": json.dumps(authority.locator_json), "known_at": authority.known_at,
        "statement_occurrence": authority.statement_occurrence_id,
        "current_anchor": authority.current_anchor_occurrence_id,
        "prior_anchor": authority.prior_anchor_occurrence_id,
    }
    for offset, changes in enumerate((
        {"role": "forged-role"}, {"type": "balance_sheet"}, {"name": "forged-name"},
        {"sha": "f" * 64}, {"bytes": authority.statement_byte_size + 1},
        {"report_ordinal": authority.report_ordinal + 1}, {"artifact": primary_artifact.id}, {"reference": 999999999},
        {"presentation": "prior_same_fiscal_quarter"},
        {"period_end": authority.statement_period_end - timedelta(days=1)},
        {"fy": authority.fiscal_year - 1}, {"fq": 2},
        {"fy_start": authority.fiscal_year_start + timedelta(days=1)},
        {"locator": json.dumps({**authority.locator_json, "column": 99})},
        {"occurrence": authority.occurrence_ordinal + 99},
    ), start=100):
        params = {**base_authority, **changes, "occurrence": offset}
        with pytest.raises(DBAPIError), db_session.begin_nested():
            db_session.execute(text("""INSERT INTO sec_statement_fact_authorities
              (raw_fact_id,statement_report_reference_id,parse_run_id,statement_artifact_id,statement_sha256,
               statement_byte_size,statement_role,statement_type,report_ordinal,report_name,occurrence_ordinal,
               occurrence_fact_id,occurrence_semantic_sha256,context_id,presentation_class,statement_period_end,
               fiscal_year,fiscal_quarter_ordinal,fiscal_year_start,locator_json,known_at,
               statement_occurrence_id,current_anchor_occurrence_id,prior_anchor_occurrence_id)
              VALUES (:raw,:reference,:run,:artifact,:sha,:bytes,:role,:type,:report_ordinal,:name,:occurrence,
                      :fact_id,:semantic,:context,:presentation,:period_end,:fy,:fq,:fy_start,CAST(:locator AS jsonb),:known_at,
                      :statement_occurrence,:current_anchor,:prior_anchor)"""), params)


def test_parser_v2_missing_filing_summary_is_typed_terminal_parse_failure(
    committed_db_session, tmp_path: Path
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="MISSFS", exchange="US", company_name="Missing Summary")
    db_session.add(stock); db_session.flush()
    register_reviewed_sec_identity(db_session, stock_id=stock.id, cik=CIK,
        effective_from=date(1980, 12, 12), known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="fixture reviewed identity")
    db_session.commit()
    report = ingest_latest_financial_filings(db_session, stock_id=stock.id, client=FakeEdgarClient(),
        storage_root=tmp_path, max_filings=1, now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
        parser_version="xbrl-lineage-v2")
    run = db_session.get(SecFinancialParseRun, db_session.scalar(select(SecFinancialParseRun.id)))
    assert run.status == "failed" and run.error_code == "statement_authority_parse_failed"
    assert "missing_retained_filing_summary" in run.error_detail
    assert any("statement_authority_parse_failed:StatementAuthorityParseError" in item for item in report.failures)
    assert db_session.scalar(select(func.count()).select_from(SecStatementReportReference)) == 0


@pytest.mark.parametrize("filename", ("R1000.xml", "R0001.xml", "r1000.XML"))
def test_generated_report_xml_is_never_retained_linked_or_authorized_for_replay(
    db_session,
    tmp_path: Path,
    filename: str,
) -> None:
    stock = Stock(ticker="RXML", exchange="US", company_name="Report XML Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="fixture reviewed identity",
    )
    client = GeneratedReportXmlClient(filename)
    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
        parser_version="inline-xbrl-v1",
    )
    report_url = _canonical_artifact_url(CIK, ACCESSION, filename)
    artifact = db_session.scalar(
        select(SecFilingArtifact).where(SecFilingArtifact.filename == filename)
    )

    assert artifact is not None
    assert artifact.state == "manifest_only"
    assert report_url not in client.calls
    assert report_url not in client.revalidated_calls
    assert db_session.scalar(
        select(func.count())
        .select_from(SecFinancialAccessionAttemptArtifact)
        .where(SecFinancialAccessionAttemptArtifact.artifact_id == artifact.id)
    ) == 0
    assert db_session.scalar(
        select(func.count())
        .select_from(SecFinancialParseRunArtifact)
        .where(SecFinancialParseRunArtifact.artifact_id == artifact.id)
    ) == 0

    upstream_factory_calls = 0

    def upstream_factory():
        nonlocal upstream_factory_calls
        upstream_factory_calls += 1
        raise AssertionError("generated report reached recovery upstream")

    replay = build_retained_financial_replay_client(
        db_session,
        stock_id=stock.id,
        operation_ids=(report.operation_id,),
        storage_root=tmp_path,
        upstream_factory=upstream_factory,
    )
    with pytest.raises(SecFinancialIntegrityError, match="unapproved SEC resource"):
        replay.get_revalidated(report_url)
    assert upstream_factory_calls == 0
    assert replay.external_requests == []


def test_ingestion_is_idempotent_pit_safe_and_does_not_publish_metric_facts(
    committed_db_session, tmp_path: Path
) -> None:
    db_session = committed_db_session
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
    first_available_at = _commit_and_finalize(db_session, first)
    replayable_after_first = earliest_replayable_sec_financial_evidence_at(
        db_session, stock_id=stock.id, storage_root=tmp_path
    )
    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
        parser_version="inline-xbrl-v1",
    )
    _commit_and_finalize(db_session, second)

    assert identity.status == "reviewed"
    assert first.filings_discovered == 1
    assert [
        (item.accession_no, item.form_type, item.accepted_at.isoformat())
        for item in first.selected_filings
    ] == [
        (
            ACCESSION,
            "10-Q",
            "2026-07-31T16:05:28-04:00",
        )
    ]
    assert first.parse_runs_created == 1
    assert first.raw_facts_created == 3
    assert second.parse_runs_created == 0
    assert second.raw_facts_created == 0
    assert select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=first_available_at - timedelta(microseconds=1),
        storage_root=tmp_path,
    ) == []
    assert len(select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=first_available_at,
        storage_root=tmp_path,
    )) == 1
    assert len(select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=first_available_at + timedelta(microseconds=1),
        storage_root=tmp_path,
    )) == 1
    acceptance_report = build_case_report(
        db_session,
        run_id="step-c-fake",
        case_id="aapl-primary",
        filing_selection_as_of=datetime(
            2026, 8, 26, 23, 59, 59, tzinfo=timezone.utc
        ),
        expected_completed_fiscal_years=(2025, 2024),
        ingestion_report=first,
        evidence_available_at=first_available_at,
    )
    assert acceptance_report.operation_attempted_at > datetime(
        2026, 8, 27, 12, 5, tzinfo=timezone.utc
    )
    assert acceptance_report.evidence_available_at == first_available_at
    assert acceptance_report.metric_facts_published == 0
    assert replayable_after_first is not None
    assert earliest_replayable_sec_financial_evidence_at(
        db_session, stock_id=stock.id, storage_root=tmp_path
    ) == replayable_after_first
    assert db_session.scalar(select(func.count()).select_from(SecFinancialFiling)) == 1
    assert db_session.scalar(select(func.count()).select_from(SecFilingArtifact)) == 4
    assert db_session.scalar(select(func.count()).select_from(SecFinancialParseRun)) == 1
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialParseRunArtifact)
    ) == 3
    assert db_session.scalar(select(func.count()).select_from(SecRawXbrlFact)) == 3
    assert db_session.scalar(select(func.count()).select_from(SecSubmissionSnapshot)) == 1
    assert db_session.scalar(select(func.count()).select_from(MetricFact)) == 0
    attempts = db_session.scalars(
        select(SecFinancialAccessionAttempt).order_by(
            SecFinancialAccessionAttempt.created_at,
            SecFinancialAccessionAttempt.id,
        )
    ).all()
    assert [attempt.outcome for attempt in attempts[:2]] == [
        "parse_succeeded",
        "parse_reused_succeeded",
    ]
    assert attempts[1].parse_run_id == attempts[0].parse_run_id
    assert attempts[1].input_manifest_hash == attempts[0].input_manifest_hash
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialAccessionAttemptArtifact).where(
            SecFinancialAccessionAttemptArtifact.attempt_id == attempts[1].id
        )
    ) == 3

    retained = db_session.scalars(
        select(SecFilingArtifact).where(SecFilingArtifact.state == "retained")
    ).all()
    assert len(retained) == 3
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
    assert discovery_names == {"__accession_index__.json"}
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
        storage_root=tmp_path,
    )
    after_ingestion = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=after_ingestion_cutoff,
        storage_root=tmp_path,
    )
    assert before_identity == []
    assert len(after_ingestion) == 1
    assert after_ingestion[0].accession_no == ACCESSION
    assert after_ingestion[0].parser_version == "inline-xbrl-v1"


    retained_inputs = db_session.scalars(
        select(SecFilingArtifact).where(SecFilingArtifact.state == "retained")
    ).all()
    # Keep the synthetic next operation causally later than the first operation.
    later_known_at = max(
        after_ingestion_cutoff, datetime.now(timezone.utc)
    ) + timedelta(milliseconds=500)
    later_operation = SecFinancialIngestionOperation(
        id=str(uuid.uuid4()),
        issuer_identity_id=identity.id,
        attempted_at=later_known_at,
    )
    db_session.add(later_operation)
    db_session.flush()
    retained_snapshot = db_session.scalar(select(SecSubmissionSnapshot))
    db_session.add(
        SecFinancialOperationSnapshot(
            operation_id=later_operation.id,
            snapshot_id=retained_snapshot.id,
        )
    )
    later_run = SecFinancialParseRun(
        filing_id=first_run.filing_id,
        operation_id=later_operation.id,
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
    db_session.add(
        SecFinancialOperationResult(
            operation_id=later_operation.id,
            result_kind="parse_run",
            parse_run_id=later_run.id,
        )
    )
    _add_current_accession_attempt_resolution(
        db_session,
        operation=later_operation,
        filing=db_session.get(SecFinancialFiling, later_run.filing_id),
        run=later_run,
        artifacts=retained_inputs,
    )
    db_session.commit()
    finalize_sec_financial_ingestion_operation(
        db_session, operation_id=later_operation.id
    )
    db_session.commit()

    before_later_parser = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=later_known_at - timedelta(microseconds=1),
        storage_root=tmp_path,
    )
    after_later_parser = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=later_known_at + timedelta(minutes=1),
        storage_root=tmp_path,
    )
    assert before_later_parser[0].parser_version == "inline-xbrl-v1"
    assert after_later_parser[0].parser_version == "inline-xbrl-v2"

    late_input = SecFilingArtifact(
        filing_id=first_run.filing_id,
        sequence=99,
        filename="late-input.xml",
        source_url=_canonical_artifact_url(
            CIK, ACCESSION, "late-input.xml"
        ),
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


    amendment_accepted_at = later_known_at + timedelta(milliseconds=500)
    amendment_known_at = amendment_accepted_at + timedelta(milliseconds=500)
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
        index_url=_canonical_artifact_url(
            CIK, "0000320193-26-000080", "index.json"
        ),
        source_url=_canonical_artifact_url(
            CIK, "0000320193-26-000080", "aapl-20260627a.htm"
        ),
        submissions_source_url=SUBMISSIONS_URL,
        discovery_payload_sha256="c" * 64,
        amends_filing_id=first_run.filing_id,
    )
    db_session.add(amendment)
    db_session.flush()
    amendment_index_storage, amendment_index_sha = _store_content_immutable(
        tmp_path, b"{}"
    )
    amendment_index_artifact = SecFilingArtifact(
        filing_id=amendment.id,
        sequence=0,
        filename="__accession_index__.json",
        source_url=amendment.index_url,
        manifest_hash="d" * 64,
        state="retained",
        content_mime="application/json",
        sha256=amendment_index_sha,
        byte_size=2,
        storage_key=amendment_index_storage,
        fetched_at=amendment_known_at,
        known_at=amendment_known_at,
    )
    db_session.add(amendment_index_artifact)
    amended_artifact = SecFilingArtifact(
        filing_id=amendment.id,
        sequence=1,
        filename="aapl-20260627a.htm",
        source_url=amendment.source_url,
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
    amendment_run_known_at = amendment_known_at + timedelta(milliseconds=500)
    amendment_operation = SecFinancialIngestionOperation(
        id=str(uuid.uuid4()),
        issuer_identity_id=identity.id,
        attempted_at=amendment_run_known_at,
    )
    db_session.add(amendment_operation)
    db_session.flush()
    db_session.add(
        SecFinancialOperationSnapshot(
            operation_id=amendment_operation.id,
            snapshot_id=retained_snapshot.id,
        )
    )
    amendment_run = SecFinancialParseRun(
        filing_id=amendment.id,
        operation_id=amendment_operation.id,
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
    db_session.add(
        SecFinancialOperationResult(
            operation_id=amendment_operation.id,
            result_kind="parse_run",
            parse_run_id=amendment_run.id,
        )
    )
    _add_current_accession_attempt_resolution(
        db_session,
        operation=amendment_operation,
        filing=amendment,
        run=amendment_run,
        artifacts=[amendment_index_artifact, amended_artifact],
    )
    db_session.commit()
    finalize_sec_financial_ingestion_operation(
        db_session, operation_id=amendment_operation.id
    )
    db_session.commit()

    before_amendment = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=amendment_accepted_at - timedelta(seconds=1),
        storage_root=tmp_path,
    )
    after_amendment = select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=amendment_run_known_at + timedelta(minutes=1),
        storage_root=tmp_path,
    )
    assert [row.form_type for row in before_amendment] == ["10-Q"]
    assert {row.form_type for row in after_amendment} == {"10-Q", "10-Q/A"}

    assert primary_input.storage_key
    primary_path = tmp_path / primary_input.storage_key
    primary_path.write_bytes(b"corrupted after first ingestion")
    with pytest.raises(SecFinancialIntegrityError, match="mismatch"):
        ingest_latest_financial_filings(
            db_session,
            stock_id=stock.id,
            client=client,
            storage_root=tmp_path,
            max_filings=1,
            now=datetime.now(timezone.utc),
        )
    db_session.rollback()
    primary_path.write_bytes(INLINE_XBRL)

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
        storage_root=tmp_path,
    )
    assert select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=retired_known_at + timedelta(seconds=1),
        storage_root=tmp_path,
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
        storage_root=tmp_path,
    )
    assert restored.status == "reviewed"
    assert {row.form_type for row in restored_evidence} == {"10-Q", "10-Q/A"}

    with pytest.raises(
        SecFinancialIngestionError,
        match="different reviewed issuer identity",
    ):
        ingest_latest_financial_filings(
            db_session,
            stock_id=stock.id,
            client=client,
            storage_root=tmp_path,
            max_filings=1,
            now=restored_known_at + timedelta(minutes=1),
        )
    db_session.rollback()


@pytest.mark.parametrize("corruption", ["missing", "size", "sha"])
def test_selection_and_replay_fail_closed_on_retained_file_integrity_failure(
    committed_db_session,
    tmp_path: Path,
    corruption: str,
) -> None:
    db_session = committed_db_session
    stock = Stock(
        ticker=f"STORE{corruption.upper()}",
        exchange="US",
        company_name="Storage Integrity Fixture",
    )
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Retained-file integrity fixture.",
    )
    db_session.commit()
    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=FakeEdgarClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    available_at = _commit_and_finalize(db_session, report)
    cutoff = available_at + timedelta(seconds=1)
    assert select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=cutoff,
        storage_root=tmp_path,
    )

    primary = db_session.scalar(
        select(SecFilingArtifact).where(
            SecFilingArtifact.filename == "aapl-20260627.htm"
        )
    )
    assert primary is not None and primary.storage_key is not None
    retained_path = tmp_path / primary.storage_key
    if corruption == "missing":
        retained_path.unlink()
    elif corruption == "size":
        retained_path.write_bytes(b"short")
    else:
        content = retained_path.read_bytes()
        retained_path.write_bytes(bytes([content[0] ^ 1]) + content[1:])

    assert select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=cutoff,
        storage_root=tmp_path,
    ) == []
    assert earliest_replayable_sec_financial_evidence_at(
        db_session,
        stock_id=stock.id,
        storage_root=tmp_path,
    ) is None
    assert [
        item.error_code
        for item in select_sec_financial_failures_as_of(
            db_session,
            stock_id=stock.id,
            cutoff=cutoff,
            storage_root=tmp_path,
        )
    ] == ["retained_artifact_integrity_failure"]


@pytest.mark.parametrize("corruption", ["missing", "truncated", "same_size_sha"])
def test_newest_corrected_run_storage_failure_never_falls_back_to_older_run(
    committed_db_session,
    tmp_path: Path,
    monkeypatch,
    corruption: str,
) -> None:
    from typer.testing import CliRunner

    from app.cli import sec_financials as financial_cli

    db_session = committed_db_session
    stock = Stock(
        ticker="TWORUNBAD",
        exchange="US",
        company_name="Two Run Storage Fixture",
    )
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Two-run retained-file integrity fixture.",
    )
    db_session.commit()
    client = ChangingSubmissionsClient()
    first = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    _commit_and_finalize(db_session, first)
    client.correct_retained_bytes_without_index_change()
    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    second_available_at = _commit_and_finalize(db_session, second)

    runs = db_session.scalars(
        select(SecFinancialParseRun).order_by(SecFinancialParseRun.id)
    ).all()
    assert len(runs) == 2
    older_run, newer_run = runs
    cutoff = second_available_at + timedelta(seconds=1)
    assert [
        item.parse_run_id
        for item in select_sec_financial_evidence_as_of(
            db_session,
            stock_id=stock.id,
            cutoff=cutoff,
            storage_root=tmp_path,
        )
    ] == [newer_run.id]

    newest_primary = db_session.scalar(
        select(SecFilingArtifact)
        .join(
            SecFinancialParseRunArtifact,
            SecFinancialParseRunArtifact.artifact_id == SecFilingArtifact.id,
        )
        .where(
            SecFinancialParseRunArtifact.parse_run_id == newer_run.id,
            SecFilingArtifact.filename == "aapl-20260627.htm",
        )
    )
    assert newest_primary is not None and newest_primary.storage_key is not None
    retained_path = tmp_path / newest_primary.storage_key
    content = retained_path.read_bytes()
    if corruption == "missing":
        retained_path.unlink()
    elif corruption == "truncated":
        retained_path.write_bytes(content[:-1])
    else:
        retained_path.write_bytes(bytes([content[0] ^ 1]) + content[1:])

    assert select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=cutoff,
        storage_root=tmp_path,
    ) == []
    assert [
        (item.parse_run_id, item.error_code)
        for item in select_sec_financial_failures_as_of(
            db_session,
            stock_id=stock.id,
            cutoff=cutoff,
            storage_root=tmp_path,
        )
    ] == [(newer_run.id, "retained_artifact_integrity_failure")]
    assert earliest_replayable_sec_financial_evidence_at(
        db_session,
        stock_id=stock.id,
        storage_root=tmp_path,
    ) is None

    monkeypatch.setattr(
        financial_cli.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path)
    )
    monkeypatch.setattr(
        financial_cli,
        "SessionLocal",
        lambda: Session(db_session.bind),
    )
    result = CliRunner().invoke(
        financial_cli.app,
        [
            "replay",
            "--ticker",
            stock.ticker,
            "--cutoff",
            cutoff.isoformat(),
        ],
    )
    assert result.exit_code == 2
    assert "filings=0" in result.output
    assert f"failure={ACCESSION}:retained_artifact_integrity_failure" in result.output
    assert f"parse_run_id={older_run.id}" not in result.output
    assert "parser=" not in result.output


def test_unrelated_submissions_churn_does_not_duplicate_filing_lineage(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = Stock(ticker="CHURN", exchange="US", company_name="Churn Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Submissions churn fixture.",
    )
    db_session.commit()
    client = ChangingSubmissionsClient()

    first = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    _commit_and_finalize(db_session, first)
    first_manifest_hash = db_session.scalar(
        select(SecFinancialParseRun.input_manifest_hash)
    )
    client.add_unrelated_filing()

    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    _commit_and_finalize(db_session, second)

    assert first.artifacts_created == 4
    assert second.artifacts_created == 0
    assert second.parse_runs_created == 0
    assert second.raw_facts_created == 0
    assert db_session.scalar(select(func.count()).select_from(SecFilingArtifact)) == 4
    assert db_session.scalar(select(func.count()).select_from(SecSubmissionSnapshot)) == 2
    assert db_session.scalar(select(func.count()).select_from(SecFinancialParseRun)) == 1
    assert db_session.scalar(
        select(func.count()).select_from(SecFinancialParseRunArtifact)
    ) == 3
    assert db_session.scalar(select(func.count()).select_from(SecRawXbrlFact)) == 3
    assert db_session.scalar(select(SecFinancialParseRun.input_manifest_hash)) == (
        first_manifest_hash
    )
    assert db_session.scalar(select(func.count()).select_from(MetricFact)) == 0


def test_concurrent_ingestion_serializes_snapshot_and_filing_lineage(
    tmp_path: Path,
) -> None:
    import os
    import subprocess

    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings
    from test_support.database_isolation import (
        build_isolated_database_url,
        create_test_schema,
        drop_test_schema,
        new_test_schema_name,
    )

    configured_url = make_url(settings.SQLALCHEMY_DATABASE_URI)
    base_database_url = configured_url.set(
        query={
            key: value
            for key, value in configured_url.query.items()
            if key != "options"
        }
    ).render_as_string(hide_password=False)
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(base_database_url, schema_name)
    create_test_schema(base_database_url, schema_name)
    backend_dir = Path(__file__).resolve().parents[2]
    migration = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=backend_dir,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    if migration.returncode != 0:
        drop_test_schema(base_database_url, schema_name)
        raise AssertionError(f"{migration.stdout}\n{migration.stderr}")
    concurrent_engine = create_engine(database_url, pool_pre_ping=True)
    ConcurrentSession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=concurrent_engine,
    )

    cik = "0000000998"
    accession = "0000000998-26-000001"
    accession_raw = accession.replace("-", "")
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    archive_root = f"https://www.sec.gov/Archives/edgar/data/998/{accession_raw}"
    index_url = f"{archive_root}/index.json"
    primary_url = f"{archive_root}/aapl-20260627.htm"
    schema_url = f"{archive_root}/aapl-20260627.xsd"
    submissions = json.loads(_submissions_payload())
    submissions["cik"] = "998"
    submissions["filings"]["recent"]["accessionNumber"][0] = accession
    index = json.loads(_index_payload())
    index["directory"]["name"] = f"/Archives/edgar/data/998/{accession_raw}"

    class ConcurrentClient:
        def __init__(self) -> None:
            self.responses = {
                submissions_url: json.dumps(submissions).encode(),
                index_url: json.dumps(index).encode(),
                primary_url: INLINE_XBRL,
                schema_url: SCHEMA_XBRL,
            }

        def get(self, url: str) -> bytes:
            return self.responses[url]

        def get_revalidated(self, url: str) -> bytes:
            return self.get(url)

    setup = ConcurrentSession()
    stock = Stock(
        ticker="CONCURSEC",
        exchange="US",
        company_name="Concurrent SEC Fixture",
    )
    setup.add(stock)
    setup.flush()
    stock_id = stock.id
    register_reviewed_sec_identity(
        setup,
        stock_id=stock_id,
        cik=cik,
        effective_from=date(1980, 1, 1),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Concurrent SEC ingestion fixture.",
    )
    setup.commit()
    setup.close()

    session_a = ConcurrentSession()
    b_done = threading.Event()
    b_errors: list[Exception] = []
    b_reports = []

    def run_b() -> None:
        session_b = ConcurrentSession()
        try:
            b_reports.append(
                ingest_latest_financial_filings(
                    session_b,
                    stock_id=stock_id,
                    client=ConcurrentClient(),
                    storage_root=tmp_path,
                    max_filings=1,
                    now=datetime(2026, 8, 27, 12, 6, tzinfo=timezone.utc),
                )
            )
            session_b.commit()
        except Exception as exc:  # pragma: no cover - failure diagnostic
            session_b.rollback()
            b_errors.append(exc)
        finally:
            session_b.close()
            b_done.set()

    thread = threading.Thread(target=run_b)
    try:
        report_a = ingest_latest_financial_filings(
            session_a,
            stock_id=stock_id,
            client=ConcurrentClient(),
            storage_root=tmp_path,
            max_filings=1,
            now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
        )
        thread.start()
        assert not b_done.wait(timeout=1.0), (
            "concurrent ingestion ran while the stock advisory lock was held"
        )
        session_a.commit()
        assert b_done.wait(timeout=10.0), (
            "concurrent ingestion did not finish after the advisory lock released"
        )
        thread.join(timeout=10.0)
        assert len(b_errors) == 1
        assert isinstance(b_errors[0], SecFinancialIngestionError)
        assert "pending finalization" in str(b_errors[0])
        assert report_a.artifacts_created == 4
        assert b_reports == []

        seal = ConcurrentSession()
        try:
            finalize_sec_financial_ingestion_operation(
                seal,
                operation_id=report_a.operation_id,
            )
            seal.commit()
        finally:
            seal.close()

        retry = ConcurrentSession()
        try:
            retry_report = ingest_latest_financial_filings(
                retry,
                stock_id=stock_id,
                client=ConcurrentClient(),
                storage_root=tmp_path,
                max_filings=1,
                now=datetime(2026, 8, 27, 12, 7, tzinfo=timezone.utc),
            )
            retry.commit()
            assert retry_report.artifacts_created == 0
            assert retry_report.parse_runs_created == 0
        finally:
            retry.close()

        verify = ConcurrentSession()
        try:
            identity_id = verify.scalar(
                select(SecIssuerIdentity.id).where(
                    SecIssuerIdentity.stock_id == stock_id
                )
            )
            filing_id = verify.scalar(
                select(SecFinancialFiling.id).where(
                    SecFinancialFiling.issuer_identity_id == identity_id
                )
            )
            assert verify.scalar(
                select(func.count()).select_from(SecSubmissionSnapshot).where(
                    SecSubmissionSnapshot.issuer_identity_id == identity_id
                )
            ) == 1
            assert verify.scalar(
                select(func.count()).select_from(SecFilingArtifact).where(
                    SecFilingArtifact.filing_id == filing_id
                )
            ) == 4
            assert verify.scalar(
                select(func.count()).select_from(SecFinancialParseRun).where(
                    SecFinancialParseRun.filing_id == filing_id
                )
            ) == 1
        finally:
            verify.close()
    finally:
        if thread.is_alive():
            session_a.rollback()
            thread.join(timeout=10.0)
        else:
            session_a.rollback()
        session_a.close()
        concurrent_engine.dispose()
        drop_test_schema(base_database_url, schema_name)


def test_legacy_submission_coupled_lineage_does_not_gain_a_third_duplicate(
    committed_db_session,
    tmp_path: Path,
) -> None:
    db_session = committed_db_session
    stock = _seed_legacy_submission_coupled_lineage(
        db_session, tmp_path, finalize_legacy=True
    )
    client = ChangingSubmissionsClient()
    client.add_unrelated_filing()

    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    _commit_and_finalize(db_session, report)

    assert report.artifacts_created == 0
    assert report.parse_runs_created == 0
    assert report.raw_facts_created == 0
    assert db_session.scalar(select(func.count()).select_from(SecFilingArtifact)) == 5
    assert db_session.scalar(select(func.count()).select_from(SecFinancialParseRun)) == 1
    assert db_session.scalar(select(func.count()).select_from(SecRawXbrlFact)) == 1
    assert db_session.scalar(select(func.count()).select_from(SecSubmissionSnapshot)) == 2


def test_noncanonical_legacy_extra_is_not_accepted_as_submissions_lineage(
    db_session,
    tmp_path: Path,
) -> None:
    stock = _seed_legacy_submission_coupled_lineage(
        db_session,
        tmp_path,
        canonical_submission_metadata=False,
    )

    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=ChangingSubmissionsClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )

    assert report.artifacts_created == 4
    assert report.parse_runs_created == 1


def test_corrupt_legacy_manifest_hash_is_not_semantically_reused(
    db_session,
    tmp_path: Path,
) -> None:
    stock = _seed_legacy_submission_coupled_lineage(
        db_session,
        tmp_path,
        canonical_manifest_hash=False,
    )

    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=ChangingSubmissionsClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )

    assert report.artifacts_created == 4
    assert report.parse_runs_created == 1


def test_run_without_legacy_submissions_link_is_not_semantically_reused(
    db_session,
    tmp_path: Path,
) -> None:
    stock = _seed_legacy_submission_coupled_lineage(
        db_session,
        tmp_path,
        run_includes_submissions=False,
    )

    report = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=ChangingSubmissionsClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )

    assert report.artifacts_created == 0
    assert report.parse_runs_created == 1
    assert report.raw_facts_created == 3


def test_accession_input_change_appends_new_observation_and_parse_run(
    db_session,
    tmp_path: Path,
) -> None:
    stock = Stock(ticker="CORRECT", exchange="US", company_name="Correction Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Accession correction fixture.",
    )
    db_session.commit()
    client = ChangingSubmissionsClient()

    ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()
    client.correct_accession_content()
    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert second.artifacts_created == 4
    assert second.parse_runs_created == 1
    assert second.raw_facts_created == 3
    assert db_session.scalar(select(func.count()).select_from(SecSubmissionSnapshot)) == 1
    assert db_session.scalar(select(func.count()).select_from(SecFilingArtifact)) == 8
    assert db_session.scalar(select(func.count()).select_from(SecFinancialParseRun)) == 2
    assert db_session.scalar(select(func.count()).select_from(SecRawXbrlFact)) == 6
    assert len(
        set(db_session.scalars(select(SecFinancialParseRun.input_manifest_hash)).all())
    ) == 2
    assert set(
        db_session.scalars(
            select(SecRawXbrlFact.raw_value).where(
                SecRawXbrlFact.concept
                == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
            )
        ).all()
    ) == {"94,000", "95,000"}
    assert db_session.scalar(select(func.count()).select_from(MetricFact)) == 0


def test_same_index_retained_byte_correction_appends_new_lineage(
    db_session,
    tmp_path: Path,
) -> None:
    stock = Stock(ticker="BYTEFIX", exchange="US", company_name="Byte Fix Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Retained-byte correction fixture.",
    )
    db_session.commit()
    client = ChangingSubmissionsClient()
    unchanged_index_sha = hashlib.sha256(client.responses[INDEX_URL]).hexdigest()

    first = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()
    client.correct_retained_bytes_without_index_change()
    second = ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert hashlib.sha256(client.responses[INDEX_URL]).hexdigest() == unchanged_index_sha
    assert first.artifacts_created == 4
    assert second.artifacts_created == 4
    assert second.parse_runs_created == 1
    assert second.raw_facts_created == 3
    assert PRIMARY_URL in client.revalidated_calls
    assert INDEX_URL in client.revalidated_calls
    assert db_session.scalar(select(func.count()).select_from(SecFilingArtifact)) == 8
    assert db_session.scalar(select(func.count()).select_from(SecFinancialParseRun)) == 2
    assert db_session.scalar(select(func.count()).select_from(SecRawXbrlFact)) == 6
    assert len(
        set(db_session.scalars(select(SecFinancialParseRun.input_manifest_hash)).all())
    ) == 2
    assert set(
        db_session.scalars(
            select(SecRawXbrlFact.raw_value).where(
                SecRawXbrlFact.concept
                == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
            )
        ).all()
    ) == {"94,000", "95,000"}
    assert db_session.scalar(select(func.count()).select_from(MetricFact)) == 0


def test_submission_snapshot_storage_corruption_fails_closed(
    db_session,
    tmp_path: Path,
) -> None:
    stock = Stock(ticker="SNAPBAD", exchange="US", company_name="Snapshot Fixture")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Snapshot integrity fixture.",
    )
    db_session.commit()
    client = ChangingSubmissionsClient()
    ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
    )
    db_session.commit()
    snapshot = db_session.scalar(select(SecSubmissionSnapshot))
    assert snapshot is not None
    (tmp_path / snapshot.storage_key).write_bytes(b"corrupt snapshot")

    with pytest.raises(SecFinancialIntegrityError, match="snapshot.*mismatch"):
        ingest_latest_financial_filings(
            db_session,
            stock_id=stock.id,
            client=client,
            storage_root=tmp_path,
            max_filings=1,
            now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
        )


def test_unavailable_required_artifact_retries_without_mutating_lineage(
    committed_db_session, tmp_path: Path
) -> None:
    db_session = committed_db_session
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
    _commit_and_finalize(db_session, first)
    first_run = db_session.scalar(select(SecFinancialParseRun))
    assert first_run.status == "failed"
    assert first_run.error_code == "required_artifact_unavailable"
    assert first.raw_facts_created == 0
    assert earliest_replayable_sec_financial_evidence_at(
        db_session, stock_id=stock.id, storage_root=tmp_path
    ) is None
    assert [
        (item.accession_no, item.error_code)
        for item in select_sec_financial_failures_as_of(
            db_session,
            stock_id=stock.id,
            cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
            storage_root=tmp_path,
        )
    ] == [(ACCESSION, "required_artifact_unavailable")]
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
    _commit_and_finalize(db_session, second)
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
    assert second.artifacts_created == 4
    assert second.raw_facts_created == 3
    replayable_at = earliest_replayable_sec_financial_evidence_at(
        db_session, stock_id=stock.id, storage_root=tmp_path
    )
    assert replayable_at is not None
    assert select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=replayable_at - timedelta(microseconds=1),
        storage_root=tmp_path,
    ) == []
    assert select_sec_financial_evidence_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=replayable_at,
        storage_root=tmp_path,
    )
    assert select_sec_financial_failures_as_of(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
        storage_root=tmp_path,
    ) == []


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


def test_identity_transition_cannot_backdate_persisted_financial_lineage(
    db_session,
    tmp_path: Path,
) -> None:
    stock = Stock(ticker="IDBACK", exchange="US", company_name="Identity Backfill")
    db_session.add(stock)
    db_session.flush()
    original = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(1980, 12, 12),
        known_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        review_reason="Identity backfill fixture.",
    )
    db_session.commit()
    ingest_latest_financial_filings(
        db_session,
        stock_id=stock.id,
        client=FakeEdgarClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 27, 12, 10, tzinfo=timezone.utc),
    )
    db_session.commit()

    with pytest.raises(
        SecFinancialIngestionError,
        match="transition predates persisted SEC lineage",
    ):
        retire_sec_identity(
            db_session,
            identity_id=original.id,
            known_at=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
            review_reason="Invalid backdated retirement.",
        )
    with pytest.raises(
        SecFinancialIngestionError,
        match="transition predates persisted SEC lineage",
    ):
        register_reviewed_sec_identity(
            db_session,
            stock_id=stock.id,
            cik=CIK,
            effective_from=date(1980, 12, 12),
            known_at=datetime(2026, 8, 27, 12, 5, tzinfo=timezone.utc),
            review_reason="Invalid backdated supersession.",
            supersedes_identity_id=original.id,
        )
    assert db_session.scalar(
        select(func.count()).select_from(SecIssuerIdentity).where(
            SecIssuerIdentity.supersedes_identity_id == original.id
        )
    ) == 0
