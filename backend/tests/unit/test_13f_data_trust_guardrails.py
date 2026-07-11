"""Two guardrails that make silent 13F data gaps loud (admin tasks).

The 13F pipeline had two silent failure modes an aggregate ratio hid:

1. **Confirmed managers that produce nothing.** 11 curated superinvestors carried
   a CIK that never files a 13F, so they were absent from every quarter. The
   readiness coverage check is a RATIO with an 80% threshold, and 71/82 = 86.6%
   cleared it — so 11 named managers were invisible while every check was green.
   A ratio cannot catch a persistent, per-manager absence; only a per-manager,
   absolute check can.

2. **High-impact CUSIPs that cannot link to a stock.** ExxonMobil (held by 14
   managers, ~$12B) sat unresolved in the CUSIP queue, so it was absent from
   Oracle's Lens entirely. The aggregate linked-common ratio (92%) hid it,
   because the missing 8% included mega-caps, not just foreign micro-caps.

Both surface as admin tasks that name the specific offenders, so an operator (or
the next agent) sees WHO is missing and WHICH stock is invisible.
"""
from datetime import date, datetime, timezone

import pytest

from app.models.institutions import Filing13F, Holding13F, InstitutionManager, ParseRun13F
from app.models.stocks import Stock
from app.services.thirteenf_admin_dashboard import build_admin_tasks


@pytest.fixture
def linked_stock(db_session):
    """A real Stock row so a `stock_id` FK on a holding resolves."""
    s = Stock(ticker="AAPL", company_name="Apple Inc", exchange="US")
    db_session.add(s)
    db_session.flush()
    return s


def _manager(db_session, *, cik, name, norm, status="active", match="confirmed"):
    m = InstitutionManager(
        cik=cik, legal_name=name, display_name=name, name_normalized=norm,
        match_status=match, status=status, is_superinvestor=True,
    )
    db_session.add(m)
    db_session.flush()
    return m


def _active_filing_with_holdings(db_session, manager, *, quarter, qend, holdings):
    """A parsed, active HR filing whose current run holds `holdings`
    (list of (cusip, issuer, stock_id, put_call) with an optional 5th element
    `value_usd` — omit it to default to 1000, pass None for an un-normalized value)."""
    acc = f"{manager.cik}-26-{manager.id:06d}"
    f = Filing13F(
        manager_id=manager.id, accession_no=acc, accession_number=acc,
        cik=manager.cik, form_type="13F-HR", period_of_report=qend,
        quarter_end_date=qend, report_quarter=quarter,
        filed_at=datetime(2026, 2, 17, tzinfo=timezone.utc), parse_status="succeeded",
        is_active_for_manager_period=True,
    )
    db_session.add(f)
    db_session.flush()
    pr = ParseRun13F(accession_number=acc, parser_version="v1", fingerprint_version="v1",
                     status="succeeded", is_current=True, holdings_count=len(holdings))
    db_session.add(pr)
    db_session.flush()
    for i, holding in enumerate(holdings):
        cusip, issuer, stock_id, put_call = holding[:4]
        value_usd = holding[4] if len(holding) > 4 else 1000
        db_session.add(Holding13F(
            filing_id=f.id, parse_run_id=pr.id, manager_id=manager.id, cusip=cusip,
            accession_number=acc, issuer_name=issuer, value_thousands=1000, value_usd=value_usd,
            row_fingerprint=f"{acc}-{i}", stock_id=stock_id, put_call=put_call,
            cusip_mapping_status="linked" if stock_id else "unresolved",
        ))
    db_session.flush()
    return f


def _codes(tasks):
    return {t["code"] for t in tasks}


def _by_code(tasks, code):
    return next(t for t in tasks if t["code"] == code)


# --------------------------------------------------------------------------
# Guardrail 1 — confirmed managers that never file
# --------------------------------------------------------------------------


