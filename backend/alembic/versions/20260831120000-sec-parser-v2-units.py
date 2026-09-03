"""Add structured QName units for append-only SEC parser v2 facts.

Revision ID: 20260831120000
Revises: 20260830140000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260831120000"
down_revision = "20260830140000"
branch_labels = None
depends_on = None

_AVAILABILITY_OLD = """IF NOT EXISTS (
                SELECT 1 FROM sec_financial_operation_snapshots
                WHERE operation_id = NEW.operation_id
            ) AND NOT EXISTS (
                SELECT 1 FROM sec_financial_resource_anchors
                WHERE operation_id = NEW.operation_id
            ) THEN"""
_AVAILABILITY_NEW = """IF NOT EXISTS (
                SELECT 1 FROM sec_financial_operation_snapshots
                WHERE operation_id = NEW.operation_id
            ) AND NOT EXISTS (
                SELECT 1 FROM sec_financial_resource_anchors
                WHERE operation_id = NEW.operation_id
            ) AND NOT EXISTS (
                SELECT 1 FROM sec_financial_history_continuation_failures failure
                JOIN sec_financial_operation_results result
                  ON result.operation_id = failure.operation_id
                 AND result.history_continuation_failure_id = failure.id
                 AND result.result_kind = 'history_continuation_failure'
                WHERE failure.operation_id = NEW.operation_id
            ) THEN"""


def _replace_availability_guard(old: str, new: str) -> None:
    connection = op.get_bind()
    definition = connection.execute(
        sa.text(
            "SELECT pg_get_functiondef('stamp_sec_financial_lineage_availability()'::regprocedure)"
        )
    ).scalar_one()
    if old not in definition:
        raise RuntimeError("SEC availability guard shape changed unexpectedly")
    op.execute(definition.replace(old, new))


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION sec_valid_qname(value jsonb) RETURNS boolean
        LANGUAGE sql IMMUTABLE AS $$ SELECT
          jsonb_typeof(value) = 'object'
          AND (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(value) key)
              = ARRAY['local_name','namespace_uri','prefix']
          AND jsonb_typeof(value->'namespace_uri') = 'string' AND btrim(value->>'namespace_uri') <> ''
          AND jsonb_typeof(value->'local_name') = 'string' AND btrim(value->>'local_name') <> ''
          AND jsonb_typeof(value->'prefix') IN ('string','null')
        $$;
        CREATE FUNCTION sec_valid_typed_node(value jsonb, depth integer DEFAULT 0)
        RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
        DECLARE attr jsonb; child jsonb;
        BEGIN
          IF depth > 32 OR jsonb_typeof(value) <> 'object'
             OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(value) key)
                <> ARRAY['attributes','children','name','tail','text']
             OR NOT sec_valid_qname(value->'name')
             OR jsonb_typeof(value->'attributes') <> 'array'
             OR jsonb_array_length(value->'attributes') > 64
             OR jsonb_typeof(value->'children') <> 'array'
             OR jsonb_array_length(value->'children') > 256
             OR jsonb_typeof(value->'text') <> 'string'
             OR jsonb_typeof(value->'tail') <> 'string' THEN RETURN false; END IF;
          FOR attr IN SELECT jsonb_array_elements(value->'attributes') LOOP
            IF jsonb_typeof(attr) <> 'object'
               OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(attr) key) <> ARRAY['name','value']
               OR jsonb_typeof(attr->'name') <> 'object'
               OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(attr->'name') key) <> ARRAY['local_name','namespace_uri','prefix']
               OR jsonb_typeof(attr->'name'->'local_name') <> 'string' OR btrim(attr->'name'->>'local_name')=''
               OR jsonb_typeof(attr->'name'->'namespace_uri') NOT IN ('string','null')
               OR jsonb_typeof(attr->'name'->'prefix') NOT IN ('string','null')
               OR jsonb_typeof(attr->'value') <> 'string' THEN RETURN false; END IF;
          END LOOP;
          FOR child IN SELECT jsonb_array_elements(value->'children') LOOP
            IF NOT sec_valid_typed_node(child, depth + 1) THEN RETURN false; END IF;
          END LOOP;
          RETURN true;
        END $$;
        """
    )
    op.add_column("sec_raw_xbrl_facts", sa.Column("unit_numerator_json", postgresql.JSONB(), nullable=True))
    op.add_column("sec_raw_xbrl_facts", sa.Column("unit_denominator_json", postgresql.JSONB(), nullable=True))
    op.add_column("sec_raw_xbrl_facts", sa.Column("dimensions_structured_json", postgresql.JSONB(), nullable=True))
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_sec_parser_v2_structured_unit()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            parser_version_value text;
            member jsonb;
            dimension_axes text[] := ARRAY[]::text[];
        BEGIN
            SELECT parser_version INTO parser_version_value
            FROM sec_financial_parse_runs WHERE id = NEW.parse_run_id;
            IF parser_version_value = 'xbrl-lineage-v2' THEN
                IF NEW.unit_numerator_json IS NULL
                   OR NEW.unit_denominator_json IS NULL
                   OR jsonb_typeof(NEW.unit_numerator_json) <> 'array'
                   OR jsonb_typeof(NEW.unit_denominator_json) <> 'array'
                   OR (NEW.unit_id IS NOT NULL AND jsonb_array_length(NEW.unit_numerator_json) = 0)
                   OR (NEW.unit_id IS NULL AND (jsonb_array_length(NEW.unit_numerator_json) <> 0
                       OR jsonb_array_length(NEW.unit_denominator_json) <> 0))
                   OR (jsonb_array_length(NEW.unit_denominator_json) > 0
                       AND jsonb_array_length(NEW.unit_numerator_json) = 0) THEN
                    RAISE EXCEPTION 'invalid parser-v2 structured unit shape';
                END IF;
                IF NEW.dimensions_structured_json IS NULL
                   OR jsonb_typeof(NEW.dimensions_structured_json) <> 'array'
                   OR pg_column_size(NEW.dimensions_structured_json) > 262144
                   OR (SELECT count(*) FROM jsonb_path_query(
                        NEW.dimensions_structured_json, '$.** ? (@.type() == "object")'
                      )) > 4096
                   OR (SELECT coalesce(sum(octet_length(value #>> '{}')), 0)
                       FROM jsonb_path_query(
                         NEW.dimensions_structured_json, '$.** ? (@.type() == "string")'
                       ) strings(value)) > 262144 THEN
                    RAISE EXCEPTION 'invalid parser-v2 structured dimensions shape';
                END IF;
                FOR member IN SELECT value FROM jsonb_array_elements(
                    NEW.unit_numerator_json || NEW.unit_denominator_json
                ) LOOP
                    IF jsonb_typeof(member) <> 'object'
                       OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(member) key)
                          <> ARRAY['local_name', 'namespace_uri', 'prefix']
                       OR jsonb_typeof(member->'namespace_uri') <> 'string'
                       OR btrim(member->>'namespace_uri') = ''
                       OR jsonb_typeof(member->'local_name') <> 'string'
                       OR btrim(member->>'local_name') = ''
                       OR NOT (jsonb_typeof(member->'prefix') IN ('string', 'null')) THEN
                        RAISE EXCEPTION 'invalid parser-v2 structured unit QName';
                    END IF;
                END LOOP;
                FOR member IN SELECT value FROM jsonb_array_elements(
                    NEW.dimensions_structured_json
                ) LOOP
                    IF jsonb_typeof(member) <> 'object'
                       OR member->>'kind' NOT IN ('explicit', 'typed')
                       OR NOT sec_valid_qname(member->'axis')
                       OR (
                           member->>'kind' = 'explicit'
                           AND (
                               (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(member) key)
                                  <> ARRAY['axis','kind','member']
                               OR NOT sec_valid_qname(member->'member')
                           )
                       )
                       OR (
                           member->>'kind' = 'typed'
                           AND (
                               (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(member) key)
                                  <> ARRAY['axis','kind','typed_canonical','typed_child','typed_content_sha256','typed_structure']
                               OR NOT sec_valid_qname(member->'typed_child')
                               OR NOT sec_valid_typed_node(member->'typed_structure')
                               OR jsonb_typeof(member->'typed_canonical') <> 'string'
                               OR convert_from(convert_to(member->>'typed_canonical', 'UTF8'), 'UTF8') <> member->>'typed_canonical'
                               OR length(convert_to(member->>'typed_canonical', 'UTF8')) > 65536
                               OR (member->>'typed_content_sha256') !~ '^[0-9a-f]{64}$'
                               OR encode(sha256(convert_to(member->>'typed_canonical', 'UTF8')), 'hex') <> member->>'typed_content_sha256'
                               OR (member->>'typed_canonical')::jsonb <> member->'typed_structure'
                           )
                       ) THEN
                        RAISE EXCEPTION 'invalid parser-v2 structured dimension';
                    END IF;
                    IF (member->'axis')::text = ANY(dimension_axes) THEN
                        RAISE EXCEPTION 'duplicate parser-v2 structured dimension axis';
                    END IF;
                    dimension_axes := array_append(dimension_axes, (member->'axis')::text);
                END LOOP;
            ELSIF NEW.unit_numerator_json IS NOT NULL
               OR NEW.unit_denominator_json IS NOT NULL
               OR NEW.dimensions_structured_json IS NOT NULL THEN
                RAISE EXCEPTION 'legacy parser facts cannot claim parser-v2 structured units';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER trg_sec_parser_v2_structured_unit
        BEFORE INSERT ON sec_raw_xbrl_facts
        FOR EACH ROW EXECUTE FUNCTION validate_sec_parser_v2_structured_unit();
        """
    )
    op.create_table(
        "sec_financial_history_continuations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("issuer_identity_id", sa.BigInteger(), nullable=False),
        sa.Column("main_snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("source_operation_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("main_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_identity", sa.String(length=64), nullable=False),
        sa.Column("validated_references_json", postgresql.JSONB(), nullable=False),
        sa.Column("filing_selection_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("history_target_json", postgresql.JSONB(), nullable=False),
        sa.Column("next_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), server_default=sa.text("txid_current()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["issuer_identity_id"], ["sec_issuer_identities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["main_snapshot_id"], ["sec_submission_snapshots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_operation_id"], ["sec_financial_ingestion_operations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_id"], ["sec_financial_history_continuations.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("parent_id", name="uq_sec_history_continuation_parent"),
        sa.CheckConstraint("next_index >= 0", name="ck_sec_history_continuation_next_index"),
    )
    op.create_table(
        "sec_financial_history_consumption_claims",
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("issuer_identity_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("main_snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("manifest_identity", sa.String(length=64), nullable=False),
        sa.Column("filing_selection_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("history_target_json", postgresql.JSONB(), nullable=False),
        sa.Column("start_index", sa.Integer(), nullable=False),
        sa.Column("end_index", sa.Integer(), nullable=False),
        sa.Column("attempted_references_json", postgresql.JSONB(), nullable=False),
        sa.Column("terminal_outcomes_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), server_default=sa.text("txid_current()"), nullable=False),
        sa.PrimaryKeyConstraint("operation_id"),
        sa.ForeignKeyConstraint(["operation_id"], ["sec_financial_ingestion_operations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["issuer_identity_id"], ["sec_issuer_identities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_id"], ["sec_financial_history_continuations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["main_snapshot_id"], ["sec_submission_snapshots.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("start_index >= 0 AND end_index > start_index AND end_index - start_index <= 20", name="ck_sec_history_consumption_bounds"),
    )
    op.create_table(
        "sec_financial_history_continuation_failures",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("issuer_identity_id", sa.BigInteger(), nullable=False),
        sa.Column("cursor_id", sa.String(length=36), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("main_snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("request_contract_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), server_default=sa.text("txid_current()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["operation_id"], ["sec_financial_ingestion_operations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["issuer_identity_id"], ["sec_issuer_identities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["main_snapshot_id"], ["sec_submission_snapshots.id"], ondelete="RESTRICT"),
    )
    op.add_column("sec_financial_operation_results", sa.Column("history_continuation_failure_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_sec_operation_result_history_failure", "sec_financial_operation_results", "sec_financial_history_continuation_failures", ["history_continuation_failure_id"], ["id"], ondelete="RESTRICT")
    op.drop_constraint("ck_sec_financial_operation_results_shape", "sec_financial_operation_results", type_="check")
    op.create_check_constraint(
        "ck_sec_financial_operation_results_shape",
        "sec_financial_operation_results",
        "(result_kind = 'parse_run' AND parse_run_id IS NOT NULL AND acquisition_failure_id IS NULL AND history_continuation_failure_id IS NULL) OR "
        "(result_kind = 'acquisition_failure' AND parse_run_id IS NULL AND acquisition_failure_id IS NOT NULL AND history_continuation_failure_id IS NULL) OR "
        "(result_kind = 'history_continuation_failure' AND parse_run_id IS NULL AND acquisition_failure_id IS NULL AND history_continuation_failure_id IS NOT NULL) OR "
        "(result_kind = 'no_eligible_filings' AND parse_run_id IS NULL AND acquisition_failure_id IS NULL AND history_continuation_failure_id IS NULL)",
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_history_continuation_failure_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE op_identity bigint; op_txid bigint; snapshot_identity bigint; cursor_row sec_financial_history_continuations%ROWTYPE;
        BEGIN
          NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
          SELECT issuer_identity_id, created_txid INTO op_identity, op_txid FROM sec_financial_ingestion_operations WHERE id=NEW.operation_id;
          IF op_identity IS DISTINCT FROM NEW.issuer_identity_id OR op_txid<>txid_current()
             OR EXISTS(SELECT 1 FROM sec_financial_lineage_availabilities WHERE operation_id=NEW.operation_id)
             OR jsonb_typeof(NEW.request_contract_json)<>'object' THEN
            RAISE EXCEPTION 'invalid SEC history continuation failure authority'; END IF;
          IF NEW.main_snapshot_id IS NOT NULL THEN
            SELECT issuer_identity_id INTO snapshot_identity FROM sec_submission_snapshots WHERE id=NEW.main_snapshot_id;
            IF snapshot_identity IS DISTINCT FROM NEW.issuer_identity_id THEN RAISE EXCEPTION 'invalid SEC history continuation failure snapshot'; END IF;
          END IF;
          SELECT * INTO cursor_row FROM sec_financial_history_continuations WHERE id=NEW.cursor_id;
          IF cursor_row.id IS NOT NULL AND (cursor_row.issuer_identity_id<>NEW.issuer_identity_id
             OR NEW.main_snapshot_id IS DISTINCT FROM cursor_row.main_snapshot_id) THEN
            RAISE EXCEPTION 'invalid SEC history continuation failure cursor context'; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_sec_history_continuation_failure_insert
        BEFORE INSERT ON sec_financial_history_continuation_failures
        FOR EACH ROW EXECUTE FUNCTION guard_sec_history_continuation_failure_insert();

        CREATE FUNCTION guard_sec_history_operation_result_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE failure_op text; failure_tx bigint; result_op_tx bigint;
        BEGIN
          IF NEW.result_kind NOT IN ('parse_run','acquisition_failure','history_continuation_failure','no_eligible_filings') THEN
            RAISE EXCEPTION 'unknown SEC operation result kind'; END IF;
          IF NEW.result_kind='history_continuation_failure' THEN
            SELECT operation_id, created_txid INTO failure_op, failure_tx
            FROM sec_financial_history_continuation_failures WHERE id=NEW.history_continuation_failure_id;
            SELECT created_txid INTO result_op_tx FROM sec_financial_ingestion_operations WHERE id=NEW.operation_id;
            IF failure_op IS DISTINCT FROM NEW.operation_id OR failure_tx<>txid_current()
               OR result_op_tx<>txid_current() THEN RAISE EXCEPTION 'invalid reciprocal history continuation failure result'; END IF;
          END IF;
          NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current(); RETURN NEW;
        END $$;
        CREATE TRIGGER trg_sec_history_operation_result_insert
        BEFORE INSERT ON sec_financial_operation_results
        FOR EACH ROW EXECUTE FUNCTION guard_sec_history_operation_result_insert();
        """
    )
    op.execute(
        "CREATE TRIGGER trg_sec_financial_history_continuation_failures_immutable "
        "BEFORE UPDATE OR DELETE ON sec_financial_history_continuation_failures "
        "FOR EACH ROW EXECUTE FUNCTION reject_sec_financial_lineage_mutation(); "
        "CREATE TRIGGER trg_sec_financial_history_continuation_failures_no_truncate "
        "BEFORE TRUNCATE ON sec_financial_history_continuation_failures "
        "FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_financial_lineage_mutation()"
    )
    _replace_availability_guard(_AVAILABILITY_OLD, _AVAILABILITY_NEW)
    op.execute(
        """
        CREATE FUNCTION guard_sec_history_consumption_claim_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE op_identity bigint; op_txid bigint; snap_identity bigint;
                parent_row sec_financial_history_continuations%ROWTYPE;
                item jsonb; expected_ref text; idx integer := 0;
        BEGIN
          NEW.created_at := clock_timestamp(); NEW.created_txid := txid_current();
          SELECT issuer_identity_id, created_txid INTO op_identity, op_txid
          FROM sec_financial_ingestion_operations WHERE id=NEW.operation_id;
          SELECT issuer_identity_id INTO snap_identity FROM sec_submission_snapshots WHERE id=NEW.main_snapshot_id;
          IF op_identity IS DISTINCT FROM NEW.issuer_identity_id OR op_txid <> txid_current()
             OR snap_identity IS DISTINCT FROM NEW.issuer_identity_id
             OR jsonb_typeof(NEW.history_target_json) <> 'object'
             OR jsonb_typeof(NEW.attempted_references_json) <> 'array'
             OR jsonb_typeof(NEW.terminal_outcomes_json) <> 'array'
             OR jsonb_array_length(NEW.attempted_references_json) <> NEW.end_index-NEW.start_index
             OR jsonb_array_length(NEW.terminal_outcomes_json) <> NEW.end_index-NEW.start_index THEN
             RAISE EXCEPTION 'invalid SEC history consumption claim authority'; END IF;
          IF NEW.parent_id IS NULL THEN
            IF NEW.start_index <> 0 THEN RAISE EXCEPTION 'invalid SEC history claim start'; END IF;
          ELSE
            SELECT * INTO parent_row FROM sec_financial_history_continuations WHERE id=NEW.parent_id FOR SHARE;
            IF parent_row.id IS NULL OR parent_row.issuer_identity_id<>NEW.issuer_identity_id
               OR parent_row.main_snapshot_id<>NEW.main_snapshot_id OR parent_row.manifest_identity<>NEW.manifest_identity
               OR parent_row.filing_selection_as_of IS DISTINCT FROM NEW.filing_selection_as_of
               OR parent_row.history_target_json<>NEW.history_target_json OR parent_row.next_index<>NEW.start_index THEN
              RAISE EXCEPTION 'invalid SEC history claim parent authority'; END IF;
          END IF;
          FOR item IN SELECT value FROM jsonb_array_elements(NEW.terminal_outcomes_json) LOOP
            expected_ref := NEW.attempted_references_json->>idx;
            IF jsonb_typeof(item)<>'object'
               OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(item) key)<>ARRAY['outcome','reference']
               OR item->>'reference' IS DISTINCT FROM expected_ref THEN
              RAISE EXCEPTION 'invalid SEC history claim outcome'; END IF;
            IF item->>'outcome'='retained_and_parsed' THEN
              IF NOT EXISTS (SELECT 1 FROM sec_submission_snapshots s
                JOIN sec_financial_operation_snapshots os ON os.snapshot_id=s.id
                WHERE os.operation_id=NEW.operation_id AND s.issuer_identity_id=NEW.issuer_identity_id
                AND s.source_url='https://data.sec.gov/submissions/'||expected_ref) THEN
                RAISE EXCEPTION 'missing durable SEC history attempt observation'; END IF;
            ELSIF NOT EXISTS (SELECT 1 FROM sec_financial_acquisition_failures f
                WHERE f.operation_id=NEW.operation_id AND f.resource_role='historical_submissions'
                AND f.resource_key='https://data.sec.gov/submissions/'||expected_ref
                AND f.error_code=item->>'outcome') THEN
                RAISE EXCEPTION 'missing durable SEC history attempt observation';
            END IF;
            idx := idx+1;
          END LOOP;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_sec_history_consumption_claim_insert
        BEFORE INSERT ON sec_financial_history_consumption_claims
        FOR EACH ROW EXECUTE FUNCTION guard_sec_history_consumption_claim_insert();
        """
    )
    op.execute(
        "CREATE TRIGGER trg_sec_financial_history_consumption_claims_immutable "
        "BEFORE UPDATE OR DELETE ON sec_financial_history_consumption_claims "
        "FOR EACH ROW EXECUTE FUNCTION reject_sec_financial_lineage_mutation(); "
        "CREATE TRIGGER trg_sec_financial_history_consumption_claims_no_truncate "
        "BEFORE TRUNCATE ON sec_financial_history_consumption_claims "
        "FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_financial_lineage_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION guard_sec_financial_history_continuation_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            snapshot_identity bigint;
            snapshot_sha text;
            operation_identity bigint;
            parent_row sec_financial_history_continuations%ROWTYPE;
            consumption sec_financial_history_consumption_claims%ROWTYPE;
            reference jsonb;
            identity_cik text;
        BEGIN
            NEW.created_at := clock_timestamp();
            NEW.created_txid := txid_current();
            SELECT issuer_identity_id, sha256 INTO snapshot_identity, snapshot_sha
            FROM sec_submission_snapshots WHERE id = NEW.main_snapshot_id;
            SELECT issuer_identity_id INTO operation_identity
            FROM sec_financial_ingestion_operations WHERE id = NEW.source_operation_id;
            SELECT cik INTO identity_cik FROM sec_issuer_identities
            WHERE id = NEW.issuer_identity_id;
            IF NEW.id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
               OR snapshot_identity IS DISTINCT FROM NEW.issuer_identity_id
               OR operation_identity IS DISTINCT FROM NEW.issuer_identity_id
               OR EXISTS (
                   SELECT 1 FROM sec_financial_lineage_availabilities
                   WHERE operation_id = NEW.source_operation_id
               )
               OR snapshot_sha IS DISTINCT FROM NEW.main_sha256
               OR NEW.main_sha256 !~ '^[0-9a-f]{64}$'
               OR NEW.manifest_identity !~ '^[0-9a-f]{64}$'
               OR jsonb_typeof(NEW.validated_references_json) <> 'array'
               OR jsonb_typeof(NEW.history_target_json) <> 'object'
               OR NEW.next_index > jsonb_array_length(NEW.validated_references_json) THEN
                RAISE EXCEPTION 'invalid SEC history continuation authority';
            END IF;
            FOR reference IN SELECT value FROM jsonb_array_elements(NEW.validated_references_json)
            LOOP
                IF jsonb_typeof(reference) <> 'string'
                   OR trim(both '"' from reference::text) !~
                      ('^CIK' || identity_cik || '-submissions-[0-9]+[.]json$') THEN
                    RAISE EXCEPTION 'invalid SEC history continuation reference';
                END IF;
            END LOOP;
            IF NEW.parent_id IS NOT NULL THEN
                SELECT * INTO parent_row FROM sec_financial_history_continuations
                WHERE id = NEW.parent_id FOR SHARE;
                IF parent_row.id IS NULL
                   OR parent_row.issuer_identity_id <> NEW.issuer_identity_id
                   OR parent_row.main_snapshot_id <> NEW.main_snapshot_id
                   OR parent_row.main_sha256 <> NEW.main_sha256
                   OR parent_row.manifest_identity <> NEW.manifest_identity
                   OR parent_row.validated_references_json <> NEW.validated_references_json
                   OR parent_row.filing_selection_as_of IS DISTINCT FROM NEW.filing_selection_as_of
                   OR parent_row.history_target_json <> NEW.history_target_json
                   OR NEW.next_index <= parent_row.next_index
                   OR NEW.next_index - parent_row.next_index > 20 THEN
                    RAISE EXCEPTION 'invalid SEC history continuation advance';
                END IF;
            ELSIF NEW.next_index < 1 OR NEW.next_index > 20 THEN
                RAISE EXCEPTION 'invalid initial SEC history continuation boundary';
            END IF;
            SELECT * INTO consumption FROM sec_financial_history_consumption_claims
            WHERE operation_id = NEW.source_operation_id;
            IF consumption.operation_id IS NULL
               OR consumption.parent_id IS DISTINCT FROM NEW.parent_id
               OR consumption.main_snapshot_id <> NEW.main_snapshot_id
               OR consumption.manifest_identity <> NEW.manifest_identity
               OR consumption.end_index <> NEW.next_index
               OR jsonb_array_length(consumption.attempted_references_json)
                  <> consumption.end_index - consumption.start_index
               OR jsonb_array_length(consumption.terminal_outcomes_json)
                  <> consumption.end_index - consumption.start_index
               OR consumption.attempted_references_json <> (
                    SELECT coalesce(jsonb_agg(item.value ORDER BY item.ordinality), '[]'::jsonb)
                    FROM jsonb_array_elements(NEW.validated_references_json)
                         WITH ORDINALITY AS item(value, ordinality)
                    WHERE item.ordinality > consumption.start_index
                      AND item.ordinality <= consumption.end_index
               ) THEN
                RAISE EXCEPTION 'continuation requires exact operation consumption claim';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER trg_sec_financial_history_continuations_insert_guard
        BEFORE INSERT ON sec_financial_history_continuations
        FOR EACH ROW EXECUTE FUNCTION guard_sec_financial_history_continuation_insert();
        """
    )
    op.execute(
        "CREATE TRIGGER trg_sec_financial_history_continuations_immutable "
        "BEFORE UPDATE OR DELETE ON sec_financial_history_continuations "
        "FOR EACH ROW EXECUTE FUNCTION reject_sec_financial_lineage_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_sec_financial_history_continuations_no_truncate "
        "BEFORE TRUNCATE ON sec_financial_history_continuations "
        "FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_financial_lineage_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_sec_raw_xbrl_facts_no_truncate "
        "BEFORE TRUNCATE ON sec_raw_xbrl_facts "
        "FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_financial_lineage_mutation()"
    )


def downgrade() -> None:
    connection = op.get_bind()
    # Lock in the same global order used by this downgrade before observing
    # either evidence set. Concurrent appenders must finish first, after which
    # their committed evidence is included in the fail-closed decision.
    connection.execute(
        sa.text(
            "LOCK TABLE sec_raw_xbrl_facts, "
            "sec_financial_history_continuations, "
            "sec_financial_history_consumption_claims, "
            "sec_financial_history_continuation_failures "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    evidence_count = connection.execute(
        sa.text(
            "SELECT count(*) FROM sec_raw_xbrl_facts "
            "WHERE unit_numerator_json IS NOT NULL "
            "OR unit_denominator_json IS NOT NULL "
            "OR dimensions_structured_json IS NOT NULL"
        )
    ).scalar_one()
    if evidence_count:
        raise RuntimeError(
            "cannot downgrade with retained SEC parser-v2 structured QName evidence"
        )
    continuation_count = connection.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM sec_financial_history_continuations) + "
            "(SELECT count(*) FROM sec_financial_history_consumption_claims) + "
            "(SELECT count(*) FROM sec_financial_history_continuation_failures)"
        )
    ).scalar_one()
    if continuation_count:
        raise RuntimeError("cannot downgrade with retained SEC history continuations")
    _replace_availability_guard(_AVAILABILITY_NEW, _AVAILABILITY_OLD)
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_history_continuations_immutable ON sec_financial_history_continuations")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_history_continuations_insert_guard ON sec_financial_history_continuations")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_financial_history_continuation_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_history_continuations_no_truncate ON sec_financial_history_continuations")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_history_consumption_claims_immutable ON sec_financial_history_consumption_claims")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_history_consumption_claim_insert ON sec_financial_history_consumption_claims")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_history_consumption_claim_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_history_consumption_claims_no_truncate ON sec_financial_history_consumption_claims")
    op.drop_table("sec_financial_history_consumption_claims")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_history_operation_result_insert ON sec_financial_operation_results")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_history_operation_result_insert()")
    op.drop_constraint("ck_sec_financial_operation_results_shape", "sec_financial_operation_results", type_="check")
    op.drop_constraint("fk_sec_operation_result_history_failure", "sec_financial_operation_results", type_="foreignkey")
    op.drop_column("sec_financial_operation_results", "history_continuation_failure_id")
    op.create_check_constraint(
        "ck_sec_financial_operation_results_shape", "sec_financial_operation_results",
        "(result_kind = 'parse_run' AND parse_run_id IS NOT NULL AND acquisition_failure_id IS NULL) OR (result_kind = 'acquisition_failure' AND parse_run_id IS NULL AND acquisition_failure_id IS NOT NULL) OR (result_kind = 'no_eligible_filings' AND parse_run_id IS NULL AND acquisition_failure_id IS NULL)",
    )
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_history_continuation_failures_immutable ON sec_financial_history_continuation_failures")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_history_continuation_failure_insert ON sec_financial_history_continuation_failures")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_history_continuation_failure_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_financial_history_continuation_failures_no_truncate ON sec_financial_history_continuation_failures")
    op.drop_table("sec_financial_history_continuation_failures")
    op.drop_table("sec_financial_history_continuations")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_raw_xbrl_facts_no_truncate ON sec_raw_xbrl_facts")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_parser_v2_structured_unit ON sec_raw_xbrl_facts")
    op.execute("DROP FUNCTION IF EXISTS validate_sec_parser_v2_structured_unit()")
    op.execute("DROP FUNCTION IF EXISTS sec_valid_typed_node(jsonb, integer)")
    op.execute("DROP FUNCTION IF EXISTS sec_valid_qname(jsonb)")
    op.drop_column("sec_raw_xbrl_facts", "unit_denominator_json")
    op.drop_column("sec_raw_xbrl_facts", "unit_numerator_json")
    op.drop_column("sec_raw_xbrl_facts", "dimensions_structured_json")
