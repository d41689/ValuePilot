"""Make Value Line parsed-fact knowledge time database-owned.

Revision ID: 20260904180000
Revises: 20260904170000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904180000"
down_revision = "20260904170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "metric_facts",
        sa.Column(
            "value_line_fact_known_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "metric_facts",
        sa.Column("value_line_created_txid", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_metric_facts_value_line_fact_known_at",
        "metric_facts",
        ["value_line_fact_known_at"],
    )

    # A retained parsed fact's caller-controlled created_at cannot prove when it
    # first existed. Record only the conservative migration observation time;
    # historical readers before this stamp must report typed unverifiability.
    # The NULL transaction identity deliberately distinguishes retained rows
    # from facts whose creating transaction was observed by the final trigger.
    op.execute(
        "UPDATE metric_facts SET value_line_fact_known_at=clock_timestamp(), "
        "value_line_created_txid=NULL WHERE source_type='parsed'"
    )
    op.execute(
        """
        CREATE FUNCTION guard_value_line_fact_time_authority()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='INSERT' THEN
            IF NEW.source_type='parsed' THEN
              NEW.created_at := clock_timestamp();
              NEW.updated_at := NEW.created_at;
              NEW.value_line_fact_known_at := NEW.created_at;
              NEW.value_line_created_txid := txid_current();
            ELSE
              NEW.value_line_fact_known_at := NULL;
              NEW.value_line_created_txid := NULL;
            END IF;
            RETURN NEW;
          END IF;

          IF OLD.source_type='parsed' OR NEW.source_type='parsed' THEN
            IF OLD.source_type<>'parsed'
               OR NEW.source_type<>'parsed'
               OR OLD.is_current IS NOT TRUE
               OR NEW.is_current IS NOT FALSE
               OR (to_jsonb(OLD) - 'is_current' - 'updated_at')
                  IS DISTINCT FROM
                  (to_jsonb(NEW) - 'is_current' - 'updated_at')
            THEN
              RAISE EXCEPTION 'Value Line parsed fact authority is immutable';
            END IF;
            -- Demotion is the one permitted projection mutation. Its audit
            -- time is still database-owned; a caller cannot backdate it.
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
          END IF;

          IF NEW.value_line_fact_known_at IS NOT NULL
             OR NEW.value_line_created_txid IS NOT NULL
          THEN
            RAISE EXCEPTION 'Value Line fact time authority is parsed-only';
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_value_line_fact_time_authority
        BEFORE INSERT OR UPDATE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION guard_value_line_fact_time_authority();
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    op.execute("LOCK TABLE metric_facts IN SHARE MODE")
    retained = connection.execute(
        sa.text("SELECT count(*) FROM metric_facts WHERE source_type='parsed'")
    ).scalar_one()
    if retained:
        raise RuntimeError(
            "downgrade refused: cannot discard retained Value Line fact time authority"
        )

    op.execute(
        "DROP TRIGGER trg_value_line_fact_time_authority ON metric_facts; "
        "DROP FUNCTION guard_value_line_fact_time_authority()"
    )
    op.drop_index(
        "ix_metric_facts_value_line_fact_known_at",
        table_name="metric_facts",
    )
    op.drop_column("metric_facts", "value_line_created_txid")
    op.drop_column("metric_facts", "value_line_fact_known_at")