def test_a_confirmed_active_manager_with_zero_filings_raises_a_task(db_session, linked_stock):
    """The 11-CIK disaster class: confirmed + active, but never produced a filing."""
    filing_mgr = _manager(db_session, cik="0001067983", name="Berkshire", norm="berkshire")
    _active_filing_with_holdings(
        db_session, filing_mgr, quarter="2025-Q4", qend=date(2025, 12, 31),
        holdings=[("037833100", "APPLE INC", linked_stock.id, None)],
    )
    _manager(db_session, cik="0000921669", name="Icahn (wrong CIK)", norm="icahn")  # never files

    tasks = build_admin_tasks(db_session)

    assert "CONFIRMED_MANAGERS_NOT_FILING" in _codes(tasks)
    task = _by_code(tasks, "CONFIRMED_MANAGERS_NOT_FILING")
    assert task["priority"] == "P1"
    # The task NAMES the offender — a bare count is not actionable.
    assert "0000921669" in {c["cik"] for c in task["metadata"]["managers"]}
    assert task["metadata"]["count"] == 1
    # The manager that DOES file is not flagged.
    assert "0001067983" not in {c["cik"] for c in task["metadata"]["managers"]}


def test_no_task_when_every_confirmed_manager_files(db_session, linked_stock):
    m = _manager(db_session, cik="0001067983", name="Berkshire", norm="berkshire")
    _active_filing_with_holdings(
        db_session, m, quarter="2025-Q4", qend=date(2025, 12, 31),
        holdings=[("037833100", "APPLE INC", linked_stock.id, None)],
    )
    assert "CONFIRMED_MANAGERS_NOT_FILING" not in _codes(build_admin_tasks(db_session))


def test_a_human_retired_manager_is_not_flagged_as_not_filing(db_session):
    """status inactive / match revoked is a human decision, not a data gap."""
    _manager(db_session, cik="0000921669", name="Retired", norm="retired",
             status="inactive", match="inactive")
    assert "CONFIRMED_MANAGERS_NOT_FILING" not in _codes(build_admin_tasks(db_session))


def test_a_manager_without_a_cik_is_not_flagged_as_not_filing(db_session):
    """A CIK-less manager cannot be expected to file — that's the match-CIK queue."""
    _manager(db_session, cik=None, name="No CIK yet", norm="nocik",
             status="active", match="seeded")
    assert "CONFIRMED_MANAGERS_NOT_FILING" not in _codes(build_admin_tasks(db_session))


# --------------------------------------------------------------------------
# Guardrail 2 — high-impact CUSIPs that cannot link to a stock
# --------------------------------------------------------------------------


def test_an_unresolved_cusip_held_by_many_managers_raises_a_task(db_session):
    """ExxonMobil-class: widely held, unresolved, therefore invisible in Lens."""
    qend = date(2025, 12, 31)
    for i in range(4):  # 4 managers all holding the same unresolved CUSIP
        m = _manager(db_session, cik=f"000000000{i}", name=f"M{i}", norm=f"m{i}")
        _active_filing_with_holdings(
            db_session, m, quarter="2025-Q4", qend=qend,
            holdings=[("30231G102", "EXXON MOBIL CORP", None, None)],  # no stock_id
        )

    tasks = build_admin_tasks(db_session, today=date(2026, 3, 1))

    assert "HIGH_IMPACT_CUSIP_UNRESOLVED" in _codes(tasks)
    task = _by_code(tasks, "HIGH_IMPACT_CUSIP_UNRESOLVED")
    offenders = {c["cusip"]: c for c in task["metadata"]["cusips"]}
    assert "30231G102" in offenders
    assert offenders["30231G102"]["manager_count"] == 4
    # Dollar impact is summed from value_usd (unit-safe), not the misnamed
    # `value_thousands` column: 4 managers x 1000 each, all normalized.
    assert offenders["30231G102"]["value_usd"] == 4000
    assert offenders["30231G102"]["value_usd_missing_count"] == 0


