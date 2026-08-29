"""Bind file deletion intents to complete, atomic account erasure.

Revision ID: 20260828220000
Revises: 20260828210000
Create Date: 2026-08-28 22:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828220000"
down_revision = "20260828210000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_erasure_events",
        sa.Column(
            "created_txid",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
    )
    op.add_column(
        "account_erasure_file_deletions",
        sa.Column(
            "created_txid",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
    )

    # Existing rows were already accepted by the prior application contract.
    # Adopt every existing pair into this migration transaction before making
    # all future creation identities database-controlled.
    op.execute(
        "UPDATE account_erasure_events SET created_txid = txid_current(); "
        "UPDATE account_erasure_file_deletions SET created_txid = txid_current();"
    )

    op.execute(
        """
        CREATE FUNCTION stamp_account_erasure_event_creation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.created_at := clock_timestamp();
            NEW.created_txid := txid_current();
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_account_erasure_events_creation_stamp
        BEFORE INSERT ON account_erasure_events
        FOR EACH ROW EXECUTE FUNCTION stamp_account_erasure_event_creation();

        CREATE FUNCTION guard_account_erasure_file_deletion()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'account erasure file-deletion intents are retained';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'pending' OR NEW.attempt_count <> 0
                   OR NEW.deleted_at IS NOT NULL THEN
                    RAISE EXCEPTION 'new account erasure file-deletion intent must be pending';
                END IF;
                NEW.created_at := clock_timestamp();
                NEW.updated_at := NEW.created_at;
                NEW.created_txid := txid_current();
                RETURN NEW;
            END IF;
            IF OLD.status = 'deleted' THEN
                RAISE EXCEPTION 'completed account erasure file-deletion intents are immutable';
            END IF;
            IF NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.document_id IS DISTINCT FROM OLD.document_id
               OR NEW.storage_path_hash IS DISTINCT FROM OLD.storage_path_hash
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.created_txid IS DISTINCT FROM OLD.created_txid THEN
                RAISE EXCEPTION 'account erasure file-deletion identity is immutable';
            END IF;
            IF NEW.storage_path IS DISTINCT FROM OLD.storage_path
               AND NOT (NEW.status = 'deleted' AND NEW.storage_path = '[deleted]') THEN
                RAISE EXCEPTION 'account erasure file-deletion target is immutable';
            END IF;
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_account_erasure_file_deletions_guard
        BEFORE INSERT OR UPDATE OR DELETE ON account_erasure_file_deletions
        FOR EACH ROW EXECUTE FUNCTION guard_account_erasure_file_deletion();

        CREATE FUNCTION reject_account_erasure_file_deletion_truncate()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'account erasure file-deletion intents are retained';
        END;
        $$;

        CREATE TRIGGER trg_account_erasure_file_deletions_no_truncate
        BEFORE TRUNCATE ON account_erasure_file_deletions
        FOR EACH STATEMENT EXECUTE FUNCTION reject_account_erasure_file_deletion_truncate();
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_pdf_document_lifecycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.lifecycle_state <> 'active'
                   OR NEW.retired_at IS NOT NULL
                   OR NEW.retired_by_user_id IS NOT NULL
                   OR NEW.retirement_reason IS NOT NULL THEN
                    RAISE EXCEPTION 'new pdf_documents must begin active';
                END IF;
                RETURN NEW;
            END IF;
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

        DROP TRIGGER IF EXISTS trg_pdf_documents_lifecycle ON pdf_documents;
        CREATE TRIGGER trg_pdf_documents_lifecycle
        BEFORE INSERT OR UPDATE OR DELETE ON pdf_documents
        FOR EACH ROW EXECUTE FUNCTION enforce_pdf_document_lifecycle();
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_pdf_document_erasure_audit()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            event_txid bigint;
            deletion account_erasure_file_deletions%ROWTYPE;
        BEGIN
            IF NEW.lifecycle_state = 'erased' AND OLD.lifecycle_state <> 'erased' THEN
                SELECT event.created_txid INTO event_txid
                FROM account_erasure_events event
                WHERE event.user_id = NEW.user_id;

                SELECT * INTO deletion
                FROM account_erasure_file_deletions candidate
                WHERE candidate.user_id = NEW.user_id
                  AND candidate.document_id = NEW.id;

                IF event_txid IS NULL OR deletion.id IS NULL
                   OR event_txid <> txid_current()
                   OR deletion.created_txid <> txid_current()
                   OR deletion.storage_path IS DISTINCT FROM OLD.file_storage_key
                   OR deletion.status <> 'pending'
                   OR deletion.attempt_count <> 0 THEN
                    RAISE EXCEPTION
                        'erased pdf_document requires atomic account erasure audit and file-deletion intent';
                END IF;

                IF NEW.retired_at IS NULL
                   OR NEW.retired_by_user_id IS DISTINCT FROM NEW.user_id
                   OR NEW.retirement_reason <> 'account_erasure'
                   OR NEW.file_storage_key IS DISTINCT FROM ('erased/document/' || NEW.id)
                   OR NEW.file_name IS DISTINCT FROM ('erased-document-' || NEW.id)
                   OR NEW.source IS DISTINCT FROM 'account_erasure_tombstone'
                   OR NEW.raw_text IS NOT NULL
                   OR NEW.notes IS NOT NULL
                   OR EXISTS (
                       SELECT 1 FROM document_pages page
                       WHERE page.document_id = NEW.id
                         AND (page.page_text IS NOT NULL OR page.page_image_key IS NOT NULL)
                   )
                   OR EXISTS (
                       SELECT 1 FROM metric_extractions extraction
                       WHERE extraction.document_id = NEW.id
                         AND (
                             extraction.raw_value_text IS NOT NULL OR
                             extraction.original_text_snippet IS NOT NULL OR
                             extraction.parsed_value_json IS NOT NULL OR
                             extraction.bbox_json IS NOT NULL
                         )
                   )
                   OR EXISTS (
                       SELECT 1 FROM metric_facts fact
                       WHERE fact.source_document_id = NEW.id
                         AND fact.is_current = true
                   ) THEN
                    RAISE EXCEPTION
                        'erased pdf_document requires complete private-content redaction';
                END IF;
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE FUNCTION validate_account_erasure_file_deletion()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pdf_documents document
                JOIN account_erasure_events event
                  ON event.user_id = document.user_id
                WHERE document.id = NEW.document_id
                  AND document.user_id = NEW.user_id
                  AND document.lifecycle_state = 'erased'
                  AND document.retired_by_user_id = NEW.user_id
                  AND document.retirement_reason = 'account_erasure'
                  AND document.file_storage_key = ('erased/document/' || document.id)
                  AND document.file_name = ('erased-document-' || document.id)
                  AND document.source = 'account_erasure_tombstone'
                  AND document.raw_text IS NULL
                  AND document.notes IS NULL
            ) OR EXISTS (
                SELECT 1 FROM document_pages page
                WHERE page.document_id = NEW.document_id
                  AND (page.page_text IS NOT NULL OR page.page_image_key IS NOT NULL)
            ) OR EXISTS (
                SELECT 1 FROM metric_extractions extraction
                WHERE extraction.document_id = NEW.document_id
                  AND (
                      extraction.raw_value_text IS NOT NULL OR
                      extraction.original_text_snippet IS NOT NULL OR
                      extraction.parsed_value_json IS NOT NULL OR
                      extraction.bbox_json IS NOT NULL
                  )
            ) OR EXISTS (
                SELECT 1 FROM metric_facts fact
                WHERE fact.source_document_id = NEW.document_id
                  AND fact.is_current = true
            ) THEN
                RAISE EXCEPTION
                    'file deletion intent requires verified erased document with complete redaction';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_account_erasure_file_deletions_validate
        AFTER INSERT OR UPDATE ON account_erasure_file_deletions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_account_erasure_file_deletion();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM account_erasure_events)
               OR EXISTS (SELECT 1 FROM account_erasure_file_deletions) THEN
                RAISE EXCEPTION
                    'cannot downgrade erasure intent integrity while erasure history exists';
            END IF;
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_account_erasure_file_deletions_validate
            ON account_erasure_file_deletions;
        DROP FUNCTION IF EXISTS validate_account_erasure_file_deletion();
        DROP TRIGGER IF EXISTS trg_account_erasure_file_deletions_no_truncate
            ON account_erasure_file_deletions;
        DROP FUNCTION IF EXISTS reject_account_erasure_file_deletion_truncate();
        DROP TRIGGER IF EXISTS trg_account_erasure_file_deletions_guard
            ON account_erasure_file_deletions;
        DROP FUNCTION IF EXISTS guard_account_erasure_file_deletion();
        DROP TRIGGER IF EXISTS trg_account_erasure_events_creation_stamp
            ON account_erasure_events;
        DROP FUNCTION IF EXISTS stamp_account_erasure_event_creation();
        """
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

        DROP TRIGGER IF EXISTS trg_pdf_documents_lifecycle ON pdf_documents;
        CREATE TRIGGER trg_pdf_documents_lifecycle
        BEFORE UPDATE OR DELETE ON pdf_documents
        FOR EACH ROW EXECUTE FUNCTION enforce_pdf_document_lifecycle();
        """
    )

    op.execute(
        """
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
        """
    )

    op.drop_column("account_erasure_file_deletions", "created_txid")
    op.drop_column("account_erasure_events", "created_txid")
