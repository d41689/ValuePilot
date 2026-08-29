"""Prevent TRUNCATE bypasses on financial-truth and audit lineage.

Revision ID: 20260828230000
Revises: 20260828220000
Create Date: 2026-08-28 23:00:00
"""

from alembic import op


revision = "20260828230000"
down_revision = "20260828220000"
branch_labels = None
depends_on = None


_PROTECTED_TABLES = (
    "account_erasure_events",
    "company_analysis_classifications",
    "stock_prices",
    "pdf_documents",
    "document_pages",
    "metric_extractions",
    "metric_facts",
    "calculated_runs",
    "sec_issuer_identities",
    "sec_financial_filings",
    "sec_filing_artifacts",
    "sec_financial_parse_runs",
    "sec_financial_parse_run_artifacts",
    "sec_raw_xbrl_facts",
    "sec_metric_publications",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_financial_truth_truncate()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '% is retained financial-truth lineage; TRUNCATE is forbidden',
                TG_TABLE_NAME;
        END;
        $$;
        """
    )
    for table_name in _PROTECTED_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_no_truncate
            BEFORE TRUNCATE ON {table_name}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_financial_truth_truncate()
            """
        )


def downgrade() -> None:
    protected_history_checks = "\n               OR ".join(
        f"EXISTS (SELECT 1 FROM {table_name})"
        for table_name in _PROTECTED_TABLES
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF {protected_history_checks} THEN
                RAISE EXCEPTION
                    'cannot downgrade financial-truth truncate guards while protected history exists';
            END IF;
        END;
        $$;
        """
    )
    for table_name in reversed(_PROTECTED_TABLES):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_no_truncate ON {table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS reject_financial_truth_truncate()")
