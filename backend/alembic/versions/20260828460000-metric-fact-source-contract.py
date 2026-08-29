"""Enforce the canonical metric-fact source and owner contract.

Revision ID: 20260828460000
Revises: 20260828450000
Create Date: 2026-08-29 21:00:00
"""

from alembic import op


revision = "20260828460000"
down_revision = "20260828450000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- Already-upgraded databases may have executed the original 3500
        -- migration before this helper was introduced.  Recreate its weak
        -- generation-only form here; 4700 atomically replaces it with exact
        -- stock/mapping/value authority.
        CREATE OR REPLACE FUNCTION parsed_metric_fact_has_exact_authority(
            target_fact_id bigint
        )
        RETURNS boolean
        LANGUAGE sql
        STABLE
        AS $$
            SELECT COALESCE((
                SELECT fact.source_type = 'parsed'
                   AND EXISTS (
                        SELECT 1
                          FROM pdf_documents document
                          JOIN metric_extractions extraction
                            ON extraction.id = fact.source_ref_id
                           AND extraction.user_id = fact.user_id
                           AND extraction.document_id = fact.source_document_id
                           AND extraction.parse_generation = fact.parse_generation
                         WHERE document.id = fact.source_document_id
                           AND document.user_id = fact.user_id
                           AND fact.parse_generation <=
                               document.current_parse_generation
                           AND (
                               NOT fact.is_current OR (
                                   document.lifecycle_state = 'active'
                                   AND fact.parse_generation =
                                       document.current_parse_generation
                                   AND extraction.original_text_snippet IS NOT NULL
                               )
                           )
                   )
                  FROM metric_facts fact
                 WHERE fact.id = target_fact_id
            ), false)
        $$;

        UPDATE metric_facts
           SET value_json = NULL
         WHERE source_type = 'manual'
           AND metric_key = 'val.fair_value'
           AND value_numeric IS NOT NULL
           AND value_json = 'null'::jsonb;

        CREATE FUNCTION current_manual_fact_has_exact_authority(
            target_fact_id bigint
        )
        RETURNS boolean
        LANGUAGE sql
        STABLE
        AS $$
            SELECT COALESCE((
                SELECT fact.source_type = 'manual'
                   AND fact.is_current = true
                   AND (
                        (
                            fact.source_document_id IS NULL
                            AND fact.metric_key = 'val.fair_value'
                            AND fact.source_ref_id IS NOT NULL
                            AND fact.unit = 'USD'
                            AND fact.currency = 'USD'
                            AND fact.period_type = 'AS_OF'
                            AND fact.period_end_date IS NOT NULL
                            AND fact.as_of_date IS NULL
                            AND EXISTS (
                                SELECT 1
                                  FROM research_case_revisions revision
                                  JOIN research_cases research_case
                                    ON research_case.id = revision.case_id
                                 WHERE revision.id = fact.source_ref_id
                                   AND research_case.user_id = fact.user_id
                                   AND research_case.stock_id = fact.stock_id
                                   AND revision.created_by_user_id = fact.user_id
                                   AND revision.snapshot_stock_id = fact.stock_id
                                   AND revision.valuation_as_of_date = fact.period_end_date
                                   AND (
                                        (
                                            fact.value_numeric IS NOT NULL
                                            AND fact.value_json IS NULL
                                            AND revision.valuation_base::double precision
                                                IS NOT DISTINCT FROM fact.value_numeric
                                            AND revision.valuation_currency = 'USD'
                                            AND revision.valuation_unavailable_reason IS NULL
                                        )
                                        OR (
                                            fact.value_numeric IS NULL
                                            AND revision.valuation_base IS NULL
                                            AND revision.valuation_currency IS NULL
                                            AND revision.valuation_unavailable_reason IS NOT NULL
                                            AND fact.value_json->>'status' = 'unavailable'
                                            AND fact.value_json->>'reason' =
                                                revision.valuation_unavailable_reason
                                            AND (
                                                (
                                                    revision.is_redacted = false
                                                    AND (
                                                        SELECT count(*)
                                                          FROM jsonb_object_keys(
                                                              fact.value_json
                                                          )
                                                    ) = 2
                                                )
                                                OR (
                                                    revision.is_redacted = true
                                                    AND revision.redaction_content_hash
                                                        IS NOT NULL
                                                    AND fact.value_json->>'reason' =
                                                        '[redacted]'
                                                    AND fact.value_json->>'redaction_content_hash'
                                                        = revision.redaction_content_hash
                                                    AND (
                                                        SELECT count(*)
                                                          FROM jsonb_object_keys(
                                                              fact.value_json
                                                          )
                                                    ) = 3
                                                )
                                            )
                                        )
                                   )
                            )
                        )
                        OR (
                            fact.source_document_id IS NOT NULL
                            AND fact.value_json IS NOT NULL
                            AND jsonb_typeof(fact.value_json->'correction') = 'boolean'
                            AND fact.value_json->'correction' = 'true'::jsonb
                            AND EXISTS (
                                SELECT 1
                                  FROM pdf_documents doc
                                  JOIN metric_extractions extraction
                                    ON extraction.id = fact.source_ref_id
                                  JOIN metric_facts original
                                    ON original.source_type = 'parsed'
                                   AND original.is_current = true
                                   AND original.user_id IS NOT DISTINCT FROM fact.user_id
                                   AND original.stock_id = fact.stock_id
                                   AND original.metric_key = fact.metric_key
                                   AND original.period IS NOT DISTINCT FROM fact.period
                                   AND original.period_type IS NOT DISTINCT FROM fact.period_type
                                   AND original.period_end_date IS NOT DISTINCT FROM fact.period_end_date
                                   AND original.as_of_date IS NOT DISTINCT FROM fact.as_of_date
                                   AND original.unit IS NOT DISTINCT FROM fact.unit
                                   AND original.currency IS NOT DISTINCT FROM fact.currency
                                   AND original.source_document_id = fact.source_document_id
                                   AND original.source_ref_id = fact.source_ref_id
                                   AND original.parse_generation = doc.current_parse_generation
                                   AND parsed_metric_fact_has_exact_authority(original.id)
                                 WHERE doc.id = fact.source_document_id
                                   AND doc.user_id = fact.user_id
                                   AND (
                                       doc.stock_id IS NULL
                                       OR doc.stock_id = fact.stock_id
                                   )
                                   AND doc.lifecycle_state = 'active'
                                   AND extraction.user_id = fact.user_id
                                   AND extraction.document_id = doc.id
                                   AND extraction.parse_generation = doc.current_parse_generation
                                   AND extraction.original_text_snippet IS NOT NULL
                            )
                        )
                   )
                  FROM metric_facts fact
                 WHERE fact.id = target_fact_id
            ), false)
        $$;

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM metric_facts
                 WHERE source_type NOT IN ('parsed', 'manual', 'calculated', 'sec')
                    OR (source_type = 'sec' AND user_id IS NOT NULL)
                    OR (source_type <> 'sec' AND user_id IS NULL)
                    OR (
                        source_type = 'manual'
                        AND source_document_id IS NULL
                        AND metric_key <> 'val.fair_value'
                    )
                    OR (
                        source_type = 'manual'
                        AND is_current = true
                        AND NOT current_manual_fact_has_exact_authority(id)
                    )
            ) THEN
                RAISE EXCEPTION
                    'metric_facts contains unreviewed source or owner shapes; remediate before upgrade';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM calculated_runs run
                  CROSS JOIN LATERAL jsonb_array_elements_text(
                      run.input_fact_ids_json
                  ) input_id(value)
                  JOIN metric_facts input_fact
                    ON input_fact.id = input_id.value::bigint
                 WHERE run.is_dirty = false
                   AND input_fact.source_type = 'manual'
                   AND NOT current_manual_fact_has_exact_authority(input_fact.id)
            ) THEN
                RAISE EXCEPTION
                    'calculated_runs contains an unauthorized manual input; remediate before upgrade';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM metric_facts
                 WHERE source_type = 'manual'
                   AND is_current = true
                 GROUP BY
                    user_id,
                    stock_id,
                    metric_key,
                    coalesce(period_type, ''),
                    coalesce(period_end_date, DATE '-infinity'),
                    coalesce(as_of_date, DATE '-infinity')
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'metric_facts contains conflicting current manual period slots; remediate before upgrade';
            END IF;
        END;
        $$;

        ALTER TABLE metric_facts
            ADD CONSTRAINT ck_metric_facts_source_type
            CHECK (source_type IN ('parsed', 'manual', 'calculated', 'sec'));

        ALTER TABLE metric_facts
            ADD CONSTRAINT ck_metric_facts_source_owner
            CHECK (
                (source_type = 'sec' AND user_id IS NULL)
                OR (source_type <> 'sec' AND user_id IS NOT NULL)
            );

        ALTER TABLE metric_facts
            ADD CONSTRAINT ck_metric_facts_manual_authority
            CHECK (
                source_type <> 'manual'
                OR source_document_id IS NOT NULL
                OR metric_key = 'val.fair_value'
            );

        CREATE UNIQUE INDEX uq_metric_facts_current_manual_period_slot
        ON metric_facts (
            user_id,
            stock_id,
            metric_key,
            coalesce(period_type, ''),
            coalesce(period_end_date, DATE '-infinity'),
            coalesce(as_of_date, DATE '-infinity')
        )
        WHERE source_type = 'manual' AND is_current = true;

        CREATE FUNCTION guard_manual_metric_fact_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.source_type <> 'manual' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;

            IF TG_OP = 'DELETE' THEN
                IF current_setting('valuepilot.account_erasure', true) = 'on' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'manual metric facts are retained lineage';
            END IF;

            IF OLD.is_current = true
               AND NEW.is_current = false
               AND to_jsonb(NEW) - 'is_current' - 'updated_at'
                   IS NOT DISTINCT FROM
                   to_jsonb(OLD) - 'is_current' - 'updated_at' THEN
                RETURN NEW;
            END IF;

            IF OLD.metric_key = 'val.fair_value'
               AND OLD.value_numeric IS NULL
               AND NEW.value_numeric IS NULL
               AND to_jsonb(NEW) - 'value_json' - 'updated_at'
                   IS NOT DISTINCT FROM
                   to_jsonb(OLD) - 'value_json' - 'updated_at'
               AND NEW.value_json->>'status' = 'unavailable'
               AND NEW.value_json->>'reason' = '[redacted]'
               AND NEW.value_json->>'redaction_content_hash' ~ '^[0-9a-f]{64}$'
               AND (
                    SELECT count(*) FROM jsonb_object_keys(NEW.value_json)
               ) = 3 THEN
                RETURN NEW;
            END IF;

            RAISE EXCEPTION
                'manual metric fact lineage and value are immutable';
        END;
        $$;

        CREATE TRIGGER trg_metric_facts_manual_immutable
        BEFORE UPDATE OR DELETE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION guard_manual_metric_fact_immutability();

        CREATE FUNCTION validate_manual_current_fact_demotion()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.source_type <> 'manual'
               OR OLD.is_current IS NOT TRUE
               OR NEW.is_current IS NOT FALSE THEN
                RETURN NEW;
            END IF;

            IF current_setting('valuepilot.account_erasure', true) = 'on'
               AND EXISTS (
                    SELECT 1
                      FROM account_erasure_events event
                     WHERE event.user_id = OLD.user_id
                       AND event.created_txid = txid_current()
               ) THEN
                RETURN NEW;
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM metric_facts replacement
                 WHERE replacement.id <> OLD.id
                   AND replacement.source_type = 'manual'
                   AND replacement.is_current = true
                   AND replacement.user_id IS NOT DISTINCT FROM OLD.user_id
                   AND replacement.stock_id = OLD.stock_id
                   AND replacement.metric_key = OLD.metric_key
                   AND replacement.period_type IS NOT DISTINCT FROM OLD.period_type
                   AND replacement.period_end_date
                       IS NOT DISTINCT FROM OLD.period_end_date
                   AND replacement.as_of_date IS NOT DISTINCT FROM OLD.as_of_date
                   AND current_manual_fact_has_exact_authority(replacement.id)
            ) THEN
                RETURN NEW;
            END IF;

            IF OLD.source_document_id IS NOT NULL
               AND EXISTS (
                    SELECT 1
                      FROM pdf_documents doc
                      LEFT JOIN metric_extractions extraction
                        ON extraction.id = OLD.source_ref_id
                     WHERE doc.id = OLD.source_document_id
                       AND (
                            doc.user_id IS DISTINCT FROM OLD.user_id
                            OR doc.stock_id IS DISTINCT FROM OLD.stock_id
                            OR doc.lifecycle_state <> 'active'
                            OR extraction.id IS NULL
                            OR extraction.user_id IS DISTINCT FROM OLD.user_id
                            OR extraction.document_id
                                IS DISTINCT FROM OLD.source_document_id
                            OR extraction.parse_generation
                                IS DISTINCT FROM doc.current_parse_generation
                       )
               ) THEN
                RETURN NEW;
            END IF;

            RAISE EXCEPTION
                'manual current fact demotion requires an atomic authorized replacement or source retirement';
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_metric_facts_manual_demotion_valid
        AFTER UPDATE OF is_current ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_manual_current_fact_demotion();

        CREATE FUNCTION validate_manual_fact_account_erasure_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.source_type = 'manual' AND NOT EXISTS (
                SELECT 1
                  FROM account_erasure_events event
                 WHERE event.user_id = OLD.user_id
                   AND event.created_txid = txid_current()
            ) THEN
                RAISE EXCEPTION
                    'manual metric fact deletion requires atomic audited account erasure';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_metric_facts_manual_erasure_delete
        AFTER DELETE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_manual_fact_account_erasure_delete();

        CREATE OR REPLACE FUNCTION validate_current_manual_fact_lineage()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_type <> 'manual' OR NOT NEW.is_current THEN
                RETURN NEW;
            END IF;

            IF NOT current_manual_fact_has_exact_authority(NEW.id) THEN
                IF NEW.source_document_id IS NULL THEN
                    RAISE EXCEPTION
                        'documentless manual fact requires an authorized user valuation revision';
                ELSE
                    RAISE EXCEPTION
                        'current document-linked manual fact requires exact current parsed fact lineage';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE OR REPLACE FUNCTION validate_document_current_manual_projection()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM metric_facts fact
                 WHERE fact.source_document_id = NEW.id
                   AND fact.source_type = 'manual'
                   AND fact.is_current = true
                   AND NOT current_manual_fact_has_exact_authority(fact.id)
            ) THEN
                RAISE EXCEPTION
                    'document projection change must demote superseded manual corrections';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION validate_formula_run_manual_input_authority()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.is_dirty = false AND EXISTS (
                SELECT 1
                  FROM jsonb_array_elements_text(
                      NEW.input_fact_ids_json
                  ) input_id(value)
                  JOIN metric_facts input_fact
                    ON input_fact.id = input_id.value::bigint
                 WHERE input_fact.source_type = 'manual'
                   AND NOT current_manual_fact_has_exact_authority(input_fact.id)
            ) THEN
                RAISE EXCEPTION
                    'formula run contains an unauthorized manual input';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_calculated_runs_manual_input_authority
        AFTER INSERT OR UPDATE ON calculated_runs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_formula_run_manual_input_authority();

        CREATE FUNCTION validate_formula_fact_manual_input_authority()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_type = 'calculated'
               AND NEW.is_current = true
               AND NEW.value_json->>'formula_lineage_version' = 'formula-v2'
               AND EXISTS (
                    SELECT 1
                      FROM calculated_runs run
                      CROSS JOIN LATERAL jsonb_array_elements_text(
                          run.input_fact_ids_json
                      ) input_id(value)
                      JOIN metric_facts input_fact
                        ON input_fact.id = input_id.value::bigint
                     WHERE run.id = NEW.source_ref_id
                       AND input_fact.source_type = 'manual'
                       AND NOT current_manual_fact_has_exact_authority(input_fact.id)
               ) THEN
                RAISE EXCEPTION
                    'formula fact contains an unauthorized manual input';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_metric_facts_formula_manual_input_authority
        AFTER INSERT OR UPDATE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_formula_fact_manual_input_authority();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM metric_facts) THEN
                RAISE EXCEPTION
                    'cannot remove metric-fact source contract while facts exist';
            END IF;
        END;
        $$;
        DROP TRIGGER IF EXISTS trg_metric_facts_formula_manual_input_authority
            ON metric_facts;
        DROP FUNCTION IF EXISTS validate_formula_fact_manual_input_authority();
        DROP TRIGGER IF EXISTS trg_calculated_runs_manual_input_authority
            ON calculated_runs;
        DROP FUNCTION IF EXISTS validate_formula_run_manual_input_authority();
        DROP TRIGGER IF EXISTS trg_metric_facts_manual_erasure_delete
            ON metric_facts;
        DROP FUNCTION IF EXISTS validate_manual_fact_account_erasure_delete();
        DROP TRIGGER IF EXISTS trg_metric_facts_manual_demotion_valid
            ON metric_facts;
        DROP FUNCTION IF EXISTS validate_manual_current_fact_demotion();
        DROP TRIGGER IF EXISTS trg_metric_facts_manual_immutable
            ON metric_facts;
        DROP FUNCTION IF EXISTS guard_manual_metric_fact_immutability();
        DROP INDEX IF EXISTS uq_metric_facts_current_manual_period_slot;
        ALTER TABLE metric_facts
            DROP CONSTRAINT IF EXISTS ck_metric_facts_manual_authority;
        ALTER TABLE metric_facts DROP CONSTRAINT IF EXISTS ck_metric_facts_source_owner;
        ALTER TABLE metric_facts DROP CONSTRAINT IF EXISTS ck_metric_facts_source_type;
        DROP FUNCTION IF EXISTS current_manual_fact_has_exact_authority(bigint);
        """
    )
