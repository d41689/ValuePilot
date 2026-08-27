"""T4 — CLI ingest hygiene (F5 + F6).

The CLI `backfill` / `ingest-holdings` commands used to call the legacy
`ingest_filing_holdings`, which (F6) wrote `parse_run_id = NULL` holdings
invisible to the product query contract, and (F5) selected pending filings by a
*report-quarter* `period_of_report` window — silently skipping the newest report
quarter, whose freshly-indexed filings carry a proxy period (= filed_at) that
lands in the FOLLOWING calendar quarter until parsed.

These tests pin the fix: `pending_ingest_quarters` translates each pending
filing's proxy period back to the REPORT quarter the `ingest_holdings` job
expects, so the newest quarter is reachable, and `ingest_pending_holdings`
delegates every pending quarter to the modern job path (never the legacy
per-filing call).

The job's `quarter` payload is a report quarter — the same thing
`fetch_quarter_index` means by it — and `_ingest_candidate_filings` widens to the
filed quarter internally. Handing it a filed quarter selects nothing;
`test_pending_ingest_quarters_speaks_the_same_language_as_the_ingest_job`
(tests/unit/test_13f_pipeline_quarter_window.py) pins the two together.
"""
import inspect
import itertools
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from typer.testing import CliRunner

from app.cli import edgar as edgar_cli
from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    JobRun,
    ParseRun13F,
    RawSourceDocument,
)
from app.services.edgar_ingestion import (
    pending_ingest_quarters,
    ingest_pending_holdings,
    next_quarter_label,
    previous_quarter_label,
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
        parse_status="succeeded" if ingested else "pending",
    )
    db_session.add(filing)
    db_session.flush()
    if ingested:
        db_session.add(
            ParseRun13F(
                accession_number=filing.accession_number,
                parser_version="test",
                fingerprint_version="v1",
                status="succeeded",
                holdings_count=1,
                is_current=True,
            )
        )
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

    # filed 2025-05 → report quarter 2025-Q1
    assert pending_ingest_quarters(db_session) == ["2025-Q1"]


def test_pending_ingest_quarters_retries_fetched_but_failed_parse(db_session):
    mgr = _manager(db_session)
    filing = _filing(
        db_session, mgr,
        period_of_report=date(2025, 3, 31), filed_at=date(2025, 5, 10),
        ingested=False,
    )
    filing.report_quarter = "2025-Q1"
    filing.raw_infotable_doc_id = _infotable_doc(db_session).id
    filing.parse_status = "failed"
    db_session.add(
        ParseRun13F(
            accession_number=filing.accession_number,
            parser_version="test",
            fingerprint_version="v1",
            status="failed",
            holdings_count=0,
            error="synthetic failure",
            is_current=False,
        )
    )
    db_session.flush()

    assert pending_ingest_quarters(db_session) == ["2025-Q1"]


def test_pending_ingest_quarters_covers_newest_report_quarter(db_session):
    """F5 regression: the newest report quarter's filings are filed the
    FOLLOWING quarter, so their proxy period (= filed_at) sits one quarter
    ahead. Translating the proxy back to its report quarter must still surface
    them — a naive report-quarter window over the proxy would drop them."""
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
    # Filed 2025-05 → reports 2025-Q1; filed 2025-08 → reports 2025-Q2.
    # The newest report quarter (2025-Q2) is NOT skipped.
    assert quarters == ["2025-Q1", "2025-Q2"]


def test_pending_ingest_quarters_deduplicates(db_session):
    mgr = _manager(db_session)
    for day in (5, 12, 20):
        _filing(
            db_session, mgr,
            period_of_report=date(2025, 5, day), filed_at=date(2025, 5, day),
            ingested=False,
        )
    # Three filings, all filed in 2025-Q2 → one report quarter, 2025-Q1.
    assert pending_ingest_quarters(db_session) == ["2025-Q1"]


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

    # Report quarters, because that is what the job's `quarter` payload means.
    assert calls == ["2025-Q1", "2025-Q2"]
    assert set(summaries) == {"2025-Q1", "2025-Q2"}
    assert summaries["2025-Q1"]["filings_processed"] == 1


def test_next_quarter_label_boundaries():
    assert next_quarter_label("2025-Q1") == "2025-Q2"
    assert next_quarter_label("2025-Q3") == "2025-Q4"
    assert next_quarter_label("2025-Q4") == "2026-Q1"
    assert next_quarter_label("2025-q2") == "2025-Q3"  # case-insensitive


