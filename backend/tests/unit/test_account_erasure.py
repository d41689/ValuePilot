from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models.auth_tokens import RefreshToken
from app.models.artifacts import DocumentPage, PdfDocument
from app.models.coverage import ResearchCoverageRequirement
from app.models.extractions import MetricExtraction
from app.models.facts import CalculatedRun, Formula, MetricFact, ScreeningRule
from app.models.notifications import (
    LogicalNotification,
    NotificationDeliveryAttempt,
    NotificationDeliveryEvent,
    NotificationDestination,
    NotificationInboxState,
    NotificationPriceAlertState,
    NotificationSubscription,
)
from app.models.portfolios import PositionJournalEvent
from app.models.research import (
    ResearchCase,
    ResearchCaseEvent,
    ResearchCaseOrigin,
    ResearchCaseRevision,
    ResearchInboxAction,
    ResearchInboxActionEvent,
)
from app.models.stocks import PoolMembership, PriceAlert, Stock, StockPool
from app.models.users import (
    AccountErasureEvent,
    AccountErasureFileDeletion,
    NotificationEvent,
    NotificationSettings,
)
from app.core.config import settings
from app.schemas.portfolios import ManualPortfolioCreate, ManualPositionCreate
from app.services.manual_portfolios import create_portfolio, create_position
from app.services.account_erasure import (
    erase_account,
    process_pending_account_erasure_file_deletions,
)
from app.services.formula_engine import FormulaEngine
from app.services.research_cases import redact_revision


