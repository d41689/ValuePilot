"""Tombstone every manual-fact rationale field in one immutable transition.

Revision ID: 20260904290000
Revises: 20260904280000
"""

from alembic import op


revision = "20260904290000"
down_revision = "20260904280000"
branch_labels = None
depends_on = None


_MANUAL_TEXT_FUNCTION = r"""
CREATE OR REPLACE FUNCTION guard_governed_metric_fact_immutability()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  governed boolean;
  reason_changed boolean;
  note_changed boolean;
  existing_hash boolean;
  redacted_json jsonb;
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

  reason_changed := OLD.source_type='manual'
    AND jsonb_typeof(COALESCE(OLD.value_json,'{}'::jsonb)->'reason')='string'
    AND OLD.value_json->>'reason'<>'[redacted]';
  note_changed := OLD.source_type='manual'
    AND jsonb_typeof(COALESCE(OLD.value_json,'{}'::jsonb)->'note')='string'
    AND OLD.value_json->>'note'<>'[redacted]';
  existing_hash := COALESCE(OLD.value_json,'{}'::jsonb)
    ?| ARRAY['redaction_content_hash','redaction_note_content_hash'];
  redacted_json := COALESCE(OLD.value_json,'{}'::jsonb);
  IF reason_changed THEN
    redacted_json := jsonb_set(redacted_json,'{reason}','"[redacted]"'::jsonb,true)
      || jsonb_build_object(
        'redaction_content_hash',NEW.value_json->'redaction_content_hash'
      );
  END IF;
  IF note_changed THEN
    redacted_json := jsonb_set(redacted_json,'{note}','"[redacted]"'::jsonb,true)
      || jsonb_build_object(
        'redaction_note_content_hash',NEW.value_json->'redaction_note_content_hash'
      );
  END IF;

  IF ROW(
       OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,OLD.period,
       OLD.created_at,OLD.value_line_parse_run_id,OLD.value_line_legacy_revision,
       OLD.value_line_report_identity_revision_id,OLD.value_line_fact_known_at,
       OLD.value_line_created_txid
     ) IS DISTINCT FROM ROW(
       NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,NEW.period,
       NEW.created_at,NEW.value_line_parse_run_id,NEW.value_line_legacy_revision,
       NEW.value_line_report_identity_revision_id,NEW.value_line_fact_known_at,
       NEW.value_line_created_txid
     ) OR (
       OLD.value_json IS DISTINCT FROM NEW.value_json
       AND NOT (
         OLD.source_type='manual' AND NOT existing_hash
         AND (reason_changed OR note_changed)
         AND NEW.value_json=redacted_json
         AND (
           NOT reason_changed OR
           NEW.value_json->>'redaction_content_hash' ~ '^[0-9a-f]{64}$'
         )
         AND (
           NOT note_changed OR
           NEW.value_json->>'redaction_note_content_hash' ~ '^[0-9a-f]{64}$'
         )
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


_REASON_ONLY_FUNCTION = r"""
CREATE OR REPLACE FUNCTION guard_governed_metric_fact_immutability()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  governed boolean;
  redacted_json jsonb;
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
    '{reason}','"[redacted]"'::jsonb,true) || jsonb_build_object(
      'redaction_content_hash',NEW.value_json->'redaction_content_hash');
  IF ROW(OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,OLD.period,
       OLD.created_at,OLD.value_line_parse_run_id,OLD.value_line_legacy_revision,
       OLD.value_line_report_identity_revision_id,OLD.value_line_fact_known_at,
       OLD.value_line_created_txid) IS DISTINCT FROM
     ROW(NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,NEW.period,
       NEW.created_at,NEW.value_line_parse_run_id,NEW.value_line_legacy_revision,
       NEW.value_line_report_identity_revision_id,NEW.value_line_fact_known_at,
       NEW.value_line_created_txid)
     OR (OLD.value_json IS DISTINCT FROM NEW.value_json AND NOT (
       OLD.source_type='manual' AND COALESCE(OLD.value_json,'{}'::jsonb) ? 'reason'
       AND OLD.value_json->>'reason'<>'[redacted]' AND NEW.value_json=redacted_json
       AND NEW.value_json->>'redaction_content_hash' ~ '^[0-9a-f]{64}$'))
     OR (OLD.source_type<>'manual' AND
       OLD.source_document_id IS DISTINCT FROM NEW.source_document_id)
  THEN RAISE EXCEPTION 'governed metric fact content and provenance are immutable';
  END IF;
  RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute(_MANUAL_TEXT_FUNCTION)


def downgrade() -> None:
    op.execute(_REASON_ONLY_FUNCTION)
