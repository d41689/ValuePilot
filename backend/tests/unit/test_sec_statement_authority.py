from dataclasses import replace
from datetime import date

import pytest

from app.services.sec_statement_authority import (
    MAX_FILING_SUMMARY_BYTES,
    StatementAuthorityParseError,
    StatementAuthoritySnapshot,
    ExplicitFiscalFocus,
    DeiFocusEvidence,
    PresentedPeriodEvidence,
    RawOccurrenceIdentity,
    authoritative_raw_fact_snapshot,
    classify_statement_occurrence,
    build_explicit_fiscal_focus,
    discover_statement_reports,
    match_statement_occurrence,
    parse_statement_occurrences,
)
from datetime import datetime, timezone
from decimal import Decimal
from app.services.sec_financial_mapping import RawFactSnapshot


def raw(**changes):
    values = dict(raw_fact_id=1, parse_run_id=10, normalization_id=1,
        namespace_uri="http://fasb.org/us-gaap/2026", local_name="Assets",
        normalized_value=Decimal("1"), unit_numerator=(), unit_denominator=(),
        context_id="C1", dimensions=(), form="10-Q", period_start=None,
        period_end=date(2026, 3, 31), statement_period_end=date(2026, 3, 31),
        fiscal_year=2026, fiscal_quarter_ordinal=1, fiscal_year_start=date(2026, 1, 1),
        stock_id=1, filing_authority_id="f", publication_cutoff=datetime(2026, 4, 1, tzinfo=timezone.utc),
        fiscal_cycle="filing_quarter_end", amendment_policy_id="a",
        known_at=datetime(2026, 4, 1, tzinfo=timezone.utc), is_nil=False)
    values.update(changes); return RawFactSnapshot(**values)


def test_filing_summary_discovers_only_safe_financial_statements_in_order():
    content = b"""<FilingSummary><MyReports>
      <Report><Position>2</Position><ShortName>Balance Sheets</ShortName><Role>role/BalanceSheet</Role><HtmlFileName>R1.htm</HtmlFileName></Report>
      <Report><ShortName>Notes</ShortName><HtmlFileName>R2.htm</HtmlFileName></Report>
      <Report><Position>3</Position><ShortName>Statements of Operations</ShortName><XmlFileName>R3.xml</XmlFileName></Report>
    </MyReports></FilingSummary>"""
    reports = discover_statement_reports(content)
    assert [(item.report_ordinal, item.filename, item.statement_type) for item in reports] == [
        (2, "R1.htm", "balance_sheet"), (3, "R3.xml", "income_statement")]


@pytest.mark.parametrize("content,reason", [
    (b"<broken", "malformed_filing_summary"),
    (b"<FilingSummary><Report><Position>1</Position><ShortName>Balance Sheet</ShortName><HtmlFileName>../R1.htm</HtmlFileName></Report></FilingSummary>", "unsafe_statement_report_reference"),
    (b"<!DOCTYPE x [<!ENTITY y 'z'>]><FilingSummary>&y;</FilingSummary>", "unsafe_xml_declaration"),
    (b"x" * (MAX_FILING_SUMMARY_BYTES + 1), "filing_summary_exceeds_byte_limit"),
])
def test_filing_summary_fails_closed(content, reason):
    with pytest.raises(StatementAuthorityParseError, match=reason): discover_statement_reports(content)


def test_statement_report_requires_explicit_context_occurrence_and_metadata():
    content = b'''<Report><Columns><Column><Labels><Label Label="As of December 31, 2025"/></Labels></Column></Columns>
      <Rows><Row><ElementName>us-gaap:Assets</ElementName><Cells><Cell contextRef="C1" factId="fact-assets" unitRef="USD"><NumericAmount>1</NumericAmount></Cell></Cells></Row></Rows></Report>'''
    item = parse_statement_occurrences(content, filename="R1.xml")[0]
    assert item.context_id == "C1"
    assert item.fact_id == "fact-assets"
    assert item.column_header == "As of December 31, 2025"
    classified = classify_statement_occurrence(item, statement_type="balance_sheet", period_start=None,
        period_end=date(2025, 12, 31), focus=ExplicitFiscalFocus(date(2026, 3, 31), 2026, 1, date(2026, 1, 1), date(2025, 1, 1)))
    assert classified.presentation_class == "prior_fiscal_year_balance_sheet"
    with pytest.raises(StatementAuthorityParseError, match="no_explicit_statement_occurrences"):
        parse_statement_occurrences(b"<td>an earlier date</td>", filename="R1.htm")


