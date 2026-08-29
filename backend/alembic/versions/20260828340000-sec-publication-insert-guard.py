"""Validate every published SEC decision at its own insert boundary.

Revision ID: 20260828340000
Revises: 20260828330000
Create Date: 2026-08-29 10:00:00
"""

from alembic import op


revision = "20260828340000"
down_revision = "20260828330000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT metric_fact_id
                  FROM sec_metric_publications
                 WHERE status = 'published'
                 GROUP BY metric_fact_id
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'existing SEC metric fact has multiple published decisions';
            END IF;
        END;
        $$;

        CREATE UNIQUE INDEX uq_sec_metric_publications_published_fact
        ON sec_metric_publications (metric_fact_id)
        WHERE status = 'published';

        CREATE FUNCTION validate_sec_metric_publication_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.status = 'published' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM metric_facts fact
                     WHERE fact.id = NEW.metric_fact_id
                       AND fact.source_type = 'sec'
                ) THEN
                    RAISE EXCEPTION
                        'published SEC decision must reference a canonical SEC metric fact';
                END IF;

                -- Re-run every canonical fact constraint against this newly
                -- inserted decision. The partial unique index above guarantees
                -- that an older valid publication cannot mask this row.
                UPDATE metric_facts
                   SET is_current = is_current
                 WHERE id = NEW.metric_fact_id;
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_sec_metric_publications_insert_valid
        AFTER INSERT ON sec_metric_publications
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_sec_metric_publication_insert();
        """
    )
    # Close the upgrade window as well as future writes. Revalidate only
    # registered/approved mappings so intentionally retained v1 history stays
    # quarantined rather than being rewritten or deleted.
    op.execute(
        """
        UPDATE metric_facts fact
           SET is_current = fact.is_current
         WHERE fact.source_type = 'sec'
           AND EXISTS (
                SELECT 1
                  FROM sec_metric_publications publication
                  JOIN sec_metric_mapping_registry mapping
                    ON mapping.mapping_version = publication.mapping_version
                   AND mapping.canonical_metric_key =
                       publication.canonical_metric_key
                 WHERE publication.metric_fact_id = fact.id
                   AND publication.status = 'published'
           )
        """
    )
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM sec_metric_publications
                 WHERE status = 'published'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade SEC publication insert guard while published lineage exists';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sec_metric_publications_insert_valid "
        "ON sec_metric_publications"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_sec_metric_publication_insert()")
    op.execute("DROP INDEX IF EXISTS uq_sec_metric_publications_published_fact")
