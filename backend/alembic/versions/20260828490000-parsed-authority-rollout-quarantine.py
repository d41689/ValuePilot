"""Quarantine projections bootstrapped by the superseded 4700 rollout.

Revision ID: 20260828490000
Revises: 20260828480000
Create Date: 2026-08-30 00:10:00
"""

from alembic import op


revision = "20260828490000"
down_revision = "20260828480000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- An earlier development version of 4700 copied canonical meaning
        -- from the fact being validated. There is no trustworthy marker that
        -- distinguishes those projections from parser-authored projections,
        -- so quarantine every row present at this rollout boundary. A normal
        -- reparse republishes exact authority under the new contract.
        DROP TRIGGER IF EXISTS trg_metric_facts_parsed_generation_valid
            ON metric_facts;
        DROP TRIGGER IF EXISTS trg_metric_extractions_lineage_immutable
            ON metric_extractions;
        DROP TRIGGER IF EXISTS trg_metric_extractions_redaction_valid
            ON metric_extractions;

        UPDATE calculated_runs run
           SET is_dirty = true
         WHERE run.is_dirty = false
           AND EXISTS (
                SELECT 1
                  FROM jsonb_array_elements_text(
                           run.input_fact_ids_json
                       ) input_id(value)
                  JOIN metric_facts input_fact
                    ON input_fact.id = input_id.value::bigint
                 WHERE input_fact.source_type = 'parsed'
           );

        UPDATE metric_facts
           SET is_current = false
         WHERE source_type = 'parsed'
           AND is_current = true;

        UPDATE metric_extractions
           SET resolved_stock_id = NULL,
               mapping_version = NULL,
               canonical_projections_json = '[]'::jsonb
         WHERE resolved_stock_id IS NOT NULL
            OR mapping_version IS NOT NULL
            OR canonical_projections_json <> '[]'::jsonb;

        CREATE CONSTRAINT TRIGGER trg_metric_facts_parsed_generation_valid
        AFTER INSERT OR UPDATE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_parsed_metric_fact_generation();

        CREATE TRIGGER trg_metric_extractions_lineage_immutable
        BEFORE UPDATE OR DELETE ON metric_extractions
        FOR EACH ROW EXECUTE FUNCTION guard_metric_extraction_lineage();

        CREATE CONSTRAINT TRIGGER trg_metric_extractions_redaction_valid
        AFTER UPDATE ON metric_extractions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_private_lineage_redaction();

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM metric_facts
                 WHERE source_type = 'parsed'
                   AND is_current = true
            ) OR EXISTS (
                SELECT 1
                  FROM metric_extractions
                 WHERE resolved_stock_id IS NOT NULL
                    OR mapping_version IS NOT NULL
                    OR canonical_projections_json <> '[]'::jsonb
            ) THEN
                RAISE EXCEPTION
                    'legacy parsed authority quarantine is incomplete';
            END IF;
        END;
        $$;
        """
    )


def downgrade() -> None:
    # Quarantined authority cannot be reconstructed honestly. The prior schema
    # accepts retained non-current lineage, so keep it retired.
    pass