def test_previous_quarter_label_boundaries():
    """The inverse of next_quarter_label; pending_ingest_quarters rides on it."""
    assert previous_quarter_label("2026-Q1") == "2025-Q4"   # year boundary
    assert previous_quarter_label("2025-Q4") == "2025-Q3"
    assert previous_quarter_label("2025-Q2") == "2025-Q1"
    assert previous_quarter_label("2025-q3") == "2025-Q2"   # case-insensitive
    for q in ("2024-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1"):
        assert next_quarter_label(previous_quarter_label(q)) == q


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
        db_session, quarters={"2025-Q2"}, ingest_fn=lambda q: calls.append(q) or {}
    )

    # Only the in-scope report quarter is ingested; the ancient one (2020-Q1,
    # filed 2020-05) is left alone.
    assert calls == ["2025-Q2"]
    assert set(summaries) == {"2025-Q2"}


def test_ingest_pending_holdings_bound_still_reaches_newest_report_quarter(db_session):
    """F5 must survive the bound.

    A 2025-Q1 report filed 2025-05 carries a proxy period in 2025-Q2. `backfill`
    now scopes to the report quarters it indexed, with no widening: the Q -> Q+1
    translation lives in `pending_ingest_quarters` and `_ingest_candidate_filings`.
    Widening here would only reach a quarter this backfill never indexed."""
    mgr = _manager(db_session)
    _filing(
        db_session, mgr,
        period_of_report=date(2025, 5, 14), filed_at=date(2025, 5, 14),
        ingested=False,
    )

    scoped = {"2025-Q1"}   # exactly what `backfill` passes now

    calls: list[str] = []
    ingest_pending_holdings(
        db_session, quarters=scoped, ingest_fn=lambda q: calls.append(q) or {}
    )

    assert calls == ["2025-Q1"]


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
        if quarter == "2025-Q2":
            raise RuntimeError("boom")
        return {"quarter": quarter, "ok": True}

    summaries = ingest_pending_holdings(db_session, ingest_fn=flaky_ingest)

    # Filed 05 / 08 / 11 → reports 2025-Q1 / Q2 / Q3. All three attempted; the
    # failure recorded, the rest succeeded.
    assert set(summaries) == {"2025-Q1", "2025-Q2", "2025-Q3"}
    assert summaries["2025-Q2"] == {"error": "boom"}
    assert summaries["2025-Q1"]["ok"] is True
    assert summaries["2025-Q3"]["ok"] is True


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


# ---------------------------------------------------------------------------
# F6/F7 product-visibility contract at the CLI boundary
#
# reparse_accession's ParseRun-backed, non-destructive behavior is proven by
# test_13f_parse_run_audit.py; ingest_if_needed's ParseRun writes by the ingest
# job tests. What regressed (F6) and what F7 flags is the CLI *composition* — so
# these pin that the CLI commands route to the job path and never to the legacy
# destructive ingest_filing_holdings.
# ---------------------------------------------------------------------------

def test_cli_commands_never_call_legacy_ingest_filing_holdings():
    """A revert of any command back to the destructive legacy path (which writes
    parse_run_id=NULL invisible holdings and, with replace_holdings, deletes the
    visible ones) must fail this test — the exact F6/F7 regression barrier."""
    for fn in (
        edgar_cli.ingest_holdings,
        edgar_cli.backfill,
        edgar_cli.reparse_filing,
        edgar_cli.reparse_all,
    ):
        src = inspect.getsource(fn)
        assert "ingest_filing_holdings" not in src, (
            f"{fn.__name__} references the legacy destructive ingest path"
        )
    # ingest + reparse go through the locked job runner; backfill via the helper.
    assert "run_locked_job" in inspect.getsource(edgar_cli.ingest_holdings)
    assert "run_locked_job" in inspect.getsource(edgar_cli.reparse_filing)
    assert "run_locked_job" in inspect.getsource(edgar_cli.reparse_all)
    assert "ingest_pending_holdings" in inspect.getsource(edgar_cli.backfill)


def _stub_session_local(monkeypatch):
    """The single-shot commands don't query the DB directly — they hand the
    session to run_locked_job (stubbed here) — so a MagicMock session is enough
    and keeps the test off the real DB."""
    monkeypatch.setattr(edgar_cli, "SessionLocal", lambda: MagicMock())


def test_ingest_holdings_cli_invokes_locked_ingest_job(monkeypatch):
    calls: list = []

    def fake_run_locked_job(session, job_type, payload, *, trigger_source="manual"):
        calls.append((job_type, payload, trigger_source))
        return {"stage": {"status": "succeeded"}, "summary": {"filings_processed": 3}}

    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.run_locked_job", fake_run_locked_job
    )
    _stub_session_local(monkeypatch)

    res = CliRunner().invoke(edgar_cli.app, ["ingest-holdings", "--quarter", "2025-Q2"])

    assert res.exit_code == 0, res.output
    assert calls == [("ingest_holdings", {"quarter": "2025-Q2"}, "cli")]


