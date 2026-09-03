"""Allow exact unresolved SEC slot decisions without weakening published facts.

Revision ID: 20260901160000
Revises: 20260901150000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260901160000"
down_revision = "20260901150000"
branch_labels = None
depends_on = None


def _function(unresolved_unit_clause: str) -> str:
    return f"""
    CREATE OR REPLACE FUNCTION guard_sec_publication_decision_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE run sec_metric_publication_runs%ROWTYPE; rule sec_metric_mapping_rules%ROWTYPE;
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.known_at:=NEW.created_at; NEW.created_txid:=txid_current();
      SELECT * INTO run FROM sec_metric_publication_runs WHERE id=NEW.publication_run_id;
      SELECT * INTO rule FROM sec_metric_mapping_rules WHERE id=NEW.mapping_rule_id;
      IF run.id IS NULL OR NEW.stock_id<>run.stock_id OR rule.id IS NULL OR rule.mapping_version_id<>run.mapping_version_id
         OR NEW.metric_key<>rule.metric_key OR {unresolved_unit_clause}
         OR NOT ((NEW.status='published' AND NEW.unit=rule.target_unit AND
                  ((NEW.fact_nature='actual' AND NEW.derivation_kind='direct' AND NEW.source_role='primary_as_filed_actual') OR
                   (NEW.fact_nature='derived_actual' AND NEW.source_role='derived_actual' AND NEW.derivation_kind IN ('current_ytd_minus_prior_ytd','fiscal_year_minus_nine_month_ytd'))))
                 OR (NEW.status<>'published' AND NEW.unit IS NULL AND NEW.currency IS NULL AND
                     NEW.value_numeric IS NULL AND NEW.metric_fact_id IS NULL AND NEW.derivation_kind='unresolved'))
      THEN RAISE EXCEPTION 'publication decision authority mismatch'; END IF;
      IF NEW.status='published' AND (
          (NEW.derivation_kind='direct' AND NOT (NEW.locator_json ?& ARRAY['statement_authority_id','statement_report_reference_id','statement_artifact_id','statement_sha256','occurrence_fact_id','report_ordinal','occurrence_ordinal','row_ordinal','column_ordinal','raw_fact_id','parse_run_id']))
          OR (NEW.derivation_kind<>'direct' AND NOT (jsonb_typeof(NEW.audit_json->'ordered_input_occurrences')='array' AND jsonb_array_length(NEW.audit_json->'ordered_input_occurrences')=2))
      ) THEN RAISE EXCEPTION 'publication occurrence provenance mismatch'; END IF;
      RETURN NEW; END $$;
    """


def upgrade() -> None:
    # Linear repair for the decision rule FK required by the already-deployed
    # integrity functions and the publication service. Earlier revisions stay
    # byte-for-byte immutable.
    op.add_column("sec_metric_publications", sa.Column("mapping_rule_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_sec_metric_publications_mapping_rule",
        "sec_metric_publications",
        "sec_metric_mapping_rules",
        ["mapping_rule_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute("""
      CREATE FUNCTION digest(input text, algorithm text) RETURNS bytea
      LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
        SELECT CASE WHEN lower(algorithm)='sha256'
          THEN sha256(convert_to(input,'UTF8')) ELSE NULL END
      $$
    """)
    op.alter_column("sec_metric_publications", "mapping_rule_id", nullable=False)
    op.create_table(
        "sec_metric_mapping_rule_concepts",
        sa.Column("id",sa.BigInteger(),autoincrement=True,nullable=False),
        sa.Column("mapping_rule_id",sa.BigInteger(),nullable=False),
        sa.Column("concept_ordinal",sa.Integer(),nullable=False),
        sa.Column("namespace_authority",sa.String(32),nullable=False),
        sa.Column("local_name",sa.String(),nullable=False),
        sa.Column("spec_sha256",sa.String(64),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("clock_timestamp()"),nullable=False),
        sa.Column("created_txid",sa.BigInteger(),server_default=sa.text("txid_current()"),nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["mapping_rule_id"],["sec_metric_mapping_rules.id"],ondelete="RESTRICT"),
        sa.UniqueConstraint("mapping_rule_id","concept_ordinal",name="uq_sec_metric_mapping_rule_concept_ordinal"),
        sa.UniqueConstraint("mapping_rule_id","local_name",name="uq_sec_metric_mapping_rule_concept_name"),
        sa.CheckConstraint("concept_ordinal>0 AND namespace_authority IN ('us_gaap','dei') AND spec_sha256 ~ '^[0-9a-f]{64}$'",name="ck_sec_metric_mapping_rule_concept_shape"),
    )
    op.execute("""INSERT INTO sec_metric_mapping_rule_concepts
      (mapping_rule_id,concept_ordinal,namespace_authority,local_name,spec_sha256)
      SELECT r.id,e.ordinality,CASE WHEN e.value='EntityCommonStockSharesOutstanding' THEN 'dei' ELSE r.concept_namespace_authority END,
             e.value,r.spec_sha256
      FROM sec_metric_mapping_rules r
      CROSS JOIN LATERAL jsonb_array_elements_text(r.metadata_json->'ordered_concepts') WITH ORDINALITY e(value,ordinality)
      WHERE r.mapping_version_id='sec-us-gaap-v1' ORDER BY r.id,e.ordinality""")
    op.execute("""CREATE TRIGGER trg_sec_metric_mapping_rule_concepts_immutable BEFORE UPDATE OR DELETE ON sec_metric_mapping_rule_concepts
      FOR EACH ROW EXECUTE FUNCTION reject_sec_financial_lineage_mutation();
      CREATE TRIGGER trg_sec_metric_mapping_rule_concepts_no_truncate BEFORE TRUNCATE ON sec_metric_mapping_rule_concepts
      FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_financial_lineage_mutation();""")
    op.create_table(
        "sec_metric_publication_audits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("publication_run_id", sa.String(36), nullable=False),
        sa.Column("mapping_rule_id", sa.BigInteger(), nullable=True),
        sa.Column("audit_ordinal", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("raw_fact_ids_json", postgresql.JSONB(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["publication_run_id"], ["sec_metric_publication_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["mapping_rule_id"], ["sec_metric_mapping_rules.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("publication_run_id", "audit_ordinal", name="uq_sec_metric_publication_audit_ordinal"),
        sa.CheckConstraint("audit_ordinal>0 AND jsonb_typeof(raw_fact_ids_json)='array'", name="ck_sec_metric_publication_audit_shape"),
    )
    op.create_table(
        "sec_metric_publication_unresolved_inputs",
        sa.Column("id",sa.BigInteger(),autoincrement=True,nullable=False),
        sa.Column("publication_id",sa.BigInteger(),nullable=False),
        sa.Column("input_ordinal",sa.Integer(),nullable=False),
        sa.Column("run_source_id",sa.BigInteger(),nullable=False),
        sa.Column("raw_fact_id",sa.BigInteger(),nullable=False),
        sa.Column("statement_authority_id",sa.BigInteger(),nullable=False),
        sa.Column("normalization_id",sa.BigInteger(),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("clock_timestamp()"),nullable=False),
        sa.Column("created_txid",sa.BigInteger(),server_default=sa.text("txid_current()"),nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["publication_id"],["sec_metric_publications.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_source_id"],["sec_metric_publication_run_sources.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["raw_fact_id"],["sec_raw_xbrl_facts.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["statement_authority_id"],["sec_statement_fact_authorities.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["normalization_id"],["sec_raw_numeric_normalizations.id"],ondelete="RESTRICT"),
        sa.UniqueConstraint("publication_id","input_ordinal",name="uq_sec_metric_publication_unresolved_input_ordinal"),
        sa.CheckConstraint("input_ordinal>0",name="ck_sec_metric_publication_unresolved_input_ordinal"),
    )
    op.execute("""
      CREATE FUNCTION reject_sec_metric_publication_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'SEC publication audits are append-only'; END $$;
      CREATE FUNCTION guard_sec_metric_publication_audit_insert() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE run sec_metric_publication_runs%ROWTYPE; rule sec_metric_mapping_rules%ROWTYPE;
      BEGIN
        NEW.created_at:=clock_timestamp(); NEW.known_at:=NEW.created_at; NEW.created_txid:=txid_current();
        SELECT * INTO run FROM sec_metric_publication_runs WHERE id=NEW.publication_run_id;
        IF run.id IS NULL THEN RAISE EXCEPTION 'publication audit run authority mismatch'; END IF;
        IF NEW.mapping_rule_id IS NOT NULL THEN
          SELECT * INTO rule FROM sec_metric_mapping_rules WHERE id=NEW.mapping_rule_id;
          IF rule.id IS NULL OR rule.mapping_version_id<>run.mapping_version_id THEN
            RAISE EXCEPTION 'publication audit mapping authority mismatch';
          END IF;
        END IF;
        IF NEW.reason_code NOT IN (
          'duplicate_identical_candidate_not_selected','lower_priority_concept_not_selected',
          'unresolved_amendment_parse_failure','unresolved_conflicting_candidates','unresolved_context',
          'unresolved_currency','unresolved_custom_concept','unresolved_derived_context_mismatch',
          'unresolved_derived_cross_stock','unresolved_derived_currency_mismatch',
          'unresolved_derived_filing_authority_mismatch','unresolved_derived_fiscal_year_mismatch',
          'unresolved_derived_input_after_cutoff','unresolved_derived_period_identity',
          'unresolved_derived_unit_mismatch','unresolved_dimensions',
          'unresolved_missing_derived_quarter_input','unresolved_period',
          'unresolved_period_filing_cycle_mismatch','unresolved_unit',
          'unresolved_unsupported_form_semantics','unresolved_value')
        THEN RAISE EXCEPTION 'publication audit reason is not approved'; END IF;
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.raw_fact_ids_json) v
                   WHERE jsonb_typeof(v)<>'number' OR (v#>>'{}')::bigint<=0)
           OR (SELECT count(*) FROM jsonb_array_elements(NEW.raw_fact_ids_json))<>
              (SELECT count(DISTINCT v#>>'{}') FROM jsonb_array_elements(NEW.raw_fact_ids_json) v)
        THEN RAISE EXCEPTION 'publication audit raw identity mismatch'; END IF;
        IF NEW.reason_code='unresolved_amendment_parse_failure' AND jsonb_array_length(NEW.raw_fact_ids_json)<>0
        THEN RAISE EXCEPTION 'failed amendment run audit cannot claim raw identity'; END IF;
        IF NEW.reason_code<>'unresolved_amendment_parse_failure' AND EXISTS (
          SELECT 1 FROM jsonb_array_elements_text(NEW.raw_fact_ids_json) v
          WHERE NOT EXISTS (
            SELECT 1 FROM sec_raw_xbrl_facts raw
            JOIN sec_metric_publication_run_sources src ON src.parse_run_id=raw.parse_run_id
            WHERE src.publication_run_id=NEW.publication_run_id AND raw.id=v::bigint
              AND (NEW.mapping_rule_id IS NULL OR rule.metadata_json->'ordered_concepts' ?
                CASE WHEN strpos(raw.concept,':')>0 THEN split_part(raw.concept,':',2) ELSE raw.concept END)))
        THEN RAISE EXCEPTION 'publication audit raw source authority mismatch'; END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER trg_sec_metric_publication_audit_insert BEFORE INSERT ON sec_metric_publication_audits
        FOR EACH ROW EXECUTE FUNCTION guard_sec_metric_publication_audit_insert();
      CREATE TRIGGER trg_sec_metric_publication_audit_update_delete BEFORE UPDATE OR DELETE ON sec_metric_publication_audits
        FOR EACH ROW EXECUTE FUNCTION reject_sec_metric_publication_audit_mutation();
      CREATE TRIGGER trg_sec_metric_publication_audit_truncate BEFORE TRUNCATE ON sec_metric_publication_audits
        FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_metric_publication_audit_mutation();
      CREATE TRIGGER trg_sec_metric_publication_unresolved_inputs_update_delete BEFORE UPDATE OR DELETE ON sec_metric_publication_unresolved_inputs
        FOR EACH ROW EXECUTE FUNCTION reject_sec_metric_publication_audit_mutation();
      CREATE TRIGGER trg_sec_metric_publication_unresolved_inputs_truncate BEFORE TRUNCATE ON sec_metric_publication_unresolved_inputs
        FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_metric_publication_audit_mutation();
    """)
    op.execute(_function("false"))
    op.execute(_atomic_function("q2_q3"))
    op.execute(_publication_source_function(allow_failed_amendment=True))
    op.execute(_availability_function(include_audits=True))
    op.execute(_provenance_function())
    op.execute(_unresolved_input_insert_function())


def downgrade() -> None:
    op.execute("LOCK TABLE sec_metric_publications, sec_metric_publication_audits IN SHARE ROW EXCLUSIVE MODE")
    connection = op.get_bind()
    if connection.exec_driver_sql("SELECT count(*) FROM sec_statement_fact_authorities").scalar_one():
        raise RuntimeError("downgrade refused: retained SEC statement authority exists")
    if connection.exec_driver_sql("SELECT count(*) FROM sec_metric_publications WHERE status<>'published' AND unit IS NULL").scalar_one():
        raise RuntimeError("cannot downgrade unresolved SEC publication evidence")
    if connection.exec_driver_sql("SELECT count(*) FROM sec_metric_publication_audits").scalar_one():
        raise RuntimeError("cannot downgrade SEC publication audit evidence")
    # Restore the prior effective behavior: unit must always equal target unit.
    op.execute(_function("NEW.unit IS DISTINCT FROM rule.target_unit"))
    op.execute(_atomic_function("legacy"))
    op.execute(_publication_source_function(allow_failed_amendment=False))
    op.execute(_availability_function(include_audits=False))
    op.execute("DROP TRIGGER IF EXISTS trg_sec_publication_provenance_publication ON sec_metric_publications; DROP TRIGGER IF EXISTS trg_sec_publication_provenance_input ON sec_metric_publication_inputs; DROP TRIGGER IF EXISTS trg_sec_publication_provenance_unresolved ON sec_metric_publication_unresolved_inputs; DROP TRIGGER IF EXISTS trg_sec_publication_unresolved_input_insert ON sec_metric_publication_unresolved_inputs; DROP FUNCTION IF EXISTS guard_sec_publication_unresolved_input_insert(); DROP FUNCTION IF EXISTS validate_sec_publication_provenance()")
    op.drop_table("sec_metric_publication_unresolved_inputs")
    op.drop_table("sec_metric_mapping_rule_concepts")
    op.drop_table("sec_metric_publication_audits")
    op.execute("DROP FUNCTION guard_sec_metric_publication_audit_insert()")
    op.execute("DROP FUNCTION reject_sec_metric_publication_audit_mutation()")
    op.drop_constraint("fk_sec_metric_publications_mapping_rule", "sec_metric_publications", type_="foreignkey")
    op.drop_column("sec_metric_publications", "mapping_rule_id")
    op.execute("DROP FUNCTION digest(text,text)")


def _atomic_function(mode: str) -> str:
    right_shape = (
        "((NEW.fiscal_quarter_ordinal=2 AND right_decision.period_type='Q' AND right_decision.fiscal_quarter_ordinal=1) OR "
        "(NEW.fiscal_quarter_ordinal=3 AND right_decision.period_type='YTD' AND right_decision.fiscal_quarter_ordinal=2))"
        if mode == "q2_q3" else
        "right_decision.period_type='YTD' AND right_decision.fiscal_quarter_ordinal=NEW.fiscal_quarter_ordinal-1"
    )
    return f"""
    CREATE OR REPLACE FUNCTION validate_sec_publication_atomic_shape() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE decision sec_metric_publications%ROWTYPE; input_count integer; input_sum numeric(38,12); direct_count integer; left_decision sec_metric_publications%ROWTYPE; right_decision sec_metric_publications%ROWTYPE;
    BEGIN
      IF TG_TABLE_NAME='metric_facts' THEN
        IF NEW.source_type='sec' THEN SELECT * INTO decision FROM sec_metric_publications WHERE id=NEW.source_ref_id;
          IF decision.id IS NULL OR decision.status<>'published' OR decision.metric_fact_id IS DISTINCT FROM NEW.id OR decision.stock_id<>NEW.stock_id OR decision.metric_key<>NEW.metric_key OR decision.period_type<>NEW.period_type OR decision.period_end_date<>NEW.period_end_date OR decision.value_numeric<>NEW.value_numeric OR decision.unit<>NEW.unit OR decision.currency IS DISTINCT FROM NEW.currency THEN RAISE EXCEPTION 'SEC fact publication reciprocity mismatch'; END IF;
        END IF;
      ELSE
        SELECT count(*),sum(i.arithmetic_sign*s.value_numeric),count(*) FILTER (WHERE i.input_role='direct') INTO input_count,input_sum,direct_count FROM sec_metric_publication_inputs i LEFT JOIN sec_metric_publications s ON s.id=i.source_publication_id WHERE i.publication_id=NEW.id;
        SELECT s.* INTO left_decision FROM sec_metric_publication_inputs i JOIN sec_metric_publications s ON s.id=i.source_publication_id WHERE i.publication_id=NEW.id AND i.input_role='left_operand';
        SELECT s.* INTO right_decision FROM sec_metric_publication_inputs i JOIN sec_metric_publications s ON s.id=i.source_publication_id WHERE i.publication_id=NEW.id AND i.input_role='right_operand';
        IF NEW.status='published' AND (NEW.metric_fact_id IS NULL OR input_count<1) THEN RAISE EXCEPTION 'published decision requires fact and exact inputs'; END IF;
        IF NEW.status='published' AND NEW.fact_nature='actual' AND (NEW.derivation_kind<>'direct' OR input_count<>1 OR direct_count<>1) THEN RAISE EXCEPTION 'direct publication arithmetic authority mismatch'; END IF;
        IF NEW.status='published' AND NEW.fact_nature='derived_actual' AND
          (NEW.derivation_kind NOT IN ('current_ytd_minus_prior_ytd','fiscal_year_minus_nine_month_ytd') OR input_count<>2 OR direct_count<>0 OR input_sum IS NULL OR input_sum<>NEW.value_numeric OR left_decision.id IS NULL OR right_decision.id IS NULL OR NEW.period_type<>'Q' OR NEW.period_basis<>'duration' OR NEW.fiscal_quarter_ordinal IS NULL OR NEW.period_start_date IS NULL OR NEW.period_end_date-NEW.period_start_date NOT BETWEEN 70 AND 110
           OR (NEW.derivation_kind='current_ytd_minus_prior_ytd' AND NOT (NEW.fiscal_quarter_ordinal IN (2,3) AND left_decision.period_type='YTD' AND left_decision.fiscal_quarter_ordinal=NEW.fiscal_quarter_ordinal AND {right_shape} AND left_decision.period_start_date=right_decision.period_start_date AND left_decision.period_end_date=NEW.period_end_date AND NEW.period_start_date=right_decision.period_end_date+1 AND right_decision.period_end_date<left_decision.period_end_date))
           OR (NEW.derivation_kind='fiscal_year_minus_nine_month_ytd' AND NOT (NEW.fiscal_quarter_ordinal=4 AND left_decision.period_type='FY' AND left_decision.fiscal_quarter_ordinal IS NULL AND right_decision.period_type='YTD' AND right_decision.fiscal_quarter_ordinal=3 AND left_decision.period_start_date=right_decision.period_start_date AND left_decision.period_end_date=NEW.period_end_date AND NEW.period_start_date=right_decision.period_end_date+1 AND right_decision.period_end_date<left_decision.period_end_date)))
          THEN RAISE EXCEPTION 'derived publication arithmetic authority mismatch'; END IF;
        IF NEW.status<>'published' AND NEW.metric_fact_id IS NOT NULL THEN RAISE EXCEPTION 'unresolved decision cannot reference fact'; END IF;
        IF NEW.status<>'published' AND input_count<>0 THEN RAISE EXCEPTION 'unresolved decision cannot own lineage inputs'; END IF;
      END IF; RETURN NULL; END $$;
    """


def _publication_source_function(*, allow_failed_amendment: bool) -> str:
    parse_authority = (
        "(parse.status='succeeded' OR (parse.status='failed' AND parse.fact_count=0 AND filing.is_amendment AND "
        "EXISTS (SELECT 1 FROM sec_financial_accession_attempts a WHERE a.parse_run_id=parse.id AND a.filing_id=filing.id AND a.outcome IN ('parse_failed','parse_reused_failed')) AND "
        "EXISTS (SELECT 1 FROM sec_financial_acquisition_resolutions r WHERE r.parse_run_id=parse.id AND r.accession_no=filing.accession_no AND r.resolution_kind='parse_failed')))"
        if allow_failed_amendment else "parse.status='succeeded'"
    )
    return f"""
    CREATE OR REPLACE FUNCTION guard_sec_publication_source_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE pub sec_metric_publication_runs%ROWTYPE; parse sec_financial_parse_runs%ROWTYPE; filing sec_financial_filings%ROWTYPE; available timestamptz;
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
      SELECT * INTO pub FROM sec_metric_publication_runs WHERE id=NEW.publication_run_id;
      SELECT * INTO parse FROM sec_financial_parse_runs WHERE id=NEW.parse_run_id;
      SELECT * INTO filing FROM sec_financial_filings WHERE id=parse.filing_id;
      SELECT available_at INTO available FROM sec_financial_lineage_availabilities WHERE operation_id=parse.operation_id;
      IF pub.id IS NULL OR NOT {parse_authority} OR parse.filing_id<>NEW.filing_id OR filing.accession_no<>NEW.accession_no
         OR filing.issuer_identity_id<>pub.issuer_identity_id OR parse.parser_version<>NEW.parser_version
         OR parse.input_manifest_hash<>NEW.input_manifest_hash OR available IS NULL OR available>pub.requested_cutoff OR available<>NEW.source_available_at
         OR parse.known_at>pub.requested_cutoff THEN RAISE EXCEPTION 'invalid publication parse authority source'; END IF;
      RETURN NEW; END $$;
    """


def _availability_function(*, include_audits: bool) -> str:
    audit_select = (
        "SELECT count(*) INTO audit_count FROM sec_metric_publication_audits WHERE publication_run_id=pub.id;"
        if include_audits else "audit_count:=0;"
    )
    rejected_term = "pub.rejected_count" if include_audits else "0"
    return f"""
    CREATE OR REPLACE FUNCTION stamp_sec_publication_availability() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE pub sec_metric_publication_runs%ROWTYPE; source_count integer; decision_count integer; audit_count integer;
    BEGIN
      SELECT * INTO pub FROM sec_metric_publication_runs WHERE id=NEW.publication_run_id FOR UPDATE;
      IF pub.id IS NULL OR pub.created_txid=txid_current() OR pub.status<>'succeeded' THEN RAISE EXCEPTION 'publication availability requires committed succeeded run'; END IF;
      SELECT count(*) INTO source_count FROM sec_metric_publication_run_sources WHERE publication_run_id=pub.id;
      SELECT count(*) INTO decision_count FROM sec_metric_publications WHERE publication_run_id=pub.id;
      {audit_select}
      IF source_count<1 OR decision_count<>pub.published_count+pub.unresolved_count OR audit_count<>{rejected_term}
      THEN RAISE EXCEPTION 'publication terminal counts or sources incomplete'; END IF;
      IF EXISTS(SELECT 1 FROM generate_series(1,source_count) n WHERE NOT EXISTS(SELECT 1 FROM sec_metric_publication_run_sources s WHERE s.publication_run_id=pub.id AND s.source_ordinal=n)) THEN RAISE EXCEPTION 'publication sources must be gapless'; END IF;
      NEW.available_at:=clock_timestamp(); NEW.finalized_txid:=txid_current(); RETURN NEW; END $$;
    """


def _provenance_function() -> str:
    return """
    CREATE OR REPLACE FUNCTION validate_sec_publication_provenance() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE p sec_metric_publications%ROWTYPE; direct_input sec_metric_publication_inputs%ROWTYPE;
      authority sec_statement_fact_authorities%ROWTYPE; occurrence sec_statement_occurrence_evidence%ROWTYPE;
      reference sec_statement_report_references%ROWTYPE; source sec_metric_publication_run_sources%ROWTYPE;
      left_p sec_metric_publications%ROWTYPE; right_p sec_metric_publications%ROWTYPE;
      evidence_count integer; bad_count integer; fact metric_facts%ROWTYPE;
      min_ordinal integer; max_ordinal integer; distinct_ordinals integer;
      evidence_raw_ids jsonb; evidence_parse_ids jsonb; evidence_normalization_ids jsonb; evidence_authority_ids jsonb;
      pub sec_metric_publication_runs%ROWTYPE;
    BEGIN
      IF TG_TABLE_NAME='sec_metric_publications' THEN p:=NEW;
      ELSIF TG_TABLE_NAME='sec_metric_publication_inputs' THEN SELECT * INTO p FROM sec_metric_publications WHERE id=NEW.publication_id;
      ELSIF TG_TABLE_NAME='sec_metric_publication_unresolved_inputs' THEN SELECT * INTO p FROM sec_metric_publications WHERE id=NEW.publication_id;
      ELSE RETURN NULL; END IF;
      IF p.id IS NULL THEN RETURN NULL; END IF;
      SELECT * INTO pub FROM sec_metric_publication_runs WHERE id=p.publication_run_id;
      IF p.status='published' AND p.derivation_kind='direct' THEN
        IF jsonb_typeof(p.locator_json)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p.locator_json))<>19
          OR NOT (p.locator_json ?& ARRAY['statement_authority_id','statement_report_reference_id','statement_artifact_id','statement_sha256','filing_summary_artifact_id','filing_summary_sha256','report_artifact_id','report_sha256','occurrence_fact_id','occurrence_semantic_sha256','report_ordinal','occurrence_ordinal','row_ordinal','column_ordinal','locator_json','evidence_locator_json','raw_fact_id','parse_run_id','normalization_id'])
          OR EXISTS (SELECT 1 FROM unnest(ARRAY['statement_authority_id','statement_report_reference_id','statement_artifact_id','filing_summary_artifact_id','report_artifact_id','report_ordinal','occurrence_ordinal','row_ordinal','column_ordinal','raw_fact_id','parse_run_id']) key
            WHERE jsonb_typeof(p.locator_json->key) IS DISTINCT FROM 'number'
              OR NOT ((p.locator_json->>key) ~ '^[1-9][0-9]*$'))
          OR jsonb_typeof(p.locator_json->'normalization_id') NOT IN ('number','null')
          OR (jsonb_typeof(p.locator_json->'normalization_id')='number' AND NOT ((p.locator_json->>'normalization_id') ~ '^[1-9][0-9]*$'))
          OR EXISTS (SELECT 1 FROM unnest(ARRAY['statement_sha256','filing_summary_sha256','report_sha256','occurrence_semantic_sha256']) key
            WHERE jsonb_typeof(p.locator_json->key) IS DISTINCT FROM 'string')
          OR jsonb_typeof(p.locator_json->'occurrence_fact_id') NOT IN ('string','null')
          OR jsonb_typeof(p.locator_json->'locator_json') IS DISTINCT FROM 'object'
          OR jsonb_typeof(p.locator_json->'evidence_locator_json') IS DISTINCT FROM 'object'
        THEN RAISE EXCEPTION 'published direct occurrence provenance shape mismatch'; END IF;
        SELECT * INTO direct_input FROM sec_metric_publication_inputs WHERE publication_id=p.id AND input_role='direct';
        SELECT * INTO source FROM sec_metric_publication_run_sources WHERE id=direct_input.run_source_id;
        SELECT a.* INTO authority FROM sec_statement_fact_authorities a WHERE a.id=(p.locator_json->>'statement_authority_id')::bigint;
        SELECT * INTO occurrence FROM sec_statement_occurrence_evidence WHERE id=authority.statement_occurrence_id;
        SELECT * INTO reference FROM sec_statement_report_references WHERE id=authority.statement_report_reference_id;
        IF direct_input.id IS NULL OR authority.id IS NULL OR authority.raw_fact_id IS DISTINCT FROM direct_input.raw_fact_id
          OR authority.parse_run_id IS DISTINCT FROM source.parse_run_id OR p.source_role IS DISTINCT FROM 'primary_as_filed_actual'
          OR (p.locator_json->>'raw_fact_id')::bigint IS DISTINCT FROM direct_input.raw_fact_id
          OR (p.locator_json->>'parse_run_id')::bigint IS DISTINCT FROM source.parse_run_id
          OR (p.locator_json->>'normalization_id')::bigint IS DISTINCT FROM direct_input.normalization_id
          OR (p.locator_json->>'statement_report_reference_id')::bigint IS DISTINCT FROM authority.statement_report_reference_id
          OR (p.locator_json->>'statement_artifact_id')::bigint IS DISTINCT FROM authority.statement_artifact_id
          OR p.locator_json->>'statement_sha256' IS DISTINCT FROM authority.statement_sha256
          OR p.locator_json->>'occurrence_fact_id' IS DISTINCT FROM authority.occurrence_fact_id
          OR p.locator_json->>'occurrence_semantic_sha256' IS DISTINCT FROM authority.occurrence_semantic_sha256
          OR (p.locator_json->>'report_ordinal')::integer IS DISTINCT FROM authority.report_ordinal
          OR (p.locator_json->>'occurrence_ordinal')::integer IS DISTINCT FROM authority.occurrence_ordinal
          OR (p.locator_json->>'row_ordinal')::integer IS DISTINCT FROM occurrence.row_ordinal
          OR (p.locator_json->>'column_ordinal')::integer IS DISTINCT FROM occurrence.column_ordinal
          OR p.locator_json->'locator_json' IS DISTINCT FROM authority.locator_json
          OR p.locator_json->'evidence_locator_json' IS DISTINCT FROM occurrence.locator_json
          OR (p.locator_json->>'filing_summary_artifact_id')::bigint IS DISTINCT FROM reference.filing_summary_artifact_id
          OR p.locator_json->>'filing_summary_sha256' IS DISTINCT FROM reference.filing_summary_sha256
          OR (p.locator_json->>'report_artifact_id')::bigint IS DISTINCT FROM reference.report_artifact_id
          OR p.locator_json->>'report_sha256' IS DISTINCT FROM reference.report_sha256
        THEN RAISE EXCEPTION 'published direct occurrence provenance mismatch'; END IF;
      ELSIF p.status='published' THEN
        SELECT sp.* INTO left_p FROM sec_metric_publication_inputs i JOIN sec_metric_publications sp ON sp.id=i.source_publication_id WHERE i.publication_id=p.id AND i.input_role='left_operand' AND i.arithmetic_sign=1;
        SELECT sp.* INTO right_p FROM sec_metric_publication_inputs i JOIN sec_metric_publications sp ON sp.id=i.source_publication_id WHERE i.publication_id=p.id AND i.input_role='right_operand' AND i.arithmetic_sign=-1;
        IF p.source_role IS DISTINCT FROM 'derived_actual' OR left_p.id IS NULL OR right_p.id IS NULL
          OR jsonb_typeof(p.locator_json)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p.locator_json))<>2
          OR NOT (p.locator_json ?& ARRAY['derivation_kind','ordered_input_occurrences'])
          OR p.locator_json->>'derivation_kind' IS DISTINCT FROM p.derivation_kind
          OR p.locator_json->'ordered_input_occurrences' IS DISTINCT FROM jsonb_build_array(left_p.locator_json,right_p.locator_json)
          OR p.audit_json->'ordered_input_occurrences' IS DISTINCT FROM jsonb_build_array(left_p.locator_json,right_p.locator_json)
        THEN RAISE EXCEPTION 'published derived occurrence provenance mismatch'; END IF;
      ELSE
        SELECT count(*),min(input_ordinal),max(input_ordinal),count(DISTINCT input_ordinal),
          jsonb_agg(raw_fact_id ORDER BY input_ordinal),jsonb_agg(s.parse_run_id ORDER BY input_ordinal),
          jsonb_agg(normalization_id ORDER BY input_ordinal),jsonb_agg(statement_authority_id ORDER BY input_ordinal)
          INTO evidence_count,min_ordinal,max_ordinal,distinct_ordinals,evidence_raw_ids,evidence_parse_ids,evidence_normalization_ids,evidence_authority_ids
          FROM sec_metric_publication_unresolved_inputs ui JOIN sec_metric_publication_run_sources s ON s.id=ui.run_source_id
          WHERE publication_id=p.id;
        IF evidence_count=0 OR min_ordinal<>1 OR max_ordinal<>evidence_count OR distinct_ordinals<>evidence_count
          OR jsonb_typeof(p.locator_json)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p.locator_json))<>1
          OR NOT (p.locator_json ? 'ordered_input_occurrences')
          OR jsonb_typeof(p.locator_json->'ordered_input_occurrences')<>'array'
          OR jsonb_array_length(p.locator_json->'ordered_input_occurrences')<>evidence_count
          OR jsonb_typeof(p.audit_json->'raw_fact_ids')<>'array' OR p.audit_json->'raw_fact_ids' IS DISTINCT FROM evidence_raw_ids
          OR jsonb_typeof(p.audit_json->'parse_run_ids')<>'array' OR p.audit_json->'parse_run_ids' IS DISTINCT FROM evidence_parse_ids
          OR jsonb_typeof(p.audit_json->'normalization_ids')<>'array' OR p.audit_json->'normalization_ids' IS DISTINCT FROM evidence_normalization_ids
          OR jsonb_typeof(p.audit_json->'statement_authority_ids')<>'array' OR p.audit_json->'statement_authority_ids' IS DISTINCT FROM evidence_authority_ids
        THEN RAISE EXCEPTION 'unresolved occurrence provenance missing'; END IF;
        SELECT count(*) INTO bad_count FROM sec_metric_publication_unresolved_inputs ui
          JOIN sec_metric_publication_run_sources s ON s.id=ui.run_source_id
          JOIN sec_raw_xbrl_facts raw ON raw.id=ui.raw_fact_id
          JOIN sec_financial_parse_runs pr ON pr.id=s.parse_run_id
          JOIN sec_financial_filings filing ON filing.id=pr.filing_id
          JOIN sec_issuer_identities issuer ON issuer.id=filing.issuer_identity_id
          JOIN sec_statement_fact_authorities a ON a.id=ui.statement_authority_id
          JOIN sec_statement_occurrence_evidence o ON o.id=a.statement_occurrence_id
          JOIN sec_statement_report_references r ON r.id=a.statement_report_reference_id
          WHERE ui.publication_id=p.id AND (s.publication_run_id<>p.publication_run_id
            OR s.source_available_at>pub.requested_cutoff OR pr.known_at>pub.requested_cutoff
            OR filing.known_at>pub.requested_cutoff OR a.known_at>pub.requested_cutoff
            OR r.known_at>pub.requested_cutoff OR raw.created_at>pub.requested_cutoff
            OR filing.issuer_identity_id<>pub.issuer_identity_id OR issuer.stock_id<>pub.stock_id
            OR raw.parse_run_id<>s.parse_run_id OR a.raw_fact_id<>ui.raw_fact_id OR a.parse_run_id<>s.parse_run_id
            OR raw.context_id IS DISTINCT FROM p.context_id OR a.context_id IS DISTINCT FROM p.context_id
            OR raw.period_start IS DISTINCT FROM p.period_start_date
            OR coalesce(raw.period_end,raw.period_instant) IS DISTINCT FROM p.period_end_date
            OR a.statement_period_end IS DISTINCT FROM p.period_end_date
            OR a.fiscal_year IS DISTINCT FROM p.fiscal_year
            OR a.fiscal_quarter_ordinal IS DISTINCT FROM p.fiscal_quarter_ordinal
            OR (p.period_basis='instant' AND (raw.period_instant IS NULL OR raw.period_start IS NOT NULL))
            OR (p.period_basis='duration' AND (raw.period_start IS NULL OR raw.period_end IS NULL OR raw.period_instant IS NOT NULL))
            OR NOT EXISTS(SELECT 1 FROM sec_metric_mapping_rule_concepts c
              JOIN sec_metric_mapping_rules mr ON mr.id=c.mapping_rule_id
              JOIN sec_metric_mapping_version_namespaces ns ON ns.mapping_version_id=mr.mapping_version_id
                AND ns.authority=c.namespace_authority
              WHERE c.mapping_rule_id=p.mapping_rule_id
                AND c.local_name=CASE WHEN strpos(raw.concept,':')>0 THEN split_part(raw.concept,':',2) ELSE raw.concept END
                AND ns.namespace_uri=raw.concept_namespace_uri)
            OR (ui.normalization_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM sec_raw_numeric_normalizations n
                WHERE n.id=ui.normalization_id AND n.raw_fact_id=ui.raw_fact_id
                  AND n.mapping_rule_id=p.mapping_rule_id AND n.mapping_version_id=pub.mapping_version_id
                  AND n.created_at<=pub.requested_cutoff))
            OR (ui.normalization_id IS NULL AND EXISTS(SELECT 1 FROM sec_raw_numeric_normalizations n
                WHERE n.raw_fact_id=ui.raw_fact_id AND n.mapping_rule_id=p.mapping_rule_id
                  AND n.mapping_version_id=pub.mapping_version_id AND n.created_at<=pub.requested_cutoff))
            OR (p.reason_code IN ('unresolved_unit','unresolved_currency','unresolved_conflicting_candidates') AND ui.normalization_id IS NULL)
            OR (p.audit_json->>'cutoff')::timestamptz IS DISTINCT FROM pub.requested_cutoff
            OR jsonb_typeof(p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)) IS DISTINCT FROM 'object'
            OR (SELECT count(*) FROM jsonb_object_keys(p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1))) IS DISTINCT FROM 19
            OR NOT (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1) ?& ARRAY['statement_authority_id','statement_report_reference_id','statement_artifact_id','statement_sha256','filing_summary_artifact_id','filing_summary_sha256','report_artifact_id','report_sha256','occurrence_fact_id','occurrence_semantic_sha256','report_ordinal','occurrence_ordinal','row_ordinal','column_ordinal','locator_json','evidence_locator_json','raw_fact_id','parse_run_id','normalization_id'])
            OR EXISTS (SELECT 1 FROM unnest(ARRAY['statement_authority_id','statement_report_reference_id','statement_artifact_id','filing_summary_artifact_id','report_artifact_id','report_ordinal','occurrence_ordinal','row_ordinal','column_ordinal','raw_fact_id','parse_run_id']) key
              WHERE jsonb_typeof(p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->key) IS DISTINCT FROM 'number'
                OR NOT ((p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>key) ~ '^[1-9][0-9]*$'))
            OR jsonb_typeof(p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->'normalization_id') NOT IN ('number','null')
            OR (jsonb_typeof(p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->'normalization_id')='number'
              AND NOT ((p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'normalization_id') ~ '^[1-9][0-9]*$'))
            OR EXISTS (SELECT 1 FROM unnest(ARRAY['statement_sha256','filing_summary_sha256','report_sha256','occurrence_semantic_sha256']) key
              WHERE jsonb_typeof(p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->key) IS DISTINCT FROM 'string')
            OR jsonb_typeof(p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->'occurrence_fact_id') NOT IN ('string','null')
            OR jsonb_typeof(p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->'locator_json') IS DISTINCT FROM 'object'
            OR jsonb_typeof(p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->'evidence_locator_json') IS DISTINCT FROM 'object'
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'raw_fact_id')::bigint IS DISTINCT FROM ui.raw_fact_id
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'parse_run_id')::bigint IS DISTINCT FROM s.parse_run_id
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'normalization_id')::bigint IS DISTINCT FROM ui.normalization_id
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'statement_authority_id')::bigint IS DISTINCT FROM a.id
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'statement_report_reference_id')::bigint IS DISTINCT FROM a.statement_report_reference_id
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'statement_artifact_id')::bigint IS DISTINCT FROM a.statement_artifact_id
            OR p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'statement_sha256' IS DISTINCT FROM a.statement_sha256
            OR p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'occurrence_fact_id' IS DISTINCT FROM a.occurrence_fact_id
            OR p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'occurrence_semantic_sha256' IS DISTINCT FROM a.occurrence_semantic_sha256
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'report_ordinal')::integer IS DISTINCT FROM a.report_ordinal
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'occurrence_ordinal')::integer IS DISTINCT FROM a.occurrence_ordinal
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'row_ordinal')::integer IS DISTINCT FROM o.row_ordinal
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'column_ordinal')::integer IS DISTINCT FROM o.column_ordinal
            OR p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->'locator_json' IS DISTINCT FROM a.locator_json
            OR p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->'evidence_locator_json' IS DISTINCT FROM o.locator_json
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'filing_summary_artifact_id')::bigint IS DISTINCT FROM r.filing_summary_artifact_id
            OR p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'filing_summary_sha256' IS DISTINCT FROM r.filing_summary_sha256
            OR (p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'report_artifact_id')::bigint IS DISTINCT FROM r.report_artifact_id
            OR p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->>'report_sha256' IS DISTINCT FROM r.report_sha256);
        IF bad_count<>0 OR p.audit_json->'ordered_input_occurrences' IS DISTINCT FROM p.locator_json->'ordered_input_occurrences'
        THEN RAISE EXCEPTION 'unresolved occurrence provenance mismatch'; END IF;
      END IF;
      IF p.metric_fact_id IS NOT NULL THEN
        IF fact.id IS NULL THEN SELECT * INTO fact FROM metric_facts WHERE id=p.metric_fact_id; END IF;
        IF (fact.value_json::jsonb->>'publication_run_id') IS DISTINCT FROM p.publication_run_id
          OR (fact.value_json::jsonb->>'decision_id') IS DISTINCT FROM p.id::text
          OR (fact.value_json::jsonb->>'source_role') IS DISTINCT FROM p.source_role
          OR fact.value_json::jsonb->'locator' IS DISTINCT FROM p.locator_json
        THEN RAISE EXCEPTION 'SEC metric fact occurrence provenance mismatch'; END IF;
      END IF;
      RETURN NULL; END $$;
    CREATE CONSTRAINT TRIGGER trg_sec_publication_provenance_publication AFTER INSERT ON sec_metric_publications DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_sec_publication_provenance();
    CREATE CONSTRAINT TRIGGER trg_sec_publication_provenance_input AFTER INSERT ON sec_metric_publication_inputs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_sec_publication_provenance();
    CREATE CONSTRAINT TRIGGER trg_sec_publication_provenance_unresolved AFTER INSERT ON sec_metric_publication_unresolved_inputs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_sec_publication_provenance();
    """


def _unresolved_input_insert_function() -> str:
    return """
    CREATE OR REPLACE FUNCTION guard_sec_publication_unresolved_input_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE p sec_metric_publications%ROWTYPE; pub sec_metric_publication_runs%ROWTYPE;
      s sec_metric_publication_run_sources%ROWTYPE; raw sec_raw_xbrl_facts%ROWTYPE;
      a sec_statement_fact_authorities%ROWTYPE;
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
      SELECT * INTO p FROM sec_metric_publications WHERE id=NEW.publication_id;
      SELECT * INTO pub FROM sec_metric_publication_runs WHERE id=p.publication_run_id;
      SELECT * INTO s FROM sec_metric_publication_run_sources WHERE id=NEW.run_source_id;
      SELECT * INTO raw FROM sec_raw_xbrl_facts WHERE id=NEW.raw_fact_id;
      SELECT * INTO a FROM sec_statement_fact_authorities WHERE id=NEW.statement_authority_id;
      IF p.id IS NULL OR p.status='published' OR pub.id IS NULL
        OR s.publication_run_id<>p.publication_run_id OR s.source_available_at>pub.requested_cutoff
        OR raw.parse_run_id<>s.parse_run_id OR a.raw_fact_id<>raw.id OR a.parse_run_id<>s.parse_run_id
        OR raw.context_id IS DISTINCT FROM p.context_id OR a.context_id IS DISTINCT FROM p.context_id
        OR raw.period_start IS DISTINCT FROM p.period_start_date
        OR coalesce(raw.period_end,raw.period_instant) IS DISTINCT FROM p.period_end_date
        OR a.statement_period_end IS DISTINCT FROM p.period_end_date
        OR a.fiscal_year IS DISTINCT FROM p.fiscal_year
        OR a.fiscal_quarter_ordinal IS DISTINCT FROM p.fiscal_quarter_ordinal
        OR NOT EXISTS(SELECT 1 FROM sec_metric_mapping_rule_concepts c
          JOIN sec_metric_mapping_rules mr ON mr.id=c.mapping_rule_id
          JOIN sec_metric_mapping_version_namespaces ns ON ns.mapping_version_id=mr.mapping_version_id
            AND ns.authority=c.namespace_authority
          WHERE c.mapping_rule_id=p.mapping_rule_id
            AND c.local_name=CASE WHEN strpos(raw.concept,':')>0 THEN split_part(raw.concept,':',2) ELSE raw.concept END
            AND ns.namespace_uri=raw.concept_namespace_uri)
        OR (NEW.normalization_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM sec_raw_numeric_normalizations n
          WHERE n.id=NEW.normalization_id AND n.raw_fact_id=NEW.raw_fact_id
            AND n.mapping_rule_id=p.mapping_rule_id AND n.mapping_version_id=pub.mapping_version_id
            AND n.created_at<=pub.requested_cutoff))
        OR (NEW.normalization_id IS NULL AND EXISTS(SELECT 1 FROM sec_raw_numeric_normalizations n
          WHERE n.raw_fact_id=NEW.raw_fact_id AND n.mapping_rule_id=p.mapping_rule_id
            AND n.mapping_version_id=pub.mapping_version_id AND n.created_at<=pub.requested_cutoff))
        OR (p.reason_code IN ('unresolved_unit','unresolved_currency','unresolved_conflicting_candidates') AND NEW.normalization_id IS NULL)
      THEN RAISE EXCEPTION 'unresolved publication input authority mismatch'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_sec_publication_unresolved_input_insert BEFORE INSERT ON sec_metric_publication_unresolved_inputs
      FOR EACH ROW EXECUTE FUNCTION guard_sec_publication_unresolved_input_insert();
    """
