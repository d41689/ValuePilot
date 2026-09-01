"""Add append-only retained SEC statement presentation authority.

Revision ID: 20260901150000
Revises: 20260901140000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260901150000"
down_revision = "20260901140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sec_statement_report_references",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("parse_run_id", sa.BigInteger(), nullable=False),
        sa.Column("filing_summary_artifact_id", sa.BigInteger(), nullable=False),
        sa.Column("filing_summary_sha256", sa.String(64), nullable=False),
        sa.Column("filing_summary_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("filing_summary_content", sa.LargeBinary(), nullable=False),
        sa.Column("report_artifact_id", sa.BigInteger(), nullable=False),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("report_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("report_content", sa.LargeBinary(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("report_ordinal", sa.Integer(), nullable=False),
        sa.Column("statement_role", sa.Text(), nullable=False),
        sa.Column("statement_type", sa.String(32), nullable=False),
        sa.Column("report_name", sa.String(255), nullable=False),
        sa.Column("reference_semantic_sha256", sa.String(64), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), server_default=sa.text("txid_current()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["parse_run_id"], ["sec_financial_parse_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["filing_summary_artifact_id"], ["sec_filing_artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["report_artifact_id"], ["sec_filing_artifacts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("parse_run_id", "report_ordinal", "report_artifact_id", name="uq_sec_statement_report_reference"),
        sa.CheckConstraint("filing_summary_sha256 ~ '^[0-9a-f]{64}$' AND report_sha256 ~ '^[0-9a-f]{64}$' AND reference_semantic_sha256 ~ '^[0-9a-f]{64}$' AND filing_summary_byte_size BETWEEN 1 AND 1000000 AND report_byte_size >= 0 AND report_ordinal > 0", name="ck_sec_statement_report_reference_shape"),
        sa.CheckConstraint("statement_type IN ('balance_sheet','income_statement','cash_flow','equity','comprehensive_income')", name="ck_sec_statement_report_reference_type"),
    )
    op.create_table(
        "sec_statement_occurrence_evidence",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("statement_report_reference_id", sa.BigInteger(), nullable=False),
        sa.Column("parse_run_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_fact_id", sa.BigInteger(), nullable=False),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("report_ordinal", sa.Integer(), nullable=False),
        sa.Column("row_ordinal", sa.Integer(), nullable=False),
        sa.Column("column_ordinal", sa.Integer(), nullable=False),
        sa.Column("occurrence_ordinal", sa.Integer(), nullable=False),
        sa.Column("fact_id", sa.Text(), nullable=True),
        sa.Column("context_id", sa.Text(), nullable=False),
        sa.Column("concept", sa.Text(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("unit_id", sa.Text(), nullable=True),
        sa.Column("header_raw", sa.Text(), nullable=False),
        sa.Column("header_normalized", sa.Text(), nullable=False),
        sa.Column("header_date", sa.Date(), nullable=False),
        sa.Column("locator_json", postgresql.JSONB(), nullable=False),
        sa.Column("semantic_sha256", sa.String(64), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), server_default=sa.text("txid_current()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["statement_report_reference_id"], ["sec_statement_report_references.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parse_run_id"], ["sec_financial_parse_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["raw_fact_id"], ["sec_raw_xbrl_facts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("statement_report_reference_id", "row_ordinal", "column_ordinal", "raw_fact_id", name="uq_sec_statement_occurrence_evidence"),
        sa.CheckConstraint("report_sha256 ~ '^[0-9a-f]{64}$' AND semantic_sha256 ~ '^[0-9a-f]{64}$' AND report_ordinal>0 AND row_ordinal>0 AND column_ordinal>0 AND occurrence_ordinal>0", name="ck_sec_statement_occurrence_shape"),
    )
    op.create_table(
        "sec_statement_fact_authorities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("raw_fact_id", sa.BigInteger(), nullable=False),
        sa.Column("statement_occurrence_id", sa.BigInteger(), nullable=False),
        sa.Column("current_anchor_occurrence_id", sa.BigInteger(), nullable=False),
        sa.Column("prior_anchor_occurrence_id", sa.BigInteger(), nullable=True),
        sa.Column("statement_report_reference_id", sa.BigInteger(), nullable=False),
        sa.Column("parse_run_id", sa.BigInteger(), nullable=False),
        sa.Column("statement_artifact_id", sa.BigInteger(), nullable=False),
        sa.Column("statement_sha256", sa.String(64), nullable=False),
        sa.Column("statement_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("statement_role", sa.Text(), nullable=False),
        sa.Column("statement_type", sa.String(32), nullable=False),
        sa.Column("report_ordinal", sa.Integer(), nullable=False),
        sa.Column("report_name", sa.String(255), nullable=False),
        sa.Column("occurrence_ordinal", sa.Integer(), nullable=False),
        sa.Column("occurrence_fact_id", sa.Text(), nullable=True),
        sa.Column("occurrence_semantic_sha256", sa.String(64), nullable=False),
        sa.Column("context_id", sa.Text(), nullable=False),
        sa.Column("presentation_class", sa.String(64), nullable=False),
        sa.Column("statement_period_end", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_quarter_ordinal", sa.Integer(), nullable=True),
        sa.Column("fiscal_year_start", sa.Date(), nullable=False),
        sa.Column("locator_json", postgresql.JSONB(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("created_txid", sa.BigInteger(), server_default=sa.text("txid_current()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["raw_fact_id"], ["sec_raw_xbrl_facts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["statement_occurrence_id"], ["sec_statement_occurrence_evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_anchor_occurrence_id"], ["sec_statement_occurrence_evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_anchor_occurrence_id"], ["sec_statement_occurrence_evidence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["statement_report_reference_id"], ["sec_statement_report_references.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parse_run_id"], ["sec_financial_parse_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["statement_artifact_id"], ["sec_filing_artifacts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("raw_fact_id", "statement_artifact_id", "report_ordinal", "occurrence_ordinal", name="uq_sec_statement_fact_authority_occurrence"),
        sa.CheckConstraint("statement_sha256 ~ '^[0-9a-f]{64}$' AND statement_byte_size >= 0", name="ck_sec_statement_authority_content"),
        sa.CheckConstraint("occurrence_semantic_sha256 ~ '^[0-9a-f]{64}$'", name="ck_sec_statement_authority_semantic"),
        sa.CheckConstraint("statement_type IN ('balance_sheet','income_statement','cash_flow','equity','comprehensive_income')", name="ck_sec_statement_authority_type"),
        sa.CheckConstraint("presentation_class IN ('current_period','prior_same_fiscal_quarter','prior_fiscal_year_comparative','prior_fiscal_year_balance_sheet')", name="ck_sec_statement_authority_class"),
        sa.CheckConstraint("report_ordinal > 0 AND occurrence_ordinal > 0", name="ck_sec_statement_authority_ordinals"),
        sa.CheckConstraint("fiscal_year BETWEEN 1800 AND 9999 AND (fiscal_quarter_ordinal IS NULL OR fiscal_quarter_ordinal BETWEEN 1 AND 4) AND fiscal_year_start <= statement_period_end", name="ck_sec_statement_authority_fiscal"),
    )
    op.execute("""
    CREATE FUNCTION guard_sec_statement_report_reference_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE run sec_financial_parse_runs%ROWTYPE; summary sec_filing_artifacts%ROWTYPE; report sec_filing_artifacts%ROWTYPE;
            reference_matches integer; expected_type text; summary_xml xml;
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
      SELECT * INTO run FROM sec_financial_parse_runs WHERE id=NEW.parse_run_id;
      SELECT * INTO summary FROM sec_filing_artifacts WHERE id=NEW.filing_summary_artifact_id;
      SELECT * INTO report FROM sec_filing_artifacts WHERE id=NEW.report_artifact_id;
      IF octet_length(NEW.filing_summary_content)<>NEW.filing_summary_byte_size
         OR encode(sha256(NEW.filing_summary_content),'hex')<>NEW.filing_summary_sha256
         OR octet_length(NEW.report_content)<>NEW.report_byte_size
         OR encode(sha256(NEW.report_content),'hex')<>NEW.report_sha256
      THEN RAISE EXCEPTION 'SEC FilingSummary content identity mismatch'; END IF;
      BEGIN summary_xml:=xmlparse(document convert_from(NEW.filing_summary_content,'UTF8'));
      EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'invalid retained FilingSummary XML'; END;
      SELECT count(*) INTO reference_matches FROM XMLTABLE(
        '//*[local-name()="Report"]' PASSING summary_xml COLUMNS
        position text PATH '*[local-name()="Position"]/text()',
        short_name text PATH '*[local-name()="ShortName"]/text()',
        long_name text PATH '*[local-name()="LongName"]/text()',
        role_value text PATH '*[local-name()="Role"]/text()',
        xml_filename text PATH '*[local-name()="XmlFileName"]/text()',
        html_filename text PATH '*[local-name()="HtmlFileName"]/text()'
      ) x WHERE x.position=NEW.report_ordinal::text
        AND (nullif(x.xml_filename,'')=NEW.filename OR nullif(x.html_filename,'')=NEW.filename)
        AND coalesce(x.role_value,'')=NEW.statement_role
        AND coalesce(nullif(x.short_name,''),nullif(x.long_name,''),NEW.filename)=NEW.report_name;
      IF reference_matches<>1 THEN RAISE EXCEPTION 'report is not an exact FilingSummary reference'; END IF;
      expected_type:=CASE
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%balance%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%financial position%' THEN 'balance_sheet'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%cash flow%' THEN 'cash_flow'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%comprehensive%' THEN 'comprehensive_income'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%income%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%operations%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%earnings%' THEN 'income_statement'
        WHEN lower(NEW.statement_role||' '||NEW.report_name) LIKE '%equity%' OR lower(NEW.statement_role||' '||NEW.report_name) LIKE '%stockholder%' THEN 'equity' END;
      IF expected_type IS DISTINCT FROM NEW.statement_type OR run.id IS NULL OR run.status<>'succeeded' OR run.parser_version<>'xbrl-lineage-v2'
         OR summary.id IS NULL OR report.id IS NULL OR summary.filing_id<>run.filing_id OR report.filing_id<>run.filing_id
         OR lower(summary.filename)<>'filingsummary.xml' OR lower(report.filename)<>lower(NEW.filename)
         OR summary.state<>'retained' OR report.state<>'retained'
         OR summary.sha256 IS DISTINCT FROM NEW.filing_summary_sha256 OR summary.byte_size IS DISTINCT FROM NEW.filing_summary_byte_size
         OR report.sha256 IS DISTINCT FROM NEW.report_sha256 OR report.byte_size IS DISTINCT FROM NEW.report_byte_size
         OR NEW.reference_semantic_sha256<>encode(sha256(convert_to(NEW.filing_summary_sha256||chr(31)||NEW.filename||chr(31)||NEW.report_ordinal::text||chr(31)||NEW.statement_role||chr(31)||NEW.statement_type||chr(31)||NEW.report_name, 'UTF8')), 'hex')
         OR NOT EXISTS (SELECT 1 FROM sec_financial_parse_run_artifacts WHERE parse_run_id=run.id AND artifact_id=summary.id)
         OR NOT EXISTS (SELECT 1 FROM sec_financial_parse_run_artifacts WHERE parse_run_id=run.id AND artifact_id=report.id)
         OR NEW.known_at<>run.known_at OR NEW.created_txid<>run.created_txid
      THEN RAISE EXCEPTION 'SEC statement report reference mismatch'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_sec_statement_report_reference_insert BEFORE INSERT ON sec_statement_report_references
      FOR EACH ROW EXECUTE FUNCTION guard_sec_statement_report_reference_insert();
    CREATE FUNCTION guard_sec_statement_occurrence_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE reference sec_statement_report_references%ROWTYPE; fact sec_raw_xbrl_facts%ROWTYPE;
            report_xml xml; found_concept text; found_context text; found_fact_id text;
            found_value text; found_unit text; found_header text; header_parts xml[]; header_match text[];
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
      SELECT * INTO reference FROM sec_statement_report_references WHERE id=NEW.statement_report_reference_id;
      SELECT * INTO fact FROM sec_raw_xbrl_facts WHERE id=NEW.raw_fact_id;
      IF reference.id IS NULL OR fact.id IS NULL OR reference.parse_run_id<>NEW.parse_run_id
         OR fact.parse_run_id<>NEW.parse_run_id OR reference.report_sha256<>NEW.report_sha256
         OR reference.report_ordinal<>NEW.report_ordinal OR NEW.known_at<>reference.known_at
         OR NEW.created_txid<>reference.created_txid OR NEW.created_txid<>fact.created_txid
      THEN RAISE EXCEPTION 'SEC statement occurrence lineage mismatch'; END IF;
      BEGIN report_xml:=xmlparse(document convert_from(reference.report_content,'UTF8'));
      EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'invalid retained statement report XML'; END;
      found_concept:=btrim(((xpath(format('/Report/Rows/Row[%s]/ElementName/text()',NEW.row_ordinal),report_xml))[1])::text,'"');
      IF position(':' in found_concept)=0 THEN found_concept:=regexp_replace(found_concept,'_',':'); END IF;
      found_context:=btrim(((xpath(format('/Report/Rows/Row[%s]/Cells/Cell[%s]/@contextRef',NEW.row_ordinal,NEW.column_ordinal),report_xml))[1])::text,'"');
      found_fact_id:=btrim(((xpath(format('/Report/Rows/Row[%s]/Cells/Cell[%s]/@factId',NEW.row_ordinal,NEW.column_ordinal),report_xml))[1])::text,'"');
      found_unit:=btrim(((xpath(format('/Report/Rows/Row[%s]/Cells/Cell[%s]/@unitRef',NEW.row_ordinal,NEW.column_ordinal),report_xml))[1])::text,'"');
      found_value:=btrim(((xpath(format('/Report/Rows/Row[%s]/Cells/Cell[%s]/NumericAmount/text()',NEW.row_ordinal,NEW.column_ordinal),report_xml))[1])::text,'"');
      header_parts:=xpath(format('/Report/Columns/Column[%s]/Labels/Label/@Label',NEW.column_ordinal),report_xml);
      SELECT btrim(string_agg(btrim(value::text,'"'), ' ')) INTO found_header FROM unnest(header_parts) value;
      header_match:=regexp_match(found_header,'(January|February|March|April|May|June|July|August|September|October|November|December)[[:space:]]+([0-9]{1,2}),?[[:space:]]+([0-9]{4})','i');
      IF found_concept IS DISTINCT FROM NEW.concept OR found_context IS DISTINCT FROM NEW.context_id
         OR found_fact_id IS DISTINCT FROM NEW.fact_id OR btrim(regexp_replace(coalesce(found_value,''),'\\s+',' ','g'))<>NEW.raw_value
         OR found_unit IS DISTINCT FROM NEW.unit_id OR found_header IS DISTINCT FROM NEW.header_raw
         OR header_match IS NULL OR to_date(header_match[1]||header_match[2]||header_match[3],'MonthDDYYYY')<>NEW.header_date
         OR btrim(regexp_replace(NEW.header_raw,'\\s+',' ','g'))<>NEW.header_normalized
         OR fact.context_id IS DISTINCT FROM NEW.context_id OR fact.concept<>NEW.concept
         OR btrim(regexp_replace(coalesce(fact.raw_value,''),'\\s+',' ','g'))<>NEW.raw_value
         OR fact.unit_id IS DISTINCT FROM NEW.unit_id
         OR NEW.fact_id IS NOT NULL AND fact.locator_json->>'element_id' IS DISTINCT FROM NEW.fact_id
      THEN RAISE EXCEPTION 'statement occurrence mismatch found=%,%,%,%,%,% expected=%,%,%,%,%,%', found_concept,found_context,found_fact_id,found_value,found_unit,found_header,NEW.concept,NEW.context_id,NEW.fact_id,NEW.raw_value,NEW.unit_id,NEW.header_raw; END IF;
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
    CREATE TRIGGER trg_sec_statement_occurrence_insert BEFORE INSERT ON sec_statement_occurrence_evidence
      FOR EACH ROW EXECUTE FUNCTION guard_sec_statement_occurrence_insert();
    CREATE FUNCTION guard_sec_statement_fact_authority_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE fact sec_raw_xbrl_facts%ROWTYPE; run sec_financial_parse_runs%ROWTYPE;
            artifact sec_filing_artifacts%ROWTYPE; link sec_financial_parse_run_artifacts%ROWTYPE; reference sec_statement_report_references%ROWTYPE;
            occurrence sec_statement_occurrence_evidence%ROWTYPE; current_anchor sec_statement_occurrence_evidence%ROWTYPE; prior_anchor sec_statement_occurrence_evidence%ROWTYPE;
            dei_year integer; dei_period text; expected_class text; expected_fq integer;
            dei_year_count integer; dei_period_count integer; filing_form text;
    BEGIN
      NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
      SELECT * INTO fact FROM sec_raw_xbrl_facts WHERE id=NEW.raw_fact_id;
      SELECT * INTO run FROM sec_financial_parse_runs WHERE id=NEW.parse_run_id;
      SELECT * INTO artifact FROM sec_filing_artifacts WHERE id=NEW.statement_artifact_id;
      SELECT * INTO reference FROM sec_statement_report_references WHERE id=NEW.statement_report_reference_id;
      SELECT * INTO occurrence FROM sec_statement_occurrence_evidence WHERE id=NEW.statement_occurrence_id;
      SELECT * INTO current_anchor FROM sec_statement_occurrence_evidence WHERE id=NEW.current_anchor_occurrence_id;
      SELECT * INTO prior_anchor FROM sec_statement_occurrence_evidence WHERE id=NEW.prior_anchor_occurrence_id;
      SELECT count(DISTINCT btrim(raw.raw_value)) FILTER (WHERE split_part(raw.concept,':',2)='DocumentFiscalYearFocus'),
             count(DISTINCT upper(btrim(raw.raw_value))) FILTER (WHERE split_part(raw.concept,':',2)='DocumentFiscalPeriodFocus'),
             min(btrim(raw.raw_value)) FILTER (WHERE split_part(raw.concept,':',2)='DocumentFiscalYearFocus')::integer,
             min(upper(btrim(raw.raw_value))) FILTER (WHERE split_part(raw.concept,':',2)='DocumentFiscalPeriodFocus')
        INTO dei_year_count,dei_period_count,dei_year,dei_period FROM sec_raw_xbrl_facts raw
       WHERE raw.parse_run_id=NEW.parse_run_id AND raw.dimensions_structured_json='[]'::jsonb
         AND raw.concept_namespace_uri IN ('http://xbrl.sec.gov/dei/2014-01-31','http://xbrl.sec.gov/dei/2018-01-31','http://xbrl.sec.gov/dei/2019-01-31','http://xbrl.sec.gov/dei/2020-01-31','http://xbrl.sec.gov/dei/2021','http://xbrl.sec.gov/dei/2021q4','http://xbrl.sec.gov/dei/2022','http://xbrl.sec.gov/dei/2023','http://xbrl.sec.gov/dei/2024','http://xbrl.sec.gov/dei/2025','http://xbrl.sec.gov/dei/2026');
      SELECT upper(filing.form_type) INTO filing_form FROM sec_financial_filings filing WHERE filing.id=run.filing_id;
      expected_fq:=CASE WHEN dei_period ~ '^Q[1-3]$' THEN right(dei_period,1)::integer ELSE NULL END;
      expected_class:=CASE WHEN occurrence.header_date=current_anchor.header_date THEN 'current_period'
        WHEN reference.statement_type='balance_sheet' AND (SELECT period_start FROM sec_raw_xbrl_facts WHERE id=occurrence.raw_fact_id) IS NULL THEN 'prior_fiscal_year_balance_sheet'
        WHEN lower(occurrence.header_raw) LIKE '%three months ended%' THEN 'prior_same_fiscal_quarter'
        WHEN lower(occurrence.header_raw) LIKE '%year ended%' OR lower(occurrence.header_raw) LIKE '%twelve months ended%' THEN 'prior_fiscal_year_comparative' END;
      SELECT * INTO link FROM sec_financial_parse_run_artifacts
       WHERE parse_run_id=NEW.parse_run_id AND artifact_id=NEW.statement_artifact_id;
      IF fact.id IS NULL OR run.id IS NULL OR artifact.id IS NULL OR link.id IS NULL OR reference.id IS NULL OR occurrence.id IS NULL OR current_anchor.id IS NULL
         OR dei_year_count<>1 OR dei_period_count<>1
         OR filing_form NOT IN ('10-Q','10-Q/A','10-K','10-K/A','20-F','20-F/A')
         OR (filing_form IN ('10-Q','10-Q/A') AND dei_period NOT IN ('Q1','Q2','Q3'))
         OR (filing_form IN ('10-K','10-K/A','20-F','20-F/A') AND (dei_period<>'FY' OR NEW.fiscal_quarter_ordinal IS NOT NULL))
         OR (NEW.presentation_class='current_period' AND NEW.fiscal_year<>dei_year)
         OR fact.parse_run_id<>NEW.parse_run_id OR fact.context_id IS DISTINCT FROM NEW.context_id
         OR reference.parse_run_id<>NEW.parse_run_id OR reference.report_artifact_id<>NEW.statement_artifact_id
         OR reference.report_ordinal<>NEW.report_ordinal
         OR reference.report_sha256<>NEW.statement_sha256 OR reference.report_byte_size<>NEW.statement_byte_size
         OR reference.statement_role<>NEW.statement_role OR reference.statement_type<>NEW.statement_type
         OR reference.report_name<>NEW.report_name
         OR occurrence.raw_fact_id<>NEW.raw_fact_id OR occurrence.statement_report_reference_id<>reference.id
         OR current_anchor.statement_report_reference_id<>reference.id
         OR current_anchor.row_ordinal<>occurrence.row_ordinal OR current_anchor.concept<>occurrence.concept
         OR current_anchor.header_date<>(SELECT filing.report_date FROM sec_financial_parse_runs pr JOIN sec_financial_filings filing ON filing.id=pr.filing_id WHERE pr.id=NEW.parse_run_id)
         OR (prior_anchor.id IS NOT NULL AND (prior_anchor.row_ordinal<>occurrence.row_ordinal OR prior_anchor.concept<>occurrence.concept))
         OR occurrence.occurrence_ordinal<>NEW.occurrence_ordinal OR occurrence.locator_json<>NEW.locator_json
         OR occurrence.header_date<>NEW.statement_period_end
         OR expected_class IS NULL OR NEW.presentation_class<>expected_class
         OR NEW.fiscal_year<>(CASE WHEN expected_class='current_period' THEN dei_year ELSE dei_year-1 END)
         OR NEW.fiscal_quarter_ordinal IS DISTINCT FROM (CASE WHEN expected_class IN ('current_period','prior_same_fiscal_quarter') THEN expected_fq ELSE NULL END)
         OR NEW.fiscal_year_start<>(CASE WHEN NEW.presentation_class='current_period' THEN
              (SELECT period_start FROM sec_raw_xbrl_facts WHERE id=current_anchor.raw_fact_id)
              ELSE (SELECT period_start FROM sec_raw_xbrl_facts WHERE id=prior_anchor.raw_fact_id) END)
         OR (NEW.presentation_class='current_period' AND NEW.prior_anchor_occurrence_id IS NOT NULL)
         OR (NEW.presentation_class<>'current_period' AND (prior_anchor.id IS NULL OR prior_anchor.statement_report_reference_id<>reference.id))
         OR (prior_anchor.id IS NOT NULL AND (
              prior_anchor.column_ordinal<=current_anchor.column_ordinal
              OR current_anchor.header_date-prior_anchor.header_date NOT BETWEEN 350 AND 380
              OR abs(((SELECT period_end-period_start FROM sec_raw_xbrl_facts WHERE id=current_anchor.raw_fact_id))
                   - ((SELECT period_end-period_start FROM sec_raw_xbrl_facts WHERE id=prior_anchor.raw_fact_id)))>14
              OR CASE dei_period
                   WHEN 'Q1' THEN lower(current_anchor.header_raw) NOT LIKE '%three months ended%' OR lower(prior_anchor.header_raw) NOT LIKE '%three months ended%'
                   WHEN 'Q2' THEN lower(current_anchor.header_raw) NOT LIKE '%six months ended%' OR lower(prior_anchor.header_raw) NOT LIKE '%six months ended%'
                   WHEN 'Q3' THEN lower(current_anchor.header_raw) NOT LIKE '%nine months ended%' OR lower(prior_anchor.header_raw) NOT LIKE '%nine months ended%'
                   WHEN 'FY' THEN (lower(current_anchor.header_raw) NOT LIKE '%year ended%' AND lower(current_anchor.header_raw) NOT LIKE '%twelve months ended%')
                                  OR (lower(prior_anchor.header_raw) NOT LIKE '%year ended%' AND lower(prior_anchor.header_raw) NOT LIKE '%twelve months ended%')
                   ELSE true END
              OR EXISTS (SELECT 1 FROM sec_statement_occurrence_evidence middle
                    WHERE middle.statement_report_reference_id=reference.id
                      AND middle.row_ordinal=current_anchor.row_ordinal AND middle.concept=current_anchor.concept
                      AND middle.column_ordinal>current_anchor.column_ordinal AND middle.column_ordinal<prior_anchor.column_ordinal
                      AND CASE dei_period
                           WHEN 'Q1' THEN lower(middle.header_raw) LIKE '%three months ended%'
                           WHEN 'Q2' THEN lower(middle.header_raw) LIKE '%six months ended%'
                           WHEN 'Q3' THEN lower(middle.header_raw) LIKE '%nine months ended%'
                           WHEN 'FY' THEN lower(middle.header_raw) LIKE '%year ended%' OR lower(middle.header_raw) LIKE '%twelve months ended%'
                           ELSE false END)))
         OR NEW.occurrence_fact_id IS NOT NULL AND NEW.occurrence_fact_id IS DISTINCT FROM fact.locator_json->>'element_id'
         OR NEW.occurrence_semantic_sha256<>encode(sha256(convert_to(
              occurrence.semantic_sha256||chr(31)||NEW.presentation_class||chr(31)||NEW.current_anchor_occurrence_id||chr(31)||coalesce(NEW.prior_anchor_occurrence_id::text,''), 'UTF8')), 'hex')
         OR run.status<>'succeeded' OR run.parser_version<>'xbrl-lineage-v2'
         OR artifact.state<>'retained' OR artifact.filing_id<>run.filing_id
         OR artifact.sha256 IS DISTINCT FROM NEW.statement_sha256
         OR artifact.byte_size IS DISTINCT FROM NEW.statement_byte_size
         OR NEW.known_at<>run.known_at OR NEW.known_at<link.known_at OR NEW.known_at<artifact.known_at
         OR NEW.created_txid<>run.created_txid OR NEW.created_txid<>link.created_txid
      THEN RAISE EXCEPTION 'SEC statement presentation authority mismatch'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_sec_statement_fact_authority_insert
      BEFORE INSERT ON sec_statement_fact_authorities FOR EACH ROW
      EXECUTE FUNCTION guard_sec_statement_fact_authority_insert();
    CREATE FUNCTION reject_sec_statement_fact_authority_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'SEC statement authority is append-only'; END $$;
    CREATE TRIGGER trg_sec_statement_fact_authority_update_delete
      BEFORE UPDATE OR DELETE ON sec_statement_fact_authorities FOR EACH ROW
      EXECUTE FUNCTION reject_sec_statement_fact_authority_mutation();
    CREATE TRIGGER trg_sec_statement_fact_authority_truncate BEFORE TRUNCATE ON sec_statement_fact_authorities
      FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_statement_fact_authority_mutation();
    CREATE TRIGGER trg_sec_statement_report_reference_update_delete BEFORE UPDATE OR DELETE ON sec_statement_report_references
      FOR EACH ROW EXECUTE FUNCTION reject_sec_statement_fact_authority_mutation();
    CREATE TRIGGER trg_sec_statement_report_reference_truncate BEFORE TRUNCATE ON sec_statement_report_references
      FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_statement_fact_authority_mutation();
    CREATE TRIGGER trg_sec_statement_occurrence_update_delete BEFORE UPDATE OR DELETE ON sec_statement_occurrence_evidence
      FOR EACH ROW EXECUTE FUNCTION reject_sec_statement_fact_authority_mutation();
    CREATE TRIGGER trg_sec_statement_occurrence_truncate BEFORE TRUNCATE ON sec_statement_occurrence_evidence
      FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_statement_fact_authority_mutation();
    """)


def downgrade() -> None:
    op.execute("LOCK TABLE sec_statement_fact_authorities, sec_statement_occurrence_evidence, sec_statement_report_references IN ACCESS EXCLUSIVE MODE")
    count = op.get_bind().execute(sa.text("SELECT (SELECT count(*) FROM sec_statement_fact_authorities) + (SELECT count(*) FROM sec_statement_occurrence_evidence) + (SELECT count(*) FROM sec_statement_report_references)")).scalar_one()
    if count:
        raise RuntimeError("downgrade refused: retained SEC statement authority exists")
    op.drop_table("sec_statement_fact_authorities")
    op.drop_table("sec_statement_occurrence_evidence")
    op.drop_table("sec_statement_report_references")
    op.execute("DROP FUNCTION guard_sec_statement_report_reference_insert()")
    op.execute("DROP FUNCTION guard_sec_statement_occurrence_insert()")
    op.execute("DROP FUNCTION reject_sec_statement_fact_authority_mutation()")
    op.execute("DROP FUNCTION guard_sec_statement_fact_authority_insert()")
