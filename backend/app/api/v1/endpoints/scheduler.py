"""Phase D: scheduler status and filing progress dashboard."""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings

router = APIRouter()


class ManagerFilingStatus(BaseModel):
    cik: str
    legal_name: str
    filed: bool
    accession_no: Optional[str] = None
    filed_at: Optional[date] = None
    period_of_report: Optional[date] = None
    form_type: Optional[str] = None


class FilingProgressResponse(BaseModel):
    quarter: str
    deadline: date
    days_until_deadline: int
    filed_count: int
    pending_count: int
    total_count: int
    managers: list[ManagerFilingStatus]


class SchedulerStatusResponse(BaseModel):
    enabled: bool
    latest_available_quarter: str
    next_run: Optional[datetime] = None


def _quarter_deadline(quarter: str) -> date:
    """Return the approximate 45-day filing deadline for a quarter."""
    import calendar
    from app.edgar.parsers.form_idx import quarter_to_year_qtr
    year, qtr = quarter_to_year_qtr(quarter)
    end_month = qtr * 3
    quarter_end = date(year, end_month, calendar.monthrange(year, end_month)[1])
    # 45 days after quarter end
    from datetime import timedelta
    return quarter_end + timedelta(days=45)


@router.get("/scheduler/status", response_model=SchedulerStatusResponse)
def get_scheduler_status():
    """Return scheduler on/off state and the latest available quarter."""
    from app.services.scheduler import latest_available_quarter
    today = date.today()
    return SchedulerStatusResponse(
        enabled=settings.EDGAR_SCHEDULER_ENABLED,
        latest_available_quarter=latest_available_quarter(today),
    )


@router.get("/scheduler/filing-progress", response_model=FilingProgressResponse)
def get_filing_progress(
    quarter: Optional[str] = Query(None, description="Quarter e.g. 2025-Q1; defaults to latest available"),
    db: Session = Depends(get_db),
):
    """Show which superinvestors have filed for a given quarter and which haven't.

    Useful for monitoring filing progress during the 45-day window after quarter-end.
    """
    from app.services.scheduler import latest_available_quarter
    from app.models.institutions import Filing13F, InstitutionManager
    from app.edgar.parsers.form_idx import quarter_to_year_qtr
    import calendar

    today = date.today()
    if not quarter:
        quarter = latest_available_quarter(today)

    year, qtr = quarter_to_year_qtr(quarter)
    q_start = date(year, (qtr - 1) * 3 + 1, 1)
    end_month = qtr * 3
    q_end = date(year, end_month, calendar.monthrange(year, end_month)[1])
    deadline = _quarter_deadline(quarter)
    days_until = (deadline - today).days

    # All confirmed superinvestors
    managers = (
        db.query(InstitutionManager)
        .filter_by(match_status="confirmed", is_superinvestor=True)
        .filter(InstitutionManager.cik.isnot(None))
        .order_by(InstitutionManager.legal_name)
        .all()
    )

    # Latest filing per manager for this quarter
    filed_map: dict[int, Filing13F] = {}
    filings = (
        db.query(Filing13F)
        .filter(Filing13F.period_of_report.between(q_start, q_end))
        .filter(Filing13F.is_latest_for_period == True)  # noqa: E712
        .all()
    )
    for f in filings:
        filed_map[f.manager_id] = f

    statuses = []
    for mgr in managers:
        filing = filed_map.get(mgr.id)
        statuses.append(ManagerFilingStatus(
            cik=mgr.cik,
            legal_name=mgr.legal_name,
            filed=filing is not None,
            accession_no=filing.accession_no if filing else None,
            filed_at=filing.filed_at if filing else None,
            period_of_report=filing.period_of_report if filing else None,
            form_type=filing.form_type if filing else None,
        ))

    filed_count = sum(1 for s in statuses if s.filed)
    return FilingProgressResponse(
        quarter=quarter,
        deadline=deadline,
        days_until_deadline=days_until,
        filed_count=filed_count,
        pending_count=len(statuses) - filed_count,
        total_count=len(statuses),
        managers=statuses,
    )
