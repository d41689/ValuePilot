"""13F-1B-06: Amendment Policy and Active Filing Switching tests."""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

import pytest

from app.edgar.parsers.primary_doc import parse_primary_doc, PrimaryDocSummary
from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    ParseRun13F,
    RawSourceDocument,
)
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal
from app.services.thirteenf_filing_detail import ingest_accession_filing_detail
from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CIK_SEQ = count(8800000000)

def _clear(session) -> None:
    # Pre-MVP8-01: persisted Oracle's Lens rows FK-reference
    # InstitutionManager, so they must clear first.
    session.query(OraclesLensScoreComponent).delete()
    session.query(OraclesLensSignal).delete()
    session.query(Holding13F).delete()
    session.query(ParseRun13F).delete()
    session.query(Filing13F).delete()
    session.query(RawSourceDocument).delete()
    session.query(InstitutionManagerCikReviewEvent).delete()
    session.query(InstitutionManager).delete()
    session.flush()

def _manager(session, *, cik: str | None = None) -> InstitutionManager:
    cik = cik or str(next(_CIK_SEQ)).zfill(10)
    m = InstitutionManager(
        canonical_name=f"Manager {cik}",
        legal_name=f"Manager {cik}",
        edgar_legal_name=f"Manager {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    session.add(m)
    session.flush()
    return m

def _xml_amendment(amendment_type: str) -> bytes:
    return f"""<edgarSubmission>
  <schemaVersion>X0101</schemaVersion>
  <submissionType>13F-HR/A</submissionType>
  <testOrLive>LIVE</testOrLive>
  <periodOfReport>03-31-2024</periodOfReport>
  <formData>
    <coverPage>
      <reportCalendarOrQuarter>03-31-2024</reportCalendarOrQuarter>
      <amendmentInfo>
        <amendmentType>{amendment_type}</amendmentType>
        <amendmentNo>1</amendmentNo>
      </amendmentInfo>
    </coverPage>
    <summaryPage>
      <tableEntryTotal>1</tableEntryTotal>
      <tableValueTotal>1000</tableValueTotal>
    </summaryPage>
  </formData>
</edgarSubmission>""".encode()

# ---------------------------------------------------------------------------
# Parsing Tests
# ---------------------------------------------------------------------------

def test_parse_primary_doc_extracts_amendment_type():
    doc = _xml_amendment("RESTATEMENT")
    summary = parse_primary_doc(doc)
    assert summary.amendment_type == "RESTATEMENT"
    assert summary.is_amendment is True


# ---------------------------------------------------------------------------
# Ingestion Tests
# ---------------------------------------------------------------------------

def test_ingest_accession_original_filing_resolves_conflicts(db_session):
    from app.services.thirteenf_filing_detail import ingest_accession_filing_detail

    _clear(db_session)
    manager = _manager(db_session)
    
    # 1. First original filing
    payload1 = {
        "accession_no": "0000000000-24-000001",
        "manager_id": manager.id,
        "form_type": "13F-HR",
        "filename": "some/path.txt",
    }
    class MockClient1:
        def get(self, url, **kwargs): return b"<edgarSubmission><submissionType>13F-HR</submissionType><periodOfReport>03-31-2024</periodOfReport><ACCEPTANCE-DATETIME>20240501120000</ACCEPTANCE-DATETIME></edgarSubmission>"
    
    res1 = ingest_accession_filing_detail(db_session, payload1, client=MockClient1())
    f1 = db_session.get(Filing13F, res1["filing_id"])
    assert f1.is_active_for_manager_period is True
    assert f1.amendment_sort_warning is False

    # 2. Second original filing for SAME quarter, later accepted_at
    payload2 = {
        "accession_no": "0000000000-24-000002",
        "manager_id": manager.id,
        "form_type": "13F-NT",
        "filename": "some/path2.txt",
    }
    class MockClient2:
        def get(self, url, **kwargs): return b"<edgarSubmission><submissionType>13F-NT</submissionType><periodOfReport>03-31-2024</periodOfReport><ACCEPTANCE-DATETIME>20240502120000</ACCEPTANCE-DATETIME></edgarSubmission>"
    
    res2 = ingest_accession_filing_detail(db_session, payload2, client=MockClient2())
    f2 = db_session.get(Filing13F, res2["filing_id"])

    db_session.refresh(f1)

    # T1-FU: an NT never beats an HR for the active slot, regardless of
    # accepted_at ordering (pre-T1-FU this test pinned the opposite — the
    # later-accepted NT stole active status from the holdings report).
    assert f1.is_active_for_manager_period is True
    assert f2.is_active_for_manager_period is False

    # 3. Third original filing (13F-HR), accepted later than f1 → wins.
    payload3 = {
        "accession_no": "0000000000-24-000003",
        "manager_id": manager.id,
        "form_type": "13F-HR",
        "filename": "some/path3.txt",
    }
    class MockClient3:
        def get(self, url, **kwargs): return b"<edgarSubmission><submissionType>13F-HR</submissionType><periodOfReport>03-31-2024</periodOfReport><ACCEPTANCE-DATETIME>20240502120000</ACCEPTANCE-DATETIME></edgarSubmission>"

    res3 = ingest_accession_filing_detail(db_session, payload3, client=MockClient3())
    f3 = db_session.get(Filing13F, res3["filing_id"])

    db_session.refresh(f1)
    db_session.refresh(f2)

    assert f3.is_active_for_manager_period is True
    assert f1.is_active_for_manager_period is False
    assert f2.is_active_for_manager_period is False  # NT still excluded

    # 4. Fourth HR with the SAME (non-NULL) accepted_at as f3 → genuine tie:
    # neither HR is active, both flagged for a human. (NULL-vs-NULL is NOT a
    # tie — accession_no decides; see apply_active_filing_policy.)
    payload4 = {
        "accession_no": "0000000000-24-000004",
        "manager_id": manager.id,
        "form_type": "13F-HR",
        "filename": "some/path4.txt",
    }
    class MockClient4:
        def get(self, url, **kwargs): return b"<edgarSubmission><submissionType>13F-HR</submissionType><periodOfReport>03-31-2024</periodOfReport><ACCEPTANCE-DATETIME>20240502120000</ACCEPTANCE-DATETIME></edgarSubmission>"

    res4 = ingest_accession_filing_detail(db_session, payload4, client=MockClient4())
    f4 = db_session.get(Filing13F, res4["filing_id"])

    db_session.refresh(f3)

    assert f3.is_active_for_manager_period is False
    assert f4.is_active_for_manager_period is False
    assert f3.amendment_sort_warning is True
    assert f4.amendment_sort_warning is True
    assert f4.amendment_status == "amendments_pending"


def test_ingest_accession_marks_amendments_correctly(db_session):
    from app.services.thirteenf_filing_detail import ingest_accession_filing_detail

    _clear(db_session)
    manager = _manager(db_session)
    
    payload = {
        "accession_no": "0000000000-24-A00001",
        "manager_id": manager.id,
        "form_type": "13F-HR/A",
        "filename": "some/path.txt",
    }
    class MockClient:
        def get(self, url, **kwargs): return _xml_amendment("NEW HOLDINGS")
    
    res = ingest_accession_filing_detail(db_session, payload, client=MockClient())
    f = db_session.get(Filing13F, res["filing_id"])
    
    assert f.is_amendment is True
    assert f.amendment_type == "NEW_HOLDINGS"
    assert f.amendment_status == "amendments_pending"
    assert f.is_active_for_manager_period is False


def test_reparse_restatement_switches_active_filing(db_session):
    from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing
    
    _clear(db_session)
    manager = _manager(db_session)
    
    # Original filing
    f_orig = Filing13F(
        manager_id=manager.id,
        accession_no="ORIG",
        accession_number="ORIG",
        form_type="13F-HR",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 15),
        quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=True,
    )
    db_session.add(f_orig)
    
    # Restatement amendment
    f_amend = Filing13F(
        manager_id=manager.id,
        accession_no="AMEND",
        accession_number="AMEND",
        form_type="13F-HR/A",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 16),
        quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=False,
        is_latest_for_period=False,
        is_amendment=True,
        amendment_type="RESTATEMENT",
        amendment_status="pending_parse",
    )
    db_session.add(f_amend)
    db_session.flush()
    
    # Perform parse
    infotable = b"<informationTable xmlns='http://www.sec.gov/edgar/document/thirteenf/informationtable'><infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>8000000</value><shrsOrPrnAmt><sshPrnamt>50000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>SOLE</investmentDiscretion><votingAuthority><Sole>50000</Sole><Shared>0</Shared><None>0</None></votingAuthority></infoTable></informationTable>"
    
    ingest_holdings_for_filing(db_session, f_amend, infotable)
    
    db_session.refresh(f_orig)
    db_session.refresh(f_amend)
    
    assert f_orig.is_active_for_manager_period is False
    assert f_amend.is_active_for_manager_period is True
    assert f_amend.amendment_status == "applied"


