"""Reviewed, point-in-time applicability gate for financial analysis methods."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import exists, or_, select, text
from sqlalchemy.orm import Session, aliased

from app.models.analysis_methods import CompanyAnalysisClassification


METHOD_POLICY_VERSION = "analysis-method-gate-v1"
CLASSIFICATIONS = {
    "ordinary_operating",
    "bank",
    "insurer",
    "reit",
    "high_sbc_acquisitive",
    "cyclical_commodity",
}
ANALYSIS_KINDS = {"owner_earnings", "roic", "per_share_trend", "valuation"}
ORDINARY_METHODS = {
    "owner_earnings": (
        "ordinary-owner-economics-v1",
        (
            "operating_cash_flow",
            "maintenance_capex",
            "working_capital",
            "stock_based_compensation",
            "acquisitions",
            "dilution",
        ),
        False,
    ),
    "roic": (
        "ordinary-roic-v1",
        (
            "nopat",
            "invested_capital",
            "acquisition_adjustments",
            "excess_cash_policy",
        ),
        True,
    ),
    "per_share_trend": (
        "ordinary-per-share-trend-v1",
        ("comparable_history", "diluted_share_count", "corporate_actions"),
        True,
    ),
}


def analysis_kind_for_metric(metric_key: str) -> str | None:
    if metric_key.startswith("owners_earnings"):
        return "owner_earnings"
    if metric_key in {
        "returns.roic",
        "returns.total_capital",
        "bs.return_on_total_capital",
    }:
        return "roic"
    return None


def metric_fact_matches_method(
    fact: Any,
    method: AnalysisMethodResult,
) -> bool:
    if (
        method.state != "eligible"
        or method.method_id is None
        or not method.output_authorized
    ):
        return False
    value_json = getattr(fact, "value_json", None)
    if not isinstance(value_json, dict):
        return False
    context = value_json.get("analysis_method")
    return bool(
        isinstance(context, dict)
        and context.get("policy_version") == method.policy_version
        and context.get("classification_id") == method.classification_id
        and context.get("method_id") == method.method_id
        and context.get("evidence_complete") is True
    )


class AnalysisMethodError(ValueError):
    pass


@dataclass(frozen=True)
class AnalysisMethodResult:
    stock_id: int
    analysis_kind: str
    state: str
    reason_code: str | None
    policy_version: str
    classification: str | None
    classification_id: int | None
    method_id: str | None
    required_evidence: tuple[str, ...]
    knowledge_cutoff: datetime
    output_authorized: bool = False
    conclusion_authorized: bool = False


def _overlaps(
    left_start: date,
    left_end: date | None,
    right_start: date,
    right_end: date | None,
) -> bool:
    return (left_end is None or right_start <= left_end) and (
        right_end is None or left_start <= right_end
    )


def register_reviewed_company_classification(
    session: Session,
    *,
    stock_id: int,
    classification: str,
    effective_from: date,
    known_at: datetime,
    review_reason: str,
    effective_to: date | None = None,
    reviewer_user_id: int | None = None,
    evidence: dict[str, Any] | None = None,
    supersedes_classification_id: int | None = None,
) -> CompanyAnalysisClassification:
    if known_at.tzinfo is None:
        raise AnalysisMethodError("known_at must be timezone-aware")
    if classification not in CLASSIFICATIONS:
        raise AnalysisMethodError("unsupported company classification")
    if not review_reason.strip():
        raise AnalysisMethodError("review_reason is required")
    if effective_to is not None and effective_to < effective_from:
        raise AnalysisMethodError("effective_to precedes effective_from")
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"company-analysis-classification:{stock_id}"},
    )
    rows = session.scalars(
        select(CompanyAnalysisClassification)
        .where(CompanyAnalysisClassification.stock_id == stock_id)
        .order_by(
            CompanyAnalysisClassification.known_at.desc(),
            CompanyAnalysisClassification.id.desc(),
        )
    ).all()
    superseded_ids = {
        row.supersedes_classification_id
        for row in rows
        if row.supersedes_classification_id is not None
    }
    terminal = [row for row in rows if row.id not in superseded_ids]
    superseded = next(
        (row for row in rows if row.id == supersedes_classification_id), None
    )
    if supersedes_classification_id is not None and (
        superseded is None
        or superseded.id not in {row.id for row in terminal}
        or known_at <= superseded.known_at
    ):
        raise AnalysisMethodError("invalid or stale classification supersession")
    for row in terminal:
        if (
            row.id != supersedes_classification_id
            and _overlaps(
                effective_from, effective_to, row.effective_from, row.effective_to
            )
        ):
            raise AnalysisMethodError("overlapping reviewed company classification")
    result = CompanyAnalysisClassification(
        stock_id=stock_id,
        classification=classification,
        status="reviewed",
        method_policy_version=METHOD_POLICY_VERSION,
        effective_from=effective_from,
        effective_to=effective_to,
        known_at=known_at,
        review_reason=review_reason.strip(),
        evidence_json=evidence or {},
        reviewer_user_id=reviewer_user_id,
        supersedes_classification_id=supersedes_classification_id,
    )
    session.add(result)
    session.flush()
    return result


def _classifications_at(
    session: Session, *, stock_id: int, cutoff: datetime
) -> list[CompanyAnalysisClassification]:
    child = aliased(CompanyAnalysisClassification)
    return list(
        session.scalars(
            select(CompanyAnalysisClassification)
            .where(
                CompanyAnalysisClassification.stock_id == stock_id,
                CompanyAnalysisClassification.status == "reviewed",
                CompanyAnalysisClassification.known_at <= cutoff,
                CompanyAnalysisClassification.effective_from <= cutoff.date(),
                or_(
                    CompanyAnalysisClassification.effective_to.is_(None),
                    CompanyAnalysisClassification.effective_to >= cutoff.date(),
                ),
                ~exists(
                    select(child.id).where(
                        child.supersedes_classification_id
                        == CompanyAnalysisClassification.id,
                        child.known_at <= cutoff,
                    )
                ),
            )
            .order_by(
                CompanyAnalysisClassification.known_at.desc(),
                CompanyAnalysisClassification.id.desc(),
            ),
        )
        .all()
    )


def evaluate_analysis_method(
    session: Session,
    *,
    stock_id: int,
    analysis_kind: str,
    cutoff: datetime,
) -> AnalysisMethodResult:
    if cutoff.tzinfo is None:
        raise AnalysisMethodError("cutoff must be timezone-aware")
    if analysis_kind not in ANALYSIS_KINDS:
        raise AnalysisMethodError("unsupported analysis kind")
    classifications = _classifications_at(session, stock_id=stock_id, cutoff=cutoff)
    if len(classifications) != 1:
        return AnalysisMethodResult(
            stock_id=stock_id,
            analysis_kind=analysis_kind,
            state="unknown",
            reason_code=(
                "company_classification_missing"
                if not classifications
                else "company_classification_conflict"
            ),
            policy_version=METHOD_POLICY_VERSION,
            classification=None,
            classification_id=None,
            method_id=None,
            required_evidence=(),
            knowledge_cutoff=cutoff,
        )
    classification = classifications[0]
    if classification.method_policy_version != METHOD_POLICY_VERSION:
        return AnalysisMethodResult(
            stock_id=stock_id,
            analysis_kind=analysis_kind,
            state="unsupported",
            reason_code="classification_policy_unsupported",
            policy_version=METHOD_POLICY_VERSION,
            classification=classification.classification,
            classification_id=classification.id,
            method_id=None,
            required_evidence=(),
            knowledge_cutoff=cutoff,
        )
    method = ORDINARY_METHODS.get(analysis_kind)
    if classification.classification == "ordinary_operating" and method is not None:
        return AnalysisMethodResult(
            stock_id=stock_id,
            analysis_kind=analysis_kind,
            state="eligible",
            reason_code=None,
            policy_version=METHOD_POLICY_VERSION,
            classification=classification.classification,
            classification_id=classification.id,
            method_id=method[0],
            required_evidence=method[1],
            knowledge_cutoff=cutoff,
            output_authorized=method[2],
        )
    reason = (
        "valuation_method_pending_ft09"
        if analysis_kind == "valuation" and classification.classification == "ordinary_operating"
        else f"{analysis_kind}_method_unapproved_for_{classification.classification}"
    )
    return AnalysisMethodResult(
        stock_id=stock_id,
        analysis_kind=analysis_kind,
        state="unsupported",
        reason_code=reason,
        policy_version=METHOD_POLICY_VERSION,
        classification=classification.classification,
        classification_id=classification.id,
        method_id=None,
        required_evidence=(),
        knowledge_cutoff=cutoff,
    )
