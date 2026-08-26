"""A reparse must not replace a verified run with a value-inconsistent one.

`_do_ingest_holdings` writes `computed_total_value_thousands = sum(this run)` and
makes the run current. `compute_portfolio_weight` prefers that computed total as
its denominator. So a reparse that produces a valid-but-partial InfoTable — one
Apple row for 8M where the filer declared 17M — silently replaced the correct
denominator, and Apple's weight jumped from 47% to 100%. Every job still
succeeded.

A reparse only switches the current ParseRun (`old_current_run_id is not None`).
A first ingest never does, so it is never gated — a genuinely non-compliant filer
still gets its one and only run.
"""
from datetime import date, datetime, timezone

import pytest

from app.models.institutions import Filing13F, InstitutionManager, ParseRun13F
from app.services.thirteenf_holdings_ingest import (
    ingest_holdings_for_filing,
    reparse_accession,
)


def _infotable(*rows: tuple[str, str, int, int]) -> bytes:
    body = "".join(
        f"""<infoTable><nameOfIssuer>{name}</nameOfIssuer><cusip>{cusip}</cusip>
        <value>{value}</value><shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt>
        <sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
        <investmentDiscretion>SOLE</investmentDiscretion>
        <votingAuthority><Sole>{shares}</Sole><Shared>0</Shared><None>0</None></votingAuthority>
        </infoTable>"""
        for name, cusip, value, shares in rows
    )
    return (
        '<?xml version="1.0"?><informationTable '
        'xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
        f"{body}</informationTable>"
    ).encode()


TWO_ROWS = _infotable(
    ("APPLE INC", "037833100", 8_000_000, 50_000),
    ("MICROSOFT CORP", "594918104", 9_000_000, 20_000),
)
ONE_ROW = _infotable(("APPLE INC", "037833100", 8_000_000, 50_000))
EMPTY_PORTFOLIO_SENTINEL = b"""<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable><nameOfIssuer>NONE</nameOfIssuer><titleOfClass>NONE</titleOfClass>
  <cusip>000000000</cusip><value>0</value><shrsOrPrnAmt>
  <sshPrnamt>0</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  <investmentDiscretion>SOLE</investmentDiscretion><votingAuthority>
  <Sole>0</Sole><Shared>0</Shared><None>0</None></votingAuthority></infoTable>
</informationTable>"""


@pytest.fixture
def filing(db_session):
    m = InstitutionManager(
        cik="9999999995", legal_name="Repro", name_normalized="repro-gate",
        match_status="confirmed",
    )
    db_session.add(m)
    db_session.flush()
    f = Filing13F(
        manager_id=m.id, accession_no="9999999995-26-000001",
        accession_number="9999999995-26-000001", form_type="13F-HR",
        period_of_report=date(2025, 12, 31), report_quarter="2025-Q4",
        filed_at=datetime(2026, 2, 17, tzinfo=timezone.utc), parse_status="pending",
        reported_total_value_thousands=17_000_000,  # the filer's own declared total
    )
    db_session.add(f)
    db_session.flush()
    return f


def _current_rows(db_session, accession):
    return db_session.execute(
        __import__("sqlalchemy").text(
            "SELECT count(*) FROM holdings_13f h JOIN parse_runs pr "
            "ON pr.id=h.parse_run_id AND pr.is_current "
            "WHERE pr.accession_number=:a"
        ),
        {"a": accession},
    ).scalar()


def test_a_partial_reparse_does_not_replace_a_reconciled_run(db_session, filing):
    """The P1 the reviewer reproduced: 17M -> 8M, Apple weight 47% -> 100%."""
    ingest_holdings_for_filing(db_session, filing, TWO_ROWS)
    db_session.refresh(filing)
    assert filing.computed_total_value_thousands == 17_000_000

    result = reparse_accession(
        db_session, "9999999995-26-000001", infotable_bytes=ONE_ROW
    )

    db_session.refresh(filing)
    # The denominator is untouched, so Apple's weight stays 8/17.
    assert filing.computed_total_value_thousands == 17_000_000
    assert _current_rows(db_session, "9999999995-26-000001") == 2
    assert result.get("quarantined") is True
    assert "reconciliation" in (result.get("quarantine_reason") or "").lower()


def test_the_quarantined_run_is_kept_for_audit_but_not_current(db_session, filing):
    ingest_holdings_for_filing(db_session, filing, TWO_ROWS)
    reparse_accession(db_session, "9999999995-26-000001", infotable_bytes=ONE_ROW)

    runs = (
        db_session.query(ParseRun13F)
        .filter(ParseRun13F.accession_number == "9999999995-26-000001")
        .all()
    )
    assert len(runs) == 2, "the partial run is retained, not deleted"
    current = [r for r in runs if r.is_current]
    assert len(current) == 1 and current[0].holdings_count == 2
    quarantined = [r for r in runs if not r.is_current]
    assert len(quarantined) == 1 and quarantined[0].status == "succeeded"


