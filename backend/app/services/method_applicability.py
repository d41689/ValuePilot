"""Authorized append-only operator writes for reviewed method applicability."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.sec_publication import (
    SecEconomicClassificationReview,
    SecEconomicRiskReview,
)
from app.models.stocks import Stock
from app.models.users import User


ECONOMIC_CLASSES = frozenset(
    {"ordinary", "bank", "insurer", "reit", "other_financial", "unclassified"}
)
RISK_ATTRIBUTES = frozenset(
    {"high_sbc", "acquisitive", "cyclical", "commodity_exposed"}
)


class MethodApplicabilityReviewError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _require_operator_and_stock(
    session: Session, *, reviewer_user_id: int, stock_id: int
) -> None:
    reviewer = session.scalar(
        select(User).where(
            User.id == reviewer_user_id,
            User.role == "admin",
            User.is_active.is_(True),
        )
    )
    if reviewer is None:
        raise MethodApplicabilityReviewError(
            "reviewer_not_authorized", "method review requires an active admin"
        )
    if session.get(Stock, stock_id) is None:
        raise MethodApplicabilityReviewError("stock_not_found", "stock not found")


def _validate_review(
    *, effective_from: date, effective_to: date | None, review_reason: str
) -> str:
    if effective_to is not None and effective_to < effective_from:
        raise MethodApplicabilityReviewError(
            "invalid_effective_interval", "effective_to precedes effective_from"
        )
    reason = review_reason.strip()
    if not reason:
        raise MethodApplicabilityReviewError(
            "review_reason_required", "review_reason is required"
        )
    return reason


def _lock_review_slot(session: Session, *, stock_id: int, kind: str) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"method-applicability-review:{stock_id}:{kind}"},
    )


def _validate_supersession(
    session: Session,
    *,
    model: type[SecEconomicClassificationReview] | type[SecEconomicRiskReview],
    supersedes_review_id: int | None,
    stock_id: int,
    effective_from: date,
    effective_to: date | None,
    risk_attribute: str | None = None,
) -> None:
    query = select(model).where(model.stock_id == stock_id)
    if risk_attribute is not None:
        query = query.where(model.risk_attribute == risk_attribute)
    rows = list(session.scalars(query.order_by(model.id)).all())
    superseded_ids = {
        row.supersedes_review_id
        for row in rows
        if row.supersedes_review_id is not None
    }
    terminal = [row for row in rows if row.id not in superseded_ids]

    def overlaps(row: SecEconomicClassificationReview | SecEconomicRiskReview) -> bool:
        return (row.effective_to is None or effective_from <= row.effective_to) and (
            effective_to is None or row.effective_from <= effective_to
        )

    if supersedes_review_id is None:
        if any(overlaps(row) for row in terminal):
            raise MethodApplicabilityReviewError(
                "overlapping_method_review",
                "overlapping review requires the exact terminal supersession target",
            )
        return
    prior = next((row for row in terminal if row.id == supersedes_review_id), None)
    if prior is None:
        raise MethodApplicabilityReviewError(
            "stale_review_supersession", "review supersession target is not terminal"
        )
    if risk_attribute is not None and prior.risk_attribute != risk_attribute:
        raise MethodApplicabilityReviewError(
            "invalid_review_supersession", "risk review type cannot change on supersession"
        )
    if not overlaps(prior):
        raise MethodApplicabilityReviewError(
            "invalid_review_supersession",
            "superseding review must overlap its exact target interval",
        )
    if any(row.id != prior.id and overlaps(row) for row in terminal):
        raise MethodApplicabilityReviewError(
            "overlapping_method_review", "review overlaps another terminal interval"
        )


def review_company_classification(
    session: Session,
    *,
    reviewer_user_id: int,
    stock_id: int,
    economic_class: str,
    effective_from: date,
    review_reason: str,
    effective_to: date | None = None,
    supersedes_review_id: int | None = None,
) -> SecEconomicClassificationReview:
    if economic_class not in ECONOMIC_CLASSES:
        raise MethodApplicabilityReviewError(
            "invalid_economic_class", "economic_class is not supported"
        )
    reason = _validate_review(
        effective_from=effective_from,
        effective_to=effective_to,
        review_reason=review_reason,
    )
    _require_operator_and_stock(
        session, reviewer_user_id=reviewer_user_id, stock_id=stock_id
    )
    _lock_review_slot(session, stock_id=stock_id, kind="classification")
    _validate_supersession(
        session,
        model=SecEconomicClassificationReview,
        supersedes_review_id=supersedes_review_id,
        stock_id=stock_id,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    review = SecEconomicClassificationReview(
        stock_id=stock_id,
        economic_class=economic_class,
        effective_from=effective_from,
        effective_to=effective_to,
        reviewer_user_id=reviewer_user_id,
        review_reason=reason,
        supersedes_review_id=supersedes_review_id,
    )
    session.add(review)
    session.flush()
    session.refresh(review)
    return review


def review_company_risk_attribute(
    session: Session,
    *,
    reviewer_user_id: int,
    stock_id: int,
    risk_attribute: str,
    is_present: bool,
    effective_from: date,
    review_reason: str,
    effective_to: date | None = None,
    supersedes_review_id: int | None = None,
) -> SecEconomicRiskReview:
    if risk_attribute not in RISK_ATTRIBUTES:
        raise MethodApplicabilityReviewError(
            "invalid_risk_attribute", "risk_attribute is not supported"
        )
    reason = _validate_review(
        effective_from=effective_from,
        effective_to=effective_to,
        review_reason=review_reason,
    )
    _require_operator_and_stock(
        session, reviewer_user_id=reviewer_user_id, stock_id=stock_id
    )
    _lock_review_slot(session, stock_id=stock_id, kind=f"risk:{risk_attribute}")
    _validate_supersession(
        session,
        model=SecEconomicRiskReview,
        supersedes_review_id=supersedes_review_id,
        stock_id=stock_id,
        effective_from=effective_from,
        effective_to=effective_to,
        risk_attribute=risk_attribute,
    )
    review = SecEconomicRiskReview(
        stock_id=stock_id,
        risk_attribute=risk_attribute,
        is_present=is_present,
        effective_from=effective_from,
        effective_to=effective_to,
        reviewer_user_id=reviewer_user_id,
        review_reason=reason,
        supersedes_review_id=supersedes_review_id,
    )
    session.add(review)
    session.flush()
    session.refresh(review)
    return review
