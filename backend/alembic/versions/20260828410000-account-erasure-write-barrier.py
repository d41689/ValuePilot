"""Make completed account erasure a database-enforced write barrier.

Revision ID: 20260828410000
Revises: 20260828400000
Create Date: 2026-08-29 17:00:00
"""

from alembic import op


revision = "20260828410000"
down_revision = "20260828400000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_erased_account_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_user_id bigint;
            prior_owner_id bigint;
            erasure_txid bigint;
            account_is_active boolean;
        BEGIN
            IF TG_ARGV[0] = 'direct_user' THEN
                target_user_id := NULLIF(to_jsonb(NEW)->>'user_id', '')::bigint;
                IF TG_OP = 'UPDATE' THEN
                    prior_owner_id := NULLIF(to_jsonb(OLD)->>'user_id', '')::bigint;
                END IF;
            ELSIF TG_ARGV[0] = 'research_case' THEN
                SELECT user_id
                  INTO target_user_id
                  FROM research_cases
                 WHERE id = NULLIF(to_jsonb(NEW)->>'case_id', '')::bigint;
                IF TG_OP = 'UPDATE'
                   AND to_jsonb(NEW)->>'case_id' IS DISTINCT FROM
                       to_jsonb(OLD)->>'case_id' THEN
                    RAISE EXCEPTION 'user-owned lineage cannot change research case'
                        USING ERRCODE = '23514';
                END IF;
            ELSE
                RAISE EXCEPTION 'unknown erased-account guard mode: %', TG_ARGV[0];
            END IF;

            -- Shared/global facts have no user privacy owner and are outside
            -- this barrier. Every user-owned row serializes with erasure even
            -- when written through raw SQL rather than the application.
            IF target_user_id IS NULL THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE'
               AND TG_ARGV[0] = 'direct_user'
               AND prior_owner_id IS DISTINCT FROM target_user_id THEN
                RAISE EXCEPTION 'user-owned rows cannot change owner'
                    USING ERRCODE = '23514';
            END IF;
            PERFORM pg_advisory_xact_lock(
                hashtextextended('account-erasure:' || target_user_id::text, 0)
            );

            SELECT is_active
              INTO account_is_active
              FROM users
             WHERE id = target_user_id;
            SELECT created_txid
              INTO erasure_txid
              FROM account_erasure_events
             WHERE user_id = target_user_id;

            -- The audited erasure transaction itself must redact/tombstone
            -- existing rows. Its transaction-local setting is accepted only
            -- before the durable event exists. Once the event is inserted,
            -- even that transaction cannot append more user-owned content.
            IF current_setting('valuepilot.account_erasure', true) = 'on'
               AND erasure_txid IS NULL THEN
                RETURN NEW;
            END IF;

            IF account_is_active IS DISTINCT FROM true OR erasure_txid IS NOT NULL THEN
                RAISE EXCEPTION
                    'completed account erasure forbids user-owned mutations'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_research_cases_erasure_barrier
        BEFORE INSERT OR UPDATE ON research_cases
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');

        CREATE TRIGGER trg_research_case_origins_erasure_barrier
        BEFORE INSERT OR UPDATE ON research_case_origins
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('research_case');

        CREATE TRIGGER trg_research_case_revisions_erasure_barrier
        BEFORE INSERT OR UPDATE ON research_case_revisions
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('research_case');

        CREATE TRIGGER trg_research_case_events_erasure_barrier
        BEFORE INSERT OR UPDATE ON research_case_events
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('research_case');

        CREATE TRIGGER trg_manual_portfolios_erasure_barrier
        BEFORE INSERT OR UPDATE ON manual_portfolios
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');

        CREATE TRIGGER trg_manual_positions_erasure_barrier
        BEFORE INSERT OR UPDATE ON manual_positions
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');

        CREATE TRIGGER trg_position_journal_events_erasure_barrier
        BEFORE INSERT OR UPDATE ON position_journal_events
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');

        CREATE TRIGGER trg_metric_facts_erasure_barrier
        BEFORE INSERT OR UPDATE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION guard_erased_account_mutation('direct_user');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM account_erasure_events) THEN
                RAISE EXCEPTION
                    'cannot remove account-erasure write barrier while erasure history exists';
            END IF;
        END;
        $$;
        DROP TRIGGER IF EXISTS trg_metric_facts_erasure_barrier ON metric_facts;
        DROP TRIGGER IF EXISTS trg_position_journal_events_erasure_barrier
            ON position_journal_events;
        DROP TRIGGER IF EXISTS trg_manual_positions_erasure_barrier
            ON manual_positions;
        DROP TRIGGER IF EXISTS trg_manual_portfolios_erasure_barrier
            ON manual_portfolios;
        DROP TRIGGER IF EXISTS trg_research_case_events_erasure_barrier
            ON research_case_events;
        DROP TRIGGER IF EXISTS trg_research_case_revisions_erasure_barrier
            ON research_case_revisions;
        DROP TRIGGER IF EXISTS trg_research_case_origins_erasure_barrier
            ON research_case_origins;
        DROP TRIGGER IF EXISTS trg_research_cases_erasure_barrier
            ON research_cases;
        DROP FUNCTION IF EXISTS guard_erased_account_mutation();
        """
    )
