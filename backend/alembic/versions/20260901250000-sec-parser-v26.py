"""Authorize append-only SEC parser v2.6 report and raw-label identity.

Revision ID: 20260901250000
Revises: 20260901240000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901250000"
down_revision = "20260901240000"
branch_labels = None
depends_on = None


V24 = "xbrl-lineage-v2.4"
V25 = "xbrl-lineage-v2.5"
V26 = "xbrl-lineage-v2.6"


def _replace_function_source(functions: tuple[str, ...], old: str, new: str) -> None:
    names = ",".join(repr(name) for name in functions)
    old_sql = "'" + old.replace("'", "''") + "'"
    new_sql = "'" + new.replace("'", "''") + "'"
    op.execute(f"""
    DO $$
    DECLARE function_name text; definition text;
    BEGIN
      FOREACH function_name IN ARRAY ARRAY[{names}] LOOP
        SELECT pg_get_functiondef(p.oid) INTO definition
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname=current_schema() AND p.proname=function_name;
        IF definition IS NULL OR position({old_sql} in definition)=0 THEN
          RAISE EXCEPTION 'parser-v2.6 guard function source mismatch: %', function_name;
        END IF;
        EXECUTE replace(definition,{old_sql},{new_sql});
      END LOOP;
    END $$;
    """)


_V25_CLASSIFIER = f"""expected_type:=CASE WHEN run.parser_version='{V25}' THEN CASE
        WHEN btrim(NEW.statement_role)='' THEN NULL
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%balance%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%financial position%' THEN 'balance_sheet'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%cash flow%'
          OR regexp_replace(lower(NEW.statement_role||' '||NEW.report_name),'[^a-z0-9]','','g') LIKE '%statementofcashflows%'
          OR regexp_replace(lower(NEW.statement_role||' '||NEW.report_name),'[^a-z0-9]','','g') LIKE '%statementsofcashflows%' THEN 'cash_flow'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%comprehensive%' THEN 'comprehensive_income'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%income%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%operations%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%earnings%' THEN 'income_statement'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%equity%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%stockholder%' THEN 'equity' END
      ELSE CASE
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%balance%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%financial position%' THEN 'balance_sheet'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%cash flow%' THEN 'cash_flow'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%comprehensive%' THEN 'comprehensive_income'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%income%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%operations%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%earnings%' THEN 'income_statement'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%equity%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%stockholder%' THEN 'equity' END END;"""

_V26_CLASSIFIER = f"""expected_type:=CASE WHEN run.parser_version='{V26}' THEN sec_statement_type_v26(NEW.statement_role)
      WHEN run.parser_version='{V25}' THEN CASE
        WHEN btrim(NEW.statement_role)='' THEN NULL
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%balance%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%financial position%' THEN 'balance_sheet'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%cash flow%'
          OR regexp_replace(lower(NEW.statement_role||' '||NEW.report_name),'[^a-z0-9]','','g') LIKE '%statementofcashflows%'
          OR regexp_replace(lower(NEW.statement_role||' '||NEW.report_name),'[^a-z0-9]','','g') LIKE '%statementsofcashflows%' THEN 'cash_flow'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%comprehensive%' THEN 'comprehensive_income'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%income%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%operations%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%earnings%' THEN 'income_statement'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%equity%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%stockholder%' THEN 'equity' END
      ELSE CASE
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%balance%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%financial position%' THEN 'balance_sheet'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%cash flow%' THEN 'cash_flow'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%comprehensive%' THEN 'comprehensive_income'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%income%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%operations%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%earnings%' THEN 'income_statement'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%equity%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%stockholder%' THEN 'equity' END END;"""

_V25_ROLE_GUARD = """((run.parser_version=ANY (ARRAY['xbrl-lineage-v2.2','xbrl-lineage-v2.3','xbrl-lineage-v2.4']) AND (btrim(NEW.statement_role)='' OR lower(NEW.statement_role) !~ '(balance|financial position|cash flow|comprehensive|income|operations|earnings|equity|stockholder)')) OR (run.parser_version='xbrl-lineage-v2.5' AND (btrim(NEW.statement_role)='' OR (lower(NEW.statement_role) !~ '(balance|financial position|cash flow|comprehensive|income|operations|earnings|equity|stockholder)' AND regexp_replace(lower(NEW.statement_role),'[^a-z0-9]','','g') !~ 'statements?ofcashflows'))))"""

