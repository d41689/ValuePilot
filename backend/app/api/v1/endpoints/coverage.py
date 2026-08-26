from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.models.coverage import ResearchCoverageRequirement
from app.models.institutions import JobRun
from app.models.stocks import Stock
from app.models.users import User
from app.services.api_rate_limits import RateLimitExceeded, consume_user_operation
from app.services.market_data_service import MarketDataService
from app.services.research_coverage import (
    PRIORITY_POLICY_VERSION,
    evaluate_research_coverage,
    serialize_requirement,
)


router = APIRouter()
_ACTIVE_JOB_STATUSES = {"queued", "running", "cancel_requested"}


@router.get("/requirements", response_model=dict)
def list_requirements(
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    rows = (
        session.query(ResearchCoverageRequirement, Stock)
        .join(Stock, Stock.id == ResearchCoverageRequirement.stock_id)
        .filter(
            ResearchCoverageRequirement.user_id == current_user.id,
            ResearchCoverageRequirement.priority_policy_version
            == PRIORITY_POLICY_VERSION,
            ResearchCoverageRequirement.is_current.is_(True),
        )
        .order_by(
            ResearchCoverageRequirement.priority_rank,
            ResearchCoverageRequirement.stock_id,
            ResearchCoverageRequirement.kind,
        )
        .all()
    )
    return {
        "priority_policy_version": PRIORITY_POLICY_VERSION,
        "items": [serialize_requirement(row, stock) for row, stock in rows],
    }


@router.post("/evaluate", response_model=dict)
def evaluate_requirements(
    session: SessionDep,
    current_user: CurrentUser,
    as_of: date | None = Query(default=None),
    lens: Literal["consensus", "distinctive"] = Query(default="consensus"),
) -> dict[str, Any]:
    return evaluate_research_coverage(
        session,
        user_id=current_user.id,
        as_of=as_of or date.today(),
        lens=lens,
    )


@router.post("/refresh-prices", response_model=dict)
def refresh_required_prices(
    session: SessionDep,
    current_user: CurrentUser,
    as_of: date | None = Query(default=None),
    lens: Literal["consensus", "distinctive"] = Query(default="consensus"),
) -> dict[str, Any]:
    """Refresh the current user's unmet EOD requirements in one provider batch.

    ``as_of`` is an explicit completed market session for this action. The
    ordinary coverage evaluation endpoint keeps date-only requests conservative
    and does not assume that the same day's close already exists.
    """
    try:
        consume_user_operation(
            session,
            user_id=current_user.id,
            operation="coverage_price_refresh",
        )
    except RateLimitExceeded as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limit_exceeded",
                "operation": error.operation,
                "message": "Too many price coverage refreshes. Try again later.",
            },
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    target_as_of = as_of or date.today()
    lock_key = f"coverage_eod_refresh:{current_user.id}:{target_as_of.isoformat()}"
    active = (
        session.query(JobRun)
        .filter(
            JobRun.lock_key == lock_key,
            JobRun.status.in_(_ACTIVE_JOB_STATUSES),
        )
        .one_or_none()
    )
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "A price coverage refresh is already running.",
                "job_id": active.id,
            },
        )

    rows = (
        session.query(ResearchCoverageRequirement)
        .filter(
            ResearchCoverageRequirement.user_id == current_user.id,
            ResearchCoverageRequirement.priority_policy_version
            == PRIORITY_POLICY_VERSION,
            ResearchCoverageRequirement.is_current.is_(True),
            ResearchCoverageRequirement.kind == "eod_price",
            ResearchCoverageRequirement.next_action == "refresh_eod_price",
        )
        .order_by(
            ResearchCoverageRequirement.priority_rank,
            ResearchCoverageRequirement.stock_id,
        )
        .all()
    )
    stock_ids = list(dict.fromkeys(row.stock_id for row in rows))
    now = datetime.now(timezone.utc)
    job = JobRun(
        job_type="coverage_eod_refresh",
        status="running",
        requested_by_user_id=current_user.id,
        trigger_source="user",
        sync_date=target_as_of,
        dedupe_key=lock_key,
        lock_key=lock_key,
        input_json={
            "as_of": target_as_of.isoformat(),
            "lens": lens,
            "stock_ids": stock_ids,
        },
        started_at=now,
        heartbeat_at=now,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        active = (
            session.query(JobRun)
            .filter(
                JobRun.lock_key == lock_key,
                JobRun.status.in_(_ACTIVE_JOB_STATUSES),
            )
            .one_or_none()
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "A price coverage refresh is already running.",
                "job_id": active.id if active else None,
            },
        )

    try:
        # A date passed to this action denotes the session to fetch. End-of-day
        # UTC is safely after the US close and keeps the target deterministic.
        refresh_now = datetime.combine(target_as_of, time.max, tzinfo=timezone.utc)
        results = MarketDataService(session).refresh_stock_prices(
            stock_ids,
            reason="coverage_queue",
            now=refresh_now,
        )
        coverage = evaluate_research_coverage(
            session,
            user_id=current_user.id,
            as_of=target_as_of,
            lens=lens,
            include_as_of_session=True,
        )
        failed_count = sum(
            result["status"] in {"failed", "blocked"} for result in results
        )
        if failed_count == 0:
            job_status = "succeeded"
        elif failed_count == len(results):
            job_status = "failed"
        else:
            job_status = "partial_success"
        finished_at = datetime.now(timezone.utc)
        completed_job = session.get(JobRun, job.id)
        assert completed_job is not None
        completed_job.status = job_status
        completed_job.summary_json = {
            "target_count": len(stock_ids),
            "failed_count": failed_count,
            "results": results,
            "coverage": coverage,
        }
        completed_job.finished_at = finished_at
        completed_job.heartbeat_at = finished_at
        session.commit()
        return {
            "job_id": completed_job.id,
            "status": completed_job.status,
            "target_count": len(stock_ids),
            "results": results,
            "coverage": coverage,
        }
    except Exception as exc:
        session.rollback()
        failed_at = datetime.now(timezone.utc)
        failed_job = session.get(JobRun, job.id)
        if failed_job is not None:
            failed_job.status = "failed"
            failed_job.error_message = str(exc)[:2000]
            failed_job.finished_at = failed_at
            failed_job.heartbeat_at = failed_at
            session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Price coverage refresh failed.",
        ) from exc