def test_resolve_amendment_activates_as_original(db_session):
    from app.services.thirteenf_admin_dashboard import resolve_amendment
    
    _clear(db_session)
    manager = _manager(db_session)
    
    f_orig = Filing13F(
        manager_id=manager.id,
        accession_no="ORIG",
        accession_number="ORIG",
        form_type="13F-HR",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 15),
        quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=True,
    )
    db_session.add(f_orig)
    
    f_amend = Filing13F(
        manager_id=manager.id,
        accession_no="AMEND",
        accession_number="AMEND",
        form_type="13F-HR/A",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 16),
        quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=False,
        is_latest_for_period=False,
        is_amendment=True,
        amendment_type="NEW_HOLDINGS",
        amendment_status="amendments_pending",
    )
    db_session.add(f_amend)
    db_session.flush()
    
    res = resolve_amendment(db_session, "AMEND", "activate_as_original", "Looks good")
    
    db_session.refresh(f_orig)
    db_session.refresh(f_amend)
    
    assert f_orig.is_active_for_manager_period is False
    assert f_amend.is_active_for_manager_period is True
    assert f_amend.amendment_status == "applied"
    assert "Looks good" in f_amend.parse_warning


# --- 2026-05-22: bulk-ingest primary-doc fix (P1 / P2 / P3) ------------------

