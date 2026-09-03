from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import event

from app.core.config import settings
from app.models.institutions import Filing13F, InstitutionManager, JobRun
from app.models.coverage import ResearchCoverageRequirement
from app.models.research import ResearchCase, ResearchCaseRevision
from app.models.stocks import Stock
from app.models.notifications import (
    ManagerFollow,
    LogicalNotification,
    NotificationDeliveryAttempt,
    NotificationDeliveryEvent,
    NotificationDestination,
    NotificationInboxState,
    NotificationPriceAlertState,
    NotificationSubscription,
)


@pytest.fixture(autouse=True)
def _authorized_test_price_source(monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_PRIMARY", "yfinance")
    monkeypatch.setattr(settings, "MARKET_DATA_SECONDARY", "none")
    monkeypatch.setattr(settings, "MARKET_DATA_ALLOW_DEVELOPMENT_PROVIDER", True)
from app.models.stocks import StockPrice
from app.services.research_notifications import (
    NotificationError,
    SlackWebhookAdapter,
    create_email_destination,
    create_or_update_slack_destination,
    deliver_pending_attempts,
    destination_secret_rotation_needed,
    follow_manager,
    is_delivery_time_allowed,
    list_follows,
    materialize_followed_manager_filing,
    materialize_intrinsic_value_crossings,
    materialize_research_coverage_changes,
    materialize_scheduled_digests,
    produce_notification,
    run_destination_secret_rotation,
    upsert_subscription,
    verify_email_destination,
)
from app.services.valuation import publish_user_intrinsic_value


def _manager(db_session, *, cik="0001234500"):
    manager = InstitutionManager(
        canonical_name="Patient Capital",
        legal_name="Patient Capital LLC",
        display_name="Patient Capital",
        cik=cik,
        match_status="confirmed",
        status="active",
        manager_type="long_term_fundamental",
        style_primary="value_concentrated",
        capital_structure="locked_lp",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _keys():
    return f"v2:{Fernet.generate_key().decode()},v1:{Fernet.generate_key().decode()}"


def test_open_case_coverage_ready_and_failed_events_are_durable_and_idempotent(
    db_session, user_factory
):
    user = user_factory("coverage-notify@example.com")
    stock = Stock(ticker="COVN", exchange="NYSE", company_name="Coverage Notice")
    db_session.add(stock)
    db_session.flush()
    case = ResearchCase(user_id=user.id, stock_id=stock.id, state="queued")
    requirement = ResearchCoverageRequirement(
        user_id=user.id,
        stock_id=stock.id,
        kind="eod_price",
        priority_policy_version="research-coverage-priority-v1.0",
        matched_rule="open_case_queued",
        priority_rank=40,
        state="ready",
        reason="A current EOD close is ready.",
        source_type="stock_price",
        source_ref_id=77,
        freshness_policy_version="us-market-session-v1.0",
        evaluated_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        is_current=True,
    )
    db_session.add_all([case, requirement])
    db_session.commit()

    assert materialize_research_coverage_changes(db_session) == 1
    assert materialize_research_coverage_changes(db_session) == 0

    requirement.state = "failed"
    requirement.reason_code = "provider_failed"
    requirement.reason = "The configured provider failed permanently."
    requirement.source_ref_id = None
    requirement.evaluated_at = datetime(2026, 7, 21, tzinfo=timezone.utc)
    db_session.commit()
    assert materialize_research_coverage_changes(db_session) == 1

    rows = db_session.query(LogicalNotification).order_by(LogicalNotification.id).all()
    assert [row.event_family for row in rows] == [
        "research_coverage_changed",
        "research_coverage_changed",
    ]
    assert [row.severity for row in rows] == ["info", "warning"]
    assert all(row.case_id == case.id for row in rows)


def test_manager_follow_is_idempotent_and_user_scoped(db_session, user_factory):
    first_user = user_factory("follow-one@example.com")
    second_user = user_factory("follow-two@example.com")
    manager = _manager(db_session)

    first, created = follow_manager(db_session, user_id=first_user.id, manager_id=manager.id)
    again, duplicate_created = follow_manager(
        db_session, user_id=first_user.id, manager_id=manager.id
    )
    other, other_created = follow_manager(
        db_session, user_id=second_user.id, manager_id=manager.id
    )

    assert created is True
    assert duplicate_created is False
    assert other_created is True
    assert again.id == first.id
    assert other.id != first.id
    assert [row.manager_id for row in list_follows(db_session, user_id=first_user.id)] == [
        manager.id
    ]


def test_slack_destination_is_allowlisted_encrypted_and_masked(db_session, user_factory):
    user = user_factory("slack-owner@example.com")
    webhook = "https://hooks.slack.com/services/T00000000/B00000000/SecretToken123"

    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", _keys()):
        destination, created = create_or_update_slack_destination(
            db_session,
            user_id=user.id,
            label="Research alerts",
            webhook_url=webhook,
            consent=True,
        )

    assert created is True
    assert destination.status == "enabled"
    assert destination.destination_hint == "hooks.slack.com/…/n123"
    assert webhook not in destination.secret_ciphertext
    assert destination.key_version == "v2"

    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", _keys()):
        with pytest.raises(NotificationError, match="approved Slack"):
            create_or_update_slack_destination(
                db_session,
                user_id=user.id,
                label="Bad",
                webhook_url="https://example.com/services/a/b/c",
                consent=True,
            )


def test_destination_creation_fails_closed_without_key_or_consent(db_session, user_factory):
    user = user_factory("blocked-destination@example.com")
    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", None):
        with pytest.raises(NotificationError, match="encryption"):
            create_or_update_slack_destination(
                db_session,
                user_id=user.id,
                label="Blocked",
                webhook_url="https://hooks.slack.com/services/T1/B2/Secret3",
                consent=True,
            )
    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", _keys()):
        with pytest.raises(NotificationError, match="consent"):
            create_or_update_slack_destination(
                db_session,
                user_id=user.id,
                label="Blocked",
                webhook_url="https://hooks.slack.com/services/T1/B2/Secret3",
                consent=False,
            )


def test_email_verification_is_hashed_single_use_and_transport_gated(db_session, user_factory):
    user = user_factory("email-destination-owner@example.com")
    sender = Mock(return_value=True)
    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", _keys()):
        destination, token = create_email_destination(
            db_session,
            user_id=user.id,
            label="Private email",
            email="investor@example.com",
            consent=True,
            verification_sender=sender,
        )
        assert destination.status == "pending_verification"
        assert "investor@example.com" not in destination.secret_ciphertext
        assert token not in destination.verification_challenges[0].token_hash
        verified = verify_email_destination(
            db_session,
            user_id=user.id,
            destination_id=destination.id,
            token=token,
        )
        assert verified.status == "enabled"
        with pytest.raises(NotificationError, match="used"):
            verify_email_destination(
                db_session,
                user_id=user.id,
                destination_id=destination.id,
                token=token,
            )
    sender.assert_called_once()


def test_logical_event_is_idempotent_and_amendment_is_linked_correction(
    db_session, user_factory
):
    user = user_factory("logical-notification@example.com")
    first, created = produce_notification(
        db_session,
        user_id=user.id,
        event_family="followed_manager_filed",
        subject_type="manager",
        subject_key="manager:7:2026-Q1",
        source_version="accession-a:parse-1",
        title="A manager filed",
        body="A delayed filing is ready for research.",
        evidence_route="/13f/managers/7",
    )
    replay, replay_created = produce_notification(
        db_session,
        user_id=user.id,
        event_family="followed_manager_filed",
        subject_type="manager",
        subject_key="manager:7:2026-Q1",
        source_version="accession-a:parse-1",
        title="A manager filed",
        body="A delayed filing is ready for research.",
        evidence_route="/13f/managers/7",
    )
    correction, correction_created = produce_notification(
        db_session,
        user_id=user.id,
        event_family="followed_manager_filed",
        subject_type="manager",
        subject_key="manager:7:2026-Q1",
        source_version="accession-b:parse-2",
        title="A manager filing was corrected",
        body="An amendment superseded the earlier filing evidence.",
        evidence_route="/13f/managers/7",
        supersedes_notification_id=first.id,
    )

    assert replay.id == first.id
    assert created is True and replay_created is False and correction_created is True
    assert correction.correction_type == "correction"
    assert correction.supersedes_notification_id == first.id
    assert db_session.query(NotificationInboxState).count() == 2


def test_followed_manager_filing_only_materializes_for_followers(db_session, user_factory):
    follower = user_factory("follower@example.com")
    bystander = user_factory("bystander@example.com")
    manager = _manager(db_session, cik="0001234567")
    filing = Filing13F(
        manager_id=manager.id,
        accession_no="0001234567-26-000001",
        accession_number="0001234567-26-000001",
        form_type="13F-HR",
        period_of_report=date(2026, 3, 31),
        filed_at=date(2026, 5, 15),
        report_quarter="2026-Q1",
        quarter_end_date=date(2026, 3, 31),
        filing_date=datetime(2026, 5, 15, tzinfo=timezone.utc).date(),
        parse_status="succeeded",
        is_active_for_manager_period=True,
        coverage_completeness="complete",
    )
    db_session.add(filing)
    db_session.flush()
    follow_manager(db_session, user_id=follower.id, manager_id=manager.id)

    created = materialize_followed_manager_filing(db_session, filing_id=filing.id)
    replay = materialize_followed_manager_filing(db_session, filing_id=filing.id)

    assert created == 1
    assert replay == 0
    assert first_for_user(db_session, follower.id) is not None
    assert first_for_user(db_session, bystander.id) is None


def first_for_user(db_session, user_id):
    from app.models.notifications import LogicalNotification

    return db_session.query(LogicalNotification).filter_by(user_id=user_id).first()


def test_delivery_is_deduplicated_audited_and_never_logs_or_returns_secret(
    db_session, user_factory
):
    user = user_factory("delivery-owner@example.com")
    keys = _keys()
    webhook = "https://hooks.slack.com/services/T111/B222/Secret333"
    now = datetime(2026, 7, 20, 17, tzinfo=timezone.utc)
    with (
        patch.object(settings, "NOTIFICATION_SECRET_KEYS", keys),
        patch.object(settings, "NOTIFICATION_DELIVERY_ENABLED", True),
        patch("app.services.research_notifications._utcnow", return_value=now),
    ):
        destination, _ = create_or_update_slack_destination(
            db_session,
            user_id=user.id,
            label="Slack",
            webhook_url=webhook,
            consent=True,
        )
        subscription = NotificationSubscription(
            user_id=user.id,
            event_family="research_review_due",
            destination_id=destination.id,
            frequency="immediate",
            timezone="America/Chicago",
            cooldown_minutes=60,
            is_enabled=True,
        )
        db_session.add(subscription)
        db_session.commit()
        notification, _ = produce_notification(
            db_session,
            user_id=user.id,
            event_family="research_review_due",
            subject_type="research_case",
            subject_key="case:91:review:2026-07-20",
            source_version="case-91-rev-2",
            title="Research review is due",
            body="Review the thesis and current evidence.",
            evidence_route="/research/cases/91",
        )
        sender = Mock(return_value=(True, "accepted"))
        result = deliver_pending_attempts(
            db_session,
            now=now,
            adapters={"slack": SlackWebhookAdapter(sender=sender)},
        )
        replay = deliver_pending_attempts(
            db_session,
            now=datetime(2026, 7, 20, 17, 5, tzinfo=timezone.utc),
            adapters={"slack": SlackWebhookAdapter(sender=sender)},
        )

    assert result["succeeded"] == 1
    assert replay["succeeded"] == 0
    sender.assert_called_once()
    assert sender.call_args.args[0] == webhook
    attempt = db_session.query(NotificationDeliveryAttempt).one()
    assert attempt.logical_notification_id == notification.id
    assert attempt.status == "succeeded"
    assert db_session.query(NotificationDeliveryEvent).count() >= 2
    assert webhook not in str(attempt.__dict__)


def test_daily_digest_materializes_once_and_delivers_pending_events(
    db_session, user_factory
):
    user = user_factory("daily-digest@example.com")
    keys = _keys()
    webhook = "https://hooks.slack.com/services/T111/B222/Digest333"
    with (
        patch.object(settings, "NOTIFICATION_SECRET_KEYS", keys),
        patch.object(settings, "NOTIFICATION_DELIVERY_ENABLED", True),
    ):
        destination, _ = create_or_update_slack_destination(
            db_session,
            user_id=user.id,
            label="Daily digest",
            webhook_url=webhook,
            consent=True,
        )
        subscription = NotificationSubscription(
            user_id=user.id,
            event_family="research_review_due",
            destination_id=destination.id,
            frequency="daily_digest",
            timezone="America/Chicago",
            cooldown_minutes=0,
            is_enabled=True,
        )
        db_session.add(subscription)
        db_session.commit()
        for index in range(2):
            produce_notification(
                db_session,
                user_id=user.id,
                event_family="research_review_due",
                subject_type="research_case",
                subject_key=f"case:{index + 1}:review",
                source_version="revision-1",
                title=f"Review case {index + 1}",
                body="Review the recorded thesis and current evidence.",
                evidence_route=f"/research/cases/{index + 1}",
            )

        assert db_session.query(NotificationDeliveryAttempt).count() == 0
        local_zone = ZoneInfo("America/Chicago")
        local_date = datetime.now(local_zone).date() + timedelta(days=2)
        as_of = datetime.combine(local_date, time(9), local_zone).astimezone(
            timezone.utc
        )
        created = materialize_scheduled_digests(db_session, as_of=as_of)
        replay = materialize_scheduled_digests(db_session, as_of=as_of)
        sender = Mock(return_value=(True, "accepted"))
        delivery = deliver_pending_attempts(
            db_session,
            now=as_of,
            adapters={"slack": SlackWebhookAdapter(sender=sender)},
        )

    assert created == 1
    assert replay == 0
    assert delivery["succeeded"] == 1
    sender.assert_called_once()
    digest = (
        db_session.query(LogicalNotification)
        .filter_by(subject_type="notification_digest")
        .one()
    )
    assert digest.payload_json["frequency"] == "daily_digest"
    assert digest.payload_json["source_notification_count"] == 2
    assert "Review case 1" in digest.body
    assert "Review case 2" in digest.body


def test_in_app_subscription_rejects_a_digest_frequency(db_session, user_factory):
    user = user_factory("in-app-frequency@example.com")

    with pytest.raises(NotificationError) as error:
        upsert_subscription(
            db_session,
            user_id=user.id,
            event_family="research_review_due",
            destination_id=None,
            frequency="daily_digest",
            timezone_name="UTC",
            quiet_start_local=None,
            quiet_end_local=None,
            cooldown_minutes=60,
            threshold_ratio=None,
            hysteresis_ratio=0.02,
            is_enabled=True,
        )

    assert error.value.code == "in_app_frequency_invalid"


def test_intrinsic_value_policy_is_consistent_across_destinations(
    db_session, user_factory
):
    user = user_factory("shared-threshold-policy@example.com")
    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", _keys()):
        destination, _ = create_or_update_slack_destination(
            db_session,
            user_id=user.id,
            label="Threshold Slack",
            webhook_url="https://hooks.slack.com/services/T111/B222/Policy333",
            consent=True,
        )
    upsert_subscription(
        db_session,
        user_id=user.id,
        event_family="intrinsic_value_threshold_crossed",
        destination_id=None,
        frequency="immediate",
        timezone_name="UTC",
        quiet_start_local=None,
        quiet_end_local=None,
        cooldown_minutes=60,
        threshold_ratio=0.20,
        hysteresis_ratio=0.02,
        is_enabled=True,
    )
    upsert_subscription(
        db_session,
        user_id=user.id,
        event_family="intrinsic_value_threshold_crossed",
        destination_id=destination.id,
        frequency="daily_digest",
        timezone_name="America/Chicago",
        quiet_start_local="22:00",
        quiet_end_local="07:00",
        cooldown_minutes=120,
        threshold_ratio=0.30,
        hysteresis_ratio=0.04,
        is_enabled=True,
    )

    rows = db_session.query(NotificationSubscription).filter_by(
        user_id=user.id,
        event_family="intrinsic_value_threshold_crossed",
    ).all()
    assert len(rows) == 2
    assert {float(row.threshold_ratio) for row in rows} == {0.30}
    assert {float(row.hysteresis_ratio) for row in rows} == {0.04}
    assert {row.cooldown_minutes for row in rows} == {120}
    assert {row.frequency for row in rows} == {"immediate", "daily_digest"}


def test_intrinsic_value_change_reinitializes_alert_without_false_crossing(
    db_session, user_factory
):
    user = user_factory("valuation-reset@example.com")
    stock = Stock(
        ticker="RESET",
        exchange="NASDAQ",
        company_name="Valuation Reset Corp",
    )
    db_session.add(stock)
    db_session.flush()
    case = ResearchCase(
        user_id=user.id,
        stock_id=stock.id,
        state="monitoring",
        decision="watch",
        next_review_on=date(2026, 10, 1),
    )
    db_session.add(case)
    db_session.add(
        NotificationSubscription(
            user_id=user.id,
            event_family="intrinsic_value_threshold_crossed",
            destination_id=None,
            frequency="immediate",
            timezone="UTC",
            cooldown_minutes=60,
            threshold_ratio=0.20,
            hysteresis_ratio=0.02,
            is_enabled=True,
        )
    )
    first_value = publish_user_intrinsic_value(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=100,
        as_of_date=date(2026, 7, 17),
    )
    first_price = StockPrice(
        stock_id=stock.id,
        price_date=date(2026, 7, 17),
        open=90,
        high=90,
        low=90,
        close=90,
        source="yfinance",
        currency="USD",
    )
    db_session.add(first_price)
    db_session.commit()

    captured_lock_keys = []
    connection = db_session.connection()

    def capture_lock(_conn, _cursor, statement, parameters, _context, _many):
        if "pg_advisory_xact_lock" in statement:
            captured_lock_keys.append(parameters.get("key"))

    event.listen(connection, "before_cursor_execute", capture_lock)
    try:
        assert materialize_intrinsic_value_crossings(
            db_session,
            as_of=datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
        ) == 0
    finally:
        event.remove(connection, "before_cursor_execute", capture_lock)
    assert f"notification-price-alert:{user.id}:{stock.id}" in captured_lock_keys
    state = db_session.query(NotificationPriceAlertState).one()
    assert state.last_side == "above"
    assert state.last_valuation_fact_id == first_value.id

    second_value = publish_user_intrinsic_value(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=150,
        as_of_date=date(2026, 7, 20),
    )
    second_price = StockPrice(
        stock_id=stock.id,
        price_date=date(2026, 7, 20),
        open=90,
        high=90,
        low=90,
        close=90,
        source="yfinance",
        currency="USD",
    )
    db_session.add(second_price)
    db_session.commit()

    created = materialize_intrinsic_value_crossings(
        db_session,
        as_of=datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
    )

    db_session.refresh(state)
    assert created == 0
    assert state.last_side == "below"
    assert state.last_price_id == second_price.id
    assert state.last_valuation_fact_id == second_value.id
    assert db_session.query(LogicalNotification).filter_by(
        event_family="intrinsic_value_threshold_crossed"
    ).count() == 0

    third_price = StockPrice(
        stock_id=stock.id,
        price_date=date(2026, 7, 21),
        open=130,
        high=130,
        low=130,
        close=130,
        source="yfinance",
        currency="USD",
    )
    db_session.add(third_price)
    db_session.commit()

    true_crossing = materialize_intrinsic_value_crossings(
        db_session,
        as_of=datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )

    assert true_crossing == 1
    notification = db_session.query(LogicalNotification).filter_by(
        event_family="intrinsic_value_threshold_crossed"
    ).one()
    assert notification.payload_json["price_id"] == third_price.id
    assert f"value-{second_value.id}" in notification.source_version


def test_post_close_alert_evaluation_uses_same_day_completed_session(
    db_session, user_factory
):
    user = user_factory("post-close-price@example.com")
    stock = Stock(
        ticker="AFTER",
        exchange="NASDAQ",
        company_name="After Close Corp",
    )
    db_session.add(stock)
    db_session.flush()
    db_session.add(
        ResearchCase(
            user_id=user.id,
            stock_id=stock.id,
            state="monitoring",
            decision="watch",
            next_review_on=date(2026, 10, 1),
        )
    )
    db_session.add(
        NotificationSubscription(
            user_id=user.id,
            event_family="intrinsic_value_threshold_crossed",
            destination_id=None,
            frequency="immediate",
            timezone="UTC",
            cooldown_minutes=60,
            threshold_ratio=0.20,
            hysteresis_ratio=0.02,
            is_enabled=True,
        )
    )
    publish_user_intrinsic_value(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=100,
        as_of_date=date(2026, 7, 20),
    )
    same_day_price = StockPrice(
        stock_id=stock.id,
        price_date=date(2026, 7, 20),
        open=75,
        high=75,
        low=75,
        close=75,
        source="yfinance",
        currency="USD",
    )
    db_session.add(same_day_price)
    db_session.commit()

    created = materialize_intrinsic_value_crossings(
        db_session,
        as_of=datetime(2026, 7, 20, 22, tzinfo=timezone.utc),
    )

    assert created == 0
    state = db_session.query(NotificationPriceAlertState).one()
    assert state.last_price_id == same_day_price.id
    assert state.last_side == "below"


def test_new_monitoring_revision_reinitializes_alert_after_research_pause(
    db_session, user_factory
):
    user = user_factory("decision-reset@example.com")
    stock = Stock(
        ticker="DECIDE",
        exchange="NASDAQ",
        company_name="Decision Reset Corp",
    )
    db_session.add(stock)
    db_session.flush()
    case = ResearchCase(
        user_id=user.id,
        stock_id=stock.id,
        state="monitoring",
        decision="watch",
        next_review_on=date(2026, 10, 1),
        head_revision_number=1,
    )
    db_session.add(case)
    db_session.flush()
    first_revision = ResearchCaseRevision(
        case_id=case.id,
        revision_number=1,
        case_state="monitoring",
        decision="watch",
        next_review_on=date(2026, 10, 1),
        valuation_low=90,
        valuation_base=100,
        valuation_high=110,
        valuation_currency="USD",
        valuation_as_of_date=date(2026, 7, 17),
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        created_by_user_id=user.id,
    )
    db_session.add(first_revision)
    db_session.add(
        NotificationSubscription(
            user_id=user.id,
            event_family="intrinsic_value_threshold_crossed",
            destination_id=None,
            frequency="immediate",
            timezone="UTC",
            cooldown_minutes=60,
            threshold_ratio=0.20,
            hysteresis_ratio=0.02,
            is_enabled=True,
        )
    )
    publish_user_intrinsic_value(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=100,
        as_of_date=date(2026, 7, 17),
    )
    db_session.add(
        StockPrice(
            stock_id=stock.id,
            price_date=date(2026, 7, 17),
            open=90,
            high=90,
            low=90,
            close=90,
            source="yfinance",
            currency="USD",
        )
    )
    db_session.commit()

    assert materialize_intrinsic_value_crossings(
        db_session,
        as_of=datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
    ) == 0
    state = db_session.query(NotificationPriceAlertState).one()
    assert state.last_research_revision_id == first_revision.id

    case.state = "researching"
    case.decision = None
    case.next_review_on = None
    db_session.add(
        StockPrice(
            stock_id=stock.id,
            price_date=date(2026, 7, 20),
            open=70,
            high=70,
            low=70,
            close=70,
            source="yfinance",
            currency="USD",
        )
    )
    db_session.commit()
    assert materialize_intrinsic_value_crossings(
        db_session,
        as_of=datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
    ) == 0

    case.state = "monitoring"
    case.decision = "watch"
    case.next_review_on = date(2026, 10, 1)
    case.head_revision_number = 2
    second_revision = ResearchCaseRevision(
        case_id=case.id,
        revision_number=2,
        case_state="monitoring",
        decision="watch",
        next_review_on=date(2026, 10, 1),
        valuation_low=90,
        valuation_base=100,
        valuation_high=110,
        valuation_currency="USD",
        valuation_as_of_date=date(2026, 7, 17),
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        created_by_user_id=user.id,
    )
    db_session.add(second_revision)
    db_session.commit()

    assert materialize_intrinsic_value_crossings(
        db_session,
        as_of=datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
    ) == 0
    db_session.refresh(state)
    assert state.last_research_revision_id == second_revision.id
    assert state.last_side == "below"
    assert db_session.query(LogicalNotification).filter_by(
        event_family="intrinsic_value_threshold_crossed"
    ).count() == 0


def test_intrinsic_value_policy_change_reinitializes_without_false_crossing(
    db_session, user_factory
):
    user = user_factory("threshold-reset@example.com")
    stock = Stock(
        ticker="POLICY",
        exchange="NASDAQ",
        company_name="Policy Reset Corp",
    )
    db_session.add(stock)
    db_session.flush()
    db_session.add(
        ResearchCase(
            user_id=user.id,
            stock_id=stock.id,
            state="monitoring",
            decision="watch",
            next_review_on=date(2026, 10, 1),
        )
    )
    upsert_subscription(
        db_session,
        user_id=user.id,
        event_family="intrinsic_value_threshold_crossed",
        destination_id=None,
        frequency="immediate",
        timezone_name="UTC",
        quiet_start_local=None,
        quiet_end_local=None,
        cooldown_minutes=60,
        threshold_ratio=0.20,
        hysteresis_ratio=0.02,
        is_enabled=True,
    )
    publish_user_intrinsic_value(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=100,
        as_of_date=date(2026, 7, 17),
    )
    db_session.add(
        StockPrice(
            stock_id=stock.id,
            price_date=date(2026, 7, 17),
            open=90,
            high=90,
            low=90,
            close=90,
            source="yfinance",
            currency="USD",
        )
    )
    db_session.commit()
    assert materialize_intrinsic_value_crossings(
        db_session,
        as_of=datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
    ) == 0

    upsert_subscription(
        db_session,
        user_id=user.id,
        event_family="intrinsic_value_threshold_crossed",
        destination_id=None,
        frequency="immediate",
        timezone_name="UTC",
        quiet_start_local=None,
        quiet_end_local=None,
        cooldown_minutes=60,
        threshold_ratio=0.05,
        hysteresis_ratio=0.02,
        is_enabled=True,
    )
    changed_policy_price = StockPrice(
        stock_id=stock.id,
        price_date=date(2026, 7, 20),
        open=90,
        high=90,
        low=90,
        close=90,
        source="yfinance",
        currency="USD",
    )
    db_session.add(changed_policy_price)
    db_session.commit()

    created = materialize_intrinsic_value_crossings(
        db_session,
        as_of=datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
    )

    state = db_session.query(NotificationPriceAlertState).one()
    assert created == 0
    assert state.last_side == "below"
    assert float(state.last_threshold_ratio) == 0.05
    assert float(state.last_hysteresis_ratio) == 0.02
    assert db_session.query(LogicalNotification).filter_by(
        event_family="intrinsic_value_threshold_crossed"
    ).count() == 0


def test_intrinsic_value_alert_ignores_currency_mismatch_and_stale_close(
    db_session, user_factory
):
    user = user_factory("ineligible-price-alert@example.com")
    upsert_subscription(
        db_session,
        user_id=user.id,
        event_family="intrinsic_value_threshold_crossed",
        destination_id=None,
        frequency="immediate",
        timezone_name="UTC",
        quiet_start_local=None,
        quiet_end_local=None,
        cooldown_minutes=60,
        threshold_ratio=0.20,
        hysteresis_ratio=0.02,
        is_enabled=True,
    )
    for ticker, price_date, currency in (
        ("EURX", date(2026, 7, 17), "EUR"),
        ("STALE", date(2026, 7, 16), "USD"),
    ):
        stock = Stock(
            ticker=ticker,
            exchange="NASDAQ",
            company_name=f"{ticker} Corp",
        )
        db_session.add(stock)
        db_session.flush()
        db_session.add(
            ResearchCase(
                user_id=user.id,
                stock_id=stock.id,
                state="monitoring",
                decision="watch",
                next_review_on=date(2026, 10, 1),
            )
        )
        publish_user_intrinsic_value(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            value_numeric=100,
            as_of_date=date(2026, 7, 17),
        )
        db_session.add(
            StockPrice(
                stock_id=stock.id,
                price_date=price_date,
                open=70,
                high=70,
                low=70,
                close=70,
                source="yfinance",
                currency=currency,
            )
        )
    db_session.commit()

    created = materialize_intrinsic_value_crossings(
        db_session,
        as_of=datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
    )

    assert created == 0
    assert db_session.query(NotificationPriceAlertState).count() == 0
    assert db_session.query(LogicalNotification).filter_by(
        event_family="intrinsic_value_threshold_crossed"
    ).count() == 0


def test_weekly_digest_waits_for_monday_local_delivery_window(
    db_session, user_factory
):
    user = user_factory("weekly-digest@example.com")
    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", _keys()):
        destination, _ = create_or_update_slack_destination(
            db_session,
            user_id=user.id,
            label="Weekly digest",
            webhook_url="https://hooks.slack.com/services/T111/B222/Weekly333",
            consent=True,
        )
        db_session.add(
            NotificationSubscription(
                user_id=user.id,
                event_family="research_review_due",
                destination_id=destination.id,
                frequency="weekly_digest",
                timezone="America/Chicago",
                cooldown_minutes=0,
                is_enabled=True,
            )
        )
        db_session.commit()
        produce_notification(
            db_session,
            user_id=user.id,
            event_family="research_review_due",
            subject_type="research_case",
            subject_key="case:weekly:review",
            source_version="revision-1",
            title="Weekly case review",
            body="Review the thesis.",
            evidence_route="/research/cases/1",
        )

        zone = ZoneInfo("America/Chicago")
        local_today = datetime.now(zone).date()
        next_monday = local_today + timedelta(days=(7 - local_today.weekday()) % 7 or 7)
        before_window = datetime.combine(next_monday, time(7, 59), zone).astimezone(
            timezone.utc
        )
        inside_window = datetime.combine(next_monday, time(9), zone).astimezone(
            timezone.utc
        )

        assert materialize_scheduled_digests(db_session, as_of=before_window) == 0
        assert materialize_scheduled_digests(db_session, as_of=inside_window) == 1
        assert materialize_scheduled_digests(db_session, as_of=inside_window) == 0

    digest = (
        db_session.query(LogicalNotification)
        .filter_by(subject_type="notification_digest")
        .one()
    )
    assert digest.payload_json["frequency"] == "weekly_digest"


def test_explicit_destination_test_does_not_require_a_subscription(
    db_session, user_factory
):
    user = user_factory("explicit-test@example.com")
    with (
        patch.object(settings, "NOTIFICATION_SECRET_KEYS", _keys()),
        patch.object(settings, "NOTIFICATION_DELIVERY_ENABLED", True),
    ):
        destination, _ = create_or_update_slack_destination(
            db_session,
            user_id=user.id,
            label="Test destination",
            webhook_url="https://hooks.slack.com/services/T111/B222/Test333",
            consent=True,
        )
        notification, _ = produce_notification(
            db_session,
            user_id=user.id,
            event_family="destination_test",
            subject_type="destination",
            subject_key=f"destination:{destination.id}:test",
            source_version="one",
            title="Destination test",
            body="Explicitly confirmed test.",
            evidence_route="/notifications",
        )
        now = datetime.now(timezone.utc)
        db_session.add(
            NotificationDeliveryAttempt(
                logical_notification_id=notification.id,
                destination_id=destination.id,
                content_version=notification.content_version,
                status="queued",
                scheduled_for=now,
                next_attempt_at=now,
            )
        )
        db_session.commit()
        sender = Mock(return_value=(True, "accepted"))
        result = deliver_pending_attempts(
            db_session,
            now=now,
            adapters={"slack": SlackWebhookAdapter(sender=sender)},
        )

    assert result["succeeded"] == 1
    sender.assert_called_once()


def test_expired_delivery_lease_is_visible_unknown_and_is_not_blindly_resent(
    db_session, user_factory
):
    user = user_factory("expired-lease@example.com")
    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", _keys()):
        destination, _ = create_or_update_slack_destination(
            db_session,
            user_id=user.id,
            label="Slack",
            webhook_url="https://hooks.slack.com/services/T111/B222/Lease333",
            consent=True,
        )
    subscription = NotificationSubscription(
        user_id=user.id,
        event_family="research_review_due",
        destination_id=destination.id,
        frequency="immediate",
        timezone="UTC",
        cooldown_minutes=0,
        is_enabled=True,
    )
    db_session.add(subscription)
    db_session.commit()
    notification, _ = produce_notification(
        db_session,
        user_id=user.id,
        event_family="research_review_due",
        subject_type="research_case",
        subject_key="case:unknown-outcome",
        source_version="one",
        title="Review",
        body="Review due.",
        evidence_route="/research/cases/1",
    )
    attempt = db_session.query(NotificationDeliveryAttempt).filter_by(
        logical_notification_id=notification.id,
        destination_id=destination.id,
    ).one()
    now = datetime.now(timezone.utc)
    attempt.status = "leased"
    attempt.attempt_count = 1
    attempt.last_attempt_at = now - timedelta(minutes=3)
    attempt.lease_expires_at = now - timedelta(minutes=1)
    attempt.next_attempt_at = now - timedelta(minutes=3)
    db_session.commit()
    sender = Mock()

    with (
        patch.object(settings, "NOTIFICATION_SECRET_KEYS", _keys()),
        patch.object(settings, "NOTIFICATION_DELIVERY_ENABLED", True),
    ):
        # The ciphertext belongs to the first temporary keyring; secret access
        # must not happen at all for an ambiguous expired lease.
        result = deliver_pending_attempts(
            db_session,
            now=now,
            adapters={"slack": SlackWebhookAdapter(sender=sender)},
        )

    db_session.refresh(attempt)
    assert result["failed"] == 1
    assert attempt.status == "permanent_failure"
    assert attempt.provider_response_class == "delivery_outcome_unknown"
    sender.assert_not_called()


def test_transient_delivery_retry_succeeds_once_and_does_not_send_again(
    db_session, user_factory
):
    user = user_factory("delivery-retry@example.com")
    keys = _keys()
    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", keys):
        destination, _ = create_or_update_slack_destination(
            db_session,
            user_id=user.id,
            label="Slack",
            webhook_url="https://hooks.slack.com/services/T111/B222/Retry333",
            consent=True,
        )
    db_session.add(
        NotificationSubscription(
            user_id=user.id,
            event_family="research_review_due",
            destination_id=destination.id,
            frequency="immediate",
            timezone="UTC",
            cooldown_minutes=0,
            is_enabled=True,
        )
    )
    db_session.commit()
    notification, _ = produce_notification(
        db_session,
        user_id=user.id,
        event_family="research_review_due",
        subject_type="research_case",
        subject_key="case:retry",
        source_version="one",
        title="Review",
        body="Review due.",
        evidence_route="/research/cases/1",
    )
    now = datetime.now(timezone.utc)
    sender = Mock(
        side_effect=[
            (False, "transient_provider_failure"),
            (True, "accepted"),
        ]
    )
    with (
        patch.object(settings, "NOTIFICATION_SECRET_KEYS", keys),
        patch.object(settings, "NOTIFICATION_DELIVERY_ENABLED", True),
    ):
        first = deliver_pending_attempts(
            db_session,
            now=now,
            adapters={"slack": SlackWebhookAdapter(sender=sender)},
        )
        second = deliver_pending_attempts(
            db_session,
            now=now + timedelta(minutes=3),
            adapters={"slack": SlackWebhookAdapter(sender=sender)},
        )
        replay = deliver_pending_attempts(
            db_session,
            now=now + timedelta(minutes=4),
            adapters={"slack": SlackWebhookAdapter(sender=sender)},
        )

    attempt = db_session.query(NotificationDeliveryAttempt).filter_by(
        logical_notification_id=notification.id
    ).one()
    assert first["retry_scheduled"] == 1
    assert second["succeeded"] == 1
    assert replay["attempted"] == 0
    assert attempt.status == "succeeded"
    assert attempt.attempt_count == 2
    assert sender.call_count == 2


def test_destination_key_rotation_is_bounded_audited_and_keeps_delivery_working(
    db_session, user_factory
):
    user = user_factory("destination-rotation@example.com")
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", f"v1:{old_key}"):
        destination, _ = create_or_update_slack_destination(
            db_session,
            user_id=user.id,
            label="Slack",
            webhook_url="https://hooks.slack.com/services/T111/B222/Rotate333",
            consent=True,
        )
    assert destination.key_version == "v1"

    keys = f"v2:{new_key},v1:{old_key}"
    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", keys):
        assert destination_secret_rotation_needed(db_session) is True
        result = run_destination_secret_rotation(db_session, limit=25)
        assert destination_secret_rotation_needed(db_session) is False
        replay = run_destination_secret_rotation(db_session, limit=25)

    db_session.refresh(destination)
    jobs = (
        db_session.query(JobRun)
        .filter_by(job_type="notification_secret_rotation")
        .order_by(JobRun.id)
        .all()
    )
    assert result["status"] == "succeeded"
    assert result["rotated"] == 1
    assert replay["rotated"] == 0
    assert destination.key_version == "v2"
    assert len(jobs) == 2
    assert jobs[0].summary_json == {
        "rotated": 1,
        "configuration_blocked": 0,
        "limit": 25,
    }
    assert all(job.status == "succeeded" for job in jobs)


def test_disabled_or_unconfigured_delivery_makes_zero_network_attempts(
    db_session, user_factory
):
    user = user_factory("no-network@example.com")
    notification, _ = produce_notification(
        db_session,
        user_id=user.id,
        event_family="research_review_due",
        subject_type="research_case",
        subject_key="case:1",
        source_version="v1",
        title="Review",
        body="Review is due.",
        evidence_route="/research/cases/1",
    )
    sender = Mock()
    with patch.object(settings, "NOTIFICATION_DELIVERY_ENABLED", False):
        result = deliver_pending_attempts(
            db_session,
            now=datetime.now(timezone.utc),
            adapters={"slack": SlackWebhookAdapter(sender=sender)},
        )
    assert notification.id
    assert result["attempted"] == 0
    sender.assert_not_called()


def test_quiet_hours_are_timezone_and_dst_aware():
    subscription = NotificationSubscription(
        user_id=1,
        event_family="research_review_due",
        frequency="immediate",
        timezone="America/Chicago",
        quiet_start_local="22:00",
        quiet_end_local="07:00",
        cooldown_minutes=60,
        is_enabled=True,
    )
    assert is_delivery_time_allowed(
        subscription, datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)
    ) is False  # 03:00 CDT
    assert is_delivery_time_allowed(
        subscription, datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc)
    ) is True  # 13:00 CDT


