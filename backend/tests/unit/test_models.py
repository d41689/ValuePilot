from sqlalchemy.orm import Session
from app.models.users import User, NotificationSettings
from app.models.stocks import Stock, StockPrice
from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact

def test_create_user(db_session: Session):
    user = User(email="test_model@example.com")
    db_session.add(user)
    db_session.commit()
    
    assert user.id is not None
    assert user.email == "test_model@example.com"
    assert user.created_at is not None

def test_user_notification_relationship(db_session: Session):
    user = User(email="notify@example.com")
    settings = NotificationSettings(
        channel="email", 
        frequency="weekly",
        send_time_local="09:00",
        timezone="UTC"
    )
    user.notification_settings = settings
    db_session.add(user)
    db_session.commit()

    retrieved_user = db_session.query(User).filter_by(email="notify@example.com").first()
    assert retrieved_user.notification_settings is not None
    assert retrieved_user.notification_settings.frequency == "weekly"

def test_create_stock_and_price(db_session: Session):
    stock = Stock(ticker="AAPL", exchange="NASDAQ", company_name="Apple Inc.")
    db_session.add(stock)
    db_session.commit()
    
    price = StockPrice(
        stock_id=stock.id, 
        price_date="2024-01-01", 
        open=100.0, high=110.0, low=90.0, close=105.0, 
        source="test"
    )
    db_session.add(price)
    db_session.commit()

    assert len(stock.prices) == 1
    assert stock.prices[0].close == 105.0

def test_create_pdf_document(db_session: Session):
    user = User(email="docs@example.com")
    db_session.add(user)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="report.pdf",
        source="upload",
        file_storage_key="s3://bucket/report.pdf",
        parse_status="pending"
    )
    db_session.add(doc)
    db_session.commit()

    assert doc.id is not None
    assert doc.user.email == "docs@example.com"

def test_create_metric_fact(db_session: Session):
    user = User(email="fact@example.com")
    stock = Stock(ticker="MSFT", exchange="NASDAQ", company_name="Microsoft")
    db_session.add(user)
    db_session.add(stock)
    db_session.commit()

    fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="pe_ratio",
        value_json={"value": 30.5},
        value_numeric=30.5,
        source_type="manual"
    )
    db_session.add(fact)
    db_session.commit()

    assert fact.id is not None
    assert fact.value_numeric == 30.5
    assert fact.stock.ticker == "MSFT"
