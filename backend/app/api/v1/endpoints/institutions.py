"""Phase C: Public API endpoints for institutional holdings.

Only confirmed managers (match_status='confirmed', cik IS NOT NULL) are exposed.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.institutions import (
    CusipTickerMap,
    Filing13F,
    Holding13F,
    InstitutionManager,
)
from app.schemas.institutions import (
    Filing13FResponse,
    Holding13FResponse,
    InstitutionResponse,
)

router = APIRouter()


def _confirmed_manager(cik: str, db: Session) -> InstitutionManager:
    mgr = (
        db.query(InstitutionManager)
        .filter_by(cik=cik, match_status="confirmed")
        .one_or_none()
    )
    if mgr is None:
        raise HTTPException(status_code=404, detail="Institution not found")
    return mgr


@router.get("/institutions", response_model=list[InstitutionResponse])
def list_institutions(
    superinvestor: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    """List confirmed institutions. Filter by ?superinvestor=true."""
    q = (
        db.query(InstitutionManager)
        .filter_by(match_status="confirmed")
        .filter(InstitutionManager.cik.isnot(None))
    )
    if superinvestor is not None:
        q = q.filter_by(is_superinvestor=superinvestor)
    return q.order_by(InstitutionManager.legal_name).all()


@router.get("/institutions/{cik}/filings", response_model=list[Filing13FResponse])
def list_filings(
    cik: str,
    period: Optional[str] = Query(None, description="Quarter filter e.g. 2024-Q4"),
    db: Session = Depends(get_db),
):
    """Return all filing versions for a confirmed institution, optionally filtered by period."""
    mgr = _confirmed_manager(cik, db)
    q = db.query(Filing13F).filter_by(manager_id=mgr.id)

    if period:
        from datetime import date
        import calendar
        try:
            parts = period.upper().split("-Q")
            year, qtr = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="period must be YYYY-Qn")
        q_start = date(year, (qtr - 1) * 3 + 1, 1)
        end_month = qtr * 3
        q_end = date(year, end_month, calendar.monthrange(year, end_month)[1])
        q = q.filter(Filing13F.period_of_report.between(q_start, q_end))

    return q.order_by(Filing13F.period_of_report.desc(), Filing13F.version_rank.desc()).all()


@router.get("/institutions/{cik}/holdings", response_model=list[Holding13FResponse])
def get_holdings(
    cik: str,
    period: Optional[str] = Query(None, description="Quarter filter e.g. 2024-Q4"),
    all_versions: bool = Query(False, description="Include all amendment versions"),
    db: Session = Depends(get_db),
):
    """Return holdings for a confirmed institution.

    Defaults to canonical snapshot (is_latest_for_period = true).
    """
    mgr = _confirmed_manager(cik, db)

    filing_q = db.query(Filing13F).filter_by(manager_id=mgr.id)
    if not all_versions:
        filing_q = filing_q.filter_by(is_latest_for_period=True)

    if period:
        from datetime import date
        import calendar
        try:
            parts = period.upper().split("-Q")
            year, qtr = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="period must be YYYY-Qn")
        q_start = date(year, (qtr - 1) * 3 + 1, 1)
        end_month = qtr * 3
        q_end = date(year, end_month, calendar.monthrange(year, end_month)[1])
        filing_q = filing_q.filter(Filing13F.period_of_report.between(q_start, q_end))

    filing_ids = [f.id for f in filing_q.all()]
    if not filing_ids:
        return []

    holdings = (
        db.query(Holding13F)
        .filter(Holding13F.filing_id.in_(filing_ids))
        .order_by(Holding13F.value_thousands.desc())
        .all()
    )

    # Enrich with ticker from cusip_ticker_map
    cusips = {h.cusip for h in holdings}
    ticker_map: dict[str, str] = {}
    if cusips:
        rows = (
            db.query(CusipTickerMap)
            .filter(CusipTickerMap.cusip.in_(cusips))
            .filter_by(is_active=True)
            .all()
        )
        for row in rows:
            if row.ticker:
                ticker_map[row.cusip] = row.ticker

    results = []
    for h in holdings:
        data = Holding13FResponse.model_validate(h)
        data.ticker = ticker_map.get(h.cusip)
        results.append(data)
    return results


@router.get("/filings/{accession_no}/holdings", response_model=list[Holding13FResponse])
def get_filing_holdings(
    accession_no: str,
    db: Session = Depends(get_db),
):
    """Return raw holdings for a specific filing accession (any version)."""
    filing = db.query(Filing13F).filter_by(accession_no=accession_no).one_or_none()
    if filing is None:
        raise HTTPException(status_code=404, detail="Filing not found")

    # Validate manager is confirmed
    mgr = db.query(InstitutionManager).get(filing.manager_id)
    if not mgr or mgr.match_status != "confirmed":
        raise HTTPException(status_code=404, detail="Filing not found")

    holdings = (
        db.query(Holding13F)
        .filter_by(filing_id=filing.id)
        .order_by(Holding13F.value_thousands.desc())
        .all()
    )
    return [Holding13FResponse.model_validate(h) for h in holdings]


@router.get("/stocks/{ticker}/institutions", response_model=list[InstitutionResponse])
def get_stock_institutions(
    ticker: str,
    db: Session = Depends(get_db),
):
    """Return confirmed institutions that hold the given ticker (latest snapshot)."""
    # Resolve CUSIP from ticker
    mapping = (
        db.query(CusipTickerMap)
        .filter_by(ticker=ticker.upper(), is_active=True)
        .first()
    )
    if mapping is None:
        return []

    cusip = mapping.cusip
    holdings = (
        db.query(Holding13F)
        .join(Filing13F, Holding13F.filing_id == Filing13F.id)
        .filter(Holding13F.cusip == cusip)
        .filter(Filing13F.is_latest_for_period == True)  # noqa: E712
        .all()
    )

    manager_ids = list({h.filing.manager_id for h in holdings if h.filing})
    if not manager_ids:
        return []

    managers = (
        db.query(InstitutionManager)
        .filter(InstitutionManager.id.in_(manager_ids))
        .filter_by(match_status="confirmed")
        .filter(InstitutionManager.cik.isnot(None))
        .all()
    )
    return managers
