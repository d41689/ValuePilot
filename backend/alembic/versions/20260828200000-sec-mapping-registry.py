"""Enforce approved SEC mapping semantics at the database boundary.

Revision ID: 20260828200000
Revises: 20260828190000
Create Date: 2026-08-28 20:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828200000"
down_revision = "20260828190000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sec_metric_mapping_registry",
        sa.Column("mapping_version", sa.String(length=80), nullable=False),
        sa.Column("concept", sa.Text(), nullable=False),
        sa.Column("canonical_metric_key", sa.Text(), nullable=False),
        sa.Column("value_kind", sa.String(length=32), nullable=False),
        sa.Column("period_basis", sa.String(length=16), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "value_kind IN ('monetary', 'currency_per_share', 'shares')",
            name="ck_sec_metric_mapping_registry_value_kind",
        ),
        sa.CheckConstraint(
            "period_basis IN ('instant', 'duration')",
            name="ck_sec_metric_mapping_registry_period_basis",
        ),
        sa.PrimaryKeyConstraint("mapping_version", "concept"),
    )
    op.execute(
        """
        INSERT INTO sec_metric_mapping_registry
            (mapping_version, concept, canonical_metric_key, value_kind,
             period_basis, known_at)
        VALUES
          ('sec-us-gaap-v2', 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax', 'is.sales', 'monetary', 'duration', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:SalesRevenueNet', 'is.sales', 'monetary', 'duration', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:Revenues', 'is.sales', 'monetary', 'duration', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:NetIncomeLoss', 'is.net_income', 'monetary', 'duration', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:OperatingIncomeLoss', 'is.operating_income', 'monetary', 'duration', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:GrossProfit', 'is.gross_profit', 'monetary', 'duration', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:NetCashProvidedByUsedInOperatingActivities', 'is.operating_cash_flow', 'monetary', 'duration', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:PaymentsToAcquirePropertyPlantAndEquipment', 'cf.capital_expenditures', 'monetary', 'duration', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:ShareBasedCompensation', 'is.stock_based_compensation', 'monetary', 'duration', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:Assets', 'bs.total_assets', 'monetary', 'instant', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:AssetsCurrent', 'bs.current_assets', 'monetary', 'instant', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:Liabilities', 'bs.total_liabilities', 'monetary', 'instant', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:LiabilitiesCurrent', 'bs.current_liabilities', 'monetary', 'instant', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:StockholdersEquity', 'bs.total_equity', 'monetary', 'instant', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest', 'bs.total_equity', 'monetary', 'instant', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:CashAndCashEquivalentsAtCarryingValue', 'bs.cash_and_equivalents', 'monetary', 'instant', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:LongTermDebtCurrent', 'bs.current_long_term_debt', 'monetary', 'instant', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:LongTermDebtNoncurrent', 'cap.long_term_debt', 'monetary', 'instant', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:EarningsPerShareDiluted', 'per_share.eps', 'currency_per_share', 'duration', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:CommonStockSharesOutstanding', 'equity.shares_outstanding', 'shares', 'instant', '2026-08-28T00:00:00Z'),
          ('sec-us-gaap-v2', 'us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding', 'equity.weighted_average_diluted_shares', 'shares', 'duration', '2026-08-28T00:00:00Z')
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_sec_metric_mapping_registry_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'SEC metric mapping registry is migration-owned; runtime DML is forbidden';
        END;
        $$;

        CREATE TRIGGER trg_sec_metric_mapping_registry_immutable_rows
        BEFORE INSERT OR UPDATE OR DELETE ON sec_metric_mapping_registry
        FOR EACH ROW EXECUTE FUNCTION reject_sec_metric_mapping_registry_mutation();

        CREATE TRIGGER trg_sec_metric_mapping_registry_no_truncate
        BEFORE TRUNCATE ON sec_metric_mapping_registry
        FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_metric_mapping_registry_mutation();

        CREATE FUNCTION normalized_sec_raw_numeric(raw sec_raw_xbrl_facts)
        RETURNS numeric
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            value_text text;
            negative_parentheses boolean := false;
            result numeric;
            transform text := lower(coalesce(raw.transformation_format, ''));
        BEGIN
            IF raw.is_nil OR raw.raw_value IS NULL THEN
                RETURN NULL;
            END IF;
            value_text := replace(replace(btrim(raw.raw_value), chr(160), ''), ' ', '');
            IF left(value_text, 1) = '(' AND right(value_text, 1) = ')' THEN
                negative_parentheses := true;
                value_text := substr(value_text, 2, length(value_text) - 2);
            END IF;
            IF transform LIKE '%comma-decimal%' OR transform LIKE '%num-comma%' THEN
                value_text := replace(replace(value_text, '.', ''), ',', '.');
            ELSE
                value_text := replace(value_text, ',', '');
            END IF;
            value_text := replace(replace(replace(value_text, '$', ''), '€', ''), '£', '');
            IF value_text IN ('', '-', '—') THEN
                IF transform LIKE '%zero%' OR transform LIKE '%dash%' THEN
                    value_text := '0';
                ELSE
                    RETURN NULL;
                END IF;
            END IF;
            BEGIN
                result := value_text::numeric;
            EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
                RETURN NULL;
            END;
            IF negative_parentheses THEN
                result := -result;
            END IF;
            IF raw.sign = '-' THEN
                result := -abs(result);
            END IF;
            IF raw.scale IS NOT NULL THEN
                result := result * power(10::numeric, raw.scale);
            END IF;
            RETURN result;
        END;
        $$;
        """
    )
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
                JOIN sec_raw_xbrl_facts raw ON raw.id = publication.raw_fact_id
                JOIN sec_financial_parse_runs parse_run ON parse_run.id = raw.parse_run_id
                JOIN sec_financial_filings filing ON filing.id = parse_run.filing_id
                JOIN sec_issuer_identities identity ON identity.id = filing.issuer_identity_id
                JOIN sec_metric_mapping_registry mapping
                  ON mapping.mapping_version = publication.mapping_version
                 AND mapping.concept = raw.concept
                WHERE publication.metric_fact_id = NEW.id
                  AND publication.raw_fact_id = NEW.source_ref_id
                  AND publication.status = 'published'
                  AND identity.stock_id = NEW.stock_id
                  AND mapping.canonical_metric_key = NEW.metric_key
                  AND publication.canonical_metric_key = NEW.metric_key
                  AND publication.canonical_unit IS NOT DISTINCT FROM NEW.unit
                  AND publication.period_type IS NOT DISTINCT FROM NEW.period_type
                  AND publication.period_end_date IS NOT DISTINCT FROM NEW.period_end_date
                  AND publication.mapping_version = NEW.value_json->>'mapping_version'
                  AND publication.knowledge_at = (NEW.value_json->>'knowledge_at')::timestamptz
                  AND publication.knowledge_at >= mapping.known_at
                  AND publication.knowledge_at >= greatest(
                    filing.accepted_at, filing.known_at, parse_run.completed_at,
                    parse_run.known_at, parse_run.created_at, raw.created_at
                  )
                  AND publication.decision_json->>'filing_id' = filing.id::text
                  AND publication.decision_json->>'parse_run_id' = parse_run.id::text
                  AND raw.dimensions_json = '{}'::jsonb
                  AND raw.is_nil = false
                  AND (
                    (mapping.value_kind = 'monetary' AND upper(raw.unit_measure) IN ('USD', 'ISO4217:USD') AND NEW.unit = 'USD' AND NEW.currency = 'USD') OR
                    (mapping.value_kind = 'currency_per_share' AND upper(raw.unit_measure) IN ('USD/SHARES', 'USD/XBRLI:SHARES', 'ISO4217:USD/SHARES', 'ISO4217:USD/XBRLI:SHARES') AND NEW.unit = 'USD_per_share' AND NEW.currency = 'USD') OR
                    (mapping.value_kind = 'shares' AND lower(raw.unit_measure) IN ('shares', 'xbrli:shares') AND NEW.unit = 'shares' AND NEW.currency IS NULL)
                  )
                  AND (
                    (
                      publication.publication_role = 'direct'
                      AND NEW.value_json->>'value_basis' = 'as_filed'
                      AND NEW.value_json->>'raw_fact_id' = raw.id::text
                      AND NEW.value_json->>'artifact_id' = raw.artifact_id::text
                      AND normalized_sec_raw_numeric(raw) IS NOT NULL
                      AND normalized_sec_raw_numeric(raw) = NEW.value_numeric::numeric
                      AND publication.period_end_date = coalesce(raw.period_instant, raw.period_end)
                      AND (
                        (mapping.period_basis = 'instant' AND raw.period_instant IS NOT NULL AND (
                          (regexp_replace(filing.form_type, '/A$', '') IN ('10-K', '20-F') AND publication.period_type = 'FY') OR
                          (regexp_replace(filing.form_type, '/A$', '') = '10-Q' AND publication.period_type = 'Q')
                        )) OR
                        (mapping.period_basis = 'duration' AND raw.period_start IS NOT NULL AND raw.period_end IS NOT NULL AND (
                          (regexp_replace(filing.form_type, '/A$', '') IN ('10-K', '20-F') AND publication.period_type = 'FY' AND raw.period_end - raw.period_start + 1 BETWEEN 300 AND 380) OR
                          (regexp_replace(filing.form_type, '/A$', '') = '10-Q' AND publication.period_type = 'Q' AND raw.period_end - raw.period_start + 1 BETWEEN 70 AND 110) OR
                          (regexp_replace(filing.form_type, '/A$', '') = '10-Q' AND publication.period_type = 'YTD' AND raw.period_end - raw.period_start + 1 BETWEEN 150 AND 300)
                        ))
                      )
                    ) OR (
                      publication.publication_role = 'derived_discrete_quarter'
                      AND mapping.period_basis = 'duration'
                      AND regexp_replace(filing.form_type, '/A$', '') = '10-Q'
                      AND raw.period_start IS NOT NULL
                      AND raw.period_end IS NOT NULL
                      AND raw.period_end - raw.period_start + 1 BETWEEN 150 AND 300
                      AND NEW.value_json->>'value_basis' = 'derived_discrete_quarter'
                      AND publication.period_type = 'Q'
                      AND publication.period_end_date = raw.period_end
                      AND NEW.value_json->'input_raw_fact_ids' @> to_jsonb(ARRAY[raw.id])
                      AND jsonb_array_length(NEW.value_json->'input_metric_fact_ids') = 2
                      AND EXISTS (
                        SELECT 1
                        FROM metric_facts prior_input
                        JOIN metric_facts current_input
                          ON current_input.id = (NEW.value_json->'input_metric_fact_ids'->>1)::bigint
                        WHERE prior_input.id = (NEW.value_json->'input_metric_fact_ids'->>0)::bigint
                          AND current_input.source_ref_id = raw.id
                          AND prior_input.stock_id = NEW.stock_id
                          AND current_input.stock_id = NEW.stock_id
                          AND prior_input.metric_key = NEW.metric_key
                          AND current_input.metric_key = NEW.metric_key
                          AND prior_input.currency IS NOT DISTINCT FROM NEW.currency
                          AND current_input.currency IS NOT DISTINCT FROM NEW.currency
                          AND prior_input.period_type = 'YTD'
                          AND current_input.period_type = 'YTD'
                          AND prior_input.period_end_date < current_input.period_end_date
                          AND current_input.period_end_date = NEW.period_end_date
                          AND current_input.value_numeric - prior_input.value_numeric = NEW.value_numeric
                      )
                    )
                  )
            ) THEN
                RAISE EXCEPTION
                    'canonical SEC metric fact conflicts with approved mapping semantics';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    # A stronger validator must also prove every row created under an older
    # revision. A no-op UPDATE invokes the deferred constraint trigger; the
    # migration transaction rolls back unchanged if any legacy row is invalid.
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
    op.execute("SET CONSTRAINTS trg_metric_facts_sec_publication IMMEDIATE")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM sec_metric_publications
                WHERE mapping_version = 'sec-us-gaap-v2'
            ) OR EXISTS (
                SELECT 1 FROM metric_facts
                WHERE source_type = 'sec'
                  AND value_json->>'mapping_version' = 'sec-us-gaap-v2'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade approved SEC mapping registry while v2 lineage exists';
            END IF;
        END;
        $$
        """
    )
    # Restore the identity/field-consistency validator owned by the preceding revision.
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
                JOIN sec_raw_xbrl_facts raw ON raw.id = publication.raw_fact_id
                JOIN sec_financial_parse_runs parse_run ON parse_run.id = raw.parse_run_id
                JOIN sec_financial_filings filing ON filing.id = parse_run.filing_id
                JOIN sec_issuer_identities identity ON identity.id = filing.issuer_identity_id
                WHERE publication.metric_fact_id = NEW.id
                  AND publication.raw_fact_id = NEW.source_ref_id
                  AND publication.status = 'published'
                  AND identity.stock_id = NEW.stock_id
                  AND publication.canonical_metric_key = NEW.metric_key
                  AND publication.canonical_unit IS NOT DISTINCT FROM NEW.unit
                  AND publication.period_type IS NOT DISTINCT FROM NEW.period_type
                  AND publication.period_end_date IS NOT DISTINCT FROM NEW.period_end_date
                  AND publication.mapping_version = NEW.value_json->>'mapping_version'
                  AND publication.knowledge_at = (NEW.value_json->>'knowledge_at')::timestamptz
                  AND publication.decision_json->>'filing_id' = filing.id::text
                  AND publication.decision_json->>'parse_run_id' = parse_run.id::text
            ) THEN
                RAISE EXCEPTION
                    'canonical SEC metric fact conflicts with published mapping lineage';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute("DROP FUNCTION normalized_sec_raw_numeric(sec_raw_xbrl_facts)")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_metric_mapping_registry_no_truncate "
        "ON sec_metric_mapping_registry"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_metric_mapping_registry_immutable_rows "
        "ON sec_metric_mapping_registry"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_metric_mapping_registry_append_only "
        "ON sec_metric_mapping_registry"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS reject_sec_metric_mapping_registry_mutation()"
    )
    op.drop_table("sec_metric_mapping_registry")
