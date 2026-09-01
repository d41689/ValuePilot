"""Authorize exact generated SEC statement-to-instance occurrence lineage.

Revision ID: 20260901210000
Revises: 20260901200000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901210000"
down_revision = "20260901200000"
branch_labels = None
depends_on = None


def _replace_function_source(functions: list[str], old: str, new: str) -> None:
    names = ",".join(repr(name) for name in functions)
    old_sql = "'" + old.replace("'", "''") + "'"
    new_sql = "'" + new.replace("'", "''") + "'"
    op.execute(
        f"""
        DO $$
        DECLARE function_name text; definition text;
        BEGIN
          FOREACH function_name IN ARRAY ARRAY[{names}] LOOP
            SELECT pg_get_functiondef(p.oid) INTO definition
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname=current_schema() AND p.proname=function_name;
            IF definition IS NULL OR position({old_sql} in definition)=0 THEN
              RAISE EXCEPTION 'parser guard function source mismatch: %', function_name;
            END IF;
            EXECUTE replace(definition, {old_sql}, {new_sql});
          END LOOP;
        END $$;
        """
    )


def _occurrence_guard(*, generated: bool) -> str:
    report_xml_source = (
        "CASE WHEN run.parser_version='xbrl-lineage-v2.2' "
        "THEN sec_statement_report_xml_text(reference.report_content) "
        "ELSE convert_from(reference.report_content,'UTF8') END"
        if generated
        else "convert_from(reference.report_content,'UTF8')"
    )
    generated_branch = """
      SELECT * INTO run FROM sec_financial_parse_runs WHERE id=NEW.parse_run_id;
      IF run.parser_version='xbrl-lineage-v2.2'
         AND lower(reference.filename) NOT LIKE '%.xml' THEN
        SELECT count(*) INTO header_date_matches
        FROM regexp_matches(
          NEW.header_raw,
          '(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[.]?[[:space:]]+[0-9]{1,2},?[[:space:]]+[0-9]{4}',
          'gi'
        );
        IF NEW.locator_json->>'kind'<>'sec_generated_statement_html_v2'
           OR jsonb_typeof(NEW.locator_json->'row')<>'number'
           OR jsonb_typeof(NEW.locator_json->'column')<>'number'
           OR (NEW.locator_json->>'row')::integer<>NEW.row_ordinal
           OR (NEW.locator_json->>'column')::integer<>NEW.column_ordinal
           OR NEW.locator_json->>'fact_id' IS DISTINCT FROM NEW.fact_id
           OR btrim(reference.statement_role)=''
           OR NEW.locator_json->>'statement_role' IS DISTINCT FROM reference.statement_role
           OR coalesce(NEW.locator_json->>'display_value','')=''
           OR coalesce(NEW.locator_json->>'row_label','')=''
           OR coalesce(NEW.locator_json->>'preferred_label_role','')=''
           OR coalesce(NEW.locator_json->>'presentation_order','') !~ '^[0-9]+(?:[.][0-9]+)?$'
           OR (NEW.locator_json->>'presentation_order')::numeric<=0
           OR coalesce(NEW.locator_json->>'scale_multiplier','') !~ '^[0-9]+(?:[.][0-9]+)?$'
           OR (NEW.locator_json->>'scale_multiplier')::numeric<=0
           OR NEW.locator_json->>'period_start' IS DISTINCT FROM coalesce(fact.period_start::text,'')
           OR NEW.locator_json->>'period_end' IS DISTINCT FROM coalesce(fact.period_end::text,fact.period_instant::text,'')
           OR NEW.locator_json->'dimensions' IS DISTINCT FROM fact.dimensions_structured_json
           OR NEW.locator_json->>'decimals' IS DISTINCT FROM fact.decimals
           OR coalesce(NEW.locator_json->>'dimensions_sha256','') !~ '^[0-9a-f]{64}$'
           OR coalesce(NEW.locator_json->>'presentation_sha256','') !~ '^[0-9a-f]{64}$'
           OR coalesce(NEW.locator_json->>'label_sha256','') !~ '^[0-9a-f]{64}$'
           OR jsonb_typeof(NEW.locator_json->'presentation_artifact_id')<>'number'
           OR jsonb_typeof(NEW.locator_json->'label_artifact_id')<>'number'
           OR NEW.locator_json->>'canonical_duplicate_rule'<>'lowest_raw_fact_id_for_exact_identity_v1'
           OR jsonb_typeof(NEW.locator_json->'equivalent_raw_fact_ids')<>'array'
           OR coalesce(NEW.locator_json->>'onclick','')=''
           OR coalesce(NEW.locator_json->>'onclick_sha256','') !~ '^[0-9a-f]{64}$'
           OR coalesce(NEW.locator_json->>'onclick_attribute','')=''
           OR coalesce(NEW.locator_json->>'onclick_attribute_sha256','') !~ '^[0-9a-f]{64}$'
           OR coalesce(NEW.locator_json->>'anchor_start_tag','')=''
           OR coalesce(NEW.locator_json->>'anchor_start_tag_sha256','') !~ '^[0-9a-f]{64}$'
           OR header_date_matches<>1
           OR encode(sha256(convert_to(NEW.locator_json->>'onclick','UTF8')),'hex')
                <>NEW.locator_json->>'onclick_sha256'
           OR encode(sha256(convert_to(NEW.locator_json->>'onclick_attribute','UTF8')),'hex')
                <>NEW.locator_json->>'onclick_attribute_sha256'
           OR encode(sha256(convert_to(NEW.locator_json->>'anchor_start_tag','UTF8')),'hex')
                <>NEW.locator_json->>'anchor_start_tag_sha256'
           OR lower(left(btrim(NEW.locator_json->>'anchor_start_tag'),2))<>'<a'
           OR right(btrim(NEW.locator_json->>'anchor_start_tag'),1)<>'>'
           OR (SELECT count(*) FROM regexp_matches(
                NEW.locator_json->>'anchor_start_tag',
                '(^|[[:space:]])onclick[[:space:]]*=', 'gi'))<>1
           OR position(NEW.locator_json->>'onclick_attribute' in
                NEW.locator_json->>'anchor_start_tag')=0
           OR position(NEW.locator_json->>'onclick' in
                NEW.locator_json->>'onclick_attribute')=0
           OR length(lower(NEW.locator_json->>'onclick'))-
              length(replace(lower(NEW.locator_json->>'onclick'),'show.showar(',''))
              <>length('show.showar(')
           OR NEW.locator_json->>'onclick' !~
                '^[[:space:]]*(top[.])?Show[.]showAR[(][[:space:]]*this[[:space:]]*,[[:space:]]*[''\"]defref_[A-Za-z0-9_-]+[''\"][[:space:]]*,[[:space:]]*window[[:space:]]*[)][[:space:]]*;?[[:space:]]*$'
        THEN RAISE EXCEPTION 'generated statement occurrence locator mismatch'; END IF;

        SELECT jsonb_agg(candidate.id ORDER BY candidate.id) INTO equivalent_ids
        FROM sec_raw_xbrl_facts candidate
        WHERE candidate.parse_run_id=fact.parse_run_id
          AND candidate.context_id IS NOT DISTINCT FROM fact.context_id
          AND candidate.concept=fact.concept
          AND btrim(regexp_replace(coalesce(candidate.raw_value,''),'\\s+',' ','g'))=
              btrim(regexp_replace(coalesce(fact.raw_value,''),'\\s+',' ','g'))
          AND candidate.unit_id IS NOT DISTINCT FROM fact.unit_id
          AND candidate.period_start IS NOT DISTINCT FROM fact.period_start
          AND candidate.period_end IS NOT DISTINCT FROM fact.period_end
          AND candidate.period_instant IS NOT DISTINCT FROM fact.period_instant
          AND candidate.dimensions_structured_json=fact.dimensions_structured_json
          AND candidate.unit_numerator_json=fact.unit_numerator_json
          AND candidate.unit_denominator_json=fact.unit_denominator_json
          AND candidate.decimals IS NOT DISTINCT FROM fact.decimals
          AND candidate.scale IS NOT DISTINCT FROM fact.scale
          AND candidate.sign IS NOT DISTINCT FROM fact.sign
          AND NOT candidate.is_nil
          AND (candidate.locator_json->>'locator_type' IS DISTINCT FROM 'inline_xbrl_html'
               OR (jsonb_typeof(candidate.locator_json->'is_hidden')='boolean'
                   AND NOT (candidate.locator_json->>'is_hidden')::boolean));
        IF equivalent_ids IS DISTINCT FROM NEW.locator_json->'equivalent_raw_fact_ids'
           OR (NEW.locator_json->'equivalent_raw_fact_ids'->>0)::bigint<>NEW.raw_fact_id
        THEN RAISE EXCEPTION 'generated statement canonical duplicate identity mismatch'; END IF;

        SELECT * INTO presentation FROM sec_filing_artifacts
         WHERE id=(NEW.locator_json->>'presentation_artifact_id')::bigint;
        SELECT * INTO label_artifact FROM sec_filing_artifacts
         WHERE id=(NEW.locator_json->>'label_artifact_id')::bigint;
        IF presentation.id IS NULL OR label_artifact.id IS NULL
           OR presentation.filing_id<>run.filing_id OR label_artifact.filing_id<>run.filing_id
           OR presentation.state<>'retained' OR label_artifact.state<>'retained'
           OR lower(presentation.filename) NOT LIKE '%\\_pre.xml' ESCAPE '\\'
           OR lower(label_artifact.filename) NOT LIKE '%\\_lab.xml' ESCAPE '\\'
           OR presentation.sha256 IS DISTINCT FROM NEW.locator_json->>'presentation_sha256'
           OR label_artifact.sha256 IS DISTINCT FROM NEW.locator_json->>'label_sha256'
           OR NOT EXISTS (SELECT 1 FROM sec_financial_parse_run_artifacts
                WHERE parse_run_id=run.id AND artifact_id=presentation.id)
           OR NOT EXISTS (SELECT 1 FROM sec_financial_parse_run_artifacts
                WHERE parse_run_id=run.id AND artifact_id=label_artifact.id)
        THEN RAISE EXCEPTION 'generated statement linkbase lineage mismatch'; END IF;

        report_text:=convert_from(reference.report_content,'UTF8');
        concept_token:='defref_'||regexp_replace(NEW.concept,':','_');
        IF position(concept_token in report_text)=0
           OR (position(''''||concept_token||'''' in NEW.locator_json->>'onclick')=0
               AND position('"'||concept_token||'"' in NEW.locator_json->>'onclick')=0)
           OR position(NEW.locator_json->>'row_label' in report_text)=0
           OR position(NEW.locator_json->>'display_value' in report_text)=0
           OR fact.context_id IS DISTINCT FROM NEW.context_id OR fact.concept<>NEW.concept
           OR btrim(regexp_replace(coalesce(fact.raw_value,''),'\\s+',' ','g'))<>NEW.raw_value
           OR fact.unit_id IS DISTINCT FROM NEW.unit_id
           OR fact.is_nil OR NEW.fact_id IS DISTINCT FROM fact.locator_json->>'element_id'
           OR (fact.locator_json->>'locator_type'='inline_xbrl_html' AND
               (jsonb_typeof(fact.locator_json->'is_hidden') IS DISTINCT FROM 'boolean'
                OR (fact.locator_json->>'is_hidden')::boolean))
           OR NEW.header_date IS DISTINCT FROM coalesce(fact.period_end,fact.period_instant)
           OR btrim(regexp_replace(NEW.header_raw,'\\s+',' ','g'))<>NEW.header_normalized
           OR (position('onclick="'||(NEW.locator_json->>'onclick')||'"' in report_text)=0
               AND position('onclick='''||(NEW.locator_json->>'onclick')||'''' in report_text)=0)
           OR position(NEW.locator_json->>'anchor_start_tag' in report_text)=0
           OR (length(report_text)-length(replace(
                report_text,NEW.locator_json->>'anchor_start_tag','')))
                / length(NEW.locator_json->>'anchor_start_tag')<>1
        THEN RAISE EXCEPTION 'generated statement occurrence fact identity mismatch'; END IF;

        display_text:=btrim(NEW.locator_json->>'display_value');
        display_negative:=display_text ~ '^[(].*[)]$';
        display_text:=regexp_replace(display_text,'[()$,[:space:]]','','g');
        fact_text:=regexp_replace(btrim(coalesce(fact.raw_value,'')),'[,[:space:]]','','g');
        IF display_text !~ '^[+-]?[0-9]+(?:[.][0-9]+)?$'
           OR fact_text !~ '^[+-]?[0-9]+(?:[.][0-9]+)?$'
        THEN RAISE EXCEPTION 'generated statement numeric identity malformed'; END IF;
        display_value:=display_text::numeric * CASE WHEN display_negative THEN -1 ELSE 1 END;
        fact_value:=fact_text::numeric * power(10::numeric,coalesce(fact.scale,0));
        IF fact.sign='-' THEN fact_value:=-fact_value; END IF;
        multiplier:=(NEW.locator_json->>'scale_multiplier')::numeric;
        IF display_value*multiplier<>fact_value THEN
          RAISE EXCEPTION 'generated statement exact numeric identity mismatch';
        END IF;

        expected_semantic:=encode(sha256(convert_to(
          NEW.report_sha256||chr(31)||NEW.report_ordinal||chr(31)||NEW.row_ordinal||chr(31)||NEW.column_ordinal||chr(31)||
          NEW.occurrence_ordinal||chr(31)||coalesce(NEW.fact_id,'')||chr(31)||NEW.context_id||chr(31)||NEW.concept||chr(31)||
          NEW.raw_value||chr(31)||coalesce(NEW.unit_id,'')||chr(31)||NEW.header_raw||chr(31)||NEW.header_normalized||chr(31)||
          NEW.header_date::text||chr(31)||coalesce(NEW.locator_json->>'kind','')||chr(31)||
          coalesce(NEW.locator_json->>'row','')||chr(31)||coalesce(NEW.locator_json->>'column','')||chr(31)||
          coalesce(NEW.locator_json->>'fact_id','')||chr(31)||coalesce(NEW.locator_json->>'display_value','')||chr(31)||
          coalesce(NEW.locator_json->>'row_label','')||chr(31)||coalesce(NEW.locator_json->>'statement_role','')||chr(31)||
          coalesce(NEW.locator_json->>'presentation_order','')||chr(31)||coalesce(NEW.locator_json->>'preferred_label_role','')||chr(31)||
          coalesce(NEW.locator_json->>'scale_multiplier','')||chr(31)||coalesce(NEW.locator_json->>'period_start','')||chr(31)||
          coalesce(NEW.locator_json->>'period_end','')||chr(31)||coalesce(NEW.locator_json->>'dimensions_sha256','')||chr(31)||
          coalesce(NEW.locator_json->>'decimals','')||chr(31)||coalesce(NEW.locator_json->>'presentation_artifact_id','')||chr(31)||
          coalesce(NEW.locator_json->>'presentation_sha256','')||chr(31)||coalesce(NEW.locator_json->>'label_artifact_id','')||chr(31)||
          coalesce(NEW.locator_json->>'label_sha256','')||chr(31)||coalesce(NEW.locator_json->>'canonical_duplicate_rule','')||chr(31)||
          coalesce(NEW.locator_json->>'equivalent_raw_fact_ids','')||chr(31)||coalesce(NEW.locator_json->>'onclick','')||chr(31)||
          coalesce(NEW.locator_json->>'onclick_sha256','')||chr(31)||coalesce(NEW.locator_json->>'onclick_attribute','')||chr(31)||
          coalesce(NEW.locator_json->>'onclick_attribute_sha256','')||chr(31)||coalesce(NEW.locator_json->>'anchor_start_tag','')||chr(31)||
          coalesce(NEW.locator_json->>'anchor_start_tag_sha256',''),'UTF8')),'hex');
        IF NEW.semantic_sha256<>expected_semantic THEN
          RAISE EXCEPTION 'statement occurrence semantic digest mismatch';
        END IF;
        RETURN NEW;
      END IF;
    """ if generated else ""
    return f"""
    CREATE OR REPLACE FUNCTION guard_sec_statement_occurrence_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE reference sec_statement_report_references%ROWTYPE; fact sec_raw_xbrl_facts%ROWTYPE;
            run sec_financial_parse_runs%ROWTYPE; presentation sec_filing_artifacts%ROWTYPE;
            label_artifact sec_filing_artifacts%ROWTYPE; report_xml xml; found_concept text;
            found_context text; found_fact_id text; found_value text; found_unit text;
            found_header text; header_parts xml[]; header_match text[]; report_text text;
            concept_token text; display_text text; fact_text text; display_negative boolean;
            display_value numeric; fact_value numeric; multiplier numeric; expected_semantic text;
            equivalent_ids jsonb;
            header_date_matches integer;
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
      SELECT * INTO reference FROM sec_statement_report_references WHERE id=NEW.statement_report_reference_id;
      SELECT * INTO fact FROM sec_raw_xbrl_facts WHERE id=NEW.raw_fact_id;
      IF reference.id IS NULL OR fact.id IS NULL OR reference.parse_run_id<>NEW.parse_run_id
         OR fact.parse_run_id<>NEW.parse_run_id OR reference.report_sha256<>NEW.report_sha256
         OR reference.report_ordinal<>NEW.report_ordinal OR NEW.known_at<>reference.known_at
         OR NEW.created_txid<>reference.created_txid OR NEW.created_txid<>fact.created_txid
      THEN RAISE EXCEPTION 'SEC statement occurrence lineage mismatch'; END IF;
      {generated_branch}
      BEGIN report_xml:=xmlparse(document {report_xml_source});
      EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'invalid retained statement report XML'; END;
      found_concept:=btrim(((xpath(format('/Report/Rows/Row[%s]/ElementName/text()',NEW.row_ordinal),report_xml))[1])::text,'"');
      IF position(':' in found_concept)=0 THEN found_concept:=regexp_replace(found_concept,'_',':'); END IF;
      found_context:=btrim(((xpath(format('/Report/Rows/Row[%s]/Cells/Cell[%s]/@contextRef',NEW.row_ordinal,NEW.column_ordinal),report_xml))[1])::text,'"');
      found_fact_id:=btrim(((xpath(format('/Report/Rows/Row[%s]/Cells/Cell[%s]/@factId',NEW.row_ordinal,NEW.column_ordinal),report_xml))[1])::text,'"');
      found_unit:=btrim(((xpath(format('/Report/Rows/Row[%s]/Cells/Cell[%s]/@unitRef',NEW.row_ordinal,NEW.column_ordinal),report_xml))[1])::text,'"');
      found_value:=btrim(((xpath(format('/Report/Rows/Row[%s]/Cells/Cell[%s]/NumericAmount/text()',NEW.row_ordinal,NEW.column_ordinal),report_xml))[1])::text,'"');
      header_parts:=xpath(format('/Report/Columns/Column[%s]/Labels/Label/@Label',NEW.column_ordinal),report_xml);
      SELECT btrim(string_agg(btrim(value::text,'"'), ' ')) INTO found_header FROM unnest(header_parts) value;
      header_match:=regexp_match(found_header,'(January|February|March|April|May|June|July|August|September|October|November|December)[[:space:]]+([0-9]{{1,2}}),?[[:space:]]+([0-9]{{4}})','i');
      IF found_concept IS DISTINCT FROM NEW.concept OR found_context IS DISTINCT FROM NEW.context_id
         OR found_fact_id IS DISTINCT FROM NEW.fact_id OR btrim(regexp_replace(coalesce(found_value,''),'\\s+',' ','g'))<>NEW.raw_value
         OR found_unit IS DISTINCT FROM NEW.unit_id OR found_header IS DISTINCT FROM NEW.header_raw
         OR header_match IS NULL OR to_date(header_match[1]||header_match[2]||header_match[3],'MonthDDYYYY')<>NEW.header_date
         OR btrim(regexp_replace(NEW.header_raw,'\\s+',' ','g'))<>NEW.header_normalized
         OR fact.context_id IS DISTINCT FROM NEW.context_id OR fact.concept<>NEW.concept
         OR btrim(regexp_replace(coalesce(fact.raw_value,''),'\\s+',' ','g'))<>NEW.raw_value
         OR fact.unit_id IS DISTINCT FROM NEW.unit_id
         OR NEW.fact_id IS NOT NULL AND fact.locator_json->>'element_id' IS DISTINCT FROM NEW.fact_id
      THEN RAISE EXCEPTION 'statement occurrence mismatch'; END IF;
      IF NEW.semantic_sha256<>encode(sha256(convert_to(
        NEW.report_sha256||chr(31)||NEW.report_ordinal||chr(31)||NEW.row_ordinal||chr(31)||NEW.column_ordinal||chr(31)||
        NEW.occurrence_ordinal||chr(31)||coalesce(NEW.fact_id,'')||chr(31)||NEW.context_id||chr(31)||NEW.concept||chr(31)||
        NEW.raw_value||chr(31)||coalesce(NEW.unit_id,'')||chr(31)||NEW.header_raw||chr(31)||NEW.header_normalized||chr(31)||
        NEW.header_date::text||chr(31)||coalesce(NEW.locator_json->>'kind','')||chr(31)||
        coalesce(NEW.locator_json->>'row','')||chr(31)||coalesce(NEW.locator_json->>'column','')||chr(31)||
        coalesce(NEW.locator_json->>'fact_id',''),'UTF8')),'hex')
      THEN RAISE EXCEPTION 'statement occurrence semantic digest mismatch'; END IF;
      RETURN NEW;
    END $$;
    """


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION sec_statement_report_xml_text(content bytea) RETURNS text
    LANGUAGE plpgsql IMMUTABLE STRICT AS $$
    DECLARE source text; envelope_match text[];
            document_open_count integer; document_close_count integer;
            text_open_count integer; text_close_count integer;
    BEGIN
      IF octet_length(content)>5000000 THEN
        RAISE EXCEPTION 'statement report exceeds byte limit';
      END IF;
      source:=convert_from(content,'UTF8');
      IF source !~* E'^[\\t\\n\\r ]*<DOCUMENT>[\\t\\n\\r ]*' THEN
        RETURN source;
      END IF;
      SELECT count(*) INTO document_open_count FROM regexp_matches(source,'<DOCUMENT>','gi');
      SELECT count(*) INTO document_close_count FROM regexp_matches(source,'</DOCUMENT>','gi');
      SELECT count(*) INTO text_open_count FROM regexp_matches(source,'<TEXT>','gi');
      SELECT count(*) INTO text_close_count FROM regexp_matches(source,'</TEXT>','gi');
      IF document_open_count<>1 OR document_close_count<>1
         OR text_open_count<>1 OR text_close_count<>1 THEN
        RAISE EXCEPTION 'malformed SEC SGML statement envelope';
      END IF;
      envelope_match:=regexp_match(
        source,
        E'^[\\t\\n\\r ]*<DOCUMENT>[\\t\\n\\r ]*(.*?)<TEXT>[\\t\\n\\r ]*(.*?)[\\t\\n\\r ]*</TEXT>[\\t\\n\\r ]*</DOCUMENT>[\\t\\n\\r ]*$',
        'is'
      );
      IF envelope_match IS NULL OR envelope_match[2] IS NULL
         OR envelope_match[2]~*'<DOCUMENT>' THEN
        RAISE EXCEPTION 'malformed SEC SGML statement envelope';
      END IF;
      RETURN envelope_match[2];
    END $$;
    """)
    _replace_function_source(
        ["validate_sec_parser_v2_structured_unit"],
        "parser_version_value = ANY (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1'])",
        "parser_version_value = ANY (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1','xbrl-lineage-v2.2'])",
    )
    _replace_function_source(
        ["guard_sec_statement_report_reference_insert", "guard_sec_statement_fact_authority_insert"],
        "run.parser_version<>ALL (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1'])",
        "run.parser_version<>ALL (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1','xbrl-lineage-v2.2'])",
    )
    _replace_function_source(
        ["guard_sec_statement_report_reference_insert"],
        "IF octet_length(NEW.filing_summary_content)<>NEW.filing_summary_byte_size",
        "IF run.parser_version='xbrl-lineage-v2.2' THEN "
        "PERFORM pg_advisory_xact_lock(hashtextextended("
        "'sec-statement-report-ordinal-v2.2',NEW.parse_run_id)); "
        "IF EXISTS (SELECT 1 FROM sec_statement_report_references existing "
        "WHERE existing.parse_run_id=NEW.parse_run_id "
        "AND existing.report_ordinal=NEW.report_ordinal) THEN "
        "RAISE EXCEPTION 'duplicate parser-v2.2 statement report ordinal'; "
        "END IF; END IF; "
        "IF octet_length(NEW.filing_summary_content)<>NEW.filing_summary_byte_size",
    )
    _replace_function_source(
        ["guard_sec_statement_report_reference_insert"],
        "IF expected_type IS DISTINCT FROM NEW.statement_type OR run.id IS NULL",
        "IF (run.parser_version='xbrl-lineage-v2.2' AND "
        "(btrim(NEW.statement_role)='' OR lower(NEW.statement_role) !~ "
        "'(balance|financial position|cash flow|comprehensive|income|operations|earnings|equity|stockholder)')) "
        "OR expected_type IS DISTINCT FROM NEW.statement_type OR run.id IS NULL",
    )
    _replace_function_source(
        ["guard_sec_statement_report_reference_insert"],
        "BEGIN summary_xml:=xmlparse(document convert_from(NEW.filing_summary_content,'UTF8'));",
        "BEGIN summary_xml:=xmlparse(document CASE WHEN run.parser_version='xbrl-lineage-v2.2' "
        "THEN sec_statement_report_xml_text(NEW.filing_summary_content) "
        "ELSE convert_from(NEW.filing_summary_content,'UTF8') END);",
    )
    for word, digit in (("three", "3"), ("six", "6"), ("nine", "9"), ("twelve", "12")):
        positive_subjects = ("occurrence", "middle") if word in {"three", "twelve"} else ("middle",)
        for subject in positive_subjects:
            positive = f"lower({subject}.header_raw) LIKE '%{word} months ended%'"
            _replace_function_source(
                ["guard_sec_statement_fact_authority_insert"],
                positive,
                f"({positive} OR (run.parser_version='xbrl-lineage-v2.2' "
                f"AND {subject}.locator_json->>'kind'='sec_generated_statement_html_v2' "
                f"AND lower({subject}.header_raw) LIKE '%{digit} months ended%'))",
            )
        for subject in ("current_anchor", "prior_anchor"):
            negative = f"lower({subject}.header_raw) NOT LIKE '%{word} months ended%'"
            _replace_function_source(
                ["guard_sec_statement_fact_authority_insert"],
                negative,
                f"({negative} AND NOT (run.parser_version='xbrl-lineage-v2.2' "
                f"AND {subject}.locator_json->>'kind'='sec_generated_statement_html_v2' "
                f"AND lower({subject}.header_raw) LIKE '%{digit} months ended%'))",
            )
    op.execute(_occurrence_guard(generated=True))


def downgrade() -> None:
    op.execute("LOCK TABLE sec_statement_fact_authorities, sec_statement_occurrence_evidence, sec_statement_report_references IN ACCESS EXCLUSIVE MODE")
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM sec_financial_parse_runs WHERE parser_version='xbrl-lineage-v2.2'"
    )).scalar_one()
    if count:
        raise RuntimeError("downgrade refused: retained parser-v2.2 authority exists")
    _replace_function_source(
        ["guard_sec_statement_report_reference_insert"],
        "IF (run.parser_version='xbrl-lineage-v2.2' AND "
        "(btrim(NEW.statement_role)='' OR lower(NEW.statement_role) !~ "
        "'(balance|financial position|cash flow|comprehensive|income|operations|earnings|equity|stockholder)')) "
        "OR expected_type IS DISTINCT FROM NEW.statement_type OR run.id IS NULL",
        "IF expected_type IS DISTINCT FROM NEW.statement_type OR run.id IS NULL",
    )
    _replace_function_source(
        ["guard_sec_statement_report_reference_insert"],
        "BEGIN summary_xml:=xmlparse(document CASE WHEN run.parser_version='xbrl-lineage-v2.2' "
        "THEN sec_statement_report_xml_text(NEW.filing_summary_content) "
        "ELSE convert_from(NEW.filing_summary_content,'UTF8') END);",
        "BEGIN summary_xml:=xmlparse(document convert_from(NEW.filing_summary_content,'UTF8'));",
    )
    _replace_function_source(
        ["guard_sec_statement_report_reference_insert"],
        "IF run.parser_version='xbrl-lineage-v2.2' THEN "
        "PERFORM pg_advisory_xact_lock(hashtextextended("
        "'sec-statement-report-ordinal-v2.2',NEW.parse_run_id)); "
        "IF EXISTS (SELECT 1 FROM sec_statement_report_references existing "
        "WHERE existing.parse_run_id=NEW.parse_run_id "
        "AND existing.report_ordinal=NEW.report_ordinal) THEN "
        "RAISE EXCEPTION 'duplicate parser-v2.2 statement report ordinal'; "
        "END IF; END IF; "
        "IF octet_length(NEW.filing_summary_content)<>NEW.filing_summary_byte_size",
        "IF octet_length(NEW.filing_summary_content)<>NEW.filing_summary_byte_size",
    )
    op.execute(_occurrence_guard(generated=False))
    op.execute("DROP FUNCTION sec_statement_report_xml_text(bytea)")
    for word, digit in reversed((("three", "3"), ("six", "6"), ("nine", "9"), ("twelve", "12"))):
        positive_subjects = ("occurrence", "middle") if word in {"three", "twelve"} else ("middle",)
        for subject in reversed(positive_subjects):
            positive = f"lower({subject}.header_raw) LIKE '%{word} months ended%'"
            _replace_function_source(
                ["guard_sec_statement_fact_authority_insert"],
                f"({positive} OR (run.parser_version='xbrl-lineage-v2.2' "
                f"AND {subject}.locator_json->>'kind'='sec_generated_statement_html_v2' "
                f"AND lower({subject}.header_raw) LIKE '%{digit} months ended%'))",
                positive,
            )
        for subject in reversed(("current_anchor", "prior_anchor")):
            negative = f"lower({subject}.header_raw) NOT LIKE '%{word} months ended%'"
            _replace_function_source(
                ["guard_sec_statement_fact_authority_insert"],
                f"({negative} AND NOT (run.parser_version='xbrl-lineage-v2.2' "
                f"AND {subject}.locator_json->>'kind'='sec_generated_statement_html_v2' "
                f"AND lower({subject}.header_raw) LIKE '%{digit} months ended%'))",
                negative,
            )
    _replace_function_source(
        ["guard_sec_statement_report_reference_insert", "guard_sec_statement_fact_authority_insert"],
        "run.parser_version<>ALL (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1','xbrl-lineage-v2.2'])",
        "run.parser_version<>ALL (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1'])",
    )
    _replace_function_source(
        ["validate_sec_parser_v2_structured_unit"],
        "parser_version_value = ANY (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1','xbrl-lineage-v2.2'])",
        "parser_version_value = ANY (ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1'])",
    )
