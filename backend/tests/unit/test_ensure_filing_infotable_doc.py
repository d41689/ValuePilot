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
from pathlib import Path

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


def _make_manager(db, *, name="Test Manager", cik: str | None = "0001234567") -> InstitutionManager:
    mgr = InstitutionManager(
        cik=cik,
        legal_name=name,
        display_name=name,
        name_normalized=name.lower(),
        match_status="confirmed" if cik else "seeded",
        is_superinvestor=False,
    )
    db.add(mgr)
    db.flush()
    return mgr


def _make_filing(db, manager: InstitutionManager, *, accession="0001234567-26-000001") -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        form_type="13F-HR",
        filed_at=date(2026, 1, 15),
        period_of_report=date(2025, 12, 31),
        is_latest_for_period=True,
    )
    db.add(filing)
    db.flush()
    return filing


def test_returns_existing_doc_when_already_linked_and_files_on_disk(db_session, tmp_path, monkeypatch):
    """Cache hit: both raw_infotable_doc_id AND raw_primary_doc_id are linked,
    AND both body files exist on disk. No network call is issued."""
    monkeypatch.setattr(edgar_ingestion.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path))

    mgr = _make_manager(db_session)
    filing = _make_filing(db_session, mgr)

    infotable_file = tmp_path / "infotable.xml"
    infotable_file.write_bytes(b"<infotable/>")
    primary_file = tmp_path / "primary.xml"
    primary_file.write_bytes(b"<primary/>")

    primary_doc = RawSourceDocument(
        source_system="edgar",
        document_type="primary_doc_xml",
        cik=mgr.cik,
        accession_no=filing.accession_no,
        source_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/primary_doc.xml",
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        raw_sha256="cached-primary",
        body_path=str(primary_file),
        parse_status="parsed",
    )
    infotable_doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable_xml",
        cik=mgr.cik,
        accession_no=filing.accession_no,
        source_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/infotable.xml",
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        raw_sha256="cached-info",
        body_path=str(infotable_file),
        parse_status="parsed",
    )
    db_session.add_all([primary_doc, infotable_doc])
    db_session.flush()
    filing.raw_primary_doc_id = primary_doc.id
    filing.raw_infotable_doc_id = infotable_doc.id
    db_session.flush()

    def _fail_client(*args, **kwargs):
        raise AssertionError("EdgarClient should not be instantiated on the cache hit path")

    monkeypatch.setattr(edgar_ingestion, "EdgarClient", _fail_client)

    result = edgar_ingestion.ensure_filing_infotable_doc(db_session, filing)
    assert result is infotable_doc


def test_self_heals_when_linked_but_file_missing_on_disk(db_session, tmp_path, monkeypatch):
    """When raw_infotable_doc_id is linked but the body file is gone (e.g. the
    storage volume was wiped by a misbehaving deploy), fall through to refetch
    rather than returning the stale row. Without this, repeated reconcile
    runs after a wipe leave the disk empty forever."""
    monkeypatch.setattr(edgar_ingestion.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(edgar_ingestion.settings, "EDGAR_FETCH_MODE", "live")

    mgr = _make_manager(db_session)
    filing = _make_filing(db_session, mgr)

    # DB row exists, body_path points to a missing file.
    stale_doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable_xml",
        cik=mgr.cik,
        accession_no=filing.accession_no,
        source_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/infotable.xml",
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        raw_sha256="stale-sha",
        body_path="/nonexistent/wiped.xml",
        parse_status="parsed",
    )
    db_session.add(stale_doc)
    db_session.flush()
    filing.raw_infotable_doc_id = stale_doc.id
    db_session.flush()

    primary_url = "https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/primary_doc.xml"
    infotable_url = "https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/infotable.xml"
    fresh_primary = b"<?xml version='1.0'?><primary/>"
    fresh_infotable = b"<?xml version='1.0'?><infotable/>"

    monkeypatch.setattr(edgar_ingestion, "_resolve_infotable_url", lambda *a, **k: infotable_url)
    monkeypatch.setattr(edgar_ingestion, "_resolve_primary_doc_url", lambda *a, **k: primary_url)

    client = _RecordingClient({primary_url: fresh_primary, infotable_url: fresh_infotable})
    monkeypatch.setattr(edgar_ingestion, "EdgarClient", lambda: client)

    result = edgar_ingestion.ensure_filing_infotable_doc(db_session, filing)

    assert result is not None
    assert sorted(client.requested_urls) == sorted([primary_url, infotable_url])
    # Body now exists on disk under the EDGAR_RAW_STORAGE_DIR.
    assert Path(result.body_path).exists()


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

    mgr = _make_manager(db_session, name="Candidate Without CIK", cik=None)
    filing = _make_filing(db_session, mgr, accession="0009999999-26-000001")

    def _fail_client(*args, **kwargs):
        raise AssertionError("should short-circuit before constructing EdgarClient")

    monkeypatch.setattr(edgar_ingestion, "EdgarClient", _fail_client)

    result = edgar_ingestion.ensure_filing_infotable_doc(db_session, filing)
    assert result is None
    assert filing.raw_infotable_doc_id is None
