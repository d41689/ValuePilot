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


# securityType values that 13F common holdings legitimately resolve to. A
# 13F common-stock row (``put_call IS NULL``) is the issuer's primary US
# equity instrument; OpenFIGI labels these with one of the strings below
# (verified against live responses for AAPL / BABA / TSM / SPY / AMT /
# FWONK (Liberty Media Tracking Stk) / ASML (NY Reg Shrs) / etc., where
# securityType is ``ADR`` not ``Depositary Receipt``). Derivatives (Option /
# Warrant / Future) share the underlying's CUSIP only by coincidence and
# must NOT auto-link.
_EQUITY_LIKE_SECURITY_TYPES = frozenset({
    "COMMON STOCK",
    "ADR",
    "GDR",
    "NY REG SHRS",       # NY Registry Shares — ASML, etc.
    "TRACKING STK",      # Liberty Media tracker series (FWONK, LSXMK, …).
    "MLP",               # Master Limited Partnership (ARLP, EPD, …).
    "REIT",
    "ETP",
    "MUTUAL FUND",
    "OPEN-END FUND",
    "CLOSED-END FUND",
    "UNIT",
    "PREFERRED",
    "PREFERRED STOCK",
    "RECEIPT",           # Generic depositary receipts.
    "TRUST",             # Royalty / income trusts traded as common.
})


def evaluate_openfigi_matches(matches: List[Dict[str, Any]]) -> tuple[str, str, Optional[str], Optional[str]]:
    """Determine confidence and auto-confirm rules for OpenFIGI matches.

    Returns: (confidence, reason, ticker, name)

    Pre-MVP8-01 (2026-05-13): the OpenFIGI ``mapCusips`` response
    returns ALL global listings for a CUSIP — equity exchanges
    worldwide, options chains, bond instruments, ADRs, etc. A
    typical equity CUSIP (e.g. Apple 037833100) returns 200+ matches.
    The original auto-confirm rule (``len(matches) == 1``) was
    therefore unreachable for real equity CUSIPs.

    2026-05-22 (this revision): the previous rule required
    ``securityType=COMMON STOCK`` AND ``exchCode=US`` for auto-confirm,
    which excluded every ADR (TSM, BABA, DEO, …), REIT (AMT, BXP, …),
    and ETP (SPY, GLD, EFA, …). OpenFIGI returns those under their own
    securityType (``Depositary Receipt`` / ``REIT`` / ``ETP``), so they
    fell through to the catch-all review_needed:low even though their
    US ticker is unambiguous. The rule now auto-confirms when **all
    equity-like listings (see _EQUITY_LIKE_SECURITY_TYPES) on US
    exchanges agree on a single ticker**. Cross-listing safety is
    preserved: if two US-exchange equity-like listings disagree on a
    ticker, we still send the CUSIP to the review queue.
    """
    if not matches:
        return ("low", "No match found in OpenFIGI", None, None)

    # Filter to US-exchange listings whose securityType is an actual equity
    # instrument that a 13F common-holding row could legitimately resolve to.
    # ``exchCode=US`` covers NYSE / Nasdaq / AMEX / OTC. Cross-listings on
    # LN, JT, etc. are intentionally ignored — they share the CUSIP but are
    # not what the 13F filing references.
    us_equity = [
        m for m in matches
        if str(m.get("exchCode", "")).upper() == "US"
        and str(m.get("securityType", "")).upper() in _EQUITY_LIKE_SECURITY_TYPES
    ]

    if us_equity:
        tickers = {m.get("ticker") for m in us_equity if m.get("ticker")}
        if len(tickers) == 1:
            ticker = next(iter(tickers))
            # Prefer a COMMON STOCK listing as the canonical representative
            # for the issuer name; fall back to the first equity listing
            # otherwise (e.g. an ADR-only / ETP-only / REIT-only set).
            common = next(
                (m for m in us_equity if str(m.get("securityType", "")).upper() == "COMMON STOCK"),
                None,
            )
            representative = common or us_equity[0]
            sec_types = sorted({str(m.get("securityType", "")) for m in us_equity if m.get("securityType")})
            return (
                "high",
                f"US-exchange match ({len(us_equity)} listings, all → {ticker}; types: {sec_types})",
                ticker,
                representative.get("name"),
            )
        # Multiple US equity-exchange listings on different tickers — review.
        return (
            "review_needed:low",
            f"Multiple US-exchange matches with conflicting tickers: {sorted(t for t in tickers if t)}",
            None,
            None,
        )

    # No US-exchange equity listing — fall back to existing heuristics for
    # non-US-only or derivative-only matches so the admin queue still gets
    # the context needed to triage.
    if len(matches) == 1:
        match = matches[0]
        sec_type = str(match.get("securityType", "")).upper()
        exch_code = str(match.get("exchCode", "")).upper()
        return (
            "review_needed:medium",
            f"Single match but exchange '{exch_code}' / type '{sec_type}' (no US equity listing)",
            match.get("ticker"),
            match.get("name"),
        )
    return (
        "review_needed:low",
        f"Multiple ({len(matches)}) matches, no US-exchange equity listing",
        None,
        None,
    )