@router.get("/admin/requirements", response_model=dict)
def list_admin_requirements(
    session: SessionDep,
    current_user: AdminUser,
) -> dict[str, Any]:
    rows = (
        session.query(ResearchCoverageRequirement, Stock, User)
        .join(Stock, Stock.id == ResearchCoverageRequirement.stock_id)
        .join(User, User.id == ResearchCoverageRequirement.user_id)
        .filter(
            ResearchCoverageRequirement.priority_policy_version
            == PRIORITY_POLICY_VERSION,
            ResearchCoverageRequirement.is_current.is_(True),
        )
        .order_by(
            ResearchCoverageRequirement.priority_rank,
            ResearchCoverageRequirement.user_id,
            ResearchCoverageRequirement.stock_id,
            ResearchCoverageRequirement.kind,
        )
        .all()
    )
    by_state: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    items = []
    for requirement, stock, user in rows:
        by_state[requirement.state] = by_state.get(requirement.state, 0) + 1
        by_kind[requirement.kind] = by_kind.get(requirement.kind, 0) + 1
        items.append(
            {
                **serialize_requirement(requirement, stock),
                "user_id": user.id,
                "user_email": user.email,
            }
        )
    return {
        "priority_policy_version": PRIORITY_POLICY_VERSION,
        "summary": {
            "total": len(items),
            "by_state": dict(sorted(by_state.items())),
            "by_kind": dict(sorted(by_kind.items())),
        },
        "items": items,
    }


@router.post("/admin/evaluate-all", response_model=dict)
def evaluate_all_users(
    session: SessionDep,
    current_user: AdminUser,
    as_of: date | None = Query(default=None),
    lens: Literal["consensus", "distinctive"] = Query(default="consensus"),
) -> dict[str, Any]:
    user_ids = [
        row[0]
        for row in session.query(User.id).filter(User.is_active.is_(True)).all()
    ]
    summaries = [
        evaluate_research_coverage(
            session,
            user_id=user_id,
            as_of=as_of or date.today(),
            lens=lens,
        )
        for user_id in user_ids
    ]
    return {
        "users_evaluated": len(user_ids),
        "requirements_evaluated": sum(
            summary["requirements_evaluated"] for summary in summaries
        ),
        "as_of": (as_of or date.today()).isoformat(),
        "lens": lens,
    }