def test_an_unresolved_cusip_held_by_one_manager_is_below_the_bar(db_session):
    """Single-holder unresolved CUSIPs are the long tail, not a consensus loss."""
    m = _manager(db_session, cik="0000000001", name="M", norm="m1")
    _active_filing_with_holdings(
        db_session, m, quarter="2025-Q4", qend=date(2025, 12, 31),
        holdings=[("451100101", "ICAHN ENTERPRISES LP", None, None)],
    )
    assert "HIGH_IMPACT_CUSIP_UNRESOLVED" not in _codes(
        build_admin_tasks(db_session, today=date(2026, 3, 1))
    )


def test_a_widely_held_LINKED_cusip_is_not_flagged(db_session, linked_stock):
    """A resolved mega-cap held by many is exactly what we want — no task."""
    qend = date(2025, 12, 31)
    for i in range(4):
        m = _manager(db_session, cik=f"000000000{i}", name=f"M{i}", norm=f"m{i}")
        _active_filing_with_holdings(
            db_session, m, quarter="2025-Q4", qend=qend,
            holdings=[("037833100", "APPLE INC", linked_stock.id, None)],  # linked
        )
    assert "HIGH_IMPACT_CUSIP_UNRESOLVED" not in _codes(
        build_admin_tasks(db_session, today=date(2026, 3, 1))
    )


def test_partial_null_value_usd_is_a_qualified_lower_bound_not_a_complete_sum(db_session):
    """When some holdings can't be normalized (value_usd IS NULL), SUM silently
    drops them. The task must expose that so a partial sum is never shown as the
    complete impact ('unknown is not zero')."""
    qend = date(2025, 12, 31)
    for i, value_usd in enumerate((100, None, None)):  # 3 holders, 2 un-normalized
        m = _manager(db_session, cik=f"000000010{i}", name=f"P{i}", norm=f"p{i}")
        _active_filing_with_holdings(
            db_session, m, quarter="2025-Q4", qend=qend,
            holdings=[("999999999", "UNKNOWN UNIT CO", None, None, value_usd)],
        )

    task = _by_code(
        build_admin_tasks(db_session, today=date(2026, 3, 1)), "HIGH_IMPACT_CUSIP_UNRESOLVED"
    )
    row = next(c for c in task["metadata"]["cusips"] if c["cusip"] == "999999999")
    assert row["manager_count"] == 3
    assert row["value_usd"] == 100  # lower bound — only the one normalized row
    assert row["value_usd_missing_count"] == 2  # the two NULLs are surfaced, not hidden


def test_all_null_value_usd_reports_zero_with_full_missing_count(db_session):
    """Every holding un-normalized: impact is genuinely unavailable, not $0."""
    qend = date(2025, 12, 31)
    for i in range(3):
        m = _manager(db_session, cik=f"000000020{i}", name=f"A{i}", norm=f"a{i}")
        _active_filing_with_holdings(
            db_session, m, quarter="2025-Q4", qend=qend,
            holdings=[("999999888", "ALL NULL CO", None, None, None)],
        )

    task = _by_code(
        build_admin_tasks(db_session, today=date(2026, 3, 1)), "HIGH_IMPACT_CUSIP_UNRESOLVED"
    )
    row = next(c for c in task["metadata"]["cusips"] if c["cusip"] == "999999888")
    assert row["manager_count"] == 3
    assert row["value_usd"] == 0
    assert row["value_usd_missing_count"] == 3  # the UI renders "impact unavailable"


def test_options_are_not_counted_as_unresolved_impact(db_session):
    """Options (put_call set) are excluded from Lens anyway, so an unresolved
    option CUSIP is not a lost common-stock consensus signal."""
    qend = date(2025, 12, 31)
    for i in range(4):
        m = _manager(db_session, cik=f"000000000{i}", name=f"M{i}", norm=f"m{i}")
        _active_filing_with_holdings(
            db_session, m, quarter="2025-Q4", qend=qend,
            holdings=[("11111111A", "SOME CALL", None, "Call")],
        )
    assert "HIGH_IMPACT_CUSIP_UNRESOLVED" not in _codes(
        build_admin_tasks(db_session, today=date(2026, 3, 1))
    )
