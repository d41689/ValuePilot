"""Protect currentness slots and persist snapshot MVCC visibility.

Revision ID: 20260904220000
Revises: 20260904210000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904220000"
down_revision = "20260904210000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_metric_fact_currentness_authority()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'metric fact currentness authority is immutable';
        END $$;
        CREATE TRIGGER trg_metric_fact_currentness_authority_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON metric_fact_currentness_authority
        FOR EACH ROW EXECUTE FUNCTION guard_metric_fact_currentness_authority();

        CREATE FUNCTION guard_metric_fact_slot_identity()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF ROW(
               OLD.user_id,OLD.stock_id,OLD.metric_key,OLD.source_type,
               OLD.source_document_id,OLD.source_ref_id,OLD.period_type,
               OLD.period_end_date,OLD.as_of_date
             ) IS DISTINCT FROM ROW(
               NEW.user_id,NEW.stock_id,NEW.metric_key,NEW.source_type,
               NEW.source_document_id,NEW.source_ref_id,NEW.period_type,
               NEW.period_end_date,NEW.as_of_date
             )
          THEN
            RAISE EXCEPTION 'metric fact canonical slot identity is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_metric_fact_slot_identity_immutable
        BEFORE UPDATE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION guard_metric_fact_slot_identity();
        """
    )
    # Cover nullable slot columns explicitly; PostgreSQL NULL-distinct unique
    # semantics are not sufficient for canonical currentness.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_metric_facts_current_canonical_slot
        ON metric_facts (
          coalesce(user_id,0),stock_id,metric_key,source_type,
          coalesce(source_document_id,0),coalesce(period_type,''),
          coalesce(period_end_date,DATE '0001-01-01'),
          coalesce(as_of_date,DATE '0001-01-01')
        ) WHERE is_current=true
        """
    )

    # Existing short-lived cursors cannot be assigned an earlier MVCC snapshot
    # after the fact. Invalidating them is conservative and bounded by their
    # existing 15-minute lifetime.
    op.execute("DELETE FROM document_list_snapshots")
    op.add_column(
        "document_list_snapshots",
        sa.Column("visibility_snapshot", sa.String(), nullable=True),
    )
    op.execute(
        "DROP TRIGGER trg_document_list_snapshots_immutable "
        "ON document_list_snapshots; "
        "DROP FUNCTION guard_document_list_snapshot_immutability()"
    )
    op.execute(
        """
        CREATE FUNCTION guard_document_list_snapshot_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          snapshot_clock timestamptz;
        BEGIN
          IF TG_OP='INSERT' THEN
            snapshot_clock := clock_timestamp();
            NEW.snapshot_cutoff := snapshot_clock;
            NEW.created_at := snapshot_clock;
            NEW.expires_at := snapshot_clock + interval '15 minutes';
            NEW.created_txid := txid_current();
            NEW.visibility_snapshot := txid_current_snapshot()::text;
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'document list snapshots are immutable';
        END $$;
        CREATE TRIGGER trg_document_list_snapshots_immutable
        BEFORE INSERT OR UPDATE ON document_list_snapshots
        FOR EACH ROW EXECUTE FUNCTION guard_document_list_snapshot_immutability();
        """
    )
    op.alter_column("document_list_snapshots", "visibility_snapshot", nullable=False)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT count(*) FROM document_list_snapshots")
    ).scalar_one():
        raise RuntimeError("downgrade refused: retained document snapshots exist")
    op.execute(
        "DROP TRIGGER trg_document_list_snapshots_immutable "
        "ON document_list_snapshots; "
        "DROP FUNCTION guard_document_list_snapshot_immutability()"
    )
    op.drop_column("document_list_snapshots", "visibility_snapshot")
    op.execute(
        """
        CREATE FUNCTION guard_document_list_snapshot_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE snapshot_clock timestamptz;
        BEGIN
          IF TG_OP='INSERT' THEN
            snapshot_clock:=clock_timestamp();
            NEW.snapshot_cutoff:=snapshot_clock;
            NEW.created_at:=snapshot_clock;
            NEW.expires_at:=snapshot_clock+interval '15 minutes';
            NEW.created_txid:=txid_current();
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'document list snapshots are immutable';
        END $$;
        CREATE TRIGGER trg_document_list_snapshots_immutable
        BEFORE INSERT OR UPDATE ON document_list_snapshots
        FOR EACH ROW EXECUTE FUNCTION guard_document_list_snapshot_immutability();
        """
    )
    op.drop_index("uq_metric_facts_current_canonical_slot", table_name="metric_facts")
    op.execute(
        "DROP TRIGGER trg_metric_fact_slot_identity_immutable ON metric_facts; "
        "DROP FUNCTION guard_metric_fact_slot_identity(); "
        "DROP TRIGGER trg_metric_fact_currentness_authority_immutable "
        "ON metric_fact_currentness_authority; "
        "DROP FUNCTION guard_metric_fact_currentness_authority()"
    )
