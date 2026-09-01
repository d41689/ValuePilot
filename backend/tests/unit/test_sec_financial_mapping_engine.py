from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from app.services.sec_financial_mapping import (
    MappingRunAuthority,
    RawFactSnapshot,
    canonical_sec_mapping_v1,
    map_sec_financial_snapshot,
)


US_GAAP = "http://fasb.org/us-gaap/2026"
USD = ({"namespace_uri": "http://www.xbrl.org/2003/iso4217", "local_name": "USD"},)


def run(mapping, facts, **kwargs):
    authority = MappingRunAuthority(
        publication_cutoff=datetime(2026, 9, 1, tzinfo=timezone.utc),
        selected_filing_authority_ids=("filing-1",), amendment_policy_id="latest-known-v1",
    )
    return map_sec_financial_snapshot(mapping, facts, authority, **kwargs)


def raw(raw_id=1, concept="RevenueFromContractWithCustomerExcludingAssessedTax", value="10", **overrides):
    values = dict(
        raw_fact_id=raw_id, parse_run_id=10, normalization_id=100 + raw_id,
        namespace_uri=US_GAAP, local_name=concept, normalized_value=Decimal(value),
        unit_numerator=USD, unit_denominator=(), context_id="C1", dimensions=(),
        form="10-Q", period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
        statement_period_end=date(2026, 3, 31), fiscal_year=2026,
        fiscal_quarter_ordinal=1, fiscal_year_start=date(2026, 1, 1),
        stock_id=7, filing_authority_id="filing-1",
        publication_cutoff=datetime(2026, 9, 1, tzinfo=timezone.utc),
        fiscal_cycle="filing_quarter_end",
        amendment_policy_id="latest-known-v1",
        known_at=datetime(2026, 5, 1, tzinfo=timezone.utc), is_nil=False,
    )
    values.update(overrides)
    return RawFactSnapshot(**values)


def test_v1_snapshot_contains_all_approved_rules_and_is_immutable():
    mapping = canonical_sec_mapping_v1()
    assert mapping.mapping_version_id == "sec-us-gaap-v1"
    assert len(mapping.rules) == 21
    assert len(mapping.currency_codes) == 4
    assert mapping.currency_codes == ("DKK", "EUR", "TWD", "USD")
    forged = replace(mapping, rules=mapping.rules[:-1])
    try:
        run(forged, [])
    except ValueError as exc:
        assert str(exc) == "unsupported mapping snapshot"
    else:
        raise AssertionError("forged approved snapshot was accepted")


def test_priority_pipeline_selects_lowest_id_and_never_falls_through_conflict():
    mapping = canonical_sec_mapping_v1()
    result = run(mapping, [raw(9), raw(3), raw(20, concept="SalesRevenueNet")])
    assert result.candidates[0].raw_fact_ids == (3,)
    assert result.candidates[0].value == Decimal("10")
    assert any(item.reason == "lower_priority_concept_not_selected" and item.raw_fact_ids == (20,) for item in result.dispositions)

    conflict = run(mapping, [raw(1, value="10"), raw(2, value="11"), raw(3, concept="SalesRevenueNet")])
    assert not conflict.candidates
    assert conflict.dispositions[0].reason == "unresolved_conflicting_candidates"
    assert conflict.dispositions[0].raw_fact_ids == (1, 2)
    assert conflict.dispositions[0].slot is not None
    assert conflict.dispositions[0].slot.period_end == date(2026, 3, 31)
    assert conflict.dispositions[0].slot.parse_run_ids == (10, 10)


def test_slot_aware_dispositions_preserve_ordered_occurrence_authority():
    mapping=canonical_sec_mapping_v1()
    evidence1={"statement_authority_id":11,"raw_fact_id":1,"report_ordinal":1,"occurrence_ordinal":1}
    evidence2={"statement_authority_id":22,"raw_fact_id":2,"report_ordinal":1,"occurrence_ordinal":2}
    conflict=run(mapping,[raw(1,value="10",occurrence_authorities=(evidence1,)),raw(2,value="11",occurrence_authorities=(evidence2,))])
    decision=next(item for item in conflict.dispositions if item.reason=="unresolved_conflicting_candidates")
    assert decision.slot is not None and decision.slot.occurrence_authorities==(evidence1,evidence2)
    invalid=run(mapping,[raw(1,is_nil=True,normalized_value=None,occurrence_authorities=(evidence1,))])
    value=next(item for item in invalid.dispositions if item.reason=="unresolved_value")
    assert value.slot is not None and value.slot.occurrence_authorities==(evidence1,)


