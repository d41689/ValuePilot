"""Reject noncanonical columns on public SEC metric facts.

Revision ID: 20260828300000
Revises: 20260828290000
Create Date: 2026-08-29 06:00:00
"""

from alembic import op


revision = "20260828300000"
down_revision = "20260828290000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION validate_sec_metric_fact_column_shape()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_type = 'sec' AND (
                NEW.user_id IS NOT NULL OR
                NEW.source_document_id IS NOT NULL OR
                NEW.value_text IS NOT NULL OR
                NEW.period IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'canonical SEC metric fact contains noncanonical or private columns';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_metric_facts_sec_column_shape
        AFTER INSERT OR UPDATE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_sec_metric_fact_column_shape();
        """
    )
    op.execute(
        "UPDATE metric_facts SET is_current = is_current "
        "WHERE source_type = 'sec' "
        "AND EXISTS ("
        "SELECT 1 FROM sec_metric_publications publication "
        "JOIN sec_metric_mapping_registry mapping "
        "ON mapping.mapping_version = publication.mapping_version "
        "WHERE publication.metric_fact_id = metric_facts.id"
        ")"
    )
    op.execute("SET CONSTRAINTS trg_metric_facts_sec_column_shape IMMEDIATE")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM metric_facts fact
                JOIN sec_metric_publications publication
                  ON publication.metric_fact_id = fact.id
                JOIN sec_metric_mapping_registry mapping
                  ON mapping.mapping_version = publication.mapping_version
                WHERE fact.source_type = 'sec'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade canonical SEC column shape while approved facts exist';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_sec_column_shape ON metric_facts"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_sec_metric_fact_column_shape()")