def test_a_legitimate_reparse_that_reconciles_still_switches(db_session, filing):
    """A parser-fix reparse that agrees with the filer's total must go through."""
    ingest_holdings_for_filing(db_session, filing, ONE_ROW)  # first ingest: 8M
    db_session.refresh(filing)
    # First ingest is never gated even though 8M != reported 17M.
    assert filing.computed_total_value_thousands == 8_000_000

    result = reparse_accession(
        db_session, "9999999995-26-000001", infotable_bytes=TWO_ROWS
    )  # 17M, matches reported

    db_session.refresh(filing)
    assert filing.computed_total_value_thousands == 17_000_000
    assert _current_rows(db_session, "9999999995-26-000001") == 2
    assert not result.get("quarantined")


def test_a_first_ingest_is_never_gated(db_session, filing):
    """No prior current run => accept whatever parses, even if it disagrees."""
    result = ingest_holdings_for_filing(db_session, filing, ONE_ROW)  # 8M vs reported 17M

    db_session.refresh(filing)
    assert filing.computed_total_value_thousands == 8_000_000
    assert _current_rows(db_session, "9999999995-26-000001") == 1
    assert not result.get("quarantined")


def test_the_reparse_job_reports_a_quarantine_as_partial_not_succeeded(
    db_session, monkeypatch
):
    """External review round 2. The reparse_accession job branch hardcoded
    `status: succeeded`, so a quarantined reparse looked fully successful to the
    operator — hiding that their reparse did not take effect. The job layer must
    surface the quarantine."""
    from app.services import thirteenf_admin_dashboard as dash

    monkeypatch.setattr(
        "app.services.thirteenf_holdings_ingest.reparse_accession",
        lambda session, accession_no: {
            "parse_run_id": 1, "holdings_count": 1,
            "quarantined": True, "quarantine_reason": "failed reconciliation gate",
        },
    )

    result = dash._execute_ingest_job(
        db_session, "reparse_accession", {"accession_no": "X-26-000001"}
    )

    assert result["status"] == "partial_success"
    assert result["quarantined"] is True
    assert result.get("quarantine_reason")


def test_the_reparse_job_still_reports_a_clean_reparse_as_succeeded(
    db_session, monkeypatch
):
    from app.services import thirteenf_admin_dashboard as dash

    monkeypatch.setattr(
        "app.services.thirteenf_holdings_ingest.reparse_accession",
        lambda session, accession_no: {"parse_run_id": 1, "holdings_count": 5},
    )

    result = dash._execute_ingest_job(
        db_session, "reparse_accession", {"accession_no": "X-26-000002"}
    )

    assert result["status"] == "succeeded"
    assert result["quarantined"] is False


def test_a_reparse_is_not_gated_when_the_filer_declared_no_total(db_session):
    """Reported NULL falls back to a row-count floor, not a value check."""
    m = InstitutionManager(
        cik="9999999994", legal_name="NoTotal", name_normalized="nototal-gate",
        match_status="confirmed",
    )
    db_session.add(m)
    db_session.flush()
    f = Filing13F(
        manager_id=m.id, accession_no="9999999994-26-000001",
        accession_number="9999999994-26-000001", form_type="13F-HR",
        period_of_report=date(2025, 12, 31), report_quarter="2025-Q4",
        filed_at=datetime(2026, 2, 17, tzinfo=timezone.utc), parse_status="pending",
        reported_total_value_thousands=None,
    )
    db_session.add(f)
    db_session.flush()

    ingest_holdings_for_filing(db_session, f, TWO_ROWS)  # 2 rows, no reported total
    # A reparse dropping to 1 row, with no declared total to check against, is a
    # row-count regression and is quarantined.
    result = reparse_accession(
        db_session, "9999999994-26-000001", infotable_bytes=ONE_ROW
    )
    assert result.get("quarantined") is True
    assert _current_rows(db_session, "9999999994-26-000001") == 2


def test_explicit_empty_portfolio_sentinel_can_replace_prior_placeholder_run(db_session):
    m = InstitutionManager(
        cik="9999999993", legal_name="Explicit Empty", name_normalized="explicit-empty",
        match_status="confirmed",
    )
    db_session.add(m)
    db_session.flush()
    f = Filing13F(
        manager_id=m.id, accession_no="9999999993-26-000001",
        accession_number="9999999993-26-000001", form_type="13F-HR",
        period_of_report=date(2025, 12, 31), report_quarter="2025-Q4",
        filed_at=datetime(2026, 2, 17, tzinfo=timezone.utc), parse_status="pending",
        reported_total_value_thousands=None,
    )
    db_session.add(f)
    db_session.flush()
    ingest_holdings_for_filing(db_session, f, ONE_ROW)

    result = reparse_accession(
        db_session,
        "9999999993-26-000001",
        infotable_bytes=EMPTY_PORTFOLIO_SENTINEL,
    )

    db_session.refresh(f)
    assert not result.get("quarantined")
    assert result["holdings_count"] == 0
    assert _current_rows(db_session, "9999999993-26-000001") == 0
    assert f.computed_total_value_thousands == 0
    assert f.common_holdings_count == 0