def test_occurrence_identity_prefers_fact_id_and_never_last_write_wins():
    occurrence = parse_statement_occurrences(b'''<Report><Columns><Column><Labels><Label Label="Three Months Ended March 31, 2026"/></Labels></Column></Columns><Rows><Row><ElementName>us-gaap:Revenue</ElementName><Cells><Cell contextRef="C" factId="f2" unitRef="USD"><NumericAmount>11</NumericAmount></Cell></Cells></Row></Rows></Report>''', filename="R.xml")[0]
    rows = [RawOccurrenceIdentity(1, "C", "us-gaap:Revenue", "10", "USD", "f1"),
            RawOccurrenceIdentity(2, "C", "us-gaap:Revenue", "11", "USD", "f2")]
    assert match_statement_occurrence(occurrence, rows) == 2
    without_id = replace(occurrence, fact_id=None, raw_value="11")
    with pytest.raises(StatementAuthorityParseError, match="ambiguous"):
        match_statement_occurrence(without_id, rows + [RawOccurrenceIdentity(3, "C", "us-gaap:Revenue", "11", "USD", None)])


@pytest.mark.parametrize("header,start,end,kind,expected", [
    ("Three Months Ended March 31, 2025", date(2025, 1, 1), date(2025, 3, 31), "income_statement", "prior_same_fiscal_quarter"),
    ("Year Ended December 31, 2025", date(2025, 1, 1), date(2025, 12, 31), "income_statement", "prior_fiscal_year_comparative"),
])
def test_real_statement_columns_prove_prior_q_and_prior_fy(header, start, end, kind, expected):
    xml = f'''<Report><Columns><Column><Labels><Label Label="{header}"/></Labels></Column></Columns><Rows><Row><ElementName>us-gaap:Revenue</ElementName><Cells><Cell contextRef="C" factId="f" unitRef="USD"><NumericAmount>1</NumericAmount></Cell></Cells></Row></Rows></Report>'''.encode()
    occurrence = parse_statement_occurrences(xml, filename="R.xml")[0]
    result = classify_statement_occurrence(occurrence, statement_type=kind, period_start=start, period_end=end,
        focus=ExplicitFiscalFocus(date(2026, 3, 31), 2026, 1, date(2026, 1, 1), date(2025, 1, 1)))
    assert result.presentation_class == expected


def test_header_date_alone_cannot_prove_presentation():
    occurrence = parse_statement_occurrences(b'''<Report><Columns><Column><Labels><Label Label="March 31, 2025"/></Labels></Column></Columns><Rows><Row><ElementName>us-gaap:Revenue</ElementName><Cells><Cell contextRef="C"><NumericAmount>1</NumericAmount></Cell></Cells></Row></Rows></Report>''', filename="R.xml")[0]
    with pytest.raises(StatementAuthorityParseError, match="unproven_statement_period_class"):
        classify_statement_occurrence(occurrence, statement_type="income_statement", period_start=date(2025, 1, 1),
            period_end=date(2025, 3, 31), focus=ExplicitFiscalFocus(date(2026, 3, 31), 2026, 1, date(2026, 1, 1)))


DEI = "http://xbrl.sec.gov/dei/2026"
def _dei(namespace=DEI, period="Q3"):
    return [DeiFocusEvidence(namespace, "DocumentFiscalYearFocus", "2026", ()),
            DeiFocusEvidence(namespace, "DocumentFiscalPeriodFocus", period, ())]


def test_fiscal_focus_rejects_custom_namespace_collision_and_discrete_only_q3():
    discrete = [PresentedPeriodEvidence("Three Months Ended September 30, 2026", date(2026, 7, 1), date(2026, 9, 30))]
    with pytest.raises(StatementAuthorityParseError, match="missing_exact_dei"):
        build_explicit_fiscal_focus(dei_facts=_dei("urn:custom-dei"), presented_periods=discrete,
            form="10-Q", statement_period_end=date(2026, 9, 30), approved_dei_namespaces=(DEI,))
    with pytest.raises(StatementAuthorityParseError, match="missing_unproven_current"):
        build_explicit_fiscal_focus(dei_facts=_dei(), presented_periods=discrete,
            form="10-Q", statement_period_end=date(2026, 9, 30), approved_dei_namespaces=(DEI,))


