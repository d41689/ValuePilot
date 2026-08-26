from __future__ import annotations

from datetime import date, datetime, timezone

from app.models.institutions import (
    Filing13F,
    InstitutionManager,
    NoIndexExpectedDate,
    OwnershipChange13F,
)
from app.models.stocks import Stock
from app.models.notifications import LogicalNotification, ManagerFollow
from app.models.users import NotificationEvent, User
from app.services.thirteenf_filing_season import (
    build_filing_season_digest,
    filing_season_state,
    persist_filing_season_digest,
)


def _value_manager(db_session, *, cik: str = "0009800001") -> InstitutionManager:
    manager = InstitutionManager(
        canonical_name="Patient Value",
        legal_name="Patient Value",
        display_name="Patient Value",
        cik=cik,
        status="active",
        match_status="confirmed",
        manager_type="value_concentrated",
        style_primary="value_concentrated",
        capital_structure="locked_lp",
        historical_turnover="low",
        is_superinvestor=True,
        is_featured=False,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _reported_filing(db_session, manager: InstitutionManager) -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        accession_no="0009800001-26-000001",
        accession_number="0009800001-26-000001",
        cik=manager.cik,
        period_of_report=date(2026, 3, 31),
        quarter_end_date=date(2026, 3, 31),
        report_quarter="2026-Q1",
        filed_at=date(2026, 5, 16),
        filing_date=date(2026, 5, 16),
        accepted_at=datetime(2026, 5, 16, 18, tzinfo=timezone.utc),
        ingested_at=datetime(2026, 5, 16, 19, tzinfo=timezone.utc),
        official_filing_deadline=date(2026, 5, 15),
        form_type="13F-HR",
        report_type="holdings_report",
        coverage_completeness="complete",
        coverage_type="normal",
        parse_status="succeeded",
        is_active_for_manager_period=True,
        is_latest_for_period=True,
        holdings_count=12,
        total_13f_common_value_usd=1_000_000,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _new_position(db_session, manager: InstitutionManager, filing: Filing13F) -> Stock:
    stock = Stock(
        ticker="DIG",
        exchange="NYSE",
        company_name="Digest Corp",
        is_active=True,
    )
    db_session.add(stock)
    db_session.flush()
    db_session.add(
        OwnershipChange13F(
            manager_id=manager.id,
            stock_id=stock.id,
            report_quarter="2026-Q1",
            quarter_end_date=date(2026, 3, 31),
            previous_report_quarter="2025-Q4",
            previous_quarter_end_date=date(2025, 12, 31),
            current_filing_id=filing.id,
            security_key=f"stock:{stock.id}",
            current_cusip="000980001",
            ssh_prnamt_type="SH",
            position_type="common",
            change_status="new_position",
            confidence_level="high_confidence",
            is_primary_signal_eligible=True,
            caveat_codes=[],
            current_value_usd=200_000,
            value_delta_usd=200_000,
            current_shares=2_000,
            share_delta=2_000,
        )
    )
    db_session.flush()
    return stock


def test_filing_season_state_uses_official_deadline_window(db_session):
    state = filing_season_state(db_session, as_of_date=date(2026, 5, 20))
    assert state == {
        "in_season": True,
        "deadline_date": "2026-05-15",
        "days_since_deadline": 5,
        "quarter": "2026-Q1",
    }

    assert filing_season_state(db_session, as_of_date=date(2026, 6, 1))["in_season"] is False


def test_filing_season_state_honors_weekend_and_expected_closure(db_session):
    db_session.add(
        NoIndexExpectedDate(
            date=date(2026, 2, 16),
            reason="federal_holiday",
            holiday_name="Presidents Day",
            source="admin_manual",
            active=True,
        )
    )
    db_session.flush()

    state = filing_season_state(db_session, as_of_date=date(2026, 2, 18))
    assert state["quarter"] == "2025-Q4"
    assert state["deadline_date"] == "2026-02-17"
    assert state["days_since_deadline"] == 1


def test_digest_includes_yesterdays_value_manager_filing_and_top_new_position(db_session):
    manager = _value_manager(db_session)
    filing = _reported_filing(db_session, manager)
    _new_position(db_session, manager, filing)

    digest = build_filing_season_digest(db_session, as_of_date=date(2026, 5, 17))

    assert digest["season"]["in_season"] is True
    assert digest["coverage"] == {
        "reported_manager_count": 1,
        "tracked_manager_count": 1,
    }
    assert digest["digest_date"] == "2026-05-17"
    assert len(digest["items"]) == 1
    assert digest["items"][0]["manager"]["display_name"] == "Patient Value"
    assert digest["items"][0]["holdings_count"] == 12
    assert digest["items"][0]["top_new_positions"][0]["stock"]["ticker"] == "DIG"


def test_digest_persistence_is_one_event_per_user_and_day(db_session):
    manager = _value_manager(db_session, cik="0009800002")
    filing = _reported_filing(db_session, manager)
    _new_position(db_session, manager, filing)
    users = [
        User(email="digest-one@example.com", is_active=True),
        User(email="digest-two@example.com", is_active=True),
    ]
    db_session.add_all(users)
    db_session.flush()
    db_session.add_all(
        [ManagerFollow(user_id=user.id, manager_id=manager.id) for user in users]
    )
    db_session.flush()

    first = persist_filing_season_digest(db_session, as_of_date=date(2026, 5, 17))
    second = persist_filing_season_digest(db_session, as_of_date=date(2026, 5, 17))

    assert first == {"status": "persisted", "created": 2, "existing": 0}
    assert second == {"status": "persisted", "created": 0, "existing": 2}
    events = db_session.query(NotificationEvent).filter(
        NotificationEvent.event_type == "thirteenf_filing_season_digest"
    ).all()
    assert len(events) == 2
    assert {event.payload_json["digest_date"] for event in events} == {"2026-05-17"}
    logical = db_session.query(LogicalNotification).filter_by(
        event_family="filing_season_digest"
    ).all()
    assert len(logical) == 2
    assert all(row.evidence_route == "/13f/oracles-lens#filing-season-digest" for row in logical)


def test_empty_user_scope_keeps_legacy_snapshot_without_noisy_logical_alert(
    db_session,
):
    manager = _value_manager(db_session, cik="0009800003")
    filing = _reported_filing(db_session, manager)
    _new_position(db_session, manager, filing)
    db_session.add(User(email="digest-empty@example.com", is_active=True))
    db_session.flush()

    result = persist_filing_season_digest(
        db_session, as_of_date=date(2026, 5, 17)
    )

    assert result["created"] == 1
    assert db_session.query(NotificationEvent).count() == 1
    assert db_session.query(LogicalNotification).count() == 0
