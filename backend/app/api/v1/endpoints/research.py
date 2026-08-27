from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.models.research import (
    ResearchCase,
    ResearchCaseEvent,
    ResearchCaseOrigin,
    ResearchCaseRevision,
    ResearchInboxAction,
)
from app.models.stocks import Stock
from app.schemas.research import (
    ResearchCaseCreate,
    ResearchOriginInput,
    ResearchRevisionCreate,
    ResearchRevisionRedact,
    ResearchInboxSnooze,
)
from app.services.research_cases import (
    ResearchCaseError,
    add_case_origin,
    create_or_open_case,
    redact_revision,
    save_revision,
    research_decision_metrics,
    serialize_case,
    serialize_origin,
    serialize_revision,
)
from app.services.research_inbox import (
    ResearchInboxError,
    complete_action,
    dismiss_action,
    regenerate_inbox,
    serialize_action,
    snooze_action,
)
from app.services.research_workspace import build_research_workspace


router = APIRouter()


def _current_projection_date(requested: date | None) -> date:
    today = date.today()
    if requested is not None and requested != today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "historical_as_of_not_supported",
                "message": (
                    "Inbox regeneration updates the current projection; "
                    "historical reconstruction is unavailable."
                ),
            },
        )
    return today


@router.get("/metrics", response_model=dict)
def get_research_metrics(
    session: SessionDep,
    current_user: CurrentUser,
    week_start: date | None = Query(default=None),
) -> dict[str, Any]:
    start = week_start or (date.today() - timedelta(days=date.today().weekday()))
    if start.weekday() != 0:
        raise HTTPException(status_code=422, detail="week_start must be a Monday")
    return research_decision_metrics(
        session,
        user_id=current_user.id,
        week_start=start,
    )


def _raise(session: SessionDep, error: ResearchCaseError) -> None:
    session.rollback()
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    ) from error


