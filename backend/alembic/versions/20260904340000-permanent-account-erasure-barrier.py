"""Make account erasure permanent and serialize user-owned writes.

Revision ID: 20260904340000
Revises: 20260904330000
"""

from __future__ import annotations

import hashlib
import runpy
from pathlib import Path

import sqlalchemy as sa
from alembic import op


revision = "20260904340000"
down_revision = "20260904330000"
branch_labels = None
depends_on = None


def _names() -> dict[str, str]:
    connection = op.get_bind()
    schema_name = connection.execute(sa.text("SELECT current_schema()")) .scalar_one()
    quote = connection.dialect.identifier_preparer.quote

    def qualified(name: str) -> str:
        return f"{quote(schema_name)}.{quote(name)}"

    return {
        "schema": quote(schema_name),
        "lock_namespace": schema_name.replace("'", "''"),
        "users": qualified("users"),
        "operations": qualified("privacy_erasure_operations"),
        "barriers": qualified("account_erasure_barriers"),
        "events": qualified("account_erasure_events"),
        "operation_guard": qualified("guard_privacy_erasure_operation"),
        "begin": qualified("begin_privacy_erasure_operation"),
        "authorized": qualified("privacy_erasure_operation_authorized"),
        "lock_user": qualified("lock_user_privacy_write"),
        "barrier_guard": qualified("guard_account_erasure_barrier"),
        "event_guard": qualified("guard_account_erasure_event"),
        "user_guard": qualified("guard_permanently_erased_user"),
        "private_guard": qualified("guard_private_user_write"),
        "text_tombstone": qualified("valid_private_text_tombstone"),
    }


def _verifier() -> str:
    from app.services.privacy_erasure import privacy_erasure_db_capability

    return hashlib.sha256(
        privacy_erasure_db_capability().encode("utf-8")
    ).hexdigest()


