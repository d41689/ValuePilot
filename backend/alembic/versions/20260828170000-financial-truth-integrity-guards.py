"""Close lifecycle, erasure, and analysis-classification DB bypasses.

Revision ID: 20260828170000
Revises: 20260828160000
Create Date: 2026-08-28 17:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828170000"
down_revision = "20260828160000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_erasure_file_deletions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("storage_path_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_class", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'deleted', 'failed')",
            name="ck_account_erasure_file_deletions_status",
        ),
        sa.CheckConstraint(
            "(status = 'deleted' AND deleted_at IS NOT NULL AND storage_path = '[deleted]') OR "
            "(status <> 'deleted' AND deleted_at IS NULL AND storage_path <> '[deleted]')",
            name="ck_account_erasure_file_deletions_shape",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["pdf_documents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", name="uq_account_erasure_file_deletions_document"
        ),
    )
    op.create_index(
        "ix_account_erasure_file_deletions_status",
        "account_erasure_file_deletions",
        ["status", "id"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_pdf_document_lifecycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'pdf_documents are retained; use lifecycle retirement';
            END IF;
            IF OLD.lifecycle_state = 'erased' THEN
                RAISE EXCEPTION 'erased pdf_document tombstones are immutable';
            END IF;
            IF NEW.lifecycle_state = 'erased' AND OLD.lifecycle_state <> 'erased' THEN
                IF current_setting('valuepilot.account_erasure', true) IS DISTINCT FROM 'on'
                   OR NEW.retirement_reason <> 'account_erasure'
                   OR NEW.retired_by_user_id IS DISTINCT FROM OLD.user_id THEN
                    RAISE EXCEPTION 'erased lifecycle requires audited account erasure';
                END IF;
            END IF;
            IF OLD.lifecycle_state = 'archived' THEN
                IF NEW.lifecycle_state = 'active' THEN
                    RAISE EXCEPTION 'archived pdf_documents cannot return to active';
                END IF;
                IF NEW.lifecycle_state = 'archived' AND (
                    NEW.retired_at IS DISTINCT FROM OLD.retired_at OR
                    NEW.retired_by_user_id IS DISTINCT FROM OLD.retired_by_user_id OR
                    NEW.retirement_reason IS DISTINCT FROM OLD.retirement_reason
                ) THEN
                    RAISE EXCEPTION 'archived pdf_document retirement metadata is immutable';
                END IF;
            END IF;
            IF OLD.lifecycle_state = 'active' AND NEW.lifecycle_state = 'active' AND (
                NEW.retired_at IS DISTINCT FROM OLD.retired_at OR
                NEW.retired_by_user_id IS DISTINCT FROM OLD.retired_by_user_id OR
                NEW.retirement_reason IS DISTINCT FROM OLD.retirement_reason
            ) THEN
                RAISE EXCEPTION 'active pdf_documents cannot carry retirement metadata';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE OR REPLACE FUNCTION validate_pdf_document_erasure_audit()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.lifecycle_state = 'erased' AND OLD.lifecycle_state <> 'erased' AND (
                NOT EXISTS (
                    SELECT 1 FROM account_erasure_events event
                    WHERE event.user_id = NEW.user_id
                ) OR NOT EXISTS (
                    SELECT 1 FROM account_erasure_file_deletions deletion
                    WHERE deletion.user_id = NEW.user_id
                      AND deletion.document_id = NEW.id
                )
            ) THEN
                RAISE EXCEPTION
                    'erased pdf_document requires account erasure audit and file-deletion intent';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_pdf_documents_erasure_audit
        AFTER UPDATE ON pdf_documents
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_pdf_document_erasure_audit();
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM company_analysis_classifications left_row
                JOIN company_analysis_classifications right_row
                  ON left_row.stock_id = right_row.stock_id
                 AND left_row.id < right_row.id
                 AND (left_row.effective_to IS NULL OR right_row.effective_from <= left_row.effective_to)
                 AND (right_row.effective_to IS NULL OR left_row.effective_from <= right_row.effective_to)
                WHERE NOT EXISTS (
                    SELECT 1 FROM company_analysis_classifications child
                    WHERE child.supersedes_classification_id = left_row.id
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM company_analysis_classifications child
                    WHERE child.supersedes_classification_id = right_row.id
                )
            ) THEN
                RAISE EXCEPTION 'existing overlapping terminal company analysis classifications';
            END IF;
        END;
        $$;

        CREATE FUNCTION validate_company_analysis_classification_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent company_analysis_classifications%ROWTYPE;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended('company-analysis-classification:' || NEW.stock_id, 0)
            );
            IF NEW.supersedes_classification_id IS NOT NULL THEN
                SELECT * INTO parent
                FROM company_analysis_classifications
                WHERE id = NEW.supersedes_classification_id
                FOR SHARE;
                IF NOT FOUND OR parent.stock_id <> NEW.stock_id
                   OR NEW.known_at <= parent.known_at
                   OR EXISTS (
                       SELECT 1 FROM company_analysis_classifications child
                       WHERE child.supersedes_classification_id = parent.id
                   ) THEN
                    RAISE EXCEPTION 'invalid or stale classification supersession';
                END IF;
            END IF;
            IF EXISTS (
                SELECT 1
                FROM company_analysis_classifications existing
                WHERE existing.stock_id = NEW.stock_id
                  AND existing.id IS DISTINCT FROM NEW.supersedes_classification_id
                  AND NOT EXISTS (
                      SELECT 1 FROM company_analysis_classifications child
                      WHERE child.supersedes_classification_id = existing.id
                  )
                  AND (existing.effective_to IS NULL OR NEW.effective_from <= existing.effective_to)
                  AND (NEW.effective_to IS NULL OR existing.effective_from <= NEW.effective_to)
            ) THEN
                RAISE EXCEPTION 'overlapping terminal company analysis classification';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_company_analysis_classifications_insert_guard
        BEFORE INSERT ON company_analysis_classifications
        FOR EACH ROW EXECUTE FUNCTION validate_company_analysis_classification_insert();
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM metric_facts fact
                WHERE fact.source_type = 'sec'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM sec_metric_publications publication
                      WHERE publication.metric_fact_id = fact.id
                        AND publication.raw_fact_id = fact.source_ref_id
                        AND publication.status = 'published'
                  )
            ) THEN
                RAISE EXCEPTION
                    'existing canonical SEC metric fact lacks published mapping lineage';
            END IF;
        END;
        $$;

        CREATE FUNCTION enforce_sec_metric_fact_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.source_type = 'sec' THEN
                    RAISE EXCEPTION 'canonical SEC metric facts are retained';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.source_type = 'sec' AND (
                to_jsonb(NEW) - 'is_current' - 'updated_at'
                IS DISTINCT FROM
                to_jsonb(OLD) - 'is_current' - 'updated_at'
            ) THEN
                RAISE EXCEPTION
                    'canonical SEC metric fact provenance and value are immutable';
            END IF;
            IF OLD.source_type = 'sec'
               AND OLD.is_current = false
               AND NEW.is_current = true THEN
                RAISE EXCEPTION
                    'retired canonical SEC metric facts cannot be restored to current';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_metric_facts_sec_immutable
        BEFORE UPDATE OR DELETE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION enforce_sec_metric_fact_immutability();

        CREATE FUNCTION validate_sec_metric_fact_publication()
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

        CREATE CONSTRAINT TRIGGER trg_metric_facts_sec_publication
        AFTER INSERT OR UPDATE ON metric_facts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_sec_metric_fact_publication();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM account_erasure_file_deletions)
               OR EXISTS (
                   SELECT 1 FROM pdf_documents
                   WHERE lifecycle_state <> 'active'
               )
               OR EXISTS (SELECT 1 FROM company_analysis_classifications)
               OR EXISTS (
                   SELECT 1 FROM research_coverage_requirements
                   WHERE kind = 'method_applicability' OR state = 'unsupported'
               )
               OR EXISTS (SELECT 1 FROM sec_metric_publications)
               OR EXISTS (SELECT 1 FROM metric_facts WHERE source_type = 'sec') THEN
                RAISE EXCEPTION
                    'cannot downgrade financial-truth integrity while protected state exists';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_sec_publication ON metric_facts"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_sec_metric_fact_publication()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_sec_immutable ON metric_facts"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_sec_metric_fact_immutability()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_company_analysis_classifications_insert_guard "
        "ON company_analysis_classifications"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_company_analysis_classification_insert()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_pdf_documents_erasure_audit ON pdf_documents"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_pdf_document_erasure_audit()")
    op.drop_index(
        "ix_account_erasure_file_deletions_status",
        table_name="account_erasure_file_deletions",
    )
    op.drop_table("account_erasure_file_deletions")
    # Restores the guard definition owned by the preceding revision.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_pdf_document_lifecycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'pdf_documents are retained; use lifecycle retirement';
            END IF;

            IF OLD.lifecycle_state = 'erased' THEN
                RAISE EXCEPTION 'erased pdf_document tombstones are immutable';
            END IF;

            IF OLD.lifecycle_state = 'archived' THEN
                IF NEW.lifecycle_state = 'active' THEN
                    RAISE EXCEPTION 'archived pdf_documents cannot return to active';
                END IF;
                IF NEW.lifecycle_state = 'archived' AND (
                    NEW.retired_at IS DISTINCT FROM OLD.retired_at OR
                    NEW.retired_by_user_id IS DISTINCT FROM OLD.retired_by_user_id OR
                    NEW.retirement_reason IS DISTINCT FROM OLD.retirement_reason
                ) THEN
                    RAISE EXCEPTION 'archived pdf_document retirement metadata is immutable';
                END IF;
            END IF;

            IF OLD.lifecycle_state = 'active' AND NEW.lifecycle_state = 'active' AND (
                NEW.retired_at IS DISTINCT FROM OLD.retired_at OR
                NEW.retired_by_user_id IS DISTINCT FROM OLD.retired_by_user_id OR
                NEW.retirement_reason IS DISTINCT FROM OLD.retirement_reason
            ) THEN
                RAISE EXCEPTION 'active pdf_documents cannot carry retirement metadata';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
