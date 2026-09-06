"""Bind privacy tombstones to a target user and database transaction.

Revision ID: 20260904330000
Revises: 20260904320000
"""

from __future__ import annotations

import hashlib
import runpy
from pathlib import Path

import sqlalchemy as sa
from alembic import op


revision = "20260904330000"
down_revision = "20260904320000"
branch_labels = None
depends_on = None


def _qualified_names() -> dict[str, str]:
    connection = op.get_bind()
    schema = connection.execute(sa.text("SELECT current_schema()")).scalar_one()
    quote = connection.dialect.identifier_preparer.quote

    def qualified(name: str) -> str:
        return f"{quote(schema)}.{quote(name)}"

    return {
        "schema": quote(schema),
        "operations": qualified("privacy_erasure_operations"),
        "guard": qualified("guard_privacy_erasure_operation"),
        "begin": qualified("begin_privacy_erasure_operation"),
        "authorized": qualified("privacy_erasure_operation_authorized"),
        "valid": qualified("valid_manual_rationale_tombstone"),
        "users": qualified("users"),
    }


def _capability_verifier() -> str:
    # Import lazily so Alembic revision discovery stays metadata-only. The
    # verifier is environment-specific; only a one-way digest is stored in the
    # database function, never the application/JWT secret or derived token.
    from app.services.privacy_erasure import privacy_erasure_db_capability

    capability = privacy_erasure_db_capability()
    return hashlib.sha256(capability.encode("utf-8")).hexdigest()


