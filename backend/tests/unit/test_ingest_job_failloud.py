"""Tests for the external-review remediation of `_execute_ingest_job`
(review R1-P1 / R4): programming errors must fail the stage loudly instead
of being demoted to a per-filing "failure" or swallowed by Phase 2's broad
except (the failure mode that let the route_period import bug reach prod).
"""
from __future__ import annotations

from datetime import date

import pytest

from app.services.thirteenf_admin_dashboard import (
    _is_programming_error,
    execute_job_payload,
)
from app.models.institutions import Filing13F, InstitutionManager

# A routing summary shaped like backfill_period_routing's real return.
_CLEAN_ROUTING = {
    "period_changed": 0, "quarter_end_added": 0, "report_quarter_added": 0,
    "needs_review": 0, "needs_review_routed": 0,
    "needs_review_unrouted": 0, "failed": 0,
}


def _make_manager(db, *, name="Test Manager", cik="0001234567") -> InstitutionManager:
    mgr = InstitutionManager(
        cik=cik,
        legal_name=name,
        display_name=name,
        name_normalized=name.lower(),
        match_status="confirmed",
        is_superinvestor=False,
    )
    db.add(mgr)
    db.flush()
    return mgr


def _make_filing(
    db, manager, *,
    accession="0001234567-26-000001",
    form_type="13F-HR",
    quarter_end_date=None,
) -> Filing13F:
    # A freshly-indexed 2025-Q4 filing, exactly as `ingest_quarter_index` writes
    # it: `period_of_report` is a PROXY equal to `filed_at` (see
    # `_accession_period_of_report`) and `report_quarter` stays NULL until
    # `backfill_period_routing` runs. `ingest_holdings("2025-Q4")` finds it
    # through the filed-quarter arm — 13Fs for 2025-Q4 are filed in 2026-Q1.
    #
    # The old fixture paired `period_of_report=date(2025, 11, 15)` with
    # `filed_at=date(2026, 2, 14)` so the pre-fix period-window query would match
    # it. No code path produces that row.
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        form_type=form_type,
        filed_at=date(2026, 2, 14),
        period_of_report=date(2026, 2, 14),
        quarter_end_date=quarter_end_date,
        is_latest_for_period=True,
    )
    db.add(filing)
    db.flush()
    return filing


# ---------- _is_programming_error -------------------------------------------

def test_is_programming_error_classification():
    assert _is_programming_error(ImportError("x")) is True
    assert _is_programming_error(ModuleNotFoundError("x")) is True  # ImportError subclass
    assert _is_programming_error(NameError("x")) is True
    assert _is_programming_error(AttributeError("x")) is True
    # Recoverable per-document / network failures are NOT programming errors.
    assert _is_programming_error(RuntimeError("EDGAR 404")) is False
    assert _is_programming_error(OSError("connection reset")) is False
    assert _is_programming_error(ValueError("bad period")) is False


# ---------- ingest_holdings fail-loud behavior ------------------------------

def test_ingest_holdings_phase2_failloud_on_import_error(db_session, monkeypatch):
    """A programming error escaping backfill_period_routing must propagate
    and fail the stage — NOT be swallowed into a zero-work 'success'."""
    mgr = _make_manager(db_session)
    _make_filing(db_session, mgr)

    # Phase 1: pretend the XML is on disk (return a truthy doc).
    monkeypatch.setattr(
        "app.services.edgar_ingestion.ensure_filing_infotable_doc",
        lambda session, filing: object(),
    )

    def _boom(session, *, filings):
        raise ImportError("cannot import name 'route_period'")

    monkeypatch.setattr("app.services.edgar_ingestion.backfill_period_routing", _boom)

    with pytest.raises(ImportError):
        execute_job_payload(db_session, "ingest_holdings", {"quarter": "2025-Q4"})


def test_ingest_holdings_phase1_failloud_on_programming_error(db_session, monkeypatch):
    """An AttributeError inside the Phase 1 per-filing loop is a real bug —
    it must propagate, not be recorded as a tolerated per-filing failure."""
    mgr = _make_manager(db_session)
    _make_filing(db_session, mgr)

    def _boom(session, filing):
        raise AttributeError("'NoneType' object has no attribute 'cik'")

    monkeypatch.setattr("app.services.edgar_ingestion.ensure_filing_infotable_doc", _boom)

    with pytest.raises(AttributeError):
        execute_job_payload(db_session, "ingest_holdings", {"quarter": "2025-Q4"})


