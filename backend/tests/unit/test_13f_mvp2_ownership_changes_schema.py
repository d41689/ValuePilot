from datetime import date

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models.institutions import (
    OWNERSHIP_CHANGE_STATUSES,
    OWNERSHIP_SIGNAL_CONFIDENCE_LEVELS,
    InstitutionManager,
    OwnershipChange13F,
)
from app.models.stocks import Stock


def _manager(db_session) -> InstitutionManager:
    manager = InstitutionManager(
        canonical_name="MVP 2 Manager",
        legal_name="MVP 2 Manager",
        cik="0009000001",
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session) -> Stock:
    stock = Stock(ticker="AAPL", exchange="NASDAQ", company_name="Apple Inc.")
    db_session.add(stock)
    db_session.flush()
    return stock


def _ownership_change(db_session, manager: InstitutionManager, stock: Stock, **overrides) -> OwnershipChange13F:
    payload = {
        "manager_id": manager.id,
        "stock_id": stock.id,
        "report_quarter": "2026-Q1",
        "quarter_end_date": date(2026, 3, 31),
        "previous_report_quarter": "2025-Q4",
        "previous_quarter_end_date": date(2025, 12, 31),
        "security_key": f"stock:{stock.id}",
        "current_cusip": "037833100",
        "previous_cusip": "037833100",
        "ssh_prnamt_type": "SH",
        "position_type": "common",
        "change_status": "increased",
        "confidence_level": "high_confidence",
        "is_primary_signal_eligible": True,
        "caveat_codes": [],
    }
    payload.update(overrides)
    row = OwnershipChange13F(**payload)
    db_session.add(row)
    db_session.flush()
    return row


def test_ownership_changes_schema_columns_and_indexes_exist(db_session):
    inspector = inspect(db_session.bind)

    columns = {column["name"] for column in inspector.get_columns("ownership_changes")}
    assert {
        "id",
        "manager_id",
        "stock_id",
        "report_quarter",
        "quarter_end_date",
        "previous_report_quarter",
        "previous_quarter_end_date",
        "current_filing_id",
        "previous_filing_id",
        "current_holding_id",
        "previous_holding_id",
        "current_parse_run_id",
        "previous_parse_run_id",
        "security_key",
        "current_cusip",
        "previous_cusip",
        "ssh_prnamt_type",
        "put_call",
        "position_type",
        "change_status",
        "confidence_level",
        "is_primary_signal_eligible",
        "caveat_codes",
        "unavailable_reason",
        "current_value_usd",
        "previous_value_usd",
        "value_delta_usd",
        "value_delta_pct",
        "current_shares",
        "previous_shares",
        "share_delta",
        "share_change_pct",
        "current_portfolio_weight_pct",
        "previous_portfolio_weight_pct",
        "mapping_confidence",
        "attribution_status",
        "has_confidential_treatment_caveat",
        "has_combination_report_caveat",
        "has_pending_amendment_caveat",
        "created_at",
        "updated_at",
    } <= columns

    indexes = {index["name"] for index in inspector.get_indexes("ownership_changes")}
    assert "uq_ownership_changes_manager_quarter_security_position" in indexes
    assert "idx_ownership_changes_stock_quarter" in indexes
    assert "idx_ownership_changes_manager_quarter" in indexes
    assert "idx_ownership_changes_change_status" in indexes
    assert "idx_ownership_changes_confidence" in indexes
    assert "idx_ownership_changes_primary_signal" in indexes


@pytest.mark.parametrize("status", sorted(OWNERSHIP_CHANGE_STATUSES))
def test_ownership_change_status_accepts_decision_gate_values(status):
    row = OwnershipChange13F(
        manager_id=1,
        report_quarter="2026-Q1",
        quarter_end_date=date(2026, 3, 31),
        security_key="stock:1",
        position_type="common",
        change_status=status,
        confidence_level="high_confidence",
    )

    assert row.change_status == status


@pytest.mark.parametrize("confidence", sorted(OWNERSHIP_SIGNAL_CONFIDENCE_LEVELS))
def test_ownership_signal_confidence_accepts_decision_gate_values(confidence):
    row = OwnershipChange13F(
        manager_id=1,
        report_quarter="2026-Q1",
        quarter_end_date=date(2026, 3, 31),
        security_key="stock:1",
        position_type="common",
        change_status="unchanged",
        confidence_level=confidence,
    )

    assert row.confidence_level == confidence


def test_ownership_change_rejects_unknown_statuses():
    with pytest.raises(ValueError):
        OwnershipChange13F(
            manager_id=1,
            report_quarter="2026-Q1",
            quarter_end_date=date(2026, 3, 31),
            security_key="stock:1",
            position_type="common",
            change_status="buy_signal",
            confidence_level="high_confidence",
        )

    with pytest.raises(ValueError):
        OwnershipChange13F(
            manager_id=1,
            report_quarter="2026-Q1",
            quarter_end_date=date(2026, 3, 31),
            security_key="stock:1",
            position_type="common",
            change_status="unchanged",
            confidence_level="certain",
        )


def test_ownership_change_unique_manager_quarter_security_position(db_session):
    manager = _manager(db_session)
    stock = _stock(db_session)
    _ownership_change(db_session, manager, stock)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            _ownership_change(db_session, manager, stock, change_status="reduced")

    _ownership_change(db_session, manager, stock, ssh_prnamt_type="PRN", change_status="unchanged")
