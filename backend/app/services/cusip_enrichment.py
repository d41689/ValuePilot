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