def test_reparse_filing_cli_invokes_reparse_accession_job(monkeypatch):
    calls: list = []

    def fake_run_locked_job(session, job_type, payload, *, trigger_source="manual"):
        calls.append((job_type, payload, trigger_source))
        return {"stage": {"status": "succeeded"}, "summary": {"holdings_count": 5, "parse_run_id": 42}}

    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.run_locked_job", fake_run_locked_job
    )
    _stub_session_local(monkeypatch)

    res = CliRunner().invoke(edgar_cli.app, ["reparse-filing", "--accession", "0001-25-000001"])

    assert res.exit_code == 0, res.output
    assert calls == [("reparse_accession", {"accession_no": "0001-25-000001"}, "cli")]
    assert "parse_run 42" in res.output


def test_reparse_filing_cli_exits_nonzero_on_job_error(monkeypatch):
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.run_locked_job",
        lambda *a, **k: {"stage": {"status": "failed"}, "summary": {"status": "failed"}, "error": "boom"},
    )
    _stub_session_local(monkeypatch)

    res = CliRunner().invoke(edgar_cli.app, ["reparse-filing", "--accession", "X"])

    assert res.exit_code == 1
    assert "boom" in res.output


def test_run_locked_job_reports_conflict_when_lock_held(db_session):
    """P2 lock: an already-active JobRun on the same lock_key makes a CLI-triggered
    run return `conflict` instead of executing an untracked second copy."""
    from app.services.thirteenf_admin_dashboard import run_locked_job

    now = datetime.now(timezone.utc)
    db_session.add(
        JobRun(
            job_type="ingest_holdings",
            status="running",
            trigger_source="pipeline",
            dedupe_key="ingest_holdings:2025-Q2",
            lock_key="ingest_holdings:2025-Q2",
            quarter="2025-Q2",
            started_at=now,
            heartbeat_at=now,
        )
    )
    db_session.flush()

    result = run_locked_job(db_session, "ingest_holdings", {"quarter": "2025-Q2"}, trigger_source="cli")

    assert result["stage"]["status"] == "conflict"
    assert result.get("error")


# ---------------------------------------------------------------------------
# Real-path integration: the CLI reparse goes through run_locked_job →
# _execute_ingest_job → reparse_accession → _do_ingest_holdings for real. Only
# the raw-bytes source (load_body) is stubbed — the parse, ParseRun swap, JobRun
# lifecycle, and product-visibility query all execute. This is the assertion the
# earlier "current-ParseRun count" real-data check failed to make: currency is
# necessary but not sufficient — active_hr_holdings_query ALSO requires the
# filing to be active.
# ---------------------------------------------------------------------------

_INFOTABLE_XML = b"""<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>8000000</value>
    <shrsOrPrnAmt><sshPrnamt>50000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority><Sole>50000</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
</informationTable>"""


