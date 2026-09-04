"""Approve exact Value Line fact-to-extraction lineage.

Revision ID: 20260904140000
Revises: 20260904130000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904140000"
down_revision = "20260904130000"
branch_labels = None
depends_on = None


PREVIOUS_POLICY_ID = (
    "value-line-resolved-v2:"
    "961bb30d1378694f1d79bd7f3dfe1693f3a50270d95664daddad16f1796f9d67"
)
CURRENT_POLICY_ID = (
    "value-line-resolved-v2:"
    "ad39a21849da51983b15588182cc8a66fa36999429d65fbc3a45323719452a4b"
)
CURRENT_POLICY_SHA256 = (
    "ad39a21849da51983b15588182cc8a66fa36999429d65fbc3a45323719452a4b"
)
POLICY_CUTOVER = "2026-09-04 00:00:00+00"


def _create_registry_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_value_line_mapping_policy_registry() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'Value Line mapping policy registry is immutable';
        END $$;

        CREATE TRIGGER trg_value_line_mapping_policy_registry
        BEFORE INSERT OR UPDATE OR DELETE ON value_line_mapping_policies
        FOR EACH ROW EXECUTE FUNCTION guard_value_line_mapping_policy_registry();
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    approved_policy = bind.execute(
        sa.text(
            "SELECT id FROM value_line_mapping_policies WHERE status='approved'"
        )
    ).scalars().all()
    if len(approved_policy) != 1 or approved_policy[0] != PREVIOUS_POLICY_ID:
        raise RuntimeError(
            "Value Line lineage upgrade refused: the deployed approved mapping "
            "policy is not the expected predecessor"
        )

    op.execute(
        """
        DROP TRIGGER trg_value_line_mapping_policy_registry
          ON value_line_mapping_policies;
        DROP FUNCTION guard_value_line_mapping_policy_registry();
        """
    )
    op.execute(
        sa.text(
            """
            UPDATE value_line_mapping_policies
            SET status='superseded', retired_at=CAST(:cutover AS TIMESTAMPTZ)
            WHERE id=:previous_id;

            INSERT INTO value_line_mapping_policies
              (id,policy_sha256,spec_version,parser_version,status,known_at,
               effective_from,retired_at)
            VALUES
              (:current_id,:current_sha,2,'value-line-v1','approved',
               CAST(:cutover AS TIMESTAMPTZ),CAST(:cutover AS TIMESTAMPTZ),NULL);
            """
        ).bindparams(
            cutover=POLICY_CUTOVER,
            previous_id=PREVIOUS_POLICY_ID,
            current_id=CURRENT_POLICY_ID,
            current_sha=CURRENT_POLICY_SHA256,
        )
    )
    _create_registry_guard()

    op.create_table(
        "value_line_fact_extraction_inputs",
        sa.Column("fact_id", sa.Integer(), nullable=False),
        sa.Column("extraction_id", sa.Integer(), nullable=False),
        sa.Column("value_line_parse_run_id", sa.BigInteger(), nullable=False),
        sa.Column("input_role", sa.String(), nullable=False),
        sa.Column("input_ordinal", sa.Integer(), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_role IN ('primary','supporting')",
            name="ck_value_line_fact_extraction_inputs_role",
        ),
        sa.CheckConstraint(
            "input_ordinal > 0",
            name="ck_value_line_fact_extraction_inputs_ordinal",
        ),
        sa.ForeignKeyConstraint(
            ["fact_id"], ["metric_facts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"], ["metric_extractions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["value_line_parse_run_id"],
            ["value_line_parse_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("fact_id", "extraction_id"),
        sa.UniqueConstraint(
            "fact_id",
            "input_ordinal",
            name="uq_value_line_fact_extraction_input_ordinal",
        ),
    )
    op.create_index(
        "ix_value_line_fact_extraction_inputs_extraction",
        "value_line_fact_extraction_inputs",
        ["extraction_id", "value_line_parse_run_id"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_value_line_fact_primary_extraction "
        "ON value_line_fact_extraction_inputs (fact_id) "
        "WHERE input_role='primary'"
    )
    op.execute(
        """
        CREATE FUNCTION guard_value_line_fact_extraction_input()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          run_row value_line_parse_runs%ROWTYPE;
          fact_row metric_facts%ROWTYPE;
          extraction_row metric_extractions%ROWTYPE;
        BEGIN
          IF TG_OP='UPDATE' THEN
            RAISE EXCEPTION 'Value Line fact extraction inputs are append-only';
          END IF;
          IF TG_OP='DELETE' THEN
            IF pg_trigger_depth() <= 1 OR EXISTS (
              SELECT 1 FROM pdf_documents d
              WHERE d.id=(SELECT r.document_id FROM value_line_parse_runs r
                          WHERE r.id=OLD.value_line_parse_run_id)
            ) THEN
              RAISE EXCEPTION 'Value Line fact extraction inputs are append-only';
            END IF;
            RETURN OLD;
          END IF;

          SELECT * INTO run_row FROM value_line_parse_runs
            WHERE id=NEW.value_line_parse_run_id;
          IF NOT FOUND OR run_row.status<>'running'
             OR run_row.created_txid<>txid_current()
          THEN
            RAISE EXCEPTION 'Value Line fact extraction input requires its creating run';
          END IF;
          SELECT * INTO fact_row FROM metric_facts WHERE id=NEW.fact_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'Value Line fact extraction input requires its fact';
          END IF;
          SELECT * INTO extraction_row FROM metric_extractions
            WHERE id=NEW.extraction_id;
          IF NOT FOUND
             OR fact_row.source_type<>'parsed'
             OR fact_row.value_line_parse_run_id<>run_row.id
             OR extraction_row.value_line_parse_run_id<>run_row.id
             OR fact_row.user_id<>run_row.user_id
             OR extraction_row.user_id<>run_row.user_id
             OR fact_row.source_document_id<>run_row.document_id
             OR extraction_row.document_id<>run_row.document_id
          THEN
            RAISE EXCEPTION 'Value Line fact extraction input must bind its creating run';
          END IF;
          NEW.created_txid := txid_current();
          NEW.created_at := clock_timestamp();
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_value_line_fact_extraction_input
        BEFORE INSERT OR UPDATE OR DELETE ON value_line_fact_extraction_inputs
        FOR EACH ROW EXECUTE FUNCTION guard_value_line_fact_extraction_input();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    manifest_count = bind.execute(
        sa.text("SELECT count(*) FROM value_line_fact_extraction_inputs")
    ).scalar_one()
    current_policy_run_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM value_line_parse_runs "
            "WHERE source_mapping_version=:policy_id"
        ),
        {"policy_id": CURRENT_POLICY_ID},
    ).scalar_one()
    if manifest_count or current_policy_run_count:
        raise RuntimeError(
            "downgrade refused: exact fact-extraction lineage or approved-policy "
            "parse history cannot be represented by revision 20260904130000"
        )

    op.execute(
        "DROP TRIGGER trg_value_line_fact_extraction_input "
        "ON value_line_fact_extraction_inputs"
    )
    op.execute("DROP FUNCTION guard_value_line_fact_extraction_input()")
    op.drop_index(
        "uq_value_line_fact_primary_extraction",
        table_name="value_line_fact_extraction_inputs",
    )
    op.drop_index(
        "ix_value_line_fact_extraction_inputs_extraction",
        table_name="value_line_fact_extraction_inputs",
    )
    op.drop_table("value_line_fact_extraction_inputs")

    op.execute(
        """
        DROP TRIGGER trg_value_line_mapping_policy_registry
          ON value_line_mapping_policies;
        DROP FUNCTION guard_value_line_mapping_policy_registry();
        """
    )
    op.execute(
        sa.text(
            """
            DELETE FROM value_line_mapping_policies WHERE id=:current_id;
            UPDATE value_line_mapping_policies
            SET status='approved', retired_at=NULL
            WHERE id=:previous_id;
            """
        ).bindparams(
            current_id=CURRENT_POLICY_ID,
            previous_id=PREVIOUS_POLICY_ID,
        )
    )
    _create_registry_guard()
