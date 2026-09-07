"""Preserve report ambiguity and authorize verified rationale erasure.

Revision ID: 20260904320000
Revises: 20260904310000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904320000"
down_revision = "20260904310000"
branch_labels = None
depends_on = None


_GOVERNED_FUNCTION = r"""
CREATE OR REPLACE FUNCTION guard_governed_metric_fact_immutability()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  governed boolean;
  reason_changed boolean;
  note_changed boolean;
  reason_prehashed boolean;
  note_prehashed boolean;
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
    AND OLD.value_json->>'reason'<>'[redacted]'
    AND NEW.value_json->>'reason'='[redacted]';
  note_changed := OLD.source_type='manual'
    AND jsonb_typeof(COALESCE(OLD.value_json,'{}'::jsonb)->'note')='string'
    AND OLD.value_json->>'note'<>'[redacted]'
    AND NEW.value_json->>'note'='[redacted]';
  reason_prehashed := COALESCE(OLD.value_json,'{}'::jsonb)
    ? 'redaction_content_hash';
  note_prehashed := COALESCE(OLD.value_json,'{}'::jsonb)
    ? 'redaction_note_content_hash';
  redacted_json := COALESCE(OLD.value_json,'{}'::jsonb);
  IF reason_changed THEN
    redacted_json := jsonb_set(redacted_json,'{reason}','"[redacted]"'::jsonb,true)
      || jsonb_build_object('redaction_content_hash',
           CASE WHEN reason_prehashed
             THEN OLD.value_json->'redaction_content_hash'
             ELSE NEW.value_json->'redaction_content_hash' END);
  END IF;
  IF note_changed THEN
    redacted_json := jsonb_set(redacted_json,'{note}','"[redacted]"'::jsonb,true)
      || jsonb_build_object('redaction_note_content_hash',
           CASE WHEN note_prehashed
             THEN OLD.value_json->'redaction_note_content_hash'
             ELSE NEW.value_json->'redaction_note_content_hash' END);
  END IF;

  IF ROW(OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,OLD.period,
       OLD.created_at,OLD.value_line_parse_run_id,OLD.value_line_legacy_revision,
       OLD.value_line_report_identity_revision_id,OLD.value_line_fact_known_at,
       OLD.value_line_created_txid) IS DISTINCT FROM
     ROW(NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,NEW.period,
       NEW.created_at,NEW.value_line_parse_run_id,NEW.value_line_legacy_revision,
       NEW.value_line_report_identity_revision_id,NEW.value_line_fact_known_at,
       NEW.value_line_created_txid)
     OR (OLD.value_json IS DISTINCT FROM NEW.value_json AND NOT (
       OLD.source_type='manual' AND (reason_changed OR note_changed)
       AND NEW.value_json=redacted_json
       AND (NOT reason_changed OR
         (reason_prehashed AND
          current_setting('valuepilot.account_erasure',true)='on') OR
         (NOT reason_prehashed AND
          NEW.value_json->>'redaction_content_hash' ~ '^[0-9a-f]{64}$'))
       AND (NOT note_changed OR
         (note_prehashed AND
          current_setting('valuepilot.account_erasure',true)='on') OR
         (NOT note_prehashed AND
          NEW.value_json->>'redaction_note_content_hash' ~ '^[0-9a-f]{64}$'))
     )) OR (OLD.source_type<>'manual' AND
       OLD.source_document_id IS DISTINCT FROM NEW.source_document_id)
  THEN
    RAISE EXCEPTION 'governed metric fact content and provenance are immutable';
  END IF;
  RETURN NEW;
