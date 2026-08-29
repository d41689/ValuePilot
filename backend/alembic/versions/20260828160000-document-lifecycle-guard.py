"""Enforce irreversible document retirement transitions.

Revision ID: 20260828160000
Revises: 20260828150000
Create Date: 2026-08-28 16:00:00
"""

from alembic import op


revision = "20260828160000"
down_revision = "20260828150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
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

        CREATE TRIGGER trg_pdf_documents_lifecycle
        BEFORE UPDATE OR DELETE ON pdf_documents
        FOR EACH ROW EXECUTE FUNCTION enforce_pdf_document_lifecycle();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pdf_documents
                WHERE lifecycle_state <> 'active'
                   OR retired_at IS NOT NULL
                   OR retired_by_user_id IS NOT NULL
                   OR retirement_reason IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade document lifecycle guard while retirement history exists';
            END IF;
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_pdf_documents_lifecycle ON pdf_documents")
    op.execute("DROP FUNCTION IF EXISTS enforce_pdf_document_lifecycle()")