def test_ingest_holdings_tolerates_per_filing_data_error(db_session, monkeypatch):
    """A non-programming error (e.g. an EDGAR 404) for one filing is recorded
    as a per-filing failure and the stage finishes partial_success — one bad
    filing does not abort the batch."""
    mgr = _make_manager(db_session)
    _make_filing(db_session, mgr)

    def _data_error(session, filing):
        raise RuntimeError("EDGAR 404 for filing")

    monkeypatch.setattr("app.services.edgar_ingestion.ensure_filing_infotable_doc", _data_error)
    monkeypatch.setattr(
        "app.services.edgar_ingestion.backfill_period_routing",
        lambda session, *, filings: dict(_CLEAN_ROUTING),
    )

    result = execute_job_payload(db_session, "ingest_holdings", {"quarter": "2025-Q4"})
    assert result["filings_failed"] == 1
    assert result["status"] == "partial_success"


def test_bulk_ingest_routes_notice_through_primary_doc_without_infotable(
    db_session,
    monkeypatch,
):
    mgr = _make_manager(db_session)
    notice = _make_filing(db_session, mgr, form_type="13F-NT")
    notice_calls = []

    def _notice_detail(session, payload):
        notice_calls.append(payload)
        notice.report_quarter = "2025-Q4"
        notice.quarter_end_date = date(2025, 12, 31)
        notice.period_of_report = date(2025, 12, 31)
        notice.parse_status = "succeeded"
        session.add(notice)
        session.commit()
        return {
            "filing_id": notice.id,
            "accession_number": notice.accession_no,
            "report_quarter": "2025-Q4",
            "status": "succeeded",
        }

    monkeypatch.setattr(
        "app.services.thirteenf_filing_detail.ingest_accession_filing_detail",
        _notice_detail,
    )

    def _must_not_fetch_infotable(*_args, **_kwargs):
        raise AssertionError("notice filings have no information table")

    monkeypatch.setattr(
        "app.services.edgar_ingestion.ensure_filing_infotable_doc",
        _must_not_fetch_infotable,
    )

    result = execute_job_payload(db_session, "ingest_holdings", {"quarter": "2025-Q4"})

    assert result["notice_filings_processed"] == 1
    assert result["filings_failed"] == 0
    assert notice_calls[0]["form_type"] == "13F-NT"
    assert result["filings_for_requested_quarter"] == 1


def test_ingest_holdings_routing_needs_review_marks_partial_success(db_session, monkeypatch):
    """Degraded period routing (needs_review / failed outcomes) is surfaced
    as partial_success rather than a silent clean success."""
    mgr = _make_manager(db_session)
    _make_filing(db_session, mgr)

    monkeypatch.setattr(
        "app.services.edgar_ingestion.ensure_filing_infotable_doc",
        lambda session, filing: object(),
    )
    monkeypatch.setattr(
        "app.services.edgar_ingestion.backfill_period_routing",
        lambda session, *, filings: {**_CLEAN_ROUTING, "needs_review": 1},
    )

    result = execute_job_payload(db_session, "ingest_holdings", {"quarter": "2025-Q4"})
    assert result["filings_routing_needs_review"] == 1
    assert result["status"] == "partial_success"


# ---------- Phase 4c amendment-safety guard (PR #56 third-review CRITICAL) ---

def test_phase4c_activates_solo_original_but_not_solo_amendment(db_session, monkeypatch):
    """Phase 4c heals is_active_for_manager_period for a solo plain 13F-HR,
    but must NOT auto-activate a solo 13F-HR/A — an amendment must go through
    the amendment policy, not this repair heuristic. The solo-group guard
    alone did not cover a *solo* amendment; the form_type=='13F-HR' guard
    closes it."""
    qend = date(2025, 12, 31)
    mgr_a = _make_manager(db_session, name="Original Mgr", cik="0001111111")
    hr = _make_filing(
        db_session, mgr_a, accession="0001111111-26-000001",
        form_type="13F-HR", quarter_end_date=qend,
    )
    mgr_b = _make_manager(db_session, name="Amendment Mgr", cik="0002222222")
    hra = _make_filing(
        db_session, mgr_b, accession="0002222222-26-000001",
        form_type="13F-HR/A", quarter_end_date=qend,
    )

    monkeypatch.setattr(
        "app.services.edgar_ingestion.ensure_filing_infotable_doc",
        lambda session, filing: object(),
    )
    monkeypatch.setattr(
        "app.services.edgar_ingestion.backfill_period_routing",
        lambda session, *, filings: dict(_CLEAN_ROUTING),
    )

    execute_job_payload(db_session, "ingest_holdings", {"quarter": "2025-Q4"})
    db_session.refresh(hr)
    db_session.refresh(hra)

    assert hr.is_active_for_manager_period is True, "solo 13F-HR should be activated"
    assert hra.is_active_for_manager_period is False, "solo 13F-HR/A must NOT be auto-activated"
