"""Require a same-transaction erasure event for every GUC bypass.

Revision ID: 20260828500000
Revises: 20260828490000
Create Date: 2026-08-30 01:00:00
"""

from alembic import op


revision = "20260828500000"
down_revision = "20260828490000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION current_transaction_has_account_erasure(
            target_user_id bigint
        )
        RETURNS boolean
        LANGUAGE sql
        STABLE
        AS $$
            SELECT target_user_id IS NOT NULL AND EXISTS (
                SELECT 1
                  FROM account_erasure_events event
                 WHERE event.user_id = target_user_id
                   AND event.created_txid = txid_current()
            )
        $$;

        -- The shared append-only function is also used by a public 13F review
        -- table. The privacy bypass is deliberately limited to user-authored
        -- histories that erase_account actually tombstones.
        CREATE OR REPLACE FUNCTION reject_research_append_only_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND current_setting('valuepilot.account_erasure', true) = 'on'
               AND TG_TABLE_NAME = ANY (ARRAY[
                    'research_case_origins',
                    'research_case_events',
                    'research_inbox_action_events',
                    'logical_notifications',
                    'notification_delivery_events',
                    'position_journal_events'
               ]) THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION '% is append-only; % is forbidden',
                TG_TABLE_NAME, TG_OP;
        END;
        $$;

        CREATE FUNCTION validate_append_only_account_erasure_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            target_user_id bigint;
            prior_user_id bigint;
        BEGIN
            IF TG_TABLE_NAME IN (
                'research_inbox_action_events',
                'logical_notifications',
                'position_journal_events'
            ) THEN
                target_user_id := NULLIF(to_jsonb(NEW)->>'user_id', '')::bigint;
                prior_user_id := NULLIF(to_jsonb(OLD)->>'user_id', '')::bigint;
            ELSIF TG_TABLE_NAME IN (
                'research_case_origins', 'research_case_events'
            ) THEN
                IF NEW.case_id IS DISTINCT FROM OLD.case_id THEN
                    RAISE EXCEPTION 'account erasure cannot move research history'
                        USING ERRCODE = '23514';
                END IF;
                SELECT user_id INTO target_user_id
                  FROM research_cases WHERE id = NEW.case_id;
                prior_user_id := target_user_id;
            ELSIF TG_TABLE_NAME = 'notification_delivery_events' THEN
                IF NEW.attempt_id IS DISTINCT FROM OLD.attempt_id THEN
                    RAISE EXCEPTION 'account erasure cannot move delivery history'
                        USING ERRCODE = '23514';
                END IF;
                SELECT notification.user_id INTO target_user_id
                  FROM notification_delivery_attempts attempt
                  JOIN logical_notifications notification
                    ON notification.id = attempt.logical_notification_id
                 WHERE attempt.id = NEW.attempt_id;
                prior_user_id := target_user_id;
            ELSE
                RAISE EXCEPTION 'unsupported account-erasure history table: %',
                    TG_TABLE_NAME USING ERRCODE = '23514';
            END IF;

            IF target_user_id IS DISTINCT FROM prior_user_id
               OR NOT current_transaction_has_account_erasure(target_user_id) THEN
                RAISE EXCEPTION
                    'immutable history mutation requires atomic audited account erasure'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE FUNCTION validate_research_revision_erasure_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            target_user_id bigint;
        BEGIN
            -- Preserve the pre-existing narrow, one-time ordinary redaction.
            IF OLD.is_redacted = false
               AND NEW.is_redacted = true
               AND (to_jsonb(NEW) - ARRAY[
                    'thesis', 'variant_view', 'decision_reason',
                    'assumptions_json', 'risks_json', 'evidence_json',
                    'valuation_unavailable_reason', 'is_redacted',
                    'redaction_content_hash', 'redaction_reason',
                    'redacted_by_user_id', 'redacted_at'
                  ]) IS NOT DISTINCT FROM
                  (to_jsonb(OLD) - ARRAY[
                    'thesis', 'variant_view', 'decision_reason',
                    'assumptions_json', 'risks_json', 'evidence_json',
                    'valuation_unavailable_reason', 'is_redacted',
                    'redaction_content_hash', 'redaction_reason',
                    'redacted_by_user_id', 'redacted_at'
                  ]) THEN
                RETURN NULL;
            END IF;

            SELECT user_id INTO target_user_id
              FROM research_cases WHERE id = NEW.case_id;
            IF NEW.case_id IS DISTINCT FROM OLD.case_id
               OR NOT current_transaction_has_account_erasure(target_user_id) THEN
                RAISE EXCEPTION
                    'research revision mutation requires atomic audited account erasure'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE FUNCTION validate_formula_run_erasure_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT current_transaction_has_account_erasure(OLD.user_id) THEN
                RAISE EXCEPTION
                    'formula run deletion requires atomic audited account erasure'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE FUNCTION validate_calculated_fact_erasure_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.source_type = 'calculated'
               AND OLD.user_id IS NOT NULL
               AND NOT current_transaction_has_account_erasure(OLD.user_id) THEN
                RAISE EXCEPTION
                    'calculated fact deletion requires atomic audited account erasure'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_research_case_origins_erasure_proof
        AFTER UPDATE ON research_case_origins
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_append_only_account_erasure_mutation();
        CREATE CONSTRAINT TRIGGER trg_research_case_events_erasure_proof
        AFTER UPDATE ON research_case_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_append_only_account_erasure_mutation();
        CREATE CONSTRAINT TRIGGER trg_research_inbox_action_events_erasure_proof
        AFTER UPDATE ON research_inbox_action_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_append_only_account_erasure_mutation();
        CREATE CONSTRAINT TRIGGER trg_logical_notifications_erasure_proof
        AFTER UPDATE ON logical_notifications
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_append_only_account_erasure_mutation();
        CREATE CONSTRAINT TRIGGER trg_notification_delivery_events_erasure_proof
        AFTER UPDATE ON notification_delivery_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_append_only_account_erasure_mutation();
        CREATE CONSTRAINT TRIGGER trg_position_journal_events_erasure_proof
        AFTER UPDATE ON position_journal_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_append_only_account_erasure_mutation();
        CREATE CONSTRAINT TRIGGER trg_research_case_revisions_erasure_proof
        AFTER UPDATE ON research_case_revisions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_research_revision_erasure_mutation();
        CREATE CONSTRAINT TRIGGER trg_calculated_runs_erasure_delete_proof
        AFTER DELETE ON calculated_runs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_formula_run_erasure_delete();
        CREATE CONSTRAINT TRIGGER trg_metric_facts_calculated_erasure_delete_proof
        AFTER DELETE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_calculated_fact_erasure_delete();
        """
    )


def downgrade() -> None:
    # This remediation adds no columns and is intentionally sticky: removing
    # its proof triggers would reopen an integrity bypass on retained history.
    pass
