from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.schemas.thirteenf_cusip import CusipMappingCreate, CusipMappingUpdate, CusipMappingResponse
from app.schemas.thirteenf_corporate_action import (
    CorporateActionMappingConfirmRequest,
    CorporateActionMappingPreviewRequest,
)

from app.api.deps import AdminUser, SessionDep
from app.services.thirteenf_admin_dashboard import (
    build_amendments,
    build_admin_readiness,
    build_admin_tasks,
    build_consumer_readiness,
    build_edgar_rate_limit_status,
    build_holdings_coverage_summary,
    build_manager_backfill_preview,
    build_managers,
    build_pending_amendments_read_model,
    build_quality_reports,
    build_quarters,
    build_status,
    cancel_job,
    bulk_import_managers,
    confirm_manager_cik,
    create_manager,
    deactivate_manager,
    get_admin_filing,
    get_amendment,
    get_job,
    get_quarter_detail_page,
    get_quality_report_for_quarter,
    list_admin_filings,
    list_parse_runs_for_accession,
    list_manager_cik_review_events,
    list_unresolved_cusip_mappings,
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
from app.services.thirteenf_user_api import (
    build_user_manager_holding_changes,
    build_user_manager_holdings,
    build_user_manager_quarters,
    build_user_managers,
    build_user_stock_holders,
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


@consumer_router.get("/managers", response_model=dict)
def read_user_managers(session: SessionDep) -> Any:
    return build_user_managers(session)


@consumer_router.get("/managers/{manager_id}/quarters", response_model=dict)
def read_user_manager_quarters(manager_id: int, session: SessionDep) -> Any:
    try:
        return build_user_manager_quarters(session, manager_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@consumer_router.get("/managers/{manager_id}/holdings", response_model=dict)
def read_user_manager_holdings(
    manager_id: int,
    session: SessionDep,
    quarter: str | None = Query(None),
) -> Any:
    try:
        return build_user_manager_holdings(session, manager_id, quarter=quarter)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@consumer_router.get("/managers/{manager_id}/holdings/changes", response_model=dict)
def read_user_manager_holding_changes(
    manager_id: int,
    session: SessionDep,
    quarter: str | None = Query(None, pattern=r"^\d{4}-Q[1-4]$"),
) -> Any:
    try:
        return build_user_manager_holding_changes(session, manager_id, quarter=quarter)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@consumer_router.get("/stocks/{stock_id}/holders", response_model=dict)
def read_user_stock_holders(
    stock_id: int,
    session: SessionDep,
    quarter: str | None = Query(None, pattern=r"^\d{4}-Q[1-4]$"),
    limit: int = Query(10, ge=1, le=50),
) -> Any:
    try:
        return build_user_stock_holders(session, stock_id, quarter=quarter, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@admin_router.get("/amendments/pending", response_model=dict)
def read_pending_amendments(
    session: SessionDep,
    current_user: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Any:
    return build_pending_amendments_read_model(session, page=page, page_size=page_size)


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


@admin_router.get("/filings", response_model=dict)
def read_filings(
    session: SessionDep,
    current_user: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    report_quarter: str | None = Query(None),
    parse_status: str | None = Query(None),
    form_type: str | None = Query(None),
    manager_id: int | None = Query(None),
) -> Any:
    return list_admin_filings(
        session,
        page=page,
        page_size=page_size,
        report_quarter=report_quarter,
        parse_status=parse_status,
        form_type=form_type,
        manager_id=manager_id,
    )


@admin_router.get("/filings/{accession_no}", response_model=dict)
def read_filing(session: SessionDep, current_user: AdminUser, accession_no: str) -> Any:
    try:
        return get_admin_filing(session, accession_no)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@admin_router.get("/filings/{accession_no}/parse-runs", response_model=dict)
def read_filing_parse_runs(
    session: SessionDep,
    current_user: AdminUser,
    accession_no: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Any:
    try:
        return list_parse_runs_for_accession(session, accession_no, page=page, page_size=page_size)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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
    start_quarter: str | None = Query(None),
    end_quarter: str | None = Query(None),
) -> Any:
    try:
        return build_manager_backfill_preview(session, manager_id, start_quarter, end_quarter)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.post("/managers/{manager_id}/backfill", response_model=dict)
def create_manager_backfill(
    session: SessionDep,
    current_user: AdminUser,
    manager_id: int,
    start_quarter: str | None = Query(None),
    end_quarter: str | None = Query(None),
) -> Any:
    try:
        from app.services.thirteenf_admin_dashboard import _validate_manager_backfill_request, trigger_job
        _validate_manager_backfill_request(
            session,
            manager_id,
            start_quarter=start_quarter,
            end_quarter=end_quarter,
        )
        job_payload = {
            "job_type": "sync_manager_backfill",
            "manager_id": manager_id,
        }
        if start_quarter:
            job_payload["start_quarter"] = start_quarter
        if end_quarter:
            job_payload["end_quarter"] = end_quarter
            
        result = trigger_job(session, requested_by_user_id=current_user.id, payload=job_payload)
        
        if result.get("conflict"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"active_job_id": result["active_job_id"], "lock_key": result["lock_key"]},
            )
        return result
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
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=500),
    status: str | None = Query(None),
    job_type: str | None = Query(None),
    started_from: datetime | None = Query(None),
    started_to: datetime | None = Query(None),
    sync_date: date | None = Query(None),
    quarter: str | None = Query(None),
) -> Any:
    return list_jobs(
        session,
        page=page,
        page_size=page_size,
        limit=limit,
        status=status,
        job_type=job_type,
        started_from=started_from,
        started_to=started_to,
        sync_date=sync_date,
        quarter=quarter,
    )


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


@admin_router.get("/holdings/coverage", response_model=dict)
def read_holdings_coverage(
    session: SessionDep,
    current_user: AdminUser,
    report_quarter: str | None = Query(None),
) -> Any:
    return build_holdings_coverage_summary(session, report_quarter=report_quarter)


@admin_router.get("/cusip-mappings/unresolved", response_model=dict)
def read_unresolved_cusip_mappings(
    session: SessionDep,
    current_user: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Any:
    return list_unresolved_cusip_mappings(session, page=page, page_size=page_size)


@admin_router.get("/cusip-mappings", response_model=dict)
def read_cusip_mappings(
    session: SessionDep,
    current_user: AdminUser,
    limit: int = Query(100, ge=1, le=1000),
    needs_review: bool = Query(False),
    unresolved: bool = Query(False),
) -> Any:
    from app.services.thirteenf_admin_dashboard import build_cusip_mappings
    return {"items": build_cusip_mappings(session, limit, needs_review, unresolved)}


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


@admin_router.post("/cusips/corporate-actions/preview", response_model=dict)
def preview_corporate_action_mapping_endpoint(
    session: SessionDep,
    current_user: AdminUser,
    payload: CorporateActionMappingPreviewRequest,
) -> Any:
    from app.services.thirteenf_corporate_action_mapping import (
        CorporateActionMappingError,
        preview_corporate_action_confirmation,
    )

    try:
        return preview_corporate_action_confirmation(
            session,
            cusip=payload.cusip,
            effective_from_quarter=payload.effective_from_quarter,
            effective_to_quarter=payload.effective_to_quarter,
        )
    except CorporateActionMappingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.post("/cusips/corporate-actions/confirm", response_model=dict)
def confirm_corporate_action_mapping_endpoint(
    session: SessionDep,
    current_user: AdminUser,
    payload: CorporateActionMappingConfirmRequest,
) -> Any:
    from app.services.thirteenf_corporate_action_mapping import (
        CorporateActionMappingError,
        confirm_corporate_action_mapping,
    )

    try:
        return confirm_corporate_action_mapping(
            session,
            cusip=payload.cusip,
            new_ticker=payload.new_ticker,
            new_issuer_name=payload.new_issuer_name,
            effective_from_quarter=payload.effective_from_quarter,
            effective_to_quarter=payload.effective_to_quarter,
            evidence_url=payload.evidence_url,
            reason=payload.reason,
            reviewer_id=current_user.id,
            prior_mapping_id=payload.prior_mapping_id,
        )
    except CorporateActionMappingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# MVP3-08: Historical Backfill endpoints
# ---------------------------------------------------------------------------


class _BackfillPreviewRequest(BaseModel):
    start_quarter: str | None = Field(None)
    end_quarter: str | None = Field(None)
    manager_ids: list[int] | None = Field(None)


class _BackfillEnqueueRequest(BaseModel):
    start_quarter: str | None = Field(None)
    end_quarter: str | None = Field(None)
    manager_ids: list[int] | None = Field(None)
    dry_run: bool = Field(False)


@admin_router.post("/backfill/preview", response_model=dict)
def backfill_preview_endpoint(
    session: SessionDep,
    current_user: AdminUser,
    payload: _BackfillPreviewRequest,
) -> Any:
    from app.services.thirteenf_historical_backfill import preview_historical_backfill
    return preview_historical_backfill(
        session,
        start_quarter=payload.start_quarter,
        end_quarter=payload.end_quarter,
        manager_ids=payload.manager_ids,
    )


@admin_router.post("/backfill/enqueue", response_model=dict)
def backfill_enqueue_endpoint(
    session: SessionDep,
    current_user: AdminUser,
    payload: _BackfillEnqueueRequest,
) -> Any:
    from app.services.thirteenf_historical_backfill import (
        HistoricalBackfillError,
        enqueue_historical_backfill,
    )
    try:
        job = enqueue_historical_backfill(
            session,
            start_quarter=payload.start_quarter,
            end_quarter=payload.end_quarter,
            manager_ids=payload.manager_ids,
            dry_run=payload.dry_run,
            requested_by_user_id=current_user.id,
            trigger_source="admin",
        )
        return {
            "job_id": job.id,
            "status": job.status,
            "job_type": job.job_type,
            "lock_key": job.lock_key,
            "dry_run": bool((job.input_json or {}).get("dry_run", False)),
        }
    except HistoricalBackfillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.get("/backfill/needs-validation", response_model=dict)
def backfill_needs_validation_endpoint(
    session: SessionDep,
    current_user: AdminUser,
) -> Any:
    from sqlalchemy import func
    from app.models.institutions import QualityFinding13F
    from app.services.thirteenf_historical_backfill import HISTORICAL_BACKFILL_RULE_CODE

    rows = (
        session.query(
            QualityFinding13F.quarter,
            QualityFinding13F.validation_run_id,
            func.count(QualityFinding13F.id).label("open_count"),
        )
        .filter(
            QualityFinding13F.rule_code == HISTORICAL_BACKFILL_RULE_CODE,
            QualityFinding13F.status == "open",
        )
        .group_by(QualityFinding13F.quarter, QualityFinding13F.validation_run_id)
        .order_by(QualityFinding13F.quarter.asc())
        .all()
    )

    by_quarter: dict[str, dict] = {}
    for quarter, report_id, open_count in rows:
        key = quarter or "unknown"
        if key not in by_quarter:
            by_quarter[key] = {"quarter": key, "open_count": 0, "quality_report_ids": []}
        by_quarter[key]["open_count"] += open_count
        if report_id not in by_quarter[key]["quality_report_ids"]:
            by_quarter[key]["quality_report_ids"].append(report_id)

    return {"quarters": sorted(by_quarter.values(), key=lambda x: x["quarter"])}


@admin_router.get("/oracles-lens/unknown-manager-priority", response_model=dict)
def oracles_lens_unknown_manager_priority_endpoint(
    session: SessionDep,
    current_user: AdminUser,
) -> Any:
    """MVP4-07b: ranked list of ``manager_type=unknown`` managers
    whose admin classification would most stabilize Oracle's Lens
    score_confidence on the latest persisted quarter. See
    ``app/services/oracles_lens/unknown_manager_priority.py``.
    """
    from app.services.oracles_lens.unknown_manager_priority import (
        build_unknown_manager_priority,
    )
    return build_unknown_manager_priority(session)


# ---------------------------------------------------------------------------
# MVP3-08: Batch Reparse by Quarter endpoints
# ---------------------------------------------------------------------------


class _ReparseByQuarterRequest(BaseModel):
    quarter: str | None = Field(None)


@admin_router.post("/jobs/reparse-by-quarter/preview", response_model=dict)
def reparse_by_quarter_preview_endpoint(
    session: SessionDep,
    current_user: AdminUser,
    payload: _ReparseByQuarterRequest,
) -> Any:
    from app.services.thirteenf_batch_reparse import (
        BatchReparseScopeError,
        preview_batch_reparse,
    )
    if not payload.quarter:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quarter is required.")
    try:
        return preview_batch_reparse(session, quarter=payload.quarter)
    except BatchReparseScopeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.post("/jobs/reparse-by-quarter/enqueue", response_model=dict)
def reparse_by_quarter_enqueue_endpoint(
    session: SessionDep,
    current_user: AdminUser,
    payload: _ReparseByQuarterRequest,
) -> Any:
    from app.services.thirteenf_batch_reparse import (
        BatchReparseScopeError,
        enqueue_batch_reparse,
    )
    if not payload.quarter:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quarter is required.")
    try:
        job = enqueue_batch_reparse(
            session,
            quarter=payload.quarter,
            requested_by_user_id=current_user.id,
            trigger_source="admin",
        )
        return {
            "job_id": job.id,
            "status": job.status,
            "job_type": job.job_type,
            "lock_key": job.lock_key,
            "quarter": payload.quarter,
        }
    except BatchReparseScopeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