def _install_erasure_runtime(names: dict[str, str]) -> None:
    users = names["users"]
    operations = names["operations"]
    barriers = names["barriers"]
    events = names["events"]
    operation_guard = names["operation_guard"]
    begin = names["begin"]
    authorized = names["authorized"]
    lock_user = names["lock_user"]
    barrier_guard = names["barrier_guard"]
    event_guard = names["event_guard"]
    user_guard = names["user_guard"]
    private_guard = names["private_guard"]
    text_tombstone = names["text_tombstone"]
    verifier = _verifier()
    lock_namespace = names["lock_namespace"]
    secure_path = f"SECURITY DEFINER SET search_path=pg_catalog,{names['schema']}"

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {authorized}(
          p_user_id bigint,p_allowed_kinds text[]
        ) RETURNS boolean
        LANGUAGE sql STABLE {secure_path} AS $$
          SELECT EXISTS (
            SELECT 1 FROM {operations} p
            WHERE p.user_id=p_user_id
              AND p.created_txid=txid_current()
              AND p.operation_kind=ANY(p_allowed_kinds)
              AND (
                p.operation_kind<>'account_erasure'
                OR NOT EXISTS (
                  SELECT 1 FROM {events} e
                  WHERE e.privacy_erasure_operation_id=p.id
                )
              )
          )
        $$;
        REVOKE ALL ON FUNCTION {authorized}(bigint,text[]) FROM PUBLIC;

        CREATE OR REPLACE FUNCTION {operation_guard}()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$ BEGIN
          IF TG_OP='INSERT'
             AND encode(sha256(convert_to(COALESCE(
               current_setting('valuepilot.privacy_erasure_capability',true),''
             ),'UTF8')),'hex')='{verifier}' THEN
            NEW.created_at:=clock_timestamp();
            NEW.created_txid:=txid_current();
            RETURN NEW;
          END IF;
          RAISE EXCEPTION
            'privacy erasure operations are database-owned append-only';
        END $$;

        CREATE OR REPLACE FUNCTION {lock_user}(p_user_id bigint)
        RETURNS boolean LANGUAGE plpgsql {secure_path} AS $$
        DECLARE blocked boolean;
        BEGIN
          -- Every participating writer takes this shared lock before any
          -- stock/case/fact child lock. Account erasure takes the exclusive
          -- form of the same per-user key.
          PERFORM pg_advisory_xact_lock_shared(
            hashtextextended(
              '{lock_namespace}:valuepilot-user:' || p_user_id::text,0
            )
          );
          IF NOT EXISTS (SELECT 1 FROM {users} WHERE id=p_user_id) THEN
            RETURN false;
          END IF;
          SELECT EXISTS(
            SELECT 1 FROM {barriers} WHERE user_id=p_user_id
          ) AND NOT {authorized}(
            p_user_id,ARRAY['account_erasure']::text[]
          ) INTO blocked;
          RETURN NOT blocked;
        END $$;

        CREATE OR REPLACE FUNCTION {begin}(
          p_user_id bigint,
          p_operation_kind text,
          p_capability text
        ) RETURNS bigint
        LANGUAGE plpgsql {secure_path} AS $$
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

          -- Account erasure takes the exclusive form of the one canonical
          -- user lock. A revision-only redaction remains an ordinary private
          -- write and takes the shared form. Different users never serialize.
          IF p_operation_kind='account_erasure' THEN
            PERFORM pg_advisory_xact_lock(
              hashtextextended(
                '{lock_namespace}:valuepilot-user:' || p_user_id::text,0
              )
            );
            PERFORM 1 FROM {users} WHERE id=p_user_id FOR UPDATE;
          ELSE
            PERFORM pg_advisory_xact_lock_shared(
              hashtextextended(
                '{lock_namespace}:valuepilot-user:' || p_user_id::text,0
              )
            );
            PERFORM 1 FROM {users} WHERE id=p_user_id;
          END IF;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'privacy erasure target does not exist';
          END IF;
          IF EXISTS (SELECT 1 FROM {barriers} WHERE user_id=p_user_id) THEN
            RAISE EXCEPTION 'privacy erasure target is permanently erased';
          END IF;

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

          -- The trigger accepts only the preimage verified here. A caller
          -- holding only the database credential can read the digest but
          -- cannot forge this transaction-local capability.
          PERFORM set_config(
            'valuepilot.privacy_erasure_capability',p_capability,true
          );
          INSERT INTO {operations}
            (user_id,operation_kind,created_at,created_txid)
          VALUES
            (p_user_id,p_operation_kind,clock_timestamp(),txid_current())
          RETURNING id INTO result_id;

          IF p_operation_kind='account_erasure' THEN
            INSERT INTO {barriers}
              (user_id,privacy_erasure_operation_id,created_at,created_txid)
            VALUES
              (p_user_id,result_id,clock_timestamp(),txid_current());
            UPDATE {users} SET is_active=false WHERE id=p_user_id;
          END IF;
          RETURN result_id;
        END $$;
        REVOKE ALL ON FUNCTION {begin}(bigint,text,text) FROM PUBLIC;

        CREATE OR REPLACE FUNCTION {barrier_guard}()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$
        DECLARE operation_id bigint;
        BEGIN
          IF TG_OP<>'INSERT' THEN
            RAISE EXCEPTION 'account erasure barriers are permanent';
          END IF;
          SELECT id INTO operation_id FROM {operations}
          WHERE user_id=NEW.user_id
            AND operation_kind='account_erasure'
            AND created_txid=txid_current();
          IF operation_id IS NULL
             OR NEW.privacy_erasure_operation_id IS DISTINCT FROM operation_id
             OR encode(sha256(convert_to(COALESCE(
               current_setting('valuepilot.privacy_erasure_capability',true),''
             ),'UTF8')),'hex')<>'{verifier}' THEN
            RAISE EXCEPTION 'account erasure barrier is not authorized';
          END IF;
          NEW.created_at:=clock_timestamp();
          NEW.created_txid:=txid_current();
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION {event_guard}()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$
        DECLARE operation_id bigint;
        BEGIN
          IF TG_OP<>'INSERT' THEN
            RAISE EXCEPTION 'account erasure events are append-only';
          END IF;
          SELECT id INTO operation_id FROM {operations}
          WHERE user_id=NEW.user_id
            AND operation_kind='account_erasure'
            AND created_txid=txid_current();
          IF operation_id IS NULL
             OR NEW.privacy_erasure_operation_id IS DISTINCT FROM operation_id
             OR NOT EXISTS (
               SELECT 1 FROM {barriers} b
               WHERE b.user_id=NEW.user_id
                 AND b.privacy_erasure_operation_id=operation_id
             ) THEN
            RAISE EXCEPTION 'account erasure event is not authorized';
          END IF;
          NEW.created_at:=clock_timestamp();
          NEW.created_txid:=txid_current();
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION {user_guard}()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$ BEGIN
          IF EXISTS (SELECT 1 FROM {barriers} WHERE user_id=OLD.id)
             AND NOT {authorized}(
               OLD.id,ARRAY['account_erasure']::text[]
             ) THEN
            RAISE EXCEPTION 'user is permanently erased';
          END IF;
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION {private_guard}()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$
        DECLARE owner_id bigint;
        DECLARE old_json jsonb;
        DECLARE new_json jsonb;
        BEGIN
          old_json:=CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD) END;
          new_json:=CASE WHEN TG_OP='DELETE' THEN NULL ELSE to_jsonb(NEW) END;
          IF TG_TABLE_NAME='metric_facts' THEN
            IF TG_OP='INSERT' AND NEW.source_type NOT IN ('manual','derived','calculated')
              THEN RETURN NEW;
            ELSIF TG_OP='DELETE' AND OLD.source_type NOT IN ('manual','derived','calculated')
              THEN RETURN OLD;
            ELSIF TG_OP='UPDATE'
              AND OLD.source_type NOT IN ('manual','derived','calculated')
              AND NEW.source_type NOT IN ('manual','derived','calculated')
              THEN RETURN NEW;
            END IF;
            IF TG_OP='UPDATE' AND OLD.user_id IS DISTINCT FROM NEW.user_id THEN
              RAISE EXCEPTION 'private fact ownership is immutable';
            END IF;
            owner_id:=CASE WHEN TG_OP='INSERT' THEN NEW.user_id ELSE OLD.user_id END;
          ELSIF TG_TABLE_NAME='research_cases' THEN
            IF TG_OP='INSERT' AND (
                 new_json->>'void_reason'='[redacted]'
                 OR new_json->>'void_reason_content_hash' IS NOT NULL
               ) THEN
              RAISE EXCEPTION 'research case private tombstone is invalid';
            END IF;
            IF TG_OP='UPDATE' AND OLD.user_id IS DISTINCT FROM NEW.user_id THEN
              RAISE EXCEPTION 'research case ownership is immutable';
            END IF;
            owner_id:=CASE WHEN TG_OP='INSERT' THEN NEW.user_id ELSE OLD.user_id END;
          ELSE
            SELECT user_id INTO owner_id FROM research_cases
            WHERE id=CASE
              WHEN TG_OP='INSERT' THEN (new_json->>'case_id')::bigint
              ELSE (old_json->>'case_id')::bigint
            END;
            IF TG_TABLE_NAME='research_case_revisions' AND TG_OP='INSERT'
               AND (
                 (new_json->>'is_redacted')::boolean
                 OR new_json->>'redaction_reason' IS NOT NULL
                 OR new_json->>'redaction_reason_content_hash' IS NOT NULL
               ) THEN
              RAISE EXCEPTION 'research revision must be redacted by audited update';
            END IF;
          END IF;
          IF owner_id IS NULL OR NOT {lock_user}(owner_id) THEN
            RAISE EXCEPTION 'user is permanently erased';
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION {text_tombstone}(
          p_old text,p_new text,p_old_hash text,p_new_hash text
        ) RETURNS boolean
        LANGUAGE sql IMMUTABLE {secure_path} AS $$
          SELECT p_old IS NOT NULL AND p_old<>'[redacted]'
             AND p_new='[redacted]'
             AND p_new_hash=COALESCE(
               p_old_hash,
               encode(sha256(convert_to(p_old,'UTF8')),'hex')
             )
        $$;
        """
    )


def _install_tombstone_guards(names: dict[str, str]) -> None:
    authorized = names["authorized"]
    text_tombstone = names["text_tombstone"]
    secure_path = f"SECURITY DEFINER SET search_path=pg_catalog,{names['schema']}"
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION guard_research_case_private_text()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$ BEGIN
          IF TG_OP='UPDATE' THEN
            IF OLD.void_reason='[redacted]'
               OR OLD.void_reason_content_hash IS NOT NULL THEN
              IF ROW(NEW.void_reason,NEW.void_reason_content_hash)
                   IS DISTINCT FROM
                   ROW(OLD.void_reason,OLD.void_reason_content_hash) THEN
                RAISE EXCEPTION 'research case private tombstone is immutable';
              END IF;
            ELSIF NEW.void_reason='[redacted]'
                  OR NEW.void_reason_content_hash IS NOT NULL THEN
              IF NOT {authorized}(
                   OLD.user_id,ARRAY['account_erasure']::text[]
                 ) OR NOT {text_tombstone}(
                   OLD.void_reason,NEW.void_reason,
                   OLD.void_reason_content_hash,NEW.void_reason_content_hash
                 ) THEN
                RAISE EXCEPTION 'research case private tombstone is invalid';
              END IF;
            END IF;
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION guard_research_revision_redaction()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$
        DECLARE owner_id bigint;
        BEGIN
          IF TG_OP='DELETE' THEN
            RAISE EXCEPTION
              'research_case_revisions is append-only; DELETE is forbidden';
          END IF;
          SELECT user_id INTO owner_id FROM research_cases WHERE id=OLD.case_id;
          IF OLD.is_redacted THEN
            IF NOT {authorized}(
                 owner_id,ARRAY['account_erasure']::text[]
               ) OR NOT {text_tombstone}(
                 OLD.redaction_reason,NEW.redaction_reason,
                 OLD.redaction_reason_content_hash,
                 NEW.redaction_reason_content_hash
               ) OR (to_jsonb(NEW)-ARRAY[
                    'redaction_reason','redaction_reason_content_hash'
                  ]) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY[
                    'redaction_reason','redaction_reason_content_hash'
                  ]) THEN
              RAISE EXCEPTION
                'research revision private tombstone is invalid';
            END IF;
            RETURN NEW;
          END IF;
          IF NOT NEW.is_redacted
             OR (to_jsonb(NEW)-ARRAY[
                  'thesis','variant_view','decision_reason','assumptions_json',
                  'risks_json','evidence_json','valuation_unavailable_reason',
                  'is_redacted','redaction_content_hash','redaction_reason',
                  'redaction_reason_content_hash','redacted_by_user_id','redacted_at'
                ]) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY[
                  'thesis','variant_view','decision_reason','assumptions_json',
                  'risks_json','evidence_json','valuation_unavailable_reason',
                  'is_redacted','redaction_content_hash','redaction_reason',
                  'redaction_reason_content_hash','redacted_by_user_id','redacted_at'
                ]) THEN
            RAISE EXCEPTION
              'research_case_revisions permits only one audited content redaction';
          END IF;
          IF NEW.redaction_reason='[redacted]' THEN
            IF NOT {authorized}(
                 owner_id,ARRAY['account_erasure']::text[]
               ) OR NEW.redaction_reason_content_hash IS DISTINCT FROM
                 encode(sha256(convert_to('account_erasure','UTF8')),'hex') THEN
              RAISE EXCEPTION 'research revision private tombstone is invalid';
            END IF;
          ELSIF NEW.redaction_reason_content_hash IS NOT NULL THEN
            RAISE EXCEPTION 'research revision private hash is invalid';
          END IF;
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION reject_research_append_only_mutation()
        RETURNS trigger LANGUAGE plpgsql {secure_path} AS $$
        DECLARE owner_id bigint;
        DECLARE expected jsonb;
        DECLARE old_reason text;
        DECLARE old_json jsonb;
        DECLARE new_json jsonb;
        BEGIN
          old_json:=to_jsonb(OLD);
          new_json:=to_jsonb(NEW);
          IF TG_TABLE_NAME='position_journal_events' AND TG_OP='UPDATE'
             AND {authorized}(
               (old_json->>'user_id')::bigint,
               ARRAY['account_erasure']::text[]
             )
             AND (to_jsonb(NEW)-ARRAY[
               'prior_quantity','new_quantity','prior_average_unit_cost',
               'new_average_unit_cost','reason','research_case_id',
               'research_revision_id','payload_json'
             ]) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY[
               'prior_quantity','new_quantity','prior_average_unit_cost',
               'new_average_unit_cost','reason','research_case_id',
               'research_revision_id','payload_json'
             ])
             AND new_json->'prior_quantity'='null'::jsonb
             AND new_json->'new_quantity'='null'::jsonb
             AND new_json->'prior_average_unit_cost'='null'::jsonb
             AND new_json->'new_average_unit_cost'='null'::jsonb
             AND new_json->'reason'='null'::jsonb
             AND new_json->'research_case_id'='null'::jsonb
             AND new_json->'research_revision_id'='null'::jsonb
             AND new_json->'payload_json'=jsonb_build_object('privacy_erased',true)
          THEN RETURN NEW; END IF;

          IF TG_TABLE_NAME='research_case_events' AND TG_OP='UPDATE'
             AND old_json->>'event_type'='revision_redacted' THEN
            SELECT user_id INTO owner_id FROM research_cases
            WHERE id=(old_json->>'case_id')::bigint;
            old_reason:=old_json->'payload_json'->>'reason';
            expected:=jsonb_set(
              old_json->'payload_json','{{reason}}','"[redacted]"'::jsonb,true
            ) || jsonb_build_object(
              'redaction_reason_content_hash',
              encode(sha256(convert_to(old_reason,'UTF8')),'hex')
            );
            IF {authorized}(
                 owner_id,ARRAY['account_erasure']::text[]
               ) AND old_reason IS NOT NULL AND old_reason<>'[redacted]'
               AND new_json->'payload_json'=expected
               AND (new_json-'payload_json') IS NOT DISTINCT FROM
                   (old_json-'payload_json') THEN
              RETURN NEW;
            END IF;
          END IF;
          RAISE EXCEPTION '% is append-only; % is forbidden',TG_TABLE_NAME,TG_OP;
        END $$;
        """
    )


