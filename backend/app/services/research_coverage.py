"""Explainable, user-scoped coverage priority and readiness projection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.artifacts import PdfDocument
from app.models.coverage import ResearchCoverageRequirement
from app.models.oracles_lens import OraclesLensSignal
from app.models.research import ResearchCase
from app.models.stocks import PoolMembership, Stock
from app.services.market_data_service import (
    PRICE_FRESHNESS_POLICY_VERSION,
    read_canonical_eod_price,
)
from app.services.oracles_lens.constants import SCORE_VERSION


PRIORITY_POLICY_VERSION = "research-coverage-priority-v1.0"
VALUE_LINE_FRESHNESS_POLICY_VERSION = "value-line-120d-v1.0"
VALUE_LINE_MAX_AGE_DAYS = 120


@dataclass(frozen=True)
class _Candidate:
    stock_id: int
    matched_rule: str
    tier: int
    lens_rank: int | None = None


def _lens_candidates(
    session: Session,
    *,
    lens: str,
    limit: int,
) -> tuple[list[tuple[int, int]], int]:
    latest_quarter = session.query(func.max(OraclesLensSignal.report_quarter)).filter(
        OraclesLensSignal.score_version == SCORE_VERSION
    ).scalar()
    if latest_quarter is None:
        return [], 0
    score_column = (
        OraclesLensSignal.distinctive_consensus_score
        if lens == "distinctive"
        else OraclesLensSignal.signal_weighted_consensus_score
    )
    base = session.query(OraclesLensSignal).filter(
        OraclesLensSignal.report_quarter == latest_quarter,
        OraclesLensSignal.score_version == SCORE_VERSION,
        score_column.isnot(None),
    )
    eligible_count = base.count()
    rows = (
        base.order_by(score_column.desc().nullslast(), OraclesLensSignal.stock_id.asc())
        .limit(limit)
        .all()
    )
    return [(row.stock_id, rank) for rank, row in enumerate(rows, start=1)], eligible_count


def _candidates(
    session: Session,
    *,
    user_id: int,
    as_of: date,
    lens: str,
    lens_limit: int,
) -> tuple[list[_Candidate], int, int]:
    selected: dict[int, _Candidate] = {}
    open_cases = (
        session.query(ResearchCase)
        .filter(
            ResearchCase.user_id == user_id,
            ResearchCase.state.in_(["queued", "researching", "monitoring"]),
        )
        .order_by(ResearchCase.created_at, ResearchCase.id)
        .all()
    )
    for case in open_cases:
        if case.state == "monitoring" and case.decision == "own":
            overdue = bool(case.next_review_on and case.next_review_on <= as_of)
            matched_rule = "open_case_own_overdue" if overdue else "open_case_own"
            tier = 1
        elif case.state == "monitoring" and case.decision == "watch":
            overdue = bool(case.next_review_on and case.next_review_on <= as_of)
            matched_rule = "open_case_watch_overdue" if overdue else "open_case_watch"
            tier = 2
        elif case.state == "researching":
            matched_rule = "open_case_researching"
            tier = 3
        else:
            matched_rule = "open_case_queued"
            tier = 4
        selected[int(case.stock_id)] = _Candidate(
            stock_id=int(case.stock_id),
            matched_rule=matched_rule,
            tier=tier,
        )

    watchlist_stock_ids = [
        row[0]
        for row in (
            session.query(PoolMembership.stock_id)
            .filter(PoolMembership.user_id == user_id)
            .distinct()
            .all()
        )
    ]
    for stock_id in watchlist_stock_ids:
        selected.setdefault(
            int(stock_id),
            _Candidate(
                stock_id=int(stock_id),
                matched_rule="watchlist_member",
                tier=5,
            ),
        )

    lens_rows, lens_eligible_count = _lens_candidates(
        session, lens=lens, limit=lens_limit
    )
    lens_selected_count = 0
    for stock_id, lens_rank in lens_rows:
        lens_selected_count += 1
        selected.setdefault(
            int(stock_id),
            _Candidate(
                stock_id=int(stock_id),
                matched_rule=f"oracles_lens_{lens}_top{lens_limit}",
                tier=6,
                lens_rank=lens_rank,
            ),
        )

    first_unmet_by_stock: dict[int, datetime] = {}
    if selected:
        rows = (
            session.query(
                ResearchCoverageRequirement.stock_id,
                func.min(ResearchCoverageRequirement.first_unmet_at),
            )
            .filter(
                ResearchCoverageRequirement.user_id == user_id,
                ResearchCoverageRequirement.stock_id.in_(selected),
                ResearchCoverageRequirement.is_current.is_(True),
            )
            .group_by(ResearchCoverageRequirement.stock_id)
            .all()
        )
        first_unmet_by_stock = {
            int(stock_id): first_unmet
            for stock_id, first_unmet in rows
            if first_unmet is not None
        }
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    ordered = sorted(
        selected.values(),
        key=lambda item: (
            item.tier,
            first_unmet_by_stock.get(item.stock_id, far_future),
            item.stock_id,
        ),
    )
    return ordered, lens_eligible_count, lens_selected_count


def _price_requirement(
    session: Session,
    *,
    stock: Stock,
    as_of: date,
    include_as_of_session: bool = False,
) -> dict[str, Any]:
    if not stock.is_active:
        return {
            "state": "blocked",
            "reason_code": "stock_inactive",
            "reason": "Automatic price refresh is disabled for an inactive stock.",
            "source_type": None,
            "source_ref_id": None,
            "evidence_json": {"is_active": False},
            "observed_at": None,
            "next_action": "review_stock_identity",
        }
    result = read_canonical_eod_price(
        session,
        stock=stock,
        as_of=as_of,
        include_as_of_session=include_as_of_session,
    )
    state = {
        "fresh": "ready",
        "stale": "stale",
        "missing": "missing",
        "unknown_freshness": "blocked",
    }[result.freshness_state]
    return {
        "state": state,
        "reason_code": result.reason_code,
        "reason": {
            "ready": "A canonical EOD close exists for the latest expected session.",
            "stale": "The latest canonical EOD close predates the expected session.",
            "missing": "No canonical EOD observation is stored for this stock.",
            "blocked": "Price freshness cannot be established from the current identity or currency evidence.",
        }[state],
        "source_type": "stock_price" if result.price_id else None,
        "source_ref_id": result.price_id,
        "evidence_json": {
            "price_date": result.price_date.isoformat() if result.price_date else None,
            "expected_session_date": (
                result.expected_session_date.isoformat()
                if result.expected_session_date
                else None
            ),
            "close": str(result.close) if result.close is not None else None,
            "currency": result.currency,
            "source": result.source,
            "calendar_code": result.calendar_code,
        },
        "observed_at": result.observed_at,
        "next_action": (
            None
            if state == "ready"
            else "refresh_eod_price"
            if state in {"missing", "stale"}
            or result.reason_code == "price_currency_unavailable"
            else "review_stock_identity"
        ),
    }


def _value_line_requirement(
    session: Session,
    *,
    user_id: int,
    stock: Stock,
    as_of: date,
) -> dict[str, Any]:
    document = (
        session.query(PdfDocument)
        .filter(
            PdfDocument.user_id == user_id,
            PdfDocument.stock_id == stock.id,
            PdfDocument.parse_status == "parsed",
            func.lower(PdfDocument.source).like("%value%line%"),
        )
        .order_by(
            PdfDocument.report_date.desc().nullslast(),
            PdfDocument.upload_time.desc(),
            PdfDocument.id.desc(),
        )
        .first()
    )
    if document is None:
        return {
            "state": "missing",
            "reason_code": "value_line_report_missing",
            "reason": "No parsed Value Line report owned by this user covers the stock.",
            "source_type": None,
            "source_ref_id": None,
            "evidence_json": {"max_age_days": VALUE_LINE_MAX_AGE_DAYS},
            "observed_at": None,
            "next_action": "upload_value_line_report",
        }
    if document.report_date is None:
        state = "failed"
        reason_code = "value_line_report_date_missing"
        reason = "The parsed report has no source-backed report date."
    else:
        age_days = (as_of - document.report_date).days
        if age_days < 0:
            state = "failed"
            reason_code = "value_line_report_date_in_future"
            reason = "The report date is later than the coverage evaluation date."
        elif age_days <= VALUE_LINE_MAX_AGE_DAYS:
            state = "ready"
            reason_code = None
            reason = "The latest user-owned Value Line report is within policy age."
        else:
            state = "stale"
            reason_code = "value_line_report_older_than_policy"
            reason = "The latest user-owned Value Line report exceeds the 120-day policy."
    return {
        "state": state,
        "reason_code": reason_code,
        "reason": reason,
        "source_type": "pdf_document",
        "source_ref_id": document.id,
        "evidence_json": {
            "report_date": (
                document.report_date.isoformat() if document.report_date else None
            ),
            "parse_status": document.parse_status,
            "max_age_days": VALUE_LINE_MAX_AGE_DAYS,
        },
        "observed_at": document.upload_time,
        "next_action": None if state == "ready" else "upload_value_line_report",
    }


def _upsert_requirement(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    kind: str,
    priority_rank: int,
    candidate: _Candidate,
    freshness_policy_version: str,
    evaluated_at: datetime,
    evaluation: dict[str, Any],
) -> None:
    row = (
        session.query(ResearchCoverageRequirement)
        .filter_by(
            user_id=user_id,
            stock_id=stock_id,
            kind=kind,
            priority_policy_version=PRIORITY_POLICY_VERSION,
        )
        .one_or_none()
    )
    if row is None:
        row = ResearchCoverageRequirement(
            user_id=user_id,
            stock_id=stock_id,
            kind=kind,
            priority_policy_version=PRIORITY_POLICY_VERSION,
        )
        session.add(row)
    row.matched_rule = candidate.matched_rule
    row.priority_rank = priority_rank
    row.rank_components = {
        "tier": candidate.tier,
        "lens_rank": candidate.lens_rank,
        "tie_breaker": "oldest_unmet_then_stock_id",
    }
    row.state = evaluation["state"]
    row.reason_code = evaluation["reason_code"]
    row.reason = evaluation["reason"]
    row.source_type = evaluation["source_type"]
    row.source_ref_id = evaluation["source_ref_id"]
    row.evidence_json = evaluation["evidence_json"]
    row.observed_at = evaluation["observed_at"]
    row.freshness_policy_version = freshness_policy_version
    row.evaluated_at = evaluated_at
    row.next_action = evaluation["next_action"]
    row.first_unmet_at = (
        None
        if row.state == "ready"
        else row.first_unmet_at or evaluated_at
    )
    row.is_current = True


def evaluate_research_coverage(
    session: Session,
    *,
    user_id: int,
    as_of: date,
    lens: str = "consensus",
    lens_limit: int = 30,
    include_as_of_session: bool = False,
) -> dict[str, Any]:
    if lens not in {"consensus", "distinctive"}:
        raise ValueError("lens must be consensus or distinctive")
    if lens_limit < 1 or lens_limit > 30:
        raise ValueError("lens_limit must be between 1 and 30")

    # ORM read/update upserts are serialized per user+policy. This makes two
    # page loads idempotent without weakening the database uniqueness guard.
    session.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"
        ),
        {"key": f"coverage:{user_id}:{PRIORITY_POLICY_VERSION}"},
    )
    evaluated_at = datetime.now(timezone.utc)
    candidates, lens_eligible_count, lens_evaluated_count = _candidates(
        session,
        user_id=user_id,
        as_of=as_of,
        lens=lens,
        lens_limit=lens_limit,
    )
    (
        session.query(ResearchCoverageRequirement)
        .filter_by(
            user_id=user_id,
            priority_policy_version=PRIORITY_POLICY_VERSION,
        )
        .update({ResearchCoverageRequirement.is_current: False})
    )

    requirements_evaluated = 0
    for candidate_rank, candidate in enumerate(candidates, start=1):
        stock = session.get(Stock, candidate.stock_id)
        if stock is None:
            continue
        evaluations = (
            (
                "eod_price",
                PRICE_FRESHNESS_POLICY_VERSION,
                _price_requirement(
                    session,
                    stock=stock,
                    as_of=as_of,
                    include_as_of_session=include_as_of_session,
                ),
            ),
            (
                "value_line_current_report",
                VALUE_LINE_FRESHNESS_POLICY_VERSION,
                _value_line_requirement(
                    session, user_id=user_id, stock=stock, as_of=as_of
                ),
            ),
        )
        for kind_offset, (kind, policy, evaluation) in enumerate(evaluations):
            _upsert_requirement(
                session,
                user_id=user_id,
                stock_id=stock.id,
                kind=kind,
                priority_rank=candidate_rank * 10 + kind_offset,
                candidate=candidate,
                freshness_policy_version=policy,
                evaluated_at=evaluated_at,
                evaluation=evaluation,
            )
            requirements_evaluated += 1
    session.commit()
    return {
        "priority_policy_version": PRIORITY_POLICY_VERSION,
        "value_line_freshness_policy_version": VALUE_LINE_FRESHNESS_POLICY_VERSION,
        "lens": lens,
        "lens_score_version": SCORE_VERSION,
        "selected_candidate_count": len(candidates),
        "lens_eligible_count": lens_eligible_count,
        "lens_evaluated_count": lens_evaluated_count,
        "lens_denominator": min(lens_limit, lens_eligible_count),
        "requirements_evaluated": requirements_evaluated,
        "evaluated_at": evaluated_at.isoformat(),
    }


def serialize_requirement(row: ResearchCoverageRequirement, stock: Stock) -> dict[str, Any]:
    return {
        "id": row.id,
        "stock_id": row.stock_id,
        "ticker": stock.ticker,
        "company_name": stock.company_name,
        "kind": row.kind,
        "priority_policy_version": row.priority_policy_version,
        "matched_rule": row.matched_rule,
        "priority_rank": row.priority_rank,
        "rank_components": row.rank_components or {},
        "state": row.state,
        "reason_code": row.reason_code,
        "reason": row.reason,
        "source_type": row.source_type,
        "source_ref_id": row.source_ref_id,
        "evidence": row.evidence_json or {},
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "freshness_policy_version": row.freshness_policy_version,
        "evaluated_at": row.evaluated_at.isoformat(),
        "next_action": row.next_action,
        "first_unmet_at": (
            row.first_unmet_at.isoformat() if row.first_unmet_at else None
        ),
    }