_V26_ROLE_GUARD = f"""({_V25_ROLE_GUARD} OR (run.parser_version='{V26}' AND
      (expected_type IS NULL OR (sec_statement_type_v26(NEW.report_name) IS NOT NULL
        AND sec_statement_type_v26(NEW.report_name) IS DISTINCT FROM expected_type))))"""


def _replacement_fragments() -> dict[str, str]:
    old_versions = (
        "ARRAY['xbrl-lineage-v2','xbrl-lineage-v2.1','xbrl-lineage-v2.2',"
        "'xbrl-lineage-v2.3','xbrl-lineage-v2.4','xbrl-lineage-v2.5']"
    )
    new_versions = old_versions[:-1] + ",'xbrl-lineage-v2.6']"
    old_generated = (
        "run.parser_version=ANY (ARRAY['xbrl-lineage-v2.2',"
        "'xbrl-lineage-v2.3','xbrl-lineage-v2.4','xbrl-lineage-v2.5'])"
    )
    new_generated = old_generated[:-2] + ",'xbrl-lineage-v2.6'])"
    old_period = f"""OR (run.parser_version='{V25}' AND
              NEW.locator_json->'period_start' IS DISTINCT FROM
                coalesce(to_jsonb(fact.period_start::text),'null'::jsonb))
           OR (run.parser_version<>'{V25}' AND
              NEW.locator_json->>'period_start' IS DISTINCT FROM
                coalesce(fact.period_start::text,''))"""
    new_period = f"""OR (run.parser_version=ANY (ARRAY['{V25}','{V26}']) AND
              NEW.locator_json->'period_start' IS DISTINCT FROM
                coalesce(to_jsonb(fact.period_start::text),'null'::jsonb))
           OR (run.parser_version<>ALL (ARRAY['{V25}','{V26}']) AND
              NEW.locator_json->>'period_start' IS DISTINCT FROM
                coalesce(fact.period_start::text,''))"""
    old_repeat = f"run.parser_version=ANY (ARRAY['{V24}','{V25}'])"
    new_repeat = f"run.parser_version=ANY (ARRAY['{V24}','{V25}','{V26}'])"
    old_report_text = "report_text:=convert_from(reference.report_content,'UTF8');"
    new_report_text = f"""report_text:=CASE WHEN run.parser_version='{V26}'
          THEN sec_statement_report_xml_text(reference.report_content)
          ELSE convert_from(reference.report_content,'UTF8') END;"""
    old_row_label = "OR position(NEW.locator_json->>'row_label' in report_text)=0"
    new_row_label = f"OR (run.parser_version<>'{V26}' AND position(NEW.locator_json->>'row_label' in report_text)=0)"
    old_header_guard = "OR header_date_matches<>1"
    new_header_guard = f"""OR (run.parser_version='{V26}' AND (
              coalesce(NEW.locator_json->>'row_label_source_html','')=''
              OR coalesce(NEW.locator_json->>'anchor_source_html','')=''
              OR coalesce(NEW.locator_json->>'anchor_end_tag','')=''
              OR octet_length(NEW.locator_json->>'row_label_source_html')>8192
              OR octet_length(NEW.locator_json->>'anchor_source_html')>8192
              OR coalesce(NEW.locator_json->>'row_label_source_html_sha256','') !~ '^[0-9a-f]{{64}}$'
              OR coalesce(NEW.locator_json->>'anchor_source_html_sha256','') !~ '^[0-9a-f]{{64}}$'
              OR encode(sha256(convert_to(NEW.locator_json->>'row_label_source_html','UTF8')),'hex')
                   <>NEW.locator_json->>'row_label_source_html_sha256'
              OR encode(sha256(convert_to(NEW.locator_json->>'anchor_source_html','UTF8')),'hex')
                   <>NEW.locator_json->>'anchor_source_html_sha256'
              OR jsonb_typeof(NEW.locator_json->'anchor_source_start')<>'number'
              OR jsonb_typeof(NEW.locator_json->'anchor_source_end')<>'number'
              OR jsonb_typeof(NEW.locator_json->'anchor_source_html_occurrence_count')<>'number'
              OR coalesce(NEW.locator_json->>'anchor_source_start','') !~ '^[0-9]+$'
              OR coalesce(NEW.locator_json->>'anchor_source_end','') !~ '^[0-9]+$'
              OR coalesce(NEW.locator_json->>'anchor_source_html_occurrence_count','') !~ '^[1-9][0-9]*$'
              OR (NEW.locator_json->>'anchor_source_end')::integer<=(NEW.locator_json->>'anchor_source_start')::integer
              OR (NEW.locator_json->>'anchor_source_end')::integer-(NEW.locator_json->>'anchor_source_start')::integer
                   <>char_length(NEW.locator_json->>'anchor_source_html')
              OR NEW.locator_json->>'anchor_source_html'<>
                   (NEW.locator_json->>'anchor_start_tag')||(NEW.locator_json->>'row_label_source_html')||
                   (NEW.locator_json->>'anchor_end_tag')
              OR lower(NEW.locator_json->>'anchor_end_tag') !~ '^</[[:space:]]*a[[:space:]]*>$'
            ))
           OR header_date_matches<>1"""
    old_fact_identity = "IF position(concept_token in report_text)=0"
    new_fact_identity = f"""IF (run.parser_version='{V26}' AND (
             report_text IS NULL
             OR substring(report_text FROM (NEW.locator_json->>'anchor_source_start')::integer+1
                  FOR char_length(NEW.locator_json->>'anchor_source_html'))
                  IS DISTINCT FROM NEW.locator_json->>'anchor_source_html'
             OR (length(report_text)-length(replace(report_text,
                  NEW.locator_json->>'anchor_source_html','')))
                  / length(NEW.locator_json->>'anchor_source_html')
                  <>(NEW.locator_json->>'anchor_source_html_occurrence_count')::integer
           ))
           OR position(concept_token in report_text)=0"""
    old_semantic = (
        f"CASE WHEN run.parser_version=ANY (ARRAY['{V24}','{V25}','{V26}']) THEN chr(31)||"
        "coalesce(NEW.locator_json->>'anchor_start_tag_occurrence_count','') ELSE '' END"
    )
    new_semantic = old_semantic + f"""||CASE WHEN run.parser_version='{V26}' THEN
          chr(31)||coalesce(NEW.locator_json->>'row_label_source_html','')||
          chr(31)||coalesce(NEW.locator_json->>'row_label_source_html_sha256','')||
          chr(31)||coalesce(NEW.locator_json->>'anchor_source_html','')||
          chr(31)||coalesce(NEW.locator_json->>'anchor_source_html_sha256','')||
          chr(31)||coalesce(NEW.locator_json->>'anchor_end_tag','')||
          chr(31)||coalesce(NEW.locator_json->>'anchor_source_start','')||
          chr(31)||coalesce(NEW.locator_json->>'anchor_source_end','')||
          chr(31)||coalesce(NEW.locator_json->>'anchor_source_html_occurrence_count','')
          ELSE '' END"""
    return locals()


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION sec_statement_type_v26(value text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE STRICT AS $$
    DECLARE normalized text; compact text;
    BEGIN
      normalized:=btrim(regexp_replace(lower(value),'[[:space:]]+',' ','g'));
      IF normalized='' THEN RETURN NULL; END IF;
      compact:=regexp_replace(normalized,'[^a-z0-9]','','g');
      IF normalized LIKE '%balance%' OR normalized LIKE '%financial position%'
         OR compact LIKE '%balancesheet%'
         OR compact LIKE '%statementoffinancialposition%'
         OR compact LIKE '%statementsoffinancialposition%' THEN RETURN 'balance_sheet'; END IF;
      IF normalized LIKE '%cash flow%' OR compact LIKE '%statementofcashflows%'
         OR compact LIKE '%statementsofcashflows%' THEN RETURN 'cash_flow'; END IF;
      IF normalized LIKE '%comprehensive%' THEN RETURN 'comprehensive_income'; END IF;
      IF normalized LIKE '%income%' OR normalized LIKE '%operations%'
         OR normalized LIKE '%earnings%' THEN RETURN 'income_statement'; END IF;
      IF normalized LIKE '%equity%' OR normalized LIKE '%stockholder%' THEN RETURN 'equity'; END IF;
      RETURN NULL;
    END $$;
    """)
    fragments = _replacement_fragments()
    old_versions = fragments["old_versions"]
    new_versions = fragments["new_versions"]
    _replace_function_source(
        (
            "validate_sec_parser_v2_structured_unit",
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
        ), old_versions, new_versions,
    )
    old_generated = fragments["old_generated"]
    new_generated = fragments["new_generated"]
    _replace_function_source(
        (
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
            "guard_sec_statement_occurrence_insert",
        ), old_generated, new_generated,
    )
    _replace_function_source(
        ("guard_sec_statement_report_reference_insert",),
        _V25_CLASSIFIER, _V26_CLASSIFIER,
    )
    _replace_function_source(
        ("guard_sec_statement_report_reference_insert",),
        _V25_ROLE_GUARD, _V26_ROLE_GUARD,
    )
    old_period = fragments["old_period"]
    new_period = fragments["new_period"]
    _replace_function_source(("guard_sec_statement_occurrence_insert",), old_period, new_period)
    old_repeat = fragments["old_repeat"]
    new_repeat = fragments["new_repeat"]
    _replace_function_source(("guard_sec_statement_occurrence_insert",), old_repeat, new_repeat)
    old_report_text = fragments["old_report_text"]
    new_report_text = fragments["new_report_text"]
    _replace_function_source(("guard_sec_statement_occurrence_insert",), old_report_text, new_report_text)
    old_fact_identity = fragments["old_fact_identity"]
    new_fact_identity = fragments["new_fact_identity"]
    _replace_function_source(
        ("guard_sec_statement_occurrence_insert",),
        old_fact_identity,
        new_fact_identity,
    )
    old_row_label = fragments["old_row_label"]
    new_row_label = fragments["new_row_label"]
    _replace_function_source(("guard_sec_statement_occurrence_insert",), old_row_label, new_row_label)
    old_header_guard = fragments["old_header_guard"]
    new_header_guard = fragments["new_header_guard"]
    _replace_function_source(("guard_sec_statement_occurrence_insert",), old_header_guard, new_header_guard)
    old_semantic = fragments["old_semantic"]
    new_semantic = fragments["new_semantic"]
    _replace_function_source(("guard_sec_statement_occurrence_insert",), old_semantic, new_semantic)


def downgrade() -> None:
    op.execute(
        "LOCK TABLE sec_financial_parse_runs, sec_statement_fact_authorities, "
        "sec_statement_occurrence_evidence, sec_statement_report_references "
        "IN ACCESS EXCLUSIVE MODE"
    )
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM sec_financial_parse_runs WHERE parser_version=:version"
    ), {"version": V26}).scalar_one()
    if count:
        raise RuntimeError("downgrade refused: retained parser-v2.6 lineage exists")
    # Restore the exact v2.5 trigger definitions in reverse order.
    fragments = _replacement_fragments()
    old_semantic = fragments["old_semantic"]
    new_semantic = fragments["new_semantic"]
    old_header_guard = fragments["old_header_guard"]
    new_header_guard = fragments["new_header_guard"]
    old_row_label = fragments["old_row_label"]
    new_row_label = fragments["new_row_label"]
    old_report_text = fragments["old_report_text"]
    new_report_text = fragments["new_report_text"]
    old_fact_identity = fragments["old_fact_identity"]
    new_fact_identity = fragments["new_fact_identity"]
    old_repeat = fragments["old_repeat"]
    new_repeat = fragments["new_repeat"]
    old_period = fragments["old_period"]
    new_period = fragments["new_period"]
    old_generated = fragments["old_generated"]
    new_generated = fragments["new_generated"]
    old_versions = fragments["old_versions"]
    new_versions = fragments["new_versions"]
    _replace_function_source(("guard_sec_statement_occurrence_insert",), new_semantic, old_semantic)
    _replace_function_source(("guard_sec_statement_occurrence_insert",), new_header_guard, old_header_guard)
    _replace_function_source(("guard_sec_statement_occurrence_insert",), new_row_label, old_row_label)
    _replace_function_source(("guard_sec_statement_occurrence_insert",), new_fact_identity, old_fact_identity)
    _replace_function_source(("guard_sec_statement_occurrence_insert",), new_report_text, old_report_text)
    _replace_function_source(("guard_sec_statement_occurrence_insert",), new_repeat, old_repeat)
    _replace_function_source(("guard_sec_statement_occurrence_insert",), new_period, old_period)
    _replace_function_source(("guard_sec_statement_report_reference_insert",), _V26_ROLE_GUARD, _V25_ROLE_GUARD)
    _replace_function_source(("guard_sec_statement_report_reference_insert",), _V26_CLASSIFIER, _V25_CLASSIFIER)
    _replace_function_source(
        (
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
            "guard_sec_statement_occurrence_insert",
        ), new_generated, old_generated,
    )
    _replace_function_source(
        (
            "validate_sec_parser_v2_structured_unit",
            "guard_sec_statement_report_reference_insert",
            "guard_sec_statement_fact_authority_insert",
        ), new_versions, old_versions,
    )
    op.execute("DROP FUNCTION sec_statement_type_v26(text)")
