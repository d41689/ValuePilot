"""Persist append-only SEC acceptance checkpoints and Rate Guard authority.

Revision ID: 20260901180000
Revises: 20260901170000
"""

from alembic import op


revision = "20260901180000"
down_revision = "20260901170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION sec_acceptance_evidence_counts()
        RETURNS jsonb LANGUAGE sql STABLE AS $$ SELECT jsonb_build_object(
          'issuer_identities',(SELECT count(*) FROM sec_issuer_identities),
          'filings',(SELECT count(*) FROM sec_financial_filings),
          'submission_snapshots',(SELECT count(*) FROM sec_submission_snapshots),
          'artifacts',(SELECT count(*) FROM sec_filing_artifacts),
          'parse_runs',(SELECT count(*) FROM sec_financial_parse_runs),
          'parse_run_artifacts',(SELECT count(*) FROM sec_financial_parse_run_artifacts),
          'raw_facts',(SELECT count(*) FROM sec_raw_xbrl_facts),
          'statement_report_references',(SELECT count(*) FROM sec_statement_report_references),
          'statement_occurrences',(SELECT count(*) FROM sec_statement_occurrence_evidence),
          'statement_authorities',(SELECT count(*) FROM sec_statement_fact_authorities),
          'numeric_normalizations',(SELECT count(*) FROM sec_raw_numeric_normalizations),
          'publication_runs',(SELECT count(*) FROM sec_metric_publication_runs),
          'publication_run_sources',(SELECT count(*) FROM sec_metric_publication_run_sources),
          'publication_decisions',(SELECT count(*) FROM sec_metric_publications),
          'publication_inputs',(SELECT count(*) FROM sec_metric_publication_inputs),
          'publication_unresolved_inputs',(SELECT count(*) FROM sec_metric_publication_unresolved_inputs),
          'publication_audits',(SELECT count(*) FROM sec_metric_publication_audits),
          'publication_availabilities',(SELECT count(*) FROM sec_metric_publication_availabilities),
          'metric_facts',(SELECT count(*) FROM metric_facts WHERE source_type='sec')
        ) $$;

        CREATE TABLE sec_acceptance_evidence_checkpoints (
          id bigserial PRIMARY KEY,
          run_id varchar(32) NOT NULL CHECK (run_id ~ '^[a-z0-9][a-z0-9-]{1,31}$'),
          case_id varchar(80) NOT NULL CHECK (case_id ~ '^[a-z0-9][a-z0-9-]+$'),
          acceptance_pass smallint NOT NULL CHECK (acceptance_pass IN (1,2)),
          phase varchar(8) NOT NULL CHECK (phase IN ('before','after')),
          attempt_id bigint NOT NULL,
          operation_id varchar(36) NULL REFERENCES sec_financial_ingestion_operations(id),
          evidence_counts jsonb NOT NULL,
          captured_at timestamptz NOT NULL,
          created_at timestamptz NOT NULL,
          created_txid bigint NOT NULL,
          UNIQUE(run_id,case_id,acceptance_pass,phase)
        );

        CREATE FUNCTION guard_sec_acceptance_evidence_checkpoint_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM sec_acceptance_case_attempts attempt
            WHERE attempt.id=NEW.attempt_id
              AND attempt.run_id=NEW.run_id
              AND attempt.case_id=NEW.case_id
              AND attempt.acceptance_pass=NEW.acceptance_pass
          ) THEN
            RAISE EXCEPTION 'evidence checkpoint attempt identity mismatch';
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM sec_acceptance_rate_guard_snapshots
            WHERE run_id=NEW.run_id AND phase='before'
          ) OR EXISTS (
            SELECT 1 FROM sec_acceptance_rate_guard_snapshots
            WHERE run_id=NEW.run_id AND phase='after'
          ) THEN
            RAISE EXCEPTION 'evidence checkpoint is outside durable runtime window';
          END IF;
          NEW.evidence_counts:=sec_acceptance_evidence_counts();
          NEW.captured_at:=clock_timestamp();
          NEW.created_at:=NEW.captured_at;
          NEW.created_txid:=txid_current();
          IF NEW.phase='before' AND NEW.operation_id IS NOT NULL THEN
            RAISE EXCEPTION 'before checkpoint cannot claim an operation';
          END IF;
          IF NEW.phase='after' AND NEW.operation_id IS NULL THEN
            RAISE EXCEPTION 'after checkpoint requires operation identity';
          END IF;
          IF NEW.phase='after' AND NOT EXISTS (
            SELECT 1 FROM sec_acceptance_operation_links
            WHERE attempt_id=NEW.attempt_id AND operation_id=NEW.operation_id
          ) THEN
            RAISE EXCEPTION 'after checkpoint operation is not linked to attempt';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER sec_acceptance_evidence_checkpoint_insert_guard
          BEFORE INSERT ON sec_acceptance_evidence_checkpoints
          FOR EACH ROW EXECUTE FUNCTION guard_sec_acceptance_evidence_checkpoint_insert();

        CREATE TABLE sec_acceptance_rate_guard_snapshots (
          id bigserial PRIMARY KEY,
          run_id varchar(32) NOT NULL CHECK (run_id ~ '^[a-z0-9][a-z0-9-]{1,31}$'),
          phase varchar(8) NOT NULL CHECK (phase IN ('before','after')),
          configured_route text NOT NULL CHECK (
            configured_route ~ '^https?://[^[:space:]]+$'
          ),
          expected_instance_id varchar(36) NOT NULL CHECK (
            expected_instance_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
          ),
          observed_instance_id varchar(36) NOT NULL CHECK (
            observed_instance_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
          ),
          fetch_mode varchar(16) NOT NULL CHECK (fetch_mode='rate_guard'),
          fallback_enabled boolean NOT NULL CHECK (NOT fallback_enabled),
          fallback_url text NULL CHECK (fallback_url IS NULL),
          rate_per_sec numeric(8,4) NOT NULL CHECK (rate_per_sec>0 AND rate_per_sec<=1),
          total_request_count bigint NOT NULL CHECK (total_request_count>=0),
          total_403_count bigint NOT NULL CHECK (total_403_count>=0),
          total_429_count bigint NOT NULL CHECK (total_429_count>=0),
          total_503_count bigint NOT NULL CHECK (total_503_count>=0),
          cache_hits bigint NOT NULL CHECK (cache_hits>=0),
          cache_misses bigint NOT NULL CHECK (cache_misses>=0),
          config_digest char(64) NOT NULL CHECK (config_digest ~ '^[0-9a-f]{64}$'),
          manifest_digest char(64) NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
          database_name varchar(80) NOT NULL CHECK (
            database_name ~ '^valuepilot_acceptance_[a-z0-9_]{2,32}$'
          ),
          runtime_counts jsonb NOT NULL,
          retained_file_count bigint NOT NULL CHECK (retained_file_count>=0),
          retained_bytes bigint NOT NULL CHECK (retained_bytes>=0),
          retained_manifest_digest char(64) NOT NULL CHECK (
            retained_manifest_digest ~ '^[0-9a-f]{64}$'
          ),
          captured_at timestamptz NOT NULL,
          created_at timestamptz NOT NULL,
          created_txid bigint NOT NULL,
          CHECK (expected_instance_id=observed_instance_id),
          UNIQUE(run_id,phase)
        );

        CREATE TABLE sec_acceptance_case_attempts (
          id bigserial PRIMARY KEY,
          run_id varchar(32) NOT NULL CHECK (run_id ~ '^[a-z0-9][a-z0-9-]{1,31}$'),
          case_id varchar(80) NOT NULL CHECK (case_id ~ '^[a-z0-9][a-z0-9-]+$'),
          acceptance_pass smallint NOT NULL CHECK (acceptance_pass IN (1,2)),
          attempt_ordinal integer NOT NULL CHECK (attempt_ordinal>0),
          attempted_at timestamptz NOT NULL,
          created_at timestamptz NOT NULL,
          created_txid bigint NOT NULL,
          UNIQUE(run_id,case_id,acceptance_pass,attempt_ordinal)
        );

        ALTER TABLE sec_acceptance_evidence_checkpoints
          ADD CONSTRAINT fk_sec_acceptance_evidence_checkpoint_attempt
          FOREIGN KEY (attempt_id) REFERENCES sec_acceptance_case_attempts(id)
          ON DELETE RESTRICT;

        CREATE TABLE sec_acceptance_operation_links (
          id bigserial PRIMARY KEY,
          attempt_id bigint NOT NULL REFERENCES sec_acceptance_case_attempts(id)
            ON DELETE RESTRICT,
          operation_id varchar(36) NOT NULL REFERENCES sec_financial_ingestion_operations(id)
            ON DELETE RESTRICT,
          operation_ordinal integer NOT NULL CHECK (operation_ordinal>0),
          operation_role varchar(16) NOT NULL CHECK (
            operation_role IN ('main','continuation','recovered','failed')
          ),
          linked_at timestamptz NOT NULL,
          created_at timestamptz NOT NULL,
          created_txid bigint NOT NULL,
          UNIQUE(attempt_id,operation_id),
          UNIQUE(attempt_id,operation_ordinal)
        );
        CREATE UNIQUE INDEX uq_sec_acceptance_operation_creation_owner
          ON sec_acceptance_operation_links(operation_id)
          WHERE operation_role<>'recovered';

        CREATE TABLE sec_acceptance_report_readiness (
          id bigserial PRIMARY KEY,
          run_id varchar(32) NOT NULL CHECK (run_id ~ '^[a-z0-9][a-z0-9-]{1,31}$'),
          case_id varchar(80) NOT NULL CHECK (case_id ~ '^[a-z0-9][a-z0-9-]+$'),
          acceptance_pass smallint NOT NULL CHECK (acceptance_pass IN (1,2)),
          attempt_id bigint NOT NULL REFERENCES sec_acceptance_case_attempts(id)
            ON DELETE RESTRICT,
          operation_id varchar(36) NOT NULL REFERENCES sec_financial_ingestion_operations(id)
            ON DELETE RESTRICT,
          report_sha256 char(64) NOT NULL CHECK (report_sha256 ~ '^[0-9a-f]{64}$'),
          report_ready_at timestamptz NOT NULL,
          created_at timestamptz NOT NULL,
          created_txid bigint NOT NULL,
          UNIQUE(run_id,case_id,acceptance_pass)
        );

        CREATE TABLE sec_acceptance_publication_bindings (
          id bigserial PRIMARY KEY,
          attempt_id bigint NOT NULL UNIQUE REFERENCES sec_acceptance_case_attempts(id)
            ON DELETE RESTRICT,
          requested_cutoff timestamptz NOT NULL,
          source_set_sha256 char(64) NOT NULL CHECK (source_set_sha256 ~ '^[0-9a-f]{64}$'),
          ordered_source_identities jsonb NOT NULL,
          mapping_version_id varchar(80) NOT NULL REFERENCES sec_metric_mapping_versions(id),
          amendment_policy varchar(80) NOT NULL,
          expected_publication_run_id varchar(36) NULL REFERENCES sec_metric_publication_runs(id),
          publication_run_id varchar(36) NOT NULL REFERENCES sec_metric_publication_runs(id),
          bound_at timestamptz NOT NULL,
          created_at timestamptz NOT NULL,
          created_txid bigint NOT NULL
        );

        CREATE FUNCTION sec_acceptance_runtime_counts()
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
            'acceptance_report_readiness',(SELECT count(*) FROM sec_acceptance_report_readiness)
            ,'acceptance_publication_bindings',(SELECT count(*) FROM sec_acceptance_publication_bindings)
          )
        $$;

        CREATE FUNCTION guard_sec_acceptance_case_attempt_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM sec_acceptance_rate_guard_snapshots
            WHERE run_id=NEW.run_id AND phase='before'
          ) THEN
            RAISE EXCEPTION 'durable runtime before checkpoint is required before case attempt';
          END IF;
          IF EXISTS (
            SELECT 1 FROM sec_acceptance_rate_guard_snapshots
            WHERE run_id=NEW.run_id AND phase='after'
          ) THEN
            RAISE EXCEPTION 'case attempt cannot follow durable runtime after checkpoint';
          END IF;
          IF EXISTS (
            SELECT 1 FROM sec_acceptance_evidence_checkpoints
            WHERE run_id=NEW.run_id AND case_id=NEW.case_id
              AND acceptance_pass=NEW.acceptance_pass AND phase='after'
          ) THEN
            RAISE EXCEPTION 'case attempt cannot follow durable case after checkpoint';
          END IF;
          NEW.attempt_ordinal:=1+(
            SELECT count(*) FROM sec_acceptance_case_attempts
            WHERE run_id=NEW.run_id AND case_id=NEW.case_id
              AND acceptance_pass=NEW.acceptance_pass
          );
          NEW.attempted_at:=clock_timestamp();
          NEW.created_at:=NEW.attempted_at;
          NEW.created_txid:=txid_current();
          RETURN NEW;
        END $$;
        CREATE TRIGGER sec_acceptance_case_attempt_insert_guard
          BEFORE INSERT ON sec_acceptance_case_attempts
          FOR EACH ROW EXECUTE FUNCTION guard_sec_acceptance_case_attempt_insert();

        CREATE FUNCTION guard_sec_acceptance_operation_link_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE attempt_row sec_acceptance_case_attempts%ROWTYPE;
        DECLARE operation_txid bigint;
        DECLARE operation_created_at timestamptz;
        BEGIN
          SELECT * INTO STRICT attempt_row FROM sec_acceptance_case_attempts
            WHERE id=NEW.attempt_id;
          IF EXISTS (
            SELECT 1 FROM sec_acceptance_rate_guard_snapshots
            WHERE run_id=attempt_row.run_id AND phase='after'
          ) THEN
            RAISE EXCEPTION 'operation link cannot follow durable runtime after checkpoint';
          END IF;
          SELECT created_txid,created_at
            INTO STRICT operation_txid,operation_created_at
            FROM sec_financial_ingestion_operations WHERE id=NEW.operation_id;
          IF NEW.operation_role<>'recovered' AND
             operation_created_at<attempt_row.attempted_at THEN
            RAISE EXCEPTION 'operation predates acceptance attempt authority';
          END IF;
          IF NEW.operation_role='recovered' THEN
            IF NOT EXISTS (
              SELECT 1 FROM sec_acceptance_operation_links prior
              JOIN sec_acceptance_case_attempts owner ON owner.id=prior.attempt_id
              JOIN sec_financial_lineage_availabilities available
                ON available.operation_id=prior.operation_id
              WHERE prior.operation_id=NEW.operation_id
                AND prior.operation_role<>'recovered'
                AND owner.run_id=attempt_row.run_id
                AND owner.case_id=attempt_row.case_id
                AND owner.acceptance_pass=attempt_row.acceptance_pass
            ) THEN
              RAISE EXCEPTION 'recovered operation lacks same-case creation authority';
            END IF;
          ELSIF operation_txid<>txid_current() THEN
            RAISE EXCEPTION 'new acceptance operation link must share creation transaction';
          END IF;
          NEW.linked_at:=clock_timestamp();
          NEW.created_at:=NEW.linked_at;
          NEW.created_txid:=txid_current();
          RETURN NEW;
        END $$;
        CREATE TRIGGER sec_acceptance_operation_link_insert_guard
          BEFORE INSERT ON sec_acceptance_operation_links
          FOR EACH ROW EXECUTE FUNCTION guard_sec_acceptance_operation_link_insert();

        CREATE FUNCTION guard_sec_acceptance_report_readiness_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM sec_acceptance_rate_guard_snapshots
            WHERE run_id=NEW.run_id AND phase='after'
          ) THEN
            RAISE EXCEPTION 'report readiness cannot follow durable runtime after checkpoint';
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM sec_acceptance_case_attempts attempt
            JOIN sec_acceptance_operation_links link ON link.attempt_id=attempt.id
            JOIN sec_acceptance_evidence_checkpoints checkpoint
              ON checkpoint.run_id=attempt.run_id
             AND checkpoint.case_id=attempt.case_id
             AND checkpoint.acceptance_pass=attempt.acceptance_pass
             AND checkpoint.phase='after'
             AND checkpoint.operation_id=link.operation_id
            WHERE attempt.id=NEW.attempt_id
              AND attempt.run_id=NEW.run_id
              AND attempt.case_id=NEW.case_id
              AND attempt.acceptance_pass=NEW.acceptance_pass
              AND link.operation_id=NEW.operation_id
          ) THEN
            RAISE EXCEPTION 'report readiness lacks audited attempt/checkpoint authority';
          END IF;
          NEW.report_ready_at:=clock_timestamp();
          NEW.created_at:=NEW.report_ready_at;
          NEW.created_txid:=txid_current();
          RETURN NEW;
        END $$;
        CREATE TRIGGER sec_acceptance_report_readiness_insert_guard
          BEFORE INSERT ON sec_acceptance_report_readiness
          FOR EACH ROW EXECUTE FUNCTION guard_sec_acceptance_report_readiness_insert();

        CREATE FUNCTION guard_sec_acceptance_publication_binding_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE run_row sec_metric_publication_runs%ROWTYPE;
        DECLARE attempt_row sec_acceptance_case_attempts%ROWTYPE;
        DECLARE pass_one_row sec_acceptance_publication_bindings%ROWTYPE;
        DECLARE source_rows jsonb;
        BEGIN
          SELECT * INTO STRICT attempt_row FROM sec_acceptance_case_attempts
            WHERE id=NEW.attempt_id;
          SELECT * INTO STRICT run_row FROM sec_metric_publication_runs
            WHERE id=NEW.publication_run_id;
          SELECT coalesce(jsonb_agg(jsonb_build_object(
                   'parse_run_id',parse_run_id,'filing_id',filing_id,
                   'accession_no',accession_no,'parser_version',parser_version,
                   'input_manifest_hash',input_manifest_hash,
                   'available_at',source_available_at) ORDER BY source_ordinal),'[]'::jsonb)
            INTO source_rows FROM sec_metric_publication_run_sources
            WHERE publication_run_id=NEW.publication_run_id;
          IF run_row.requested_cutoff<>NEW.requested_cutoff OR
             run_row.source_set_sha256<>NEW.source_set_sha256 OR
             run_row.mapping_version_id<>NEW.mapping_version_id OR
             run_row.amendment_policy<>NEW.amendment_policy OR
             source_rows<>NEW.ordered_source_identities OR
             (NEW.expected_publication_run_id IS NOT NULL AND
              NEW.expected_publication_run_id<>NEW.publication_run_id) THEN
            RAISE EXCEPTION 'acceptance publication binding differs from run authority';
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM sec_acceptance_operation_links link
            JOIN sec_financial_ingestion_operations operation
              ON operation.id=link.operation_id
            JOIN sec_issuer_identities issuer
              ON issuer.id=operation.issuer_identity_id
            WHERE link.attempt_id=NEW.attempt_id
              AND issuer.id=run_row.issuer_identity_id
              AND issuer.stock_id=run_row.stock_id
          ) OR EXISTS (
            SELECT 1 FROM sec_acceptance_operation_links link
            JOIN sec_financial_ingestion_operations operation
              ON operation.id=link.operation_id
            JOIN sec_issuer_identities issuer
              ON issuer.id=operation.issuer_identity_id
            WHERE link.attempt_id=NEW.attempt_id
              AND (issuer.id<>run_row.issuer_identity_id OR
                   issuer.stock_id<>run_row.stock_id)
          ) THEN
            RAISE EXCEPTION 'acceptance publication binding differs from attempt issuer authority';
          END IF;
          IF attempt_row.acceptance_pass=1 AND
             NEW.expected_publication_run_id IS NOT NULL THEN
            RAISE EXCEPTION 'pass-one publication binding cannot claim replay authority';
          ELSIF attempt_row.acceptance_pass=2 THEN
            SELECT binding.* INTO STRICT pass_one_row
            FROM sec_acceptance_publication_bindings binding
            JOIN sec_acceptance_case_attempts prior ON prior.id=binding.attempt_id
            WHERE prior.run_id=attempt_row.run_id
              AND prior.case_id=attempt_row.case_id
              AND prior.acceptance_pass=1;
            IF NEW.expected_publication_run_id IS NULL OR
               NEW.expected_publication_run_id<>pass_one_row.publication_run_id OR
               NEW.publication_run_id<>pass_one_row.publication_run_id OR
               NEW.requested_cutoff<>pass_one_row.requested_cutoff OR
               NEW.source_set_sha256<>pass_one_row.source_set_sha256 OR
               NEW.ordered_source_identities<>pass_one_row.ordered_source_identities OR
               NEW.mapping_version_id<>pass_one_row.mapping_version_id OR
               NEW.amendment_policy<>pass_one_row.amendment_policy THEN
              RAISE EXCEPTION 'pass-two publication binding is not exact pass-one replay';
            END IF;
          END IF;
          NEW.bound_at:=clock_timestamp();
          NEW.created_at:=NEW.bound_at;
          NEW.created_txid:=txid_current();
          RETURN NEW;
        END $$;
        CREATE TRIGGER sec_acceptance_publication_binding_insert_guard
          BEFORE INSERT ON sec_acceptance_publication_bindings
          FOR EACH ROW EXECUTE FUNCTION guard_sec_acceptance_publication_binding_insert();

        CREATE FUNCTION guard_sec_acceptance_rate_guard_snapshot_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE counts jsonb;
        BEGIN
          NEW.configured_route:=rtrim(btrim(NEW.configured_route),'/');
          counts:=sec_acceptance_runtime_counts();
          NEW.runtime_counts:=counts;
          NEW.captured_at:=clock_timestamp();
          NEW.created_at:=NEW.captured_at;
          NEW.created_txid:=txid_current();
          IF EXISTS (
            SELECT 1 FROM sec_acceptance_rate_guard_snapshots
            WHERE run_id=NEW.run_id AND phase=NEW.phase
          ) THEN
            RETURN NEW;
          END IF;
          IF NEW.phase='before' THEN
            IF EXISTS (SELECT 1 FROM sec_acceptance_rate_guard_snapshots) OR
               (counts->>'users')::bigint<>0 OR
               (counts->>'stocks')::bigint<>0 OR
               (counts->>'pdf_documents')::bigint<>0 OR
               (counts->>'metric_extractions')::bigint<>0 OR
               (counts->>'metric_facts_total')::bigint<>0 OR
               (counts->>'issuer_identities')::bigint<>0 OR
               (counts->>'ingestion_operations')::bigint<>0 OR
               (counts->>'publication_runs')::bigint<>0 OR
               (counts->>'legacy_parse_runs')::bigint<>0 OR
               (counts->>'economic_classification_reviews')::bigint<>0 OR
               (counts->>'economic_risk_attribute_reviews')::bigint<>0 OR
               (counts->>'acceptance_case_attempts')::bigint<>0 OR
               (counts->>'acceptance_operation_links')::bigint<>0 OR
               (counts->>'acceptance_evidence_checkpoints')::bigint<>0 OR
               (counts->>'acceptance_report_readiness')::bigint<>0 THEN
              RAISE EXCEPTION 'durable runtime before checkpoint requires clean acceptance baseline';
            END IF;
          ELSE
            IF NOT EXISTS (
              SELECT 1 FROM sec_acceptance_rate_guard_snapshots prior
              WHERE prior.run_id=NEW.run_id AND prior.phase='before'
                AND prior.database_name=NEW.database_name
                AND prior.manifest_digest=NEW.manifest_digest
                AND prior.config_digest=NEW.config_digest
                AND prior.expected_instance_id=NEW.expected_instance_id
            ) THEN
              RAISE EXCEPTION 'durable runtime after checkpoint lacks matching before authority';
            END IF;
            IF (SELECT count(*) FROM sec_acceptance_report_readiness
                WHERE run_id=NEW.run_id)<>48 OR
               (SELECT count(*) FROM sec_acceptance_evidence_checkpoints
                WHERE run_id=NEW.run_id AND phase='before')<>48 OR
               (SELECT count(*) FROM sec_acceptance_evidence_checkpoints
                WHERE run_id=NEW.run_id AND phase='after')<>48 OR
               (SELECT count(DISTINCT case_id) FROM sec_acceptance_report_readiness
                WHERE run_id=NEW.run_id AND acceptance_pass=1)<>24 OR
               (SELECT count(DISTINCT case_id) FROM sec_acceptance_report_readiness
                WHERE run_id=NEW.run_id AND acceptance_pass=2)<>24 OR
               (SELECT coalesce(max(report_ready_at),'-infinity'::timestamptz)
                FROM sec_acceptance_report_readiness WHERE run_id=NEW.run_id)>=NEW.captured_at OR
               (SELECT coalesce(max(captured_at),'-infinity'::timestamptz)
                FROM sec_acceptance_evidence_checkpoints WHERE run_id=NEW.run_id)>=NEW.captured_at THEN
              RAISE EXCEPTION 'durable runtime after checkpoint requires 24x2 audited report-ready cases';
            END IF;
            IF (counts->>'metric_facts_manual')::bigint<>0 OR
               (counts->>'metric_facts_other')::bigint<>0 OR
               (counts->>'metric_facts_user_owned')::bigint<>0 OR
               (counts->>'pdf_documents')::bigint<>0 OR
               (counts->>'metric_extractions')::bigint<>0 OR
               (counts->>'legacy_parse_runs')::bigint<>0 OR
               (counts->>'economic_classification_reviews')::bigint<>0 OR
               (counts->>'economic_risk_attribute_reviews')::bigint<>0 THEN
              RAISE EXCEPTION 'durable runtime after checkpoint found disallowed non-SEC data';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER sec_acceptance_rate_guard_snapshot_insert_guard
          BEFORE INSERT ON sec_acceptance_rate_guard_snapshots
          FOR EACH ROW EXECUTE FUNCTION guard_sec_acceptance_rate_guard_snapshot_insert();

        CREATE FUNCTION reject_sec_acceptance_authority_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'SEC acceptance authority is append-only';
        END $$;
        CREATE TRIGGER sec_acceptance_evidence_checkpoint_append_only
          BEFORE UPDATE OR DELETE OR TRUNCATE ON sec_acceptance_evidence_checkpoints
          FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_acceptance_authority_mutation();
        CREATE TRIGGER sec_acceptance_rate_guard_snapshot_append_only
          BEFORE UPDATE OR DELETE OR TRUNCATE ON sec_acceptance_rate_guard_snapshots
          FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_acceptance_authority_mutation();
        CREATE TRIGGER sec_acceptance_case_attempt_append_only
          BEFORE UPDATE OR DELETE OR TRUNCATE ON sec_acceptance_case_attempts
          FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_acceptance_authority_mutation();
        CREATE TRIGGER sec_acceptance_operation_link_append_only
          BEFORE UPDATE OR DELETE OR TRUNCATE ON sec_acceptance_operation_links
          FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_acceptance_authority_mutation();
        CREATE TRIGGER sec_acceptance_report_readiness_append_only
          BEFORE UPDATE OR DELETE OR TRUNCATE ON sec_acceptance_report_readiness
          FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_acceptance_authority_mutation();
        CREATE TRIGGER sec_acceptance_publication_binding_append_only
          BEFORE UPDATE OR DELETE OR TRUNCATE ON sec_acceptance_publication_bindings
          FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_acceptance_authority_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE sec_acceptance_report_readiness;
        DROP TABLE sec_acceptance_publication_bindings;
        DROP TABLE sec_acceptance_operation_links;
        DROP TABLE sec_acceptance_evidence_checkpoints;
        DROP TABLE sec_acceptance_case_attempts;
        DROP TABLE sec_acceptance_rate_guard_snapshots;
        DROP FUNCTION reject_sec_acceptance_authority_mutation();
        DROP FUNCTION guard_sec_acceptance_report_readiness_insert();
        DROP FUNCTION guard_sec_acceptance_publication_binding_insert();
        DROP FUNCTION guard_sec_acceptance_operation_link_insert();
        DROP FUNCTION guard_sec_acceptance_case_attempt_insert();
        DROP FUNCTION guard_sec_acceptance_rate_guard_snapshot_insert();
        DROP FUNCTION guard_sec_acceptance_evidence_checkpoint_insert();
        DROP FUNCTION sec_acceptance_runtime_counts();
        DROP FUNCTION sec_acceptance_evidence_counts();
        """
    )
