from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.stocks import Stock
from app.models.artifacts import PdfDocument
from app.ingestion.parsers.base import IdentityInfo

class IdentityService:
    def __init__(self, db: Session):
        self.db = db

    def resolve_stock_identity(self, document: PdfDocument, identity_info: IdentityInfo) -> None:
        """
        Resolves the stock identity for a document based on extracted info.
        Updates the document's stock_id and identity_needs_review flags.
        """
        if not identity_info.ticker:
            document.identity_needs_review = True
            document.notes = (document.notes or "") + "\nCould not extract ticker."
            self.db.add(document)
            self.db.commit()
            return

        ticker = identity_info.ticker.upper()
        # Normalize exchange if needed (e.g., NDQ -> NASDAQ). For V1 we store as extracted or map it.
        # Let's assume we store the raw code for now or a simplified version.
        exchange = identity_info.exchange.upper() if identity_info.exchange else "UNKNOWN"

        # 1. Try to find existing stock
        stmt = select(Stock).where(Stock.ticker == ticker)
        existing_stock = self.db.scalar(stmt)

        if existing_stock:
            document.stock_id = existing_stock.id
            
            # Check name similarity
            if identity_info.company_name:
                similarity = SequenceMatcher(None, existing_stock.company_name.lower(), identity_info.company_name.lower()).ratio()
                if similarity < 0.6: # Threshold
                    document.identity_needs_review = True
                    document.notes = (document.notes or "") + f"\nName mismatch: '{existing_stock.company_name}' vs extracted '{identity_info.company_name}'"
            
        else:
            # 2. Auto-create new stock
            new_stock = Stock(
                ticker=ticker,
                exchange=exchange,
                company_name=identity_info.company_name or "Unknown Company"
            )
            self.db.add(new_stock)
            self.db.commit()
            self.db.refresh(new_stock)
            
            document.stock_id = new_stock.id
            # If we just created it from this doc, the name matches by definition, 
            # but we might flag it if the name was missing.
            if not identity_info.company_name:
                document.identity_needs_review = True
                document.notes = (document.notes or "") + "\nNew stock created without company name."

        self.db.add(document)
        self.db.commit()
