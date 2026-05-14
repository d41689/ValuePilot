"""CUSIP → ticker enrichment service using OpenFIGI.

Implements strict temporal overlap rules and application-level 64-bit advisory locks
to prevent race conditions when mapping identical CUSIPs concurrently.
"""
import logging
import struct
import hashlib
from datetime import date, datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.institutions import CusipTickerMap, Holding13F, InstitutionManager
from app.models.stocks import Stock
from app.openfigi.client import OpenFigiClient
from app.services.cusip_validation import is_valid_cusip

logger = logging.getLogger(__name__)


def _cusip_lock_id(cusip: str) -> int:
    """Generate a 64-bit integer hash from the CUSIP for pg_try_advisory_xact_lock."""
    digest = hashlib.sha256(cusip.encode()).digest()
    return struct.unpack("<q", digest[:8])[0]


def _active_mapping(db: Session, cusip: str, valid_from: Optional[date]) -> Optional[CusipTickerMap]:
    """Return existing active mapping for this cusip/valid_from combination."""
    q = db.query(CusipTickerMap).filter_by(cusip=cusip, is_active=True)
    if valid_from is not None:
        q = q.filter_by(valid_from=valid_from)
    else:
        q = q.filter(CusipTickerMap.valid_from.is_(None))
    return q.one_or_none()


def _has_overlap(db: Session, cusip: str, new_from: Optional[date], new_to: Optional[date], exclude_id: Optional[int] = None) -> bool:
    """Check whether any existing active interval for this CUSIP overlaps [new_from, new_to]."""
    q = db.query(CusipTickerMap).filter_by(cusip=cusip, is_active=True)
    if exclude_id is not None:
        q = q.filter(CusipTickerMap.id != exclude_id)
    existing = q.all()
    
    for row in existing:
        r_from = row.valid_from
        r_to = row.valid_to
        
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
    """Insert new CUSIP mapping with concurrency safety and strict temporal validity rules."""
    
    lock_id = _cusip_lock_id(cusip)
    locked = db.execute(text("SELECT pg_try_advisory_xact_lock(:id)"), {"id": lock_id}).scalar()
    if not locked:
        raise RuntimeError(f"Could not acquire advisory lock for CUSIP {cusip}")

    _CONFIDENCE_RANK = {"manual": 4, "high": 3, "medium": 2, "low": 1}
    new_rank = _CONFIDENCE_RANK.get(confidence, 0)

    existing = _active_mapping(db, cusip, valid_from)
    if existing is not None:
        existing_rank = _CONFIDENCE_RANK.get(existing.confidence or "", 0)
        if new_rank <= existing_rank:
            # Do not overwrite with lower or equal confidence for the same interval
            return existing
        existing.is_active = False
        db.add(existing)

    if _has_overlap(db, cusip, valid_from, valid_to, exclude_id=existing.id if existing else None):
        logger.warning(
            "CUSIP %s: new interval [%s, %s] overlaps existing — flagging for review",
            cusip,
            valid_from,
            valid_to,
        )
        if not confidence.startswith("review_needed:"):
            confidence = f"review_needed:{confidence}"

    from sqlalchemy.exc import SQLAlchemyError

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
    try:
        with db.begin_nested():
            db.flush()
    except SQLAlchemyError as exc:
        logger.warning("upsert_cusip_mapping flush failed for %s: %s", cusip, exc)
        raise
    return mapping


def evaluate_openfigi_matches(matches: List[Dict[str, Any]]) -> tuple[str, str, Optional[str], Optional[str]]:
    """Determine confidence and auto-confirm rules for OpenFIGI matches.

    Returns: (confidence, reason, ticker, name)

    Pre-MVP8-01 (2026-05-13): the OpenFIGI ``mapCusips`` response
    returns ALL global listings for a CUSIP — equity exchanges
    worldwide, options chains, bond instruments, ADRs, etc. A
    typical equity CUSIP (e.g. Apple 037833100) returns 200+ matches.
    The original auto-confirm rule (``len(matches) == 1``) was
    therefore unreachable for real equity CUSIPs. The rule now
    filters to US Common Stock listings FIRST, then auto-confirms
    when all US Common Stock entries agree on a single ticker.
    """
    if not matches:
        return ("low", "No match found in OpenFIGI", None, None)

    # Filter to US Common Stock equity listings.
    us_common = [
        m for m in matches
        if str(m.get("securityType", "")).upper() == "COMMON STOCK"
        and str(m.get("exchCode", "")).upper() == "US"
    ]

    if us_common:
        tickers = {m.get("ticker") for m in us_common if m.get("ticker")}
        if len(tickers) == 1:
            ticker = next(iter(tickers))
            first = us_common[0]
            return (
                "high",
                f"US Common Stock match ({len(us_common)} listings, all → {ticker})",
                ticker,
                first.get("name"),
            )
        # Multiple US Common Stock matches with different tickers — needs review.
        return (
            "review_needed:low",
            f"Multiple US Common Stock matches with conflicting tickers: {sorted(t for t in tickers if t)}",
            None,
            None,
        )

    # No US Common Stock match — fall back to existing heuristics for
    # non-equity / non-US listings so the admin queue still gets the
    # context needed to triage.
    if len(matches) == 1:
        match = matches[0]
        sec_type = str(match.get("securityType", "")).upper()
        exch_code = str(match.get("exchCode", "")).upper()
        return (
            "review_needed:medium",
            f"Single match but type '{sec_type}' or exchange '{exch_code}' (not US Common Stock)",
            match.get("ticker"),
            match.get("name"),
        )
    return (
        "review_needed:low",
        f"Multiple ({len(matches)}) matches, no US Common Stock listing",
        None,
        None,
    )


