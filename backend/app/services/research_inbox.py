"""Deterministic, user-scoped Research Inbox projection and actions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.coverage import ResearchCoverageRequirement
from app.models.oracles_lens import OraclesLensSignal
from app.models.research import (
    ResearchCase,
    ResearchInboxAction,
    ResearchInboxActionEvent,
)
from app.models.stocks import PoolMembership, Stock
from app.services.oracles_lens.constants import SCORE_VERSION


INBOX_PRIORITY_POLICY_VERSION = "research-inbox-priority-v1.0"
INFORMATIONAL_FAMILIES = {"candidate_discovery", "manager_activity"}
MAX_SNOOZE_DAYS = 30


class ResearchInboxError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class _DesiredAction:
    logical_key: str
    action_family: str
    subject_type: str
    subject_key: str
    source_version: str
    matched_rule: str
    tier: int
    within_tier: int
    reason: str
    target_case_id: int | None
    stock_id: int
    evidence: dict[str, Any]

    @property
    def priority_rank(self) -> int:
        return self.tier * 10_000 + self.within_tier


def _case_tier(case: ResearchCase) -> int:
    if case.state == "monitoring" and case.decision == "own":
        return 1
    if case.state == "monitoring" and case.decision == "watch":
        return 2
    if case.state == "researching":
        return 3
    return 4


def _desired_actions(
    session: Session,
    *,
    user_id: int,
    as_of: date,
    lens: str,
    lens_limit: int,
) -> list[_DesiredAction]:
    desired: list[_DesiredAction] = []
    active_cases = (
        session.query(ResearchCase)
        .filter(
            ResearchCase.user_id == user_id,
            ResearchCase.state.in_(["queued", "researching", "monitoring"]),
        )
        .order_by(ResearchCase.created_at, ResearchCase.id)
        .all()
    )
    active_stock_ids = {case.stock_id for case in active_cases}
    for case in active_cases:
        tier = _case_tier(case)
        if (
            case.state == "monitoring"
            and case.next_review_on is not None
            and case.next_review_on <= as_of
        ):
            overdue = case.next_review_on < as_of
            matched_rule = (
                f"{case.decision}ed_review_overdue"
                if overdue and case.decision == "own"
                else "watch_review_overdue"
                if overdue
                else f"{case.decision}_review_due"
            )
            # Keep public copy precise: an owned research case is not a broker
            # position and this action is a review obligation, not a signal.
            if case.decision == "own":
                matched_rule = "owned_review_overdue" if overdue else "own_review_due"
            reason = (
                f"Your {case.decision} research review was scheduled for "
                f"{case.next_review_on.isoformat()}; reassess the recorded thesis and risks."
            )
            desired.append(
                _DesiredAction(
                    logical_key=f"case-review:{case.id}",
                    action_family="review_due",
                    subject_type="research_case",
                    subject_key=str(case.id),
                    source_version=(
                        f"case-v{case.version}:head-{case.head_revision_number}:"
                        f"review-{case.next_review_on.isoformat()}"
                    ),
                    matched_rule=matched_rule,
                    tier=tier,
                    within_tier=case.id,
                    reason=reason,
                    target_case_id=case.id,
                    stock_id=case.stock_id,
                    evidence={
                        "case_state": case.state,
                        "decision": case.decision,
                        "next_review_on": case.next_review_on.isoformat(),
                    },
                )
            )
        elif case.state == "researching":
            desired.append(
                _DesiredAction(
                    logical_key=f"case-research:{case.id}",
                    action_family="continue_research",
                    subject_type="research_case",
                    subject_key=str(case.id),
                    source_version=f"case-v{case.version}:head-{case.head_revision_number}",
                    matched_rule="research_incomplete",
                    tier=tier,
                    within_tier=case.id,
                    reason="This case is still researching and has no current watch, own, or pass decision.",
                    target_case_id=case.id,
                    stock_id=case.stock_id,
                    evidence={"case_state": case.state, "head_revision_number": case.head_revision_number},
                )
            )
        elif case.state == "queued":
            desired.append(
                _DesiredAction(
                    logical_key=f"case-start:{case.id}",
                    action_family="start_research",
                    subject_type="research_case",
                    subject_key=str(case.id),
                    source_version=f"case-v{case.version}:head-{case.head_revision_number}",
                    matched_rule="case_queued",
                    tier=tier,
                    within_tier=case.id,
                    reason="This queued idea has not yet received an independent research review.",
                    target_case_id=case.id,
                    stock_id=case.stock_id,
                    evidence={"case_state": case.state},
                )
            )

        requirements = (
            session.query(ResearchCoverageRequirement)
            .filter(
                ResearchCoverageRequirement.user_id == user_id,
                ResearchCoverageRequirement.stock_id == case.stock_id,
                ResearchCoverageRequirement.is_current.is_(True),
                ResearchCoverageRequirement.state != "ready",
            )
            .order_by(ResearchCoverageRequirement.priority_rank, ResearchCoverageRequirement.id)
            .all()
        )
        for requirement in requirements:
            desired.append(
                _DesiredAction(
                    logical_key=f"case-coverage:{case.id}:{requirement.kind}",
                    action_family="coverage_gap",
                    subject_type="research_case",
                    subject_key=str(case.id),
                    source_version=(
                        f"{requirement.priority_policy_version}:"
                        f"{requirement.freshness_policy_version}:"
                        f"{requirement.state}:{requirement.evaluated_at.isoformat()}"
                    ),
                    matched_rule=f"open_case_coverage_{requirement.state}",
                    tier=tier,
                    within_tier=5_000 + requirement.priority_rank,
                    reason=requirement.reason,
                    target_case_id=case.id,
                    stock_id=case.stock_id,
                    evidence={
                        "coverage_requirement_id": requirement.id,
                        "kind": requirement.kind,
                        "state": requirement.state,
                        "next_action": requirement.next_action,
                    },
                )
            )

    membership_rows = (
        session.query(PoolMembership.stock_id, func.min(PoolMembership.id))
        .filter(PoolMembership.user_id == user_id)
        .group_by(PoolMembership.stock_id)
        .order_by(PoolMembership.stock_id)
        .all()
    )
    selected_stock_ids = set(active_stock_ids)
    for stock_id, membership_id in membership_rows:
        if stock_id in selected_stock_ids:
            continue
        selected_stock_ids.add(stock_id)
        desired.append(
            _DesiredAction(
                logical_key=f"candidate-stock:{stock_id}",
                action_family="candidate_discovery",
                subject_type="stock",
                subject_key=str(stock_id),
                source_version=f"watchlist-membership:{membership_id}",
                matched_rule="watchlist_without_case",
                tier=5,
                within_tier=stock_id,
                reason="This Watchlist company has no active research case or recorded decision cycle.",
                target_case_id=None,
                stock_id=stock_id,
                evidence={"membership_id": membership_id},
            )
        )

    latest_quarter = session.query(func.max(OraclesLensSignal.report_quarter)).filter(
        OraclesLensSignal.score_version == SCORE_VERSION
    ).scalar()
    if latest_quarter:
        score_column = (
            OraclesLensSignal.distinctive_consensus_score
            if lens == "distinctive"
            else OraclesLensSignal.signal_weighted_consensus_score
        )
        signals = (
            session.query(OraclesLensSignal)
            .filter(
                OraclesLensSignal.report_quarter == latest_quarter,
                OraclesLensSignal.score_version == SCORE_VERSION,
                score_column.isnot(None),
            )
            .order_by(score_column.desc().nullslast(), OraclesLensSignal.stock_id)
            .limit(lens_limit)
            .all()
        )
        for lens_rank, signal in enumerate(signals, start=1):
            if signal.stock_id in selected_stock_ids:
                continue
            selected_stock_ids.add(signal.stock_id)
            score = (
                signal.distinctive_consensus_score
                if lens == "distinctive"
                else signal.signal_weighted_consensus_score
            )
            desired.append(
                _DesiredAction(
                    logical_key=f"candidate-stock:{signal.stock_id}",
                    action_family="candidate_discovery",
                    subject_type="stock",
                    subject_key=str(signal.stock_id),
                    source_version=f"{latest_quarter}:{SCORE_VERSION}:{lens}",
                    matched_rule=f"oracles_lens_{lens}_candidate",
                    tier=6,
                    within_tier=lens_rank,
                    reason=(
                        f"This company ranks #{lens_rank} in the selected {lens} lens; "
                        "treat the filing-derived score as a research prompt, not a recommendation."
                    ),
                    target_case_id=None,
                    stock_id=signal.stock_id,
                    evidence={
                        "signal_id": signal.id,
                        "report_quarter": signal.report_quarter,
                        "score_version": signal.score_version,
                        "lens": lens,
                        "score": str(Decimal(score)) if score is not None else None,
                        "caution_flag_codes": signal.caution_flag_codes or [],
                    },
                )
            )
    return sorted(
        desired,
        key=lambda item: (item.tier, item.within_tier, item.logical_key, item.source_version),
    )


def _append_event(
    session: Session,
    *,
    action: ResearchInboxAction,
    event_type: str,
    actor_user_id: int | None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        ResearchInboxActionEvent(
            action_id=action.id,
            user_id=action.user_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            payload_json=payload,
        )
    )


def regenerate_inbox(
    session: Session,
    *,
    user_id: int,
    as_of: date,
    lens: str = "consensus",
    lens_limit: int = 30,
) -> dict[str, Any]:
    if lens not in {"consensus", "distinctive"}:
        raise ResearchInboxError("invalid_lens", "Lens must be consensus or distinctive.")
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"research-inbox:{user_id}:{INBOX_PRIORITY_POLICY_VERSION}"},
    )
    now = datetime.now(timezone.utc)
    desired = _desired_actions(
        session,
        user_id=user_id,
        as_of=as_of,
        lens=lens,
        lens_limit=lens_limit,
    )
    desired_keys = {(item.logical_key, item.source_version) for item in desired}
    created_count = 0
    updated_count = 0
    for item in desired:
        action = (
            session.query(ResearchInboxAction)
            .filter_by(
                user_id=user_id,
                logical_key=item.logical_key,
                source_version=item.source_version,
            )
            .one_or_none()
        )
        if action is None:
            prior = (
                session.query(ResearchInboxAction)
                .filter(
                    ResearchInboxAction.user_id == user_id,
                    ResearchInboxAction.logical_key == item.logical_key,
                    ResearchInboxAction.source_version != item.source_version,
                    ResearchInboxAction.state != "superseded",
                )
                .order_by(ResearchInboxAction.created_at.desc(), ResearchInboxAction.id.desc())
                .first()
            )
            if prior is not None:
                prior.state = "superseded"
                prior.snoozed_until = None
                _append_event(
                    session,
                    action=prior,
                    event_type="superseded",
                    actor_user_id=None,
                    payload={"new_source_version": item.source_version},
                )
            action = ResearchInboxAction(
                user_id=user_id,
                logical_key=item.logical_key,
                action_family=item.action_family,
                subject_type=item.subject_type,
                subject_key=item.subject_key,
                source_version=item.source_version,
                supersedes_action_id=prior.id if prior else None,
                priority_policy_version=INBOX_PRIORITY_POLICY_VERSION,
                matched_rule=item.matched_rule,
                priority_rank=item.priority_rank,
                rank_components={"tier": item.tier, "within_tier": item.within_tier},
                reason=item.reason,
                state="open",
                target_case_id=item.target_case_id,
                stock_id=item.stock_id,
                evidence_json=item.evidence,
                first_observed_at=now,
                last_observed_at=now,
            )
            session.add(action)
            session.flush()
            _append_event(
                session,
                action=action,
                event_type="created",
                actor_user_id=None,
                payload={"source_version": item.source_version, "matched_rule": item.matched_rule},
            )
            created_count += 1
            continue

        material_before = (
            action.matched_rule,
            action.priority_rank,
            action.reason,
            action.evidence_json,
        )
        action.matched_rule = item.matched_rule
        action.priority_rank = item.priority_rank
        action.rank_components = {"tier": item.tier, "within_tier": item.within_tier}
        action.reason = item.reason
        action.evidence_json = item.evidence
        action.last_observed_at = now
        if action.state == "snoozed" and action.snoozed_until and action.snoozed_until < as_of:
            action.state = "open"
            action.snoozed_until = None
            _append_event(
                session,
                action=action,
                event_type="snooze_expired",
                actor_user_id=None,
                payload={"as_of": as_of.isoformat()},
            )
        material_after = (
            action.matched_rule,
            action.priority_rank,
            action.reason,
            action.evidence_json,
        )
        if material_before != material_after:
            _append_event(
                session,
                action=action,
                event_type="materially_updated",
                actor_user_id=None,
                payload={"source_version": item.source_version},
            )
            updated_count += 1

    stale = (
        session.query(ResearchInboxAction)
        .filter(
            ResearchInboxAction.user_id == user_id,
            ResearchInboxAction.priority_policy_version == INBOX_PRIORITY_POLICY_VERSION,
            ResearchInboxAction.state.in_(["open", "snoozed"]),
        )
        .all()
    )
    for action in stale:
        if (action.logical_key, action.source_version) in desired_keys:
            continue
        action.state = "completed"
        action.snoozed_until = None
        _append_event(
            session,
            action=action,
            event_type="auto_completed",
            actor_user_id=None,
            payload={"as_of": as_of.isoformat()},
        )
        updated_count += 1
    session.commit()
    return {
        "priority_policy_version": INBOX_PRIORITY_POLICY_VERSION,
        "as_of": as_of.isoformat(),
        "lens": lens,
        "desired_count": len(desired),
        "created_count": created_count,
        "updated_count": updated_count,
    }


def _owned_action(
    session: Session, *, user_id: int, action_id: int, for_update: bool = True
) -> ResearchInboxAction:
    query = session.query(ResearchInboxAction).filter(
        ResearchInboxAction.id == action_id,
        ResearchInboxAction.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update()
    action = query.one_or_none()
    if action is None:
        raise ResearchInboxError("action_not_found", "Inbox action not found.", status_code=404)
    return action


def snooze_action(
    session: Session,
    *,
    user_id: int,
    action_id: int,
    snoozed_until: date,
    today: date | None = None,
) -> ResearchInboxAction:
    action = _owned_action(session, user_id=user_id, action_id=action_id)
    base = today or date.today()
    if snoozed_until <= base or snoozed_until > base + timedelta(days=MAX_SNOOZE_DAYS):
        raise ResearchInboxError(
            "invalid_snooze_window",
            "Snooze must be a future calendar date no more than 30 days away.",
        )
    if action.state not in {"open", "snoozed"}:
        raise ResearchInboxError("invalid_action_state", "Only an open action can be snoozed.")
    action.state = "snoozed"
    action.snoozed_until = snoozed_until
    _append_event(
        session,
        action=action,
        event_type="snoozed",
        actor_user_id=user_id,
        payload={"snoozed_until": snoozed_until.isoformat()},
    )
    session.commit()
    return action


def dismiss_action(session: Session, *, user_id: int, action_id: int) -> ResearchInboxAction:
    action = _owned_action(session, user_id=user_id, action_id=action_id)
    if action.action_family not in INFORMATIONAL_FAMILIES:
        raise ResearchInboxError(
            "dismissal_not_permitted",
            "Monitoring and active research obligations cannot be permanently dismissed.",
        )
    if action.state not in {"open", "snoozed"}:
        raise ResearchInboxError("invalid_action_state", "Only an active action can be dismissed.")
    action.state = "dismissed"
    action.snoozed_until = None
    _append_event(
        session, action=action, event_type="dismissed", actor_user_id=user_id
    )
    session.commit()
    return action


def complete_action(session: Session, *, user_id: int, action_id: int) -> ResearchInboxAction:
    action = _owned_action(session, user_id=user_id, action_id=action_id)
    if action.state not in {"open", "snoozed"}:
        raise ResearchInboxError("invalid_action_state", "Only an active action can be completed.")
    action.state = "completed"
    action.snoozed_until = None
    _append_event(
        session, action=action, event_type="completed", actor_user_id=user_id
    )
    session.commit()
    return action


def serialize_action(action: ResearchInboxAction, stock: Stock | None) -> dict[str, Any]:
    return {
        "id": action.id,
        "logical_key": action.logical_key,
        "action_family": action.action_family,
        "subject_type": action.subject_type,
        "subject_key": action.subject_key,
        "source_version": action.source_version,
        "supersedes_action_id": action.supersedes_action_id,
        "priority_policy_version": action.priority_policy_version,
        "matched_rule": action.matched_rule,
        "priority_rank": action.priority_rank,
        "rank_components": action.rank_components or {},
        "reason": action.reason,
        "state": action.state,
        "snoozed_until": action.snoozed_until.isoformat() if action.snoozed_until else None,
        "target_case_id": action.target_case_id,
        "stock_id": action.stock_id,
        "ticker": stock.ticker if stock else None,
        "company_name": stock.company_name if stock else None,
        "evidence": action.evidence_json or {},
        "first_observed_at": action.first_observed_at.isoformat(),
        "last_observed_at": action.last_observed_at.isoformat(),
    }
