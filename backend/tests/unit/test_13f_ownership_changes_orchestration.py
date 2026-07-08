"""T2: the compute_ownership_changes job orchestration (F2).

Verifies the standalone job branch loops all active HR/HR-A managers for a
quarter and materializes the ownership_changes read model — the production
caller that MVP2-02 never wired.
"""
from datetime import date

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    OwnershipChange13F,
    ParseRun13F,
)
from app.models.stocks import Stock
from app.services.thirteenf_admin_dashboard import _JOB_LOCK_BUILDERS, execute_job_payload

_CIK = iter(range(9200001, 9200999))


def _mk_manager(db):
    cik = str(next(_CIK)).zfill(10)
    m = InstitutionManager(
        canonical_name=f"M{cik}", legal_name=f"M{cik}", cik=cik,
        status="active", match_status="confirmed",
    )
    db.add(m); db.flush()
    return m


def _mk_stock(db, ticker):
    s = Stock(ticker=ticker, exchange="NASDAQ", company_name=ticker)
    db.add(s); db.flush()
    return s


def _mk_filing(db, m, quarter, acc):
    qe = {1: date(int(quarter[:4]), 3, 31), 4: date(int(quarter[:4]), 12, 31)}[int(quarter[-1])]
    f = Filing13F(
        manager_id=m.id, accession_no=acc, accession_number=acc, cik=m.cik,
        period_of_report=qe, filed_at=qe, filing_date=qe, form_type="13F-HR",
        report_type="holdings_report", coverage_completeness="complete",
        coverage_type="normal", report_quarter=quarter, quarter_end_date=qe,
        official_filing_deadline=qe, is_active_for_manager_period=True,
        parse_status="succeeded", amendment_status="no_amendments_seen",
    )
    db.add(f); db.flush()
    return f


def _mk_run(db, f):
    r = ParseRun13F(accession_number=f.accession_number, parser_version="t",
                    status="succeeded", is_current=True)
    db.add(r); db.flush()
    return r


def _mk_holding(db, f, r, s, cusip, shares, value):
    h = Holding13F(
        filing_id=f.id, parse_run_id=r.id, manager_id=f.manager_id,
        accession_number=f.accession_number, report_quarter=f.report_quarter,
        quarter_end_date=f.quarter_end_date, row_fingerprint=f.accession_number + cusip,
        holding_row_fingerprint=f.accession_number + cusip + "v1", cusip=cusip,
        issuer_name=s.company_name, value_thousands=value // 1000, value_usd=value,
        shares=shares, ssh_prnamt=shares, ssh_prnamt_type="SH",
        holding_attribution_status="direct", stock_id=s.id,
        cusip_mapping_status="linked", portfolio_weight_pct=0.1,
    )
    db.add(h); db.flush()
    return h


def test_compute_ownership_changes_job_materializes_all_active_managers(db_session):
    held = _mk_stock(db_session, "AAA")
    new = _mk_stock(db_session, "BBB")
    for i in range(2):
        m = _mk_manager(db_session)
        prev = _mk_filing(db_session, m, "2025-Q4", f"P{i}-25-000001")
        cur = _mk_filing(db_session, m, "2026-Q1", f"C{i}-26-000001")
        pr = _mk_run(db_session, prev)
        cr = _mk_run(db_session, cur)
        _mk_holding(db_session, prev, pr, held, "111111111", 100, 1000)
        _mk_holding(db_session, cur, cr, held, "111111111", 150, 1500)   # increased
        _mk_holding(db_session, cur, cr, new, "222222222", 50, 500)      # new_position

    summary = execute_job_payload(db_session, "compute_ownership_changes", {"quarter": "2026-Q1"})

    assert summary["status"] == "succeeded"
    assert summary["managers_processed"] == 2
    assert summary["failure_count"] == 0
    assert summary["rows_created"] >= 4  # each manager: an increased + a new position
    # Both managers now have computed changes for the quarter.
    managers_with_changes = (
        db_session.query(OwnershipChange13F.manager_id)
        .filter(OwnershipChange13F.report_quarter == "2026-Q1")
        .distinct()
        .count()
    )
    assert managers_with_changes == 2


def test_compute_ownership_changes_only_touches_target_quarter(db_session):
    held = _mk_stock(db_session, "CCC")
    m = _mk_manager(db_session)
    prev = _mk_filing(db_session, m, "2025-Q4", "Q-25-000001")
    cur = _mk_filing(db_session, m, "2026-Q1", "Q-26-000001")
    pr = _mk_run(db_session, prev)
    cr = _mk_run(db_session, cur)
    _mk_holding(db_session, prev, pr, held, "111111111", 100, 1000)
    _mk_holding(db_session, cur, cr, held, "111111111", 150, 1500)

    execute_job_payload(db_session, "compute_ownership_changes", {"quarter": "2026-Q1"})

    q1 = db_session.query(OwnershipChange13F).filter_by(report_quarter="2026-Q1").count()
    q4 = db_session.query(OwnershipChange13F).filter_by(report_quarter="2025-Q4").count()
    assert q1 >= 1
    assert q4 == 0  # prior quarter is a data source, not recomputed here


def test_compute_ownership_changes_lock_key_is_quarter_scoped():
    assert (
        _JOB_LOCK_BUILDERS["compute_ownership_changes"]({"quarter": "2026-Q1"})
        == "compute_ownership_changes:2026-Q1"
    )