def _owned_case(session: SessionDep, *, user_id: int, case_id: int) -> ResearchCase:
    case = (
        session.query(ResearchCase)
        .filter(ResearchCase.id == case_id, ResearchCase.user_id == user_id)
        .one_or_none()
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Research case not found.")
    return case


@router.post("/cases", response_model=dict)
def create_case(
    payload: ResearchCaseCreate,
    response: Response,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        case, created, origin_created = create_or_open_case(
            session,
            user_id=current_user.id,
            stock_id=payload.stock_id,
            origin=payload.origin,
        )
    except ResearchCaseError as error:
        _raise(session, error)
    stock = session.get(Stock, case.stock_id)
    assert stock is not None
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return {
        "created": created,
        "origin_created": origin_created,
        "case": serialize_case(case, stock),
    }


@router.get("/cases", response_model=dict)
def list_cases(
    session: SessionDep,
    current_user: CurrentUser,
    state_filter: Literal[
        "queued", "researching", "monitoring", "closed", "voided"
    ]
    | None = Query(default=None, alias="state"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    query = (
        session.query(ResearchCase, Stock)
        .join(Stock, Stock.id == ResearchCase.stock_id)
        .filter(ResearchCase.user_id == current_user.id)
    )
    if state_filter:
        query = query.filter(ResearchCase.state == state_filter)
    total = query.count()
    rows = (
        query.order_by(
            ResearchCase.updated_at.desc(),
            ResearchCase.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [serialize_case(case, stock) for case, stock in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/cases/{case_id}", response_model=dict)
def get_case(
    case_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    case = _owned_case(session, user_id=current_user.id, case_id=case_id)
    stock = session.get(Stock, case.stock_id)
    assert stock is not None
    origins = (
        session.query(ResearchCaseOrigin)
        .filter_by(case_id=case.id)
        .order_by(ResearchCaseOrigin.created_at, ResearchCaseOrigin.id)
        .all()
    )
    head = (
        session.query(ResearchCaseRevision)
        .filter_by(case_id=case.id, revision_number=case.head_revision_number)
        .one_or_none()
        if case.head_revision_number
        else None
    )
    return {
        "case": serialize_case(case, stock),
        "origins": [serialize_origin(origin) for origin in origins],
        "head_revision": serialize_revision(head) if head else None,
    }


@router.get("/cases/{case_id}/workspace", response_model=dict)
def get_case_workspace(
    case_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    as_of: date | None = Query(default=None),
) -> dict[str, Any]:
    try:
        return build_research_workspace(
            session,
            user_id=current_user.id,
            case_id=case_id,
            as_of=as_of or date.today(),
        )
    except ResearchCaseError as error:
        _raise(session, error)


@router.post("/cases/{case_id}/origins", response_model=dict)
def add_origin(
    case_id: int,
    payload: ResearchOriginInput,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        origin, created = add_case_origin(
            session,
            user_id=current_user.id,
            case_id=case_id,
            origin=payload,
        )
    except ResearchCaseError as error:
        _raise(session, error)
    return {"created": created, "origin": serialize_origin(origin)}


@router.post("/cases/{case_id}/revisions", response_model=dict)
def create_revision(
    case_id: int,
    payload: ResearchRevisionCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        case, revision = save_revision(
            session,
            user_id=current_user.id,
            case_id=case_id,
            payload=payload,
        )
    except ResearchCaseError as error:
        _raise(session, error)
    stock = session.get(Stock, case.stock_id)
    assert stock is not None
    return {
        "case": serialize_case(case, stock),
        "revision": serialize_revision(revision),
    }


@router.get("/cases/{case_id}/revisions", response_model=dict)
def list_revisions(
    case_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    case = _owned_case(session, user_id=current_user.id, case_id=case_id)
    query = session.query(ResearchCaseRevision).filter_by(case_id=case.id)
    total = query.count()
    revisions = (
        query.order_by(ResearchCaseRevision.revision_number.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [serialize_revision(revision) for revision in revisions],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post("/cases/{case_id}/revisions/{revision_number}/redact", response_model=dict)
def redact_case_revision(
    case_id: int,
    revision_number: int,
    payload: ResearchRevisionRedact,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    try:
        revision = redact_revision(
            session,
            user_id=current_user.id,
            case_id=case_id,
            revision_number=revision_number,
            reason=payload.reason,
        )
    except ResearchCaseError as error:
        _raise(session, error)
    return {"revision": serialize_revision(revision)}


@router.get("/cases/{case_id}/events", response_model=dict)
def list_events(
    case_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    case = _owned_case(session, user_id=current_user.id, case_id=case_id)
    query = session.query(ResearchCaseEvent).filter_by(case_id=case.id)
    total = query.count()
    rows = (
        query.order_by(ResearchCaseEvent.created_at, ResearchCaseEvent.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "event_type": row.event_type,
                "correlation_id": row.correlation_id,
                "payload": row.payload_json,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post("/inbox/regenerate", response_model=dict)
def regenerate_research_inbox(
    session: SessionDep,
    current_user: CurrentUser,
    as_of: date | None = Query(default=None),
    lens: Literal["consensus", "distinctive"] = Query(default="consensus"),
) -> dict[str, Any]:
    try:
        return regenerate_inbox(
            session,
            user_id=current_user.id,
            as_of=_current_projection_date(as_of),
            lens=lens,
        )
    except ResearchInboxError as error:
        session.rollback()
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error


@router.get("/inbox", response_model=dict)
def list_inbox_actions(
    session: SessionDep,
    current_user: CurrentUser,
    include_snoozed: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    visible_states = ["open", "snoozed"] if include_snoozed else ["open"]
    query = (
        session.query(ResearchInboxAction, Stock)
        .outerjoin(Stock, Stock.id == ResearchInboxAction.stock_id)
        .filter(
            ResearchInboxAction.user_id == current_user.id,
            ResearchInboxAction.state.in_(visible_states),
        )
    )
    total = query.count()
    rows = (
        query.order_by(
            ResearchInboxAction.priority_rank,
            ResearchInboxAction.first_observed_at,
            ResearchInboxAction.id,
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [serialize_action(action, stock) for action, stock in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def _mutate_inbox_action(
    session: SessionDep,
    operation,
    *,
    user_id: int,
    action_id: int,
    **kwargs,
) -> dict[str, Any]:
    try:
        action = operation(
            session,
            user_id=user_id,
            action_id=action_id,
            **kwargs,
        )
    except ResearchInboxError as error:
        session.rollback()
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    stock = session.get(Stock, action.stock_id) if action.stock_id else None
    return {"action": serialize_action(action, stock)}


@router.post("/inbox/{action_id}/snooze", response_model=dict)
def snooze_inbox_action(
    action_id: int,
    payload: ResearchInboxSnooze,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    return _mutate_inbox_action(
        session,
        snooze_action,
        user_id=current_user.id,
        action_id=action_id,
        snoozed_until=payload.snoozed_until,
    )


@router.post("/inbox/{action_id}/dismiss", response_model=dict)
def dismiss_inbox_action(
    action_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    return _mutate_inbox_action(
        session,
        dismiss_action,
        user_id=current_user.id,
        action_id=action_id,
    )


@router.post("/inbox/{action_id}/complete", response_model=dict)
def complete_inbox_action(
    action_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, Any]:
    return _mutate_inbox_action(
        session,
        complete_action,
        user_id=current_user.id,
        action_id=action_id,
    )
