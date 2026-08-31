"""SEC publication integrity and canonical metric-fact bridge.

Revision ID: 20260901130000
Revises: 20260901120000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260901130000"
down_revision = "20260901120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("metric_facts", "value_numeric", type_=sa.Numeric(38,12), postgresql_using="value_numeric::numeric(38,12)")
    op.alter_column("metric_facts", "user_id", nullable=True)
    op.create_check_constraint("ck_metric_facts_source_owner", "metric_facts", "(source_type='sec' AND user_id IS NULL) OR (source_type<>'sec' AND user_id IS NOT NULL)")
    op.create_check_constraint("ck_metric_facts_sec_source_shape", "metric_facts", "source_type<>'sec' OR (source_document_id IS NULL AND source_ref_id IS NOT NULL AND unit IN ('currency','currency_per_share','shares') AND ((unit IN ('currency','currency_per_share') AND currency ~ '^[A-Z]{3}$') OR (unit='shares' AND currency IS NULL)))")
    op.create_foreign_key("fk_sec_publication_metric_fact", "sec_metric_publications", "metric_facts", ["metric_fact_id"], ["id"], ondelete="RESTRICT", deferrable=True, initially="DEFERRED")
    op.create_index("uq_metric_facts_current_sec_period", "metric_facts", ["stock_id","metric_key","period_type","period_end_date"], unique=True, postgresql_where=sa.text("source_type='sec' AND is_current=true"))
    op.execute(r"""
    CREATE FUNCTION guard_sec_mapping_child_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE parent sec_metric_mapping_versions%ROWTYPE; namespace_exists boolean;
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
      SELECT * INTO parent FROM sec_metric_mapping_versions WHERE id=NEW.mapping_version_id;
      IF parent.id IS NULL OR NEW.spec_sha256<>parent.spec_sha256 THEN RAISE EXCEPTION 'mapping child spec authority mismatch'; END IF;
      IF TG_TABLE_NAME='sec_metric_mapping_version_currencies' AND
         (NEW.registry_id<>parent.currency_registry_id OR NEW.canonical_serialization<>parent.currency_serialization OR NEW.registry_sha256<>parent.currency_sha256)
      THEN RAISE EXCEPTION 'mapping currency registry authority mismatch'; END IF;
      IF TG_TABLE_NAME='sec_metric_mapping_rules' THEN
        SELECT EXISTS(SELECT 1 FROM sec_metric_mapping_version_namespaces n
          WHERE n.mapping_version_id=NEW.mapping_version_id AND n.authority=NEW.concept_namespace_authority)
          INTO namespace_exists;
        IF NOT namespace_exists THEN RAISE EXCEPTION 'mapping rule namespace authority mismatch'; END IF;
      END IF;
      RETURN NEW; END $$;
    CREATE TRIGGER trg_sec_mapping_namespace_guard BEFORE INSERT ON sec_metric_mapping_version_namespaces FOR EACH ROW EXECUTE FUNCTION guard_sec_mapping_child_insert();
    CREATE TRIGGER trg_sec_mapping_currency_guard BEFORE INSERT ON sec_metric_mapping_version_currencies FOR EACH ROW EXECUTE FUNCTION guard_sec_mapping_child_insert();
    CREATE TRIGGER trg_sec_mapping_rule_guard BEFORE INSERT ON sec_metric_mapping_rules FOR EACH ROW EXECUTE FUNCTION guard_sec_mapping_child_insert();

    CREATE FUNCTION guard_sec_publication_run_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE identity sec_issuer_identities%ROWTYPE; mapping sec_metric_mapping_versions%ROWTYPE;
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
      SELECT * INTO identity FROM sec_issuer_identities WHERE id=NEW.issuer_identity_id;
      SELECT * INTO mapping FROM sec_metric_mapping_versions WHERE id=NEW.mapping_version_id;
      IF identity.id IS NULL OR identity.stock_id<>NEW.stock_id OR identity.status<>'reviewed'
         OR identity.effective_from>NEW.requested_cutoff::date OR (identity.effective_to IS NOT NULL AND identity.effective_to<NEW.requested_cutoff::date)
         OR identity.known_at>least(NEW.requested_cutoff,NEW.created_at)
         OR mapping.id IS NULL OR mapping.status<>'approved' OR mapping.effective_from>NEW.requested_cutoff OR mapping.known_at>NEW.requested_cutoff
         OR mapping.id<>'sec-us-gaap-v1' OR mapping.spec_sha256<>'01b828534060e04439103c935842c1a9cf42d3f5a2311934c99bef81bdcc073d'
         OR (SELECT count(*) FROM sec_metric_mapping_version_namespaces WHERE mapping_version_id=mapping.id)<>24
         OR (SELECT count(*) FROM sec_metric_mapping_version_currencies WHERE mapping_version_id=mapping.id)<>4
         OR (SELECT count(*) FROM sec_metric_mapping_rules WHERE mapping_version_id=mapping.id)<>21
      THEN RAISE EXCEPTION 'publication run authority mismatch'; END IF;
      RETURN NEW; END $$;
    CREATE TRIGGER trg_sec_publication_run_guard BEFORE INSERT ON sec_metric_publication_runs FOR EACH ROW EXECUTE FUNCTION guard_sec_publication_run_insert();

    CREATE FUNCTION guard_sec_publication_decision_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE run sec_metric_publication_runs%ROWTYPE; rule sec_metric_mapping_rules%ROWTYPE;
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.known_at:=NEW.created_at; NEW.created_txid:=txid_current();
      SELECT * INTO run FROM sec_metric_publication_runs WHERE id=NEW.publication_run_id;
      SELECT * INTO rule FROM sec_metric_mapping_rules WHERE id=NEW.mapping_rule_id;
      IF run.id IS NULL OR NEW.stock_id<>run.stock_id OR rule.id IS NULL OR rule.mapping_version_id<>run.mapping_version_id
         OR NEW.metric_key<>rule.metric_key OR NEW.unit IS DISTINCT FROM rule.target_unit
         OR NOT ((NEW.fact_nature='actual' AND NEW.derivation_kind='direct') OR
                 (NEW.fact_nature='derived_actual' AND NEW.derivation_kind IN ('current_ytd_minus_prior_ytd','fiscal_year_minus_nine_month_ytd')) OR
                 (NEW.status<>'published' AND NEW.derivation_kind='unresolved'))
      THEN RAISE EXCEPTION 'publication decision authority mismatch'; END IF;
      RETURN NEW; END $$;
    CREATE TRIGGER trg_sec_publication_decision_guard BEFORE INSERT ON sec_metric_publications FOR EACH ROW EXECUTE FUNCTION guard_sec_publication_decision_insert();

    CREATE FUNCTION compute_sec_numeric_v1(raw sec_raw_xbrl_facts) RETURNS numeric LANGUAGE plpgsql IMMUTABLE STRICT AS $$
    DECLARE lexical text; canonical text; unsigned text; integer_part text; fraction_part text; result numeric; negative boolean:=false; format text:=coalesce(raw.transformation_format,'standalone-canonical-xml'); scale_value integer:=coalesce(raw.scale,0); integer_digits integer; fraction_digits integer;
    BEGIN
      -- Bounds precede every regex/cast/power operation. 256 bytes comfortably
      -- exceeds NUMERIC(38,12) plus retained grouping/whitespace syntax.
      IF raw.is_nil OR raw.raw_value IS NULL OR octet_length(raw.raw_value)>256 OR char_length(raw.raw_value)>256
         OR octet_length(format)>120 OR char_length(format)>120 OR octet_length(coalesce(raw.sign,''))>1
         OR scale_value NOT BETWEEN -30 AND 30 THEN RAISE EXCEPTION 'unsupported SEC numeric normalization'; END IF;
      lexical:=btrim(translate(raw.raw_value, E'\u00a0\u202f\u2007', '   '));
      IF lexical='' OR lower(lexical) IN ('nan','infinity','-infinity','inf','-inf') THEN RAISE EXCEPTION 'unsupported SEC numeric normalization'; END IF;
      IF left(lexical,1)='(' AND right(lexical,1)=')' THEN negative:=true; lexical:=substr(lexical,2,length(lexical)-2); END IF;
      IF format='standalone-canonical-xml' THEN
        IF lexical !~ '^[+-]?[0-9]+(\.[0-9]+)?$' THEN RAISE EXCEPTION 'unsupported SEC numeric normalization'; END IF; canonical:=lexical;
      ELSIF format IN ('ixt:num-dot-decimal','ixt:numdotdecimal') THEN
        IF lexical !~ '^[0-9]{1,3}(,[0-9]{3})*(\.[0-9]+)?$' AND lexical !~ '^[0-9]+(\.[0-9]+)?$' THEN RAISE EXCEPTION 'unsupported SEC numeric normalization'; END IF; canonical:=replace(lexical,',','');
      ELSIF format IN ('ixt:num-comma-decimal','ixt:numcommadecimal') THEN
        IF lexical !~ '^[0-9]{1,3}(\.[0-9]{3})*(,[0-9]+)?$' AND lexical !~ '^[0-9]+(,[0-9]+)?$' THEN RAISE EXCEPTION 'unsupported SEC numeric normalization'; END IF; canonical:=replace(replace(lexical,'.',''),',','.');
      ELSIF format IN ('ixt:fixed-zero','ixt:zerodash') THEN
        IF lexical NOT IN ('-','0') THEN RAISE EXCEPTION 'unsupported SEC numeric normalization'; END IF; canonical:='0';
      ELSE RAISE EXCEPTION 'unsupported SEC numeric normalization'; END IF;
      unsigned:=canonical; IF left(unsigned,1) IN ('+','-') THEN unsigned:=substr(unsigned,2); END IF;
      integer_part:=split_part(unsigned,'.',1); fraction_part:=CASE WHEN strpos(unsigned,'.')>0 THEN split_part(unsigned,'.',2) ELSE '' END;
      integer_digits:=length(ltrim(integer_part,'0')); fraction_digits:=length(rtrim(fraction_part,'0'));
      IF length(integer_part)>64 OR length(fraction_part)>64 OR greatest(integer_digits+scale_value,0)>26 OR greatest(fraction_digits-scale_value,0)>12
      THEN RAISE EXCEPTION 'SEC numeric normalization exceeds exact NUMERIC(38,12)'; END IF;
      result:=canonical::numeric;
      IF negative THEN result:=-result; END IF;
      IF negative AND raw.sign='-' THEN RAISE EXCEPTION 'unsupported SEC numeric normalization'; END IF;
      IF raw.sign='-' THEN result:=-result; ELSIF raw.sign IS NOT NULL AND raw.sign NOT IN ('','+') THEN RAISE EXCEPTION 'unsupported SEC numeric normalization'; END IF;
      result:=result*power(10::numeric,scale_value);
      IF result::numeric(38,12)<>result THEN RAISE EXCEPTION 'SEC numeric normalization exceeds exact NUMERIC(38,12)'; END IF;
      RETURN result::numeric(38,12);
    EXCEPTION WHEN numeric_value_out_of_range OR invalid_text_representation THEN RAISE EXCEPTION 'unsupported SEC numeric normalization'; END $$;

    CREATE FUNCTION guard_sec_raw_numeric_normalization_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE raw sec_raw_xbrl_facts%ROWTYPE; rule sec_metric_mapping_rules%ROWTYPE; computed numeric(38,12); requested numeric(38,12); digest_value text;
    BEGIN
      requested:=NEW.normalized_value; SELECT * INTO raw FROM sec_raw_xbrl_facts WHERE id=NEW.raw_fact_id; SELECT * INTO rule FROM sec_metric_mapping_rules WHERE id=NEW.mapping_rule_id;
      IF raw.id IS NULL OR rule.id IS NULL OR rule.mapping_version_id<>NEW.mapping_version_id OR NEW.mapping_version_id<>'sec-us-gaap-v1' OR NEW.normalization_version<>'sec_numeric_v1' THEN RAISE EXCEPTION 'numeric normalization authority mismatch'; END IF;
      computed:=compute_sec_numeric_v1(raw);
      IF requested IS DISTINCT FROM computed THEN RAISE EXCEPTION 'caller numeric normalization mismatch'; END IF;
      digest_value:=encode(digest(concat_ws(E'\x1f',raw.raw_value,raw.transformation_format,raw.sign,raw.scale::text,raw.is_nil::text,raw.unit_numerator_json::text,raw.unit_denominator_json::text),'sha256'),'hex');
      NEW.normalized_value:=computed; NEW.raw_semantic_sha256:=digest_value; NEW.transformation_identity:=coalesce(raw.transformation_format,'standalone-canonical-xml'); NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current(); RETURN NEW;
    END $$;
    CREATE TRIGGER trg_sec_raw_numeric_normalization_guard BEFORE INSERT ON sec_raw_numeric_normalizations FOR EACH ROW EXECUTE FUNCTION guard_sec_raw_numeric_normalization_insert();

    CREATE FUNCTION guard_sec_publication_source_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE pub sec_metric_publication_runs%ROWTYPE; parse sec_financial_parse_runs%ROWTYPE; filing sec_financial_filings%ROWTYPE; available timestamptz;
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
      SELECT * INTO pub FROM sec_metric_publication_runs WHERE id=NEW.publication_run_id;
      SELECT * INTO parse FROM sec_financial_parse_runs WHERE id=NEW.parse_run_id;
      SELECT * INTO filing FROM sec_financial_filings WHERE id=parse.filing_id;
      SELECT available_at INTO available FROM sec_financial_lineage_availabilities WHERE operation_id=parse.operation_id;
      IF pub.id IS NULL OR parse.status<>'succeeded' OR parse.filing_id<>NEW.filing_id OR filing.accession_no<>NEW.accession_no
         OR filing.issuer_identity_id<>pub.issuer_identity_id OR parse.parser_version<>NEW.parser_version
         OR parse.input_manifest_hash<>NEW.input_manifest_hash OR available IS NULL OR available>pub.requested_cutoff OR available<>NEW.source_available_at
         OR parse.known_at>pub.requested_cutoff THEN RAISE EXCEPTION 'invalid publication parse authority source'; END IF;
      RETURN NEW; END $$;
    CREATE TRIGGER trg_sec_publication_source_guard BEFORE INSERT ON sec_metric_publication_run_sources FOR EACH ROW EXECUTE FUNCTION guard_sec_publication_source_insert();

    CREATE FUNCTION guard_sec_publication_input_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE decision sec_metric_publications%ROWTYPE; source_run text; source_parse bigint; raw sec_raw_xbrl_facts%ROWTYPE; source_decision sec_metric_publications%ROWTYPE; rule sec_metric_mapping_rules%ROWTYPE; normalization sec_raw_numeric_normalizations%ROWTYPE;
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
      SELECT * INTO decision FROM sec_metric_publications WHERE id=NEW.publication_id;
      SELECT * INTO rule FROM sec_metric_mapping_rules WHERE id=decision.mapping_rule_id;
      IF decision.id IS NULL OR decision.status<>'published' THEN RAISE EXCEPTION 'only published decisions may own lineage inputs'; END IF;
      IF NEW.input_role='direct' THEN
      SELECT publication_run_id,parse_run_id INTO source_run,source_parse FROM sec_metric_publication_run_sources WHERE id=NEW.run_source_id;
      SELECT * INTO raw FROM sec_raw_xbrl_facts WHERE id=NEW.raw_fact_id;
      SELECT * INTO normalization FROM sec_raw_numeric_normalizations WHERE id=NEW.normalization_id;
      IF decision.derivation_kind<>'direct' OR source_run<>decision.publication_run_id OR raw.id IS NULL OR raw.parse_run_id<>source_parse
         OR normalization.id IS NULL OR normalization.raw_fact_id<>raw.id OR normalization.mapping_rule_id<>decision.mapping_rule_id OR normalization.mapping_version_id<>rule.mapping_version_id OR normalization.normalized_value<>decision.value_numeric
         OR raw.context_id IS DISTINCT FROM decision.context_id OR raw.period_start IS DISTINCT FROM decision.period_start_date
         OR coalesce(raw.period_end,raw.period_instant) IS DISTINCT FROM decision.period_end_date
         OR encode(digest(coalesce(raw.dimensions_structured_json,'[]'::jsonb)::text,'sha256'),'hex')<>decision.dimensions_sha256
         OR NOT EXISTS(SELECT 1 FROM sec_metric_mapping_version_namespaces n WHERE n.mapping_version_id=rule.mapping_version_id AND n.authority=rule.concept_namespace_authority AND n.namespace_uri=raw.concept_namespace_uri)
         OR NOT (rule.metadata_json->'ordered_concepts' ? CASE WHEN strpos(raw.concept,':')>0 THEN split_part(raw.concept,':',2) ELSE raw.concept END)
         OR (decision.period_basis='instant' AND (raw.period_instant IS NULL OR raw.period_start IS NOT NULL))
         OR (decision.period_basis='duration' AND (raw.period_start IS NULL OR raw.period_end IS NULL))
         OR (decision.unit IN ('currency','currency_per_share') AND NOT coalesce((
              jsonb_array_length(raw.unit_numerator_json)=1 AND raw.unit_numerator_json->0->>'namespace_uri'='http://www.xbrl.org/2003/iso4217'
              AND raw.unit_numerator_json->0->>'local_name'=decision.currency
              AND ((decision.unit='currency' AND jsonb_array_length(raw.unit_denominator_json)=0) OR
                   (decision.unit='currency_per_share' AND jsonb_array_length(raw.unit_denominator_json)=1 AND raw.unit_denominator_json->0->>'namespace_uri'='http://www.xbrl.org/2003/instance' AND raw.unit_denominator_json->0->>'local_name'='shares'))),false))
         OR (decision.unit='shares' AND NOT coalesce((jsonb_array_length(raw.unit_numerator_json)=1 AND raw.unit_numerator_json->0->>'namespace_uri'='http://www.xbrl.org/2003/instance' AND raw.unit_numerator_json->0->>'local_name'='shares' AND jsonb_array_length(raw.unit_denominator_json)=0),false))
      THEN RAISE EXCEPTION 'direct publication input outside exact raw authority'; END IF;
      ELSE
        SELECT * INTO source_decision FROM sec_metric_publications WHERE id=NEW.source_publication_id;
        IF decision.derivation_kind NOT IN ('current_ytd_minus_prior_ytd','fiscal_year_minus_nine_month_ytd') OR source_decision.id IS NULL
           OR source_decision.publication_run_id<>decision.publication_run_id OR source_decision.status<>'published' OR source_decision.derivation_kind<>'direct'
           OR source_decision.stock_id<>decision.stock_id OR source_decision.metric_key<>decision.metric_key OR source_decision.mapping_rule_id<>decision.mapping_rule_id
           OR source_decision.unit<>decision.unit OR source_decision.currency IS DISTINCT FROM decision.currency
           OR source_decision.context_id<>decision.context_id OR source_decision.dimensions_sha256<>decision.dimensions_sha256
           OR source_decision.fiscal_year<>decision.fiscal_year
        THEN RAISE EXCEPTION 'derived publication input outside compatible direct authority'; END IF;
      END IF;
      RETURN NEW; END $$;
    CREATE TRIGGER trg_sec_publication_input_guard BEFORE INSERT ON sec_metric_publication_inputs FOR EACH ROW EXECUTE FUNCTION guard_sec_publication_input_insert();

    CREATE FUNCTION validate_sec_publication_atomic_shape() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE decision sec_metric_publications%ROWTYPE; fact metric_facts%ROWTYPE; input_count integer; input_sum numeric(38,12); direct_count integer; left_decision sec_metric_publications%ROWTYPE; right_decision sec_metric_publications%ROWTYPE;
    BEGIN
      IF TG_TABLE_NAME='metric_facts' THEN
        IF NEW.source_type='sec' THEN
          SELECT * INTO decision FROM sec_metric_publications WHERE id=NEW.source_ref_id;
          IF decision.id IS NULL OR decision.status<>'published' OR decision.metric_fact_id IS DISTINCT FROM NEW.id
             OR decision.stock_id<>NEW.stock_id OR decision.metric_key<>NEW.metric_key OR decision.period_type<>NEW.period_type
             OR decision.period_end_date<>NEW.period_end_date OR decision.value_numeric<>NEW.value_numeric
             OR decision.unit<>NEW.unit OR decision.currency IS DISTINCT FROM NEW.currency THEN RAISE EXCEPTION 'SEC fact publication reciprocity mismatch'; END IF;
        END IF;
      ELSE
        SELECT count(*),sum(i.arithmetic_sign*s.value_numeric),count(*) FILTER (WHERE i.input_role='direct')
          INTO input_count,input_sum,direct_count FROM sec_metric_publication_inputs i LEFT JOIN sec_metric_publications s ON s.id=i.source_publication_id WHERE i.publication_id=NEW.id;
        SELECT s.* INTO left_decision FROM sec_metric_publication_inputs i JOIN sec_metric_publications s ON s.id=i.source_publication_id WHERE i.publication_id=NEW.id AND i.input_role='left_operand';
        SELECT s.* INTO right_decision FROM sec_metric_publication_inputs i JOIN sec_metric_publications s ON s.id=i.source_publication_id WHERE i.publication_id=NEW.id AND i.input_role='right_operand';
        IF NEW.status='published' AND (NEW.metric_fact_id IS NULL OR input_count<1) THEN RAISE EXCEPTION 'published decision requires fact and exact inputs'; END IF;
        IF NEW.status='published' AND NEW.fact_nature='actual' AND
           (NEW.derivation_kind<>'direct' OR input_count<>1 OR direct_count<>1) THEN RAISE EXCEPTION 'direct publication arithmetic authority mismatch'; END IF;
        IF NEW.status='published' AND NEW.fact_nature='derived_actual' AND
           (NEW.derivation_kind NOT IN ('current_ytd_minus_prior_ytd','fiscal_year_minus_nine_month_ytd') OR input_count<>2 OR direct_count<>0 OR input_sum IS NULL OR input_sum<>NEW.value_numeric
            OR left_decision.id IS NULL OR right_decision.id IS NULL
            OR NEW.period_type<>'Q' OR NEW.period_basis<>'duration' OR NEW.fiscal_quarter_ordinal IS NULL
            OR NEW.period_start_date IS NULL OR NEW.period_end_date-NEW.period_start_date NOT BETWEEN 70 AND 110
            OR (NEW.derivation_kind='current_ytd_minus_prior_ytd' AND NOT (
                 NEW.fiscal_quarter_ordinal IN (2,3) AND left_decision.period_type='YTD' AND left_decision.fiscal_quarter_ordinal=NEW.fiscal_quarter_ordinal
                 AND right_decision.period_type='YTD' AND right_decision.fiscal_quarter_ordinal=NEW.fiscal_quarter_ordinal-1
                 AND left_decision.period_start_date=right_decision.period_start_date
                 AND left_decision.period_end_date=NEW.period_end_date AND right_decision.period_end_date<left_decision.period_end_date))
            OR (NEW.derivation_kind='fiscal_year_minus_nine_month_ytd' AND NOT (
                 NEW.fiscal_quarter_ordinal=4 AND left_decision.period_type='FY' AND left_decision.fiscal_quarter_ordinal IS NULL
                 AND right_decision.period_type='YTD' AND right_decision.fiscal_quarter_ordinal=3
                 AND left_decision.period_start_date=right_decision.period_start_date
                 AND left_decision.period_end_date=NEW.period_end_date AND right_decision.period_end_date<left_decision.period_end_date)))
           THEN RAISE EXCEPTION 'derived publication arithmetic authority mismatch'; END IF;
        IF NEW.status<>'published' AND NEW.metric_fact_id IS NOT NULL THEN RAISE EXCEPTION 'unresolved decision cannot reference fact'; END IF;
        IF NEW.status<>'published' AND input_count<>0 THEN RAISE EXCEPTION 'unresolved decision cannot own lineage inputs'; END IF;
      END IF;
      RETURN NULL; END $$;
    CREATE CONSTRAINT TRIGGER trg_metric_fact_sec_reciprocal AFTER INSERT OR UPDATE ON metric_facts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_sec_publication_atomic_shape();
    CREATE CONSTRAINT TRIGGER trg_sec_publication_reciprocal AFTER INSERT OR UPDATE ON sec_metric_publications DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_sec_publication_atomic_shape();

    CREATE FUNCTION guard_sec_metric_fact_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF OLD.source_type='sec' AND NOT (TG_OP='UPDATE' AND OLD.is_current=true AND NEW.is_current=false
        AND ROW(OLD.id,OLD.user_id,OLD.stock_id,OLD.metric_key,OLD.value_json,OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,OLD.period,OLD.period_type,OLD.period_end_date,OLD.as_of_date,OLD.source_document_id,OLD.source_type,OLD.source_ref_id,OLD.created_at)
          IS NOT DISTINCT FROM ROW(NEW.id,NEW.user_id,NEW.stock_id,NEW.metric_key,NEW.value_json,NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,NEW.period,NEW.period_type,NEW.period_end_date,NEW.as_of_date,NEW.source_document_id,NEW.source_type,NEW.source_ref_id,NEW.created_at))
      THEN RAISE EXCEPTION 'SEC metric fact is append-only except current demotion'; END IF; RETURN NEW; END $$;
    CREATE TRIGGER trg_sec_metric_fact_mutation BEFORE UPDATE OR DELETE ON metric_facts FOR EACH ROW EXECUTE FUNCTION guard_sec_metric_fact_mutation();

    CREATE FUNCTION stamp_sec_publication_availability() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE pub sec_metric_publication_runs%ROWTYPE; source_count integer; decision_count integer;
    BEGIN
      SELECT * INTO pub FROM sec_metric_publication_runs WHERE id=NEW.publication_run_id FOR UPDATE;
      IF pub.id IS NULL OR pub.created_txid=txid_current() OR pub.status<>'succeeded' THEN RAISE EXCEPTION 'publication availability requires committed succeeded run'; END IF;
      SELECT count(*) INTO source_count FROM sec_metric_publication_run_sources WHERE publication_run_id=pub.id;
      SELECT count(*) INTO decision_count FROM sec_metric_publications WHERE publication_run_id=pub.id;
      IF source_count<1 OR decision_count<>pub.published_count+pub.unresolved_count+pub.rejected_count THEN RAISE EXCEPTION 'publication terminal counts or sources incomplete'; END IF;
      IF EXISTS(SELECT 1 FROM generate_series(1,source_count) n WHERE NOT EXISTS(SELECT 1 FROM sec_metric_publication_run_sources s WHERE s.publication_run_id=pub.id AND s.source_ordinal=n)) THEN RAISE EXCEPTION 'publication sources must be gapless'; END IF;
      NEW.available_at:=clock_timestamp(); NEW.finalized_txid:=txid_current(); RETURN NEW; END $$;
    CREATE TRIGGER trg_sec_publication_availability_guard BEFORE INSERT ON sec_metric_publication_availabilities FOR EACH ROW EXECUTE FUNCTION stamp_sec_publication_availability();
    """)


def downgrade() -> None:
    connection=op.get_bind()
    connection.execute(sa.text("LOCK TABLE metric_facts, sec_metric_publications, sec_raw_numeric_normalizations IN SHARE ROW EXCLUSIVE MODE"))
    if connection.execute(sa.text("SELECT (SELECT count(*) FROM metric_facts WHERE source_type='sec' OR user_id IS NULL OR (value_numeric IS NOT NULL AND value_numeric::double precision::numeric(38,12)<>value_numeric))+(SELECT count(*) FROM sec_raw_numeric_normalizations)" )).scalar_one():
        raise RuntimeError("cannot downgrade SEC/shared-owner/precision-sensitive metric facts")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_publication_availability_guard ON sec_metric_publication_availabilities; DROP FUNCTION IF EXISTS stamp_sec_publication_availability();")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_publication_decision_guard ON sec_metric_publications; DROP FUNCTION IF EXISTS guard_sec_publication_decision_insert(); DROP TRIGGER IF EXISTS trg_sec_publication_run_guard ON sec_metric_publication_runs; DROP FUNCTION IF EXISTS guard_sec_publication_run_insert();")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_raw_numeric_normalization_guard ON sec_raw_numeric_normalizations; DROP FUNCTION IF EXISTS guard_sec_raw_numeric_normalization_insert(); DROP FUNCTION IF EXISTS compute_sec_numeric_v1(sec_raw_xbrl_facts);")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_metric_fact_mutation ON metric_facts; DROP FUNCTION IF EXISTS guard_sec_metric_fact_mutation();")
    op.execute("DROP TRIGGER IF EXISTS trg_metric_fact_sec_reciprocal ON metric_facts; DROP TRIGGER IF EXISTS trg_sec_publication_reciprocal ON sec_metric_publications; DROP FUNCTION IF EXISTS validate_sec_publication_atomic_shape();")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_publication_input_guard ON sec_metric_publication_inputs; DROP FUNCTION IF EXISTS guard_sec_publication_input_insert();")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_publication_source_guard ON sec_metric_publication_run_sources; DROP FUNCTION IF EXISTS guard_sec_publication_source_insert();")
    op.execute("DROP TRIGGER IF EXISTS trg_sec_mapping_namespace_guard ON sec_metric_mapping_version_namespaces; DROP TRIGGER IF EXISTS trg_sec_mapping_currency_guard ON sec_metric_mapping_version_currencies; DROP TRIGGER IF EXISTS trg_sec_mapping_rule_guard ON sec_metric_mapping_rules; DROP FUNCTION IF EXISTS guard_sec_mapping_child_insert();")
    op.drop_index("uq_metric_facts_current_sec_period", table_name="metric_facts")
    op.drop_constraint("fk_sec_publication_metric_fact", "sec_metric_publications", type_="foreignkey")
    op.drop_constraint("ck_metric_facts_sec_source_shape", "metric_facts", type_="check")
    op.drop_constraint("ck_metric_facts_source_owner", "metric_facts", type_="check")
    op.alter_column("metric_facts","user_id",nullable=False)
    op.alter_column("metric_facts","value_numeric",type_=sa.Float(),postgresql_using="value_numeric::double precision")
