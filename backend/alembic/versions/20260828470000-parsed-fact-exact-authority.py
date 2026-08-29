"""Bind parsed facts to immutable extraction mapping projections.

Revision ID: 20260828470000
Revises: 20260828460000
Create Date: 2026-08-29 22:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260828470000"
down_revision = "20260828460000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "metric_extractions",
        sa.Column(
            "resolved_stock_id",
            sa.BigInteger(),
            sa.ForeignKey("stocks.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "metric_extractions",
        sa.Column("mapping_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "metric_extractions",
        sa.Column(
            "canonical_projections_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_metric_extractions_resolved_stock",
        "metric_extractions",
        ["resolved_stock_id"],
    )
    op.create_check_constraint(
        "ck_metric_extractions_projection_array",
        "metric_extractions",
        "jsonb_typeof(canonical_projections_json) = 'array'",
    )
    op.create_check_constraint(
        "ck_metric_extractions_mapping_version",
        "metric_extractions",
        "mapping_version IS NULL OR mapping_version = 'value-line-v2'",
    )
    op.create_check_constraint(
        "ck_metric_extractions_projection_authority_shape",
        "metric_extractions",
        "jsonb_array_length(canonical_projections_json) = 0 "
        "OR (resolved_stock_id IS NOT NULL AND mapping_version IS NOT NULL)",
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT fact.source_ref_id
                 FROM metric_facts fact
                 WHERE fact.source_type = 'parsed'
                   AND fact.source_ref_id IS NOT NULL
                 GROUP BY fact.source_ref_id
                HAVING count(DISTINCT fact.stock_id) > 1
            ) THEN
                RAISE EXCEPTION
                    'one parsed extraction is bound to multiple stocks; review before upgrade';
            END IF;
            IF EXISTS (
                SELECT 1
                  FROM metric_facts fact
                  JOIN metric_extractions extraction
                    ON extraction.id = fact.source_ref_id
                  JOIN pdf_documents document
                    ON document.id = extraction.document_id
                 WHERE fact.source_type = 'parsed'
                   AND (
                       extraction.user_id IS DISTINCT FROM fact.user_id
                       OR extraction.document_id IS DISTINCT FROM
                           fact.source_document_id
                       OR extraction.parse_generation IS DISTINCT FROM
                           fact.parse_generation
                       OR (
                           document.stock_id IS NOT NULL
                           AND document.stock_id IS DISTINCT FROM fact.stock_id
                       )
                   )
            ) THEN
                RAISE EXCEPTION
                    'parsed fact/extraction identity is inconsistent; review before upgrade';
            END IF;
        END;
        $$;

        -- A legacy fact cannot certify its own canonical meaning. Retain all
        -- pre-contract facts as non-current audit history and require a
        -- post-upgrade reparse to publish exact projections.
        DROP TRIGGER IF EXISTS trg_metric_facts_parsed_generation_valid
            ON metric_facts;

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

        DROP TRIGGER IF EXISTS trg_metric_extractions_lineage_immutable
            ON metric_extractions;
        DROP TRIGGER IF EXISTS trg_metric_extractions_redaction_valid
            ON metric_extractions;
        """
    )

    op.execute(
        """
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
                           AND extraction.resolved_stock_id = fact.stock_id
                           AND extraction.mapping_version = 'value-line-v2'
                         WHERE document.id = fact.source_document_id
                           AND document.user_id = fact.user_id
                           AND (
                               document.stock_id IS NULL
                               OR document.stock_id = fact.stock_id
                           )
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
                           AND EXISTS (
                               SELECT 1
                                 FROM jsonb_array_elements(
                                     extraction.canonical_projections_json
                                 ) projection
                                WHERE projection = jsonb_build_object(
                                    'metric_key', fact.metric_key,
                                    'value_numeric', fact.value_numeric,
                                    'value_text', fact.value_text,
                                    'value_json', fact.value_json,
                                    'unit', fact.unit,
                                    'currency', fact.currency,
                                    'period', fact.period,
                                    'period_type', fact.period_type,
                                    'period_end_date', fact.period_end_date,
                                    'as_of_date', fact.as_of_date
                                )
                           )
                   )
                  FROM metric_facts fact
                 WHERE fact.id = target_fact_id
            ), false)
        $$;

        CREATE OR REPLACE FUNCTION validate_parsed_metric_fact_generation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_type = 'parsed'
               AND NOT parsed_metric_fact_has_exact_authority(NEW.id)
               AND NOT (
                    NEW.is_current = false
                    AND EXISTS (
                        SELECT 1
                          FROM pdf_documents document
                          JOIN metric_extractions extraction
                            ON extraction.id = NEW.source_ref_id
                           AND extraction.user_id = NEW.user_id
                           AND extraction.document_id = NEW.source_document_id
                           AND extraction.parse_generation = NEW.parse_generation
                         WHERE document.id = NEW.source_document_id
                           AND document.user_id = NEW.user_id
                           AND document.lifecycle_state = 'erased'
                    )
               ) THEN
                RAISE EXCEPTION
                    'parsed metric fact lacks exact extraction projection authority';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_metric_facts_parsed_generation_valid
        AFTER INSERT OR UPDATE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_parsed_metric_fact_generation();

        CREATE OR REPLACE FUNCTION guard_metric_extraction_lineage()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'metric_extractions are retained parse lineage';
            END IF;
            IF current_setting('valuepilot.account_erasure', true)
                   IS DISTINCT FROM 'on'
               OR NEW.raw_value_text IS NOT NULL
               OR NEW.original_text_snippet IS NOT NULL
               OR NEW.parsed_value_json IS NOT NULL
               OR NEW.bbox_json IS NOT NULL
               OR NEW.canonical_projections_json <> '[]'::jsonb
               OR to_jsonb(NEW)
                    - 'raw_value_text' - 'original_text_snippet'
                    - 'parsed_value_json' - 'bbox_json'
                    - 'canonical_projections_json'
                  IS DISTINCT FROM
                  to_jsonb(OLD)
                    - 'raw_value_text' - 'original_text_snippet'
                    - 'parsed_value_json' - 'bbox_json'
                    - 'canonical_projections_json' THEN
                RAISE EXCEPTION 'metric_extractions are immutable parse lineage';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_metric_extractions_lineage_immutable
        BEFORE UPDATE OR DELETE ON metric_extractions
        FOR EACH ROW EXECUTE FUNCTION guard_metric_extraction_lineage();

        CREATE CONSTRAINT TRIGGER trg_metric_extractions_redaction_valid
        AFTER UPDATE ON metric_extractions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_private_lineage_redaction();

        CREATE FUNCTION validate_parsed_projection_erasure()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM metric_extractions extraction
                 WHERE extraction.user_id = NEW.user_id
                   AND extraction.canonical_projections_json <> '[]'::jsonb
            ) THEN
                RAISE EXCEPTION
                    'account erasure requires parsed projection redaction'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_account_erasure_parsed_projection_complete
        AFTER INSERT ON account_erasure_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_parsed_projection_erasure();

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM metric_facts fact
                 WHERE fact.source_type = 'parsed'
                   AND fact.is_current = true
            ) OR EXISTS (
                SELECT 1
                  FROM metric_extractions
                 WHERE resolved_stock_id IS NOT NULL
                    OR mapping_version IS NOT NULL
                    OR canonical_projections_json <> '[]'::jsonb
            ) THEN
                RAISE EXCEPTION
                    'legacy parsed authority was not quarantined';
            END IF;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM metric_facts WHERE source_type = 'parsed'
            ) OR EXISTS (
                SELECT 1
                  FROM metric_extractions
                 WHERE resolved_stock_id IS NOT NULL
                    OR mapping_version IS NOT NULL
                    OR canonical_projections_json <> '[]'::jsonb
            ) THEN
                RAISE EXCEPTION
                    'cannot remove parsed exact authority while parsed lineage exists';
            END IF;
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_account_erasure_parsed_projection_complete
            ON account_erasure_events;
        DROP FUNCTION IF EXISTS validate_parsed_projection_erasure();

        CREATE OR REPLACE FUNCTION guard_metric_extraction_lineage()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'metric_extractions are retained parse lineage';
            END IF;
            IF current_setting('valuepilot.account_erasure', true)
                   IS DISTINCT FROM 'on'
               OR NEW.raw_value_text IS NOT NULL
               OR NEW.original_text_snippet IS NOT NULL
               OR NEW.parsed_value_json IS NOT NULL
               OR NEW.bbox_json IS NOT NULL
               OR to_jsonb(NEW)
                    - 'raw_value_text' - 'original_text_snippet'
                    - 'parsed_value_json' - 'bbox_json'
                  IS DISTINCT FROM
                  to_jsonb(OLD)
                    - 'raw_value_text' - 'original_text_snippet'
                    - 'parsed_value_json' - 'bbox_json' THEN
                RAISE EXCEPTION 'metric_extractions are immutable parse lineage';
            END IF;
            RETURN NEW;
        END;
        $$;

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

        CREATE OR REPLACE FUNCTION validate_parsed_metric_fact_generation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_type = 'parsed'
               AND NOT parsed_metric_fact_has_exact_authority(NEW.id) THEN
                RAISE EXCEPTION
                    'parsed metric fact generation is not current document lineage';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.drop_constraint(
        "ck_metric_extractions_projection_authority_shape",
        "metric_extractions",
        type_="check",
    )
    op.drop_constraint(
        "ck_metric_extractions_mapping_version",
        "metric_extractions",
        type_="check",
    )
    op.drop_constraint(
        "ck_metric_extractions_projection_array",
        "metric_extractions",
        type_="check",
    )
    op.drop_index(
        "ix_metric_extractions_resolved_stock",
        table_name="metric_extractions",
    )
    op.drop_column("metric_extractions", "canonical_projections_json")
    op.drop_column("metric_extractions", "mapping_version")
    op.drop_column("metric_extractions", "resolved_stock_id")
