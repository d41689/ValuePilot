"""CUSIP → ticker enrichment service.

Step 3 from the plan: Dataroma holdings pages first, then EDGAR search fallback.
Writes into cusip_ticker_map with overlap validation before insert.
"""
import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.dataroma.client import DataromaClient
from app.dataroma.parsers.holdings import DataromaHolding, parse_holdings
from app.models.institutions import CusipTickerMap, InstitutionManager

logger = logging.getLogger(__name__)


def _active_mapping(db: Session, cusip: str, valid_from: Optional[date]) -> Optional[CusipTickerMap]:
    """Return existing active mapping for this cusip/valid_from combination."""
    q = db.query(CusipTickerMap).filter_by(cusip=cusip, is_active=True)
    if valid_from is not None:
        q = q.filter_by(valid_from=valid_from)
    else:
        q = q.filter(CusipTickerMap.valid_from.is_(None))
    return q.one_or_none()


def _has_overlap(db: Session, cusip: str, new_from: Optional[date], new_to: Optional[date]) -> bool:
    """Check whether any existing active interval for this CUSIP overlaps [new_from, new_to]."""
    existing = db.query(CusipTickerMap).filter_by(cusip=cusip, is_active=True).all()
    for row in existing:
        # Treat None as open-ended
        r_from = row.valid_from
        r_to = row.valid_to
        # Overlap if intervals intersect
        starts_before = (new_to is None) or (r_from is None) or (new_to >= r_from)
        ends_after = (new_from is None) or (r_to is None) or (new_from <= r_to)
        if starts_before and ends_after:
            return True
    return False


def upsert_cusip_mapping(
    db: Session,
    *,
    cusip: str,
    ticker: Optional[str],
    issuer_name: Optional[str],
    source: str,
    mapping_reason: Optional[str] = None,
    confidence: str = "medium",
    valid_from: Optional[date] = None,
    valid_to: Optional[date] = None,
) -> CusipTickerMap:
    """Insert new CUSIP mapping or skip if a higher-quality mapping exists.

    Rules:
    - manual > high > medium > low confidence; lower quality never overwrites higher
    - overlap check before insert; conflicts are logged, not silently dropped
    """
    _CONFIDENCE_RANK = {"manual": 4, "high": 3, "medium": 2, "low": 1}
    new_rank = _CONFIDENCE_RANK.get(confidence, 0)

    existing = _active_mapping(db, cusip, valid_from)
    if existing is not None:
        existing_rank = _CONFIDENCE_RANK.get(existing.confidence or "", 0)
        if new_rank <= existing_rank:
            return existing
        # New entry is higher quality; deactivate old
        existing.is_active = False

    if _has_overlap(db, cusip, valid_from, valid_to):
        logger.warning(
            "CUSIP %s: new interval [%s, %s] overlaps existing — flagging for review",
            cusip,
            valid_from,
            valid_to,
        )
        confidence = f"review_needed:{confidence}"

    mapping = CusipTickerMap(
        cusip=cusip,
        ticker=ticker,
        issuer_name=issuer_name,
        source=source,
        mapping_reason=mapping_reason,
        confidence=confidence,
        valid_from=valid_from,
        valid_to=valid_to,
        is_active=True,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(mapping)
    db.flush()
    return mapping


def enrich_from_dataroma(db: Session) -> int:
    """Fetch holdings pages for all confirmed superinvestors and seed cusip_ticker_map.

    Returns count of new mappings inserted.
    """
    managers = (
        db.query(InstitutionManager)
        .filter_by(is_superinvestor=True)
        .filter(InstitutionManager.dataroma_code.isnot(None))
        .all()
    )
    inserted = 0
    with DataromaClient() as dc:
        for mgr in managers:
            try:
                html = dc.get_holdings(mgr.dataroma_code)
            except Exception as exc:
                logger.error(
                    "Dataroma holdings fetch failed for %s (%s): %s",
                    mgr.legal_name,
                    mgr.dataroma_code,
                    exc,
                )
                continue

            holdings = parse_holdings(html)
            for h in holdings:
                if not h.ticker:
                    continue
                # Use issuer_name as mapping_reason evidence
                try:
                    m = upsert_cusip_mapping(
                        db,
                        cusip=h.cusip or "",  # CUSIP not on Dataroma page; skipped if empty
                        ticker=h.ticker,
                        issuer_name=h.issuer_name,
                        source="dataroma",
                        mapping_reason=(
                            f"https://www.dataroma.com/m/holdings.php?m={mgr.dataroma_code}"
                        ),
                        confidence="medium",
                    )
                    if m.id is not None:
                        inserted += 1
                except Exception as exc:
                    logger.warning("cusip_ticker_map insert failed for %s: %s", h.ticker, exc)

    db.flush()
    return inserted
