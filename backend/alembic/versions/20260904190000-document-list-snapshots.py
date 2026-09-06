"""Persist bounded document-list snapshot membership.

Revision ID: 20260904190000
Revises: 20260904180000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904190000"
down_revision = "20260904180000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_list_snapshots",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("page_limit", sa.Integer(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("max_document_id", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "page_limit BETWEEN 1 AND 500",
            name="ck_document_list_snapshots_limit",
        ),
        sa.CheckConstraint(
            "total_count BETWEEN 0 AND 5000",
            name="ck_document_list_snapshots_total",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_list_snapshots_user_id",
        "document_list_snapshots",
        ["user_id"],
    )
    op.create_index(
        "ix_document_list_snapshots_expires_at",
        "document_list_snapshots",
        ["expires_at"],
    )
    op.create_table(
        "document_list_snapshot_members",
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("upload_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "ordinal > 0", name="ck_document_list_snapshot_members_ordinal"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["document_list_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("snapshot_id", "ordinal"),
        sa.UniqueConstraint(
            "snapshot_id",
            "document_id",
            name="uq_document_list_snapshot_member_document",
        ),
    )
    op.create_index(
        "ix_document_list_snapshot_members_document_id",
        "document_list_snapshot_members",
        ["document_id"],
    )
    op.execute(
        """
        CREATE FUNCTION guard_document_list_snapshot_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='INSERT' THEN
            NEW.created_at := clock_timestamp();
            NEW.created_txid := txid_current();
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'document list snapshots are immutable';
        END $$;

        CREATE TRIGGER trg_document_list_snapshots_immutable
        BEFORE INSERT OR UPDATE ON document_list_snapshots
        FOR EACH ROW EXECUTE FUNCTION guard_document_list_snapshot_immutability();

        CREATE FUNCTION guard_document_list_snapshot_member_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          snapshot_txid bigint;
        BEGIN
          IF TG_OP='INSERT' THEN
            SELECT created_txid INTO snapshot_txid
              FROM document_list_snapshots
              WHERE id=NEW.snapshot_id
              FOR SHARE;
            IF NOT FOUND OR snapshot_txid IS DISTINCT FROM txid_current() THEN
              RAISE EXCEPTION 'snapshot membership must be captured atomically';
            END IF;
            NEW.created_txid := txid_current();
            RETURN NEW;
          END IF;
          IF TG_OP='UPDATE' OR EXISTS (
            SELECT 1 FROM document_list_snapshots WHERE id=OLD.snapshot_id
          ) THEN
            RAISE EXCEPTION 'document list snapshot members are immutable';
          END IF;
          RETURN OLD;
        END $$;

        CREATE TRIGGER trg_document_list_snapshot_members_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON document_list_snapshot_members
        FOR EACH ROW EXECUTE FUNCTION guard_document_list_snapshot_member_immutability();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_document_list_snapshot_members_immutable "
        "ON document_list_snapshot_members; "
        "DROP TRIGGER trg_document_list_snapshots_immutable "
        "ON document_list_snapshots; "
        "DROP FUNCTION IF EXISTS guard_document_list_snapshot_member_immutability(); "
        "DROP FUNCTION guard_document_list_snapshot_immutability()"
    )
    op.drop_index(
        "ix_document_list_snapshot_members_document_id",
        table_name="document_list_snapshot_members",
    )
    op.drop_table("document_list_snapshot_members")
    op.drop_index(
        "ix_document_list_snapshots_expires_at",
        table_name="document_list_snapshots",
    )
    op.drop_index(
        "ix_document_list_snapshots_user_id",
        table_name="document_list_snapshots",
    )
    op.drop_table("document_list_snapshots")
