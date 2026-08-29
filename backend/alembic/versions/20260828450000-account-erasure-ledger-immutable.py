"""Make the completed account-erasure ledger unconditionally immutable.

Revision ID: 20260828450000
Revises: 20260828440000
Create Date: 2026-08-29 20:00:00
"""

from alembic import op


revision = "20260828450000"
down_revision = "20260828440000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_account_erasure_events_append_only
            ON account_erasure_events;

        CREATE FUNCTION reject_account_erasure_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'account_erasure_events is append-only; % is forbidden', TG_OP
                USING ERRCODE = '23514';
        END;
        $$;

        CREATE TRIGGER trg_account_erasure_events_append_only
        BEFORE UPDATE OR DELETE ON account_erasure_events
        FOR EACH ROW EXECUTE FUNCTION reject_account_erasure_event_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM account_erasure_events) THEN
                RAISE EXCEPTION
                    'cannot restore erasure-ledger bypass while erasure history exists';
            END IF;
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_account_erasure_events_append_only
            ON account_erasure_events;
        DROP FUNCTION IF EXISTS reject_account_erasure_event_mutation();

        CREATE TRIGGER trg_account_erasure_events_append_only
        BEFORE UPDATE OR DELETE ON account_erasure_events
        FOR EACH ROW EXECUTE FUNCTION reject_research_append_only_mutation();
        """
    )
