"""T4 — CLI ingest hygiene (F5 + F6).

The CLI `backfill` / `ingest-holdings` commands used to call the legacy
`ingest_filing_holdings`, which (F6) wrote `parse_run_id = NULL` holdings
invisible to the product query contract, and (F5) selected pending filings by a
*report-quarter* `period_of_report` window — silently skipping the newest report
quarter, whose freshly-indexed filings carry a proxy period (= filed_at) that
lands in the FOLLOWING calendar quarter until parsed.

These tests pin the fix: `pending_ingest_quarters` groups by the proxy period so
the newest quarter is reachable, and `ingest_pending_holdings` delegates every
pending quarter to the modern job path (never the legacy per-filing call).
"""
import itertools
from datetime import date

from app.models.institutions import (
    Filing13F,
    InstitutionManager,
    RawSourceDocument,
)
from app.services.edgar_ingestion import (
    pending_ingest_quarters,
    ingest_pending_holdings,
    next_quarter_label,
)

_SEQ = itertools.count(1)


def _infotable_doc(db_session) -> RawSourceDocument:
    n = next(_SEQ)
    doc = RawSourceDocument(
        source_system="edgar",
        document_type="13f_infotable",
        source_url=f"https://example.test/infotable-{n}.xml",
        body_path=f"/tmp/infotable-{n}.xml",
    )
    db_session.add(doc)
    db_session.flush()
    return doc


def _manager(db_session) -> InstitutionManager:
    n = next(_SEQ)
    mgr = InstitutionManager(
        cik=None,
        legal_name=f"CLI Mgr {n}",
        display_name=f"CLI Mgr {n}",
        name_normalized=f"cli mgr {n}",
        match_status="seeded",
        is_superinvestor=False,
    )
    db_session.add(mgr)
    db_session.flush()
    return mgr


