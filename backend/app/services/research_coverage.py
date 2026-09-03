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
    CanonicalEodPrice,
    PRICE_FRESHNESS_POLICY_VERSION,
    StoredPriceEvidence,
    read_canonical_eod_price,
    read_current_eod_prices,
    read_stored_price_evidence,
    serialize_canonical_eod_price,
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
    knowledge_cutoff: datetime | None = None,
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
        knowledge_cutoff=knowledge_cutoff,
    )
    canonical = serialize_canonical_eod_price(result)
    if result.status == "available":
        state = "ready"
    elif result.reason_code == "price_older_than_expected_session":
        state = "stale"
    elif result.reason_code == "price_missing":
        state = "missing"
    else:
        state = "blocked"
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
            "price_date": canonical["price_date"],
            "expected_session_date": canonical["expected_session_date"],
            "close": (
                str(canonical["observation_value"])
                if canonical["observation_value"] is not None
                else None
            ),
            "currency": canonical["currency"],
            "source": canonical["source"],
            "source_authorization_state": canonical["source_authorization_state"],
            "calendar_code": canonical["calendar_code"],
            "status": canonical["status"],
            "as_of_date": canonical["as_of_date"],
            "as_of_mode": canonical["as_of_mode"],
            "source_policy_version": canonical["source_policy_version"],
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
    price_knowledge_cutoff = evaluated_at if as_of == evaluated_at.date() else None
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
                    knowledge_cutoff=price_knowledge_cutoff,
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


def _serialize_price_requirement_evidence(
    *,
    row: ResearchCoverageRequirement,
    canonical: CanonicalEodPrice | None,
    referenced: StoredPriceEvidence | None,
) -> tuple[dict[str, Any], str | None]:
    """Return persisted price evidence only while its authority remains valid.

    Read permission is deliberately stricter than storage. A legacy snapshot
    without proof that its source was authorized when persisted cannot acquire
    authority merely because that provider happens to be configured today.
    """
    evidence = dict(row.evidence_json or {})
    had_displayable_observation = evidence.get("close") is not None
    if not (had_displayable_observation or row.state == "ready"):
        return evidence, None

    persisted_authorization = evidence.get("source_authorization_state")
    current_authorization = (
        referenced.source_authorization_state
        if referenced is not None
        else "unavailable"
    )
    authoritative_currency = referenced.currency if referenced is not None else None
    blocker_reason = None
    if (
        row.source_type != "stock_price"
        or referenced is None
        or persisted_authorization != "authorized"
        or current_authorization != "authorized"
    ):
        blocker_reason = "source_unavailable"
    elif authoritative_currency is None:
        blocker_reason = "price_currency_unavailable"
    elif (
        str(evidence.get("source") or "").strip().lower()
        != referenced.normalized_source
        or str(evidence.get("currency") or "").strip().upper()
        != authoritative_currency
        or evidence.get("price_date") != referenced.price_date.isoformat()
    ):
        blocker_reason = "price_reference_mismatch"
    elif canonical is None:
        blocker_reason = "price_missing"
    elif canonical.status != "available":
        blocker_reason = canonical.reason_code or "price_unavailable"
    elif canonical.price_id != referenced.price_id:
        blocker_reason = "price_reference_mismatch"

    if blocker_reason is None:
        evidence["source_authorization_state"] = "authorized"
        evidence["currency"] = authoritative_currency
        return evidence, None

    evidence["close"] = None
    evidence["source_authorization_state"] = (
        current_authorization
        if persisted_authorization == "authorized"
        else "unavailable"
    )
    if blocker_reason == "price_currency_unavailable":
        evidence["currency"] = None
    return evidence, blocker_reason


def _projection_state(row: ResearchCoverageRequirement, blocker_reason: str | None) -> str:
    if blocker_reason is None:
        return row.state
    if blocker_reason == "price_older_than_expected_session":
        return "stale"
    if blocker_reason == "price_missing":
        return "missing"
    return "blocked"


def _projection_reason(blocker_reason: str) -> str:
    return {
        "price_currency_unavailable": (
            "The persisted price currency is not a current monetary ISO 4217 code."
        ),
        "price_older_than_expected_session": (
            "The persisted price no longer covers the latest expected market session."
        ),
        "price_missing": "No canonical EOD observation is currently available.",
        "price_reference_mismatch": (
            "The persisted price reference no longer matches canonical price evidence."
        ),
    }.get(
        blocker_reason,
        "The persisted price source is not currently authorized for display.",
    )


def _serialize_requirement(
    row: ResearchCoverageRequirement,
    stock: Stock,
    *,
    canonical: CanonicalEodPrice | None = None,
    referenced: StoredPriceEvidence | None = None,
) -> dict[str, Any]:
    evidence = dict(row.evidence_json or {})
    blocker_reason = None
    if row.kind == "eod_price":
        evidence, blocker_reason = _serialize_price_requirement_evidence(
            row=row,
            canonical=canonical,
            referenced=referenced,
        )
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
        "state": _projection_state(row, blocker_reason),
        "reason_code": (
            row.reason_code
            if blocker_reason is None
            else blocker_reason
        ),
        "reason": (
            row.reason
            if blocker_reason is None
            else _projection_reason(blocker_reason)
        ),
        "source_type": row.source_type,
        "source_ref_id": row.source_ref_id,
        "evidence": evidence,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "freshness_policy_version": row.freshness_policy_version,
        "evaluated_at": row.evaluated_at.isoformat(),
        "next_action": (
            row.next_action
            if blocker_reason is None
            else "refresh_eod_price"
        ),
        "first_unmet_at": (
            row.first_unmet_at.isoformat() if row.first_unmet_at else None
        ),
    }


def serialize_requirements(
    session: Session,
    rows: list[tuple[ResearchCoverageRequirement, Stock]],
    *,
    evaluated_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Project coverage with one request clock and fixed-count price reads."""

    projection_time = evaluated_at or datetime.now(timezone.utc)
    price_rows = [pair for pair in rows if pair[0].kind == "eod_price"]
    canonical_by_stock_id = read_current_eod_prices(
        session,
        stocks=[stock for _, stock in price_rows],
        evaluated_at=projection_time,
    )
    references = read_stored_price_evidence(
        session,
        references=[
            (int(row.source_ref_id), int(row.stock_id))
            for row, _ in price_rows
            if row.source_ref_id is not None
        ],
    )
    return [
        _serialize_requirement(
            row,
            stock,
            canonical=canonical_by_stock_id.get(int(row.stock_id)),
            referenced=(
                references.get((int(row.source_ref_id), int(row.stock_id)))
                if row.source_ref_id is not None
                else None
            ),
        )
        for row, stock in rows
    ]


def serialize_requirement(
    session: Session,
    row: ResearchCoverageRequirement,
    stock: Stock,
    *,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper; product list projections use the batch API."""

    return serialize_requirements(
        session,
        [(row, stock)],
        evaluated_at=evaluated_at,
    )[0]
