"""Bind canonical SEC facts to approved mapping and source provenance.

Revision ID: 20260828240000
Revises: 20260828230000
Create Date: 2026-08-29 00:00:00
"""

from alembic import op


revision = "20260828240000"
down_revision = "20260828230000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION validate_sec_metric_provenance_metadata()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_type = 'sec' AND NOT EXISTS (
                SELECT 1
                FROM sec_metric_publications publication
                JOIN sec_raw_xbrl_facts raw
                  ON raw.id = publication.raw_fact_id
                JOIN sec_financial_parse_runs parse_run
                  ON parse_run.id = raw.parse_run_id
                JOIN sec_metric_mapping_registry mapping
                  ON mapping.mapping_version = publication.mapping_version
                 AND mapping.concept = raw.concept
                WHERE publication.metric_fact_id = NEW.id
                  AND publication.status = 'published'
                  AND NEW.value_json ? 'mapping_known_at'
                  AND (NEW.value_json->>'mapping_known_at')::timestamptz = mapping.known_at
                  AND NEW.value_json->>'parser_version' = parse_run.parser_version
                  AND NEW.value_json->>'context_id' IS NOT DISTINCT FROM raw.context_id
                  AND NEW.value_json->>'unit_measure' IS NOT DISTINCT FROM raw.unit_measure
                  AND NEW.value_json->>'decimals' IS NOT DISTINCT FROM raw.decimals
                  AND (
                      (raw.scale IS NULL AND NEW.value_json->'scale' = 'null'::jsonb) OR
                      (raw.scale IS NOT NULL AND NEW.value_json->>'scale' = raw.scale::text)
                  )
                  AND NEW.value_json->>'dimensions_policy' = 'consolidated_only'
                  AND NEW.value_json->'dimensions' = raw.dimensions_json
            ) THEN
                RAISE EXCEPTION
                    'canonical SEC metric fact provenance metadata conflicts with approved lineage';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_metric_facts_sec_provenance_metadata
        AFTER INSERT OR UPDATE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_sec_metric_provenance_metadata();
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
    op.execute(
        "SET CONSTRAINTS trg_metric_facts_sec_provenance_metadata IMMEDIATE"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM metric_facts
                WHERE source_type = 'sec'
                  AND value_json->>'mapping_version' = 'sec-us-gaap-v2'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade SEC provenance metadata integrity while v2 facts exist';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_sec_provenance_metadata ON metric_facts"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_sec_metric_provenance_metadata()")