END $$;
"""


_PREHASH_FUNCTION = r"""
CREATE OR REPLACE FUNCTION guard_prehashed_manual_rationale_immutability()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  expected_hash text;
BEGIN
  IF OLD.source_type <> 'manual' THEN RETURN NEW; END IF;

  IF COALESCE(OLD.value_json,'{}'::jsonb) ? 'redaction_content_hash'
     AND ROW(OLD.value_json->'reason',OLD.value_json->'redaction_content_hash')
       IS DISTINCT FROM
       ROW(NEW.value_json->'reason',NEW.value_json->'redaction_content_hash')
  THEN
    IF current_setting('valuepilot.account_erasure',true)='on'
       AND jsonb_typeof(OLD.value_json->'reason')='string'
       AND OLD.value_json->>'reason'<>'[redacted]'
       AND NEW.value_json->>'reason'='[redacted]'
       AND NEW.value_json->'redaction_content_hash'
           = OLD.value_json->'redaction_content_hash'
    THEN
      expected_hash := encode(digest(OLD.value_json->>'reason','sha256'),'hex');
      IF OLD.value_json->>'redaction_content_hash' IS DISTINCT FROM expected_hash THEN
        INSERT INTO manual_rationale_erasure_anomalies
          (fact_id,user_id,field_name,reason_code,observed_hash,created_at,created_txid)
        VALUES
          (OLD.id,OLD.user_id,'reason','retained_hash_mismatch',
           OLD.value_json->>'redaction_content_hash',clock_timestamp(),txid_current())
        ON CONFLICT (fact_id,field_name) DO NOTHING;
      END IF;
    ELSE
      RAISE EXCEPTION 'manual reason privacy hash is immutable';
    END IF;
  END IF;

  IF COALESCE(OLD.value_json,'{}'::jsonb) ? 'redaction_note_content_hash'
     AND ROW(OLD.value_json->'note',OLD.value_json->'redaction_note_content_hash')
       IS DISTINCT FROM
       ROW(NEW.value_json->'note',NEW.value_json->'redaction_note_content_hash')
  THEN
    IF current_setting('valuepilot.account_erasure',true)='on'
       AND jsonb_typeof(OLD.value_json->'note')='string'
       AND OLD.value_json->>'note'<>'[redacted]'
       AND NEW.value_json->>'note'='[redacted]'
       AND NEW.value_json->'redaction_note_content_hash'
           = OLD.value_json->'redaction_note_content_hash'
    THEN
      expected_hash := encode(digest(OLD.value_json->>'note','sha256'),'hex');
      IF OLD.value_json->>'redaction_note_content_hash' IS DISTINCT FROM expected_hash THEN
        INSERT INTO manual_rationale_erasure_anomalies
          (fact_id,user_id,field_name,reason_code,observed_hash,created_at,created_txid)
        VALUES
          (OLD.id,OLD.user_id,'note','retained_hash_mismatch',
           OLD.value_json->>'redaction_note_content_hash',clock_timestamp(),txid_current())
        ON CONFLICT (fact_id,field_name) DO NOTHING;
      END IF;
    ELSE
      RAISE EXCEPTION 'manual note privacy hash is immutable';
    END IF;
  END IF;
  RETURN NEW;
END $$;
"""


_OLD_PREHASH_FUNCTION = r"""
CREATE OR REPLACE FUNCTION guard_prehashed_manual_rationale_immutability()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.source_type <> 'manual' THEN RETURN NEW; END IF;
  IF COALESCE(OLD.value_json,'{}'::jsonb) ? 'redaction_content_hash'
     AND ROW(OLD.value_json->'reason',OLD.value_json->'redaction_content_hash')
       IS DISTINCT FROM ROW(NEW.value_json->'reason',NEW.value_json->'redaction_content_hash')
  THEN RAISE EXCEPTION 'manual reason privacy hash is immutable'; END IF;
  IF COALESCE(OLD.value_json,'{}'::jsonb) ? 'redaction_note_content_hash'
     AND ROW(OLD.value_json->'note',OLD.value_json->'redaction_note_content_hash')
       IS DISTINCT FROM ROW(NEW.value_json->'note',NEW.value_json->'redaction_note_content_hash')
  THEN RAISE EXCEPTION 'manual note privacy hash is immutable'; END IF;
  RETURN NEW;
