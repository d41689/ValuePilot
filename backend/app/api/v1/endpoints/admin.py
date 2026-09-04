from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.api.deps import SessionDep, AdminUser
from app.models.users import User
from app.schemas.users import UserRead, UserUpdate
from app.schemas.method_applicability import (
    ClassificationReviewCreate,
    ClassificationReviewRead,
    RiskReviewCreate,
    RiskReviewRead,
)
from app.services.method_applicability import (
    MethodApplicabilityReviewError,
    review_company_classification,
    review_company_risk_attribute,
)

router = APIRouter()


def _method_review_http_error(error: MethodApplicabilityReviewError) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if error.code == "stock_not_found"
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": str(error)},
    )


def _method_review_db_conflict(error: DBAPIError) -> HTTPException:
    detail = str(error.orig).lower()
    if "method applicability review requires active admin" in detail:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "reviewer_not_authorized",
                "message": "Method review requires an active admin; reload and retry.",
            },
        )
    known_conflicts = (
        "overlapping economic classification review",
        "overlapping economic risk review",
        "invalid economic classification supersession",
        "invalid economic risk supersession",
        "duplicate key value",
    )
    if not any(marker in detail for marker in known_conflicts):
        raise error
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "method_review_write_conflict",
            "message": "Method review authority changed; reload and retry.",
        },
    )
@router.post(
    "/stocks/{stock_id}/method-classification-reviews",
    response_model=ClassificationReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def create_method_classification_review(
    *,
    session: SessionDep,
    current_user: AdminUser,
    stock_id: int,
    payload: ClassificationReviewCreate,
) -> Any:
    try:
        review = review_company_classification(
            session,
            reviewer_user_id=current_user.id,
            stock_id=stock_id,
            economic_class=payload.economic_class,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            review_reason=payload.review_reason,
            supersedes_review_id=payload.supersedes_review_id,
        )
        session.commit()
        session.refresh(review)
        return review
    except MethodApplicabilityReviewError as error:
        session.rollback()
        raise _method_review_http_error(error) from error
    except DBAPIError as error:
        session.rollback()
        raise _method_review_db_conflict(error) from error


@router.post(
    "/stocks/{stock_id}/method-risk-reviews",
    response_model=RiskReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def create_method_risk_review(
    *,
    session: SessionDep,
    current_user: AdminUser,
    stock_id: int,
    payload: RiskReviewCreate,
) -> Any:
    try:
        review = review_company_risk_attribute(
            session,
            reviewer_user_id=current_user.id,
            stock_id=stock_id,
            risk_attribute=payload.risk_attribute,
            is_present=payload.is_present,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            review_reason=payload.review_reason,
            supersedes_review_id=payload.supersedes_review_id,
        )
        session.commit()
        session.refresh(review)
        return review
    except MethodApplicabilityReviewError as error:
        session.rollback()
        raise _method_review_http_error(error) from error
    except DBAPIError as error:
        session.rollback()
        raise _method_review_db_conflict(error) from error


@router.get("/users", response_model=list[UserRead])
def list_users(
    *,
    session: SessionDep,
    current_user: AdminUser,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    stmt = select(User).offset(skip).limit(limit)
    return list(session.scalars(stmt).all())


@router.patch("/users/{user_id}", response_model=UserRead)
def patch_user(
    *,
    session: SessionDep,
    current_user: AdminUser,
    user_id: int,
    payload: UserUpdate,
) -> Any:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    changed = False
    if payload.role is not None and payload.role != user.role:
        user.role = payload.role
        changed = True
    if payload.tier is not None and payload.tier != user.tier:
        user.tier = payload.tier
        changed = True
    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active = payload.is_active
        changed = True

    if changed:
        session.add(user)
        session.commit()
        session.refresh(user)

    return user


@router.delete("/users/{user_id}", response_model=dict)
def disable_user(
    *,
    session: SessionDep,
    current_user: AdminUser,
    user_id: int,
) -> Any:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot disable current admin user")

    user.is_active = False
    session.add(user)
    session.commit()
    return {"status": "disabled", "user_id": user.id}
