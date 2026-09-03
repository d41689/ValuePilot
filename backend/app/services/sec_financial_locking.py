"""One transaction-scoped lock domain for SEC lineage visibility/publication."""

from sqlalchemy import text
from sqlalchemy.orm import Session


SEC_FINANCIAL_STOCK_LOCK_NAMESPACE = "sec-financial-authority-stock"


def acquire_sec_financial_stock_lock(db: Session, *, stock_id: int) -> None:
    """Serialize one stock's lineage availability and publication universe."""

    if not isinstance(stock_id, int) or isinstance(stock_id, bool) or stock_id <= 0:
        raise ValueError("SEC financial stock lock requires a positive stock id")
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"{SEC_FINANCIAL_STOCK_LOCK_NAMESPACE}:{stock_id}"},
    )
