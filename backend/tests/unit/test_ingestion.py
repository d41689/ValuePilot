import pytest
from app.models.users import User
from app.ingestion.normalization.scaler import Scaler
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.parsers.base import IdentityInfo
from app.services.identity_service import IdentityService
from app.models.stocks import Stock
from app.models.artifacts import PdfDocument

def test_scaler_normalization():
    # Test Currency / Scale
    val, unit = Scaler.normalize("$1.2 bil", "number")
    assert val == 1_200_000_000.0
    assert unit == "USD"

    val, unit = Scaler.normalize("350 mil.", "number")
    assert val == 350_000_000.0
    assert unit == "number" # No $ sign

    val, unit = Scaler.normalize("$500", "number")
    assert val == 500.0
    assert unit == "USD"

    # Test Percent
    val, unit = Scaler.normalize("5.4%", "percent")
    assert val == pytest.approx(0.054)
    assert unit == "ratio"

    val, unit = Scaler.normalize("10.5", "ratio")
    assert val == 10.5
    assert unit == "ratio"
    
    # Test Invalid
    val, unit = Scaler.normalize("invalid", "number")
    assert val is None

def test_parser_identity_extraction():
    # Mock text similar to Value Line header
    text = """
    VALUE LINE SURVEY
    PAGE 1234   JANUARY 1, 2024
    SOME CORP.    XYZ (NDQ)
    RECENT PRICE 100.00
    """
    parser = ValueLineV1Parser(text)
    info = parser.extract_identity()
    
    assert info.ticker == "XYZ"
    assert info.exchange == "NDQ"
    assert info.company_name == "SOME CORP."

def test_parser_metric_extraction():
    text = """
    RECENT PRICE 120.50
    P/E RATIO 15.2
    DIV'D YLD 2.5%
    """
    parser = ValueLineV1Parser(text)
    results = parser.parse()
    
    assert len(results) == 3
    
    # Check Price
    price = next(r for r in results if r.field_key == "recent_price")
    assert price.raw_value_text == "120.50"
    
    # Check P/E
    pe = next(r for r in results if r.field_key == "pe_ratio")
    assert pe.raw_value_text == "15.2"
    
    # Check Yield
    yld = next(r for r in results if r.field_key == "dividend_yield")
    assert yld.raw_value_text == "2.5%"

def test_identity_service_resolution(db_session):
    service = IdentityService(db_session)
    
    # Create dummy user
    user = User(email="ingestion_test@example.com")
    db_session.add(user)
    db_session.commit()

    # Case 1: New Stock
    doc = PdfDocument(user_id=user.id, file_name="test.pdf", source="upload", file_storage_key="k", parse_status="pending")
    # Need to add doc to session for foreign key to work? No, doc.stock_id can be null initially.
    # But usually doc is already added.
    db_session.add(doc)
    
    info = IdentityInfo(ticker="NEW", exchange="NYS", company_name="New Corp")
    service.resolve_stock_identity(doc, info)
    
    assert doc.stock_id is not None
    stock = db_session.get(Stock, doc.stock_id)
    assert stock.ticker == "NEW"
    assert stock.company_name == "New Corp"
    assert doc.identity_needs_review is False

    # Case 2: Existing Stock
    info2 = IdentityInfo(ticker="NEW", exchange="NYS", company_name="New Corp Inc") # Slightly diff name
    doc2 = PdfDocument(user_id=user.id, file_name="test2.pdf", source="upload", file_storage_key="k2", parse_status="pending")
    db_session.add(doc2)
    
    service.resolve_stock_identity(doc2, info2)
    assert doc2.stock_id == stock.id # Should link to same stock