def _install_capability_functions(names: dict[str, str]) -> None:
    operations = names["operations"]
    guard = names["guard"]
    begin = names["begin"]
    authorized = names["authorized"]
    valid = names["valid"]
    users = names["users"]
    verifier = _capability_verifier()
    trigger_name = "trg_privacy_erasure_operations_immutable"

    op.execute(
        f"""
        CREATE FUNCTION {guard}()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION
            'privacy erasure operations are database-owned append-only';
        END $$;
        CREATE TRIGGER {trigger_name}
        BEFORE INSERT OR UPDATE OR DELETE ON {operations}
        FOR EACH ROW EXECUTE FUNCTION {guard}();

        CREATE FUNCTION {begin}(
          p_user_id bigint,
          p_operation_kind text,
          p_capability text
        ) RETURNS bigint
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog AS $$
        DECLARE
          existing_id bigint;
          existing_user_id bigint;
          existing_kind text;
          result_id bigint;
        BEGIN
          IF p_operation_kind NOT IN ('account_erasure','revision_redaction') THEN
            RAISE EXCEPTION 'unsupported privacy erasure operation';
          END IF;
          IF encode(sha256(convert_to(p_capability,'UTF8')),'hex')
               IS DISTINCT FROM '{verifier}' THEN
            RAISE EXCEPTION 'privacy erasure capability rejected';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM {users} WHERE id=p_user_id) THEN
            RAISE EXCEPTION 'privacy erasure target does not exist';
          END IF;

          PERFORM pg_advisory_xact_lock(
            hashtextextended('privacy-erasure:' || p_user_id::text,0)
          );
          SELECT id,user_id,operation_kind
            INTO existing_id,existing_user_id,existing_kind
          FROM {operations}
          WHERE created_txid=txid_current();
          IF existing_id IS NOT NULL THEN
            IF existing_user_id=p_user_id AND existing_kind=p_operation_kind THEN
              RETURN existing_id;
            END IF;
            RAISE EXCEPTION
              'a privacy erasure transaction cannot change target or purpose';
          END IF;

          -- The application role owns legacy tables today. Merely revoking an
          -- ACL from a table owner is ineffective, so the operation row has an
          -- always-rejecting trigger. This explicit capability function takes
          -- an ACCESS EXCLUSIVE lock, disables that one trigger transactionally,
          -- writes a DB-stamped row, and restores it. Plain DML cannot perform
          -- the ALTER step; a DB-only caller also lacks the derived capability.
          LOCK TABLE {operations} IN ACCESS EXCLUSIVE MODE;
          EXECUTE 'ALTER TABLE {operations} DISABLE TRIGGER {trigger_name}';
          INSERT INTO {operations}
            (user_id,operation_kind,created_at,created_txid)
          VALUES
            (p_user_id,p_operation_kind,clock_timestamp(),txid_current())
          RETURNING id INTO result_id;
          EXECUTE 'ALTER TABLE {operations} ENABLE TRIGGER {trigger_name}';
          RETURN result_id;
        END $$;
        REVOKE ALL ON FUNCTION {begin}(bigint,text,text) FROM PUBLIC;

        CREATE FUNCTION {authorized}(
          p_user_id bigint,
          p_allowed_kinds text[]
        ) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog AS $$
          SELECT EXISTS (
            SELECT 1 FROM {operations}
            WHERE user_id=p_user_id
              AND created_txid=txid_current()
              AND operation_kind=ANY(p_allowed_kinds)
          )
        $$;
        REVOKE ALL ON FUNCTION {authorized}(bigint,text[]) FROM PUBLIC;

        CREATE FUNCTION {valid}(
          p_old jsonb,
          p_new jsonb,
          p_user_id bigint
        ) RETURNS boolean
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog AS $$
        DECLARE
          old_json jsonb:=COALESCE(p_old,'{{}}'::jsonb);
          expected_json jsonb:=COALESCE(p_old,'{{}}'::jsonb);
          reason_changed boolean;
          note_changed boolean;
          expected_hash text;
        BEGIN
          reason_changed := jsonb_typeof(old_json->'reason')='string'
            AND old_json->>'reason'<>'[redacted]'
            AND p_new->>'reason'='[redacted]';
          note_changed := jsonb_typeof(old_json->'note')='string'
            AND old_json->>'note'<>'[redacted]'
            AND p_new->>'note'='[redacted]';
          IF NOT (reason_changed OR note_changed) OR NOT {authorized}(
              p_user_id,ARRAY['account_erasure','revision_redaction']::text[]
          ) THEN
            RETURN false;
          END IF;

          IF reason_changed THEN
            expected_hash := CASE
              WHEN old_json ? 'redaction_content_hash'
                THEN old_json->>'redaction_content_hash'
              ELSE encode(sha256(convert_to(old_json->>'reason','UTF8')),'hex')
            END;
            expected_json := jsonb_set(
              expected_json,'{{reason}}','"[redacted]"'::jsonb,true
            ) || jsonb_build_object('redaction_content_hash',expected_hash);
          END IF;
          IF note_changed THEN
            expected_hash := CASE
              WHEN old_json ? 'redaction_note_content_hash'
                THEN old_json->>'redaction_note_content_hash'
              ELSE encode(sha256(convert_to(old_json->>'note','UTF8')),'hex')
            END;
            expected_json := jsonb_set(
              expected_json,'{{note}}','"[redacted]"'::jsonb,true
            ) || jsonb_build_object('redaction_note_content_hash',expected_hash);
          END IF;
          RETURN p_new=expected_json;
        END $$;
        REVOKE ALL ON FUNCTION {valid}(jsonb,jsonb,bigint) FROM PUBLIC;
        """
    )