def test_reconcile_restatement_activation_heals_already_ingested(db_session):
    """A RESTATEMENT amendment parsed before is_amendment/amendment_type were
    set is stuck pending_parse / inactive — reconcile must activate it on a
    re-run and demote the superseded original. Idempotent. (P1.)
    """
    from app.services.thirteenf_holdings_ingest import reconcile_restatement_activation

    _clear(db_session)
    manager = _manager(db_session)
    f_orig = Filing13F(
        manager_id=manager.id, accession_no="O1", accession_number="O1",
        form_type="13F-HR", period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 15), quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=True, is_latest_for_period=False,
    )
    f_amend = Filing13F(
        manager_id=manager.id, accession_no="A1", accession_number="A1",
        form_type="13F-HR/A", period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 16), quarter_end_date=date(2024, 3, 31),
        is_latest_for_period=True,
        is_active_for_manager_period=False, is_amendment=True,
        amendment_type="RESTATEMENT", amendment_status="pending_parse",
        parse_status="succeeded",
    )
    db_session.add_all([f_orig, f_amend])
    db_session.flush()

    assert reconcile_restatement_activation(db_session, f_amend) is True
    db_session.flush()
    assert f_amend.is_active_for_manager_period is True
    assert f_amend.amendment_status == "applied"
    assert f_orig.is_active_for_manager_period is False
    # Idempotent — a second call changes nothing.
    assert reconcile_restatement_activation(db_session, f_amend) is False


def test_reconcile_restatement_activation_skips_non_restatement(db_session):
    """A NEW_HOLDINGS amendment is not auto-activated — it stays pending for an
    admin to resolve."""
    from app.services.thirteenf_holdings_ingest import reconcile_restatement_activation

    _clear(db_session)
    manager = _manager(db_session)
    f = Filing13F(
        manager_id=manager.id, accession_no="A2", accession_number="A2",
        form_type="13F-HR/A", period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 16), quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=False, is_amendment=True,
        amendment_type="NEW_HOLDINGS", amendment_status="amendments_pending",
        parse_status="succeeded",
    )
    db_session.add(f)
    db_session.flush()

    assert reconcile_restatement_activation(db_session, f) is False
    db_session.refresh(f)
    assert f.is_active_for_manager_period is False
    assert f.amendment_status == "amendments_pending"


