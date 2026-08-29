"""Cover the complete user-content graph during account erasure.

Revision ID: 20260828440000
Revises: 20260828430000
Create Date: 2026-08-29 19:00:00
"""

from alembic import op


revision = "20260828440000"
down_revision = "20260828430000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_erased_account_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_user_id bigint;
            prior_owner_id bigint;
            target_reference_id bigint;
            prior_reference_id bigint;
            erasure_txid bigint;
            account_is_active boolean;
        BEGIN
            IF TG_ARGV[0] = 'direct_user' THEN
                target_user_id := NULLIF(to_jsonb(NEW)->>'user_id', '')::bigint;
                IF TG_OP = 'UPDATE' THEN
                    prior_owner_id := NULLIF(to_jsonb(OLD)->>'user_id', '')::bigint;
                END IF;
            ELSIF TG_ARGV[0] = 'research_case' THEN
                target_reference_id := NULLIF(to_jsonb(NEW)->>'case_id', '')::bigint;
                SELECT user_id INTO target_user_id
                  FROM research_cases WHERE id = target_reference_id;
                IF TG_OP = 'UPDATE' THEN
                    prior_reference_id := NULLIF(to_jsonb(OLD)->>'case_id', '')::bigint;
                END IF;
            ELSIF TG_ARGV[0] = 'document' THEN
                target_reference_id := NULLIF(to_jsonb(NEW)->>'document_id', '')::bigint;
                SELECT user_id INTO target_user_id
                  FROM pdf_documents WHERE id = target_reference_id;
                IF TG_OP = 'UPDATE' THEN
                    prior_reference_id := NULLIF(to_jsonb(OLD)->>'document_id', '')::bigint;
                END IF;
            ELSIF TG_ARGV[0] = 'notification_destination' THEN
                target_reference_id := NULLIF(to_jsonb(NEW)->>'destination_id', '')::bigint;
                SELECT user_id INTO target_user_id
                  FROM notification_destinations WHERE id = target_reference_id;
                IF TG_OP = 'UPDATE' THEN
                    prior_reference_id := NULLIF(to_jsonb(OLD)->>'destination_id', '')::bigint;
                END IF;
            ELSIF TG_ARGV[0] = 'logical_notification' THEN
                target_reference_id := NULLIF(
                    to_jsonb(NEW)->>'logical_notification_id', ''
                )::bigint;
                SELECT user_id INTO target_user_id
                  FROM logical_notifications WHERE id = target_reference_id;
                IF TG_OP = 'UPDATE' THEN
                    prior_reference_id := NULLIF(
                        to_jsonb(OLD)->>'logical_notification_id', ''
                    )::bigint;
                END IF;
            ELSIF TG_ARGV[0] = 'delivery_attempt' THEN
                target_reference_id := NULLIF(to_jsonb(NEW)->>'attempt_id', '')::bigint;
                SELECT notification.user_id INTO target_user_id
                  FROM notification_delivery_attempts attempt
                  JOIN logical_notifications notification
                    ON notification.id = attempt.logical_notification_id
                 WHERE attempt.id = target_reference_id;
                IF TG_OP = 'UPDATE' THEN
                    prior_reference_id := NULLIF(to_jsonb(OLD)->>'attempt_id', '')::bigint;
                END IF;
            ELSE
                RAISE EXCEPTION 'unknown erased-account guard mode: %', TG_ARGV[0];
            END IF;

            IF target_user_id IS NULL THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE'
               AND TG_ARGV[0] = 'direct_user'
               AND prior_owner_id IS DISTINCT FROM target_user_id THEN
                RAISE EXCEPTION 'user-owned rows cannot change owner'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE'
               AND TG_ARGV[0] <> 'direct_user'
               AND prior_reference_id IS DISTINCT FROM target_reference_id THEN
                RAISE EXCEPTION 'user-owned lineage cannot change ownership reference'
                    USING ERRCODE = '23514';
            END IF;

            PERFORM pg_advisory_xact_lock(
                hashtextextended('account-erasure:' || target_user_id::text, 0)
            );
            SELECT is_active INTO account_is_active
              FROM users WHERE id = target_user_id;
            SELECT created_txid INTO erasure_txid
              FROM account_erasure_events WHERE user_id = target_user_id;

            IF current_setting('valuepilot.account_erasure', true) = 'on'
               AND erasure_txid IS NULL THEN
                RETURN NEW;
            END IF;
            IF account_is_active IS DISTINCT FROM true OR erasure_txid IS NOT NULL THEN
                RAISE EXCEPTION
                    'completed account erasure forbids user-owned mutations'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_notification_events_erasure_barrier
        BEFORE INSERT OR UPDATE ON notification_events
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_logical_notifications_erasure_barrier
        BEFORE INSERT OR UPDATE ON logical_notifications
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_notification_inbox_states_erasure_barrier
        BEFORE INSERT OR UPDATE ON notification_inbox_states
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_notification_price_alert_states_erasure_barrier
        BEFORE INSERT OR UPDATE ON notification_price_alert_states
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_notification_delivery_attempts_erasure_barrier
        BEFORE INSERT OR UPDATE ON notification_delivery_attempts
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('logical_notification');
        CREATE TRIGGER trg_notification_delivery_events_erasure_barrier
        BEFORE INSERT OR UPDATE ON notification_delivery_events
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('delivery_attempt');
        CREATE TRIGGER trg_notification_email_challenges_erasure_barrier
        BEFORE INSERT OR UPDATE ON notification_email_challenges
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('notification_destination');

        CREATE TRIGGER trg_research_inbox_actions_erasure_barrier
        BEFORE INSERT OR UPDATE ON research_inbox_actions
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_research_inbox_action_events_erasure_barrier
        BEFORE INSERT OR UPDATE ON research_inbox_action_events
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_research_coverage_requirements_erasure_barrier
        BEFORE INSERT OR UPDATE ON research_coverage_requirements
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');

        CREATE TRIGGER trg_formulas_erasure_barrier
        BEFORE INSERT OR UPDATE ON formulas
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_calculated_runs_erasure_barrier
        BEFORE INSERT OR UPDATE ON calculated_runs
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_screening_rules_erasure_barrier
        BEFORE INSERT OR UPDATE ON screening_rules
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_stock_pools_erasure_barrier
        BEFORE INSERT OR UPDATE ON stock_pools
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_pool_memberships_erasure_barrier
        BEFORE INSERT OR UPDATE ON pool_memberships
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_price_alerts_erasure_barrier
        BEFORE INSERT OR UPDATE ON price_alerts
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');

        CREATE TRIGGER trg_pdf_documents_erasure_barrier
        BEFORE INSERT OR UPDATE ON pdf_documents
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        CREATE TRIGGER trg_document_pages_erasure_barrier
        BEFORE INSERT OR UPDATE ON document_pages
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('document');
        CREATE TRIGGER trg_metric_extractions_erasure_barrier
        BEFORE INSERT OR UPDATE ON metric_extractions
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        """
    )

    # These histories are normally immutable. The privacy transaction may
    # broaden a revision tombstone or delete user-created formula lineage; the
    # deferred completion trigger below proves that the transaction ended only
    # in the exact non-content state.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_research_revision_redaction()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND current_setting('valuepilot.account_erasure', true) = 'on' THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'research_case_revisions is append-only; DELETE is forbidden';
            END IF;
            IF OLD.is_redacted
               OR NOT NEW.is_redacted
               OR (to_jsonb(NEW) - ARRAY[
                    'thesis', 'variant_view', 'decision_reason', 'assumptions_json',
                    'risks_json', 'evidence_json', 'valuation_unavailable_reason',
                    'is_redacted', 'redaction_content_hash', 'redaction_reason',
                    'redacted_by_user_id', 'redacted_at'
                  ]) IS DISTINCT FROM
                  (to_jsonb(OLD) - ARRAY[
                    'thesis', 'variant_view', 'decision_reason', 'assumptions_json',
                    'risks_json', 'evidence_json', 'valuation_unavailable_reason',
                    'is_redacted', 'redaction_content_hash', 'redaction_reason',
                    'redacted_by_user_id', 'redacted_at'
                  ]) THEN
                RAISE EXCEPTION 'research_case_revisions permits only one audited content redaction';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE OR REPLACE FUNCTION enforce_formula_run_lineage_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND current_setting('valuepilot.account_erasure', true) = 'on' THEN
                RETURN OLD;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'formula calculation runs are retained lineage';
            END IF;
            IF to_jsonb(NEW) - 'is_dirty' - 'updated_at'
               IS DISTINCT FROM to_jsonb(OLD) - 'is_dirty' - 'updated_at' THEN
                RAISE EXCEPTION 'formula calculation run lineage is immutable';
            END IF;
            IF OLD.is_dirty = true AND NEW.is_dirty = false THEN
                RAISE EXCEPTION 'dirty formula calculation runs cannot be restored';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE OR REPLACE FUNCTION enforce_formula_metric_fact_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND OLD.user_id IS NOT NULL
               AND current_setting('valuepilot.account_erasure', true) = 'on' THEN
                RETURN OLD;
            END IF;
            IF OLD.source_type = 'calculated'
               AND OLD.value_json->>'formula_lineage_version' = 'formula-v2' THEN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'formula metric facts are retained lineage';
                END IF;
                IF to_jsonb(NEW) - 'is_current' - 'updated_at'
                   IS DISTINCT FROM to_jsonb(OLD) - 'is_current' - 'updated_at' THEN
                    RAISE EXCEPTION 'formula metric fact lineage and value are immutable';
                END IF;
                IF OLD.is_current = false AND NEW.is_current = true THEN
                    RAISE EXCEPTION 'retired formula metric facts cannot be restored';
                END IF;
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE FUNCTION validate_account_erasure_user_graph()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            incomplete_component text;
            incomplete_row jsonb;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM research_case_events event
                  JOIN research_cases research_case ON research_case.id = event.case_id
                 WHERE research_case.user_id = NEW.user_id
                   AND event.payload_json IS DISTINCT FROM
                       '{"privacy_erased": true}'::jsonb
            ) THEN
                RAISE EXCEPTION 'account erasure graph incomplete: research_case_events'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1 FROM research_case_revisions revision
                  JOIN research_cases research_case ON research_case.id = revision.case_id
                 WHERE research_case.user_id = NEW.user_id
                   AND (
                       revision.valuation_low IS NOT NULL
                       OR revision.valuation_base IS NOT NULL
                       OR revision.valuation_high IS NOT NULL
                       OR revision.valuation_currency IS NOT NULL
                       OR revision.valuation_as_of_date IS NOT NULL
                       OR revision.decision IS NOT NULL
                       OR revision.next_review_on IS NOT NULL
                       OR revision.is_qualified_decision = true
                   )
            ) THEN
                RAISE EXCEPTION 'account erasure graph incomplete: research_case_revisions'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1 FROM research_cases row
                 WHERE row.user_id = NEW.user_id
                   AND (
                       row.state <> 'voided'
                       OR row.decision IS NOT NULL
                       OR row.next_review_on IS NOT NULL
                       OR row.void_reason <> '[redacted]'
                   )
            ) THEN
                RAISE EXCEPTION 'account erasure graph incomplete: research_cases'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1 FROM notification_settings row
                 WHERE row.user_id = NEW.user_id
            ) THEN
                RAISE EXCEPTION 'account erasure graph incomplete: notification_settings'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1 FROM metric_facts row
                 WHERE row.user_id = NEW.user_id
                   AND row.source_type IN ('manual', 'calculated')
            ) THEN
                RAISE EXCEPTION 'account erasure graph incomplete: metric_facts'
                    USING ERRCODE = '23514';
            END IF;
            SELECT to_jsonb(row) INTO incomplete_row
              FROM research_inbox_actions row
             WHERE row.user_id = NEW.user_id
               AND (
                   row.reason <> '[redacted]'
                   OR row.rank_components IS NOT NULL
                   OR row.evidence_json IS DISTINCT FROM
                      '{"privacy_erased": true}'::jsonb
                   OR row.state <> 'dismissed'
                   OR row.snoozed_until IS NOT NULL
                   OR row.target_case_id IS NOT NULL
                   OR row.stock_id IS NOT NULL
               )
             LIMIT 1;
            IF incomplete_row IS NOT NULL THEN
                RAISE EXCEPTION 'account erasure graph incomplete action: %', incomplete_row
                    USING ERRCODE = '23514';
            END IF;
            SELECT CASE
                WHEN EXISTS (
                    SELECT 1 FROM notification_events row
                     WHERE row.user_id = NEW.user_id
                       AND row.payload_json::jsonb IS DISTINCT FROM
                           '{"privacy_erased": true}'::jsonb
                ) THEN 'notification_events'
                WHEN EXISTS (
                    SELECT 1 FROM logical_notifications row
                     WHERE row.user_id = NEW.user_id
                       AND (
                           row.title <> '[redacted]'
                           OR row.body <> '[redacted]'
                           OR row.evidence_route <> '[redacted]'
                           OR row.payload_json IS DISTINCT FROM
                              '{"privacy_erased": true}'::jsonb
                           OR row.case_id IS NOT NULL
                           OR row.stock_id IS NOT NULL
                           OR row.manager_id IS NOT NULL
                       )
                ) THEN 'logical_notifications'
                WHEN EXISTS (
                    SELECT 1 FROM notification_inbox_states row
                     WHERE row.user_id = NEW.user_id
                ) THEN 'notification_inbox_states'
                WHEN EXISTS (
                    SELECT 1 FROM notification_price_alert_states row
                     WHERE row.user_id = NEW.user_id
                ) THEN 'notification_price_alert_states'
                WHEN EXISTS (
                    SELECT 1
                      FROM notification_delivery_events event
                      JOIN notification_delivery_attempts attempt
                        ON attempt.id = event.attempt_id
                      JOIN logical_notifications notification
                        ON notification.id = attempt.logical_notification_id
                     WHERE notification.user_id = NEW.user_id
                       AND (
                           event.response_class <> 'account_erasure'
                           OR event.payload_json IS DISTINCT FROM
                              '{"privacy_erased": true}'::jsonb
                       )
                ) THEN 'notification_delivery_events'
                WHEN EXISTS (
                    SELECT 1 FROM research_case_origins origin
                      JOIN research_cases research_case ON research_case.id = origin.case_id
                     WHERE research_case.user_id = NEW.user_id
                       AND (
                           origin.origin_key <> ('[redacted:' || origin.id || ']')
                           OR origin.source_ref_json IS DISTINCT FROM
                              '{"privacy_erased": true}'::jsonb
                       )
                ) THEN 'research_case_origins'
                WHEN EXISTS (
                    SELECT 1 FROM research_inbox_actions row
                     WHERE row.user_id = NEW.user_id
                       AND (
                           row.reason <> '[redacted]'
                           OR row.rank_components IS NOT NULL
                           OR row.evidence_json IS DISTINCT FROM
                              '{"privacy_erased": true}'::jsonb
                           OR row.state <> 'dismissed'
                           OR row.snoozed_until IS NOT NULL
                           OR row.target_case_id IS NOT NULL
                           OR row.stock_id IS NOT NULL
                       )
                ) THEN 'research_inbox_actions'
                WHEN EXISTS (
                    SELECT 1 FROM research_inbox_action_events row
                     WHERE row.user_id = NEW.user_id
                       AND row.payload_json IS DISTINCT FROM
                           '{"privacy_erased": true}'::jsonb
                ) THEN 'research_inbox_action_events'
                WHEN EXISTS (
                    SELECT 1 FROM research_coverage_requirements row
                     WHERE row.user_id = NEW.user_id
                ) THEN 'research_coverage_requirements'
                WHEN EXISTS (SELECT 1 FROM formulas row WHERE row.user_id = NEW.user_id)
                    THEN 'formulas'
                WHEN EXISTS (SELECT 1 FROM calculated_runs row WHERE row.user_id = NEW.user_id)
                    THEN 'calculated_runs'
                WHEN EXISTS (SELECT 1 FROM screening_rules row WHERE row.user_id = NEW.user_id)
                    THEN 'screening_rules'
                WHEN EXISTS (SELECT 1 FROM stock_pools row WHERE row.user_id = NEW.user_id)
                    THEN 'stock_pools'
                WHEN EXISTS (SELECT 1 FROM pool_memberships row WHERE row.user_id = NEW.user_id)
                    THEN 'pool_memberships'
                WHEN EXISTS (SELECT 1 FROM price_alerts row WHERE row.user_id = NEW.user_id)
                    THEN 'price_alerts'
                ELSE NULL
            END INTO incomplete_component;
            IF incomplete_component IS NOT NULL THEN
                RAISE EXCEPTION 'account erasure graph incomplete: %', incomplete_component
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1 FROM notification_events row
                 WHERE row.user_id = NEW.user_id
                   AND row.payload_json::jsonb IS DISTINCT FROM
                       '{"privacy_erased": true}'::jsonb
            ) OR EXISTS (
                SELECT 1 FROM logical_notifications row
                 WHERE row.user_id = NEW.user_id
                   AND (
                       row.title <> '[redacted]'
                       OR row.body <> '[redacted]'
                       OR row.evidence_route <> '[redacted]'
                       OR row.payload_json IS DISTINCT FROM
                          '{"privacy_erased": true}'::jsonb
                       OR row.case_id IS NOT NULL
                       OR row.stock_id IS NOT NULL
                       OR row.manager_id IS NOT NULL
                   )
            ) OR EXISTS (
                SELECT 1 FROM notification_inbox_states row
                 WHERE row.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1 FROM notification_price_alert_states row
                 WHERE row.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1
                  FROM notification_delivery_events event
                  JOIN notification_delivery_attempts attempt
                    ON attempt.id = event.attempt_id
                  JOIN logical_notifications notification
                    ON notification.id = attempt.logical_notification_id
                 WHERE notification.user_id = NEW.user_id
                   AND (
                       event.response_class <> 'account_erasure'
                       OR event.payload_json IS DISTINCT FROM
                          '{"privacy_erased": true}'::jsonb
                   )
            ) OR EXISTS (
                SELECT 1 FROM notification_settings row
                 WHERE row.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1 FROM research_case_origins origin
                  JOIN research_cases research_case ON research_case.id = origin.case_id
                 WHERE research_case.user_id = NEW.user_id
                   AND (
                       origin.origin_key <> ('[redacted:' || origin.id || ']')
                       OR origin.source_ref_json IS DISTINCT FROM
                          '{"privacy_erased": true}'::jsonb
                   )
            ) OR EXISTS (
                SELECT 1 FROM research_case_events event
                  JOIN research_cases research_case ON research_case.id = event.case_id
                 WHERE research_case.user_id = NEW.user_id
                   AND event.payload_json IS DISTINCT FROM
                       '{"privacy_erased": true}'::jsonb
            ) OR EXISTS (
                SELECT 1 FROM research_case_revisions revision
                  JOIN research_cases research_case ON research_case.id = revision.case_id
                 WHERE research_case.user_id = NEW.user_id
                   AND (
                       revision.valuation_low IS NOT NULL
                       OR revision.valuation_base IS NOT NULL
                       OR revision.valuation_high IS NOT NULL
                       OR revision.valuation_currency IS NOT NULL
                       OR revision.valuation_as_of_date IS NOT NULL
                       OR revision.decision IS NOT NULL
                       OR revision.next_review_on IS NOT NULL
                       OR revision.is_qualified_decision = true
                   )
            ) OR EXISTS (
                SELECT 1 FROM research_cases row
                 WHERE row.user_id = NEW.user_id
                   AND (
                       row.state <> 'voided'
                       OR row.decision IS NOT NULL
                       OR row.next_review_on IS NOT NULL
                       OR row.void_reason <> '[redacted]'
                   )
            ) OR EXISTS (
                SELECT 1 FROM research_inbox_actions row
                 WHERE row.user_id = NEW.user_id
                   AND (
                       row.reason <> '[redacted]'
                       OR row.rank_components IS NOT NULL
                       OR row.evidence_json IS DISTINCT FROM
                          '{"privacy_erased": true}'::jsonb
                       OR row.state <> 'dismissed'
                       OR row.snoozed_until IS NOT NULL
                       OR row.target_case_id IS NOT NULL
                       OR row.stock_id IS NOT NULL
                   )
            ) OR EXISTS (
                SELECT 1 FROM research_inbox_action_events row
                 WHERE row.user_id = NEW.user_id
                   AND row.payload_json IS DISTINCT FROM
                       '{"privacy_erased": true}'::jsonb
            ) OR EXISTS (
                SELECT 1 FROM research_coverage_requirements row
                 WHERE row.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1 FROM formulas row WHERE row.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1 FROM calculated_runs row WHERE row.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1 FROM screening_rules row WHERE row.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1 FROM stock_pools row WHERE row.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1 FROM pool_memberships row WHERE row.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1 FROM price_alerts row WHERE row.user_id = NEW.user_id
            ) OR EXISTS (
                SELECT 1 FROM metric_facts row
                 WHERE row.user_id = NEW.user_id
                   AND row.source_type IN ('manual', 'calculated')
            ) THEN
                RAISE EXCEPTION
                    'account erasure event requires complete user-content graph tombstone'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_account_erasure_events_user_graph_complete
        AFTER INSERT ON account_erasure_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_account_erasure_user_graph();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM account_erasure_events) THEN
                RAISE EXCEPTION
                    'cannot remove complete user-graph erasure guard while erasure history exists';
            END IF;
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_account_erasure_events_user_graph_complete
            ON account_erasure_events;
        DROP FUNCTION IF EXISTS validate_account_erasure_user_graph();

        DROP TRIGGER IF EXISTS trg_metric_extractions_erasure_barrier ON metric_extractions;
        DROP TRIGGER IF EXISTS trg_document_pages_erasure_barrier ON document_pages;
        DROP TRIGGER IF EXISTS trg_pdf_documents_erasure_barrier ON pdf_documents;
        DROP TRIGGER IF EXISTS trg_price_alerts_erasure_barrier ON price_alerts;
        DROP TRIGGER IF EXISTS trg_pool_memberships_erasure_barrier ON pool_memberships;
        DROP TRIGGER IF EXISTS trg_stock_pools_erasure_barrier ON stock_pools;
        DROP TRIGGER IF EXISTS trg_screening_rules_erasure_barrier ON screening_rules;
        DROP TRIGGER IF EXISTS trg_calculated_runs_erasure_barrier ON calculated_runs;
        DROP TRIGGER IF EXISTS trg_formulas_erasure_barrier ON formulas;
        DROP TRIGGER IF EXISTS trg_research_coverage_requirements_erasure_barrier
            ON research_coverage_requirements;
        DROP TRIGGER IF EXISTS trg_research_inbox_action_events_erasure_barrier
            ON research_inbox_action_events;
        DROP TRIGGER IF EXISTS trg_research_inbox_actions_erasure_barrier
            ON research_inbox_actions;
        DROP TRIGGER IF EXISTS trg_notification_email_challenges_erasure_barrier
            ON notification_email_challenges;
        DROP TRIGGER IF EXISTS trg_notification_delivery_events_erasure_barrier
            ON notification_delivery_events;
        DROP TRIGGER IF EXISTS trg_notification_delivery_attempts_erasure_barrier
            ON notification_delivery_attempts;
        DROP TRIGGER IF EXISTS trg_notification_price_alert_states_erasure_barrier
            ON notification_price_alert_states;
        DROP TRIGGER IF EXISTS trg_notification_inbox_states_erasure_barrier
            ON notification_inbox_states;
        DROP TRIGGER IF EXISTS trg_logical_notifications_erasure_barrier
            ON logical_notifications;
        DROP TRIGGER IF EXISTS trg_notification_events_erasure_barrier
            ON notification_events;

        CREATE OR REPLACE FUNCTION guard_research_revision_redaction()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'research_case_revisions is append-only; DELETE is forbidden';
            END IF;
            IF OLD.is_redacted
               OR NOT NEW.is_redacted
               OR (to_jsonb(NEW) - ARRAY[
                    'thesis', 'variant_view', 'decision_reason', 'assumptions_json',
                    'risks_json', 'evidence_json', 'valuation_unavailable_reason',
                    'is_redacted', 'redaction_content_hash', 'redaction_reason',
                    'redacted_by_user_id', 'redacted_at'
                  ]) IS DISTINCT FROM
                  (to_jsonb(OLD) - ARRAY[
                    'thesis', 'variant_view', 'decision_reason', 'assumptions_json',
                    'risks_json', 'evidence_json', 'valuation_unavailable_reason',
                    'is_redacted', 'redaction_content_hash', 'redaction_reason',
                    'redacted_by_user_id', 'redacted_at'
                  ]) THEN
                RAISE EXCEPTION 'research_case_revisions permits only one audited content redaction';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE OR REPLACE FUNCTION enforce_formula_run_lineage_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'formula calculation runs are retained lineage';
            END IF;
            IF to_jsonb(NEW) - 'is_dirty' - 'updated_at'
               IS DISTINCT FROM to_jsonb(OLD) - 'is_dirty' - 'updated_at' THEN
                RAISE EXCEPTION 'formula calculation run lineage is immutable';
            END IF;
            IF OLD.is_dirty = true AND NEW.is_dirty = false THEN
                RAISE EXCEPTION 'dirty formula calculation runs cannot be restored';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE OR REPLACE FUNCTION enforce_formula_metric_fact_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.source_type = 'calculated'
               AND OLD.value_json->>'formula_lineage_version' = 'formula-v2' THEN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'formula metric facts are retained lineage';
                END IF;
                IF to_jsonb(NEW) - 'is_current' - 'updated_at'
                   IS DISTINCT FROM to_jsonb(OLD) - 'is_current' - 'updated_at' THEN
                    RAISE EXCEPTION 'formula metric fact lineage and value are immutable';
                END IF;
                IF OLD.is_current = false AND NEW.is_current = true THEN
                    RAISE EXCEPTION 'retired formula metric facts cannot be restored';
                END IF;
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;
        """
    )

    # Restore the 4100 guard definition after all 4400 triggers have gone.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_erased_account_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_user_id bigint;
            prior_owner_id bigint;
            erasure_txid bigint;
            account_is_active boolean;
        BEGIN
            IF TG_ARGV[0] = 'direct_user' THEN
                target_user_id := NULLIF(to_jsonb(NEW)->>'user_id', '')::bigint;
                IF TG_OP = 'UPDATE' THEN
                    prior_owner_id := NULLIF(to_jsonb(OLD)->>'user_id', '')::bigint;
                END IF;
            ELSIF TG_ARGV[0] = 'research_case' THEN
                SELECT user_id INTO target_user_id FROM research_cases
                 WHERE id = NULLIF(to_jsonb(NEW)->>'case_id', '')::bigint;
                IF TG_OP = 'UPDATE'
                   AND to_jsonb(NEW)->>'case_id' IS DISTINCT FROM
                       to_jsonb(OLD)->>'case_id' THEN
                    RAISE EXCEPTION 'user-owned lineage cannot change research case'
                        USING ERRCODE = '23514';
                END IF;
            ELSE
                RAISE EXCEPTION 'unknown erased-account guard mode: %', TG_ARGV[0];
            END IF;
            IF target_user_id IS NULL THEN RETURN NEW; END IF;
            IF TG_OP = 'UPDATE' AND TG_ARGV[0] = 'direct_user'
               AND prior_owner_id IS DISTINCT FROM target_user_id THEN
                RAISE EXCEPTION 'user-owned rows cannot change owner'
                    USING ERRCODE = '23514';
            END IF;
            PERFORM pg_advisory_xact_lock(
                hashtextextended('account-erasure:' || target_user_id::text, 0)
            );
            SELECT is_active INTO account_is_active FROM users WHERE id = target_user_id;
            SELECT created_txid INTO erasure_txid FROM account_erasure_events
             WHERE user_id = target_user_id;
            IF current_setting('valuepilot.account_erasure', true) = 'on'
               AND erasure_txid IS NULL THEN RETURN NEW; END IF;
            IF account_is_active IS DISTINCT FROM true OR erasure_txid IS NOT NULL THEN
                RAISE EXCEPTION 'completed account erasure forbids user-owned mutations'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