def test_account_erasure_revokes_credentials_and_tombstones_authored_content(
    client, db_session, user_factory, auth_headers, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    user = user_factory(
        "erase-me@example.com",
        password="ErasePass123!",
    )
    stock = Stock(ticker="ERASE", exchange="NYSE", company_name="Erase Corp")
    db_session.add(stock)
    db_session.flush()
    retained_pdf = tmp_path / "private-value-line.pdf"
    retained_pdf.write_bytes(b"private proprietary report")
    document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="private-value-line.pdf",
        source="Value Line",
        file_storage_key=str(retained_pdf),
        parse_status="parsed",
        raw_text="private report text",
        notes="private note",
    )
    db_session.add(document)
    db_session.flush()
    page = DocumentPage(
        document_id=document.id,
        page_number=1,
        page_text="private page text",
        page_image_key="private/page.png",
        text_extraction_method="native_text",
    )
    extraction = MetricExtraction(
        user_id=user.id,
        document_id=document.id,
        page_number=1,
        field_key="is.net_income",
        raw_value_text="123",
        original_text_snippet="Net income 123",
        parsed_value_json={"value": 123},
        bbox_json={"x": 1},
    )
    db_session.add_all([page, extraction])
    case = ResearchCase(
        user_id=user.id,
        stock_id=stock.id,
        state="monitoring",
        decision="own",
        next_review_on=date(2026, 10, 1),
        head_revision_number=1,
    )
    db_session.add(case)
    db_session.flush()
    revision = ResearchCaseRevision(
        case_id=case.id,
        revision_number=1,
        thesis="Private thesis content",
        variant_view="Private disconfirming content",
        decision_reason="Private decision reason",
        assumptions_json=[{"secret": "private assumption"}],
        risks_json=[{"secret": "private risk"}],
        evidence_json=[{"source_type": "user_note", "label": "Private note", "claim": "Private"}],
        case_state="monitoring",
        valuation_low=Decimal("80"),
        valuation_base=Decimal("100"),
        valuation_high=Decimal("120"),
        valuation_currency="USD",
        valuation_as_of_date=date(2026, 7, 20),
        decision="own",
        next_review_on=date(2026, 10, 1),
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        created_by_user_id=user.id,
    )
    db_session.add(revision)
    portfolio = create_portfolio(
        db_session,
        user_id=user.id,
        payload=ManualPortfolioCreate(
            name="Private portfolio",
            description="Private portfolio description",
        ),
    )
    position = create_position(
        db_session,
        user_id=user.id,
        portfolio_id=portfolio.id,
        payload=ManualPositionCreate(
            stock_id=stock.id,
            quantity=Decimal("12.5"),
            average_unit_cost=Decimal("88.25"),
            currency="USD",
            opened_on=date(2026, 7, 1),
            reason="Private position reason",
        ),
    )
    destination = NotificationDestination(
        user_id=user.id,
        channel="slack",
        label="Private Slack",
        destination_hint="hooks.slack.com/…/cret",
        secret_ciphertext="encrypted-secret",
        key_version="v1",
        status="enabled",
        consented_at=datetime.now(timezone.utc),
    )
    token = RefreshToken(
        jti="erase-token-jti",
        user_id=user.id,
        family_id="erase-token-family",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add_all([destination, token])
    db_session.commit()

    response = client.post(
        "/api/v1/users/me/erase",
        headers=auth_headers(user),
        json={
            "password": "ErasePass123!",
            "confirmation": "ERASE MY ACCOUNT",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "erased"
    assert payload["documents_tombstoned"] == 1
    assert payload["file_deletions_queued"] == 1
    assert payload["file_deletions_deleted"] == 1
    assert payload["file_deletions_failed"] == 0
    assert payload["file_deletions_retained_shared"] == 0
    db_session.refresh(user)
    db_session.refresh(revision)
    db_session.refresh(position)
    db_session.refresh(destination)
    db_session.refresh(token)
    assert user.is_active is False
    assert user.email == f"erased-{user.id}@deleted.invalid"
    assert revision.is_redacted is True
    assert revision.thesis == "[redacted]"
    assert revision.assumptions_json == []
    assert position.state == "closed"
    assert position.quantity == 0
    assert position.average_unit_cost is None
    event = db_session.query(PositionJournalEvent).filter_by(position_id=position.id).one()
    assert event.reason is None
    assert event.prior_quantity is None
    assert event.new_quantity is None
    assert destination.status == "revoked"
    assert destination.secret_ciphertext == "[revoked]"
    assert token.revoked_at is not None
    assert token.revoked_reason == "account_erasure"
    db_session.refresh(document)
    db_session.refresh(page)
    db_session.refresh(extraction)
    assert document.lifecycle_state == "erased"
    assert document.retirement_reason == "account_erasure"
    assert document.file_name == f"erased-document-{document.id}"
    assert document.source == "account_erasure_tombstone"
    assert document.raw_text is None
    assert document.notes is None
    assert document.file_storage_key == f"erased/document/{document.id}"
    assert retained_pdf.exists() is False
    assert page.page_text is None
    assert page.page_image_key is None
    assert extraction.raw_value_text is None
    assert extraction.original_text_snippet is None
    assert extraction.parsed_value_json is None
    assert extraction.bbox_json is None
    audit = db_session.query(AccountErasureEvent).filter_by(user_id=user.id).one()
    assert audit.content_hash
    deletion = db_session.query(AccountErasureFileDeletion).filter_by(
        document_id=document.id
    ).one()
    assert deletion.status == "deleted"
    assert deletion.storage_path == "[deleted]"
    assert deletion.storage_path_hash
    assert client.get("/api/v1/research/cases", headers=auth_headers(user)).status_code == 403


def test_account_erasure_requires_password_and_exact_confirmation(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("erase-reject@example.com", password="ErasePass123!")
    response = client.post(
        "/api/v1/users/me/erase",
        headers=auth_headers(user),
        json={"password": "wrong-password", "confirmation": "ERASE MY ACCOUNT"},
    )
    assert response.status_code == 403
    db_session.refresh(user)
    assert user.is_active is True


def test_account_erasure_finishes_revision_that_was_already_normally_redacted(
    db_session, user_factory
):
    user = user_factory("erase-pre-redacted@example.com", password="ErasePass123!")
    stock = Stock(
        ticker="ERPRE",
        exchange="NYSE",
        company_name="Pre-redacted Revision Corp",
    )
    db_session.add(stock)
    db_session.flush()
    case = ResearchCase(
        user_id=user.id,
        stock_id=stock.id,
        state="monitoring",
        decision="own",
        next_review_on=date(2026, 10, 1),
        head_revision_number=1,
    )
    db_session.add(case)
    db_session.flush()
    revision = ResearchCaseRevision(
        case_id=case.id,
        revision_number=1,
        thesis="Private thesis",
        assumptions_json=[],
        risks_json=[],
        evidence_json=[],
        case_state="monitoring",
        valuation_low=Decimal("80"),
        valuation_base=Decimal("100"),
        valuation_high=Decimal("120"),
        valuation_currency="USD",
        valuation_as_of_date=date(2026, 8, 1),
        decision="own",
        next_review_on=date(2026, 10, 1),
        is_qualified_decision=True,
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        created_by_user_id=user.id,
    )
    db_session.add(revision)
    db_session.commit()

    redact_revision(
        db_session,
        user_id=user.id,
        case_id=case.id,
        revision_number=1,
        reason="user_requested_redaction",
    )
    db_session.refresh(revision)
    original_hash = revision.redaction_content_hash
    original_reason = revision.redaction_reason
    original_redacted_at = revision.redacted_at
    assert revision.is_redacted is True
    assert revision.valuation_base == Decimal("100")

    result = erase_account(db_session, user=user, password="ErasePass123!")

    assert result["status"] == "erased"
    db_session.refresh(revision)
    assert revision.valuation_low is None
    assert revision.valuation_base is None
    assert revision.valuation_high is None
    assert revision.valuation_currency is None
    assert revision.valuation_as_of_date is None
    assert revision.decision is None
    assert revision.next_review_on is None
    assert revision.is_qualified_decision is False
    assert revision.redaction_content_hash == original_hash
    assert revision.redaction_reason == original_reason
    assert revision.redacted_at == original_redacted_at


def test_completed_account_erasure_is_database_write_barrier(
    db_session, user_factory
):
    user = user_factory("erase-write-barrier@example.com", password="ErasePass123!")
    other_user = user_factory(
        "erase-ledger-move-target@example.com", password="ErasePass123!"
    )
    stock = Stock(
        ticker="ERBAR",
        exchange="NYSE",
        company_name="Erasure Barrier Corp",
    )
    db_session.add(stock)
    db_session.flush()
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    db_session.commit()
    user_id = user.id
    stock_id = stock.id
    case_id = case.id

    erase_account(db_session, user=user, password="ErasePass123!")

    db_session.execute(
        text("SELECT set_config('valuepilot.account_erasure', 'on', true)")
    )
    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text(
                """
                UPDATE account_erasure_events
                   SET user_id = :other_user_id,
                       content_hash = repeat('f', 64),
                       summary_json = '{"forged": true}'::jsonb
                 WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id, "other_user_id": other_user.id},
        )
    db_session.rollback()

    event = db_session.query(AccountErasureEvent).filter_by(user_id=user_id).one()
    assert event.content_hash != "f" * 64
    db_session.execute(
        text("SELECT set_config('valuepilot.account_erasure', 'on', true)")
    )
    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text("DELETE FROM account_erasure_events WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
    db_session.rollback()

    with pytest.raises(DBAPIError, match="identity is immutable"):
        db_session.execute(
            text(
                "UPDATE users SET is_active = true, email = 'restored@example.com' "
                "WHERE id = :user_id"
            ),
            {"user_id": user_id},
        )
    db_session.rollback()

    rejected_statements = [
        (
            """
            INSERT INTO research_cases
                (user_id, stock_id, state, head_revision_number, version)
            VALUES (:user_id, :stock_id, 'queued', 0, 1)
            """,
            {"user_id": user_id, "stock_id": stock_id},
        ),
        (
            """
            INSERT INTO research_case_revisions
                (case_id, revision_number, thesis, assumptions_json, risks_json,
                 evidence_json, case_state, is_qualified_decision,
                 snapshot_stock_id, stock_ticker, stock_company_name,
                 stock_exchange, created_by_user_id, is_redacted)
            VALUES
                (:case_id, 1, 'resurrected thesis', '[]'::jsonb, '[]'::jsonb,
                 '[]'::jsonb, 'queued', false, :stock_id, 'ERBAR',
                 'Erasure Barrier Corp', 'NYSE', :user_id, false)
            """,
            {"case_id": case_id, "stock_id": stock_id, "user_id": user_id},
        ),
        (
            """
            INSERT INTO metric_facts
                (user_id, stock_id, metric_key, value_numeric, unit, currency,
                 period_type, period_end_date, source_type, is_current)
            VALUES
                (:user_id, :stock_id, 'val.fair_value', 100, 'USD', 'USD',
                 'AS_OF', DATE '2026-08-28', 'manual', true)
            """,
            {"user_id": user_id, "stock_id": stock_id},
        ),
        (
            """
            INSERT INTO manual_portfolios (user_id, name, status, version)
            VALUES (:user_id, 'resurrected portfolio', 'active', 1)
            """,
            {"user_id": user_id},
        ),
    ]
    for statement, params in rejected_statements:
        with pytest.raises(DBAPIError, match="account erasure"):
            db_session.execute(text(statement), params)
        db_session.rollback()


def test_account_erasure_covers_complete_user_content_graph_and_write_barriers(
    db_session, user_factory
):
    user = user_factory("erase-complete-graph@example.com", password="ErasePass123!")
    stock = Stock(ticker="ERGRAPH", exchange="NYSE", company_name="Erasure Graph Corp")
    db_session.add(stock)
    db_session.flush()
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    db_session.add(case)
    db_session.flush()
    origin = ResearchCaseOrigin(
        case_id=case.id,
        origin_type="manual",
        origin_key="private-origin",
        source_version="user-v1",
        source_ref_json={"private": "origin detail"},
    )
    case_event = ResearchCaseEvent(
        case_id=case.id,
        event_type="case_created",
        actor_user_id=user.id,
        correlation_id="private-case-event",
        payload_json={"private": "case event detail"},
    )
    action = ResearchInboxAction(
        user_id=user.id,
        logical_key="private-action",
        action_family="continue_research",
        subject_type="stock",
        subject_key=str(stock.id),
        source_version="private-v1",
        priority_policy_version="research-priority-v1",
        matched_rule="private-rule",
        priority_rank=1,
        rank_components={"private": 10},
        reason="Private research action reason",
        state="open",
        target_case_id=case.id,
        stock_id=stock.id,
        evidence_json={"private": "research evidence"},
        first_observed_at=datetime.now(timezone.utc),
        last_observed_at=datetime.now(timezone.utc),
    )
    db_session.add_all([origin, case_event, action])
    db_session.flush()
    action_event = ResearchInboxActionEvent(
        action_id=action.id,
        user_id=user.id,
        event_type="created",
        actor_user_id=user.id,
        payload_json={"private": "action event detail"},
    )
    coverage = ResearchCoverageRequirement(
        user_id=user.id,
        stock_id=stock.id,
        kind="valuation_input",
        priority_policy_version="coverage-v1",
        matched_rule="private-coverage-rule",
        priority_rank=1,
        rank_components={"private": 1},
        state="missing",
        reason_code="private_gap",
        reason="Private coverage reason",
        evidence_json={"private": "coverage evidence"},
        freshness_policy_version="freshness-v1",
        evaluated_at=datetime.now(timezone.utc),
        next_action="upload_private_report",
    )
    pool = StockPool(user_id=user.id, name="Private watchlist", description="Private list")
    rule = ScreeningRule(
        user_id=user.id,
        name="Private screen",
        rule_json={"metric": "private", "operator": ">", "value": 1},
    )
    db_session.add_all([action_event, coverage, pool, rule])
    db_session.flush()
    membership = PoolMembership(
        user_id=user.id,
        pool_id=pool.id,
        stock_id=stock.id,
        inclusion_type="manual",
    )
    price_alert = PriceAlert(
        user_id=user.id,
        pool_id=pool.id,
        stock_id=stock.id,
        target_price=100,
        tolerance_pct=0.05,
        cooldown_hours=24,
        is_active=True,
    )
    destination = NotificationDestination(
        user_id=user.id,
        channel="slack",
        label="Private destination",
        destination_hint="private destination hint",
        secret_ciphertext="private secret",
        key_version="v1",
        status="enabled",
        consented_at=datetime.now(timezone.utc),
    )
    logical = LogicalNotification(
        user_id=user.id,
        event_family="research_review_due",
        subject_type="research_case",
        subject_key=str(case.id),
        logical_key="private-notification",
        source_version="private-v1",
        case_id=case.id,
        stock_id=stock.id,
        title="Private notification title",
        body="Private notification body",
        evidence_route="/private/evidence",
        payload_json={"private": "notification payload"},
        severity="warning",
    )
    settings_row = NotificationSettings(
        user_id=user.id,
        channel="email",
        frequency="daily_summary",
        send_time_local="09:00",
        timezone="America/Chicago",
        is_enabled=True,
    )
    legacy_notification = NotificationEvent(
        user_id=user.id,
        event_type="daily_summary",
        payload_json={"private": "legacy notification"},
    )
    db_session.add_all(
        [membership, price_alert, destination, logical, settings_row, legacy_notification]
    )
    db_session.flush()
    subscription = NotificationSubscription(
        user_id=user.id,
        event_family="research_review_due",
        destination_id=destination.id,
        frequency="daily_digest",
        timezone="America/Chicago",
        cooldown_minutes=60,
        hysteresis_ratio=Decimal("0.02"),
        is_enabled=True,
    )
    inbox_state = NotificationInboxState(
        logical_notification_id=logical.id,
        user_id=user.id,
    )
    attempt = NotificationDeliveryAttempt(
        logical_notification_id=logical.id,
        destination_id=destination.id,
        content_version=1,
        status="succeeded",
        scheduled_for=datetime.now(timezone.utc),
        next_attempt_at=datetime.now(timezone.utc),
        provider_response_class="private provider response",
        succeeded_at=datetime.now(timezone.utc),
    )
    alert_state = NotificationPriceAlertState(
        user_id=user.id,
        stock_id=stock.id,
        last_side="above",
        consecutive_fresh_count=2,
        last_threshold_ratio=Decimal("0.10"),
        last_hysteresis_ratio=Decimal("0.02"),
    )
    formula_document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="private-formula-input.pdf",
        source="upload",
        file_storage_key="test/erasure/private-formula-input.pdf",
        parse_status="parsed",
    )
    db_session.add(formula_document)
    db_session.flush()
    formula_extraction = MetricExtraction(
        user_id=user.id,
        document_id=formula_document.id,
        page_number=1,
        field_key="private_formula_input",
        raw_value_text="2",
        original_text_snippet="Private formula input 2",
        parsed_value_json={"value": 2},
        parser_version="v1",
        parse_generation=formula_document.current_parse_generation,
        resolved_stock_id=stock.id,
        mapping_version="value-line-v2",
        canonical_projections_json=[
            {
                "metric_key": "private_formula_input",
                "value_numeric": 2,
                "value_text": None,
                "value_json": None,
                "unit": None,
                "currency": None,
                "period": "2025",
                "period_type": "FY",
                "period_end_date": "2025-12-31",
                "as_of_date": None,
            }
        ],
    )
    db_session.add(formula_extraction)
    db_session.flush()
    manual_input = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="private_formula_input",
        value_numeric=2,
        period="2025",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="parsed",
        source_document_id=formula_document.id,
        source_ref_id=formula_extraction.id,
        parse_generation=formula_document.current_parse_generation,
        is_current=True,
    )
    formula = Formula(
        user_id=user.id,
        name="Private formula",
        output_key="private_formula_output",
        expression='metric("private_formula_input") * 2',
        dependencies_json=["private_formula_input"],
    )
    db_session.add_all(
        [subscription, inbox_state, attempt, alert_state, manual_input, formula]
    )
    db_session.commit()
    db_session.refresh(attempt)
    delivery_event = NotificationDeliveryEvent(
        attempt_id=attempt.id,
        event_type="succeeded",
        response_class="private response",
        payload_json={"private": "delivery payload"},
    )
    db_session.add(delivery_event)
    db_session.commit()
    assert FormulaEngine(db_session).run_formula(
        formula.id, stock.id, user.id
    ) is not None
    user_id = user.id
    stock_id = stock.id
    case_id = case.id

    result = erase_account(db_session, user=user, password="ErasePass123!")

    assert result["status"] == "erased"
    for model in (
        NotificationInboxState,
        NotificationPriceAlertState,
        ResearchCoverageRequirement,
        PriceAlert,
        PoolMembership,
        StockPool,
        ScreeningRule,
        CalculatedRun,
        Formula,
    ):
        assert db_session.query(model).filter_by(user_id=user_id).count() == 0
    db_session.refresh(subscription)
    assert subscription.is_enabled is False
    assert db_session.query(MetricFact).filter(
        MetricFact.user_id == user_id,
        MetricFact.source_type.in_(["manual", "calculated"]),
    ).count() == 0
    assert db_session.query(NotificationEvent).filter_by(user_id=user_id).one().payload_json == {
        "privacy_erased": True
    }
    tombstoned_notification = db_session.query(LogicalNotification).filter_by(
        user_id=user_id
    ).one()
    assert tombstoned_notification.title == "[redacted]"
    assert tombstoned_notification.body == "[redacted]"
    assert tombstoned_notification.payload_json == {"privacy_erased": True}
    assert tombstoned_notification.case_id is None
    assert db_session.query(NotificationDeliveryEvent).filter_by(
        attempt_id=attempt.id
    ).one().payload_json == {"privacy_erased": True}
    assert db_session.query(ResearchCaseOrigin).filter_by(case_id=case_id).one().source_ref_json == {
        "privacy_erased": True
    }
    assert db_session.query(ResearchCaseEvent).filter_by(case_id=case_id).one().payload_json == {
        "privacy_erased": True
    }
    tombstoned_action = db_session.query(ResearchInboxAction).filter_by(
        user_id=user_id
    ).one()
    assert tombstoned_action.reason == "[redacted]"
    assert tombstoned_action.rank_components is None
    assert tombstoned_action.evidence_json == {"privacy_erased": True}
    assert db_session.query(ResearchInboxActionEvent).filter_by(
        user_id=user_id
    ).one().payload_json == {"privacy_erased": True}
    assert db_session.query(NotificationSettings).filter_by(user_id=user_id).count() == 0

    rejected = [
        (
            "INSERT INTO notification_events (user_id,event_type,payload_json) "
            "VALUES (:user_id,'daily_summary','{}'::json)",
            {"user_id": user_id},
        ),
        (
            "INSERT INTO notification_destinations "
            "(user_id,channel,label,destination_hint,secret_ciphertext,key_version,status,consented_at) "
            "VALUES (:user_id,'email','resurrected','private@example.com','secret','v1','enabled',now())",
            {"user_id": user_id},
        ),
        (
            "INSERT INTO notification_subscriptions "
            "(user_id,event_family,frequency,timezone,cooldown_minutes,hysteresis_ratio,is_enabled) "
            "VALUES (:user_id,'research_review_due','immediate','UTC',60,0.02,true)",
            {"user_id": user_id},
        ),
        (
            "INSERT INTO manager_follows (user_id,manager_id) VALUES (:user_id,-1)",
            {"user_id": user_id},
        ),
        (
            "INSERT INTO formulas (user_id,name,output_key,expression,dependencies_json) "
            "VALUES (:user_id,'resurrected','resurrected','1','[]'::json)",
            {"user_id": user_id},
        ),
        (
            "INSERT INTO screening_rules (user_id,name,rule_json) "
            "VALUES (:user_id,'resurrected','{}'::json)",
            {"user_id": user_id},
        ),
        (
            "INSERT INTO stock_pools (user_id,name) VALUES (:user_id,'resurrected')",
            {"user_id": user_id},
        ),
        (
            "INSERT INTO research_coverage_requirements "
            "(user_id,stock_id,kind,priority_policy_version,matched_rule,priority_rank,state,reason,"
            "freshness_policy_version,evaluated_at,is_current) VALUES "
            "(:user_id,:stock_id,'valuation_input','v1','rule',1,'missing','resurrected','v1',now(),true)",
            {"user_id": user_id, "stock_id": stock_id},
        ),
    ]
    for statement, params in rejected:
        with pytest.raises(DBAPIError, match="account erasure"):
            db_session.execute(text(statement), params)
        db_session.rollback()


def test_raw_sql_cannot_forge_account_erasure_completion(
    db_session, user_factory
):
    user = user_factory("forged-erasure-event@example.com")
    stock = Stock(
        ticker="FRGER",
        exchange="NYSE",
        company_name="Forged Erasure Event Corp",
    )
    db_session.add(stock)
    db_session.flush()
    db_session.add(ResearchCase(user_id=user.id, stock_id=stock.id, state="queued"))
    db_session.flush()

    # Even a caller that discovers the transaction-local application setting
    # cannot mint the durable completion marker without performing the entire
    # privacy tombstone in the same transaction.
    db_session.execute(
        text("SELECT set_config('valuepilot.account_erasure', 'on', true)")
    )
    db_session.execute(
        text(
            """
            INSERT INTO account_erasure_events
                (user_id, content_hash, summary_json)
            VALUES (:user_id, repeat('0', 64), '{}'::jsonb)
            """
        ),
        {"user_id": user.id},
    )
    with pytest.raises(DBAPIError, match="complete privacy tombstone"):
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db_session.rollback()

    assert db_session.query(AccountErasureEvent).filter_by(user_id=user.id).count() == 0


def test_account_erasure_setting_alone_cannot_mutate_immutable_history(
    db_session,
    user_factory,
):
    user = user_factory("forged-erasure-bypass@example.com")
    stock = Stock(
        ticker="ERBYP",
        exchange="NYSE",
        company_name="Erasure Bypass Corp",
    )
    db_session.add(stock)
    db_session.flush()
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="researching")
    db_session.add(case)
    db_session.flush()
    revision = ResearchCaseRevision(
        case_id=case.id,
        revision_number=1,
        thesis="Original thesis",
        assumptions_json=[],
        risks_json=[],
        evidence_json=[],
        case_state="researching",
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        created_by_user_id=user.id,
    )
    event = ResearchCaseEvent(
        case_id=case.id,
        event_type="case_created",
        actor_user_id=user.id,
        correlation_id="erasure-bypass-test",
        payload_json={"original": True},
    )
    db_session.add_all([revision, event])
    db_session.commit()
    revision_id = revision.id
    event_id = event.id

    db_session.execute(
        text("SELECT set_config('valuepilot.account_erasure', 'on', true)")
    )
    db_session.execute(
        text(
            "UPDATE research_case_revisions "
            "SET thesis = 'forged' WHERE id = :id"
        ),
        {"id": revision_id},
    )
    with pytest.raises(DBAPIError, match="atomic audited account erasure"):
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db_session.rollback()

    db_session.execute(
        text("SELECT set_config('valuepilot.account_erasure', 'on', true)")
    )
    db_session.execute(
        text(
            "UPDATE research_case_events "
            "SET payload_json = '{\"forged\": true}'::jsonb WHERE id = :id"
        ),
        {"id": event_id},
    )
    with pytest.raises(DBAPIError, match="atomic audited account erasure"):
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db_session.rollback()

    assert db_session.get(ResearchCaseRevision, revision_id).thesis == "Original thesis"
    assert db_session.get(ResearchCaseEvent, event_id).payload_json == {
        "original": True
    }


def test_account_erasure_commit_failure_does_not_delete_active_file(
    db_session, user_factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    user = user_factory("erase-rollback@example.com", password="ErasePass123!")
    retained_pdf = tmp_path / "rollback-retained.pdf"
    retained_pdf.write_bytes(b"must survive a failed database transaction")
    document = PdfDocument(
        user_id=user.id,
        file_name=retained_pdf.name,
        source="Value Line",
        file_storage_key=str(retained_pdf),
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.commit()

    def _failed_commit() -> None:
        raise RuntimeError("injected commit failure")

    monkeypatch.setattr(db_session, "commit", _failed_commit)
    with pytest.raises(RuntimeError, match="injected commit failure"):
        erase_account(db_session, user=user, password="ErasePass123!")
    db_session.rollback()

    assert retained_pdf.is_file()
    db_session.refresh(document)
    assert document.lifecycle_state == "active"


def test_account_erasure_file_delete_failure_is_durable_and_retryable(
    db_session, user_factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    user = user_factory("erase-retry@example.com", password="ErasePass123!")
    retained_pdf = tmp_path / "retry-retained.pdf"
    retained_pdf.write_bytes(b"delete this after the database tombstone commits")
    document = PdfDocument(
        user_id=user.id,
        file_name=retained_pdf.name,
        source="Value Line",
        file_storage_key=str(retained_pdf),
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.commit()

    original_unlink = type(retained_pdf).unlink

    def _failed_unlink(self, *, missing_ok=False):
        raise PermissionError("injected filesystem failure")

    monkeypatch.setattr(type(retained_pdf), "unlink", _failed_unlink)
    result = erase_account(db_session, user=user, password="ErasePass123!")

    assert result["status"] == "erased"
    assert result["file_deletions_deleted"] == 0
    assert result["file_deletions_failed"] == 1
    assert retained_pdf.is_file()
    deletion = db_session.query(AccountErasureFileDeletion).filter_by(
        document_id=document.id
    ).one()
    assert deletion.status == "failed"
    assert deletion.attempt_count == 1
    assert deletion.last_error_class == "PermissionError"

    monkeypatch.setattr(type(retained_pdf), "unlink", original_unlink)
    retry = process_pending_account_erasure_file_deletions(
        db_session, user_id=user.id
    )

    assert retry == {
        "file_deletions_deleted": 1,
        "file_deletions_failed": 0,
        "file_deletions_retained_shared": 0,
    }
    assert retained_pdf.exists() is False
    db_session.refresh(deletion)
    assert deletion.status == "deleted"
    assert deletion.attempt_count == 2
    assert deletion.storage_path == "[deleted]"


def test_account_erasure_retains_blob_referenced_by_another_users_document(
    db_session, user_factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    first_user = user_factory(
        "erase-shared-first@example.com", password="ErasePass123!"
    )
    second_user = user_factory(
        "erase-shared-second@example.com", password="ErasePass123!"
    )
    shared_pdf = tmp_path / "shared-archive.pdf"
    shared_pdf.write_bytes(b"one retained artifact referenced by two users")
    first_document = PdfDocument(
        user_id=first_user.id,
        file_name=shared_pdf.name,
        source="Value Line",
        file_storage_key=str(shared_pdf),
        parse_status="parsed",
    )
    second_document = PdfDocument(
        user_id=second_user.id,
        file_name=shared_pdf.name,
        source="Value Line",
        file_storage_key=str(shared_pdf),
        parse_status="parsed",
    )
    db_session.add_all([first_document, second_document])
    db_session.commit()

    first_result = erase_account(
        db_session,
        user=first_user,
        password="ErasePass123!",
    )

    assert first_result["file_deletions_deleted"] == 0
    assert first_result["file_deletions_failed"] == 0
    assert first_result["file_deletions_retained_shared"] == 1
    assert shared_pdf.is_file()
    db_session.refresh(second_document)
    assert second_document.lifecycle_state == "active"
    first_deletion = db_session.query(AccountErasureFileDeletion).filter_by(
        document_id=first_document.id
    ).one()
    assert first_deletion.status == "retained_shared"

    second_result = erase_account(
        db_session,
        user=second_user,
        password="ErasePass123!",
    )

    assert second_result["file_deletions_deleted"] == 1
    assert second_result["file_deletions_retained_shared"] == 0
    assert shared_pdf.exists() is False


def test_account_erasure_retains_blob_referenced_through_path_alias(
    db_session, user_factory, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "UPLOAD_DIR", "uploads")
    managed_root = tmp_path / "uploads"
    managed_root.mkdir()
    first_user = user_factory(
        "erase-alias-first@example.com", password="ErasePass123!"
    )
    second_user = user_factory(
        "erase-alias-second@example.com", password="ErasePass123!"
    )
    shared_pdf = managed_root / "shared-alias.pdf"
    shared_pdf.write_bytes(b"same managed file through two path aliases")
    first_document = PdfDocument(
        user_id=first_user.id,
        file_name=shared_pdf.name,
        source="Value Line",
        file_storage_key="uploads/shared-alias.pdf",
        parse_status="parsed",
    )
    second_document = PdfDocument(
        user_id=second_user.id,
        file_name=shared_pdf.name,
        source="Value Line",
        file_storage_key=str(shared_pdf.resolve()),
        parse_status="parsed",
    )
    db_session.add_all([first_document, second_document])
    db_session.commit()

    result = erase_account(
        db_session,
        user=first_user,
        password="ErasePass123!",
    )

    assert result["file_deletions_deleted"] == 0
    assert result["file_deletions_retained_shared"] == 1
    assert shared_pdf.is_file()
    db_session.refresh(second_document)
    assert second_document.lifecycle_state == "active"


def test_account_erasure_never_unlinks_outside_managed_storage(
    db_session, user_factory, tmp_path, monkeypatch
):
    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(managed_root))
    user = user_factory(
        "erase-outside-root@example.com", password="ErasePass123!"
    )
    outside_file = tmp_path / "must-not-delete.pdf"
    outside_file.write_bytes(b"host-visible file outside managed uploads")
    document = PdfDocument(
        user_id=user.id,
        file_name=outside_file.name,
        source="upload",
        file_storage_key=str(outside_file),
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.commit()

    result = erase_account(db_session, user=user, password="ErasePass123!")

    assert result["file_deletions_deleted"] == 0
    assert result["file_deletions_failed"] == 1
    assert outside_file.is_file()
    deletion = db_session.query(AccountErasureFileDeletion).filter_by(
        document_id=document.id
    ).one()
    assert deletion.status == "failed"
    assert deletion.last_error_class == "AccountErasureError"
