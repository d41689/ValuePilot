"""Reject incomplete or forged account-erasure completion events.

Revision ID: 20260828420000
Revises: 20260828410000
Create Date: 2026-08-29 18:00:00
"""

from alembic import op


revision = "20260828420000"
down_revision = "20260828410000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION validate_account_erasure_completion()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF current_setting('valuepilot.account_erasure', true)
               IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION
                    'account erasure event requires audited erasure transaction'
                    USING ERRCODE = '23514';
            END IF;

            PERFORM pg_advisory_xact_lock(
                hashtextextended('account-erasure:' || NEW.user_id::text, 0)
            );

            IF NOT EXISTS (
                SELECT 1 FROM users candidate
                 WHERE candidate.id = NEW.user_id
                   AND candidate.is_active = false
                   AND candidate.email = (
                       'erased-' || candidate.id || '@deleted.invalid'
                   )
            ) OR EXISTS (
                SELECT 1 FROM refresh_tokens token
                 WHERE token.user_id = NEW.user_id
                   AND token.revoked_at IS NULL
            ) OR EXISTS (
                SELECT 1
                  FROM research_case_revisions revision
                  JOIN research_cases research_case
                    ON research_case.id = revision.case_id
                 WHERE research_case.user_id = NEW.user_id
                   AND (
                       revision.is_redacted IS DISTINCT FROM true
                       OR revision.thesis <> '[redacted]'
                       OR revision.assumptions_json <> '[]'::jsonb
                       OR revision.risks_json <> '[]'::jsonb
                       OR revision.evidence_json <> '[]'::jsonb
                       OR revision.variant_view NOT IN ('[redacted]')
                       OR revision.decision_reason NOT IN ('[redacted]')
                       OR revision.valuation_unavailable_reason NOT IN ('[redacted]')
                   )
            ) OR EXISTS (
                SELECT 1 FROM research_cases research_case
                 WHERE research_case.user_id = NEW.user_id
                   AND research_case.void_reason IS NOT NULL
                   AND research_case.void_reason <> '[redacted]'
            ) OR EXISTS (
                SELECT 1 FROM manual_portfolios portfolio
                 WHERE portfolio.user_id = NEW.user_id
                   AND (
                       portfolio.status <> 'archived'
                       OR portfolio.name <> (
                           'Erased portfolio ' || portfolio.id
                       )
                       OR portfolio.description IS NOT NULL
                       OR portfolio.archived_at IS NULL
                   )
            ) OR EXISTS (
                SELECT 1 FROM manual_positions position
                 WHERE position.user_id = NEW.user_id
                   AND (
                       position.state <> 'closed'
                       OR position.quantity <> 0
                       OR position.average_unit_cost IS NOT NULL
                       OR position.research_case_id IS NOT NULL
                       OR position.research_revision_id IS NOT NULL
                       OR position.closed_on IS NULL
                       OR position.last_reviewed_on IS NOT NULL
                   )
            ) OR EXISTS (
                SELECT 1 FROM position_journal_events journal
                 WHERE journal.user_id = NEW.user_id
                   AND (
                       journal.prior_quantity IS NOT NULL
                       OR journal.new_quantity IS NOT NULL
                       OR journal.prior_average_unit_cost IS NOT NULL
                       OR journal.new_average_unit_cost IS NOT NULL
                       OR journal.reason IS NOT NULL
                       OR journal.research_case_id IS NOT NULL
                       OR journal.research_revision_id IS NOT NULL
                       OR journal.payload_json IS DISTINCT FROM
                          '{"privacy_erased": true}'::jsonb
                   )
            ) OR EXISTS (
                SELECT 1 FROM notification_destinations destination
                 WHERE destination.user_id = NEW.user_id
                   AND (
                       destination.status <> 'revoked'
                       OR destination.secret_ciphertext <> '[revoked]'
                       OR destination.key_version <> 'revoked'
                       OR destination.destination_hint <> '[revoked]'
                       OR destination.label <> '[revoked]'
                       OR destination.revoked_at IS NULL
                   )
            ) OR EXISTS (
                SELECT 1 FROM notification_subscriptions subscription
                 WHERE subscription.user_id = NEW.user_id
                   AND subscription.is_enabled = true
            ) OR EXISTS (
                SELECT 1
                  FROM notification_delivery_attempts attempt
                  JOIN notification_destinations destination
                    ON destination.id = attempt.destination_id
                 WHERE destination.user_id = NEW.user_id
                   AND attempt.status IN (
                       'queued', 'leased', 'retry_scheduled'
                   )
            ) OR EXISTS (
                SELECT 1 FROM manager_follows follow
                 WHERE follow.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1 FROM notification_settings setting
                 WHERE setting.user_id = NEW.user_id
                   AND setting.is_enabled = true
            ) OR EXISTS (
                SELECT 1 FROM api_rate_limit_events rate_event
                 WHERE rate_event.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1 FROM pdf_documents document
                 WHERE document.user_id = NEW.user_id
                   AND (
                       document.lifecycle_state <> 'erased'
                       OR document.retired_by_user_id IS DISTINCT FROM NEW.user_id
                       OR document.retirement_reason <> 'account_erasure'
                       OR document.file_storage_key <>
                          ('erased/document/' || document.id)
                       OR document.file_name <>
                          ('erased-document-' || document.id)
                       OR document.source <> 'account_erasure_tombstone'
                       OR document.raw_text IS NOT NULL
                       OR document.notes IS NOT NULL
                       OR NOT EXISTS (
                           SELECT 1
                             FROM account_erasure_file_deletions deletion
                            WHERE deletion.user_id = NEW.user_id
                              AND deletion.document_id = document.id
                              AND deletion.created_txid = NEW.created_txid
                       )
                   )
            ) OR EXISTS (
                SELECT 1
                  FROM document_pages page
                  JOIN pdf_documents document
                    ON document.id = page.document_id
                 WHERE document.user_id = NEW.user_id
                   AND (
                       page.page_text IS NOT NULL
                       OR page.page_image_key IS NOT NULL
                   )
            ) OR EXISTS (
                SELECT 1
                  FROM metric_extractions extraction
                  JOIN pdf_documents document
                    ON document.id = extraction.document_id
                 WHERE document.user_id = NEW.user_id
                   AND (
                       extraction.raw_value_text IS NOT NULL
                       OR extraction.original_text_snippet IS NOT NULL
                       OR extraction.parsed_value_json IS NOT NULL
                       OR extraction.bbox_json IS NOT NULL
                   )
            ) OR EXISTS (
                SELECT 1
                  FROM metric_facts fact
                  JOIN pdf_documents document
                    ON document.id = fact.source_document_id
                 WHERE document.user_id = NEW.user_id
                   AND fact.is_current = true
            ) OR EXISTS (
                SELECT 1 FROM metric_facts fact
                 WHERE fact.user_id = NEW.user_id
                   AND fact.source_type = 'manual'
                   AND fact.value_json ? 'reason'
                   AND fact.value_json->>'reason' <> '[redacted]'
            ) THEN
                RAISE EXCEPTION
                    'account erasure event requires complete privacy tombstone'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_account_erasure_events_complete
        AFTER INSERT ON account_erasure_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_account_erasure_completion();

        CREATE FUNCTION guard_erased_user_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM account_erasure_events event
                 WHERE event.user_id = OLD.id
            ) AND (
                NEW.is_active IS DISTINCT FROM false
                OR NEW.email IS DISTINCT FROM
                   ('erased-' || OLD.id || '@deleted.invalid')
            ) THEN
                RAISE EXCEPTION
                    'completed account erasure identity is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_users_erasure_identity_guard
        BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION guard_erased_user_identity();
        """
    )

    # Extend the 4100 transaction barrier to credential/configuration tables
    # that account erasure revokes or removes.
    op.execute(
        """
        CREATE TRIGGER trg_refresh_tokens_erasure_barrier
        BEFORE INSERT OR UPDATE ON refresh_tokens
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_notification_destinations_erasure_barrier
        BEFORE INSERT OR UPDATE ON notification_destinations
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_notification_subscriptions_erasure_barrier
        BEFORE INSERT OR UPDATE ON notification_subscriptions
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_manager_follows_erasure_barrier
        BEFORE INSERT OR UPDATE ON manager_follows
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_notification_settings_erasure_barrier
        BEFORE INSERT OR UPDATE ON notification_settings
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_api_rate_limit_events_erasure_barrier
        BEFORE INSERT OR UPDATE ON api_rate_limit_events
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM account_erasure_events) THEN
                RAISE EXCEPTION
                    'cannot remove account-erasure completeness guard while erasure history exists';
            END IF;
        END;
        $$;
        DROP TRIGGER IF EXISTS trg_api_rate_limit_events_erasure_barrier
            ON api_rate_limit_events;
        DROP TRIGGER IF EXISTS trg_notification_settings_erasure_barrier
            ON notification_settings;
        DROP TRIGGER IF EXISTS trg_manager_follows_erasure_barrier
            ON manager_follows;
        DROP TRIGGER IF EXISTS trg_notification_subscriptions_erasure_barrier
            ON notification_subscriptions;
        DROP TRIGGER IF EXISTS trg_notification_destinations_erasure_barrier
            ON notification_destinations;
        DROP TRIGGER IF EXISTS trg_refresh_tokens_erasure_barrier
            ON refresh_tokens;
        DROP TRIGGER IF EXISTS trg_users_erasure_identity_guard ON users;
        DROP FUNCTION IF EXISTS guard_erased_user_identity();
        DROP TRIGGER IF EXISTS trg_account_erasure_events_complete
            ON account_erasure_events;
        DROP FUNCTION IF EXISTS validate_account_erasure_completion();
        """
    )