@pytest.mark.parametrize("dei_facts,form", [
    (_dei() + [DeiFocusEvidence(DEI, "DocumentFiscalYearFocus", "2025", ())], "10-Q"),
    (_dei() + [DeiFocusEvidence(DEI, "DocumentFiscalPeriodFocus", "Q2", ())], "10-Q"),
    ([DeiFocusEvidence(DEI, "DocumentFiscalPeriodFocus", "Q3", ())], "10-Q"),
])
def test_fiscal_focus_rejects_missing_or_conflicting_exact_dei_values(dei_facts, form):
    periods = [PresentedPeriodEvidence("Nine Months Ended September 30, 2026",
        date(2026, 1, 1), date(2026, 9, 30), "ref", 1, "Revenue", 1)]
    with pytest.raises(StatementAuthorityParseError, match="missing_exact_dei"):
        build_explicit_fiscal_focus(dei_facts=dei_facts, presented_periods=periods,
            form=form, statement_period_end=date(2026, 9, 30), approved_dei_namespaces=(DEI,))


@pytest.mark.parametrize(("form", "period"), [("10-Q", "FY"), ("10-K", "Q3"), ("6-K", "Q3")])
def test_fiscal_focus_rejects_form_period_mismatch_and_unsupported_6k(form, period):
    with pytest.raises(StatementAuthorityParseError, match="dei_fiscal_period_form_mismatch"):
        build_explicit_fiscal_focus(dei_facts=_dei(period=period), presented_periods=[],
            form=form, statement_period_end=date(2026, 9, 30), approved_dei_namespaces=(DEI,))


def test_q3_cycle_start_requires_matching_explicit_ytd_current_and_prior():
    periods = [
        PresentedPeriodEvidence("Nine Months Ended September 30, 2026", date(2026, 1, 1), date(2026, 9, 30), "ref", 4, "Revenue", 2),
        PresentedPeriodEvidence("Nine Months Ended September 30, 2025", date(2025, 1, 1), date(2025, 9, 30), "ref", 4, "Revenue", 4),
    ]
    focus = build_explicit_fiscal_focus(dei_facts=_dei(), presented_periods=periods,
        form="10-Q", statement_period_end=date(2026, 9, 30), approved_dei_namespaces=(DEI,))
    assert focus.fiscal_year_start == date(2026, 1, 1)
    assert focus.prior_fiscal_year_start == date(2025, 1, 1)
    mismatched = [replace(periods[0], column_header="Six Months Ended September 30, 2026")]
    with pytest.raises(StatementAuthorityParseError, match="missing_unproven_current"):
        build_explicit_fiscal_focus(dei_facts=_dei(), presented_periods=mismatched,
            form="10-Q", statement_period_end=date(2026, 9, 30), approved_dei_namespaces=(DEI,))
    wrong_prior = [periods[0], replace(periods[1], row_ordinal=99)]
    unpaired = build_explicit_fiscal_focus(dei_facts=_dei(), presented_periods=wrong_prior,
        form="10-Q", statement_period_end=date(2026, 9, 30), approved_dei_namespaces=(DEI,))
    assert unpaired.prior_fiscal_year_start is None
    bad_header_date = [replace(periods[0], column_header="Nine Months Ended September 29, 2026")]
    with pytest.raises(StatementAuthorityParseError, match="missing_unproven_current"):
        build_explicit_fiscal_focus(dei_facts=_dei(), presented_periods=bad_header_date,
            form="10-Q", statement_period_end=date(2026, 9, 30), approved_dei_namespaces=(DEI,))


@pytest.mark.parametrize(("form", "period", "current_header", "current_start", "current_end",
                          "prior_header", "prior_start", "prior_end"), [
    ("10-Q", "Q1", "Three Months Ended December 27, 2025", date(2025, 9, 28), date(2025, 12, 27),
     "Three Months Ended December 28, 2024", date(2024, 9, 29), date(2024, 12, 28)),
    ("10-K", "FY", "Year Ended December 27, 2025", date(2024, 12, 22), date(2025, 12, 27),
     "Year Ended December 28, 2024", date(2023, 12, 31), date(2024, 12, 28)),
])
def test_non_calendar_fy_labels_and_53_week_cycles_use_explicit_context_dates(
    form, period, current_header, current_start, current_end,
    prior_header, prior_start, prior_end,
):
    periods = [
        PresentedPeriodEvidence(current_header, current_start, current_end, "ref", 7, "Revenue", 2),
        PresentedPeriodEvidence(prior_header, prior_start, prior_end, "ref", 7, "Revenue", 4),
    ]
    focus = build_explicit_fiscal_focus(dei_facts=_dei(period=period), presented_periods=periods,
        form=form, statement_period_end=current_end, approved_dei_namespaces=(DEI,))
    assert focus.fiscal_year == 2026
    assert focus.fiscal_year_start == current_start
    assert focus.prior_fiscal_year_start == prior_start

    mismatched = [replace(periods[0], column_header=current_header.replace("27", "26", 1)), periods[1]]
    with pytest.raises(StatementAuthorityParseError, match="missing_unproven_current"):
        build_explicit_fiscal_focus(dei_facts=_dei(period=period), presented_periods=mismatched,
            form=form, statement_period_end=current_end, approved_dei_namespaces=(DEI,))