def test_typed_fail_closed_units_currency_dimensions_namespace_period_and_form():
    mapping = canonical_sec_mapping_v1()
    cases = [
        (raw(namespace_uri="urn:fake"), "unresolved_custom_concept"),
        (raw(dimensions=(("axis", "member"),)), "unresolved_dimensions"),
        (raw(unit_numerator=({"namespace_uri": "http://www.xbrl.org/2003/iso4217", "local_name": "JPY"},)), "unresolved_currency"),
        (raw(unit_numerator=()), "unresolved_unit"),
        (raw(period_end=date(2026, 7, 1)), "unresolved_period_filing_cycle_mismatch"),
        (raw(form="6-K"), "unresolved_unsupported_form_semantics"),
        (raw(is_nil=True, normalized_value=None), "unresolved_value"),
    ]
    for fact, reason in cases:
        result = run(mapping, [fact])
        assert not result.candidates
        assert result.dispositions[0].reason == reason


def test_period_classification_and_strict_derived_quarter_truth_tables():
    mapping = canonical_sec_mapping_v1()
    q1 = raw(1, value="40")
    q2_ytd = raw(2, value="100", period_end=date(2026, 6, 30), statement_period_end=date(2026, 6, 30), fiscal_quarter_ordinal=2)
    result = run(mapping, [q1, q2_ytd])
    by_period = {(item.period_type, item.fiscal_quarter_ordinal): item for item in result.candidates}
    assert by_period[("Q", 1)].value == Decimal("40")
    assert by_period[("YTD", 2)].value == Decimal("100")
    assert by_period[("Q", 2)].value == Decimal("60")
    assert by_period[("Q", 2)].derivation_kind == "current_ytd_minus_prior_ytd"
    assert by_period[("Q", 2)].raw_fact_ids == (2, 1)


def test_derived_candidate_preserves_ordered_occurrence_provenance():
    mapping = canonical_sec_mapping_v1()
    q1 = raw(1, value="40", occurrence_authorities=({"statement_authority_id": 11, "locator_json": {"row": 1}},))
    q2_ytd = raw(2, value="100", period_end=date(2026, 6, 30), statement_period_end=date(2026, 6, 30),
                 fiscal_quarter_ordinal=2, occurrence_authorities=({"statement_authority_id": 22, "locator_json": {"row": 2}},))
    result = run(mapping, [q1, q2_ytd])
    derived = next(item for item in result.candidates if item.derivation_kind == "current_ytd_minus_prior_ytd")
    assert [item["statement_authority_id"] for item in derived.occurrence_authorities] == [22, 11]

    direct_q2 = raw(3, value="61", period_start=date(2026, 4, 1), period_end=date(2026, 6, 30), statement_period_end=date(2026, 6, 30), fiscal_quarter_ordinal=2)
    precedence = run(mapping, [q1, q2_ytd, direct_q2])
    q2_candidates = [item for item in precedence.candidates if item.period_type == "Q" and item.fiscal_quarter_ordinal == 2]
    assert len(q2_candidates) == 1 and q2_candidates[0].value == Decimal("61") and q2_candidates[0].derivation_kind == "direct"

    q3_ytd = raw(4, value="150", period_end=date(2026, 9, 30), statement_period_end=date(2026, 9, 30), fiscal_quarter_ordinal=3)
    fy = raw(5, value="230", form="10-K", period_end=date(2026, 12, 31), statement_period_end=date(2026, 12, 31), fiscal_quarter_ordinal=None, fiscal_cycle="filing_fiscal_year_end")
    annual = run(mapping, [q3_ytd, fy])
    q4 = next(item for item in annual.candidates if item.derivation_kind == "fiscal_year_minus_nine_month_ytd")
    assert q4.value == Decimal("80") and q4.fiscal_quarter_ordinal == 4
    assert q4.parse_run_ids == (10, 10)


