"""Make manual privacy tombstones strictly one-way.

Revision ID: 20260904270000
Revises: 20260904260000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904270000"
down_revision = "20260904260000"
branch_labels = None
depends_on = None


_ONE_WAY_FUNCTION = r"""
CREATE OR REPLACE FUNCTION guard_governed_metric_fact_immutability()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  governed boolean;
  redacted_json jsonb;
BEGIN
  governed := OLD.source_type IN ('manual','calculated','derived');

  IF TG_OP='DELETE' THEN
    IF NOT governed THEN
      RETURN OLD;
    END IF;
    IF OLD.source_document_id IS NOT NULL
       AND pg_trigger_depth()>1
       AND NOT EXISTS (
         SELECT 1 FROM pdf_documents d WHERE d.id=OLD.source_document_id
       )
    THEN
      RETURN OLD;
    END IF;
    IF OLD.value_line_report_identity_revision_id IS NOT NULL
       AND pg_trigger_depth()>1
       AND NOT EXISTS (
         SELECT 1 FROM value_line_document_report_identity_revisions r
         WHERE r.id=OLD.value_line_report_identity_revision_id
       )
    THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'metric facts cannot be deleted directly';
  END IF;

  IF NOT governed THEN
    RETURN NEW;
  END IF;

  IF OLD.is_current=false AND NEW.is_current=true THEN
    RAISE EXCEPTION 'governed metric facts cannot be reactivated';
  END IF;

  -- User-authored ``reason`` is the only metric-fact text erased by the
  -- account-erasure path.  The economic value and every other provenance
  -- field remain immutable.  An existing tombstone is byte-for-byte frozen:
  -- its integrity hash cannot be replaced in a later UPDATE.
  redacted_json := jsonb_set(
    COALESCE(OLD.value_json,'{}'::jsonb),
    '{reason}',
    '"[redacted]"'::jsonb,
    true
  ) || jsonb_build_object(
    'redaction_content_hash', NEW.value_json->'redaction_content_hash'
  );

  IF ROW(
       OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,OLD.period,
       OLD.created_at,OLD.value_line_parse_run_id,
       OLD.value_line_legacy_revision,
       OLD.value_line_report_identity_revision_id,
       OLD.value_line_fact_known_at,OLD.value_line_created_txid
     ) IS DISTINCT FROM ROW(
       NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,NEW.period,
       NEW.created_at,NEW.value_line_parse_run_id,
       NEW.value_line_legacy_revision,
       NEW.value_line_report_identity_revision_id,
       NEW.value_line_fact_known_at,NEW.value_line_created_txid
     ) OR (
       OLD.value_json IS DISTINCT FROM NEW.value_json
       AND NOT (
         OLD.source_type='manual'
         AND COALESCE(OLD.value_json,'{}'::jsonb) ? 'reason'
         AND OLD.value_json->>'reason' <> '[redacted]'
         AND NEW.value_json = redacted_json
         AND NEW.value_json->>'redaction_content_hash' ~ '^[0-9a-f]{64}$'
       )
     ) OR (
       OLD.source_type<>'manual'
       AND OLD.source_document_id IS DISTINCT FROM NEW.source_document_id
     )
  THEN
    RAISE EXCEPTION 'governed metric fact content and provenance are immutable';
  END IF;
  RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute(_ONE_WAY_FUNCTION)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT count(*) FROM metric_facts "
            "WHERE source_type='manual' "
            "AND COALESCE(value_json->>'reason','')='[redacted]' "
            "AND value_json ? 'redaction_content_hash'"
        )
    ).scalar_one():
        raise RuntimeError(
            "downgrade refused: cannot weaken retained one-way privacy tombstones"
        )
    # Reinstall the 260 implementation only when no one-way tombstone would
    # lose its invariant.  The full definition is restored by downgrade 260
    # when the chain is subsequently moved farther back.
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION guard_governed_metric_fact_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          governed boolean;
          redacted_json jsonb;
          redacted_json_with_hash jsonb;
        BEGIN
          governed := OLD.source_type IN ('manual','calculated','derived');
          IF TG_OP='DELETE' THEN
            IF NOT governed THEN RETURN OLD; END IF;
            IF OLD.source_document_id IS NOT NULL AND pg_trigger_depth()>1
               AND NOT EXISTS (SELECT 1 FROM pdf_documents d WHERE d.id=OLD.source_document_id)
            THEN RETURN OLD; END IF;
            IF OLD.value_line_report_identity_revision_id IS NOT NULL
               AND pg_trigger_depth()>1 AND NOT EXISTS (
                 SELECT 1 FROM value_line_document_report_identity_revisions r
                 WHERE r.id=OLD.value_line_report_identity_revision_id
               )
            THEN RETURN OLD; END IF;
            RAISE EXCEPTION 'metric facts cannot be deleted directly';
          END IF;
          IF NOT governed THEN RETURN NEW; END IF;
          IF OLD.is_current=false AND NEW.is_current=true THEN
            RAISE EXCEPTION 'governed metric facts cannot be reactivated';
          END IF;
          redacted_json := jsonb_set(COALESCE(OLD.value_json,'{}'::jsonb),
            '{reason}','"[redacted]"'::jsonb,true);
          redacted_json_with_hash := redacted_json || CASE
            WHEN NEW.value_json ? 'redaction_content_hash' THEN jsonb_build_object(
              'redaction_content_hash',NEW.value_json->'redaction_content_hash')
            ELSE '{}'::jsonb END;
          IF ROW(OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,OLD.period,
               OLD.created_at,OLD.value_line_parse_run_id,OLD.value_line_legacy_revision,
               OLD.value_line_report_identity_revision_id,OLD.value_line_fact_known_at,
               OLD.value_line_created_txid) IS DISTINCT FROM
             ROW(NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,NEW.period,
               NEW.created_at,NEW.value_line_parse_run_id,NEW.value_line_legacy_revision,
               NEW.value_line_report_identity_revision_id,NEW.value_line_fact_known_at,
               NEW.value_line_created_txid)
             OR (OLD.value_json IS DISTINCT FROM NEW.value_json AND NOT (
               OLD.source_type='manual' AND OLD.value_numeric IS NULL
               AND COALESCE(OLD.value_json,'{}'::jsonb) ? 'reason'
               AND NEW.value_json IN (redacted_json,redacted_json_with_hash)
               AND (NOT (NEW.value_json ? 'redaction_content_hash') OR
                 NEW.value_json->>'redaction_content_hash' ~ '^[0-9a-f]{64}$')))
             OR (OLD.source_type<>'manual' AND
                 OLD.source_document_id IS DISTINCT FROM NEW.source_document_id)
          THEN RAISE EXCEPTION 'governed metric fact content and provenance are immutable';
          END IF;
          RETURN NEW;
        END $$;
        """
    )
