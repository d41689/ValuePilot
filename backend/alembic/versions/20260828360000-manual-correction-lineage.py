"""Bind manual corrections to current evidence and invalidate formula outputs.

Revision ID: 20260828360000
Revises: 20260828350000
Create Date: 2026-08-29 12:00:00
"""

from alembic import op


revision = "20260828360000"
down_revision = "20260828350000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve legacy rows as lineage, but do not leave an invalid correction
    # in the current product projection.
    op.execute(
        """
        UPDATE metric_facts fact
           SET is_current = false
         WHERE fact.source_type = 'manual'
           AND fact.source_document_id IS NOT NULL
           AND fact.is_current = true
           AND NOT EXISTS (
                SELECT 1
                  FROM pdf_documents doc
                  JOIN metric_extractions extraction
                    ON extraction.id = fact.source_ref_id
                 WHERE doc.id = fact.source_document_id
                   AND doc.user_id = fact.user_id
                   AND doc.stock_id = fact.stock_id
                   AND doc.lifecycle_state = 'active'
                   AND extraction.user_id = fact.user_id
                   AND extraction.document_id = doc.id
                   AND extraction.parse_generation = doc.current_parse_generation
           );

        CREATE FUNCTION dirty_formula_runs_for_manual_override()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_type = 'manual' AND NEW.is_current = true THEN
                UPDATE calculated_runs run
                   SET is_dirty = true
                 WHERE run.is_dirty = false
                   AND run.user_id = NEW.user_id
                   AND run.stock_id = NEW.stock_id
                   AND EXISTS (
                        SELECT 1
                          FROM jsonb_array_elements_text(
                                   run.input_fact_ids_json
                               ) AS input_id(value)
                          JOIN metric_facts input_fact
                            ON input_fact.id = input_id.value::bigint
                         WHERE input_fact.metric_key = NEW.metric_key
                           AND input_fact.period IS NOT DISTINCT FROM NEW.period
                           AND input_fact.period_type IS NOT DISTINCT FROM NEW.period_type
                           AND input_fact.period_end_date IS NOT DISTINCT FROM NEW.period_end_date
                           AND input_fact.as_of_date IS NOT DISTINCT FROM NEW.as_of_date
                   );
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_metric_facts_manual_override_dirties_formula
        AFTER INSERT ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION dirty_formula_runs_for_manual_override();

        CREATE FUNCTION validate_current_manual_fact_lineage()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_type = 'manual'
               AND NEW.source_document_id IS NOT NULL
               AND NEW.is_current = true
               AND NOT EXISTS (
                    SELECT 1
                      FROM pdf_documents doc
                      JOIN metric_extractions extraction
                        ON extraction.id = NEW.source_ref_id
                     WHERE doc.id = NEW.source_document_id
                       AND doc.user_id = NEW.user_id
                       AND doc.stock_id = NEW.stock_id
                       AND doc.lifecycle_state = 'active'
                       AND extraction.user_id = NEW.user_id
                       AND extraction.document_id = doc.id
                       AND extraction.parse_generation = doc.current_parse_generation
               ) THEN
                RAISE EXCEPTION
                    'current document-linked manual fact requires exact current extraction lineage';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_metric_facts_manual_lineage_valid
        AFTER INSERT OR UPDATE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_current_manual_fact_lineage();

        CREATE FUNCTION validate_document_current_manual_projection()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM metric_facts fact
                  LEFT JOIN metric_extractions extraction
                    ON extraction.id = fact.source_ref_id
                 WHERE fact.source_document_id = NEW.id
                   AND fact.source_type = 'manual'
                   AND fact.is_current = true
                   AND (
                        fact.user_id IS DISTINCT FROM NEW.user_id
                        OR fact.stock_id IS DISTINCT FROM NEW.stock_id
                        OR NEW.lifecycle_state <> 'active'
                        OR extraction.id IS NULL
                        OR extraction.user_id IS DISTINCT FROM NEW.user_id
                        OR extraction.document_id IS DISTINCT FROM NEW.id
                        OR extraction.parse_generation IS DISTINCT FROM NEW.current_parse_generation
                   )
            ) THEN
                RAISE EXCEPTION
                    'document projection change must demote superseded manual corrections';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_pdf_documents_manual_projection_valid
        AFTER UPDATE OF stock_id, current_parse_generation, lifecycle_state
        ON pdf_documents
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_document_current_manual_projection();

        SET CONSTRAINTS ALL IMMEDIATE;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM metric_facts
                 WHERE source_type = 'manual'
                   AND source_document_id IS NOT NULL
                   AND is_current = true
            ) OR EXISTS (
                SELECT 1
                  FROM calculated_runs run
                  CROSS JOIN LATERAL jsonb_array_elements_text(
                      run.input_fact_ids_json
                  ) input_id(value)
                  JOIN metric_facts input_fact
                    ON input_fact.id = input_id.value::bigint
                 WHERE input_fact.source_type = 'manual'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade manual correction lineage while protected state exists';
            END IF;
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_pdf_documents_manual_projection_valid
            ON pdf_documents;
        DROP FUNCTION IF EXISTS validate_document_current_manual_projection();
        DROP TRIGGER IF EXISTS trg_metric_facts_manual_lineage_valid
            ON metric_facts;
        DROP FUNCTION IF EXISTS validate_current_manual_fact_lineage();
        DROP TRIGGER IF EXISTS trg_metric_facts_manual_override_dirties_formula
            ON metric_facts;
        DROP FUNCTION IF EXISTS dirty_formula_runs_for_manual_override();
        """
    )