def test_structured_per_share_and_shares_units_are_exact():
    mapping = canonical_sec_mapping_v1()
    shares = ({"namespace_uri": "http://www.xbrl.org/2003/instance", "local_name": "shares"},)
    eps = raw(1, concept="EarningsPerShareDiluted", value="1.25", unit_denominator=shares)
    count = raw(2, concept="CommonStockSharesOutstanding", value="100", period_start=None, unit_numerator=shares)
    result = run(mapping, [eps, count])
    assert {item.unit for item in result.candidates} == {"currency_per_share", "shares"}


def test_mapping_output_and_decision_trail_are_bounded():
    mapping = canonical_sec_mapping_v1()
    facts = [raw(index, namespace_uri="urn:custom", concept=f"Custom{index}") for index in range(1, 400)]
    result = run(mapping, facts, max_decisions=32)
    assert len(result.dispositions) == 32
    assert result.truncated_decision_count == 367


def test_513_slotless_raw_audits_report_nonzero_truncation():
    mapping = canonical_sec_mapping_v1()
    facts = [raw(index, namespace_uri="urn:custom", concept=f"IssuerCustomConcept{index}") for index in range(1, 514)]
    result = run(mapping, facts)
    assert not result.candidates and len(result.dispositions) == 512
    assert result.truncated_decision_count == 1
    assert all(item.slot is None and item.reason == "unresolved_custom_concept" for item in result.dispositions)


def test_elapsed_day_contract_boundaries_are_inclusive_calendar_days():
    mapping = canonical_sec_mapping_v1()
    for elapsed, expected in [(69, False), (70, True), (110, True), (111, False), (149, False), (150, True), (210, True), (211, False), (239, False), (240, True), (300, True), (301, False)]:
        fact = raw(period_end=date(2026, 1, 1) + __import__("datetime").timedelta(days=elapsed - 1), statement_period_end=date(2026, 1, 1) + __import__("datetime").timedelta(days=elapsed - 1))
        assert bool(run(mapping, [fact]).candidates) is expected
    for elapsed, expected in [(299, False), (300, True), (379, True), (380, True), (381, False)]:
        end = date(2026, 1, 1) + __import__("datetime").timedelta(days=elapsed - 1)
        fact = raw(form="10-K", period_end=end, statement_period_end=end, fiscal_quarter_ordinal=None, fiscal_cycle="filing_fiscal_year_end")
        assert bool(run(mapping, [fact]).candidates) is expected


def test_missing_and_incompatible_derived_operands_are_typed_and_nonfinite_is_local():
    mapping = canonical_sec_mapping_v1()
    q2 = raw(1, value="100", period_end=date(2026, 6, 30), statement_period_end=date(2026, 6, 30), fiscal_quarter_ordinal=2)
    result = run(mapping, [q2, raw(2, value="NaN")])
    assert any(item.reason == "unresolved_missing_derived_quarter_input" for item in result.dispositions)
    assert any(item.reason == "unresolved_value" and item.raw_fact_ids == (2,) for item in result.dispositions)
    wrong_start = raw(3, value="40", fiscal_year_start=date(2025, 12, 31))
    mismatch = run(mapping, [q2, wrong_start])
    assert any(item.reason == "unresolved_derived_fiscal_year_mismatch" for item in mismatch.dispositions)


def test_mapping_run_authority_enforces_pit_selected_sources_and_amendment_policy():
    mapping = canonical_sec_mapping_v1()
    early_authority = MappingRunAuthority(datetime(2026, 8, 30, tzinfo=timezone.utc), ("filing-1",), "latest-known-v1")
    early = map_sec_financial_snapshot(mapping, [raw(publication_cutoff=early_authority.publication_cutoff)], early_authority)
    assert early.dispositions[0].reason == "unresolved_derived_input_after_cutoff"
    for candidate in (
        (mapping, raw(known_at=datetime(2026, 9, 2, tzinfo=timezone.utc))),
        (mapping, raw(filing_authority_id="not-selected")),
        (mapping, raw(amendment_policy_id="wrong-policy")),
    ):
        result = run(candidate[0], [candidate[1]])
        assert not result.candidates
        assert result.dispositions[0].reason in {"unresolved_derived_input_after_cutoff", "unresolved_derived_filing_authority_mismatch"}


