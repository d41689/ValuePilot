"""Enforce exact canonical SEC provenance and quarantine unknown mappings.

Revision ID: 20260828260000
Revises: 20260828250000
Create Date: 2026-08-29 02:00:00
"""

from alembic import op


revision = "20260828260000"
down_revision = "20260828250000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_sec_metric_provenance_metadata()
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
                JOIN sec_financial_filings filing
                  ON filing.id = parse_run.filing_id
                JOIN sec_metric_mapping_registry mapping
                  ON mapping.mapping_version = publication.mapping_version
                 AND mapping.concept = raw.concept
                 AND mapping.canonical_metric_key =
                     publication.canonical_metric_key
                WHERE publication.metric_fact_id = NEW.id
                  AND publication.status = 'published'
                  AND NEW.value_json ? 'mapping_known_at'
                  AND (NEW.value_json->>'mapping_known_at')::timestamptz =
                      mapping.known_at
                  AND NEW.value_json->>'mapping_version' =
                      publication.mapping_version
                  AND NEW.value_json->>'fact_nature' = 'actual'
                  AND NEW.value_json->>'source_role' = 'primary_as_filed'
                  AND NEW.value_json->>'source_accession' = filing.accession_no
                  AND NEW.value_json->>'filing_form' = filing.form_type
                  AND NEW.value_json->>'filing_id' = filing.id::text
                  AND NEW.value_json->>'parse_run_id' = parse_run.id::text
                  AND NEW.value_json->>'parser_version' = parse_run.parser_version
                  AND NEW.value_json->>'raw_fact_id' = raw.id::text
                  AND NEW.value_json->>'artifact_id' = raw.artifact_id::text
                  AND (NEW.value_json->>'knowledge_at')::timestamptz =
                      publication.knowledge_at
                  AND NEW.as_of_date = publication.knowledge_at::date
                  AND (NEW.value_json->>'period_end')::date =
                      publication.period_end_date
                  AND NEW.value_json->>'context_id' IS NOT DISTINCT FROM
                      raw.context_id
                  AND NEW.value_json->>'unit_measure' IS NOT DISTINCT FROM
                      raw.unit_measure
                  AND NEW.value_json->>'decimals' IS NOT DISTINCT FROM raw.decimals
                  AND (
                      (raw.scale IS NULL AND
                       NEW.value_json->'scale' = 'null'::jsonb) OR
                      (raw.scale IS NOT NULL AND
                       NEW.value_json->>'scale' = raw.scale::text)
                  )
                  AND NEW.value_json->>'dimensions_policy' = 'consolidated_only'
                  AND NEW.value_json->'dimensions' = raw.dimensions_json
                  AND NEW.value_json->'locator' = raw.locator_json
                  AND (
                    (
                      publication.publication_role = 'direct'
                      AND NEW.value_json->>'value_basis' = 'as_filed'
                      AND (NEW.value_json->>'period_start')::date
                          IS NOT DISTINCT FROM raw.period_start
                      AND (
                        SELECT count(*) FROM jsonb_object_keys(NEW.value_json)
                      ) = 22
                      AND NEW.value_json ?& ARRAY[
                        'fact_nature', 'source_role', 'source_accession',
                        'filing_form', 'filing_id', 'parse_run_id',
                        'parser_version', 'raw_fact_id', 'artifact_id',
                        'mapping_version', 'mapping_known_at', 'knowledge_at',
                        'period_start', 'period_end', 'context_id',
                        'dimensions_policy', 'dimensions', 'unit_measure',
                        'decimals', 'scale', 'locator', 'value_basis'
                      ]
                    ) OR (
                      publication.publication_role =
                          'derived_discrete_quarter'
                      AND NEW.value_json->>'value_basis' =
                          'derived_discrete_quarter'
                      AND NEW.value_json->>'derivation' =
                          'current_ytd_minus_prior_ytd'
                      AND (
                        SELECT count(*) FROM jsonb_object_keys(NEW.value_json)
                      ) = 26
                      AND NEW.value_json ?& ARRAY[
                        'fact_nature', 'source_role', 'source_accession',
                        'filing_form', 'filing_id', 'parse_run_id',
                        'parser_version', 'raw_fact_id', 'artifact_id',
                        'mapping_version', 'mapping_known_at', 'knowledge_at',
                        'period_start', 'period_end', 'context_id',
                        'dimensions_policy', 'dimensions', 'unit_measure',
                        'decimals', 'scale', 'locator', 'value_basis',
                        'derivation', 'input_metric_fact_ids',
                        'input_raw_fact_ids', 'input_provenance'
                      ]
                    )
                  )
            ) THEN
                RAISE EXCEPTION
                    'canonical SEC metric fact provenance is not exact approved lineage';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    # Revalidate approved mappings only. Unknown legacy versions are retained
    # untouched but hidden by the canonical product visibility predicate.
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
                SELECT 1
                FROM metric_facts fact
                JOIN sec_metric_publications publication
                  ON publication.metric_fact_id = fact.id
                JOIN sec_raw_xbrl_facts raw
                  ON raw.id = publication.raw_fact_id
                JOIN sec_metric_mapping_registry mapping
                  ON mapping.mapping_version = publication.mapping_version
                 AND mapping.concept = raw.concept
                WHERE fact.source_type = 'sec'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade exact SEC provenance while approved facts exist';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_sec_metric_provenance_metadata()
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
                  AND (NEW.value_json->>'mapping_known_at')::timestamptz =
                      mapping.known_at
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
        """
    )
