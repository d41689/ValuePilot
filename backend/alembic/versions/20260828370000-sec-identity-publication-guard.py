"""Require a current reviewed SEC identity for canonical publication.

Revision ID: 20260828370000
Revises: 20260828360000
Create Date: 2026-08-29 13:00:00
"""

from alembic import op


revision = "20260828370000"
down_revision = "20260828360000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A later identity retirement invalidates the current product projection,
    # not the retained historical fact.
    op.execute(
        """
        UPDATE metric_facts fact
           SET is_current = false
         WHERE fact.source_type = 'sec'
           AND fact.is_current = true
           AND NOT EXISTS (
                SELECT 1
                  FROM sec_metric_publications publication
                  JOIN sec_raw_xbrl_facts raw
                    ON raw.id = publication.raw_fact_id
                  JOIN sec_financial_parse_runs parse_run
                    ON parse_run.id = raw.parse_run_id
                  JOIN sec_financial_filings filing
                    ON filing.id = parse_run.filing_id
                  JOIN sec_issuer_identities filing_identity
                    ON filing_identity.id = filing.issuer_identity_id
                 WHERE publication.metric_fact_id = fact.id
                   AND publication.status = 'published'
                   AND EXISTS (
                        SELECT 1
                          FROM sec_issuer_identities current_identity
                         WHERE current_identity.stock_id = fact.stock_id
                           AND current_identity.cik = filing_identity.cik
                           AND current_identity.status = 'reviewed'
                           AND current_identity.known_at <= clock_timestamp()
                           AND current_identity.effective_from <=
                               coalesce(filing.report_date, filing.filed_on)
                           AND (
                                current_identity.effective_to IS NULL
                                OR current_identity.effective_to >=
                                   coalesce(filing.report_date, filing.filed_on)
                           )
                           AND NOT EXISTS (
                                SELECT 1
                                  FROM sec_issuer_identities successor
                                 WHERE successor.supersedes_identity_id =
                                       current_identity.id
                                   AND successor.known_at <= clock_timestamp()
                           )
                   )
           );

        CREATE FUNCTION validate_sec_metric_fact_identity()
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
                  JOIN sec_issuer_identities filing_identity
                    ON filing_identity.id = filing.issuer_identity_id
                 WHERE publication.metric_fact_id = NEW.id
                   AND publication.status = 'published'
                   AND EXISTS (
                        SELECT 1
                          FROM sec_issuer_identities current_identity
                         WHERE current_identity.stock_id = NEW.stock_id
                           AND current_identity.cik = filing_identity.cik
                           AND current_identity.status = 'reviewed'
                           AND current_identity.known_at <= publication.knowledge_at
                           AND current_identity.effective_from <=
                               coalesce(filing.report_date, filing.filed_on)
                           AND (
                                current_identity.effective_to IS NULL
                                OR current_identity.effective_to >=
                                   coalesce(filing.report_date, filing.filed_on)
                           )
                           AND NOT EXISTS (
                                SELECT 1
                                  FROM sec_issuer_identities successor
                                 WHERE successor.supersedes_identity_id =
                                       current_identity.id
                                   AND successor.known_at <= publication.knowledge_at
                           )
                   )
            ) THEN
                RAISE EXCEPTION
                    'canonical SEC metric fact requires reviewed effective issuer identity';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_metric_facts_sec_identity_valid
        AFTER INSERT OR UPDATE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_sec_metric_fact_identity();

        CREATE FUNCTION validate_sec_identity_current_projection()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM metric_facts fact
                  JOIN sec_metric_publications publication
                    ON publication.metric_fact_id = fact.id
                  JOIN sec_raw_xbrl_facts raw
                    ON raw.id = publication.raw_fact_id
                  JOIN sec_financial_parse_runs parse_run
                    ON parse_run.id = raw.parse_run_id
                  JOIN sec_financial_filings filing
                    ON filing.id = parse_run.filing_id
                  JOIN sec_issuer_identities filing_identity
                    ON filing_identity.id = filing.issuer_identity_id
                 WHERE fact.source_type = 'sec'
                   AND fact.is_current = true
                   AND fact.stock_id = NEW.stock_id
                   AND filing_identity.cik = NEW.cik
                   AND NOT EXISTS (
                        SELECT 1
                          FROM sec_issuer_identities current_identity
                         WHERE current_identity.stock_id = fact.stock_id
                           AND current_identity.cik = filing_identity.cik
                           AND current_identity.status = 'reviewed'
                           AND current_identity.known_at <= clock_timestamp()
                           AND current_identity.effective_from <=
                               coalesce(filing.report_date, filing.filed_on)
                           AND (
                                current_identity.effective_to IS NULL
                                OR current_identity.effective_to >=
                                   coalesce(filing.report_date, filing.filed_on)
                           )
                           AND NOT EXISTS (
                                SELECT 1
                                  FROM sec_issuer_identities successor
                                 WHERE successor.supersedes_identity_id =
                                       current_identity.id
                                   AND successor.known_at <= clock_timestamp()
                           )
                   )
            ) THEN
                RAISE EXCEPTION
                    'SEC identity transition must demote ineligible canonical facts';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_sec_identity_current_projection_valid
        AFTER INSERT ON sec_issuer_identities
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_sec_identity_current_projection();

        SET CONSTRAINTS ALL IMMEDIATE;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM metric_facts WHERE source_type = 'sec'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade SEC identity publication guard while SEC facts exist';
            END IF;
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_sec_identity_current_projection_valid
            ON sec_issuer_identities;
        DROP FUNCTION IF EXISTS validate_sec_identity_current_projection();
        DROP TRIGGER IF EXISTS trg_metric_facts_sec_identity_valid
            ON metric_facts;
        DROP FUNCTION IF EXISTS validate_sec_metric_fact_identity();
        """
    )
