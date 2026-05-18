from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count
from unittest import mock

import pytest

from app.models.institutions import (
    CusipTickerMap,
    Filing13F,
    Holding13F,
    InstitutionManager,
    OwnershipChange13F,
    ParseRun13F,
    QualityFinding13F,
    QualityReport13F,
)
from app.models.users import User
from app.services.thirteenf_corporate_action_mapping import (
    CorporateActionMappingError,
    confirm_corporate_action_mapping,
    preview_corporate_action_confirmation,
)
from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing


_CIK_SEQ = count(9920000000)
_ACC_SEQ = count(1)
_CUSIP_SEQ = count(100000001)
_OWNERSHIP_ROW_SEQ = count(1)


def _next_accession() -> str:
    return f"0009920001-26-{next(_ACC_SEQ):06d}"


def _next_cusip() -> str:
    return f"{next(_CUSIP_SEQ):09d}"


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK_SEQ)).zfill(10)
    manager = InstitutionManager(
        canonical_name=f"Corp Action Manager {cik}",
        legal_name=f"Corp Action Manager {cik}",
        edgar_legal_name=f"Corp Action Manager {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _reviewer(db_session) -> User:
    user = User(email=f"corp-action-reviewer-{next(_CIK_SEQ)}@example.com", role="admin")
    db_session.add(user)
    db_session.flush()
    return user


def _filing(db_session, manager: InstitutionManager, *, quarter: str = "2024-Q1") -> Filing13F:
    accession = _next_accession()
    year, qtr = quarter.split("-Q")
    period_end_month = int(qtr) * 3
    period_end = date(int(year), period_end_month, 30 if period_end_month in (6, 9) else 31)
    filing = Filing13F(
        manager_id=manager.id,
        cik=manager.cik,
        accession_no=accession,
        accession_number=accession,
        form_type="13F-HR",
        period_of_report=period_end,
        filed_at=period_end,
        filing_date=period_end,
        accepted_at=datetime(period_end.year, period_end.month, period_end.day, 17, tzinfo=timezone.utc),
        report_quarter=quarter,
        quarter_end_date=period_end,
        is_active_for_manager_period=True,
        parse_status="succeeded",
        report_type="holdings_report",
        coverage_completeness="complete",
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _ownership_change(
    db_session,
    *,
    manager: InstitutionManager,
    filing: Filing13F,
    cusip_current: str | None,
    cusip_previous: str | None,
    quarter: str,
    change_status: str = "increased",
) -> OwnershipChange13F:
    qtr = quarter.split("-Q")[1]
    period_end_month = int(qtr) * 3
    period_end = date(int(quarter.split("-Q")[0]), period_end_month, 30 if period_end_month in (6, 9) else 31)
    row = OwnershipChange13F(
        manager_id=manager.id,
        report_quarter=quarter,
        quarter_end_date=period_end,
        current_filing_id=filing.id,
        security_key=f"sec-{next(_OWNERSHIP_ROW_SEQ)}",
        current_cusip=cusip_current,
        previous_cusip=cusip_previous,
        change_status=change_status,
        confidence_level="high_confidence",
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_confirm_requires_evidence_url(db_session):
    reviewer = _reviewer(db_session)
    cusip = _next_cusip()
    with pytest.raises(CorporateActionMappingError, match="evidence_url"):
        confirm_corporate_action_mapping(
            db_session,
            cusip=cusip,
            new_ticker="ABCD",
            new_issuer_name="Newco Inc.",
            effective_from_quarter="2024-Q3",
            evidence_url="",
            reason="Spin-off completed.",
            reviewer_id=reviewer.id,
        )


def test_confirm_requires_reason(db_session):
    reviewer = _reviewer(db_session)
    cusip = _next_cusip()
    with pytest.raises(CorporateActionMappingError, match="reason"):
        confirm_corporate_action_mapping(
            db_session,
            cusip=cusip,
            new_ticker="ABCD",
            new_issuer_name="Newco Inc.",
            effective_from_quarter="2024-Q3",
            evidence_url="https://sec.example/8-K-2024-07",
            reason="   ",
            reviewer_id=reviewer.id,
        )


def test_confirm_creates_new_mapping_with_audit_fields(db_session):
    reviewer = _reviewer(db_session)
    cusip = _next_cusip()
    before_count = db_session.query(CusipTickerMap).filter_by(cusip=cusip).count()

    result = confirm_corporate_action_mapping(
        db_session,
        cusip=cusip,
        new_ticker="NEWT",
        new_issuer_name="Newco Inc.",
        effective_from_quarter="2024-Q3",
        evidence_url="https://sec.example/8-K-2024-07",
        reason="Stock split via parent's 8-K (2024-07-15) recorded.",
        reviewer_id=reviewer.id,
    )

    after_count = db_session.query(CusipTickerMap).filter_by(cusip=cusip).count()
    assert after_count == before_count + 1

    new_mapping = db_session.get(CusipTickerMap, result["new_mapping_id"])
    assert new_mapping.cusip == cusip
    assert new_mapping.ticker == "NEWT"
    assert new_mapping.issuer_name == "Newco Inc."
    assert new_mapping.source == "manual"
    assert new_mapping.mapping_status == "confirmed"
    assert new_mapping.confidence == "manual"
    assert new_mapping.effective_from_quarter == "2024-Q3"
    assert new_mapping.effective_to_quarter is None
    assert new_mapping.evidence_url == "https://sec.example/8-K-2024-07"
    assert "Stock split" in (new_mapping.mapping_reason or "")
    assert new_mapping.reviewed_by == reviewer.id
    assert new_mapping.reviewed_at is not None
    assert result["prior_mapping_id"] is None


def test_confirm_rejects_prior_mapping_for_different_cusip(db_session):
    """Security invariant: ``prior_mapping_id`` must belong to the CUSIP being
    confirmed. Otherwise a confirm call for CUSIP A could supersede CUSIP B's
    mapping history.
    """
    reviewer = _reviewer(db_session)
    cusip_a = _next_cusip()
    cusip_b = _next_cusip()
    foreign_mapping = CusipTickerMap(
        cusip=cusip_b,
        ticker="OTHR",
        issuer_name="Otherco Inc.",
        source="openfigi",
        mapping_status="confirmed",
        confidence="high",
        effective_from_quarter="2023-Q1",
        effective_to_quarter=None,
        is_active=True,
    )
    db_session.add(foreign_mapping)
    db_session.flush()

    with pytest.raises(CorporateActionMappingError, match="does not belong"):
        confirm_corporate_action_mapping(
            db_session,
            cusip=cusip_a,
            new_ticker="NEWT",
            new_issuer_name="Newco Inc.",
            effective_from_quarter="2024-Q3",
            evidence_url="https://sec.example/8-K-2024-07",
            reason="Cross-CUSIP supersede attempt — must be rejected.",
            reviewer_id=reviewer.id,
            prior_mapping_id=foreign_mapping.id,
        )

    # The foreign mapping must remain untouched.
    db_session.expire_all()
    refreshed = db_session.get(CusipTickerMap, foreign_mapping.id)
    assert refreshed.mapping_status == "confirmed"
    assert refreshed.effective_to_quarter is None
    # No new mapping was inserted for cusip_a.
    assert db_session.query(CusipTickerMap).filter_by(cusip=cusip_a).count() == 0


def test_confirm_supersedes_prior_mapping(db_session):
    reviewer = _reviewer(db_session)
    cusip = _next_cusip()
    prior = CusipTickerMap(
        cusip=cusip,
        ticker="OLDT",
        issuer_name="Oldco Inc.",
        source="openfigi",
        mapping_status="confirmed",
        confidence="high",
        effective_from_quarter="2023-Q1",
        effective_to_quarter=None,
        is_active=True,
    )
    db_session.add(prior)
    db_session.flush()

    result = confirm_corporate_action_mapping(
        db_session,
        cusip=cusip,
        new_ticker="NEWT",
        new_issuer_name="Newco Inc.",
        effective_from_quarter="2024-Q3",
        evidence_url="https://sec.example/8-K-2024-07",
        reason="Spin-off completed; identity rolls to NEWT.",
        reviewer_id=reviewer.id,
        prior_mapping_id=prior.id,
    )

    refreshed_prior = db_session.get(CusipTickerMap, prior.id)
    assert refreshed_prior.mapping_status == "superseded"
    assert refreshed_prior.effective_to_quarter == "2024-Q2"
    new_mapping = db_session.get(CusipTickerMap, result["new_mapping_id"])
    assert new_mapping.effective_from_quarter == "2024-Q3"
    assert new_mapping.mapping_status == "confirmed"
    assert result["prior_mapping_id"] == prior.id


def test_confirm_rejects_overlapping_active_mapping(db_session):
    reviewer = _reviewer(db_session)
    cusip = _next_cusip()
    existing = CusipTickerMap(
        cusip=cusip,
        ticker="EXST",
        source="openfigi",
        mapping_status="confirmed",
        confidence="high",
        effective_from_quarter="2023-Q1",
        effective_to_quarter="2025-Q4",
        is_active=True,
    )
    db_session.add(existing)
    db_session.flush()

    with pytest.raises(CorporateActionMappingError, match="overlap"):
        confirm_corporate_action_mapping(
            db_session,
            cusip=cusip,
            new_ticker="NEWT",
            new_issuer_name="Newco Inc.",
            effective_from_quarter="2024-Q2",
            effective_to_quarter="2024-Q4",
            evidence_url="https://sec.example/8-K-2024-07",
            reason="Conflict test — should not commit.",
            reviewer_id=reviewer.id,
        )


def test_confirm_handles_null_end_quarter_as_open_ended_overlap(db_session):
    reviewer = _reviewer(db_session)
    cusip = _next_cusip()
    existing = CusipTickerMap(
        cusip=cusip,
        ticker="EXST",
        source="openfigi",
        mapping_status="confirmed",
        confidence="high",
        effective_from_quarter="2023-Q1",
        effective_to_quarter=None,
        is_active=True,
    )
    db_session.add(existing)
    db_session.flush()

    with pytest.raises(CorporateActionMappingError, match="overlap"):
        confirm_corporate_action_mapping(
            db_session,
            cusip=cusip,
            new_ticker="NEWT",
            new_issuer_name="Newco Inc.",
            effective_from_quarter="2024-Q3",
            evidence_url="https://sec.example/8-K-2024-07",
            reason="Open-ended overlap rejection.",
            reviewer_id=reviewer.id,
        )


def test_confirm_invalidates_affected_ownership_changes_without_mutation(db_session):
    """D4: confirmed mapping must invalidate affected ownership_changes via an audit
    trail (QualityFinding rows), NOT by mutating change_status / value_usd / shares.
    """
    reviewer = _reviewer(db_session)
    manager = _manager(db_session)
    cusip = _next_cusip()
    other_cusip = _next_cusip()

    filing_q2 = _filing(db_session, manager, quarter="2024-Q2")
    filing_q3 = _filing(db_session, manager, quarter="2024-Q3")
    filing_q4 = _filing(db_session, manager, quarter="2024-Q4")
    affected_in_range = _ownership_change(
        db_session,
        manager=manager,
        filing=filing_q3,
        cusip_current=cusip,
        cusip_previous=cusip,
        quarter="2024-Q3",
        change_status="increased",
    )
    affected_via_previous = _ownership_change(
        db_session,
        manager=manager,
        filing=filing_q4,
        cusip_current=other_cusip,
        cusip_previous=cusip,
        quarter="2024-Q4",
        change_status="cusip_changed",
    )
    outside_range = _ownership_change(
        db_session,
        manager=manager,
        filing=filing_q2,
        cusip_current=cusip,
        cusip_previous=cusip,
        quarter="2024-Q2",
        change_status="increased",
    )
    unrelated = _ownership_change(
        db_session,
        manager=manager,
        filing=filing_q3,
        cusip_current=other_cusip,
        cusip_previous=other_cusip,
        quarter="2024-Q3",
        change_status="increased",
    )

    before_change_statuses = {
        row.id: row.change_status
        for row in db_session.query(OwnershipChange13F).all()
    }
    before_value_usd = {
        row.id: row.current_value_usd
        for row in db_session.query(OwnershipChange13F).all()
    }

    result = confirm_corporate_action_mapping(
        db_session,
        cusip=cusip,
        new_ticker="NEWT",
        new_issuer_name="Newco Inc.",
        effective_from_quarter="2024-Q3",
        effective_to_quarter="2024-Q4",
        evidence_url="https://sec.example/8-K-2024-07",
        reason="Spin-off effective 2024-Q3; affects Q3 and Q4 holdings.",
        reviewer_id=reviewer.id,
    )

    # Ownership_changes rows are NOT mutated
    db_session.expire_all()
    for row in db_session.query(OwnershipChange13F).all():
        assert row.change_status == before_change_statuses[row.id]
        assert row.current_value_usd == before_value_usd[row.id]

    # QualityReport + per-row QualityFinding rows were written
    report = db_session.get(QualityReport13F, result["quality_report_id"])
    assert report is not None
    assert report.status in {"warning", "passed", "failed"}
    findings = (
        db_session.query(QualityFinding13F)
        .filter(QualityFinding13F.validation_run_id == report.id)
        .all()
    )
    flagged_entity_ids = {f.entity_id for f in findings if f.entity_type == "ownership_change"}
    assert affected_in_range.id in flagged_entity_ids
    assert affected_via_previous.id in flagged_entity_ids
    assert outside_range.id not in flagged_entity_ids
    assert unrelated.id not in flagged_entity_ids
    for finding in findings:
        assert finding.rule_code == "OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION"
        assert finding.severity == "warning"
        assert finding.status == "open"
    assert result["affected_ownership_changes_count"] == 2


def test_preview_does_not_mutate(db_session):
    reviewer = _reviewer(db_session)
    manager = _manager(db_session)
    cusip = _next_cusip()
    filing_q3 = _filing(db_session, manager, quarter="2024-Q3")
    _ownership_change(
        db_session,
        manager=manager,
        filing=filing_q3,
        cusip_current=cusip,
        cusip_previous=cusip,
        quarter="2024-Q3",
    )

    before_mappings = db_session.query(CusipTickerMap).count()
    before_reports = db_session.query(QualityReport13F).count()
    before_findings = db_session.query(QualityFinding13F).count()

    preview = preview_corporate_action_confirmation(
        db_session,
        cusip=cusip,
        effective_from_quarter="2024-Q3",
    )

    assert preview["affected_ownership_changes_count"] == 1
    assert db_session.query(CusipTickerMap).count() == before_mappings
    assert db_session.query(QualityReport13F).count() == before_reports
    assert db_session.query(QualityFinding13F).count() == before_findings
    # reviewer object only used to make sure preview never touches user fields
    assert db_session.get(User, reviewer.id) is not None


def test_endpoint_requires_admin(client, db_session, user_factory, auth_headers):
    non_admin = user_factory(email="not-an-admin@example.com", role="user")
    response = client.post(
        "/api/v1/admin/13f/cusips/corporate-actions/preview",
        headers=auth_headers(non_admin),
        json={"cusip": "000000001", "effective_from_quarter": "2024-Q3"},
    )
    assert response.status_code in (401, 403)


def test_endpoint_confirm_happy_path(client, db_session, user_factory, auth_headers):
    admin = user_factory(email="admin-corp-action@example.com", role="admin")
    cusip = _next_cusip()

    response = client.post(
        "/api/v1/admin/13f/cusips/corporate-actions/confirm",
        headers=auth_headers(admin),
        json={
            "cusip": cusip,
            "new_ticker": "NEWT",
            "new_issuer_name": "Newco Inc.",
            "effective_from_quarter": "2024-Q3",
            "evidence_url": "https://sec.example/8-K-2024-07",
            "reason": "Spin-off effective 2024-Q3.",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["affected_ownership_changes_count"] >= 0
    new_mapping = db_session.get(CusipTickerMap, payload["new_mapping_id"])
    assert new_mapping is not None
    assert new_mapping.mapping_status == "confirmed"
    assert new_mapping.reviewed_by == admin.id
