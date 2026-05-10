from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.schemas.thirteenf_cusip import CusipMappingCreate, CusipMappingUpdate, CusipMappingResponse

from app.api.deps import AdminUser, SessionDep
from app.services.thirteenf_admin_dashboard import (
    build_amendments,
    build_admin_readiness,
    build_admin_tasks,
    build_consumer_readiness,
    build_edgar_rate_limit_status,
    build_manager_backfill_preview,
    build_managers,
    build_quality_reports,
    build_quarters,
    build_status,
    cancel_job,
    bulk_import_managers,
    confirm_manager_cik,
    create_manager,
    deactivate_manager,
    get_amendment,
    get_job,
    get_quarter_detail_page,
    get_quality_report_for_quarter,
    list_manager_cik_review_events,
    list_workers,
    list_jobs,
    reject_manager_cik,
    release_stale_job_lock,
    resolve_amendment,
    retry_manager_cik_search,
    revoke_manager_cik,
    trigger_job,
    update_manager,
)
from app.services.thirteenf_daily_sync import (
    create_no_index_date,
    list_no_index_dates,
    update_no_index_date,
)

admin_router = APIRouter()
consumer_router = APIRouter()


class ManagerReviewRequest(BaseModel):
    cik: str | None = None
    note: str | None = None
    search_name: str | None = None


class AmendmentResolveRequest(BaseModel):
    action: str
    note: str | None = None


class ManagerCreateRequest(BaseModel):
    canonical_name: str
    legal_name: str | None = None
    display_name: str | None = None
    edgar_legal_name: str | None = None
    status: str | None = None
    manager_type: str | None = None
    is_featured: bool = False
    source: str | None = None
    source_url: str | None = None
    confidence_score: int | None = Field(default=None, ge=0, le=100)
    value_unit_override: str | None = None
    review_note: str | None = None


class ManagerPatchRequest(BaseModel):
    canonical_name: str | None = None
    display_name: str | None = None
    edgar_legal_name: str | None = None
    status: str | None = None
    manager_type: str | None = None
    is_featured: bool | None = None
    source: str | None = None
    source_url: str | None = None
    confidence_score: int | None = Field(default=None, ge=0, le=100)
    value_unit_override: str | None = None
    review_note: str | None = None


class ManagerBulkImportRequest(BaseModel):
    csv_text: str


class JobTriggerRequest(BaseModel):
    job_type: str
    quarter: str | None = None
    quarters: int | None = Field(default=None, ge=1, le=40)
    start_quarter: str | None = None
    accession_no: str | None = None
    dry_run: bool = False
    trigger_source: str | None = None


class NoIndexDateCreateRequest(BaseModel):
    date: date
    reason: str
    holiday_name: str | None = None
    note: str | None = None


class NoIndexDatePatchRequest(BaseModel):
    note: str | None = None
    active: bool | None = None


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


@admin_router.get("/quarters/{quarter}/detail", response_model=dict)
def read_quarter_detail(
    session: SessionDep,
    current_user: AdminUser,
    quarter: str,
    filing_limit: int = Query(25, ge=1, le=200),
    filing_offset: int = Query(0, ge=0),
    filing_status: str | None = Query(default=None, pattern="^(pending|failed|parsed_no_holdings|parsed)$"),
) -> Any:
    try:
        return get_quarter_detail_page(
            session,
            quarter,
            filing_limit=filing_limit,
            filing_offset=filing_offset,
            filing_status=filing_status,
        )
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@admin_router.get("/edgar-rate-limit", response_model=dict)
def read_edgar_rate_limit_status(session: SessionDep, current_user: AdminUser) -> Any:
    return build_edgar_rate_limit_status()


@admin_router.get("/no-index-dates", response_model=dict)
def read_no_index_dates(
    session: SessionDep,
    current_user: AdminUser,
    year: int | None = Query(default=None, ge=1994, le=2100),
) -> Any:
    return {"items": list_no_index_dates(session, year=year)}


