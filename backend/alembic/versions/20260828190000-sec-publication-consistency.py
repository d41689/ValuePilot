"""Validate canonical SEC fact identity against published raw lineage.

Revision ID: 20260828190000
Revises: 20260828180000
Create Date: 2026-08-28 19:00:00
"""

from alembic import op


revision = "20260828190000"
down_revision = "20260828180000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_sec_metric_fact_publication()
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
                JOIN sec_issuer_identities identity
                  ON identity.id = filing.issuer_identity_id
                WHERE publication.metric_fact_id = NEW.id
                  AND publication.raw_fact_id = NEW.source_ref_id
                  AND publication.status = 'published'
                  AND identity.stock_id = NEW.stock_id
                  AND publication.canonical_metric_key = NEW.metric_key
                  AND publication.canonical_unit IS NOT DISTINCT FROM NEW.unit
                  AND publication.period_type IS NOT DISTINCT FROM NEW.period_type
                  AND publication.period_end_date IS NOT DISTINCT FROM NEW.period_end_date
                  AND publication.mapping_version = NEW.value_json->>'mapping_version'
                  AND publication.knowledge_at =
                      (NEW.value_json->>'knowledge_at')::timestamptz
                  AND publication.decision_json->>'filing_id' = filing.id::text
                  AND publication.decision_json->>'parse_run_id' = parse_run.id::text
                  AND (
                      (
                          publication.publication_role = 'direct'
                          AND NEW.value_json->>'value_basis' = 'as_filed'
                          AND NEW.value_json->>'raw_fact_id' = raw.id::text
                          AND NEW.value_json->>'artifact_id' = raw.artifact_id::text
                      ) OR (
                          publication.publication_role = 'derived_discrete_quarter'
                          AND NEW.value_json->>'value_basis' =
                              'derived_discrete_quarter'
                          AND NEW.value_json->'input_raw_fact_ids'
                              @> to_jsonb(ARRAY[raw.id])
                          AND jsonb_array_length(
                              NEW.value_json->'input_metric_fact_ids'
                          ) = 2
                      )
                  )
                  AND (
                      (NEW.unit = 'USD' AND NEW.currency = 'USD') OR
                      (NEW.unit = 'USD_per_share' AND NEW.currency = 'USD') OR
                      (NEW.unit = 'shares' AND NEW.currency IS NULL)
                  )
            ) THEN
                RAISE EXCEPTION
                    'canonical SEC metric fact conflicts with published mapping lineage';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_sec_metric_fact_publication()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_type = 'sec' AND NOT EXISTS (
                SELECT 1
                FROM sec_metric_publications publication
                WHERE publication.metric_fact_id = NEW.id
                  AND publication.raw_fact_id = NEW.source_ref_id
                  AND publication.status = 'published'
            ) THEN
                RAISE EXCEPTION
                    'canonical SEC metric fact requires published mapping lineage';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
