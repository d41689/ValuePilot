from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import AdminUser, SessionDep
from app.services.thirteenf_admin_dashboard import (
    build_admin_readiness,
    build_admin_tasks,
    build_consumer_readiness,
    build_managers,
    build_quality_reports,
    build_quarters,
    build_status,
    cancel_job,
    confirm_manager_cik,
    get_job,
    get_quality_report_for_quarter,
    list_workers,
    list_jobs,
    reject_manager_cik,
    trigger_job,
)

admin_router = APIRouter()
consumer_router = APIRouter()


class ManagerReviewRequest(BaseModel):
    cik: str | None = None
    note: str | None = None


class JobTriggerRequest(BaseModel):
    job_type: str
    quarter: str | None = None
    quarters: int | None = Field(default=None, ge=1, le=40)
    start_quarter: str | None = None
    accession_no: str | None = None
    dry_run: bool = False
    trigger_source: str | None = None


@admin_router.get("/status", response_model=dict)
def read_status(session: SessionDep, current_user: AdminUser) -> Any:
    return build_status(session)


@admin_router.get("/readiness", response_model=dict)
def read_admin_readiness(session: SessionDep, current_user: AdminUser) -> Any:
    return build_admin_readiness(session)


@consumer_router.get("/readiness", response_model=dict)
def read_consumer_readiness(session: SessionDep) -> Any:
    return build_consumer_readiness(session)


@admin_router.get("/quarters", response_model=dict)
def read_quarters(
    session: SessionDep,
    current_user: AdminUser,
    limit: int = Query(8, ge=1, le=40),
) -> Any:
    return {"items": build_quarters(session, limit=limit)}


@admin_router.get("/quarters/{quarter}", response_model=dict)
def read_quarter(session: SessionDep, current_user: AdminUser, quarter: str) -> Any:
    quarters = build_quarters(session, limit=40)
    for item in quarters:
        if item["quarter"] == quarter:
            return item
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quarter not found")


@admin_router.get("/tasks", response_model=dict)
def read_tasks(session: SessionDep, current_user: AdminUser) -> Any:
    return {"items": build_admin_tasks(session)}


@admin_router.get("/quality", response_model=dict)
def read_quality_reports(
    session: SessionDep,
    current_user: AdminUser,
    limit: int = Query(20, ge=1, le=100),
) -> Any:
    return {"items": build_quality_reports(session, limit=limit)}


@admin_router.get("/quality/{quarter}", response_model=dict)
def read_quality_report(session: SessionDep, current_user: AdminUser, quarter: str) -> Any:
    try:
        return get_quality_report_for_quarter(session, quarter)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@admin_router.get("/managers", response_model=dict)
def read_managers(session: SessionDep, current_user: AdminUser) -> Any:
    return {"items": build_managers(session)}


@admin_router.post("/managers/{manager_id}/confirm-cik", response_model=dict)
def confirm_cik(
    session: SessionDep,
    current_user: AdminUser,
    manager_id: int,
    payload: ManagerReviewRequest,
) -> Any:
    try:
        return confirm_manager_cik(
            session,
            manager_id,
            cik=payload.cik,
            note=payload.note,
            reviewed_by_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.post("/managers/{manager_id}/reject-cik", response_model=dict)
def reject_cik(
    session: SessionDep,
    current_user: AdminUser,
    manager_id: int,
    payload: ManagerReviewRequest,
) -> Any:
    try:
        return reject_manager_cik(
            session,
            manager_id,
            note=payload.note,
            reviewed_by_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.get("/jobs", response_model=dict)
def read_jobs(
    session: SessionDep,
    current_user: AdminUser,
    limit: int = Query(100, ge=1, le=500),
) -> Any:
    return {"items": list_jobs(session, limit=limit)}


@admin_router.get("/jobs/{job_id}", response_model=dict)
def read_job(session: SessionDep, current_user: AdminUser, job_id: int) -> Any:
    try:
        return get_job(session, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@admin_router.get("/workers", response_model=dict)
def read_workers(session: SessionDep, current_user: AdminUser) -> Any:
    return {"items": list_workers(session)}


@admin_router.post("/jobs", response_model=dict)
def create_job(session: SessionDep, current_user: AdminUser, payload: JobTriggerRequest) -> Any:
    try:
        result = trigger_job(session, requested_by_user_id=current_user.id, payload=payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result.get("conflict"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"active_job_id": result["active_job_id"], "lock_key": result["lock_key"]},
        )
    return result


@admin_router.post("/jobs/{job_id}/cancel", response_model=dict)
def cancel_admin_job(session: SessionDep, current_user: AdminUser, job_id: int) -> Any:
    try:
        return cancel_job(session, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@admin_router.post("/jobs/retry-failed-filings", response_model=dict)
def retry_failed_filings(session: SessionDep, current_user: AdminUser, payload: JobTriggerRequest) -> Any:
    job_payload = payload.model_dump()
    job_payload["job_type"] = "ingest_holdings"
    try:
        result = trigger_job(session, requested_by_user_id=current_user.id, payload=job_payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result.get("conflict"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"active_job_id": result["active_job_id"], "lock_key": result["lock_key"]},
        )
    return result
