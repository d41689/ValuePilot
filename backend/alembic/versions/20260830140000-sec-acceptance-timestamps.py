"""Stamp SEC ingestion operation attempt time in PostgreSQL.

Revision ID: 20260830140000
Revises: 20260830130000
Create Date: 2026-08-30 14:00:00.000000
"""

from alembic import op


revision = "20260830140000"
down_revision = "20260830130000"
branch_labels = None
depends_on = None


_STAMPED_OPERATION_GUARD = """
CREATE OR REPLACE FUNCTION guard_sec_financial_operation_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    operation_identity sec_issuer_identities%ROWTYPE;
BEGIN
    NEW.attempted_at := clock_timestamp();
    NEW.created_at := NEW.attempted_at;
    NEW.created_txid := txid_current();
    SELECT * INTO operation_identity
    FROM sec_issuer_identities
    WHERE id = NEW.issuer_identity_id;
    IF operation_identity.id IS NULL THEN
        RAISE EXCEPTION 'operation requires reviewed SEC issuer identity';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('sec-issuer-cik:' || operation_identity.cik, 0)
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'sec-issuer-stock:' || operation_identity.stock_id::text, 0
        )
    );
    SELECT * INTO operation_identity
    FROM sec_issuer_identities
    WHERE id = NEW.issuer_identity_id
    FOR SHARE;
    IF operation_identity.status <> 'reviewed'
       OR operation_identity.known_at > NEW.attempted_at
       OR EXISTS (
           SELECT 1 FROM sec_issuer_identities child
           WHERE child.supersedes_identity_id = operation_identity.id
             AND child.known_at <= NEW.attempted_at
       ) THEN
        RAISE EXCEPTION 'operation requires current reviewed SEC issuer identity';
    END IF;
    RETURN NEW;
END;
$$
"""


_CALLER_ATTEMPT_OPERATION_GUARD = """
CREATE OR REPLACE FUNCTION guard_sec_financial_operation_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    operation_identity sec_issuer_identities%ROWTYPE;
BEGIN
    NEW.created_at := clock_timestamp();
    NEW.created_txid := txid_current();
    SELECT * INTO operation_identity
    FROM sec_issuer_identities
    WHERE id = NEW.issuer_identity_id;
    IF operation_identity.id IS NULL THEN
        RAISE EXCEPTION 'operation requires reviewed SEC issuer identity';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('sec-issuer-cik:' || operation_identity.cik, 0)
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'sec-issuer-stock:' || operation_identity.stock_id::text, 0
        )
    );
    SELECT * INTO operation_identity
    FROM sec_issuer_identities
    WHERE id = NEW.issuer_identity_id
    FOR SHARE;
    IF operation_identity.status <> 'reviewed'
       OR operation_identity.known_at > NEW.attempted_at
       OR EXISTS (
           SELECT 1 FROM sec_issuer_identities child
           WHERE child.supersedes_identity_id = operation_identity.id
             AND child.known_at <= NEW.attempted_at
       ) THEN
        RAISE EXCEPTION 'operation requires current reviewed SEC issuer identity';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.execute(_STAMPED_OPERATION_GUARD)


def downgrade() -> None:
    op.execute(_CALLER_ATTEMPT_OPERATION_GUARD)