def test_notification_api_never_discloses_another_users_resources(
    client, db_session, user_factory, auth_headers
):
    owner = user_factory("notification-api-owner@example.com")
    other = user_factory("notification-api-other@example.com")
    manager = _manager(db_session, cik="0002234567")
    follow, _ = follow_manager(db_session, user_id=owner.id, manager_id=manager.id)

    response = client.delete(
        f"/api/v1/notifications/manager-follows/{follow.id}",
        headers=auth_headers(other),
    )
    assert response.status_code == 404
    rows = db_session.query(ManagerFollow).filter_by(user_id=owner.id).all()
    assert len(rows) == 1


def test_delivery_history_is_user_scoped_paginated_and_secret_free(
    client, db_session, user_factory, auth_headers
):
    owner = user_factory("delivery-history-owner@example.com")
    other = user_factory("delivery-history-other@example.com")
    keys = _keys()
    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", keys):
        destination, _ = create_or_update_slack_destination(
            db_session,
            user_id=owner.id,
            label="Research Slack",
            webhook_url="https://hooks.slack.com/services/T111/B222/HistorySecret333",
            consent=True,
        )
    notification, _ = produce_notification(
        db_session,
        user_id=owner.id,
        event_family="research_review_due",
        subject_type="research_case",
        subject_key="case:history",
        source_version="one",
        title="Review due",
        body="Review evidence.",
        evidence_route="/research/cases/1",
    )
    now = datetime.now(timezone.utc)
    db_session.add(
        NotificationDeliveryAttempt(
            logical_notification_id=notification.id,
            destination_id=destination.id,
            content_version=1,
            status="permanent_failure",
            attempt_count=2,
            scheduled_for=now,
            next_attempt_at=now,
            last_attempt_at=now,
            provider_response_class="permanent_provider_rejection",
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/notifications/delivery-attempts?limit=10",
        headers=auth_headers(owner),
    )
    hidden = client.get(
        "/api/v1/notifications/delivery-attempts?limit=10",
        headers=auth_headers(other),
    )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["status"] == "permanent_failure"
    assert response.json()["items"][0]["destination_hint"].endswith("/…/t333")
    assert "HistorySecret333" not in response.text
    assert "ciphertext" not in response.text
    assert hidden.json()["total"] == 0


def test_notification_operations_are_aggregate_admin_only_and_secret_free(
    client, db_session, user_factory, auth_headers
):
    admin = user_factory("notification-ops-admin@example.com", role="admin")
    ordinary = user_factory("notification-ops-user@example.com")
    owner = user_factory("notification-ops-owner@example.com")
    keys = _keys()
    with patch.object(settings, "NOTIFICATION_SECRET_KEYS", keys):
        destination, _ = create_or_update_slack_destination(
            db_session,
            user_id=owner.id,
            label="Private operations destination",
            webhook_url="https://hooks.slack.com/services/T111/B222/OpsSecret333",
            consent=True,
        )
    notification, _ = produce_notification(
        db_session,
        user_id=owner.id,
        event_family="research_review_due",
        subject_type="research_case",
        subject_key="case:ops",
        source_version="one",
        title="Private title",
        body="Private content.",
        evidence_route="/research/cases/1",
    )
    now = datetime.now(timezone.utc)
    db_session.add(
        NotificationDeliveryAttempt(
            logical_notification_id=notification.id,
            destination_id=destination.id,
            content_version=1,
            status="retry_scheduled",
            attempt_count=1,
            scheduled_for=now - timedelta(minutes=5),
            next_attempt_at=now + timedelta(minutes=1),
            last_attempt_at=now - timedelta(minutes=2),
            provider_response_class="transient_provider_failure",
        )
    )
    db_session.commit()

    forbidden = client.get(
        "/api/v1/notifications/admin/operations",
        headers=auth_headers(ordinary),
    )
    response = client.get(
        "/api/v1/notifications/admin/operations",
        headers=auth_headers(admin),
    )

    assert forbidden.status_code == 403
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["backlog"]["retry_scheduled"] == 1
    assert body["failures_by_class"]["transient_provider_failure"] == 1
    assert "OpsSecret333" not in response.text
    assert "Private title" not in response.text
    assert "Private operations destination" not in response.text
