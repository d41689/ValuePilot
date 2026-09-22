from dataclasses import replace
from datetime import date
import hashlib

import pytest

from app.services.sec_statement_authority import (
    MAX_FILING_SUMMARY_BYTES,
    StatementAuthorityParseError,
    StatementAuthoritySnapshot,
    StatementOccurrence,
    ExplicitFiscalFocus,
    DeiFocusEvidence,
    PresentedPeriodEvidence,
    RawOccurrenceIdentity,
    authoritative_raw_fact_snapshot,
    classify_statement_occurrence,
    build_explicit_fiscal_focus,
    discover_statement_reports,
    match_statement_occurrence,
    parse_generated_statement_occurrences,
    parse_statement_occurrences,
    _display_decimal,
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
      <Report><Position>3</Position><ShortName>Statements of Operations</ShortName><Role>role/IncomeStatement</Role><XmlFileName>R3.xml</XmlFileName></Report>
    </MyReports></FilingSummary>"""
    reports = discover_statement_reports(content)
    assert [(item.report_ordinal, item.filename, item.statement_type) for item in reports] == [
        (2, "R1.htm", "balance_sheet"), (3, "R3.xml", "income_statement")]


def test_filing_summary_classifies_real_compact_cash_flow_and_named_balance_reports():
    content = b"""<FilingSummary><MyReports>
      <Report><Position>4</Position>
        <LongName>9952153 - Statement - CONDENSED CONSOLIDATED BALANCE SHEETS (Unaudited)</LongName>
        <Role>http://www.apple.com/role/CONDENSEDCONSOLIDATEDBALANCESHEETSUnaudited</Role>
        <ShortName>CONDENSED CONSOLIDATED BALANCE SHEETS (Unaudited)</ShortName>
        <HtmlFileName>R4.htm</HtmlFileName></Report>
      <Report><Position>7</Position>
        <LongName>9952156 - Statement - CONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS (Unaudited)</LongName>
        <Role>http://www.apple.com/role/CONDENSEDCONSOLIDATEDSTATEMENTSOFCASHFLOWSUnaudited</Role>
        <ShortName>CONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS (Unaudited)</ShortName>
        <HtmlFileName>R7.htm</HtmlFileName></Report>
    </MyReports></FilingSummary>"""

    reports = discover_statement_reports(
        content,
        allow_compact_statement_names=True,
    )

    assert [(item.filename, item.statement_type) for item in reports] == [
        ("R4.htm", "balance_sheet"),
        ("R7.htm", "cash_flow"),
    ]


def test_v26_filing_summary_requires_recognized_compact_role_and_consistent_name():
    valid = b"""<FilingSummary><Report><Position>4</Position>
      <Role>http://www.apple.com/taxonomy/role/StatementOfFinancialPositionClassified</Role>
      <ShortName>CONDENSED CONSOLIDATED BALANCE SHEETS</ShortName>
      <HtmlFileName>R4.htm</HtmlFileName></Report></FilingSummary>"""
    reports = discover_statement_reports(
        valid,
        allow_compact_statement_names=True,
        require_recognized_statement_role=True,
    )
    assert reports[0].statement_type == "balance_sheet"

    unknown_role = valid.replace(
        b"StatementOfFinancialPositionClassified", b"UnrecognizedStatement"
    )
    with pytest.raises(StatementAuthorityParseError, match="no_statement_reports"):
        discover_statement_reports(
            unknown_role,
            allow_compact_statement_names=True,
            require_recognized_statement_role=True,
        )

    conflicting_name = valid.replace(
        b"CONDENSED CONSOLIDATED BALANCE SHEETS",
        b"CONSOLIDATED STATEMENTS OF OPERATIONS",
    )
    with pytest.raises(StatementAuthorityParseError, match="conflicting_statement_role_name"):
        discover_statement_reports(
            conflicting_name,
            allow_compact_statement_names=True,
            require_recognized_statement_role=True,
        )


@pytest.mark.parametrize("role", [None, "", "role/UnrecognizedStatement"])
def test_generated_statement_reference_requires_nonempty_recognized_role(role):
    role_xml = "" if role is None else f"<Role>{role}</Role>"
    content = f"""<FilingSummary><Report><Position>1</Position>
      <ShortName>Statements of Operations</ShortName>{role_xml}
      <HtmlFileName>R1.htm</HtmlFileName></Report></FilingSummary>""".encode()
    with pytest.raises(StatementAuthorityParseError, match="no_statement_reports"):
        discover_statement_reports(content)


def test_filing_summary_rejects_duplicate_position_across_distinct_reports():
    content = b"""<FilingSummary><MyReports>
      <Report><Position>1</Position><Role>role/IncomeStatement</Role><ShortName>Income</ShortName><HtmlFileName>R1.htm</HtmlFileName></Report>
      <Report><Position>1</Position><Role>role/BalanceSheet</Role><ShortName>Balance</ShortName><HtmlFileName>R2.htm</HtmlFileName></Report>
    </MyReports></FilingSummary>"""
    with pytest.raises(StatementAuthorityParseError, match="duplicate_statement_report_reference"):
        discover_statement_reports(content)


@pytest.mark.parametrize(
    ("field", "first", "second"),
    [
        ("Position", "1", "2"),
        ("Role", "role/IncomeStatement", "role/BalanceSheet"),
        ("XmlFileName", "R1.xml", "R2.xml"),
        ("HtmlFileName", "R1.htm", "R2.htm"),
        ("ShortName", "Income", "Operations"),
        ("LongName", "Income Statement", "Operations Statement"),
        ("MenuCategory", "Statements", "Notes"),
    ],
)
def test_filing_summary_rejects_duplicate_authority_bearing_report_children(
    field, first, second
):
    content = f"""<FilingSummary><Report>
      <Position>1</Position><Role>role/IncomeStatement</Role>
      <ShortName>Income</ShortName><HtmlFileName>R1.htm</HtmlFileName>
      <{field}>{first}</{field}><{field}>{second}</{field}>
    </Report></FilingSummary>""".encode()
    with pytest.raises(
        StatementAuthorityParseError,
        match="ambiguous_statement_report_field",
    ):
        discover_statement_reports(content)


@pytest.mark.parametrize("content,reason", [
    (b"<broken", "malformed_filing_summary"),
    (b"<FilingSummary><Report><Position>1</Position><ShortName>Balance Sheet</ShortName><Role>role/BalanceSheet</Role><HtmlFileName>../R1.htm</HtmlFileName></Report></FilingSummary>", "unsafe_statement_report_reference"),
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


def test_date_only_instant_requires_proven_balance_sheet_statement():
    occurrence = StatementOccurrence(
        "c-current",
        "us-gaap:Assets",
        1,
        {"kind": "sec_generated_statement_html_v2", "row": 2, "column": 2},
        "assets-current",
        "100000000",
        "usd",
        "Jun. 27, 2026",
        "digest",
    )
    focus = ExplicitFiscalFocus(
        date(2026, 6, 27), 2026, 3, date(2025, 9, 28), date(2024, 9, 29)
    )

    classified = classify_statement_occurrence(
        occurrence,
        statement_type="balance_sheet",
        period_start=None,
        period_end=date(2026, 6, 27),
        focus=focus,
        allow_balance_sheet_date_only_instant=True,
    )

    assert classified.presentation_class == "current_period"
    with pytest.raises(StatementAuthorityParseError, match="unproven_statement_period_class"):
        classify_statement_occurrence(
            occurrence,
            statement_type="cash_flow",
            period_start=None,
            period_end=date(2026, 6, 27),
            focus=focus,
            allow_balance_sheet_date_only_instant=True,
        )


def _generated_statement_html(
    *,
    concept: str = "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
    label: str = "Net sales",
    displayed: str = "$ 109,417",
) -> bytes:
    # This is the bounded shape retained in AAPL's old SGML, early inline, and
    # recent inline FilingSummary R*.htm statement reports.
    return f"""<html><body><table>
      <tr><th rowspan="2">CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS
        - USD ($)<br/>shares in Thousands, $ in Millions</th>
        <th colspan="2">3 Months Ended</th><th colspan="2">9 Months Ended</th></tr>
      <tr><th>Jun. 27, 2026</th><th>Jun. 28, 2025</th>
          <th>Jun. 27, 2026</th><th>Jun. 28, 2025</th></tr>
      <tr class="re"><td><a onclick="Show.showAR( this, 'defref_{concept}', window );">{label}</a></td>
          <td class="nump">{displayed}<span></span></td><td></td><td></td><td></td></tr>
    </table></body></html>""".encode()


def _presentation_linkbase(*, concept: str = "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax") -> bytes:
    return f"""<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
      xmlns:xlink="http://www.w3.org/1999/xlink">
      <link:presentationLink xlink:role="http://www.apple.com/role/Operations">
        <link:loc xlink:label="parent" xlink:href="aapl.xsd#us-gaap_StatementLineItems"/>
        <link:loc xlink:label="revenue" xlink:href="aapl.xsd#{concept}"/>
        <link:presentationArc xlink:from="parent" xlink:to="revenue" order="1"
          preferredLabel="http://www.xbrl.org/2003/role/terseLabel"/>
      </link:presentationLink>
    </link:linkbase>""".encode()


def _label_linkbase(*, concept: str = "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
                    label: str = "Net sales") -> bytes:
    return f"""<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
      xmlns:xlink="http://www.w3.org/1999/xlink">
      <link:labelLink>
        <link:loc xlink:label="revenue" xlink:href="aapl.xsd#{concept}"/>
        <link:label xlink:label="revenue-label" xlink:role="http://www.xbrl.org/2003/role/terseLabel"
          xml:lang="en-US">{label}</link:label>
        <link:labelArc xlink:from="revenue" xlink:to="revenue-label" order="1"/>
      </link:labelLink>
    </link:linkbase>""".encode()


def _real_sec_shared_label_resource_linkbase() -> bytes:
    concept = "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax"
    return f"""<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
      xmlns:xlink="http://www.w3.org/1999/xlink">
      <link:labelLink xlink:role="http://www.xbrl.org/2003/role/link">
        <link:loc xlink:label="loc-revenue" xlink:href="aapl.xsd#{concept}"/>
        <link:label xlink:label="lab-revenue" xlink:role="http://www.xbrl.org/2003/role/documentation"
          xml:lang="en-US">Revenue recognized from customer contracts.</link:label>
        <link:label xlink:label="lab-revenue" xlink:role="http://www.xbrl.org/2003/role/label"
          xml:lang="en-US">Net sales</link:label>
        <link:label xlink:label="lab-revenue" xlink:role="http://www.xbrl.org/2003/role/terseLabel"
          xml:lang="en-US">Net sales</link:label>
        <link:label xlink:label="lab-revenue" xlink:role="http://www.xbrl.org/2003/role/terseLabel"
          xml:lang="fr">Ventes nettes</link:label>
        <link:labelArc xlink:from="loc-revenue" xlink:to="lab-revenue"/>
      </link:labelLink>
    </link:linkbase>""".encode()


@pytest.mark.parametrize("variant,reason", [
    ("unused", None),
    ("whitespace_text", None),
    ("legacy", "invalid_label_arc"),
    ("selected", "invalid_label_arc"),
    ("ambiguous_presentation", "invalid_label_arc"),
    ("standard", "invalid_label_arc"),
    ("terse", "invalid_label_arc"),
    ("lookalike_role", "invalid_label_arc"),
    ("padded_role", "invalid_label_arc"),
    ("duplicate_resource", "ambiguous_label_resource"),
    ("duplicate_locator", "ambiguous_label_locator"),
    ("duplicate_arc", "invalid_label_arc"),
    ("unbound_arc", "invalid_label_arc"),
    ("conflicting_label", "unproven_generated_statement_presentation"),
    ("conflicting_amount", "unresolved_generated_statement_occurrence"),
    ("conflicting_context", "ambiguous_generated_statement_occurrence"),
    ("conflicting_dimension", "ambiguous_generated_statement_occurrence"),
])
def test_v210_ignores_only_unused_empty_exact_documentation_labels(variant, reason):
    documentation = b"http://www.xbrl.org/2003/role/documentation"
    labels = _real_sec_shared_label_resource_linkbase().replace(
        b"Revenue recognized from customer contracts.",
        b" \n\t " if variant == "whitespace_text" else b"",
    )
    pre = _presentation_linkbase()
    candidates = [_generated_raw()]
    if variant == "selected":
        pre = pre.replace(b"http://www.xbrl.org/2003/role/terseLabel", documentation)
    if variant == "ambiguous_presentation":
        pre = pre.replace(b"</link:presentationLink>",
            b'<link:presentationArc xlink:from="parent" xlink:to="revenue" order="2"/>'
            b'</link:presentationLink>')
    if variant in {"standard", "terse"}:
        role = b"label" if variant == "standard" else b"terseLabel"
        labels = labels.replace(documentation, b"http://www.xbrl.org/2003/role/unused")
        labels = labels.replace(
            b"role/" + role + b'"\n          xml:lang="en-US">Net sales',
            b"role/" + role + b'"\n          xml:lang="en-US">',
        )
        # Keep documentation nonempty so the failure proves the display role.
        labels = labels.replace(b'role/unused"\n          xml:lang="en-US">',
                                b'role/unused"\n          xml:lang="en-US">Description')
    if variant == "lookalike_role":
        labels = labels.replace(documentation, b"https://example.test/role/documentation")
    if variant == "padded_role":
        labels = labels.replace(documentation, b" " + documentation + b" ")
    if variant == "duplicate_resource":
        labels = labels.replace(b"</link:labelLink>",
            b'<link:label xlink:label="lab-revenue" xlink:role="' + documentation +
            b'" xml:lang="en-US"/></link:labelLink>')
    if variant == "duplicate_locator":
        labels = labels.replace(b"</link:labelLink>",
            b'<link:loc xlink:label="loc-revenue" xlink:href="a.xsd#us-gaap_Assets"/></link:labelLink>')
    if variant == "duplicate_arc":
        labels = labels.replace(b"</link:labelLink>",
            b'<link:labelArc xlink:from="loc-revenue" xlink:to="lab-revenue"/></link:labelLink>')
    if variant == "unbound_arc":
        labels = labels.replace(b'xlink:to="lab-revenue"', b'xlink:to="missing"')
    if variant == "conflicting_label":
        labels = labels.replace(b"</link:labelLink>",
            b'<link:label xlink:label="other" xlink:role="http://www.xbrl.org/2003/role/terseLabel" xml:lang="en-US">Other sales</link:label>'
            b'<link:labelArc xlink:from="loc-revenue" xlink:to="other"/></link:labelLink>')
    if variant == "conflicting_amount":
        candidates = [_generated_raw(raw_value="109418000000")]
    if variant == "conflicting_context":
        candidates.append(_generated_raw(raw_fact_id=12, context_id="other"))
    if variant == "conflicting_dimension":
        candidates.append(_generated_raw(raw_fact_id=12, dimensions=(("axis", "member"),)))
    kwargs = dict(
        filename="R8.htm", statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=pre, label_linkbase=labels, candidates=candidates,
        presentation_artifact_id=21, presentation_sha256="1" * 64,
        label_artifact_id=22, label_sha256="2" * 64,
        allow_unused_empty_documentation=variant != "legacy",
    )
    if reason:
        with pytest.raises(StatementAuthorityParseError, match=reason):
            parse_generated_statement_occurrences(_generated_statement_html(), **kwargs)
    else:
        result = parse_generated_statement_occurrences(_generated_statement_html(), **kwargs)
        assert len(result.occurrences) == 1
        assert result.occurrences[0].raw_value == "109417000000"
        assert result.occurrences[0].locator["row_label"] == "Net sales"
        assert result.candidate_scope == "all_contexts_v1"


@pytest.mark.parametrize(
    "role,displayed,raw_value,enabled,accepted",
    [
        ("http://www.xbrl.org/2009/role/negatedLabel", "(12,715)", "12715000000", True, True),
        ("http://www.xbrl.org/2009/role/negatedLabel", "12,715", "-12715000000", True, True),
        ("http://www.xbrl.org/2009/role/negatedLabel", "0", "0", True, True),
        ("http://www.xbrl.org/2009/role/negatedLabel", "(12,714)", "12715000000", True, False),
        ("http://www.xbrl.org/2009/role/negatedLabel", "12,715", "12715000000", True, False),
        ("http://www.xbrl.org/2003/role/terseLabel", "(12,715)", "12715000000", True, False),
        ("https://example.test/role/negatedLabel", "(12,715)", "12715000000", True, False),
        ("http://www.xbrl.org/2009/role/negatedLabel", "(12,715)", "12715000000", False, False),
    ],
)
def test_generated_negated_label_preserves_raw_sign_and_requires_exact_role(
    role, displayed, raw_value, enabled, accepted
):
    """AAPL cash-outflow presentation is inverted, not a negative raw capex fact."""
    concept = "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment"
    label = "Payments for acquisition of property, plant and equipment"
    original_role = b"http://www.xbrl.org/2003/role/terseLabel"
    kwargs = dict(
        filename="R8.htm",
        statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(concept=concept).replace(
            original_role, role.encode()
        ),
        label_linkbase=_label_linkbase(concept=concept, label=label).replace(
            original_role, role.encode()
        ),
        candidates=[_generated_raw(
            concept=concept.replace("_", ":", 1), raw_value=raw_value
        )],
        presentation_artifact_id=21,
        presentation_sha256="a" * 64,
        label_artifact_id=22,
        label_sha256="b" * 64,
        allow_negated_label=enabled,
    )
    html = _generated_statement_html(concept=concept, label=label, displayed=displayed)
    if not accepted:
        with pytest.raises(StatementAuthorityParseError, match="unresolved_generated_statement_occurrence"):
            parse_generated_statement_occurrences(html, **kwargs)
        return
    result = parse_generated_statement_occurrences(html, **kwargs)
    assert len(result.occurrences) == 1
    occurrence = result.occurrences[0]
    assert occurrence.raw_value == raw_value
    assert occurrence.locator["display_value"] == displayed
    assert occurrence.locator["preferred_label_role"] == role
    assert occurrence.locator["scale_multiplier"] == "1000000"


@pytest.mark.parametrize("variant,accepted", [
    ("valid", True), ("old_version", False), ("unnamed", False),
    ("equity", False), ("dimension_anchor", False), ("dimension_role", False),
    ("duplicate_empty_context", False), ("dimensional_only", False),
    ("wrong_title", False), ("custom_dimension_role", False),
    ("reference_popups", True), ("two_report_tables", False),
])
def test_consolidated_candidate_scope_is_explicit_and_keeps_same_scope_conflicts(variant, accepted):
    name = "CONSOLIDATED STATEMENTS OF CASH FLOWS"
    html = _generated_statement_html().replace(b"CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS", name.encode())
    pre = _presentation_linkbase()
    candidates = [_generated_raw(), _generated_raw(raw_fact_id=12, context_id="retained", dimensions=(("axis", "member"),))]
    if variant == "dimension_anchor":
        html = html.replace(b"</table>", b"<tr><td><a onclick=\"Show.showAR(this, 'defref_us-gaap_StatementEquityComponentsAxis=us-gaap_RetainedEarningsMember', window)\">Retained earnings</a></td></tr></table>")
    if variant == "dimension_role":
        pre = pre.replace(b"</link:presentationLink>", b'<link:loc xlink:label="dim" xlink:href="a.xsd#us-gaap_SegmentAxis"/></link:presentationLink>')
    if variant == "custom_dimension_role":
        candidates[1] = _generated_raw(raw_fact_id=12, context_id="region", dimensions=({"kind":"explicit","axis":{"local_name":"Region","prefix":"custom"},"member":{"local_name":"North","prefix":"custom"}},))
        pre = pre.replace(b"</link:presentationLink>", b'<link:loc xlink:label="dim" xlink:href="a.xsd#alias_Region"/></link:presentationLink>')
    if variant == "duplicate_empty_context":
        candidates.append(_generated_raw(raw_fact_id=13, context_id="other"))
    if variant == "dimensional_only":
        candidates = candidates[1:]
    if variant == "wrong_title":
        html = _generated_statement_html()
    if variant in {"reference_popups", "two_report_tables"}:
        html = html.replace(b'<table>', b'<table class="report">', 1)
        other_class = b'authRefData' if variant == 'reference_popups' else b'report'
        html = html.replace(b'</body>', b'<table class="'+other_class+b'"><tr><td>Taxonomy documentation</td></tr></table></body>')
    result = parse_generated_statement_occurrences(
        html, filename="R8.htm", statement_role="http://www.apple.com/role/Operations",
        statement_type="equity" if variant == "equity" else "cash_flow",
        report_name="" if variant == "unnamed" else name,
        presentation_linkbase=pre, label_linkbase=_label_linkbase(), candidates=candidates,
        presentation_artifact_id=21, presentation_sha256="1"*64,
        label_artifact_id=22, label_sha256="2"*64, allow_partial=True,
        allow_dimension_member_anchors=True,
        allow_consolidated_candidate_scope=variant != "old_version",
    )
    assert bool(result.occurrences) is accepted
    if accepted:
        assert result.candidate_scope == "consolidated_empty_dimensions_v1"
        assert result.occurrences[0].context_id == "c-18"
        assert result.occurrences[0].locator["candidate_scope"] == result.candidate_scope


def _generated_raw(**changes):
    values = dict(
        raw_fact_id=11,
        context_id="c-18",
        concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        raw_value="109417000000",
        unit_id="usd",
        element_id="f-56",
        period_start=date(2026, 3, 29),
        period_end=date(2026, 6, 27),
        dimensions=(),
        unit_numerator=("iso4217:USD",),
        unit_denominator=(),
        decimals="-6",
        scale=None,
        sign=None,
        is_nil=False,
        is_hidden=False,
    )
    values.update(changes)
    return RawOccurrenceIdentity(**values)


@pytest.mark.parametrize("enabled", [False, True])
def test_v211_dollar_accounting_negative_restores_exact_prior_year_anchor(enabled):
    # Minimal retained FY2023 MCO R9 row: all three periods and raw values exist.
    # Losing the middle '$ (1)' creates a false 2023 -> 2021 anchor gap.
    fragment = "us-gaap_OtherComprehensiveIncomeDefinedBenefitPlansNetUnamortizedGainLossArisingDuringPeriodTax"
    label = "Net actuarial gains (losses) and prior service cost, tax"
    content = f'''<table><tr><th rowspan="2">CONSOLIDATED STATEMENT OF SHAREHOLDERS' EQUITY (Parenthetical) - USD ($), $ in Millions</th>
      <th colspan="3">12 Months Ended</th></tr><tr><th>Dec. 31, 2023</th><th>Dec. 31, 2022</th><th>Dec. 31, 2021</th></tr>
      <tr><td><a onclick="Show.showAR(this, 'defref_{fragment}', window)">{label}</a></td><td>(2)</td><td>$ (1)</td><td>$ 18</td></tr></table>'''.encode()
    candidates = [_generated_raw(raw_fact_id=index, context_id=f"c-{year}",
        concept=fragment.replace("_", ":", 1), raw_value=value,
        period_start=date(year, 1, 1), period_end=date(year, 12, 31))
        for index, (year, value) in enumerate(((2023, "-2000000"), (2022, "-1000000"), (2021, "18000000")), 1)]
    result = parse_generated_statement_occurrences(
        content, filename="R9.htm", statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(concept=fragment),
        label_linkbase=_label_linkbase(concept=fragment, label=label), candidates=candidates,
        presentation_artifact_id=21, presentation_sha256="1" * 64,
        label_artifact_id=22, label_sha256="2" * 64,
        allow_dollar_prefixed_negative=enabled,
    )
    periods = [PresentedPeriodEvidence(o.column_header, c.period_start, c.period_end,
        "R9", o.locator["row"], o.concept, o.locator["column"])
        for o in result.occurrences for c in candidates if c.context_id == o.context_id]
    kwargs = dict(dei_facts=[
        DeiFocusEvidence("dei", "DocumentFiscalYearFocus", "2023", ()),
        DeiFocusEvidence("dei", "DocumentFiscalPeriodFocus", "FY", ())],
        presented_periods=periods, form="10-K", statement_period_end=date(2023, 12, 31),
        approved_dei_namespaces=("dei",))
    if not enabled:
        assert len(result.occurrences) == 2
        with pytest.raises(StatementAuthorityParseError, match="unproven_prior_fiscal_cycle_anchor"):
            build_explicit_fiscal_focus(**kwargs)
    else:
        assert [o.raw_value for o in result.occurrences] == ["-2000000", "-1000000", "18000000"]
        assert result.occurrences[1].locator["display_value"] == "$ (1)"
        focus = build_explicit_fiscal_focus(**kwargs)
        assert (focus.fiscal_year_start, focus.prior_fiscal_year_start) == (date(2023, 1, 1), date(2022, 1, 1))


@pytest.mark.parametrize("value,expected", [
    ("$ (1)", Decimal("-1")), ("$(1,234.5)", Decimal("-1234.5")),
    ("$ ( 0 )", Decimal("0")), ("$ (-1)", None), ("$ (+1)", None),
    ("$ (1) trailing", None), ("$ ((1))", None), ("$ (1,23)", None),
    ("$ (NaN)", None), ("$ (Infinity)", None), ("USD (1)", None),
])
def test_v211_dollar_accounting_grammar_is_exact(value, expected):
    assert _display_decimal(value, allow_dollar_prefixed_negative=True) == expected
    assert _display_decimal(value) is None


@pytest.mark.parametrize("variant", [
    "blank", "old_version", "dash", "unknown_text", "missing_cell", "spanned_cell",
    "nonempty_span", "hidden_span", "nested_table", "rowspan", "image",
    "raw_prior_exists", "rejected_raw_prior_exists", "rejected_value", "wrong_header",
    "no_independent_anchor", "no_older_or_independent_anchor", "conflicting_anchor",
    "same_concept_conflicting_anchor", "all_blank",
    "duplicate_blank_colspan", "duplicate_blank_rowspan", "duplicate_current_colspan",
    "duplicate_current_rowspan", "duplicate_blank_class", "duplicate_same_span",
])
def test_v212_explicit_blank_prior_year_is_not_an_older_year_anchor(variant):
    # Retained FY2020 R8 row: 2020 ($16m), a truly blank 2019, 2018 ($1m).
    fragment = "us-gaap_OtherComprehensiveIncomeLossCashFlowHedgeGainLossAfterReclassificationTax"
    concept = fragment.replace("_", ":", 1)
    label = "Net unrealized and unrealized gain on cash flow hedges, tax"
    middle = '<td class="text">\u00a0<span></span></td>'
    middle = {
        "dash": "<td>-</td>", "unknown_text": "<td>not available</td>",
        "missing_cell": "", "spanned_cell": '<td colspan="2"> </td>',
        "nonempty_span": "<td><span>0</span></td>", "image": '<td><img src="zero.png"/></td>',
        "hidden_span": '<td><span style="display:none">0</span></td>',
        "nested_table": '<td><table></table></td>', "rowspan": '<td rowspan="2"> </td>',
        "rejected_value": "<td>3</td>",
    }.get(variant, middle)
    content = f'''<table><tr><th rowspan="2">CONSOLIDATED STATEMENT OF SHAREHOLDERS' EQUITY (Parenthetical), $ in Millions</th>
      <th colspan="3">12 Months Ended</th></tr><tr><th>Dec. 31, 2020</th><th>Dec. 31, 2019</th><th>Dec. 31, 2018</th></tr>
      <tr><td><a onclick="Show.showAR(this, 'defref_{fragment}', window)">{label}</a></td><td>$ (16)</td>{middle}<td>$ (1)</td></tr></table>'''.encode()
    if variant == "wrong_header":
        content = content.replace(b"Dec. 31, 2019", b"Dec. 31, 2017")
    if variant.startswith("duplicate_blank_"):
        attribute = variant.removeprefix("duplicate_blank_")
        content = content.replace(b'<td class="text">',
            f'<td {attribute}="2" {attribute.upper()}="1" class="text">'.encode())
    if variant.startswith("duplicate_current_"):
        attribute = variant.removeprefix("duplicate_current_")
        content = content.replace(b"<td>$ (16)</td>",
            f'<td {attribute}="2" {attribute}="1">$ (16)</td>'.encode())
    if variant == "duplicate_same_span":
        content = content.replace(b'<td class="text">', b'<td colspan="1" colspan="1" class="text">')
    if variant in {"no_older_or_independent_anchor", "all_blank"}:
        content = content.replace(b"<td>$ (1)</td>", b"<td> </td>")
    if variant == "all_blank":
        content = content.replace(b"<td>$ (16)</td>", b"<td> </td>")
    candidates = [_generated_raw(raw_fact_id=index, context_id=f"c-{year}", concept=concept,
        raw_value=value, period_start=date(year, 1, 1), period_end=date(year, 12, 31))
        for index, (year, value) in enumerate(((2020, "-16000000"), (2018, "-1000000")), 1)]
    if variant in {"raw_prior_exists", "rejected_raw_prior_exists"}:
        candidates.append(replace(candidates[0], raw_fact_id=3, context_id="prior",
            raw_value="0", period_start=date(2019, 1, 1), period_end=date(2019, 12, 31),
            is_hidden=variant == "rejected_raw_prior_exists"))
    def parse():
        return parse_generated_statement_occurrences(
        content, filename="R8.htm", statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(concept=fragment),
        label_linkbase=_label_linkbase(concept=fragment, label=label), candidates=candidates,
        presentation_artifact_id=21, presentation_sha256="1" * 64,
        label_artifact_id=22, label_sha256="2" * 64,
        allow_partial=True, allow_dollar_prefixed_negative=True,
        allow_explicit_blank_prior_annual_column=variant != "old_version",
        report_sha256=hashlib.sha256(content).hexdigest(),
        )
    if variant == "rowspan":
        with pytest.raises(StatementAuthorityParseError, match="invalid_statement_table_shape"):
            parse()
        return
    result = parse()
    marked = [o for o in result.occurrences if "explicit_blank_prior_annual_column" in o.locator]
    should_mark = variant in {"blank", "no_independent_anchor", "no_older_or_independent_anchor", "conflicting_anchor", "same_concept_conflicting_anchor"}
    assert bool(marked) is should_mark
    if variant in {"missing_cell", "spanned_cell", "nonempty_span", "hidden_span", "rejected_value"}:
        assert concept in result.rejected_concepts
        assert not result.occurrences
        return
    expected_values = [] if variant == "all_blank" else ["-16000000"] if variant == "no_older_or_independent_anchor" else ["-16000000", "-1000000"]
    assert [o.raw_value for o in result.occurrences] == expected_values
    periods = [PresentedPeriodEvidence(o.column_header, c.period_start, c.period_end,
        "R8", o.locator["row"], o.concept, o.locator["column"],
        o.locator.get("explicit_blank_prior_annual_column"))
        for o in result.occurrences for c in candidates if c.context_id == o.context_id]
    if variant not in {"no_independent_anchor", "no_older_or_independent_anchor", "all_blank"}:
        periods += [PresentedPeriodEvidence(f"12 Months Ended Dec. 31, {year}",
            date(year, 1, 1), date(year, 12, 31), "R2", 3, "us-gaap:Revenue", column)
            for column, year in ((2, 2020), (3, 2019))]
    if variant in {"conflicting_anchor", "same_concept_conflicting_anchor"}:
        periods += [PresentedPeriodEvidence(f"12 Months Ended Dec. 31, {year}",
            date(year, 1, 1), date(year, 12, 31), "R8", 4,
            concept if variant == "same_concept_conflicting_anchor" else "us-gaap:NetIncomeLoss", column)
            for column, year in ((2, 2020), (3, 2018))]
    kwargs = dict(dei_facts=[DeiFocusEvidence("dei", "DocumentFiscalYearFocus", "2020", ()),
        DeiFocusEvidence("dei", "DocumentFiscalPeriodFocus", "FY", ())],
        presented_periods=periods, form="10-K", statement_period_end=date(2020, 12, 31),
        approved_dei_namespaces=("dei",),
        allow_explicit_blank_prior_annual_column=variant != "old_version")
    if variant == "blank":
        focus = build_explicit_fiscal_focus(**kwargs)
        assert (focus.fiscal_year_start, focus.prior_fiscal_year_start) == (date(2020, 1, 1), date(2019, 1, 1))
        assert marked[0].locator["explicit_blank_prior_annual_column"]["column"] == 3
    else:
        reason = "missing_unproven_current_fiscal_year_start" if variant == "all_blank" else "unproven_prior_fiscal_cycle_anchor"
        with pytest.raises(StatementAuthorityParseError, match=reason):
            build_explicit_fiscal_focus(**kwargs)


@pytest.mark.parametrize("variant,accepted", [
    ("millions", True), ("old_version", False), ("no_share_scale", False),
    ("thousands", True), ("amount_conflict", False), ("context_conflict", False),
    ("dimension_conflict", False), ("per_share", False),
    ("conflicting_scales", False),
])
def test_v211_explicit_share_millions_keeps_exact_candidate_identity(variant, accepted):
    fragment = "us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding"
    content = _generated_statement_html(concept=fragment, label="Diluted (in shares)", displayed="184.7")
    content = content.replace(b"shares in Thousands", b"shares in Millions")
    value = "184700000"
    if variant == "no_share_scale": content = content.replace(b"shares in Millions, ", b"")
    if variant == "thousands":
        content = content.replace(b"shares in Millions", b"shares in Thousands")
        value = "184700"
    if variant == "conflicting_scales":
        content = content.replace(b"shares in Millions", b"shares in Millions, shares in Thousands")
    if variant == "amount_conflict": value = "184800000"
    candidates = [_generated_raw(concept=fragment.replace("_", ":", 1), raw_value=value,
        unit_id="shares", unit_numerator=({"namespace_uri": "http://www.xbrl.org/2003/instance", "local_name": "shares"},))]
    if variant == "context_conflict": candidates.append(replace(candidates[0], raw_fact_id=12, context_id="other"))
    if variant == "dimension_conflict": candidates.append(replace(candidates[0], raw_fact_id=12, dimensions=(("axis", "member"),)))
    if variant == "per_share": candidates[0] = replace(candidates[0], unit_denominator=({"local_name": "shares"},))
    kwargs = dict(filename="R3.htm", statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(concept=fragment),
        label_linkbase=_label_linkbase(concept=fragment, label="Diluted (in shares)"), candidates=candidates,
        presentation_artifact_id=21, presentation_sha256="1" * 64,
        label_artifact_id=22, label_sha256="2" * 64,
        allow_shares_in_millions=variant != "old_version")
    if not accepted:
        reason = "ambiguous_statement_share_scale" if variant == "conflicting_scales" else "(?:unresolved|ambiguous)_generated_statement_occurrence"
        with pytest.raises(StatementAuthorityParseError, match=reason):
            parse_generated_statement_occurrences(content, **kwargs)
    else:
        result = parse_generated_statement_occurrences(content, **kwargs)
        assert len(result.occurrences) == 1
        assert result.occurrences[0].raw_value == value
        assert result.occurrences[0].locator["scale_multiplier"] == ("1000" if variant == "thousands" else "1000000")


def test_generated_balance_sheet_resolves_exact_date_only_instant():
    concept = "us-gaap_Assets"
    role = "http://www.apple.com/role/CONDENSEDCONSOLIDATEDBALANCESHEETSUnaudited"
    html = f"""<html><body><table>
      <tr><th>CONDENSED CONSOLIDATED BALANCE SHEETS - USD ($), $ in Millions</th>
          <th>Jun. 27, 2026</th></tr>
      <tr><td><a onclick="Show.showAR(this, 'defref_{concept}', window)">Total assets</a></td>
          <td>100</td></tr>
    </table></body></html>""".encode()
    candidate = _generated_raw(
        concept="us-gaap:Assets",
        raw_value="100000000",
        element_id="assets-current",
        period_start=None,
    )

    resolution = parse_generated_statement_occurrences(
        html,
        filename="R4.htm",
        statement_role=role,
        statement_type="balance_sheet",
        presentation_linkbase=_presentation_linkbase(concept=concept).replace(
            b"http://www.apple.com/role/Operations", role.encode()
        ),
        label_linkbase=_label_linkbase(concept=concept, label="Total assets"),
        candidates=[candidate],
        presentation_artifact_id=21,
        presentation_sha256="1" * 64,
        label_artifact_id=22,
        label_sha256="2" * 64,
        allow_balance_sheet_date_only_instant=True,
    )

    assert len(resolution.occurrences) == 1
    assert resolution.occurrences[0].context_id == "c-18"


def test_generated_date_only_instant_is_not_accepted_outside_balance_sheet():
    concept = "us-gaap_Assets"
    role = "http://www.apple.com/role/StatementOfCashFlows"
    html = f"""<html><body><table><tr><th>USD ($), $ in Millions</th>
      <th>Jun. 27, 2026</th></tr><tr><td><a
      onclick="Show.showAR(this, 'defref_{concept}', window)">Total assets</a></td>
      <td>100</td></tr></table></body></html>""".encode()
    resolution = parse_generated_statement_occurrences(
        html,
        filename="R7.htm",
        statement_role=role,
        statement_type="cash_flow",
        presentation_linkbase=_presentation_linkbase(concept=concept).replace(
            b"http://www.apple.com/role/Operations", role.encode()
        ),
        label_linkbase=_label_linkbase(concept=concept, label="Total assets"),
        candidates=[_generated_raw(
            concept="us-gaap:Assets", raw_value="100000000",
            element_id="assets-current", period_start=None,
        )],
        presentation_artifact_id=21,
        presentation_sha256="1" * 64,
        label_artifact_id=22,
        label_sha256="2" * 64,
        allow_partial=True,
        allow_balance_sheet_date_only_instant=True,
    )

    assert resolution.occurrences == ()
    assert resolution.rejected_concepts == {"us-gaap:Assets"}


@pytest.mark.parametrize("onclick_prefix", ["", "top."])
def test_generated_statement_resolves_real_old_early_and_recent_shapes_by_exact_authority(onclick_prefix):
    html = _generated_statement_html().replace(b"Show.showAR", f"{onclick_prefix}Show.showAR".encode())
    occurrences = parse_generated_statement_occurrences(
        html,
        filename="R2.htm",
        statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(),
        label_linkbase=_label_linkbase(),
        candidates=[_generated_raw()],
        presentation_artifact_id=21,
        presentation_sha256="1" * 64,
        label_artifact_id=22,
        label_sha256="2" * 64,
    ).occurrences
    current_quarter = occurrences[0]
    assert (current_quarter.context_id, current_quarter.fact_id, current_quarter.raw_value) == (
        "c-18", "f-56", "109417000000")
    assert current_quarter.column_header == "3 Months Ended Jun. 27, 2026"
    assert current_quarter.locator == {
        "kind": "sec_generated_statement_html_v2",
        "row": 3,
        "column": 2,
        "fact_id": "f-56",
        "display_value": "$ 109,417",
        "row_label": "Net sales",
        "statement_role": "http://www.apple.com/role/Operations",
        "presentation_order": "1",
        "preferred_label_role": "http://www.xbrl.org/2003/role/terseLabel",
        "scale_multiplier": "1000000",
        "period_start": "2026-03-29",
        "period_end": "2026-06-27",
        "dimensions": [],
        "dimensions_sha256": hashlib.sha256(b"[]").hexdigest(),
        "decimals": "-6",
        "presentation_artifact_id": 21,
        "presentation_sha256": "1" * 64,
        "label_artifact_id": 22,
        "label_sha256": "2" * 64,
        "canonical_duplicate_rule": "lowest_raw_fact_id_for_exact_identity_v1",
        "equivalent_raw_fact_ids": [11],
        "onclick": current_quarter.locator["onclick"],
        "onclick_sha256": hashlib.sha256(
            current_quarter.locator["onclick"].encode()
        ).hexdigest(),
        "onclick_attribute": current_quarter.locator["onclick_attribute"],
        "onclick_attribute_sha256": hashlib.sha256(
            current_quarter.locator["onclick_attribute"].encode()
        ).hexdigest(),
        "anchor_start_tag": current_quarter.locator["anchor_start_tag"],
        "anchor_start_tag_sha256": hashlib.sha256(
            current_quarter.locator["anchor_start_tag"].encode()
        ).hexdigest(),
    }


@pytest.mark.parametrize(
    ("raw_label", "decoded_label"),
    [
        ("Total shareholders&rsquo; equity", "Total shareholders’ equity"),
        ("Total shareholders&#8217; equity", "Total shareholders’ equity"),
        ("<span>Total</span> shareholders&rsquo; equity", "Total shareholders’ equity"),
    ],
)
def test_v26_generated_statement_binds_decoded_label_to_exact_raw_anchor_fragment(
    raw_label, decoded_label
):
    concept = "us-gaap_StockholdersEquity"
    html = _generated_statement_html(
        concept=concept,
        label=raw_label,
        displayed="$ 100",
    )
    resolution = parse_generated_statement_occurrences(
        html,
        filename="R5.htm",
        statement_role="http://www.apple.com/role/CONSOLIDATEDBALANCESHEETS",
        statement_type="balance_sheet",
        presentation_linkbase=_presentation_linkbase(concept=concept).replace(
            b"http://www.apple.com/role/Operations",
            b"http://www.apple.com/role/CONSOLIDATEDBALANCESHEETS",
        ),
        label_linkbase=_label_linkbase(
            concept=concept,
            label=decoded_label,
        ),
        candidates=[
            _generated_raw(
                concept="us-gaap:StockholdersEquity",
                raw_value="100000000",
                element_id="equity-current",
                period_start=None,
            )
        ],
        presentation_artifact_id=21,
        presentation_sha256="1" * 64,
        label_artifact_id=22,
        label_sha256="2" * 64,
        allow_balance_sheet_date_only_instant=True,
        require_exact_raw_label_fragment=True,
    )

    locator = resolution.occurrences[0].locator
    assert locator["row_label"] == decoded_label
    assert locator["row_label_source_html"] == raw_label
    assert locator["anchor_source_html"].startswith(locator["anchor_start_tag"])
    assert locator["anchor_source_html"].endswith("</a>")
    assert locator["anchor_source_start"] < locator["anchor_source_end"]
    assert locator["anchor_source_html_occurrence_count"] == 1
    assert locator["anchor_source_html_sha256"] == hashlib.sha256(
        locator["anchor_source_html"].encode()
    ).hexdigest()


def test_v26_generated_statement_rejects_oversized_raw_label_fragment():
    concept = "us-gaap_StockholdersEquity"
    label = "A" * 8_193
    with pytest.raises(
        StatementAuthorityParseError,
        match="unproven_generated_statement_raw_label_fragment",
    ):
        parse_generated_statement_occurrences(
            _generated_statement_html(
                concept=concept,
                label=label,
                displayed="$ 100",
            ),
            filename="R5.htm",
            statement_role="http://www.apple.com/role/CONSOLIDATEDBALANCESHEETS",
            statement_type="balance_sheet",
            presentation_linkbase=_presentation_linkbase(concept=concept).replace(
                b"http://www.apple.com/role/Operations",
                b"http://www.apple.com/role/CONSOLIDATEDBALANCESHEETS",
            ),
            label_linkbase=_label_linkbase(concept=concept, label=label),
            candidates=[
                _generated_raw(
                    concept="us-gaap:StockholdersEquity",
                    raw_value="100000000",
                    element_id="equity-current",
                    period_start=None,
                )
            ],
            presentation_artifact_id=21,
            presentation_sha256="1" * 64,
            label_artifact_id=22,
            label_sha256="2" * 64,
            allow_balance_sheet_date_only_instant=True,
            require_exact_raw_label_fragment=True,
        )


@pytest.mark.parametrize("candidate", [
    _generated_raw(raw_value="109417000001"),  # decimals never authorizes rounding
    _generated_raw(is_nil=True),
    _generated_raw(is_hidden=True),
])
def test_generated_statement_rejects_rounding_nil_and_hidden_instance_facts(candidate):
    with pytest.raises(StatementAuthorityParseError, match="unresolved_generated_statement_occurrence"):
        parse_generated_statement_occurrences(
            _generated_statement_html(), filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=_presentation_linkbase(), label_linkbase=_label_linkbase(),
            candidates=[candidate], presentation_artifact_id=21,
            presentation_sha256="1" * 64, label_artifact_id=22, label_sha256="2" * 64)


@pytest.mark.parametrize("collision", [
    _generated_raw(raw_fact_id=12, context_id="segment", dimensions=(("axis", "member"),)),
    _generated_raw(raw_fact_id=12, context_id="other-unit", unit_id="usd2"),
    _generated_raw(raw_fact_id=12, context_id="duplicate"),
])
def test_generated_statement_fails_closed_on_dimension_unit_or_duplicate_identity(collision):
    with pytest.raises(StatementAuthorityParseError, match="ambiguous_generated_statement_occurrence"):
        parse_generated_statement_occurrences(
            _generated_statement_html(), filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=_presentation_linkbase(), label_linkbase=_label_linkbase(),
            candidates=[_generated_raw(), collision], presentation_artifact_id=21,
            presentation_sha256="1" * 64, label_artifact_id=22, label_sha256="2" * 64)


def test_generated_statement_partial_mode_never_authorizes_ambiguous_identity():
    resolution = parse_generated_statement_occurrences(
        _generated_statement_html(), filename="R2.htm",
        statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(), label_linkbase=_label_linkbase(),
        candidates=[
            _generated_raw(),
            _generated_raw(raw_fact_id=12, context_id="segment", dimensions=(("axis", "member"),)),
        ],
        presentation_artifact_id=21, presentation_sha256="1" * 64,
        label_artifact_id=22, label_sha256="2" * 64,
        allow_partial=True,
    )
    assert resolution.occurrences == ()
    assert resolution.rejected_concepts == {
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    }


def test_generated_statement_rejects_entire_ambiguous_concept_but_keeps_clean_concept():
    revenue = "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax"
    gross = "us-gaap_GrossProfit"
    abstract = "us-gaap_StatementLineItems"
    html = f"""<html><body><table><tr><th>USD ($), $ in Millions</th>
      <th>3 Months Ended Jun. 27, 2026</th><th>3 Months Ended Jun. 28, 2025</th></tr>
      <tr><td><a onclick="Show.showAR(this, 'defref_{revenue}', window)">Net sales</a></td><td>100</td><td>90</td></tr>
      <tr><td><a onclick="Show.showAR(this, 'defref_{gross}', window)">Gross profit</a></td><td>40</td><td>-</td></tr>
      <tr><td><a onclick="Show.showAR(this, 'defref_{abstract}', window)">Abstract</a></td><td>-</td><td>-</td></tr>
      </table></body></html>""".encode()
    presentation = f"""<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">
      <link:presentationLink xlink:role="http://www.apple.com/role/Operations">
      <link:loc xlink:label="r" xlink:href="a.xsd#{revenue}"/><link:loc xlink:label="g" xlink:href="a.xsd#{gross}"/>
      <link:presentationArc xlink:from="root" xlink:to="r" order="1"/><link:presentationArc xlink:from="root" xlink:to="g" order="2"/>
      </link:presentationLink></link:linkbase>""".encode()
    labels = f"""<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink"><link:labelLink>
      <link:loc xlink:label="r" xlink:href="a.xsd#{revenue}"/><link:loc xlink:label="g" xlink:href="a.xsd#{gross}"/>
      <link:label xlink:label="rl" xml:lang="en-US">Net sales</link:label><link:label xlink:label="gl" xml:lang="en-US">Gross profit</link:label>
      <link:labelArc xlink:from="r" xlink:to="rl"/><link:labelArc xlink:from="g" xlink:to="gl"/>
      </link:labelLink></link:linkbase>""".encode()
    candidates = [
        _generated_raw(raw_fact_id=1, raw_value="100000000", element_id="r-current"),
        _generated_raw(raw_fact_id=2, context_id="r-prior-a", raw_value="90000000", element_id="r-a",
                       period_start=date(2025, 3, 30), period_end=date(2025, 6, 28), dimensions=()),
        _generated_raw(raw_fact_id=3, context_id="r-prior-b", raw_value="90000000", element_id="r-b",
                       period_start=date(2025, 3, 30), period_end=date(2025, 6, 28), dimensions=(("axis", "member"),)),
        _generated_raw(raw_fact_id=4, concept="us-gaap:GrossProfit", raw_value="40000000", element_id="g-current"),
    ]
    resolution = parse_generated_statement_occurrences(
        html, filename="R2.htm", statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=presentation, label_linkbase=labels, candidates=candidates,
        presentation_artifact_id=21, presentation_sha256="1" * 64,
        label_artifact_id=22, label_sha256="2" * 64, allow_partial=True,
    )
    assert [item.concept for item in resolution.occurrences] == ["us-gaap:GrossProfit"]
    assert resolution.rejected_concepts == {"us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"}
    assert {item.reason for item in resolution.rejections} == {"ambiguous_generated_statement_occurrence"}


@pytest.mark.parametrize("onclick", [
    "Show.showAR(this, 'defref_us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax', window); alert(1)",
    "Show.showAR(this, 'defref_us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax', window); Show.showAR(this, 'defref_us-gaap_GrossProfit', window)",
    "Show.showAR(this, 'defref_us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax\", window)",
])
def test_generated_statement_rejects_noncanonical_or_multiple_onclick_targets(onclick):
    html = _generated_statement_html().replace(
        b"Show.showAR( this, 'defref_us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax', window );",
        onclick.encode(),
    )
    with pytest.raises(StatementAuthorityParseError, match="ambiguous_generated_statement_onclick"):
        parse_generated_statement_occurrences(
            html, filename="R2.htm", statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=_presentation_linkbase(), label_linkbase=_label_linkbase(),
            candidates=[_generated_raw()], presentation_artifact_id=21,
            presentation_sha256="1" * 64, label_artifact_id=22, label_sha256="2" * 64,
        )


def test_generated_statement_v24_ignores_exact_dimension_member_showar_rows():
    dimension = (
        b"<tr><td><a onclick=\"top.Show.showAR( this, "
        b"'defref_srt_ProductOrServiceAxis=us-gaap_ProductMember', window );\">"
        b"Products</a></td><td>-</td></tr>"
    )
    html = _generated_statement_html().replace(b"</table>", dimension + b"</table>")

    with pytest.raises(
        StatementAuthorityParseError,
        match="ambiguous_generated_statement_onclick",
    ):
        parse_generated_statement_occurrences(
            html, filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=_presentation_linkbase(),
            label_linkbase=_label_linkbase(), candidates=[_generated_raw()],
            presentation_artifact_id=21, presentation_sha256="1" * 64,
            label_artifact_id=22, label_sha256="2" * 64,
        )

    resolution = parse_generated_statement_occurrences(
        html, filename="R2.htm",
        statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(),
        label_linkbase=_label_linkbase(), candidates=[_generated_raw()],
        presentation_artifact_id=21, presentation_sha256="1" * 64,
        label_artifact_id=22, label_sha256="2" * 64,
        allow_dimension_member_anchors=True,
    )
    assert [item.concept for item in resolution.occurrences] == [
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    ]


@pytest.mark.parametrize(
    "target",
    [
        "srt_ProductOrServiceAxis=us-gaap_ProductMember=us-gaap_ServiceMember",
        "srt_ProductOrServiceAxis=us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
        "srt_ProductOrServiceMember=us-gaap_ProductMember",
        "srt_ProductOrServiceAxis=us-gaap_ProductMember); alert(1",
    ],
)
def test_generated_statement_v24_rejects_noncanonical_dimension_showar(target):
    html = _generated_statement_html().replace(
        b"</table>",
        (
            "<tr><td><a onclick=\"Show.showAR(this, 'defref_"
            + target
            + "', window)\">dimension</a></td><td>-</td></tr></table>"
        ).encode(),
    )
    with pytest.raises(
        StatementAuthorityParseError,
        match="ambiguous_generated_statement_onclick",
    ):
        parse_generated_statement_occurrences(
            html, filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=_presentation_linkbase(),
            label_linkbase=_label_linkbase(), candidates=[_generated_raw()],
            presentation_artifact_id=21, presentation_sha256="1" * 64,
            label_artifact_id=22, label_sha256="2" * 64,
            allow_dimension_member_anchors=True,
        )


def test_generated_statement_requires_nonempty_exact_presentation_link_role():
    without_role = _presentation_linkbase().replace(
        b' xlink:role="http://www.apple.com/role/Operations"', b""
    )
    with pytest.raises(StatementAuthorityParseError, match="missing_statement_presentation_role"):
        parse_generated_statement_occurrences(
            _generated_statement_html(), filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=without_role, label_linkbase=_label_linkbase(),
            candidates=[_generated_raw()], presentation_artifact_id=21,
            presentation_sha256="1" * 64, label_artifact_id=22, label_sha256="2" * 64,
        )


@pytest.mark.parametrize(
    "duplicate_href",
    [
        "aapl.xsd#us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
        "aapl.xsd#us-gaap_GrossProfit",
    ],
)
def test_generated_statement_rejects_duplicate_label_locator(duplicate_href):
    labels = _label_linkbase().replace(
        b'<link:loc xlink:label="revenue"',
        (
            '<link:loc xlink:label="revenue" xlink:href="'
            + duplicate_href
            + '"/><link:loc xlink:label="revenue"'
        ).encode(),
        1,
    )
    with pytest.raises(StatementAuthorityParseError, match="ambiguous_label_locator"):
        parse_generated_statement_occurrences(
            _generated_statement_html(), filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=_presentation_linkbase(), label_linkbase=labels,
            candidates=[_generated_raw()], presentation_artifact_id=21,
            presentation_sha256="1" * 64, label_artifact_id=22,
            label_sha256="2" * 64,
        )


def test_generated_statement_rejects_empty_label_locator_identity():
    labels = _label_linkbase().replace(
        b'xlink:label="revenue"', b'xlink:label=""', 1
    )
    with pytest.raises(StatementAuthorityParseError, match="ambiguous_label_locator"):
        parse_generated_statement_occurrences(
            _generated_statement_html(), filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=_presentation_linkbase(), label_linkbase=labels,
            candidates=[_generated_raw()], presentation_artifact_id=21,
            presentation_sha256="1" * 64, label_artifact_id=22,
            label_sha256="2" * 64,
        )


def test_generated_statement_accepts_real_sec_shared_label_resource_roles():
    resolution = parse_generated_statement_occurrences(
        _generated_statement_html(), filename="R2.htm",
        statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(),
        label_linkbase=_real_sec_shared_label_resource_linkbase(),
        candidates=[_generated_raw()], presentation_artifact_id=21,
        presentation_sha256="1" * 64, label_artifact_id=22,
        label_sha256="2" * 64,
    )

    assert len(resolution.occurrences) == 1
    assert resolution.occurrences[0].locator["row_label"] == "Net sales"
    assert resolution.occurrences[0].locator["preferred_label_role"].endswith(
        "/terseLabel"
    )


def test_generated_statement_uses_inherited_effective_label_language():
    inherited_french = _label_linkbase().replace(
        b"<link:linkbase ", b'<link:linkbase xml:lang="fr" ', 1
    ).replace(b' xml:lang="en-US"', b"", 1)
    rejected = parse_generated_statement_occurrences(
        _generated_statement_html(), filename="R2.htm",
        statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(),
        label_linkbase=inherited_french, candidates=[_generated_raw()],
        presentation_artifact_id=21, presentation_sha256="1" * 64,
        label_artifact_id=22, label_sha256="2" * 64, allow_partial=True,
    )
    assert rejected.occurrences == ()
    assert rejected.rejected_concepts == {
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    }

    nested_english = inherited_french.replace(
        b"<link:labelLink>", b'<link:labelLink xml:lang=" EN-uS ">', 1
    )
    accepted = parse_generated_statement_occurrences(
        _generated_statement_html(), filename="R2.htm",
        statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(),
        label_linkbase=nested_english, candidates=[_generated_raw()],
        presentation_artifact_id=21, presentation_sha256="1" * 64,
        label_artifact_id=22, label_sha256="2" * 64,
    )
    assert len(accepted.occurrences) == 1


def test_generated_statement_explicit_empty_language_resets_english_ancestor():
    reset = _label_linkbase().replace(
        b'xml:lang="en-US">Net sales', b'xml:lang="">Net sales', 1
    ).replace(b"<link:linkbase ", b'<link:linkbase xml:lang="en-US" ', 1)
    resolution = parse_generated_statement_occurrences(
        _generated_statement_html(), filename="R2.htm",
        statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(), label_linkbase=reset,
        candidates=[_generated_raw()], presentation_artifact_id=21,
        presentation_sha256="1" * 64, label_artifact_id=22,
        label_sha256="2" * 64, allow_partial=True,
    )
    assert resolution.occurrences == ()


def test_generated_statement_rejects_duplicate_label_resource_role_language_identity():
    labels = _real_sec_shared_label_resource_linkbase().replace(
        b"</link:labelLink>",
        b'''<link:label xlink:label="lab-revenue"
          xlink:role="http://www.xbrl.org/2003/role/terseLabel"
          xml:lang="en-US">Conflicting sales label</link:label></link:labelLink>''',
    )
    with pytest.raises(StatementAuthorityParseError, match="ambiguous_label_resource"):
        parse_generated_statement_occurrences(
            _generated_statement_html(), filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=_presentation_linkbase(), label_linkbase=labels,
            candidates=[_generated_raw()], presentation_artifact_id=21,
            presentation_sha256="1" * 64, label_artifact_id=22,
            label_sha256="2" * 64,
        )


@pytest.mark.parametrize(
    ("labels", "reason"),
    [
        (
            _label_linkbase()
            .replace(b'xlink:label="revenue"', b'xlink:label=" "', 1)
            .replace(b'xlink:from="revenue"', b'xlink:from=" "', 1),
            "ambiguous_label_locator",
        ),
        (
            _label_linkbase()
            .replace(b'xlink:label="revenue-label"', b'xlink:label=""', 1)
            .replace(b'xlink:to="revenue-label"', b'xlink:to=""', 1),
            "ambiguous_label_resource",
        ),
        (
            _label_linkbase().replace(
                b'xlink:from="revenue"', b'xlink:from=""', 1
            ),
            "invalid_label_arc",
        ),
        (
            _label_linkbase().replace(
                b'xlink:to="revenue-label"', b'xlink:to="missing"', 1
            ),
            "invalid_label_arc",
        ),
    ],
)
def test_generated_statement_rejects_empty_or_unbound_label_authority(
    labels, reason
):
    with pytest.raises(StatementAuthorityParseError, match=reason):
        parse_generated_statement_occurrences(
            _generated_statement_html(), filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=_presentation_linkbase(), label_linkbase=labels,
            candidates=[_generated_raw()], presentation_artifact_id=21,
            presentation_sha256="1" * 64, label_artifact_id=22,
            label_sha256="2" * 64,
        )


@pytest.mark.parametrize("valid_first", [False, True])
def test_generated_statement_rejects_duplicate_raw_onclick_attributes(valid_first):
    valid = (
        "Show.showAR( this, "
        "'defref_us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax', "
        "window );"
    )
    attributes = (
        f'onclick="{valid}" onclick="alert(1)"'
        if valid_first
        else f'onclick="alert(1)" onclick="{valid}"'
    )
    html = _generated_statement_html().replace(
        f'onclick="{valid}"'.encode(), attributes.encode(), 1
    )
    with pytest.raises(
        StatementAuthorityParseError,
        match="ambiguous_generated_statement_onclick",
    ):
        parse_generated_statement_occurrences(
            html, filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=_presentation_linkbase(),
            label_linkbase=_label_linkbase(), candidates=[_generated_raw()],
            presentation_artifact_id=21, presentation_sha256="1" * 64,
            label_artifact_id=22, label_sha256="2" * 64,
        )


def test_generated_statement_rejects_header_with_multiple_dates():
    html = _generated_statement_html().replace(
        b"Jun. 27, 2026", b"Jun. 27, 2026 and Jun. 28, 2025", 1
    )
    with pytest.raises(
        StatementAuthorityParseError,
        match="unresolved_generated_statement_occurrence",
    ):
        parse_generated_statement_occurrences(
            html, filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=_presentation_linkbase(),
            label_linkbase=_label_linkbase(), candidates=[_generated_raw()],
            presentation_artifact_id=21, presentation_sha256="1" * 64,
            label_artifact_id=22, label_sha256="2" * 64,
        )


def test_generated_statement_canonicalizes_only_exact_duplicate_instance_identity():
    occurrence = parse_generated_statement_occurrences(
        _generated_statement_html(), filename="R2.htm",
        statement_role="http://www.apple.com/role/Operations",
        presentation_linkbase=_presentation_linkbase(), label_linkbase=_label_linkbase(),
        candidates=[_generated_raw(), _generated_raw(raw_fact_id=12, element_id="f-duplicate")],
        presentation_artifact_id=21, presentation_sha256="1" * 64,
        label_artifact_id=22, label_sha256="2" * 64,
    ).occurrences[0]
    assert occurrence.fact_id == "f-56"
    assert occurrence.locator["equivalent_raw_fact_ids"] == [11, 12]
    assert occurrence.locator["canonical_duplicate_rule"] == "lowest_raw_fact_id_for_exact_identity_v1"


@pytest.mark.parametrize("presentation,label", [
    (_presentation_linkbase(concept="us-gaap_GrossProfit"), _label_linkbase()),
    (_presentation_linkbase(), _label_linkbase(label="Revenue")),
])
def test_generated_statement_requires_exact_role_concept_arc_and_preferred_label(presentation, label):
    with pytest.raises(StatementAuthorityParseError, match="unproven_generated_statement_presentation"):
        parse_generated_statement_occurrences(
            _generated_statement_html(), filename="R2.htm",
            statement_role="http://www.apple.com/role/Operations",
            presentation_linkbase=presentation, label_linkbase=label,
            candidates=[_generated_raw()], presentation_artifact_id=21,
            presentation_sha256="1" * 64, label_artifact_id=22, label_sha256="2" * 64)


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
