"""Preserve append-only Value Line parse generations.

Revision ID: 20260828350000
Revises: 20260828340000
Create Date: 2026-08-29 11:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828350000"
down_revision = "20260828340000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pdf_documents",
        sa.Column(
            "current_parse_generation",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "document_pages",
        sa.Column(
            "parse_generation",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "metric_extractions",
        sa.Column(
            "parse_generation",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "metric_facts",
        sa.Column("parse_generation", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE metric_facts SET parse_generation = 1 "
        "WHERE source_type = 'parsed'"
    )
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.create_check_constraint(
        "ck_pdf_documents_parse_generation_positive",
        "pdf_documents",
        "current_parse_generation > 0",
    )
    op.create_check_constraint(
        "ck_document_pages_parse_generation_positive",
        "document_pages",
        "parse_generation > 0",
    )
    op.create_check_constraint(
        "ck_metric_extractions_parse_generation_positive",
        "metric_extractions",
        "parse_generation > 0",
    )
    op.create_check_constraint(
        "ck_metric_facts_parsed_generation",
        "metric_facts",
        "source_type <> 'parsed' OR parse_generation IS NOT NULL",
    )
    op.execute("DROP INDEX IF EXISTS uq_metric_facts_parsed_document_slot")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_metric_facts_parsed_document_slot
        ON metric_facts (
            stock_id,
            metric_key,
            period_type,
            period_end_date,
            source_document_id,
            parse_generation
        )
        WHERE source_type = 'parsed'
        """
    )
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.create_index(
        "uq_document_pages_document_generation_page",
        "document_pages",
        ["document_id", "parse_generation", "page_number"],
        unique=True,
    )
    op.create_index(
        "ix_metric_extractions_document_generation",
        "metric_extractions",
        ["document_id", "parse_generation"],
    )
    # Pre-generation rows cannot be linked exactly without guessing. Preserve
    # them as audit history but remove them from the current projection; a
    # successful reparse will publish a fully linked generation.
    op.execute(
        """
        UPDATE metric_facts fact
           SET is_current = false
         WHERE fact.source_type = 'parsed'
           AND fact.is_current = true
           AND NOT EXISTS (
                SELECT 1
                  FROM metric_extractions extraction
                 WHERE extraction.id = fact.source_ref_id
                   AND extraction.user_id = fact.user_id
                   AND extraction.document_id = fact.source_document_id
                   AND extraction.parse_generation = fact.parse_generation
                   AND extraction.original_text_snippet IS NOT NULL
           )
        """
    )

    op.execute(
        """
        CREATE FUNCTION guard_document_page_lineage()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'document_pages are retained parse lineage';
            END IF;
            IF current_setting('valuepilot.account_erasure', true)
                   IS DISTINCT FROM 'on'
               OR NEW.page_text IS NOT NULL
               OR NEW.page_image_key IS NOT NULL
               OR to_jsonb(NEW) - 'page_text' - 'page_image_key'
                  IS DISTINCT FROM
                  to_jsonb(OLD) - 'page_text' - 'page_image_key' THEN
                RAISE EXCEPTION 'document_pages are immutable parse lineage';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_document_pages_lineage_immutable
        BEFORE UPDATE OR DELETE ON document_pages
        FOR EACH ROW EXECUTE FUNCTION guard_document_page_lineage();

        CREATE FUNCTION guard_metric_extraction_lineage()
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

        CREATE TRIGGER trg_metric_extractions_lineage_immutable
        BEFORE UPDATE OR DELETE ON metric_extractions
        FOR EACH ROW EXECUTE FUNCTION guard_metric_extraction_lineage();

        CREATE FUNCTION validate_private_lineage_redaction()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_document_id bigint;
        BEGIN
            target_document_id := NEW.document_id;
            IF NOT EXISTS (
                SELECT 1
                  FROM pdf_documents document
                  JOIN account_erasure_events event
                    ON event.user_id = document.user_id
                 WHERE document.id = target_document_id
                   AND document.lifecycle_state = 'erased'
                   AND document.retirement_reason = 'account_erasure'
                   AND event.created_txid = txid_current()
            ) THEN
                RAISE EXCEPTION
                    'private parse lineage redaction requires atomic audited account erasure';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_document_pages_redaction_valid
        AFTER UPDATE ON document_pages
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_private_lineage_redaction();

        CREATE CONSTRAINT TRIGGER trg_metric_extractions_redaction_valid
        AFTER UPDATE ON metric_extractions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_private_lineage_redaction();

        CREATE FUNCTION guard_parsed_metric_fact_lineage()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.source_type = 'parsed' THEN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'parsed metric facts are retained lineage';
                END IF;
                IF to_jsonb(NEW) - 'is_current' - 'updated_at'
                   IS DISTINCT FROM
                   to_jsonb(OLD) - 'is_current' - 'updated_at' THEN
                    RAISE EXCEPTION
                        'parsed metric fact provenance and value are immutable';
                END IF;
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;

        CREATE TRIGGER trg_metric_facts_parsed_immutable
        BEFORE UPDATE OR DELETE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION guard_parsed_metric_fact_lineage();

        CREATE FUNCTION parsed_metric_fact_has_exact_authority(
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

        CREATE FUNCTION validate_parsed_metric_fact_generation()
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

        CREATE CONSTRAINT TRIGGER trg_metric_facts_parsed_generation_valid
        AFTER INSERT OR UPDATE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_parsed_metric_fact_generation();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pdf_documents
                 WHERE current_parse_generation > 1
            ) OR EXISTS (
                SELECT 1 FROM document_pages WHERE parse_generation > 1
            ) OR EXISTS (
                SELECT 1 FROM metric_extractions WHERE parse_generation > 1
            ) OR EXISTS (
                SELECT 1 FROM metric_facts WHERE parse_generation > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade document parse generations while reparse lineage exists';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_parsed_generation_valid ON metric_facts"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_parsed_metric_fact_generation()")
    op.execute(
        "DROP FUNCTION IF EXISTS parsed_metric_fact_has_exact_authority(bigint)"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_parsed_immutable ON metric_facts"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_parsed_metric_fact_lineage()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_extractions_redaction_valid ON metric_extractions"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_document_pages_redaction_valid ON document_pages"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_private_lineage_redaction()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_extractions_lineage_immutable ON metric_extractions"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_metric_extraction_lineage()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_document_pages_lineage_immutable ON document_pages"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_document_page_lineage()")
    op.drop_index(
        "ix_metric_extractions_document_generation",
        table_name="metric_extractions",
    )
    op.drop_index(
        "uq_document_pages_document_generation_page", table_name="document_pages"
    )
    op.execute("DROP INDEX IF EXISTS uq_metric_facts_parsed_document_slot")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_metric_facts_parsed_document_slot
        ON metric_facts (
            stock_id, metric_key, period_type, period_end_date,
            source_document_id
        )
        WHERE source_type = 'parsed'
        """
    )
    op.drop_constraint(
        "ck_metric_facts_parsed_generation", "metric_facts", type_="check"
    )
    op.drop_constraint(
        "ck_metric_extractions_parse_generation_positive",
        "metric_extractions",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_pages_parse_generation_positive",
        "document_pages",
        type_="check",
    )
    op.drop_constraint(
        "ck_pdf_documents_parse_generation_positive",
        "pdf_documents",
        type_="check",
    )
    op.drop_column("metric_facts", "parse_generation")
    op.drop_column("metric_extractions", "parse_generation")
    op.drop_column("document_pages", "parse_generation")
    op.drop_column("pdf_documents", "current_parse_generation")
