"""Freeze each manual rationale field as soon as its privacy hash exists.

Revision ID: 20260904310000
Revises: 20260904300000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904310000"
down_revision = "20260904300000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION guard_prehashed_manual_rationale_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.source_type <> 'manual' THEN
            RETURN NEW;
          END IF;

          -- A field hash is itself the one-way boundary.  This also protects
          -- legacy/imported rows whose text was not tombstoned atomically:
          -- callers cannot convert hash A to hash B under cover of the first
          -- text-to-redacted transition.
          IF COALESCE(OLD.value_json, '{}'::jsonb)
               ? 'redaction_content_hash'
             AND ROW(
               OLD.value_json->'reason',
               OLD.value_json->'redaction_content_hash'
             ) IS DISTINCT FROM ROW(
               NEW.value_json->'reason',
               NEW.value_json->'redaction_content_hash'
             )
          THEN
            RAISE EXCEPTION 'manual reason privacy hash is immutable';
          END IF;

          IF COALESCE(OLD.value_json, '{}'::jsonb)
               ? 'redaction_note_content_hash'
             AND ROW(
               OLD.value_json->'note',
               OLD.value_json->'redaction_note_content_hash'
             ) IS DISTINCT FROM ROW(
               NEW.value_json->'note',
               NEW.value_json->'redaction_note_content_hash'
             )
          THEN
            RAISE EXCEPTION 'manual note privacy hash is immutable';
          END IF;

          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_zzzz_prehashed_manual_rationale_immutable
        BEFORE UPDATE ON metric_facts
        FOR EACH ROW
        EXECUTE FUNCTION guard_prehashed_manual_rationale_immutability();
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    protected_rows = connection.execute(
        sa.text(
            "SELECT count(*) FROM metric_facts "
            "WHERE source_type='manual' AND ("
            "(value_json ? 'redaction_content_hash' "
            " AND COALESCE(value_json->>'reason','') <> '[redacted]') OR "
            "(value_json ? 'redaction_note_content_hash' "
            " AND COALESCE(value_json->>'note','') <> '[redacted]'))"
        )
    ).scalar_one()
    if protected_rows:
        raise RuntimeError(
            "downgrade refused: cannot weaken pre-hashed manual rationale"
        )
    op.execute(
        "DROP TRIGGER trg_zzzz_prehashed_manual_rationale_immutable "
        "ON metric_facts"
    )
    op.execute("DROP FUNCTION guard_prehashed_manual_rationale_immutability()")
