from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.auth_tokens import RefreshToken
from app.models.notifications import NotificationDestination
from app.models.portfolios import PositionJournalEvent
from app.models.research import ResearchCase, ResearchCaseRevision
from app.models.stocks import Stock
from app.models.users import AccountErasureEvent
from app.schemas.portfolios import ManualPortfolioCreate, ManualPositionCreate
from app.services.manual_portfolios import create_portfolio, create_position


def test_account_erasure_revokes_credentials_and_tombstones_authored_content(
    client, db_session, user_factory, auth_headers
):
    user = user_factory(
        "erase-me@example.com",
        password="ErasePass123!",
    )
    stock = Stock(ticker="ERASE", exchange="NYSE", company_name="Erase Corp")
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
    audit = db_session.query(AccountErasureEvent).filter_by(user_id=user.id).one()
    assert audit.content_hash
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
