"""Tests for ``ensure_filing_infotable_doc`` (issue #43).

The helper makes the standalone ``ingest_holdings`` admin job self-sufficient:
when a Filing13F has no infotable XML on disk yet, the job calls this helper
to resolve URLs and fetch primary_doc + infotable, then proceeds to parse.
Before this helper existed, ``ingest_holdings`` silently skipped every filing
without ``raw_infotable_doc_id`` set — see the prod incident on 2026-05-19
(61 filings indexed for 2025-Q4, 0 holdings ingested).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.services import edgar_ingestion
from app.models.institutions import (
    Filing13F,
    InstitutionManager,
    RawSourceDocument,
)


class _RecordingClient:
    """Stand-in for EdgarClient. Records URLs and returns canned bytes."""

    def __init__(self, payloads: dict[str, bytes]) -> None:
        self._payloads = payloads
        self.requested_urls: list[str] = []

    def get(self, url: str) -> bytes:
        self.requested_urls.append(url)
        if url not in self._payloads:
            raise AssertionError(f"unexpected URL requested: {url}")
        return self._payloads[url]

    def __enter__(self) -> "_RecordingClient":
        return self

    def __exit__(self, *args) -> None:
        return None

    def close(self) -> None:
        return None


def _make_manager(db, *, name="Test Manager", cik="0001234567") -> InstitutionManager:
    mgr = InstitutionManager(
        canonical_name=name,
        cik=cik,
        match_status="confirmed",
        status="active",
    )
    db.add(mgr)
    db.flush()
    return mgr


def _make_filing(db, manager: InstitutionManager, *, accession="0001234567-26-000001") -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        form_type="13F-HR",
        filed_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        period_of_report=date(2025, 12, 31),
        is_latest_for_period=True,
        is_active_for_manager_period=True,
    )
    db.add(filing)
    db.flush()
    return filing


def test_returns_existing_doc_when_already_linked(db_session, tmp_path, monkeypatch):
    """Idempotent: if raw_infotable_doc_id is already set and the row is loadable,
    no network call is issued."""
    monkeypatch.setattr(edgar_ingestion.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path))

    mgr = _make_manager(db_session)
    filing = _make_filing(db_session, mgr)

    existing_doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable_xml",
        cik=mgr.cik,
        accession_no=filing.accession_no,
        source_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/infotable.xml",
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        raw_sha256="cached",
        body_path=str(tmp_path / "cached.xml"),
        parse_status="parsed",
    )
    db_session.add(existing_doc)
    db_session.flush()
    filing.raw_infotable_doc_id = existing_doc.id
    db_session.flush()

    # If the helper attempts to construct an EdgarClient at all, the test fails.
    def _fail_client(*args, **kwargs):
        raise AssertionError("EdgarClient should not be instantiated on the cache hit path")

    monkeypatch.setattr(edgar_ingestion, "EdgarClient", _fail_client)

    result = edgar_ingestion.ensure_filing_infotable_doc(db_session, filing)
    assert result is existing_doc


def test_fetches_and_links_when_missing(db_session, tmp_path, monkeypatch):
    """When raw_infotable_doc_id is None, the helper resolves URLs, fetches
    primary_doc + infotable, and sets both IDs on the filing."""
    monkeypatch.setattr(edgar_ingestion.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(edgar_ingestion.settings, "EDGAR_FETCH_MODE", "live")

    mgr = _make_manager(db_session)
    filing = _make_filing(db_session, mgr)

    primary_url = "https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/primary_doc.xml"
    infotable_url = "https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/infotable.xml"
    primary_body = b"<?xml version='1.0'?><primary/>"
    infotable_body = b"<?xml version='1.0'?><infotable/>"

    monkeypatch.setattr(
        edgar_ingestion,
        "_resolve_infotable_url",
        lambda client, cik, acc_raw, acc_no: infotable_url,
    )
    monkeypatch.setattr(
        edgar_ingestion,
        "_resolve_primary_doc_url",
        lambda client, cik, acc_raw, acc_no: primary_url,
    )

    client = _RecordingClient({primary_url: primary_body, infotable_url: infotable_body})
    monkeypatch.setattr(edgar_ingestion, "EdgarClient", lambda: client)

    result = edgar_ingestion.ensure_filing_infotable_doc(db_session, filing)

    assert result is not None
    assert result.document_type == "infotable_xml"
    assert filing.raw_infotable_doc_id == result.id
    assert filing.raw_primary_doc_id is not None
    # Both URLs were requested exactly once.
    assert sorted(client.requested_urls) == sorted([primary_url, infotable_url])
    # Both RawSourceDocument rows were written.
    primary_doc = db_session.query(RawSourceDocument).get(filing.raw_primary_doc_id)
    assert primary_doc.document_type == "primary_doc_xml"
    assert primary_doc.source_url == primary_url


def test_returns_none_when_manager_has_no_cik(db_session, tmp_path, monkeypatch):
    """A candidate manager without a confirmed CIK cannot have its filings
    resolved on EDGAR. Helper returns None instead of raising — the caller
    decides whether to skip or report."""
    monkeypatch.setattr(edgar_ingestion.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path))

    mgr = InstitutionManager(
        canonical_name="Candidate Without CIK",
        cik=None,
        match_status="needs_review",
        status="candidate",
    )
    db_session.add(mgr)
    db_session.flush()
    filing = _make_filing(db_session, mgr, accession="0009999999-26-000001")

    def _fail_client(*args, **kwargs):
        raise AssertionError("should short-circuit before constructing EdgarClient")

    monkeypatch.setattr(edgar_ingestion, "EdgarClient", _fail_client)

    result = edgar_ingestion.ensure_filing_infotable_doc(db_session, filing)
    assert result is None
    assert filing.raw_infotable_doc_id is None