@admin_router.post("/no-index-dates", response_model=dict)
def create_13f_no_index_date(
    session: SessionDep,
    current_user: AdminUser,
    payload: NoIndexDateCreateRequest,
) -> Any:
    try:
        return create_no_index_date(
            session,
            expected_date=payload.date,
            reason=payload.reason,
            holiday_name=payload.holiday_name,
            note=payload.note,
            created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.patch("/no-index-dates/{expected_date}", response_model=dict)
def patch_13f_no_index_date(
    session: SessionDep,
    current_user: AdminUser,
    expected_date: date,
    payload: NoIndexDatePatchRequest,
) -> Any:
    try:
        return update_no_index_date(
            session,
            expected_date,
            note=payload.note,
            active=payload.active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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


@admin_router.get("/amendments", response_model=dict)
def read_amendments(
    session: SessionDep,
    current_user: AdminUser,
    limit: int = Query(100, ge=1, le=500),
) -> Any:
    return {"items": build_amendments(session, limit=limit)}


@admin_router.get("/amendments/{accession_no}", response_model=dict)
def read_amendment(session: SessionDep, current_user: AdminUser, accession_no: str) -> Any:
    try:
        return get_amendment(session, accession_no)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@admin_router.post("/amendments/{accession_no}/resolve", response_model=dict)
def resolve_13f_amendment(
    session: SessionDep,
    current_user: AdminUser,
    accession_no: str,
    payload: AmendmentResolveRequest,
) -> Any:
    try:
        return resolve_amendment(
            session,
            accession_no,
            action=payload.action,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.get("/managers", response_model=dict)
def read_managers(session: SessionDep, current_user: AdminUser) -> Any:
    return {"items": build_managers(session)}


@admin_router.post("/managers", response_model=dict)
def create_13f_manager(
    session: SessionDep,
    current_user: AdminUser,
    payload: ManagerCreateRequest,
) -> Any:
    try:
        return create_manager(session, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.post("/managers/bulk-import", response_model=dict)
def bulk_import_13f_managers(
    session: SessionDep,
    current_user: AdminUser,
    payload: ManagerBulkImportRequest,
) -> Any:
    try:
        return bulk_import_managers(session, payload.csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.patch("/managers/{manager_id}", response_model=dict)
def patch_13f_manager(
    session: SessionDep,
    current_user: AdminUser,
    manager_id: int,
    payload: ManagerPatchRequest,
) -> Any:
    try:
        return update_manager(session, manager_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.post("/managers/{manager_id}/deactivate", response_model=dict)
def deactivate_13f_manager(
    session: SessionDep,
    current_user: AdminUser,
    manager_id: int,
    payload: ManagerReviewRequest,
) -> Any:
    try:
        return deactivate_manager(
            session,
            manager_id,
            note=payload.note,
            reviewed_by_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.get("/managers/{manager_id}/backfill-preview", response_model=dict)
def read_manager_backfill_preview(
    session: SessionDep,
    current_user: AdminUser,
    manager_id: int,
) -> Any:
    try:
        return build_manager_backfill_preview(session, manager_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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


@admin_router.post("/managers/{manager_id}/revoke-cik", response_model=dict)
def revoke_cik(
    session: SessionDep,
    current_user: AdminUser,
    manager_id: int,
    payload: ManagerReviewRequest,
) -> Any:
    try:
        return revoke_manager_cik(
            session,
            manager_id,
            note=payload.note,
            reviewed_by_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.post("/managers/{manager_id}/retry-cik-search", response_model=dict)
def retry_cik_search(
    session: SessionDep,
    current_user: AdminUser,
    manager_id: int,
    payload: ManagerReviewRequest,
) -> Any:
    try:
        return retry_manager_cik_search(
            session,
            manager_id,
            search_name=payload.search_name or "",
            note=payload.note,
            reviewed_by_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.get("/managers/{manager_id}/cik-review-events", response_model=dict)
def read_manager_cik_review_events(
    session: SessionDep,
    current_user: AdminUser,
    manager_id: int,
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    try:
        return {"items": list_manager_cik_review_events(session, manager_id, limit=limit)}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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


@admin_router.post("/jobs/{job_id}/release-stale-lock", response_model=dict)
def release_admin_stale_lock(session: SessionDep, current_user: AdminUser, job_id: int) -> Any:
    try:
        return release_stale_job_lock(session, job_id)
    except ValueError as exc:
        status_code = status.HTTP_404_NOT_FOUND if str(exc) == "Job not found" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


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


@admin_router.post("/filings/{accession_no}/reparse", response_model=dict)
def reparse_filing(
    session: SessionDep,
    current_user: AdminUser,
    accession_no: str,
) -> Any:
    """Reparse an existing filing by accession number (PRD §6.3-§6.5).

    Creates a new parse_run for the accession:
    - On success, the new parse_run becomes is_current=True; old holdings are retained.
    - On failure, the old current parse_run is restored; the failed run is persisted for audit.
    """
    from app.services.thirteenf_holdings_ingest import reparse_accession

    try:
        result = reparse_accession(session, accession_no)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reparse failed: {exc}",
        ) from exc
    return result


@admin_router.get("/cusips", response_model=dict)
def read_cusips(
    session: SessionDep,
    current_user: AdminUser,
    limit: int = Query(100, ge=1, le=1000),
    needs_review: bool = Query(False),
    unresolved: bool = Query(False),
) -> Any:
    from app.services.thirteenf_admin_dashboard import build_cusip_mappings
    return {"items": build_cusip_mappings(session, limit, needs_review, unresolved)}


@admin_router.post("/cusips", response_model=CusipMappingResponse)
def create_cusip_mapping_endpoint(
    session: SessionDep, current_user: AdminUser, payload: CusipMappingCreate
) -> Any:
    from app.services.thirteenf_admin_dashboard import create_manual_cusip_mapping
    try:
        return create_manual_cusip_mapping(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.patch("/cusips/{cusip}", response_model=CusipMappingResponse)
def update_cusip_mapping_endpoint(
    session: SessionDep, current_user: AdminUser, cusip: str, payload: CusipMappingUpdate
) -> Any:
    from app.services.thirteenf_admin_dashboard import update_manual_cusip_mapping
    try:
        return update_manual_cusip_mapping(session, cusip, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

