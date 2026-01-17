from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.stocks import Stock
from app.models.artifacts import PdfDocument
from app.ingestion.parsers.base import IdentityInfo

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
        exchange = identity_info.exchange.upper() if identity_info.exchange else "UNKNOWN"

        stmt = select(Stock).where(Stock.ticker == ticker, Stock.exchange == exchange)
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
            return stock, needs_review, note

        stock = Stock(
            ticker=ticker,
            exchange=exchange,
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