def _restatement_chain(db_session):
    """HR -> HR/A#1 -> HR/A#2 in one (manager, quarter_end_date), mirroring the
    live crash case (manager 4007 / 2025-Q3). ids ascend with filing order so
    the reproduction matches production's UOW PK-ordered UPDATE emission."""
    _clear(db_session)
    manager = _manager(db_session)
    qend = date(2024, 3, 31)
    f_orig = Filing13F(
        manager_id=manager.id, accession_no="O1", accession_number="O1",
        form_type="13F-HR", period_of_report=qend, filed_at=date(2024, 5, 14),
        quarter_end_date=qend, is_active_for_manager_period=False,
        is_latest_for_period=False, parse_status="succeeded",
    )
    f_r1 = Filing13F(
        manager_id=manager.id, accession_no="A1", accession_number="A1",
        form_type="13F-HR/A", period_of_report=qend, filed_at=date(2024, 5, 15),
        quarter_end_date=qend, is_active_for_manager_period=False,
        is_latest_for_period=False, is_amendment=True,
        amendment_type="RESTATEMENT", amendment_status="pending_parse",
        parse_status="succeeded",
    )
    f_r2 = Filing13F(
        manager_id=manager.id, accession_no="A2", accession_number="A2",
        form_type="13F-HR/A", period_of_report=qend, filed_at=date(2024, 5, 16),
        quarter_end_date=qend, is_active_for_manager_period=False,
        is_latest_for_period=True, is_amendment=True,
        amendment_type="RESTATEMENT", amendment_status="pending_parse",
        parse_status="succeeded",
    )
    db_session.add_all([f_orig, f_r1, f_r2])
    db_session.flush()
    return f_orig, f_r1, f_r2


def test_reconcile_restatement_latest_wins_regardless_of_call_order(db_session):
    """T1 core guarantee, revised by T1-FU: with two all-NULL-accepted_at
    RESTATEMENTs, reconciling the earlier one must NOT crash and must NOT
    steal activation from the current winner. T1-FU revision: all-NULL
    acceptance is MISSING EVIDENCE — no auto-switch (the current active stays)
    and the unrankable candidates are flagged for a human, instead of trusting
    the accession_no fallback (accession prefixes identify the SUBMITTING
    agent, not the manager — real dev data has 3 groups where lexical order
    inverts acceptance order)."""
    from app.services.thirteenf_holdings_ingest import reconcile_restatement_activation

    f_orig, f_r1, f_r2 = _restatement_chain(db_session)

    # Mirror Phase 3: the latest restatement is already active.
    f_r2.is_active_for_manager_period = True
    f_r2.amendment_status = "applied"
    f_orig.is_active_for_manager_period = False
    db_session.flush()

    # Phase 5 then re-reconciles the EARLIER restatement first (filed_at asc).
    # No crash; no steal. Returns True because the unrankable candidate (r1)
    # gets flagged for human review (missing-acceptance state change).
    assert reconcile_restatement_activation(db_session, f_r1) is True
    db_session.flush()
    assert f_r1.is_active_for_manager_period is False
    assert f_r2.is_active_for_manager_period is True  # kept — no auto-switch
    assert f_r1.amendment_sort_warning is True
    assert f_r1.amendment_status == "amendments_pending"
    assert f_r2.amendment_status == "applied"  # terminal, untouched