def _install_live_guards(names: dict[str, str]) -> None:
    authorized = names["authorized"]
    valid = names["valid"]
    secure_path = f"SECURITY DEFINER SET search_path=pg_catalog,{names['schema']}"
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION guard_ft07_metric_fact_authority_update()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$
        DECLARE
          governs_owner_earnings boolean;
          governs_piotroski boolean;
          governs_manual_valuation boolean;
          current_state_allowed boolean;
          valuation_content_allowed boolean;
        BEGIN
          governs_owner_earnings :=
            (OLD.source_type='calculated' AND
             OLD.metric_key LIKE 'owners\\_earnings\\_per\\_share%' ESCAPE '\\')
            OR
            (NEW.source_type='calculated' AND
             NEW.metric_key LIKE 'owners\\_earnings\\_per\\_share%' ESCAPE '\\');
          governs_piotroski :=
            (OLD.source_type='calculated' AND
             OLD.metric_key LIKE 'score.piotroski.%')
            OR
            (NEW.source_type='calculated' AND
             NEW.metric_key LIKE 'score.piotroski.%');
          governs_manual_valuation :=
            (OLD.source_type='manual' AND OLD.metric_key='val.fair_value')
            OR
            (NEW.source_type='manual' AND NEW.metric_key='val.fair_value');
          current_state_allowed :=
            OLD.is_current IS NOT DISTINCT FROM NEW.is_current
            OR (OLD.is_current IS TRUE AND NEW.is_current IS FALSE);

          IF governs_owner_earnings OR governs_piotroski THEN
            IF ROW(
                OLD.id,OLD.user_id,OLD.stock_id,OLD.metric_key,OLD.value_json,
                OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,OLD.period,
                OLD.period_type,OLD.period_end_date,OLD.as_of_date,
                OLD.source_document_id,OLD.source_type,OLD.source_ref_id,
                OLD.value_line_parse_run_id,OLD.value_line_legacy_revision,
                OLD.created_at
              ) IS DISTINCT FROM ROW(
                NEW.id,NEW.user_id,NEW.stock_id,NEW.metric_key,NEW.value_json,
                NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,NEW.period,
                NEW.period_type,NEW.period_end_date,NEW.as_of_date,
                NEW.source_document_id,NEW.source_type,NEW.source_ref_id,
                NEW.value_line_parse_run_id,NEW.value_line_legacy_revision,
                NEW.created_at
              ) OR NOT current_state_allowed THEN
              RAISE EXCEPTION 'FT-07 metric fact authority is immutable';
            END IF;
          END IF;

          IF governs_manual_valuation THEN
            IF ROW(
                OLD.id,OLD.user_id,OLD.stock_id,OLD.metric_key,
                OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,
                OLD.period,OLD.period_type,OLD.period_end_date,OLD.as_of_date,
                OLD.source_document_id,OLD.source_type,OLD.source_ref_id,
                OLD.value_line_parse_run_id,OLD.value_line_legacy_revision,
                OLD.created_at
              ) IS DISTINCT FROM ROW(
                NEW.id,NEW.user_id,NEW.stock_id,NEW.metric_key,
                NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,
                NEW.period,NEW.period_type,NEW.period_end_date,NEW.as_of_date,
                NEW.source_document_id,NEW.source_type,NEW.source_ref_id,
                NEW.value_line_parse_run_id,NEW.value_line_legacy_revision,
                NEW.created_at
              ) OR NOT current_state_allowed THEN
              RAISE EXCEPTION 'FT-07 metric fact authority is immutable';
            END IF;
            valuation_content_allowed :=
              OLD.value_json IS NOT DISTINCT FROM NEW.value_json
              OR {valid}(OLD.value_json,NEW.value_json,OLD.user_id);
            IF NOT valuation_content_allowed THEN
              RAISE EXCEPTION 'FT-07 metric fact authority is immutable';
            END IF;
          END IF;
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION guard_governed_metric_fact_immutability()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$
        DECLARE governed boolean;
        BEGIN
          governed := OLD.source_type IN ('manual','calculated','derived');
          IF TG_OP='DELETE' THEN
            IF NOT governed THEN RETURN OLD; END IF;
            IF OLD.source_document_id IS NOT NULL AND pg_trigger_depth()>1
               AND NOT EXISTS (
                 SELECT 1 FROM pdf_documents d WHERE d.id=OLD.source_document_id
               ) THEN RETURN OLD; END IF;
            IF OLD.value_line_report_identity_revision_id IS NOT NULL
               AND pg_trigger_depth()>1 AND NOT EXISTS (
                 SELECT 1 FROM value_line_document_report_identity_revisions r
                 WHERE r.id=OLD.value_line_report_identity_revision_id
               ) THEN RETURN OLD; END IF;
            RAISE EXCEPTION 'metric facts cannot be deleted directly';
          END IF;
          IF NOT governed THEN RETURN NEW; END IF;
          IF OLD.is_current=false AND NEW.is_current=true THEN
            RAISE EXCEPTION 'governed metric facts cannot be reactivated';
          END IF;
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
                 AND NEW.source_type='manual'
                 AND {valid}(OLD.value_json,NEW.value_json,OLD.user_id)
               )
             ) OR (
               OLD.source_type<>'manual'
               AND OLD.source_document_id IS DISTINCT FROM NEW.source_document_id
             ) THEN
            RAISE EXCEPTION
              'governed metric fact content and provenance are immutable';
          END IF;
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION guard_prehashed_manual_rationale_immutability()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$
        DECLARE expected_hash text;
        BEGIN
          IF OLD.source_type<>'manual' THEN RETURN NEW; END IF;
          IF COALESCE(OLD.value_json,'{{}}'::jsonb) ? 'redaction_content_hash'
             AND ROW(OLD.value_json->'reason',OLD.value_json->'redaction_content_hash')
               IS DISTINCT FROM
               ROW(NEW.value_json->'reason',NEW.value_json->'redaction_content_hash')
          THEN
            IF {valid}(OLD.value_json,NEW.value_json,OLD.user_id) THEN
              expected_hash := encode(
                sha256(convert_to(OLD.value_json->>'reason','UTF8')),'hex'
              );
              IF OLD.value_json->>'redaction_content_hash'
                   IS DISTINCT FROM expected_hash THEN
                INSERT INTO manual_rationale_erasure_anomalies
                  (fact_id,user_id,field_name,reason_code,observed_hash,
                   created_at,created_txid)
                VALUES
                  (OLD.id,OLD.user_id,'reason','retained_hash_mismatch',
                   OLD.value_json->>'redaction_content_hash',
                   clock_timestamp(),txid_current())
                ON CONFLICT (fact_id,field_name) DO NOTHING;
              END IF;
            ELSE
              RAISE EXCEPTION 'manual reason privacy hash is immutable';
            END IF;
          END IF;
          IF COALESCE(OLD.value_json,'{{}}'::jsonb) ? 'redaction_note_content_hash'
             AND ROW(OLD.value_json->'note',
                     OLD.value_json->'redaction_note_content_hash')
               IS DISTINCT FROM
               ROW(NEW.value_json->'note',
                   NEW.value_json->'redaction_note_content_hash')
          THEN
            IF {valid}(OLD.value_json,NEW.value_json,OLD.user_id) THEN
              expected_hash := encode(
                sha256(convert_to(OLD.value_json->>'note','UTF8')),'hex'
              );
              IF OLD.value_json->>'redaction_note_content_hash'
                   IS DISTINCT FROM expected_hash THEN
                INSERT INTO manual_rationale_erasure_anomalies
                  (fact_id,user_id,field_name,reason_code,observed_hash,
                   created_at,created_txid)
                VALUES
                  (OLD.id,OLD.user_id,'note','retained_hash_mismatch',
                   OLD.value_json->>'redaction_note_content_hash',
                   clock_timestamp(),txid_current())
                ON CONFLICT (fact_id,field_name) DO NOTHING;
              END IF;
            ELSE
              RAISE EXCEPTION 'manual note privacy hash is immutable';
            END IF;
          END IF;
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION guard_manual_rationale_erasure_anomaly()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$ BEGIN
          IF TG_OP='INSERT' AND pg_trigger_depth()=2
             AND {authorized}(
               NEW.user_id,
               ARRAY['account_erasure','revision_redaction']::text[]
             ) THEN
            NEW.created_at:=clock_timestamp();
            NEW.created_txid:=txid_current();
            RETURN NEW;
          END IF;
          RAISE EXCEPTION
            'manual rationale erasure anomalies are database-owned append-only';
        END $$;

        CREATE OR REPLACE FUNCTION reject_research_append_only_mutation()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$
        DECLARE old_row jsonb; new_row jsonb;
        BEGIN
          old_row:=to_jsonb(OLD);
          new_row:=to_jsonb(NEW);
          IF TG_TABLE_NAME='position_journal_events' AND TG_OP='UPDATE'
             AND {authorized}(
               (old_row->>'user_id')::bigint,
               ARRAY['account_erasure']::text[]
             )
             AND (new_row-ARRAY[
               'prior_quantity','new_quantity','prior_average_unit_cost',
               'new_average_unit_cost','reason','research_case_id',
               'research_revision_id','payload_json'
             ]) IS NOT DISTINCT FROM (old_row-ARRAY[
               'prior_quantity','new_quantity','prior_average_unit_cost',
               'new_average_unit_cost','reason','research_case_id',
               'research_revision_id','payload_json'
             ])
             AND new_row->'prior_quantity'='null'::jsonb
             AND new_row->'new_quantity'='null'::jsonb
             AND new_row->'prior_average_unit_cost'='null'::jsonb
             AND new_row->'new_average_unit_cost'='null'::jsonb
             AND new_row->'reason'='null'::jsonb
             AND new_row->'research_case_id'='null'::jsonb
             AND new_row->'research_revision_id'='null'::jsonb
             AND new_row->'payload_json'=jsonb_build_object('privacy_erased',true)
          THEN RETURN NEW; END IF;
          RAISE EXCEPTION '% is append-only; % is forbidden',TG_TABLE_NAME,TG_OP;
        END $$;
        """
    )


def upgrade() -> None:
    op.create_table(
        "privacy_erasure_operations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("operation_kind", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "operation_kind IN ('account_erasure','revision_redaction')",
            name="ck_privacy_erasure_operation_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "created_txid", name="uq_privacy_erasure_operations_txid"
        ),
    )
    op.create_index(
        "ix_privacy_erasure_operations_user_txid",
        "privacy_erasure_operations",
        ["user_id", "created_txid"],
    )
    names = _qualified_names()
    _install_capability_functions(names)
    _install_live_guards(names)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT count(*) FROM privacy_erasure_operations")
    ).scalar_one():
        raise RuntimeError(
            "downgrade refused: cannot discard retained privacy erasure authority"
        )
    names = _qualified_names()
    # Restore the parent revision's live functions before removing helpers.
    _restore_r24_functions()
    op.execute(
        f"DROP FUNCTION {names['valid']}(jsonb,jsonb,bigint);"
        f"DROP FUNCTION {names['authorized']}(bigint,text[]);"
        f"DROP FUNCTION {names['begin']}(bigint,text,text);"
        f"DROP TRIGGER trg_privacy_erasure_operations_immutable ON "
        f"{names['operations']};"
        f"DROP FUNCTION {names['guard']}()"
    )
    op.drop_index(
        "ix_privacy_erasure_operations_user_txid",
        table_name="privacy_erasure_operations",
    )
    op.drop_table("privacy_erasure_operations")


def _restore_r24_functions() -> None:
    """Restore parent live behavior for an empty, development-only roundtrip."""

    r16 = runpy.run_path(
        str(Path(__file__).with_name("20260904160000-piotroski-method-authority.py"))
    )
    r24 = runpy.run_path(
        str(
            Path(__file__).with_name(
                "20260904320000-r24-currentness-and-privacy-authority.py"
            )
        )
    )
    op.execute(r16["_guard_sql"](protect_piotroski=True))
    op.execute(r24["_GOVERNED_FUNCTION"])
    op.execute(r24["_PREHASH_FUNCTION"])
    op.execute(_R24_ANOMALY_GUARD)
    op.execute(_R24_APPEND_ONLY_GUARD)


# Exact parent behavior is retained only so an empty-schema downgrade remains
# structurally valid. Any R25 operation is irreversible and blocks downgrade.
_R24_APPEND_ONLY_GUARD = r"""
CREATE OR REPLACE FUNCTION reject_research_append_only_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  IF TG_OP='UPDATE'
     AND current_setting('valuepilot.account_erasure',true)='on' THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION '% is append-only; % is forbidden',TG_TABLE_NAME,TG_OP;
END $$;
"""

_R24_ANOMALY_GUARD = r"""
CREATE OR REPLACE FUNCTION guard_manual_rationale_erasure_anomaly()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  IF TG_OP='INSERT' AND pg_trigger_depth()=2
     AND current_setting('valuepilot.account_erasure',true)='on' THEN
    NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
    RETURN NEW;
  END IF;
  RAISE EXCEPTION
    'manual rationale erasure anomalies are database-owned append-only';
END $$;
"""