def enrich_unmapped_holdings(db: Session, client: Optional[OpenFigiClient] = None, limit: int = 100) -> int:
    """Find holdings that are pending mapping, fetch OpenFIGI, and update them."""
    
    # 1. Fetch holdings that still need a CUSIP->ticker mapping AND whose CUSIP
    #    has no cusip_ticker_map row yet. `pending_mapping` (freshly ingested)
    #    and `unresolved` are both enrichable; `needs_review` is the ambiguous-
    #    result human queue and is excluded. A holding can be `unresolved`
    #    either because OpenFIGI was never consulted for its CUSIP or because it
    #    was and returned no usable match — the `cusip NOT IN cusip_ticker_map`
    #    clause excludes the latter (its CUSIP already has a row), so OpenFIGI
    #    is never re-queried and a run-to-completion loop terminates (see
    #    enrich_all_unmapped_holdings).
    mapped_cusips = db.query(CusipTickerMap.cusip).filter(CusipTickerMap.cusip.isnot(None))
    pending_holdings = (
        db.query(Holding13F)
        .filter(Holding13F.cusip_mapping_status.in_(["pending_mapping", "unresolved"]))
        .filter(Holding13F.cusip.isnot(None))
        .filter(~Holding13F.cusip.in_(mapped_cusips))
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
    
    owns_client = client is None
    if owns_client:
        client = OpenFigiClient()

    try:
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
    finally:
        # Close the client only if we created it — an injected client is the
        # caller's to manage.
        if owns_client:
            client.close()


def _count_enrichable_holdings(db: Session) -> int:
    """Holdings still needing a CUSIP->ticker mapping whose CUSIP has no
    cusip_ticker_map row yet — the OpenFIGI enrichment work remaining."""
    mapped_cusips = db.query(CusipTickerMap.cusip).filter(CusipTickerMap.cusip.isnot(None))
    return (
        db.query(Holding13F)
        .filter(Holding13F.cusip_mapping_status.in_(["pending_mapping", "unresolved"]))
        .filter(Holding13F.cusip.isnot(None))
        .filter(~Holding13F.cusip.in_(mapped_cusips))
        .count()
    )


def enrich_all_unmapped_holdings(
    db: Session,
    *,
    client: Optional[OpenFigiClient] = None,
    batch_size: int = 100,
    max_batches: int = 300,
) -> dict[str, int]:
    """Run OpenFIGI CUSIP enrichment to completion, then bootstrap + backfill.

    Loops `enrich_unmapped_holdings` batch by batch until no holding with an
    unmapped CUSIP remains — each batch maps (and so removes from the pool)
    every CUSIP it touches, so the loop terminates — then creates Stock rows
    and links holdings. `max_batches` is a hard safety cap; OpenFIGI rate
    limiting is owned by Rate Guard, so the loop itself does not throttle.
    """
    owns_client = client is None
    if owns_client:
        client = OpenFigiClient()
    total_mapped = 0
    batches = 0
    try:
        while batches < max_batches:
            before = _count_enrichable_holdings(db)
            if before == 0:
                break
            total_mapped += enrich_unmapped_holdings(db, client=client, limit=batch_size)
            batches += 1
            if _count_enrichable_holdings(db) >= before:
                # No progress — guard against an unexpected stall.
                logger.warning(
                    "enrich_all_unmapped_holdings: batch %d made no progress, stopping",
                    batches,
                )
                break
    finally:
        if owns_client:
            client.close()
    # bootstrap + backfill run after a completed loop. A mid-loop failure
    # propagates here without bootstrapping (the enrich_cusip job fails) — but
    # each batch's mappings are already committed and the loop is resumable
    # (already-mapped CUSIPs are skipped), so the retriable job recovers on the
    # next run. DB-mutating bootstrap/backfill are deliberately kept off the
    # exception path.
    new_stocks = bootstrap_stocks_from_cusip_map(db)
    holdings_linked = backfill_stock_ids(db)
    return {
        "mappings_created": total_mapped,
        "batches_run": batches,
        "new_stocks": new_stocks,
        "holdings_linked": holdings_linked,
        "holdings_still_unmapped": _count_enrichable_holdings(db),
    }


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
        # Temporal-validity contract (external review R2-P2): a holding can
        # only be safely linked to a CUSIP mapping if we can check the
        # mapping's valid_from/valid_to window against the holding's
        # quarter_end_date. When quarter_end_date is NULL we CANNOT — linking
        # anyway risks attaching a mapping from the wrong side of a
        # corporate-action boundary. So leave the holding pending and let a
        # later run (after period routing populates quarter_end_date) link
        # it. In the normal pipeline, routing runs before enrichment, so
        # this branch should not be hit; it only guards stragglers.
        if h.quarter_end_date is None:
            h.cusip_mapping_status = "pending_mapping"
            h.stock_id = None
            continue

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