def enrich_unmapped_holdings(db: Session, client: Optional[OpenFigiClient] = None, limit: int = 100) -> int:
    """Find holdings that are pending mapping, fetch OpenFIGI, and update them."""
    
    # 1. Fetch pending CUSIPs
    pending_holdings = (
        db.query(Holding13F)
        .filter(Holding13F.cusip_mapping_status == "pending_mapping")
        .limit(limit)
        .all()
    )
    
    if not pending_holdings:
        return 0
        
    # Validation Pass
    valid_cusips = set()
    invalid_count = 0
    for h in pending_holdings:
        if not is_valid_cusip(h.cusip):
            h.cusip_mapping_status = "invalid_cusip"
            invalid_count += 1
        else:
            valid_cusips.add(h.cusip)
            
    if invalid_count > 0:
        db.commit()
        
    cusips_to_map = list(valid_cusips)
    if not cusips_to_map:
        return 0
    
    if client is None:
        client = OpenFigiClient()
        
    results = client.map_cusips(cusips_to_map)
    
    # Process results
    mapped_count = 0
    for cusip, matches in zip(cusips_to_map, results):
        confidence, reason, ticker, name = evaluate_openfigi_matches(matches)
        
        try:
            mapping = upsert_cusip_mapping(
                db,
                cusip=cusip,
                ticker=ticker,
                issuer_name=name,
                source="openfigi",
                mapping_reason=reason,
                confidence=confidence,
            )
            mapped_count += 1
        except Exception as exc:
            logger.warning("Failed to persist mapping for CUSIP %s: %s", cusip, exc)
            
    # After generating mappings, apply them to holdings
    _apply_mappings_to_holdings(db, cusips_to_map)
    
    return mapped_count


def enrich_cusips_from_openfigi(db: Session, limit: int = 100) -> int:
    """OpenFIGI-backed CUSIP enrichment entrypoint.

    Dataroma is not used for CUSIP or security-identity mapping. It remains a
    manager-discovery hint only.
    """
    return enrich_unmapped_holdings(db, limit=limit)


def enrich_from_dataroma(db: Session, limit: int = 100) -> int:
    """Deprecated compatibility alias; does not call Dataroma.

    Use enrich_cusips_from_openfigi for new code. This alias exists only for
    older callers while MVP3-01 removes legacy naming from active surfaces.
    """
    return enrich_cusips_from_openfigi(db, limit=limit)


def bootstrap_stocks_from_cusip_map(db: Session) -> int:
    """Create Stock rows for high-confidence active CUSIP mappings with tickers."""
    mappings = (
        db.query(CusipTickerMap)
        .filter(CusipTickerMap.is_active.is_(True))
        .filter(CusipTickerMap.ticker.isnot(None))
        .filter(~CusipTickerMap.confidence.like("review_needed:%"))
        .all()
    )
    created = 0
    for mapping in mappings:
        existing = (
            db.query(Stock)
            .filter_by(ticker=mapping.ticker, market_country="US", is_active=True)
            .first()
        )
        if existing:
            continue
        db.add(
            Stock(
                ticker=mapping.ticker,
                company_name=mapping.issuer_name or mapping.ticker,
                exchange="US",
                market_country="US",
                is_active=True,
            )
        )
        created += 1
    if created:
        db.commit()
    return created


def backfill_stock_ids(db: Session) -> int:
    """Apply existing CUSIP mappings to holdings and return linked holding count."""
    cusips = [row[0] for row in db.query(Holding13F.cusip).filter(Holding13F.cusip.isnot(None)).distinct().all()]
    if not cusips:
        return 0
    _apply_mappings_to_holdings(db, cusips)
    return db.query(Holding13F).filter(Holding13F.stock_id.isnot(None)).count()


def enrich_stocks_from_edgar_tickers(db: Session) -> dict[str, int]:
    """Compatibility placeholder for legacy stock enrichment pipeline stage."""
    return {"new_mappings": 0}


def _apply_mappings_to_holdings(db: Session, cusips: List[str]) -> None:
    """Update stock_id and cusip_mapping_status on holdings for the given CUSIPs."""
    holdings = (
        db.query(Holding13F)
        .filter(Holding13F.cusip.in_(cusips))
        .filter(Holding13F.cusip_mapping_status.in_(["pending_mapping", "unresolved", "needs_review"]))
        .all()
    )
    
    for h in holdings:
        # Determine the effective mapping for this holding based on its quarter_end_date
        mapping = (
            db.query(CusipTickerMap)
            .filter_by(cusip=h.cusip, is_active=True)
            .filter(
                (CusipTickerMap.valid_from.is_(None) | (CusipTickerMap.valid_from <= h.quarter_end_date)) &
                (CusipTickerMap.valid_to.is_(None) | (CusipTickerMap.valid_to >= h.quarter_end_date))
            )
            .order_by(CusipTickerMap.id.desc())
            .first()
        )
        
        if not mapping:
            h.cusip_mapping_status = "unresolved"
            h.stock_id = None
            continue
            
        if mapping.confidence and "review_needed" in mapping.confidence:
            h.cusip_mapping_status = "needs_review"
            h.stock_id = None
            continue
            
        if not mapping.ticker:
            h.cusip_mapping_status = "unresolved"
            h.stock_id = None
            continue
            
        # Try to resolve to a Stock
        stock = db.query(Stock).filter_by(ticker=mapping.ticker, market_country="US", is_active=True).first()
        if not stock:
            # Auto-create the stock if it's high confidence US Common Stock
            stock = Stock(
                ticker=mapping.ticker,
                company_name=mapping.issuer_name or mapping.ticker,
                exchange="US",
                market_country="US",
                is_active=True,
            )
            db.add(stock)
            db.flush()
            
        h.stock_id = stock.id
        h.cusip_mapping_status = "linked"
        
    db.commit()