def upgrade() -> None:
    op.add_column(
        "research_cases",
        sa.Column("void_reason_content_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "research_case_revisions",
        sa.Column(
            "redaction_reason_content_hash", sa.String(length=64), nullable=True
        ),
    )
    op.add_column(
        "account_erasure_events",
        sa.Column("privacy_erasure_operation_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "account_erasure_events",
        sa.Column("created_txid", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_account_erasure_events_privacy_operation",
        "account_erasure_events",
        "privacy_erasure_operations",
        ["privacy_erasure_operation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_account_erasure_events_privacy_operation",
        "account_erasure_events",
        ["privacy_erasure_operation_id"],
        unique=True,
        postgresql_where=sa.text("privacy_erasure_operation_id IS NOT NULL"),
    )
    op.create_table(
        "account_erasure_barriers",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("privacy_erasure_operation_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["privacy_erasure_operation_id"],
            ["privacy_erasure_operations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint(
            "privacy_erasure_operation_id",
            name="uq_account_erasure_barriers_operation",
        ),
    )

    # Upgrade legacy completed erasures into an explicit permanent state. The
    # negative transaction id is a visible migration marker, never a claim of
    # historical MVCC identity and can never authorize current-transaction DML.
    op.execute(
        """
        ALTER TABLE privacy_erasure_operations
          DISABLE TRIGGER trg_privacy_erasure_operations_immutable;
        INSERT INTO privacy_erasure_operations
          (user_id,operation_kind,created_at,created_txid)
        SELECT e.user_id,'account_erasure',e.created_at,-e.id
        FROM account_erasure_events e
        WHERE NOT EXISTS (
          SELECT 1 FROM privacy_erasure_operations p
          WHERE p.user_id=e.user_id AND p.operation_kind='account_erasure'
        );
        ALTER TABLE privacy_erasure_operations
          ENABLE TRIGGER trg_privacy_erasure_operations_immutable;

        UPDATE account_erasure_events e SET
          privacy_erasure_operation_id=(
            SELECT p.id FROM privacy_erasure_operations p
            WHERE p.user_id=e.user_id AND p.operation_kind='account_erasure'
            ORDER BY p.id LIMIT 1
          ),
          created_txid=(
            SELECT p.created_txid FROM privacy_erasure_operations p
            WHERE p.user_id=e.user_id AND p.operation_kind='account_erasure'
            ORDER BY p.id LIMIT 1
          );
        INSERT INTO account_erasure_barriers
          (user_id,privacy_erasure_operation_id,created_at,created_txid)
        SELECT e.user_id,e.privacy_erasure_operation_id,e.created_at,e.created_txid
        FROM account_erasure_events e;
        UPDATE users u SET is_active=false
        WHERE EXISTS (
          SELECT 1 FROM account_erasure_barriers b WHERE b.user_id=u.id
        );
        """
    )
    op.alter_column(
        "account_erasure_events", "privacy_erasure_operation_id", nullable=False
    )
    op.alter_column("account_erasure_events", "created_txid", nullable=False)

    names = _names()
    _install_erasure_runtime(names)
    _install_tombstone_guards(names)
    op.execute(
        """
        DROP TRIGGER trg_account_erasure_events_append_only
          ON account_erasure_events;
        CREATE TRIGGER trg_account_erasure_events_append_only
          BEFORE INSERT OR UPDATE OR DELETE ON account_erasure_events
          FOR EACH ROW EXECUTE FUNCTION guard_account_erasure_event();

        CREATE TRIGGER trg_account_erasure_barriers_permanent
          BEFORE INSERT OR UPDATE OR DELETE ON account_erasure_barriers
          FOR EACH ROW EXECUTE FUNCTION guard_account_erasure_barrier();
        CREATE TRIGGER trg_users_permanent_erasure
          BEFORE UPDATE ON users
          FOR EACH ROW EXECUTE FUNCTION guard_permanently_erased_user();

        CREATE TRIGGER trg_00_privacy_metric_facts
          BEFORE INSERT OR UPDATE OR DELETE ON metric_facts
          FOR EACH ROW EXECUTE FUNCTION guard_private_user_write();
        CREATE TRIGGER trg_00_privacy_research_cases
          BEFORE INSERT OR UPDATE OR DELETE ON research_cases
          FOR EACH ROW EXECUTE FUNCTION guard_private_user_write();
        CREATE TRIGGER trg_00_privacy_research_case_origins
          BEFORE INSERT OR UPDATE OR DELETE ON research_case_origins
          FOR EACH ROW EXECUTE FUNCTION guard_private_user_write();
        CREATE TRIGGER trg_00_privacy_research_case_revisions
          BEFORE INSERT OR UPDATE OR DELETE ON research_case_revisions
          FOR EACH ROW EXECUTE FUNCTION guard_private_user_write();
        CREATE TRIGGER trg_00_privacy_research_case_events
          BEFORE INSERT OR UPDATE OR DELETE ON research_case_events
          FOR EACH ROW EXECUTE FUNCTION guard_private_user_write();
        CREATE TRIGGER trg_research_cases_private_text
          BEFORE INSERT OR UPDATE ON research_cases
          FOR EACH ROW EXECUTE FUNCTION guard_research_case_private_text();
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT count(*) FROM account_erasure_barriers")
    ).scalar_one():
        raise RuntimeError(
            "downgrade refused: cannot discard permanent account erasure barriers"
        )
    names = _names()
    r25 = runpy.run_path(
        str(Path(__file__).with_name("20260904330000-db-owned-privacy-erasure.py"))
    )

    op.execute(
        """
        DROP TRIGGER trg_research_cases_private_text ON research_cases;
        DROP TRIGGER trg_00_privacy_research_case_events ON research_case_events;
        DROP TRIGGER trg_00_privacy_research_case_revisions ON research_case_revisions;
        DROP TRIGGER trg_00_privacy_research_case_origins ON research_case_origins;
        DROP TRIGGER trg_00_privacy_research_cases ON research_cases;
        DROP TRIGGER trg_00_privacy_metric_facts ON metric_facts;
        DROP TRIGGER trg_users_permanent_erasure ON users;
        DROP TRIGGER trg_account_erasure_barriers_permanent
          ON account_erasure_barriers;
        DROP TRIGGER trg_account_erasure_events_append_only
          ON account_erasure_events;
        """
    )
    r25["_install_live_guards"](r25["_qualified_names"]())
    op.execute(
        """
        CREATE TRIGGER trg_account_erasure_events_append_only
          BEFORE UPDATE OR DELETE ON account_erasure_events
          FOR EACH ROW EXECUTE FUNCTION reject_research_append_only_mutation();
        DROP FUNCTION guard_research_case_private_text();
        DROP FUNCTION valid_private_text_tombstone(text,text,text,text);
        DROP FUNCTION guard_private_user_write();
        DROP FUNCTION guard_permanently_erased_user();
        DROP FUNCTION guard_account_erasure_event();
        DROP FUNCTION guard_account_erasure_barrier();
        DROP FUNCTION lock_user_privacy_write(bigint);
        """
    )
    _restore_parent_operation_runtime(names)
    op.drop_table("account_erasure_barriers")
    op.drop_index(
        "uq_account_erasure_events_privacy_operation",
        table_name="account_erasure_events",
    )
    op.drop_constraint(
        "fk_account_erasure_events_privacy_operation",
        "account_erasure_events",
        type_="foreignkey",
    )
    op.drop_column("account_erasure_events", "created_txid")
    op.drop_column("account_erasure_events", "privacy_erasure_operation_id")
    op.drop_column("research_case_revisions", "redaction_reason_content_hash")
    op.drop_column("research_cases", "void_reason_content_hash")


def _restore_parent_operation_runtime(names: dict[str, str]) -> None:
    operations = names["operations"]
    guard = names["operation_guard"]
    begin = names["begin"]
    authorized = names["authorized"]
    users = names["users"]
    verifier = _verifier()
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {authorized}(
          p_user_id bigint,p_allowed_kinds text[]
        ) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
          SELECT EXISTS (
            SELECT 1 FROM {operations}
            WHERE user_id=p_user_id
              AND created_txid=txid_current()
              AND operation_kind=ANY(p_allowed_kinds)
          )
        $$;
        REVOKE ALL ON FUNCTION {authorized}(bigint,text[]) FROM PUBLIC;
        CREATE OR REPLACE FUNCTION {guard}()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION
            'privacy erasure operations are database-owned append-only';
        END $$;
        CREATE OR REPLACE FUNCTION {begin}(
          p_user_id bigint,p_operation_kind text,p_capability text
        ) RETURNS bigint
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE existing_id bigint; existing_user_id bigint;
          existing_kind text; result_id bigint;
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
          FROM {operations} WHERE created_txid=txid_current();
          IF existing_id IS NOT NULL THEN
            IF existing_user_id=p_user_id AND existing_kind=p_operation_kind THEN
              RETURN existing_id;
            END IF;
            RAISE EXCEPTION
              'a privacy erasure transaction cannot change target or purpose';
          END IF;
          LOCK TABLE {operations} IN ACCESS EXCLUSIVE MODE;
          EXECUTE 'ALTER TABLE {operations}
            DISABLE TRIGGER trg_privacy_erasure_operations_immutable';
          INSERT INTO {operations}
            (user_id,operation_kind,created_at,created_txid)
          VALUES (p_user_id,p_operation_kind,clock_timestamp(),txid_current())
          RETURNING id INTO result_id;
          EXECUTE 'ALTER TABLE {operations}
            ENABLE TRIGGER trg_privacy_erasure_operations_immutable';
          RETURN result_id;
        END $$;
        REVOKE ALL ON FUNCTION {begin}(bigint,text,text) FROM PUBLIC;
        """
    )