def _active_hr_filing_with_doc(db_session):
    n = next(_SEQ)
    cik = str(9900000000 + n)[:10]
    mgr = InstitutionManager(
        legal_name=f"IT Mgr {n}", display_name=f"IT Mgr {n}",
        name_normalized=f"it mgr {n}", cik=cik, status="active", match_status="confirmed",
    )
    db_session.add(mgr)
    db_session.flush()
    doc = _infotable_doc(db_session)
    accession = f"ITAC{n:016d}"
    filing = Filing13F(
        manager_id=mgr.id, cik=cik, accession_no=accession, accession_number=accession,
        form_type="13F-HR", period_of_report=date(2024, 3, 31), filed_at=date(2024, 5, 15),
        filing_date=date(2024, 5, 15), accepted_at=datetime(2024, 5, 15, 17, tzinfo=timezone.utc),
        report_quarter="2024-Q1", quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=True, parse_status="pending",
        report_type="holdings_report", coverage_completeness="complete",
        raw_infotable_doc_id=doc.id,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def test_cli_reparse_path_is_product_visible_end_to_end(db_session, monkeypatch):
    """F6/F7 visibility contract, proven — not mocked. Runs the real
    run_locked_job('reparse_accession') path and asserts the reparsed holdings
    are returned by active_hr_holdings_query (active + current + HR), the prior
    run is retained, no NULL-parse_run rows appear, and the JobRun is a succeeded
    `cli` run."""
    from app.services.thirteenf_admin_dashboard import run_locked_job
    from app.services.thirteenf_holdings_query import active_hr_holdings_query
    from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing

    filing = _active_hr_filing_with_doc(db_session)
    acc = filing.accession_number

    # Initial ingest → run1 + holdings (product-visible).
    r1 = ingest_holdings_for_filing(db_session, filing, _INFOTABLE_XML)
    db_session.flush()
    visible_before = active_hr_holdings_query(db_session).filter(
        ParseRun13F.accession_number == acc
    ).count()
    assert visible_before == 1

    # reparse from the stored doc: stub only the raw-bytes read.
    monkeypatch.setattr("app.edgar.fetcher.load_body", lambda doc: _INFOTABLE_XML)

    result = run_locked_job(db_session, "reparse_accession", {"accession_no": acc}, trigger_source="cli")

    assert result["stage"]["status"] == "succeeded", result
    # New current ParseRun; old run retained (non-destructive).
    runs = (
        db_session.query(ParseRun13F)
        .filter(ParseRun13F.accession_number == acc)
        .order_by(ParseRun13F.id)
        .all()
    )
    assert len(runs) == 2
    assert runs[0].id == r1["parse_run_id"] and runs[0].is_current is False
    assert runs[1].is_current is True
    # Product-visible through the real contract query, and no invisible rows.
    visible_after = active_hr_holdings_query(db_session).filter(
        ParseRun13F.accession_number == acc
    ).count()
    assert visible_after == 1
    assert db_session.query(Holding13F).filter(
        Holding13F.parse_run_id.is_(None), Holding13F.accession_number == acc
    ).count() == 0
    # JobRun recorded as a succeeded cli run.
    job = (
        db_session.query(JobRun)
        .filter(JobRun.lock_key == f"reparse_accession:{acc}")
        .one()
    )
    assert job.status == "succeeded" and job.trigger_source == "cli"


def test_cli_reparse_path_inactive_filing_is_not_product_visible(db_session, monkeypatch):
    """Currency is not visibility: reparsing a filing that is NOT the active one
    for its (manager, quarter) yields a current ParseRun but zero product-visible
    rows — exactly the distinction the earlier real-data check missed."""
    from app.services.thirteenf_admin_dashboard import run_locked_job
    from app.services.thirteenf_holdings_query import active_hr_holdings_query
    from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing

    filing = _active_hr_filing_with_doc(db_session)
    filing.is_active_for_manager_period = False  # superseded by a restatement, say
    db_session.flush()
    acc = filing.accession_number

    ingest_holdings_for_filing(db_session, filing, _INFOTABLE_XML)
    db_session.flush()
    monkeypatch.setattr("app.edgar.fetcher.load_body", lambda doc: _INFOTABLE_XML)

    run_locked_job(db_session, "reparse_accession", {"accession_no": acc}, trigger_source="cli")

    current_rows = (
        db_session.query(Holding13F)
        .join(ParseRun13F, Holding13F.parse_run_id == ParseRun13F.id)
        .filter(ParseRun13F.accession_number == acc, ParseRun13F.is_current.is_(True))
        .count()
    )
    visible_rows = active_hr_holdings_query(db_session).filter(
        ParseRun13F.accession_number == acc
    ).count()
    assert current_rows == 1  # a current ParseRun exists
    assert visible_rows == 0  # but the inactive filing contributes nothing


def test_reparse_all_cli_nonzero_exit_on_partial_failure(db_session, monkeypatch):
    """Runtime reparse-all: one success + one failing accession → the success is
    counted, the failure logged, and the command exits non-zero."""
    mgr = _manager(db_session)
    ok = _filing(db_session, mgr, period_of_report=date(2025, 3, 31), filed_at=date(2025, 5, 10), ingested=True)
    bad = _filing(db_session, mgr, period_of_report=date(2024, 12, 31), filed_at=date(2025, 2, 11), ingested=True)
    ok_acc, bad_acc = ok.accession_no, bad.accession_no

    def fake_run_locked_job(session, job_type, payload, *, trigger_source="manual"):
        assert job_type == "reparse_accession"
        if payload["accession_no"] == bad_acc:
            return {"stage": {"status": "failed"}, "summary": {"status": "failed"}, "error": "boom"}
        return {"stage": {"status": "succeeded"}, "summary": {"holdings_count": 7}}

    monkeypatch.setattr("app.services.thirteenf_admin_dashboard.run_locked_job", fake_run_locked_job)
    monkeypatch.setattr(edgar_cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    res = CliRunner().invoke(edgar_cli.app, ["reparse-all"])

    assert res.exit_code == 1, res.output
    assert "7 holdings, 1 failed" in res.output