def _filing(
    db_session,
    mgr,
    *,
    period_of_report: date,
    filed_at: date,
    ingested: bool,
) -> Filing13F:
    n = next(_SEQ)
    accession = f"CLI{n:016d}"
    filing = Filing13F(
        manager_id=mgr.id,
        accession_no=accession,
        accession_number=accession,
        form_type="13F-HR",
        period_of_report=period_of_report,
        filed_at=filed_at,
        # An un-ingested filing has no infotable doc yet; an ingested one does.
        raw_infotable_doc_id=_infotable_doc(db_session).id if ingested else None,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def test_pending_ingest_quarters_excludes_already_ingested(db_session):
    mgr = _manager(db_session)
    # ingested → has raw_infotable_doc_id → must NOT appear
    _filing(
        db_session, mgr,
        period_of_report=date(2025, 3, 31), filed_at=date(2025, 5, 10),
        ingested=True,
    )
    # un-ingested → proxy period == filed_at (2025-05) → 2025-Q2
    _filing(
        db_session, mgr,
        period_of_report=date(2025, 5, 12), filed_at=date(2025, 5, 12),
        ingested=False,
    )

    assert pending_ingest_quarters(db_session) == ["2025-Q2"]


def test_pending_ingest_quarters_covers_newest_report_quarter(db_session):
    """F5 regression: the newest report quarter's filings are filed the
    FOLLOWING quarter, so their proxy period (= filed_at) sits one quarter
    ahead. Grouping by the proxy period must still surface them — a
    report-quarter window would drop them entirely."""
    mgr = _manager(db_session)
    # Reports 2025-Q1 but was filed 2025-05 (2025-Q2). Un-ingested, so its
    # period_of_report is still the filed_at proxy.
    _filing(
        db_session, mgr,
        period_of_report=date(2025, 5, 14), filed_at=date(2025, 5, 14),
        ingested=False,
    )
    # A filing filed 2025-08 (2025-Q3).
    _filing(
        db_session, mgr,
        period_of_report=date(2025, 8, 14), filed_at=date(2025, 8, 14),
        ingested=False,
    )

    quarters = pending_ingest_quarters(db_session)
    # Both filing quarters present — the newest (2025-Q3) is NOT skipped.
    assert quarters == ["2025-Q2", "2025-Q3"]


def test_pending_ingest_quarters_deduplicates(db_session):
    mgr = _manager(db_session)
    for day in (5, 12, 20):
        _filing(
            db_session, mgr,
            period_of_report=date(2025, 5, day), filed_at=date(2025, 5, day),
            ingested=False,
        )
    assert pending_ingest_quarters(db_session) == ["2025-Q2"]


def test_ingest_pending_holdings_delegates_to_job_per_quarter(db_session):
    """F6 regression: ingest goes through the injected job callable (the real
    default is the ParseRun-backed `ingest_holdings` job) once per pending
    quarter — never the legacy per-filing path."""
    mgr = _manager(db_session)
    _filing(
        db_session, mgr,
        period_of_report=date(2025, 5, 14), filed_at=date(2025, 5, 14),
        ingested=False,
    )
    _filing(
        db_session, mgr,
        period_of_report=date(2025, 8, 14), filed_at=date(2025, 8, 14),
        ingested=False,
    )

    calls: list[str] = []

    def fake_ingest(quarter: str) -> dict:
        calls.append(quarter)
        return {"quarter": quarter, "filings_processed": 1}

    summaries = ingest_pending_holdings(db_session, ingest_fn=fake_ingest)

    assert calls == ["2025-Q2", "2025-Q3"]
    assert set(summaries) == {"2025-Q2", "2025-Q3"}
    assert summaries["2025-Q2"]["filings_processed"] == 1


def test_next_quarter_label_boundaries():
    assert next_quarter_label("2025-Q1") == "2025-Q2"
    assert next_quarter_label("2025-Q3") == "2025-Q4"
    assert next_quarter_label("2025-Q4") == "2026-Q1"
    assert next_quarter_label("2025-q2") == "2025-Q3"  # case-insensitive


def test_ingest_pending_holdings_bounds_to_requested_quarters(db_session):
    """Regression: `backfill --quarters N` must not reprocess ancient stuck
    quarters. `quarters=` restricts the ingest to the caller's scope, so a
    permanently-pending old filing (e.g. a CIK-less manager whose infotable can
    never be fetched) can't drag every historical quarter into every run."""
    mgr = _manager(db_session)
    # An ancient, forever-pending filing (simulates the CIK-less / stuck case).
    _filing(
        db_session, mgr,
        period_of_report=date(2020, 5, 14), filed_at=date(2020, 5, 14),
        ingested=False,
    )
    # A current-scope pending filing.
    _filing(
        db_session, mgr,
        period_of_report=date(2025, 8, 14), filed_at=date(2025, 8, 14),
        ingested=False,
    )

    calls: list[str] = []
    summaries = ingest_pending_holdings(
        db_session, quarters={"2025-Q3"}, ingest_fn=lambda q: calls.append(q) or {}
    )

    # Only the in-scope quarter is ingested; the ancient one is left alone.
    assert calls == ["2025-Q3"]
    assert set(summaries) == {"2025-Q3"}


def test_ingest_pending_holdings_bound_still_reaches_newest_report_quarter(db_session):
    """F5 must survive the bound: the newest report quarter's filings are filed
    the FOLLOWING calendar quarter, so `backfill` scopes to report quarters PLUS
    their next quarter. A 2025-Q1 report filed 2025-05 (proxy period 2025-Q2)
    must still be ingested when the scope is derived from report quarter
    2025-Q1."""
    mgr = _manager(db_session)
    _filing(
        db_session, mgr,
        period_of_report=date(2025, 5, 14), filed_at=date(2025, 5, 14),
        ingested=False,
    )

    report_quarters = ["2025-Q1"]
    scoped = set(report_quarters) | {next_quarter_label(q) for q in report_quarters}

    calls: list[str] = []
    ingest_pending_holdings(
        db_session, quarters=scoped, ingest_fn=lambda q: calls.append(q) or {}
    )

    assert calls == ["2025-Q2"]  # reached via the following filing quarter


def test_ingest_pending_holdings_isolates_quarter_failure(db_session):
    """Regression: a hard failure in one quarter must not abandon the others.
    The job path re-raises programming/hard errors; without isolation a single
    bad quarter would abort the whole backfill and skip every healthy one."""
    mgr = _manager(db_session)
    for month in (5, 8, 11):
        _filing(
            db_session, mgr,
            period_of_report=date(2025, month, 14), filed_at=date(2025, month, 14),
            ingested=False,
        )

    def flaky_ingest(quarter: str) -> dict:
        if quarter == "2025-Q3":
            raise RuntimeError("boom")
        return {"quarter": quarter, "ok": True}

    summaries = ingest_pending_holdings(db_session, ingest_fn=flaky_ingest)

    # All three quarters attempted; the failure recorded, the rest succeeded.
    assert set(summaries) == {"2025-Q2", "2025-Q3", "2025-Q4"}
    assert summaries["2025-Q3"] == {"error": "boom"}
    assert summaries["2025-Q2"]["ok"] is True
    assert summaries["2025-Q4"]["ok"] is True


def test_ingest_pending_holdings_noop_when_all_ingested(db_session):
    mgr = _manager(db_session)
    _filing(
        db_session, mgr,
        period_of_report=date(2025, 3, 31), filed_at=date(2025, 5, 10),
        ingested=True,
    )

    calls: list[str] = []
    summaries = ingest_pending_holdings(
        db_session, ingest_fn=lambda q: calls.append(q)
    )

    assert calls == []
    assert summaries == {}
