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
from app.models.institutions import CusipTickerMap, Holding13F, InstitutionManager
from app.models.stocks import Stock

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

    from sqlalchemy.exc import SQLAlchemyError

    mapping = CusipTickerMap(
        cusip=cusip,
        ticker=ticker,
        issuer_name=issuer_name,
        source=source[:20],           # VARCHAR(20) guard
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


def _normalize_name(name: str) -> str:
    """Lowercase, strip legal suffixes and punctuation for comparison."""
    import re
    s = name.lower()
    s = re.sub(r"\b(inc|corp|co|ltd|llc|lp|plc|nv|ag|sa|the|class [a-z]|cl [a-z])\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _name_score(a: str, b: str) -> float:
    """Containment ratio: fraction of shorter token set covered by larger."""
    ta = {t for t in a.split() if len(t) > 1}
    tb = {t for t in b.split() if len(t) > 1}
    if not ta or not tb:
        return 0.0
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(smaller & larger) / len(smaller)


def enrich_from_dataroma(db: Session) -> int:
    """Seed cusip_ticker_map by matching Dataroma tickers to holdings by issuer name.

    Dataroma holdings pages show ticker + company name but no CUSIP.
    We collect (ticker, issuer_name) from Dataroma, then match against
    (cusip, issuer_name) in holdings_13f using normalized name similarity.

    Returns count of new mappings inserted.
    """
    from sqlalchemy import text

    # Step 1: collect (ticker, issuer_name) from all Dataroma manager pages
    managers = (
        db.query(InstitutionManager)
        .filter_by(is_superinvestor=True)
        .filter(InstitutionManager.dataroma_code.isnot(None))
        .all()
    )
    ticker_map: dict[str, str] = {}  # normalized_name → ticker (best seen)
    ticker_raw: dict[str, str] = {}  # normalized_name → raw issuer_name

    with DataromaClient() as dc:
        for mgr in managers:
            try:
                html = dc.get_holdings(mgr.dataroma_code)
            except Exception as exc:
                logger.error(
                    "Dataroma holdings fetch failed for %s (%s): %s",
                    mgr.legal_name, mgr.dataroma_code, exc,
                )
                continue

            for h in parse_holdings(html):
                if not h.ticker or not h.issuer_name:
                    continue
                key = _normalize_name(h.issuer_name)
                if key and key not in ticker_map:
                    ticker_map[key] = h.ticker
                    ticker_raw[key] = h.issuer_name

    logger.info("Dataroma: collected %d distinct (ticker, name) pairs", len(ticker_map))

    # Step 2: get distinct (cusip, issuer_name) from holdings_13f
    rows = db.execute(text(
        "SELECT DISTINCT cusip, issuer_name FROM holdings_13f WHERE cusip IS NOT NULL"
    )).fetchall()

    # Step 3: match by name, insert into cusip_ticker_map
    inserted = 0
    unmatched: list[str] = []
    for row in rows:
        cusip = row.cusip
        norm = _normalize_name(row.issuer_name or "")
        if not norm:
            continue

        # Exact match first
        ticker = ticker_map.get(norm)
        raw_name = ticker_raw.get(norm)
        if ticker is None:
            # Fuzzy: find best scoring name above threshold
            best_score, best_ticker, best_raw = 0.0, None, None
            for candidate_norm, candidate_ticker in ticker_map.items():
                score = _name_score(norm, candidate_norm)
                if score > best_score:
                    best_score, best_ticker, best_raw = score, candidate_ticker, ticker_raw[candidate_norm]
            if best_score >= 0.85:
                ticker = best_ticker
                raw_name = best_raw
            elif best_score >= 0.7:
                ticker = best_ticker
                raw_name = best_raw
                logger.debug(
                    "Low-confidence match: %r -> %s (score=%.2f)", row.issuer_name, ticker, best_score
                )
            else:
                unmatched.append(row.issuer_name or cusip)
                continue

        try:
            confidence = "medium" if ticker else "low"
            upsert_cusip_mapping(
                db,
                cusip=cusip,
                ticker=ticker,
                issuer_name=raw_name or row.issuer_name,
                source="dataroma",
                mapping_reason="name-matched from Dataroma holdings pages",
                confidence=confidence,
            )
            inserted += 1
        except Exception as exc:
            logger.warning("cusip_ticker_map insert failed for %s/%s: %s", cusip, ticker, exc)

    if unmatched:
        logger.info(
            "enrich_from_dataroma: %d CUSIPs unmatched (not in any Dataroma portfolio): %s…",
            len(unmatched), ", ".join(unmatched[:5]),
        )
    db.flush()
    return inserted


# ---------------------------------------------------------------------------
# Step 1 – bootstrap stocks from cusip_ticker_map
# ---------------------------------------------------------------------------

def bootstrap_stocks_from_cusip_map(db: Session) -> int:
    """Upsert one Stock row per distinct ticker in cusip_ticker_map.

    Uses issuer_name as company_name; exchange defaults to 'US' since
    CUSIP-level data doesn't carry exchange info reliably.
    Returns count of newly created Stock rows.
    """
    from sqlalchemy import text

    # Best issuer_name per ticker: prefer the most common one
    rows = db.execute(text("""
        SELECT ticker, issuer_name, COUNT(*) AS cnt
        FROM cusip_ticker_map
        WHERE ticker IS NOT NULL AND is_active = true
        GROUP BY ticker, issuer_name
        ORDER BY ticker, cnt DESC
    """)).fetchall()

    best: dict[str, str] = {}  # ticker → best issuer_name
    for row in rows:
        if row.ticker not in best:
            best[row.ticker] = row.issuer_name or row.ticker

    created = 0
    for ticker, company_name in best.items():
        existing = db.query(Stock).filter_by(ticker=ticker).first()
        if existing is None:
            db.add(Stock(
                ticker=ticker,
                company_name=company_name,
                exchange="US",
                is_active=True,
            ))
            created += 1

    db.flush()
    logger.info("bootstrap_stocks_from_cusip_map: created %d new Stock rows", created)
    return created


def backfill_stock_ids(db: Session) -> int:
    """Set holdings_13f.stock_id via cusip → cusip_ticker_map.ticker → stocks.id.

    Idempotent: only updates rows where stock_id IS NULL.
    Returns count of holdings updated.
    """
    from sqlalchemy import text

    result = db.execute(text("""
        UPDATE holdings_13f h
        SET stock_id = s.id
        FROM cusip_ticker_map c
        JOIN stocks s ON s.ticker = c.ticker
        WHERE h.cusip = c.cusip
          AND c.is_active = true
          AND h.stock_id IS NULL
    """))
    updated = result.rowcount
    logger.info("backfill_stock_ids: updated %d holdings", updated)
    return updated


# ---------------------------------------------------------------------------
# Step 2 – EDGAR company_tickers.json for remaining unmatched CUSIPs
# ---------------------------------------------------------------------------

def enrich_stocks_from_edgar_tickers(db: Session) -> dict[str, int]:
    """Fetch SEC company_tickers.json, match unmatched holdings by issuer name,
    upsert stocks, update cusip_ticker_map, and backfill stock_id.

    Returns dict with keys: tickers_fetched, new_stocks, new_mappings, holdings_linked.
    """
    import json
    from sqlalchemy import text
    from app.edgar.client import EdgarClient

    # Fetch EDGAR company ticker universe
    with EdgarClient() as client:
        raw = client.get("https://www.sec.gov/files/company_tickers.json")
    data = json.loads(raw)

    # Build lookup: normalized_name → (ticker, title)
    edgar_lookup: dict[str, tuple[str, str]] = {}
    for entry in data.values():
        ticker = (entry.get("ticker") or "").strip().upper()
        title = (entry.get("title") or "").strip()
        if ticker and title:
            key = _normalize_name(title)
            if key and key not in edgar_lookup:
                edgar_lookup[key] = (ticker, title)

    logger.info("enrich_stocks_from_edgar_tickers: %d EDGAR tickers loaded", len(edgar_lookup))

    # Get unmatched CUSIPs (no stock_id, and not yet in cusip_ticker_map)
    unmatched = db.execute(text("""
        SELECT DISTINCT h.cusip, h.issuer_name
        FROM holdings_13f h
        LEFT JOIN cusip_ticker_map c ON c.cusip = h.cusip AND c.is_active = true
        WHERE h.stock_id IS NULL
          AND c.cusip IS NULL
          AND h.cusip IS NOT NULL
          AND h.issuer_name IS NOT NULL
    """)).fetchall()

    logger.info("enrich_stocks_from_edgar_tickers: %d unmatched CUSIPs to resolve", len(unmatched))

    new_mappings = 0
    for row in unmatched:
        norm = _normalize_name(row.issuer_name)
        if not norm:
            continue

        # Exact match first
        match = edgar_lookup.get(norm)
        if match is None:
            # Fuzzy: find best above threshold
            best_score, best_match = 0.0, None
            for candidate_norm, candidate_val in edgar_lookup.items():
                score = _name_score(norm, candidate_norm)
                if score > best_score:
                    best_score, best_match = score, candidate_val
            if best_score >= 0.85:
                match = best_match
                confidence = "medium"
            elif best_score >= 0.75:
                match = best_match
                confidence = "low"
            else:
                continue
        else:
            confidence = "high"  # exact normalized match

        ticker, title = match
        try:
            upsert_cusip_mapping(
                db,
                cusip=row.cusip,
                ticker=ticker,
                issuer_name=title,
                source="sec_co_tickers",
                mapping_reason="name-matched from SEC company_tickers.json",
                confidence=confidence,
            )
            new_mappings += 1
        except Exception as exc:
            logger.warning("Failed to map %s → %s: %s", row.cusip, ticker, exc)

    db.flush()

    # Ensure stock rows exist for all newly mapped tickers
    new_stocks = bootstrap_stocks_from_cusip_map(db)

    # Backfill stock_id for the newly linked holdings
    holdings_linked = backfill_stock_ids(db)

    return {
        "tickers_fetched": len(edgar_lookup),
        "new_mappings": new_mappings,
        "new_stocks": new_stocks,
        "holdings_linked": holdings_linked,
    }