def test_reconcile_restatement_demote_then_activate_is_constraint_safe(db_session):
    """T1: activating a restatement must flush the demotion of a HIGHER-id active
    filing before setting itself active, or SQLAlchemy's PK-ordered UPDATE
    emission activates the lower-id restatement first and trips
    uq_active_filing_per_manager_period. This hazard is independent of the
    latest-wins short-circuit, so the demoted row here is a plain original."""
    from sqlalchemy.exc import IntegrityError
    from app.services.thirteenf_holdings_ingest import reconcile_restatement_activation

    _clear(db_session)
    manager = _manager(db_session)
    qend = date(2024, 3, 31)
    # Insert the restatement FIRST so it gets the LOWER id.
    f_restate = Filing13F(
        manager_id=manager.id, accession_no="R1", accession_number="R1",
        form_type="13F-HR/A", period_of_report=qend, filed_at=date(2024, 5, 16),
        quarter_end_date=qend, is_active_for_manager_period=False,
        is_latest_for_period=True, is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )
    db_session.add(f_restate)
    db_session.flush()
    # A currently-active plain original with a HIGHER id (e.g. re-ingested after
    # the amendment). Not a RESTATEMENT, so the latest-wins guard does not
    # short-circuit — reconcile must demote it, and that demote must be flushed
    # before the lower-id activation.
    f_active = Filing13F(
        manager_id=manager.id, accession_no="H1", accession_number="H1",
        form_type="13F-HR", period_of_report=qend, filed_at=date(2024, 5, 14),
        quarter_end_date=qend, is_active_for_manager_period=True,
        is_latest_for_period=False, parse_status="succeeded",
    )
    db_session.add(f_active)
    db_session.flush()
    assert f_restate.id < f_active.id  # the hazardous id ordering

    try:
        assert reconcile_restatement_activation(db_session, f_restate) is True
        db_session.flush()
    except IntegrityError:  # pragma: no cover - the bug the flush fixes
        pytest.fail("reconcile must flush demotion before activation")

    assert f_restate.is_active_for_manager_period is True
    assert f_active.is_active_for_manager_period is False
    # Idempotent.
    assert reconcile_restatement_activation(db_session, f_restate) is False


def _restatement(db_session, manager, *, acc, filed, accepted=None, parse="succeeded",
                 latest=False, active=False):
    from datetime import datetime, timezone
    qend = date(2024, 3, 31)
    f = Filing13F(
        manager_id=manager.id, accession_no=acc, accession_number=acc,
        form_type="13F-HR/A", period_of_report=qend, filed_at=filed,
        quarter_end_date=qend, is_active_for_manager_period=active,
        is_latest_for_period=latest, is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status=parse,
        accepted_at=(datetime(*accepted, tzinfo=timezone.utc) if accepted else None),
    )
    db_session.add(f)
    db_session.flush()
    return f


def test_reconcile_restatement_ranks_by_accepted_at_over_accession(db_session):
    """T1 (review follow-up): accepted_at outranks accession_no — a later-accepted
    restatement wins even when its accession sorts LOWER, matching
    apply_amendment_policy's (accepted_at, accession_no) key. Guards against the
    original filed_at/id key that ignored accepted_at."""
    from app.services.thirteenf_holdings_ingest import reconcile_restatement_activation

    _clear(db_session)
    manager = _manager(db_session)
    # LOWER accession but LATER accepted_at -> should win.
    r_win = _restatement(db_session, manager, acc="AAA1", filed=date(2024, 5, 15),
                         accepted=(2024, 5, 16, 11), latest=True)
    # HIGHER accession but EARLIER accepted_at -> should lose.
    r_lose = _restatement(db_session, manager, acc="AAA2", filed=date(2024, 5, 15),
                          accepted=(2024, 5, 16, 9))

    # T1-FU: calling reconcile on the LOSER converges the group immediately —
    # the ranked winner is activated (returns True because state changed), and
    # the loser must never claim activation. (Pre-T1-FU this was a strict
    # no-op returning False; terminal state is identical.)
    assert reconcile_restatement_activation(db_session, r_lose) is True
    db_session.flush()
    assert r_lose.is_active_for_manager_period is False
    assert r_win.is_active_for_manager_period is True
    # Re-running on the winner is now a no-op — already converged.
    assert reconcile_restatement_activation(db_session, r_win) is False
    db_session.flush()
    assert r_win.is_active_for_manager_period is True
    assert r_lose.is_active_for_manager_period is False


def test_reconcile_three_restatements_only_latest_active_any_call_order(db_session):
    """T1 (review follow-up): with 3 parsed restatements, only the latest
    (accepted_at all NULL) yields ONE deterministic, crash-free terminal state
    no matter the call order. T1-FU revision: all-NULL acceptance is missing
    evidence — nothing is auto-activated (the old accession_no fallback is not
    a time proxy: prefixes identify the SUBMITTING agent), all three are
    flagged for human resolution, and repeated calls are idempotent."""
    from app.services.thirteenf_holdings_ingest import reconcile_restatement_activation

    _clear(db_session)
    manager = _manager(db_session)
    r1 = _restatement(db_session, manager, acc="A1", filed=date(2024, 5, 15))
    r2 = _restatement(db_session, manager, acc="A2", filed=date(2024, 5, 16), latest=True)
    r3 = _restatement(db_session, manager, acc="A3", filed=date(2024, 5, 17))

    # Deliberately non-sorted call order; second pass proves idempotence.
    for f in (r2, r1, r3, r2, r1, r3):
        reconcile_restatement_activation(db_session, f)
        db_session.flush()

    db_session.refresh(r1); db_session.refresh(r2); db_session.refresh(r3)
    # No auto-switch on missing evidence: nothing active, all flagged.
    assert [r1.is_active_for_manager_period, r2.is_active_for_manager_period,
            r3.is_active_for_manager_period] == [False, False, False]
    for r in (r1, r2, r3):
        assert r.amendment_sort_warning is True
        assert r.amendment_status == "amendments_pending"


