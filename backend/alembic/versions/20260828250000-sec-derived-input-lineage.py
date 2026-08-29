"""Bind derived SEC quarters to exact published direct inputs.

Revision ID: 20260828250000
Revises: 20260828240000
Create Date: 2026-08-29 01:00:00
"""

from alembic import op


revision = "20260828250000"
down_revision = "20260828240000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION validate_sec_derived_input_lineage()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_type = 'sec'
               AND NEW.value_json->>'value_basis' = 'derived_discrete_quarter'
               AND NOT EXISTS (
                    SELECT 1
                    FROM sec_metric_publications derived_publication
                    JOIN sec_raw_xbrl_facts current_raw
                      ON current_raw.id = derived_publication.raw_fact_id
                    JOIN metric_facts prior_input
                      ON prior_input.id =
                         (NEW.value_json->'input_metric_fact_ids'->>0)::bigint
                    JOIN metric_facts current_input
                      ON current_input.id =
                         (NEW.value_json->'input_metric_fact_ids'->>1)::bigint
                    JOIN sec_metric_publications prior_publication
                      ON prior_publication.metric_fact_id = prior_input.id
                    JOIN sec_metric_publications current_publication
                      ON current_publication.metric_fact_id = current_input.id
                    WHERE derived_publication.metric_fact_id = NEW.id
                      AND derived_publication.publication_role =
                          'derived_discrete_quarter'
                      AND derived_publication.status = 'published'
                      AND derived_publication.mapping_version =
                          NEW.value_json->>'mapping_version'
                      AND prior_publication.publication_role = 'direct'
                      AND current_publication.publication_role = 'direct'
                      AND prior_publication.status = 'published'
                      AND current_publication.status = 'published'
                      AND prior_publication.mapping_version =
                          derived_publication.mapping_version
                      AND current_publication.mapping_version =
                          derived_publication.mapping_version
                      AND derived_publication.knowledge_at = greatest(
                          prior_publication.knowledge_at,
                          current_publication.knowledge_at
                      )
                      AND (NEW.value_json->>'knowledge_at')::timestamptz =
                          derived_publication.knowledge_at
                      AND NEW.as_of_date = derived_publication.knowledge_at::date
                      AND prior_publication.raw_fact_id = prior_input.source_ref_id
                      AND current_publication.raw_fact_id = current_input.source_ref_id
                      AND current_publication.raw_fact_id = current_raw.id
                      AND jsonb_typeof(NEW.value_json->'input_metric_fact_ids') =
                          'array'
                      AND jsonb_array_length(
                          NEW.value_json->'input_metric_fact_ids'
                      ) = 2
                      AND NEW.value_json->'input_metric_fact_ids' =
                          jsonb_build_array(prior_input.id, current_input.id)
                      AND NEW.value_json->'input_raw_fact_ids' =
                          jsonb_build_array(
                              prior_input.source_ref_id,
                              current_input.source_ref_id
                          )
                      AND prior_input.user_id IS NULL
                      AND current_input.user_id IS NULL
                      AND prior_input.source_type = 'sec'
                      AND current_input.source_type = 'sec'
                      AND prior_input.value_json->>'value_basis' = 'as_filed'
                      AND current_input.value_json->>'value_basis' = 'as_filed'
                      AND (NOT NEW.is_current OR (
                          prior_input.is_current = true
                          AND current_input.is_current = true
                      ))
                      AND prior_input.stock_id = NEW.stock_id
                      AND current_input.stock_id = NEW.stock_id
                      AND prior_input.metric_key = NEW.metric_key
                      AND current_input.metric_key = NEW.metric_key
                      AND prior_input.unit IS NOT DISTINCT FROM NEW.unit
                      AND current_input.unit IS NOT DISTINCT FROM NEW.unit
                      AND prior_input.currency IS NOT DISTINCT FROM NEW.currency
                      AND current_input.currency IS NOT DISTINCT FROM NEW.currency
                      AND prior_input.period_type = 'YTD'
                      AND current_input.period_type = 'YTD'
                      AND prior_input.value_json->>'period_start' =
                          current_input.value_json->>'period_start'
                      AND prior_input.period_end_date < current_input.period_end_date
                      AND current_input.period_end_date = NEW.period_end_date
                      AND NEW.value_json->>'period_start' =
                          (prior_input.period_end_date + 1)::text
                      AND current_input.value_numeric - prior_input.value_numeric =
                          NEW.value_numeric
                      AND jsonb_typeof(NEW.value_json->'input_provenance') = 'array'
                      AND jsonb_array_length(
                          NEW.value_json->'input_provenance'
                      ) = 2
                      AND NEW.value_json->'input_provenance' =
                          jsonb_build_array(
                            jsonb_build_object(
                              'metric_fact_id', prior_input.id,
                              'raw_fact_id', prior_input.source_ref_id,
                              'artifact_id', prior_input.value_json->'artifact_id',
                              'source_accession',
                                  prior_input.value_json->'source_accession',
                              'filing_id', prior_input.value_json->'filing_id',
                              'parse_run_id', prior_input.value_json->'parse_run_id',
                              'parser_version',
                                  prior_input.value_json->'parser_version',
                              'mapping_version',
                                  prior_input.value_json->'mapping_version',
                              'mapping_known_at',
                                  prior_input.value_json->'mapping_known_at',
                              'knowledge_at', prior_input.value_json->'knowledge_at',
                              'period_start', prior_input.value_json->'period_start',
                              'period_end', prior_input.value_json->'period_end',
                              'context_id', prior_input.value_json->'context_id',
                              'dimensions_policy',
                                  prior_input.value_json->'dimensions_policy',
                              'dimensions', prior_input.value_json->'dimensions',
                              'unit_measure', prior_input.value_json->'unit_measure',
                              'decimals', prior_input.value_json->'decimals',
                              'scale', prior_input.value_json->'scale',
                              'locator', prior_input.value_json->'locator',
                              'value_numeric', prior_input.value_numeric,
                              'unit', prior_input.unit,
                              'currency', prior_input.currency
                            ),
                            jsonb_build_object(
                              'metric_fact_id', current_input.id,
                              'raw_fact_id', current_input.source_ref_id,
                              'artifact_id', current_input.value_json->'artifact_id',
                              'source_accession',
                                  current_input.value_json->'source_accession',
                              'filing_id', current_input.value_json->'filing_id',
                              'parse_run_id', current_input.value_json->'parse_run_id',
                              'parser_version',
                                  current_input.value_json->'parser_version',
                              'mapping_version',
                                  current_input.value_json->'mapping_version',
                              'mapping_known_at',
                                  current_input.value_json->'mapping_known_at',
                              'knowledge_at', current_input.value_json->'knowledge_at',
                              'period_start', current_input.value_json->'period_start',
                              'period_end', current_input.value_json->'period_end',
                              'context_id', current_input.value_json->'context_id',
                              'dimensions_policy',
                                  current_input.value_json->'dimensions_policy',
                              'dimensions', current_input.value_json->'dimensions',
                              'unit_measure', current_input.value_json->'unit_measure',
                              'decimals', current_input.value_json->'decimals',
                              'scale', current_input.value_json->'scale',
                              'locator', current_input.value_json->'locator',
                              'value_numeric', current_input.value_numeric,
                              'unit', current_input.unit,
                              'currency', current_input.currency
                            )
                          )
               ) THEN
                RAISE EXCEPTION
                    'canonical SEC derived fact conflicts with published direct input lineage';
            END IF;

            IF TG_OP = 'UPDATE'
               AND OLD.source_type = 'sec'
               AND OLD.is_current = true
               AND NEW.is_current = false
               AND EXISTS (
                    SELECT 1
                    FROM metric_facts derived
                    WHERE derived.source_type = 'sec'
                      AND derived.is_current = true
                      AND derived.value_json->>'value_basis' =
                          'derived_discrete_quarter'
                      AND derived.value_json->'input_metric_fact_ids' @>
                          jsonb_build_array(NEW.id)
               ) THEN
                RAISE EXCEPTION
                    'current SEC derived fact cannot retain a demoted direct input';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_metric_facts_sec_derived_input_lineage
        AFTER INSERT OR UPDATE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_sec_derived_input_lineage();
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
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM sec_metric_publications
                WHERE publication_role = 'derived_discrete_quarter'
                  AND status = 'published'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade exact SEC derived-input lineage while derived facts exist';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_sec_derived_input_lineage "
        "ON metric_facts"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_sec_derived_input_lineage()")
