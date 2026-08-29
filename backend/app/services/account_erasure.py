"""One-transaction account erasure with minimal append-only integrity markers."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import null, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.api_security import ApiRateLimitEvent
from app.models.artifacts import DocumentPage, PdfDocument
from app.models.auth_tokens import RefreshToken
from app.models.coverage import ResearchCoverageRequirement
from app.models.facts import CalculatedRun, Formula, MetricFact, ScreeningRule
from app.models.extractions import MetricExtraction
from app.models.notifications import (
    LogicalNotification,
    ManagerFollow,
    NotificationDeliveryAttempt,
    NotificationDeliveryEvent,
    NotificationDestination,
    NotificationEmailChallenge,
    NotificationInboxState,
    NotificationPriceAlertState,
    NotificationSubscription,
)
from app.models.portfolios import ManualPortfolio, ManualPosition, PositionJournalEvent
from app.models.research import (
    ResearchCase,
    ResearchCaseEvent,
    ResearchCaseOrigin,
    ResearchCaseRevision,
    ResearchInboxAction,
    ResearchInboxActionEvent,
)
from app.models.stocks import PoolMembership, PriceAlert, StockPool
from app.models.users import (
    AccountErasureEvent,
    AccountErasureFileDeletion,
    NotificationEvent,
    NotificationSettings,
    User,
)
from app.services.valuation import redact_published_unavailable_reason


class AccountErasureError(ValueError):
    pass


def _managed_deletion_target(storage_path: str) -> Path:
    """Resolve a deletion target without allowing escape from managed uploads."""
    root = Path(settings.UPLOAD_DIR).resolve()
    candidate = Path(storage_path)
    if candidate.is_symlink():
        raise AccountErasureError("refusing to unlink symlink storage path")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AccountErasureError(
            "refusing to unlink path outside managed upload storage"
        ) from exc
    if resolved == root:
        raise AccountErasureError("refusing to unlink managed storage root")
    return resolved


def _validate_erasure_deletion_intent(
    session: Session,
    *,
    row: AccountErasureFileDeletion,
) -> PdfDocument:
    """Re-prove the committed privacy tombstone before touching the filesystem."""
    document = (
        session.query(PdfDocument)
        .filter(
            PdfDocument.id == row.document_id,
            PdfDocument.user_id == row.user_id,
        )
        .with_for_update()
        .one_or_none()
    )
    expected_tombstone = f"erased/document/{row.document_id}"
    expected_file_name = f"erased-document-{row.document_id}"
    valid_document = (
        document is not None
        and document.lifecycle_state == "erased"
        and document.retirement_reason == "account_erasure"
        and document.retired_by_user_id == row.user_id
        and document.retired_at is not None
        and document.file_storage_key == expected_tombstone
        and document.file_name == expected_file_name
        and document.source == "account_erasure_tombstone"
        and document.raw_text is None
        and document.notes is None
    )
    has_event = (
        session.query(AccountErasureEvent.id)
        .filter(AccountErasureEvent.user_id == row.user_id)
        .first()
        is not None
    )
    has_page_content = (
        session.query(DocumentPage.id)
        .filter(
            DocumentPage.document_id == row.document_id,
            (DocumentPage.page_text.is_not(None))
            | (DocumentPage.page_image_key.is_not(None)),
        )
        .first()
        is not None
    )
    has_extraction_content = (
        session.query(MetricExtraction.id)
        .filter(
            MetricExtraction.document_id == row.document_id,
            (MetricExtraction.raw_value_text.is_not(None))
            | (MetricExtraction.original_text_snippet.is_not(None))
            | (MetricExtraction.parsed_value_json.is_not(None))
            | (MetricExtraction.bbox_json.is_not(None))
            | (MetricExtraction.canonical_projections_json != []),
        )
        .first()
        is not None
    )
    has_current_fact = (
        session.query(MetricFact.id)
        .filter(
            MetricFact.source_document_id == row.document_id,
            MetricFact.is_current.is_(True),
        )
        .first()
        is not None
    )
    expected_hash = hashlib.sha256(row.storage_path.encode("utf-8")).hexdigest()
    if (
        not valid_document
        or not has_event
        or has_page_content
        or has_extraction_content
        or has_current_fact
        or not secrets.compare_digest(row.storage_path_hash, expected_hash)
    ):
        raise AccountErasureError(
            "file deletion requires a verified, completely redacted account-erasure tombstone"
        )
    return document


def process_pending_account_erasure_file_deletions(
    session: Session,
    *,
    user_id: int | None = None,
    limit: int = 100,
) -> dict[str, int]:
    """Retry durable post-commit file deletions without reopening evidence."""
    query = session.query(AccountErasureFileDeletion).filter(
        AccountErasureFileDeletion.status.in_(["pending", "failed", "retained_shared"])
    )
    if user_id is not None:
        query = query.filter(AccountErasureFileDeletion.user_id == user_id)
    rows = (
        query.order_by(AccountErasureFileDeletion.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .all()
    )
    deleted = 0
    failed = 0
    retained_shared = 0
    for row in rows:
        row.attempt_count += 1
        try:
            path = _managed_deletion_target(row.storage_path)
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"document-storage:{path}"},
            )
            _validate_erasure_deletion_intent(session, row=row)
            candidate_documents = (
                session.query(PdfDocument)
                .filter(
                    PdfDocument.id != row.document_id,
                    PdfDocument.lifecycle_state != "erased",
                )
                .order_by(PdfDocument.id)
                .with_for_update()
                .all()
            )
            shared_reference = False
            for candidate in candidate_documents:
                try:
                    candidate_path = _managed_deletion_target(
                        candidate.file_storage_key
                    )
                except AccountErasureError:
                    continue
                if candidate_path == path:
                    shared_reference = True
                    break
            if shared_reference:
                row.status = "retained_shared"
                row.last_error_class = None
                retained_shared += 1
                continue
            if path.exists() and not path.is_file():
                raise AccountErasureError("storage path is not a regular file")
            path.unlink(missing_ok=True)
            row.status = "deleted"
            row.storage_path = "[deleted]"
            row.deleted_at = datetime.now(timezone.utc)
            row.last_error_class = None
            deleted += 1
        except (OSError, AccountErasureError) as exc:
            row.status = "failed"
            row.last_error_class = type(exc).__name__
            failed += 1
    session.commit()
    return {
        "file_deletions_deleted": deleted,
        "file_deletions_failed": failed,
        "file_deletions_retained_shared": retained_shared,
    }


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
    for case in cases:
        digest.update(
            json.dumps(
                {
                    "state": case.state,
                    "decision": case.decision,
                    "next_review_on": case.next_review_on,
                    "void_reason": case.void_reason,
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        )
        case.state = "voided"
        case.decision = None
        case.next_review_on = None
        case.void_reason = "[redacted]"
        case.closed_at = case.closed_at or now
        case.version += 1
    case_ids = [case.id for case in cases]

    origins = (
        session.query(ResearchCaseOrigin)
        .filter(ResearchCaseOrigin.case_id.in_(case_ids or [-1]))
        .all()
    )
    for origin in origins:
        digest.update(
            json.dumps(
                {
                    "origin_key": origin.origin_key,
                    "source_ref_json": origin.source_ref_json,
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        )
        origin.origin_key = f"[redacted:{origin.id}]"
        origin.source_ref_json = {"privacy_erased": True}

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
            json.dumps(
                {
                    **authored,
                    "valuation_low": revision.valuation_low,
                    "valuation_base": revision.valuation_base,
                    "valuation_high": revision.valuation_high,
                    "valuation_currency": revision.valuation_currency,
                    "valuation_as_of_date": revision.valuation_as_of_date,
                    "decision": revision.decision,
                    "next_review_on": revision.next_review_on,
                    "is_qualified_decision": revision.is_qualified_decision,
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        )
        if not revision.is_redacted:
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
            redacted_revisions += 1

        # A normal revision redaction deliberately preserves the authored
        # decision/valuation snapshot. Account erasure has a stronger contract:
        # these remaining user-authored fields must be cleared even when the
        # revision was already redacted. Preserve its original redaction audit
        # metadata and do not emit a duplicate publication-redaction event.
        revision.valuation_low = None
        revision.valuation_base = None
        revision.valuation_high = None
        revision.valuation_currency = None
        revision.valuation_as_of_date = None
        revision.decision = None
        revision.next_review_on = None
        revision.is_qualified_decision = False

    # Case event identity is retained, but event payloads can contain prior
    # decisions, reasons, and user prose. The one account-erasure event below
    # is the surviving content hash/summary required by the PRD.
    case_event_count = (
        session.query(ResearchCaseEvent)
        .filter(ResearchCaseEvent.case_id.in_(case_ids or [-1]))
        .update(
            {ResearchCaseEvent.payload_json: {"privacy_erased": True}},
            synchronize_session=False,
        )
    )

    inbox_actions = (
        session.query(ResearchInboxAction)
        .filter_by(user_id=user.id)
        .order_by(ResearchInboxAction.id)
        .all()
    )
    for action in inbox_actions:
        digest.update(
            json.dumps(
                {
                    "reason": action.reason,
                    "rank_components": action.rank_components,
                    "evidence": action.evidence_json,
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        )
        action.reason = "[redacted]"
        action.rank_components = null()
        action.evidence_json = {"privacy_erased": True}
        action.state = "dismissed"
        action.snoozed_until = None
        action.target_case_id = None
        action.stock_id = None
    # Execute a set-based tombstone as the authoritative write. This also
    # covers rows that may have been loaded earlier in a no-autoflush session.
    session.query(ResearchInboxAction).filter_by(user_id=user.id).update(
        {
            ResearchInboxAction.reason: "[redacted]",
            ResearchInboxAction.rank_components: null(),
            ResearchInboxAction.evidence_json: {"privacy_erased": True},
            ResearchInboxAction.state: "dismissed",
            ResearchInboxAction.snoozed_until: None,
            ResearchInboxAction.target_case_id: None,
            ResearchInboxAction.stock_id: None,
        },
        synchronize_session=False,
    )
    inbox_event_count = (
        session.query(ResearchInboxActionEvent)
        .filter_by(user_id=user.id)
        .update(
            {ResearchInboxActionEvent.payload_json: {"privacy_erased": True}},
            synchronize_session=False,
        )
    )
    coverage_deleted = (
        session.query(ResearchCoverageRequirement)
        .filter_by(user_id=user.id)
        .delete(synchronize_session=False)
    )

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

    notification_ids = [
        row.id
        for row in session.query(LogicalNotification.id)
        .filter(LogicalNotification.user_id == user.id)
        .all()
    ]
    attempt_ids = [
        row.id
        for row in session.query(NotificationDeliveryAttempt.id)
        .filter(NotificationDeliveryAttempt.logical_notification_id.in_(notification_ids or [-1]))
        .all()
    ]
    delivery_event_count = (
        session.query(NotificationDeliveryEvent)
        .filter(NotificationDeliveryEvent.attempt_id.in_(attempt_ids or [-1]))
        .update(
            {
                NotificationDeliveryEvent.response_class: "account_erasure",
                NotificationDeliveryEvent.payload_json: {"privacy_erased": True},
            },
            synchronize_session=False,
        )
    )
    inbox_state_deleted = (
        session.query(NotificationInboxState)
        .filter_by(user_id=user.id)
        .delete(synchronize_session=False)
    )
    price_alert_state_deleted = (
        session.query(NotificationPriceAlertState)
        .filter_by(user_id=user.id)
        .delete(synchronize_session=False)
    )
    logical_notification_count = 0
    for notification in (
        session.query(LogicalNotification)
        .filter_by(user_id=user.id)
        .order_by(LogicalNotification.id)
        .all()
    ):
        digest.update(
            json.dumps(
                {
                    "title": notification.title,
                    "body": notification.body,
                    "evidence_route": notification.evidence_route,
                    "payload": notification.payload_json,
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        )
        notification.title = "[redacted]"
        notification.body = "[redacted]"
        notification.evidence_route = "[redacted]"
        notification.payload_json = {"privacy_erased": True}
        notification.case_id = None
        notification.stock_id = None
        notification.manager_id = None
        logical_notification_count += 1
    legacy_notification_count = (
        session.query(NotificationEvent)
        .filter_by(user_id=user.id)
        .update(
            {NotificationEvent.payload_json: {"privacy_erased": True}},
            synchronize_session=False,
        )
    )

    destinations = session.query(NotificationDestination).filter_by(user_id=user.id).all()
    destination_ids = [row.id for row in destinations]
    for row in destinations:
        row.status = "revoked"
        row.label = "[revoked]"
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
        session.delete(settings_row)

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

    # User-created rules, lists, alerts, formulas, run results and manual facts
    # are content rather than shared financial lineage. Purge them in dependency
    # order under the audited exception. Parsed facts remain only as inaccessible
    # document lineage and are demoted below; shared SEC facts have user_id NULL.
    price_alerts_deleted = (
        session.query(PriceAlert).filter_by(user_id=user.id).delete(synchronize_session=False)
    )
    pool_memberships_deleted = (
        session.query(PoolMembership)
        .filter_by(user_id=user.id)
        .delete(synchronize_session=False)
    )
    stock_pools_deleted = (
        session.query(StockPool).filter_by(user_id=user.id).delete(synchronize_session=False)
    )
    screening_rules_deleted = (
        session.query(ScreeningRule)
        .filter_by(user_id=user.id)
        .delete(synchronize_session=False)
    )
    notification_price_alerts_deleted = price_alert_state_deleted
    user_fact_ids = [
        row.id
        for row in session.query(MetricFact.id)
        .filter(
            MetricFact.user_id == user.id,
            MetricFact.source_type.in_(["manual", "calculated"]),
        )
        .all()
    ]
    user_facts_deleted = (
        session.query(MetricFact)
        .filter(MetricFact.id.in_(user_fact_ids or [-1]))
        .delete(synchronize_session=False)
    )
    calculated_runs_deleted = (
        session.query(CalculatedRun)
        .filter_by(user_id=user.id)
        .delete(synchronize_session=False)
    )
    formulas_deleted = (
        session.query(Formula).filter_by(user_id=user.id).delete(synchronize_session=False)
    )

    # Canonical archive/backfill takes the same row lock before changing a
    # storage key. The winner commits first and the waiter observes its final
    # lifecycle/path, preventing stale deletion intents or tombstone updates.
    documents = (
        session.query(PdfDocument)
        .filter_by(user_id=user.id)
        .order_by(PdfDocument.id)
        .with_for_update()
        .all()
    )
    document_ids = [document.id for document in documents]
    for document in documents:
        digest.update(
            json.dumps(
                {
                    "document_id": document.id,
                    "file_name": document.file_name,
                    "storage_key": document.file_storage_key,
                    "raw_text": document.raw_text,
                    "notes": document.notes,
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        )
        storage_path = document.file_storage_key
        session.add(
            AccountErasureFileDeletion(
                user_id=user.id,
                document_id=document.id,
                storage_path=storage_path,
                storage_path_hash=hashlib.sha256(
                    storage_path.encode("utf-8")
                ).hexdigest(),
                status="pending",
            )
        )
        document.lifecycle_state = "erased"
        document.retired_at = now
        document.retired_by_user_id = user.id
        document.retirement_reason = "account_erasure"
        document.file_storage_key = f"erased/document/{document.id}"
        document.file_name = f"erased-document-{document.id}"
        document.source = "account_erasure_tombstone"
        document.raw_text = None
        document.notes = None

    if document_ids:
        pages = session.query(DocumentPage).filter(
            DocumentPage.document_id.in_(document_ids)
        ).all()
        for page in pages:
            page.page_text = None
            page.page_image_key = None
        extractions = session.query(MetricExtraction).filter(
            MetricExtraction.document_id.in_(document_ids)
        ).all()
        for extraction in extractions:
            extraction.raw_value_text = None
            extraction.original_text_snippet = None
            # SQLAlchemy JSON encodes Python None as a JSON `null` value by
            # default. Account erasure requires physical SQL NULL so no
            # content-bearing JSON value remains at rest.
            extraction.parsed_value_json = null()
            extraction.bbox_json = null()
            extraction.canonical_projections_json = []
        session.query(MetricFact).filter(
            MetricFact.source_document_id.in_(document_ids),
            MetricFact.is_current.is_(True),
        ).update({MetricFact.is_current: False}, synchronize_session=False)

    user.email = f"erased-{user.id}@deleted.invalid"
    user.hashed_password = hash_password(secrets.token_urlsafe(32))
    user.is_active = False
    summary = {
        "redacted_revisions": redacted_revisions,
        "portfolios_tombstoned": len(portfolios),
        "positions_tombstoned": len(positions),
        "journal_events_tombstoned": journal_count,
        "case_events_tombstoned": case_event_count,
        "research_inbox_actions_tombstoned": len(inbox_actions),
        "research_inbox_events_tombstoned": inbox_event_count,
        "coverage_requirements_purged": coverage_deleted,
        "logical_notifications_tombstoned": logical_notification_count,
        "notification_delivery_events_tombstoned": delivery_event_count,
        "notification_inbox_states_purged": inbox_state_deleted,
        "notification_price_alert_states_purged": notification_price_alerts_deleted,
        "legacy_notification_events_tombstoned": legacy_notification_count,
        "price_alerts_purged": price_alerts_deleted,
        "pool_memberships_purged": pool_memberships_deleted,
        "stock_pools_purged": stock_pools_deleted,
        "screening_rules_purged": screening_rules_deleted,
        "user_metric_facts_purged": user_facts_deleted,
        "calculated_runs_purged": calculated_runs_deleted,
        "formulas_purged": formulas_deleted,
        "destinations_revoked": len(destinations),
        "refresh_tokens_revoked": revoked_tokens,
        "documents_tombstoned": len(documents),
        "file_deletions_queued": len(documents),
    }
    audit = AccountErasureEvent(
        user_id=user.id,
        content_hash=digest.hexdigest(),
        summary_json=summary,
    )
    # Apply every content mutation before the durable completion marker exists.
    # This makes the marker the final write in the privacy transaction instead
    # of relying on SQLAlchemy's dependency-based flush order.
    session.flush()
    session.add(audit)
    session.flush()
    session.execute(
        text(
            "SET CONSTRAINTS "
            "trg_account_erasure_events_complete, "
            "trg_account_erasure_events_user_graph_complete IMMEDIATE"
        )
    )
    session.commit()
    # Production commit ends the transaction-local setting. Pytest wraps each
    # test in an outer transaction, so reset explicitly as well; this also makes
    # the post-commit file-deletion worker independent of the erasure bypass.
    session.execute(text("SELECT set_config('valuepilot.account_erasure', 'off', true)"))
    session.execute(
        text(
            "SET CONSTRAINTS "
            "trg_account_erasure_events_complete, "
            "trg_account_erasure_events_user_graph_complete DEFERRED"
        )
    )
    session.commit()
    deletion_summary = process_pending_account_erasure_file_deletions(
        session,
        user_id=user.id,
    )
    return {"status": "erased", **summary, **deletion_summary}