def test_reconcile_ignores_failed_later_restatement(db_session):
    """T1 (review follow-up): a later restatement that FAILED to parse must not
    block the latest SUCCEEDED restatement from being active."""
    from app.services.thirteenf_holdings_ingest import reconcile_restatement_activation

    _clear(db_session)
    manager = _manager(db_session)
    r_ok = _restatement(db_session, manager, acc="A1", filed=date(2024, 5, 15), latest=True)
    _restatement(db_session, manager, acc="A2", filed=date(2024, 5, 16), parse="failed")

    assert reconcile_restatement_activation(db_session, r_ok) is True
    db_session.flush()
    assert r_ok.is_active_for_manager_period is True


def test_ingest_path_multi_restatement_latest_wins_out_of_order(db_session):
    """T1 (review follow-up): exercise the REAL ingest caller
    (ingest_holdings_for_filing -> reconcile inside the savepoint), not a direct
    reconcile call. Ingesting an earlier restatement AFTER a later one must not
    steal activation from the later winner."""
    from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing

    _clear(db_session)
    manager = _manager(db_session)
    qend = date(2024, 3, 31)
    f_orig = Filing13F(
        manager_id=manager.id, accession_no="ORIG", accession_number="ORIG",
        form_type="13F-HR", period_of_report=qend, filed_at=date(2024, 5, 14),
        quarter_end_date=qend, is_active_for_manager_period=True,
        is_latest_for_period=False,
    )
    f_r1 = Filing13F(
        manager_id=manager.id, accession_no="AMEND1", accession_number="AMEND1",
        form_type="13F-HR/A", period_of_report=qend, filed_at=date(2024, 5, 15),
        quarter_end_date=qend, is_active_for_manager_period=False,
        is_latest_for_period=False, is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse",
    )
    f_r2 = Filing13F(
        manager_id=manager.id, accession_no="AMEND2", accession_number="AMEND2",
        form_type="13F-HR/A", period_of_report=qend, filed_at=date(2024, 5, 16),
        quarter_end_date=qend, is_active_for_manager_period=False,
        is_latest_for_period=True, is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse",
    )
    db_session.add_all([f_orig, f_r1, f_r2])
    db_session.flush()

    infotable = b"<informationTable xmlns='http://www.sec.gov/edgar/document/thirteenf/informationtable'><infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>8000000</value><shrsOrPrnAmt><sshPrnamt>50000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>SOLE</investmentDiscretion><votingAuthority><Sole>50000</Sole><Shared>0</Shared><None>0</None></votingAuthority></infoTable></informationTable>"

    # Ingest the LATER restatement first, then the EARLIER one (out of order).
    ingest_holdings_for_filing(db_session, f_r2, infotable)
    ingest_holdings_for_filing(db_session, f_r1, infotable)

    db_session.refresh(f_orig); db_session.refresh(f_r1); db_session.refresh(f_r2)
    assert f_r2.is_active_for_manager_period is True
    assert f_r1.is_active_for_manager_period is False
    assert f_orig.is_active_for_manager_period is False


