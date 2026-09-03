"""Add crash-safe SEC acceptance case completion ownership.

Revision ID: 20260901200000
Revises: 20260901190000
"""

from alembic import op


revision = "20260901200000"
down_revision = "20260901190000"
branch_labels = None
depends_on = None


def _runtime_counts_function(completion_claims: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION sec_acceptance_runtime_counts()
        RETURNS jsonb LANGUAGE sql STABLE AS $$
          SELECT sec_acceptance_evidence_counts() || jsonb_build_object(
            'users',(SELECT count(*) FROM users),
            'stocks',(SELECT count(*) FROM stocks),
            'pdf_documents',(SELECT count(*) FROM pdf_documents),
            'metric_extractions',(SELECT count(*) FROM metric_extractions),
            'metric_facts_total',(SELECT count(*) FROM metric_facts),
            'metric_facts_manual',(SELECT count(*) FROM metric_facts WHERE source_type='manual'),
            'metric_facts_other',(SELECT count(*) FROM metric_facts WHERE source_type NOT IN ('sec','manual')),
            'metric_facts_user_owned',(SELECT count(*) FROM metric_facts WHERE user_id IS NOT NULL),
            'ingestion_operations',(SELECT count(*) FROM sec_financial_ingestion_operations),
            'operation_results',(SELECT count(*) FROM sec_financial_operation_results),
            'lineage_availabilities',(SELECT count(*) FROM sec_financial_lineage_availabilities),
            'accession_attempts',(SELECT count(*) FROM sec_financial_accession_attempts),
            'operation_snapshot_links',(SELECT count(*) FROM sec_financial_operation_snapshots),
            'acquisition_resolutions',(SELECT count(*) FROM sec_financial_acquisition_resolutions),
            'resource_anchors',(SELECT count(*) FROM sec_financial_resource_anchors),
            'history_continuations',(SELECT count(*) FROM sec_financial_history_continuations),
            'history_consumption_claims',(SELECT count(*) FROM sec_financial_history_consumption_claims),
            'history_continuation_failures',(SELECT count(*) FROM sec_financial_history_continuation_failures),
            'acquisition_failures',(SELECT count(*) FROM sec_financial_acquisition_failures),
            'attempt_artifact_links',(SELECT count(*) FROM sec_financial_accession_attempt_artifacts),
            'legacy_parse_runs',(SELECT count(*) FROM sec_financial_legacy_parse_runs),
            'economic_classification_reviews',(SELECT count(*) FROM sec_economic_classification_reviews),
            'economic_risk_attribute_reviews',(SELECT count(*) FROM sec_economic_risk_attribute_reviews),
            'mapping_versions',(SELECT count(*) FROM sec_metric_mapping_versions),
            'mapping_rules',(SELECT count(*) FROM sec_metric_mapping_rules),
            'mapping_rule_concepts',(SELECT count(*) FROM sec_metric_mapping_rule_concepts),
            'method_policy_versions',(SELECT count(*) FROM sec_method_policy_versions),
            'acceptance_case_attempts',(SELECT count(*) FROM sec_acceptance_case_attempts),
            'acceptance_operation_links',(SELECT count(*) FROM sec_acceptance_operation_links),
            'acceptance_evidence_checkpoints',(SELECT count(*) FROM sec_acceptance_evidence_checkpoints),
            'acceptance_report_readiness',(SELECT count(*) FROM sec_acceptance_report_readiness),
            'acceptance_publication_bindings',(SELECT count(*) FROM sec_acceptance_publication_bindings)
            {completion_claims}
          )
        $$;
    """


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION sec_acceptance_completion_lock_namespace()
        RETURNS integer LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
          SELECT 1448296515::integer
        $$;

        CREATE FUNCTION sec_acceptance_completion_lock_local(
          scoped_run_id text,
          scoped_case_id text,
          scoped_acceptance_pass smallint
        ) RETURNS integer LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
        BEGIN
          IF scoped_run_id='' OR scoped_case_id='' OR
             scoped_acceptance_pass NOT IN (1,2) THEN
            RAISE EXCEPTION 'invalid SEC acceptance completion lock scope';
          END IF;
          RETURN hashtext(
            encode(convert_to(scoped_run_id,'UTF8'),'hex') || ':' ||
            encode(convert_to(scoped_case_id,'UTF8'),'hex') || ':' ||
            scoped_acceptance_pass::text
          );
        END $$;

        CREATE FUNCTION sec_acceptance_completion_session_lock_held(
          scoped_run_id text,
          scoped_case_id text,
          scoped_acceptance_pass smallint
        ) RETURNS boolean LANGUAGE sql STABLE STRICT PARALLEL SAFE AS $$
          SELECT EXISTS (
            SELECT 1 FROM pg_locks
            WHERE locktype='advisory' AND granted
              AND pid=pg_backend_pid() AND objsubid=2
              AND classid::bigint=(
                sec_acceptance_completion_lock_namespace()::bigint & 4294967295)
              AND objid::bigint=(
                sec_acceptance_completion_lock_local(
                  scoped_run_id,scoped_case_id,scoped_acceptance_pass
                )::bigint & 4294967295)
          )
        $$;

        CREATE TABLE sec_acceptance_case_completion_claims (
          id bigserial PRIMARY KEY,
          run_id varchar(96) NOT NULL,
          case_id varchar(96) NOT NULL,
          acceptance_pass smallint NOT NULL CHECK (acceptance_pass IN (1,2)),
          attempt_id bigint NOT NULL
            REFERENCES sec_acceptance_case_attempts(id),
          generation integer NOT NULL CHECK (generation > 0),
          previous_claim_id bigint NULL
            REFERENCES sec_acceptance_case_completion_claims(id),
          owner_backend_pid integer NULL,
          owner_backend_start timestamptz NULL,
          owner_session_token_hash char(32) NULL,
          claimed_at timestamptz NOT NULL,
          created_at timestamptz NOT NULL,
          created_txid bigint NOT NULL,
          UNIQUE (run_id,case_id,acceptance_pass,generation)
        );

        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM sec_acceptance_evidence_checkpoints before_checkpoint
            LEFT JOIN sec_acceptance_evidence_checkpoints after_checkpoint
              ON after_checkpoint.run_id=before_checkpoint.run_id
             AND after_checkpoint.case_id=before_checkpoint.case_id
             AND after_checkpoint.acceptance_pass=before_checkpoint.acceptance_pass
             AND after_checkpoint.phase='after'
            WHERE before_checkpoint.phase='before'
              AND (
                before_checkpoint.operation_id IS NOT NULL OR
                (after_checkpoint.id IS NOT NULL AND
                 (after_checkpoint.attempt_id<>before_checkpoint.attempt_id OR
                  after_checkpoint.operation_id IS NULL)) OR
                EXISTS (
                  SELECT 1 FROM sec_acceptance_operation_links link
                  JOIN sec_acceptance_case_attempts attempt ON attempt.id=link.attempt_id
                  WHERE attempt.run_id=before_checkpoint.run_id
                    AND attempt.case_id=before_checkpoint.case_id
                    AND attempt.acceptance_pass=before_checkpoint.acceptance_pass
                    AND attempt.id<>before_checkpoint.attempt_id
                ) OR
                EXISTS (
                  SELECT 1 FROM sec_acceptance_publication_bindings binding
                  JOIN sec_acceptance_case_attempts attempt ON attempt.id=binding.attempt_id
                  WHERE attempt.run_id=before_checkpoint.run_id
                    AND attempt.case_id=before_checkpoint.case_id
                    AND attempt.acceptance_pass=before_checkpoint.acceptance_pass
                    AND attempt.id<>before_checkpoint.attempt_id
                ) OR
                EXISTS (
                  SELECT 1 FROM sec_acceptance_report_readiness ready
                  WHERE ready.run_id=before_checkpoint.run_id
                    AND ready.case_id=before_checkpoint.case_id
                    AND ready.acceptance_pass=before_checkpoint.acceptance_pass
                    AND ready.attempt_id<>before_checkpoint.attempt_id
                )
              )
          ) OR EXISTS (
            SELECT 1 FROM sec_acceptance_evidence_checkpoints checkpoint
            WHERE checkpoint.phase='after' AND NOT EXISTS (
              SELECT 1 FROM sec_acceptance_evidence_checkpoints before_checkpoint
              WHERE before_checkpoint.run_id=checkpoint.run_id
                AND before_checkpoint.case_id=checkpoint.case_id
                AND before_checkpoint.acceptance_pass=checkpoint.acceptance_pass
                AND before_checkpoint.phase='before'
            )
          ) OR EXISTS (
            SELECT 1 FROM sec_acceptance_operation_links link
            JOIN sec_acceptance_case_attempts attempt ON attempt.id=link.attempt_id
            WHERE NOT EXISTS (
              SELECT 1 FROM sec_acceptance_evidence_checkpoints before_checkpoint
              WHERE before_checkpoint.run_id=attempt.run_id
                AND before_checkpoint.case_id=attempt.case_id
                AND before_checkpoint.acceptance_pass=attempt.acceptance_pass
                AND before_checkpoint.phase='before'
            )
          ) OR EXISTS (
            SELECT 1 FROM sec_acceptance_publication_bindings binding
            JOIN sec_acceptance_case_attempts attempt ON attempt.id=binding.attempt_id
            WHERE NOT EXISTS (
              SELECT 1 FROM sec_acceptance_evidence_checkpoints before_checkpoint
              WHERE before_checkpoint.run_id=attempt.run_id
                AND before_checkpoint.case_id=attempt.case_id
                AND before_checkpoint.acceptance_pass=attempt.acceptance_pass
                AND before_checkpoint.phase='before'
            )
          ) OR EXISTS (
            SELECT 1 FROM sec_acceptance_report_readiness ready
            WHERE NOT EXISTS (
              SELECT 1 FROM sec_acceptance_evidence_checkpoints before_checkpoint
              WHERE before_checkpoint.run_id=ready.run_id
                AND before_checkpoint.case_id=ready.case_id
                AND before_checkpoint.acceptance_pass=ready.acceptance_pass
                AND before_checkpoint.phase='before'
            )
          ) THEN
            RAISE EXCEPTION 'legacy acceptance authority crosses completion attempts';
          END IF;
        END $$;

        INSERT INTO sec_acceptance_case_completion_claims
          (run_id,case_id,acceptance_pass,attempt_id,generation,
           previous_claim_id,claimed_at,created_at,created_txid)
        SELECT checkpoint.run_id,checkpoint.case_id,checkpoint.acceptance_pass,
               checkpoint.attempt_id,1,NULL,clock_timestamp(),clock_timestamp(),
               txid_current()
        FROM sec_acceptance_evidence_checkpoints checkpoint
        WHERE checkpoint.phase='before';

        CREATE FUNCTION guard_sec_acceptance_completion_claim_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE attempt_row sec_acceptance_case_attempts%ROWTYPE;
        DECLARE prior_row sec_acceptance_case_completion_claims%ROWTYPE;
        DECLARE backend_started_at timestamptz;
        DECLARE session_token text;
        BEGIN
          IF NOT sec_acceptance_completion_session_lock_held(
            NEW.run_id,NEW.case_id,NEW.acceptance_pass) THEN
            RAISE EXCEPTION 'completion claim requires active session lease';
          END IF;
          PERFORM pg_advisory_xact_lock(
            sec_acceptance_completion_lock_namespace(),
            sec_acceptance_completion_lock_local(
              NEW.run_id,NEW.case_id,NEW.acceptance_pass));
          SELECT * INTO STRICT attempt_row
            FROM sec_acceptance_case_attempts WHERE id=NEW.attempt_id;
          IF attempt_row.run_id<>NEW.run_id OR attempt_row.case_id<>NEW.case_id OR
             attempt_row.acceptance_pass<>NEW.acceptance_pass THEN
            RAISE EXCEPTION 'completion claim attempt scope mismatch';
          END IF;
          SELECT * INTO prior_row
            FROM sec_acceptance_case_completion_claims
            WHERE run_id=NEW.run_id AND case_id=NEW.case_id
              AND acceptance_pass=NEW.acceptance_pass
            ORDER BY generation DESC LIMIT 1;
          IF prior_row.id IS NOT NULL AND NEW.attempt_id<>prior_row.attempt_id AND (
            EXISTS (
              SELECT 1 FROM sec_acceptance_evidence_checkpoints checkpoint
              WHERE checkpoint.run_id=NEW.run_id AND checkpoint.case_id=NEW.case_id
                AND checkpoint.acceptance_pass=NEW.acceptance_pass
            ) OR EXISTS (
              SELECT 1 FROM sec_acceptance_publication_bindings binding
              JOIN sec_acceptance_case_attempts attempt
                ON attempt.id=binding.attempt_id
              WHERE attempt.run_id=NEW.run_id AND attempt.case_id=NEW.case_id
                AND attempt.acceptance_pass=NEW.acceptance_pass
            )
          ) THEN
            RAISE EXCEPTION 'completion takeover must retain durable attempt authority';
          END IF;
          IF EXISTS (
            SELECT 1 FROM sec_acceptance_report_readiness ready
            WHERE ready.run_id=NEW.run_id AND ready.case_id=NEW.case_id
              AND ready.acceptance_pass=NEW.acceptance_pass
          ) THEN
            RAISE EXCEPTION 'completion claim cannot follow report readiness';
          END IF;
          IF NEW.owner_backend_pid IS NOT NULL OR
             NEW.owner_backend_start IS NOT NULL OR
             NEW.owner_session_token_hash IS NOT NULL THEN
            RAISE EXCEPTION 'completion owner identity is database stamped';
          END IF;
          IF NOT sec_acceptance_completion_session_lock_held(
            NEW.run_id,NEW.case_id,NEW.acceptance_pass) THEN
            RAISE EXCEPTION 'completion claim lost active session lease';
          END IF;
          SELECT backend_start INTO STRICT backend_started_at
            FROM pg_stat_activity WHERE pid=pg_backend_pid();
          session_token:=gen_random_uuid()::text;
          PERFORM set_config(
            'valuepilot.sec_acceptance_completion_owner_token',session_token,false);
          NEW.generation:=COALESCE(prior_row.generation,0)+1;
          NEW.previous_claim_id:=prior_row.id;
          NEW.owner_backend_pid:=pg_backend_pid();
          NEW.owner_backend_start:=backend_started_at;
          NEW.owner_session_token_hash:=md5(session_token);
          NEW.claimed_at:=clock_timestamp();
          NEW.created_at:=NEW.claimed_at;
          NEW.created_txid:=txid_current();
          RETURN NEW;
        END $$;
        CREATE TRIGGER sec_acceptance_completion_claim_insert_guard
          BEFORE INSERT ON sec_acceptance_case_completion_claims
          FOR EACH ROW EXECUTE FUNCTION guard_sec_acceptance_completion_claim_insert();

        CREATE FUNCTION guard_sec_acceptance_current_completion_owner()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE attempt_row sec_acceptance_case_attempts%ROWTYPE;
        DECLARE owner_row sec_acceptance_case_completion_claims%ROWTYPE;
        DECLARE backend_started_at timestamptz;
        DECLARE session_token text;
        BEGIN
          SELECT * INTO STRICT attempt_row
            FROM sec_acceptance_case_attempts WHERE id=NEW.attempt_id;
          PERFORM pg_advisory_xact_lock(
            sec_acceptance_completion_lock_namespace(),
            sec_acceptance_completion_lock_local(
              attempt_row.run_id,attempt_row.case_id,
              attempt_row.acceptance_pass));
          SELECT * INTO owner_row
            FROM sec_acceptance_case_completion_claims
            WHERE run_id=attempt_row.run_id AND case_id=attempt_row.case_id
              AND acceptance_pass=attempt_row.acceptance_pass
            ORDER BY generation DESC LIMIT 1;
          SELECT backend_start INTO STRICT backend_started_at
            FROM pg_stat_activity WHERE pid=pg_backend_pid();
          session_token:=current_setting(
            'valuepilot.sec_acceptance_completion_owner_token',true);
          IF owner_row.attempt_id IS NULL OR
             owner_row.attempt_id<>NEW.attempt_id OR
             owner_row.owner_backend_pid IS NULL OR
             owner_row.owner_backend_pid<>pg_backend_pid() OR
             owner_row.owner_backend_start IS DISTINCT FROM backend_started_at OR
             owner_row.owner_session_token_hash IS NULL OR
             session_token IS NULL OR session_token='' OR
             owner_row.owner_session_token_hash<>md5(session_token) OR
             NOT sec_acceptance_completion_session_lock_held(
               attempt_row.run_id,attempt_row.case_id,
               attempt_row.acceptance_pass) THEN
            RAISE EXCEPTION 'acceptance write requires active completion owner';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER sec_acceptance_operation_link_completion_owner_guard
          BEFORE INSERT ON sec_acceptance_operation_links
          FOR EACH ROW EXECUTE FUNCTION guard_sec_acceptance_current_completion_owner();
        CREATE TRIGGER sec_acceptance_publication_binding_completion_owner_guard
          BEFORE INSERT ON sec_acceptance_publication_bindings
          FOR EACH ROW EXECUTE FUNCTION guard_sec_acceptance_current_completion_owner();
        CREATE TRIGGER sec_acceptance_report_readiness_completion_owner_guard
          BEFORE INSERT ON sec_acceptance_report_readiness
          FOR EACH ROW EXECUTE FUNCTION guard_sec_acceptance_current_completion_owner();
        CREATE TRIGGER sec_acceptance_evidence_checkpoint_completion_owner_guard
          BEFORE INSERT ON sec_acceptance_evidence_checkpoints
          FOR EACH ROW EXECUTE FUNCTION guard_sec_acceptance_current_completion_owner();

        CREATE TRIGGER sec_acceptance_completion_claims_append_only
          BEFORE UPDATE OR DELETE OR TRUNCATE
          ON sec_acceptance_case_completion_claims
          FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_acceptance_authority_mutation();
        """
    )
    op.execute(
        _runtime_counts_function(
            ",'acceptance_completion_claims',"
            "(SELECT count(*) FROM sec_acceptance_case_completion_claims)"
        )
    )


