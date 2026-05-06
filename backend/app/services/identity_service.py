from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.stocks import Stock
from app.models.artifacts import PdfDocument
from app.ingestion.parsers.base import IdentityInfo
from app.core.stock_identity import canonical_market_country, normalize_listing_exchange

class IdentityService:
    def __init__(self, db: Session):
        self.db = db

    def resolve_stock(self, identity_info: IdentityInfo) -> tuple[Stock, bool, str | None]:
        """
        Resolves (or creates) a Stock from extracted identity info.

        Returns:
          (stock, identity_needs_review, note)
        """
        if not identity_info.ticker:
            raise ValueError("Could not extract ticker.")

        ticker = identity_info.ticker.upper()
        raw_exchange = identity_info.exchange.upper() if identity_info.exchange else None
        market_country = canonical_market_country(raw_exchange, ticker=ticker)
        listing_exchange = normalize_listing_exchange(raw_exchange)

        stmt = select(Stock).where(
            Stock.ticker == ticker,
            Stock.market_country == market_country,
            Stock.is_active.is_(True),
        )
        stock = self.db.scalar(stmt)

        needs_review = False
        note: str | None = None

        if stock:
            if identity_info.company_name:
                similarity = SequenceMatcher(
                    None, stock.company_name.lower(), identity_info.company_name.lower()
                ).ratio()
                if similarity < 0.6:
                    needs_review = True
                    note = (
                        f"Name mismatch: '{stock.company_name}' vs extracted '{identity_info.company_name}'"
                    )
                else:
                    stock.company_name = identity_info.company_name
            _update_listing_metadata(stock, listing_exchange, raw_exchange)
            return stock, needs_review, note

        stock = Stock(
            ticker=ticker,
            exchange=listing_exchange or market_country,
            market_country=market_country,
            listing_exchange=listing_exchange,
            raw_exchange=raw_exchange,
            company_name=identity_info.company_name or "Unknown Company",
        )
        self.db.add(stock)
        self.db.flush()

        if not identity_info.company_name:
            needs_review = True
            note = "New stock created without company name."

        return stock, needs_review, note

    def resolve_stock_identity(self, document: PdfDocument, identity_info: IdentityInfo) -> None:
        """
        Resolves the stock identity for a document based on extracted info.
        Updates the document's stock_id and identity_needs_review flags.
        """
        try:
            stock, needs_review, note = self.resolve_stock(identity_info)
        except ValueError as e:
            document.identity_needs_review = True
            document.notes = (document.notes or "") + f"\n{str(e)}"
            self.db.add(document)
            self.db.flush()
            return

        document.stock_id = stock.id
        if needs_review:
            document.identity_needs_review = True
            if note:
                document.notes = (document.notes or "") + f"\n{note}"

        self.db.add(document)
        self.db.flush()


def _update_listing_metadata(
    stock: Stock,
    listing_exchange: str | None,
    raw_exchange: str | None,
) -> None:
    if listing_exchange and not stock.listing_exchange:
        stock.listing_exchange = listing_exchange
    if listing_exchange and stock.exchange == stock.market_country:
        stock.exchange = listing_exchange
    if raw_exchange and not stock.raw_exchange:
        stock.raw_exchange = raw_exchange