def test_apply_primary_doc_metadata_flags_amendment_from_form_type(db_session):
    """A 13F-HR/A is treated as an amendment even when the primary-doc parser
    does not flag is_amendment — the "/A" form type is authoritative. (P2.)
    """
    from types import SimpleNamespace
    from app.services.thirteenf_filing_detail import apply_primary_doc_metadata

    _clear(db_session)
    manager = _manager(db_session)
    f = Filing13F(
        manager_id=manager.id, accession_no="A3", accession_number="A3",
        form_type="13F-HR/A", period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 16), quarter_end_date=date(2024, 3, 31),
    )
    db_session.add(f)
    db_session.flush()

    summary = SimpleNamespace(
        is_amendment=False, amendment_type=None, report_type=None,
        form_spec_version=None, xml_schema_version=None,
        has_confidential_treatment=False,
        other_managers_reporting=None, other_managers_included=None,
    )
    apply_primary_doc_metadata(db_session, f, summary)
    assert f.is_amendment is True


def test_amendment_payload_status_reflects_amendment_status(db_session):
    """The Amendment Accessions list status must agree with amendment_status,
    not be computed "applied" off is_latest_for_period. (P3.)
    """
    from app.services.thirteenf_admin_dashboard import _amendment_payload

    _clear(db_session)
    manager = _manager(db_session)
    f = Filing13F(
        manager_id=manager.id, accession_no="A4", accession_number="A4",
        form_type="13F-HR/A", period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 16), quarter_end_date=date(2024, 3, 31),
        is_latest_for_period=True, is_amendment=True,
        amendment_type="NEW_HOLDINGS", amendment_status="amendments_pending",
    )
    db_session.add(f)
    db_session.flush()

    infotable_xml = (
        b"<informationTable xmlns='http://www.sec.gov/edgar/document/thirteenf/informationtable'>"
        b"<infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>"
        b"<cusip>037833100</cusip><value>8000000</value><shrsOrPrnAmt><sshPrnamt>50000</sshPrnamt>"
        b"<sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>SOLE</investmentDiscretion>"
        b"<votingAuthority><Sole>50000</Sole><Shared>0</Shared><None>0</None></votingAuthority>"
        b"</infoTable></informationTable>"
    )
    ingest_holdings_for_filing(db_session, f, infotable_xml)

    infotable = RawSourceDocument(
        source_system="edgar", document_type="infotable_xml",
        cik=manager.cik, accession_no=f.accession_no,
        source_url="https://example.test/infotable.xml",
        http_status=200, fetched_at=datetime.now(timezone.utc),
        body_path="test/infotable.xml", parse_status="parsed",
    )
    db_session.add(infotable)
    db_session.flush()
    f.raw_infotable_doc_id = infotable.id
    db_session.add(f)
    db_session.flush()

    payload = _amendment_payload(db_session, f)
    # amendment_status is amendments_pending -> the row reads "pending",
    # consistent with the card's "X pending" warning (pre-fix it was "applied").
    assert payload["status"] == "pending"


def test_apply_amendment_policy_preserves_admin_resolved_amendment(db_session):
    """A re-run of the amendment policy (bulk Phase 2.5) must not revert an
    admin-resolved amendment. Regression for the PR #92 review blocker — an
    `applied` amendment and the original it superseded must survive a re-run.
    """
    from app.services.thirteenf_filing_detail import apply_amendment_policy

    _clear(db_session)
    manager = _manager(db_session)
    # Original, demoted by a prior admin "activate_as_original" on the amendment.
    f_orig = Filing13F(
        manager_id=manager.id, accession_no="O5", accession_number="O5",
        form_type="13F-HR", period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 15), quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=False, is_latest_for_period=False,
    )
    # NEW_HOLDINGS amendment an admin resolved as the active filing.
    f_amend = Filing13F(
        manager_id=manager.id, accession_no="A5", accession_number="A5",
        form_type="13F-HR/A", period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 16), quarter_end_date=date(2024, 3, 31),
        is_latest_for_period=True, is_amendment=True,
        amendment_type="NEW_HOLDINGS", amendment_status="applied",
        is_active_for_manager_period=True,
    )
    db_session.add_all([f_orig, f_amend])
    db_session.flush()

    # Simulate the bulk re-ingest's Phase 2.5 pass 2 (policy for every filing).
    apply_amendment_policy(db_session, f_orig)
    apply_amendment_policy(db_session, f_amend)
    db_session.flush()

    # The admin's resolution survives — the amendment stays active/applied and
    # the superseded original stays inactive.
    assert f_amend.is_active_for_manager_period is True
    assert f_amend.amendment_status == "applied"
    assert f_orig.is_active_for_manager_period is False
