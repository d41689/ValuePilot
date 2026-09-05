"""One-transaction account erasure with minimal append-only integrity markers."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timezone

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.api_security import ApiRateLimitEvent
from app.models.auth_tokens import RefreshToken
from app.models.facts import MetricFact
from app.models.notifications import (
    ManagerFollow,
    NotificationDeliveryAttempt,
    NotificationDestination,
    NotificationEmailChallenge,
    NotificationSubscription,
)
from app.models.portfolios import ManualPortfolio, ManualPosition, PositionJournalEvent
from app.models.research import ResearchCase, ResearchCaseEvent, ResearchCaseRevision
from app.models.users import AccountErasureEvent, NotificationSettings, User
from app.services.valuation import redact_published_unavailable_reason


class AccountErasureError(ValueError):
    pass


def erase_account(
    session: Session,
    *,
    user: User,
    password: str,
) -> dict[str, int | str]:
    if not verify_password(password, user.hashed_password):
        raise AccountErasureError("Password verification failed.")
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"account-erasure:{user.id}"},
    )
    if session.query(AccountErasureEvent).filter_by(user_id=user.id).first():
        raise AccountErasureError("Account erasure was already completed.")

    # This transaction-local setting permits UPDATE (never DELETE) through the
    # append-only journal trigger solely for the audited privacy tombstone.
    session.execute(text("SELECT set_config('valuepilot.account_erasure', 'on', true)"))
    now = datetime.now(timezone.utc)
    today = now.date()
    digest = hashlib.sha256()

    cases = session.query(ResearchCase).filter_by(user_id=user.id).all()
    case_ids = [case.id for case in cases]
    revisions = (
        session.query(ResearchCaseRevision)
        .filter(ResearchCaseRevision.case_id.in_(case_ids or [-1]))
        .order_by(ResearchCaseRevision.id)
        .all()
    )
    redacted_revisions = 0
    for revision in revisions:
        authored = {
            "thesis": revision.thesis,
            "variant_view": revision.variant_view,
            "decision_reason": revision.decision_reason,
            "assumptions": revision.assumptions_json,
            "risks": revision.risks_json,
            "evidence": revision.evidence_json,
            "valuation_unavailable_reason": revision.valuation_unavailable_reason,
        }
        digest.update(
            json.dumps(authored, sort_keys=True, default=str).encode("utf-8")
        )
        if revision.is_redacted:
            continue
        content_hash = hashlib.sha256(
            json.dumps(authored, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        revision.thesis = "[redacted]"
        revision.variant_view = "[redacted]" if revision.variant_view else None
        revision.decision_reason = "[redacted]" if revision.decision_reason else None
        revision.assumptions_json = []
        revision.risks_json = []
        revision.evidence_json = []
        revision.valuation_unavailable_reason = (
            "[redacted]" if revision.valuation_unavailable_reason else None
        )
        revision.is_redacted = True
        revision.redaction_content_hash = content_hash
        revision.redaction_reason = "account_erasure"
        revision.redacted_by_user_id = user.id
        revision.redacted_at = now
        redact_published_unavailable_reason(
            session,
            user_id=user.id,
            stock_id=revision.snapshot_stock_id,
            revision_id=revision.id,
            content_hash=content_hash,
        )
        session.add(
            ResearchCaseEvent(
                case_id=revision.case_id,
                actor_user_id=user.id,
                event_type="revision_redacted",
                correlation_id=f"account-erasure-{user.id}-{revision.id}",
                payload_json={
                    "revision_id": revision.id,
                    "revision_number": revision.revision_number,
                    "content_hash": content_hash,
                    "reason": "account_erasure",
                },
            )
        )
        redacted_revisions += 1

    portfolios = session.query(ManualPortfolio).filter_by(user_id=user.id).all()
    for portfolio in portfolios:
        digest.update(
            json.dumps(
                {"name": portfolio.name, "description": portfolio.description},
                sort_keys=True,
            ).encode("utf-8")
        )
        portfolio.name = f"Erased portfolio {portfolio.id}"
        portfolio.description = None
        portfolio.status = "archived"
        portfolio.archived_at = now
        portfolio.version += 1

    positions = session.query(ManualPosition).filter_by(user_id=user.id).all()
    for position in positions:
        digest.update(
            json.dumps(
                {
                    "quantity": str(position.quantity),
                    "average_unit_cost": str(position.average_unit_cost),
                    "research_case_id": position.research_case_id,
                    "research_revision_id": position.research_revision_id,
                },
                sort_keys=True,
            ).encode("utf-8")
        )
        position.state = "closed"
        position.quantity = 0
        position.average_unit_cost = None
        position.research_case_id = None
        position.research_revision_id = None
        position.closed_on = position.closed_on or today
        position.last_reviewed_on = None
        position.version += 1

    journal_count = (
        session.query(PositionJournalEvent)
        .filter_by(user_id=user.id)
        .update(
            {
                PositionJournalEvent.prior_quantity: None,
                PositionJournalEvent.new_quantity: None,
                PositionJournalEvent.prior_average_unit_cost: None,
                PositionJournalEvent.new_average_unit_cost: None,
                PositionJournalEvent.reason: None,
                PositionJournalEvent.research_case_id: None,
                PositionJournalEvent.research_revision_id: None,
                PositionJournalEvent.payload_json: {"privacy_erased": True},
            },
            synchronize_session=False,
        )
    )

    destinations = session.query(NotificationDestination).filter_by(user_id=user.id).all()
    destination_ids = [row.id for row in destinations]
    for row in destinations:
        row.status = "revoked"
        row.secret_ciphertext = "[revoked]"
        row.key_version = "revoked"
        row.destination_hint = "[revoked]"
        row.revoked_at = now
        row.last_error_class = "account_erasure"
    if destination_ids:
        session.query(NotificationEmailChallenge).filter(
            NotificationEmailChallenge.destination_id.in_(destination_ids)
        ).update(
            {
                NotificationEmailChallenge.token_hash: hashlib.sha256(
                    secrets.token_bytes(32)
                ).hexdigest(),
                NotificationEmailChallenge.used_at: now,
                NotificationEmailChallenge.expires_at: now,
            },
            synchronize_session=False,
        )
    session.query(NotificationSubscription).filter_by(user_id=user.id).update(
        {NotificationSubscription.is_enabled: False}, synchronize_session=False
    )
    session.query(NotificationDeliveryAttempt).filter(
        NotificationDeliveryAttempt.destination_id.in_(destination_ids or [-1]),
        NotificationDeliveryAttempt.status.in_(["queued", "leased", "retry_scheduled"]),
    ).update(
        {
            NotificationDeliveryAttempt.status: "configuration_blocked",
            NotificationDeliveryAttempt.provider_response_class: "account_erasure",
            NotificationDeliveryAttempt.lease_expires_at: None,
            NotificationDeliveryAttempt.next_attempt_at: now,
        },
        synchronize_session=False,
    )
    session.query(ManagerFollow).filter_by(user_id=user.id).delete(
        synchronize_session=False
    )
    settings_row = session.query(NotificationSettings).filter_by(user_id=user.id).first()
    if settings_row is not None:
        settings_row.is_enabled = False

    revoked_tokens = (
        session.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .update(
            {
                RefreshToken.revoked_at: now,
                RefreshToken.revoked_reason: "account_erasure",
            },
            synchronize_session=False,
        )
    )
    session.query(ApiRateLimitEvent).filter_by(user_id=user.id).delete(
        synchronize_session=False
    )

    # Manual ``reason`` and ``note`` are user-authored rationale. Tombstone
    # those fields and no others: ``raw``/``value_text`` and numeric values are
    # the economic observation, while the remaining JSON is server provenance.
    manual_facts = session.query(MetricFact).filter(
        MetricFact.user_id == user.id,
        MetricFact.source_type == "manual",
    ).all()
    for fact in manual_facts:
        if not isinstance(fact.value_json, dict):
            continue
        reason = fact.value_json.get("reason")
        note = fact.value_json.get("note")
        rationale = {
            "reason": reason,
            "note": note,
        }
        redactable = {
            key: value
            for key, value in rationale.items()
            if isinstance(value, str) and value and value != "[redacted]"
        }
        if not redactable:
            continue
        redacted = dict(fact.value_json)
        for key, value in redactable.items():
            content_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
            digest.update(value.encode("utf-8"))
            redacted[key] = "[redacted]"
            redacted[
                "redaction_content_hash"
                if key == "reason"
                else "redaction_note_content_hash"
            ] = content_hash
        fact.value_json = redacted

    user.email = f"erased-{user.id}@deleted.invalid"
    user.hashed_password = hash_password(secrets.token_urlsafe(32))
    user.is_active = False
    summary = {
        "redacted_revisions": redacted_revisions,
        "portfolios_tombstoned": len(portfolios),
        "positions_tombstoned": len(positions),
        "journal_events_tombstoned": journal_count,
        "destinations_revoked": len(destinations),
        "refresh_tokens_revoked": revoked_tokens,
    }
    audit = AccountErasureEvent(
        user_id=user.id,
        content_hash=digest.hexdigest(),
        summary_json=summary,
    )
    session.add(audit)
    session.commit()
    return {"status": "erased", **summary}