def test_derived_diagnoses_currency_context_and_dimensions_before_missing():
    mapping = canonical_sec_mapping_v1()
    q2 = raw(1, value="100", period_end=date(2026, 6, 30), statement_period_end=date(2026, 6, 30), fiscal_quarter_ordinal=2)
    eur = ({"namespace_uri": "http://www.xbrl.org/2003/iso4217", "local_name": "EUR"},)
    for right, reason in (
        (raw(2, value="40", unit_numerator=eur), "unresolved_derived_currency_mismatch"),
        (raw(3, value="40", context_id="C2"), "unresolved_derived_context_mismatch"),
    ):
        result = run(mapping, [q2, right])
        assert any(item.reason == reason for item in result.dispositions)
    dimensioned = run(mapping, [q2, raw(4, dimensions=({"axis": "x"},))])
    assert any(item.reason == "unresolved_dimensions" for item in dimensioned.dispositions)


def test_q4_overflow_is_local_typed_value_failure():
    mapping = canonical_sec_mapping_v1()
    huge = "99999999999999999999999999"
    q3 = raw(1, value=f"-{huge}", period_end=date(2026, 9, 30), statement_period_end=date(2026, 9, 30), fiscal_quarter_ordinal=3)
    fy = raw(2, value=huge, form="10-K", period_end=date(2026, 12, 31), statement_period_end=date(2026, 12, 31), fiscal_quarter_ordinal=None, fiscal_cycle="filing_fiscal_year_end")
    other = raw(3, concept="GrossProfit", value="7")
    result = run(mapping, [q3, fy, other])
    assert any(item.reason == "unresolved_value" and item.raw_fact_ids == (2, 1) for item in result.dispositions)
    assert any(item.metric_key == "is.gross_profit" for item in result.candidates)


def test_only_compatible_direct_quarter_suppresses_stably_selected_derivation():
    mapping = canonical_sec_mapping_v1()
    eur = ({"namespace_uri": "http://www.xbrl.org/2003/iso4217", "local_name": "EUR"},)
    usd_q1 = raw(30, value="40")
    usd_ytd = raw(20, value="100", period_end=date(2026, 6, 30), statement_period_end=date(2026, 6, 30), fiscal_quarter_ordinal=2)
    eur_direct = raw(10, value="61", unit_numerator=eur, period_start=date(2026, 4, 1), period_end=date(2026, 6, 30), statement_period_end=date(2026, 6, 30), fiscal_quarter_ordinal=2)
    for facts in ([eur_direct, usd_ytd, usd_q1], [usd_q1, eur_direct, usd_ytd]):
        result = run(mapping, facts)
        q2 = [item for item in result.candidates if item.period_type == "Q" and item.fiscal_quarter_ordinal == 2]
        assert {(item.currency, item.derivation_kind, item.value) for item in q2} == {
            ("EUR", "direct", Decimal("61")), ("USD", "current_ytd_minus_prior_ytd", Decimal("60"))
        }


def test_multiple_period_operands_choose_full_compatible_then_lowest_lineage_id():
    mapping = canonical_sec_mapping_v1()
    eur = ({"namespace_uri": "http://www.xbrl.org/2003/iso4217", "local_name": "EUR"},)
    left = raw(50, value="100", period_end=date(2026, 6, 30), statement_period_end=date(2026, 6, 30), fiscal_quarter_ordinal=2)
    wrong = raw(1, concept="SalesRevenueNet", value="999", unit_numerator=eur)
    compatible = raw(9, value="40")
    result = run(mapping, [left, wrong, compatible])
    derived = next(item for item in result.candidates if item.derivation_kind == "current_ytd_minus_prior_ytd")
    assert derived.raw_fact_ids == (50, 9)
    assert derived.value == Decimal("60")


def test_priority_slots_preserve_distinct_fiscal_cycle_identity_independent_of_raw_order():
    mapping = canonical_sec_mapping_v1()
    a = raw(20, value="40", fiscal_year_start=date(2026, 1, 1))
    b = raw(10, value="50", fiscal_year_start=date(2025, 12, 28))
    for facts in ([a, b], [b, a]):
        result = run(mapping, facts)
        assert {(item.fiscal_year_start, item.value) for item in result.candidates} == {
            (date(2026, 1, 1), Decimal("40")), (date(2025, 12, 28), Decimal("50"))
        }