def test_prior_cycle_anchor_requires_immediately_prior_eligible_column_and_cadence():
    current = PresentedPeriodEvidence("Nine Months Ended December 27, 2025",
        date(2025, 3, 30), date(2025, 12, 27), "ref", 8, "Revenue", 2)
    prior = PresentedPeriodEvidence("Nine Months Ended December 28, 2024",
        date(2024, 3, 31), date(2024, 12, 28), "ref", 8, "Revenue", 3)
    two_year = PresentedPeriodEvidence("Nine Months Ended December 30, 2023",
        date(2023, 4, 2), date(2023, 12, 30), "ref", 8, "Revenue", 4)
    focus = build_explicit_fiscal_focus(dei_facts=_dei(period="Q3"),
        presented_periods=[current, prior, two_year], form="10-Q",
        statement_period_end=current.period_end, approved_dei_namespaces=(DEI,))
    assert focus.prior_fiscal_year_start == prior.period_start

    with pytest.raises(StatementAuthorityParseError, match="unproven_prior_fiscal_cycle_anchor"):
        build_explicit_fiscal_focus(dei_facts=_dei(period="Q3"),
            presented_periods=[current, two_year], form="10-Q",
            statement_period_end=current.period_end, approved_dei_namespaces=(DEI,))

    with pytest.raises(StatementAuthorityParseError, match="unproven_prior_fiscal_cycle_anchor"):
        build_explicit_fiscal_focus(dei_facts=_dei(period="Q3"),
            presented_periods=[current, replace(prior, column_ordinal=1)], form="10-Q",
            statement_period_end=current.period_end, approved_dei_namespaces=(DEI,))


def test_prior_fy_instant_without_explicit_prior_cycle_start_stays_unproven():
    occurrence = parse_statement_occurrences(b'''<Report><Columns><Column><Labels><Label Label="As of December 31, 2025"/></Labels></Column></Columns><Rows><Row><ElementName>us-gaap_Assets</ElementName><Cells><Cell contextRef="I"><NumericAmount>1</NumericAmount></Cell></Cells></Row></Rows></Report>''', filename="R.xml")[0]
    with pytest.raises(StatementAuthorityParseError, match="unproven_statement_presentation_class"):
        classify_statement_occurrence(occurrence, statement_type="balance_sheet", period_start=None,
            period_end=date(2025, 12, 31), focus=ExplicitFiscalFocus(date(2026, 3, 31), 2026, 1, date(2026, 1, 1), None))


def _authority(**changes):
    values = dict(raw_fact_id=1, parse_run_id=10, context_id="C1",
                  presentation_class="prior_same_fiscal_quarter",
                  statement_period_end=date(2025, 3, 31), fiscal_year=2025,
                  fiscal_quarter_ordinal=1, fiscal_year_start=date(2025, 1, 1),
                  report_ordinal=2, occurrence_ordinal=1)
    values.update(changes)
    return StatementAuthoritySnapshot(**values)


def test_adapter_selects_deterministically_and_rejects_conflicting_or_missing_authority():
    base = raw(statement_period_end=date(1900, 1, 1), fiscal_cycle="untrusted")
    restored = authoritative_raw_fact_snapshot(base, [_authority(report_ordinal=3), _authority(report_ordinal=1)])
    assert restored.statement_period_end == date(2025, 3, 31)
    assert restored.fiscal_cycle == "explicit_prior_same_fiscal_quarter_comparative"
    with pytest.raises(StatementAuthorityParseError, match="conflicting"):
        authoritative_raw_fact_snapshot(base, [_authority(), _authority(statement_period_end=date(2024, 3, 31))])
    with pytest.raises(StatementAuthorityParseError, match="missing"):
        authoritative_raw_fact_snapshot(replace(base, raw_fact_id=99), [_authority()])