def downgrade() -> None:
    op.execute(_runtime_counts_function(""))
    op.execute(
        """
        DROP TRIGGER sec_acceptance_completion_claims_append_only
          ON sec_acceptance_case_completion_claims;
        DROP TRIGGER sec_acceptance_evidence_checkpoint_completion_owner_guard
          ON sec_acceptance_evidence_checkpoints;
        DROP TRIGGER sec_acceptance_report_readiness_completion_owner_guard
          ON sec_acceptance_report_readiness;
        DROP TRIGGER sec_acceptance_publication_binding_completion_owner_guard
          ON sec_acceptance_publication_bindings;
        DROP TRIGGER sec_acceptance_operation_link_completion_owner_guard
          ON sec_acceptance_operation_links;
        DROP FUNCTION guard_sec_acceptance_current_completion_owner();
        DROP TRIGGER sec_acceptance_completion_claim_insert_guard
          ON sec_acceptance_case_completion_claims;
        DROP FUNCTION guard_sec_acceptance_completion_claim_insert();
        DROP TABLE sec_acceptance_case_completion_claims;
        DROP FUNCTION sec_acceptance_completion_session_lock_held(text,text,smallint);
        DROP FUNCTION sec_acceptance_completion_lock_local(text,text,smallint);
        DROP FUNCTION sec_acceptance_completion_lock_namespace();
        """
    )