def test_valid_high_priority_assigns_one_lower_priority_outcome_before_validation():
    mapping = canonical_sec_mapping_v1()
    lower = raw(2, concept="SalesRevenueNet", dimensions=({"axis": "x"},))
    result = run(mapping, [raw(1), lower])
    lower_outcomes = [item.reason for item in result.dispositions if item.raw_fact_ids == (2,)]
    assert lower_outcomes == ["lower_priority_concept_not_selected"]


def test_lower_priority_cannot_escape_period_slot_via_currency_or_context():
    mapping = canonical_sec_mapping_v1()
    eur = ({"namespace_uri": "http://www.xbrl.org/2003/iso4217", "local_name": "EUR"},)
    high = raw(1, value="10")
    for lower in (
        raw(2, concept="SalesRevenueNet", value="20", unit_numerator=eur),
        raw(3, concept="SalesRevenueNet", value="20", context_id="OTHER-CONSOLIDATED"),
    ):
        result = run(mapping, [high, lower])
        assert [(item.raw_fact_ids, item.currency) for item in result.candidates] == [((1,), "USD")]
        outcomes = [item.reason for item in result.dispositions if item.raw_fact_ids == (lower.raw_fact_id,)]
        assert outcomes == ["lower_priority_concept_not_selected"]


def test_same_priority_equal_numeric_but_different_currency_conflicts_regardless_of_ids():
    mapping = canonical_sec_mapping_v1()
    eur = ({"namespace_uri": "http://www.xbrl.org/2003/iso4217", "local_name": "EUR"},)
    for facts in ([raw(1, value="10"), raw(2, value="10", unit_numerator=eur)],
                  [raw(2, value="10"), raw(1, value="10", unit_numerator=eur)]):
        result = run(mapping, facts)
        assert not result.candidates
        assert [(item.reason, item.raw_fact_ids) for item in result.dispositions] == [
            ("unresolved_conflicting_candidates", (1, 2))
        ]


def test_numeric_boundary_invalid_high_priority_falls_back_to_valid_lower_once():
    mapping = canonical_sec_mapping_v1()
    high = raw(1, value="999999999999999999999999999")
    lower = raw(2, concept="SalesRevenueNet", value="7")
    result = run(mapping, [high, lower])
    assert [(item.raw_fact_ids, item.value) for item in result.candidates] == [((2,), Decimal("7"))]
    assert [(item.reason, item.raw_fact_ids) for item in result.dispositions] == [("unresolved_value", (1,))]


def test_ytd_and_fy_require_exact_fiscal_year_start_but_discrete_quarter_does_not():
    mapping = canonical_sec_mapping_v1()
    q1 = raw(1, value="40")
    bad_q2 = raw(2, value="100", period_start=date(2026, 1, 2), period_end=date(2026, 6, 30), statement_period_end=date(2026, 6, 30), fiscal_quarter_ordinal=2)
    bad_q3 = raw(3, value="150", period_start=date(2026, 1, 2), period_end=date(2026, 9, 30), statement_period_end=date(2026, 9, 30), fiscal_quarter_ordinal=3)
    bad_fy = raw(4, value="230", form="10-K", period_start=date(2026, 1, 2), period_end=date(2026, 12, 31), statement_period_end=date(2026, 12, 31), fiscal_quarter_ordinal=None, fiscal_cycle="filing_fiscal_year_end")
    direct_q2 = raw(5, value="60", period_start=date(2026, 4, 1), period_end=date(2026, 6, 30), statement_period_end=date(2026, 6, 30), fiscal_quarter_ordinal=2)
    result = run(mapping, [q1, bad_q2, bad_q3, bad_fy, direct_q2])
    assert any(item.raw_fact_ids == (5,) and item.period_type == "Q" for item in result.candidates)
    assert not any(item.derivation_kind != "direct" for item in result.candidates)
    for raw_id in (2, 3, 4):
        assert any(item.reason == "unresolved_period_filing_cycle_mismatch" and item.raw_fact_ids == (raw_id,) for item in result.dispositions)
