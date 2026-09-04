"""One stock-scoped ordering boundary for metric-fact reads and mutations."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


METRIC_FACT_STOCK_LOCK_NAMESPACE = "valuepilot:metric-facts-stock:"


def acquire_metric_fact_stock_lock(session: Session, *, stock_id: int) -> None:
    """Take M before any research-case lock that can lead to a fact write."""

    session.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(:lock_key, 0))"
        ),
        {"lock_key": f"{METRIC_FACT_STOCK_LOCK_NAMESPACE}{stock_id}"},
    )