END $$;
"""


_OLD_GOVERNED_FUNCTION = r"""
CREATE OR REPLACE FUNCTION guard_governed_metric_fact_immutability()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  governed boolean;
  reason_changed boolean;
  note_changed boolean;
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
    AND OLD.value_json->>'reason'<>'[redacted]'
    AND NEW.value_json->>'reason'='[redacted]';
  note_changed := OLD.source_type='manual'
    AND jsonb_typeof(COALESCE(OLD.value_json,'{}'::jsonb)->'note')='string'
    AND OLD.value_json->>'note'<>'[redacted]'
    AND NEW.value_json->>'note'='[redacted]';
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
  IF ROW(OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,OLD.period,
       OLD.created_at,OLD.value_line_parse_run_id,OLD.value_line_legacy_revision,
       OLD.value_line_report_identity_revision_id,OLD.value_line_fact_known_at,
       OLD.value_line_created_txid) IS DISTINCT FROM
     ROW(NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,NEW.period,
       NEW.created_at,NEW.value_line_parse_run_id,NEW.value_line_legacy_revision,
       NEW.value_line_report_identity_revision_id,NEW.value_line_fact_known_at,
       NEW.value_line_created_txid) OR (
       OLD.value_json IS DISTINCT FROM NEW.value_json
       AND NOT (
         OLD.source_type='manual'
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
     ) OR (OLD.source_type<>'manual' AND
       OLD.source_document_id IS DISTINCT FROM NEW.source_document_id)
  THEN
    RAISE EXCEPTION 'governed metric fact content and provenance are immutable';
  END IF;
  RETURN NEW;
END $$;
"""


def upgrade() -> None:
    # The old document-level uniqueness forced reparses with a distinct exact
    # identity to erase one another.  The immutable identity revision is the
    # correct uniqueness boundary; cross-identity disagreement stays visible.
    op.drop_index(
        "uq_metric_facts_current_parsed_document_period",
        table_name="metric_facts",
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_metric_facts_current_parsed_identity_period
        ON metric_facts (
          stock_id,metric_key,coalesce(period_type,''),
          coalesce(period_end_date,DATE '0001-01-01'),
          coalesce(value_line_report_identity_revision_id,
                   -source_document_id::bigint,0)
        ) WHERE source_type='parsed' AND is_current=true
        """
    )
    # Earlier ingestion elected one ID across distinct same-date report
    # identities.  The facts were retained, so establish the newly conservative
    # projection at this migration's knowledge time: one representative for
    # each distinct canonical observation in an actually divergent latest
    # slot.  The normal parsed-fact guard forbids application reactivation;
    # disabling it only for this controlled backfill still lets the database
    # currentness-capture trigger append the exact new state and timestamp.
    op.execute(
        r"""
        ALTER TABLE metric_facts DISABLE TRIGGER trg_value_line_fact_run_binding;
        ALTER TABLE metric_facts DISABLE TRIGGER trg_value_line_fact_time_authority;
        WITH identity_ranked AS (
          SELECT
            f.id,f.user_id,f.stock_id,f.metric_key,f.period_type,
            f.period_end_date,f.is_current,f.value_numeric,f.value_text,
            f.unit,f.currency,
            f.value_json->>'mapping_id' AS mapping_id,
            f.value_json->>'source_mapping_version' AS source_mapping_version,
            f.value_json->>'definition_basis' AS definition_basis,
            f.value_json->>'dimensions_identity' AS dimensions_identity,
            f.value_json->>'fact_nature' AS fact_nature,
            f.value_json->>'status' AS observation_status,
            r.id AS identity_revision_id,
            COALESCE(r.report_date,DATE '0001-01-01') AS report_date,
            max(COALESCE(r.report_date,DATE '0001-01-01')) OVER (
              PARTITION BY f.user_id,f.stock_id,f.metric_key,f.period_type,
                f.period_end_date
            ) AS latest_report_date,
            row_number() OVER (
              PARTITION BY f.user_id,f.stock_id,f.metric_key,f.period_type,
                f.period_end_date,r.id
              ORDER BY f.is_current DESC,f.id DESC
            ) AS identity_rank
          FROM metric_facts f
          JOIN value_line_document_report_identity_revisions r
            ON r.id=f.value_line_report_identity_revision_id
          WHERE f.source_type='parsed'
        ),
        at_latest_date AS (
          SELECT i.*
          FROM identity_ranked i
          WHERE i.identity_rank=1
            AND i.report_date=i.latest_report_date
        ),
        distinct_observations AS (
          SELECT DISTINCT
            user_id,stock_id,metric_key,period_type,period_end_date,
            value_numeric,value_text,unit,currency,mapping_id,
            source_mapping_version,definition_basis,
            dimensions_identity,fact_nature,observation_status
          FROM at_latest_date
        ),
        divergent_slots AS (
          SELECT user_id,stock_id,metric_key,period_type,period_end_date
          FROM distinct_observations
          GROUP BY user_id,stock_id,metric_key,period_type,period_end_date
          HAVING count(*)>1
        ),
        representatives AS (
          SELECT a.id,
            row_number() OVER (
              PARTITION BY a.user_id,a.stock_id,a.metric_key,a.period_type,
                a.period_end_date,a.value_numeric,a.value_text,a.unit,a.currency,
                a.mapping_id,a.source_mapping_version,a.definition_basis,
                a.dimensions_identity,a.fact_nature,
                a.observation_status
              ORDER BY a.is_current DESC,a.id DESC
            ) AS observation_rank
          FROM at_latest_date a
          JOIN divergent_slots d
            ON d.user_id IS NOT DISTINCT FROM a.user_id
           AND d.stock_id=a.stock_id AND d.metric_key=a.metric_key
           AND d.period_type IS NOT DISTINCT FROM a.period_type
           AND d.period_end_date IS NOT DISTINCT FROM a.period_end_date
        )
        UPDATE metric_facts f SET is_current=true
        FROM representatives r
        WHERE r.id=f.id AND r.observation_rank=1 AND f.is_current=false;
        SET CONSTRAINTS ALL IMMEDIATE;
        ALTER TABLE metric_facts ENABLE TRIGGER trg_value_line_fact_time_authority;
        ALTER TABLE metric_facts ENABLE TRIGGER trg_value_line_fact_run_binding;
        """
    )

    op.create_table(
        "manual_rationale_erasure_anomalies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("fact_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("field_name", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("observed_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "field_name IN ('reason','note')",
            name="ck_manual_rationale_erasure_anomaly_field",
        ),
        sa.CheckConstraint(
            "reason_code='retained_hash_mismatch'",
            name="ck_manual_rationale_erasure_anomaly_reason",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fact_id", "field_name", name="uq_manual_rationale_erasure_anomaly"
        ),
    )
    op.execute(
        """
        CREATE FUNCTION guard_manual_rationale_erasure_anomaly()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP='INSERT' AND pg_trigger_depth()=2
             AND current_setting('valuepilot.account_erasure',true)='on' THEN
            NEW.created_at:=clock_timestamp();
            NEW.created_txid:=txid_current();
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'manual rationale erasure anomalies are database-owned append-only';
        END $$;
        CREATE TRIGGER trg_manual_rationale_erasure_anomaly_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON manual_rationale_erasure_anomalies
        FOR EACH ROW EXECUTE FUNCTION guard_manual_rationale_erasure_anomaly();
        """
    )
    op.execute(_GOVERNED_FUNCTION)
    op.execute(_PREHASH_FUNCTION)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT count(*) FROM manual_rationale_erasure_anomalies")
    ).scalar_one():
        raise RuntimeError(
            "downgrade refused: cannot discard rationale erasure integrity anomalies"
        )
    duplicate_documents = connection.execute(
        sa.text(
            "SELECT count(*) FROM (SELECT stock_id,metric_key,period_type,"
            "period_end_date,source_document_id FROM metric_facts "
            "WHERE source_type='parsed' AND is_current=true GROUP BY 1,2,3,4,5 "
            "HAVING count(*)>1) d"
        )
    ).scalar_one()
    if duplicate_documents:
        raise RuntimeError(
            "downgrade refused: retained cross-identity parsed ambiguity exists"
        )
    op.execute(_OLD_GOVERNED_FUNCTION)
    op.execute(_OLD_PREHASH_FUNCTION)
    op.execute(
        "DROP TRIGGER trg_manual_rationale_erasure_anomaly_immutable "
        "ON manual_rationale_erasure_anomalies; "
        "DROP FUNCTION guard_manual_rationale_erasure_anomaly()"
    )
    op.drop_table("manual_rationale_erasure_anomalies")
    op.drop_index(
        "uq_metric_facts_current_parsed_identity_period",
        table_name="metric_facts",
    )
    op.create_index(
        "uq_metric_facts_current_parsed_document_period",
        "metric_facts",
        [
            "stock_id",
            "metric_key",
            "period_type",
            "period_end_date",
            "source_document_id",
        ],
        unique=True,
        postgresql_where=sa.text("source_type='parsed' AND is_current=true"),
    )
