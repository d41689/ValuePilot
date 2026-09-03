import hashlib
import re
from pathlib import Path

import yaml


SPEC_PATH = Path("docs/metric_facts_mapping_spec.yml")
PRD_PATH = Path("docs/prd/value-pilot-prd-v0.1.md")
SOURCE_POLICY_PATH = Path("docs/architecture/coverage-source-policy.md")

EXPECTED_SEC_METRICS = {
    "bs.cash_and_equivalents",
    "bs.cash_and_restricted_cash",
    "bs.current_assets",
    "bs.current_liabilities",
    "bs.equity_including_noncontrolling_interest",
    "bs.stockholders_equity",
    "bs.total_assets",
    "bs.total_liabilities",
    "cap.long_term_debt_current",
    "cap.long_term_debt_noncurrent",
    "cap.short_term_borrowings",
    "cf.capital_expenditures",
    "cf.stock_based_compensation",
    "equity.shares_outstanding",
    "equity.weighted_average_diluted_shares",
    "is.gross_profit",
    "is.net_income",
    "is.operating_income",
    "is.operating_cash_flow",
    "is.revenue",
    "per_share.eps",
}


def _approved_sec_contract() -> tuple[dict, dict]:
    with SPEC_PATH.open(encoding="utf-8") as stream:
        spec = yaml.safe_load(stream)
    approved = [
        version
        for version in spec["sec_xbrl"]["versions"]
        if version["status"] == "approved"
    ]
    assert spec["version"] >= 2
    assert len(approved) == 1
    return spec, approved[0]


def _namespace_matches(authority: dict, uri: str) -> bool:
    return uri in authority["exact_namespace_uris"]


def test_sec_mapping_has_strict_namespace_authorities_and_explicit_concept_identity():
    _, contract = _approved_sec_contract()
    mappings = contract["mappings"]
    mapping_ids = [mapping["id"] for mapping in mappings]
    metric_keys = [mapping["metric_key"] for mapping in mappings]

    assert len(mapping_ids) == len(set(mapping_ids))
    assert len(metric_keys) == len(set(metric_keys))
    assert set(metric_keys) == EXPECTED_SEC_METRICS

    taxonomy = contract["taxonomy"]
    assert taxonomy["authority"] == "namespace_uri_and_local_name"
    assert taxonomy["prefix_role"] == "display_only"
    authorities = taxonomy["namespace_authorities"]
    assert set(authorities) == {"us_gaap", "dei"}

    accepted = {
        "us_gaap": tuple(
            [f"http://fasb.org/us-gaap/{year}-01-31" for year in range(2014, 2022)]
            + [f"http://fasb.org/us-gaap/{year}" for year in range(2022, 2027)]
        ),
        "dei": (
            "http://xbrl.sec.gov/dei/2014-01-31",
            "http://xbrl.sec.gov/dei/2018-01-31",
            "http://xbrl.sec.gov/dei/2019-01-31",
            "http://xbrl.sec.gov/dei/2020-01-31",
            "http://xbrl.sec.gov/dei/2021",
            "http://xbrl.sec.gov/dei/2021q4",
            "http://xbrl.sec.gov/dei/2022",
            "http://xbrl.sec.gov/dei/2023",
            "http://xbrl.sec.gov/dei/2024",
            "http://xbrl.sec.gov/dei/2025",
            "http://xbrl.sec.gov/dei/2026",
        ),
    }
    rejected = {
        "us_gaap": (
            "https://evilfasb.org/us-gaap/2024",
            "https://fasb.org.evil.example/us-gaap/2024",
            "https://fasb.org/us-gaap/2024/extra",
            "https://fasb.org/dei/2024",
            "http://fasb.org/us-gaap/0000",
            "http://fasb.org/us-gaap/2027",
            "http://fasb.org/us-gaap/2022-01-31",
            "http://fasb.org/us-gaap/2021q4",
        ),
        "dei": (
            "https://evil.example/dei/2024",
            "https://xbrl.sec.gov.evil.example/dei/2024",
            "https://xbrl.sec.gov/dei/2024/extra",
            "https://xbrl.sec.gov/us-gaap/2024",
            "http://xbrl.sec.gov/dei/0000",
            "http://xbrl.sec.gov/dei/2027",
            "http://xbrl.sec.gov/dei/2015-01-31",
            "http://xbrl.sec.gov/dei/2021q3",
        ),
    }
    for authority_name, namespace in authorities.items():
        assert namespace["display_prefix"]
        assert tuple(namespace["exact_namespace_uris"]) == accepted[authority_name]
        assert all(_namespace_matches(namespace, uri) for uri in accepted[authority_name])
        assert not any(_namespace_matches(namespace, uri) for uri in rejected[authority_name])
    assert taxonomy["registry_persistence"] == (
        "every_authority_exact_uri_with_mapping_spec_digest"
    )
    assert taxonomy["new_namespace_uri_policy"] == "new_mapping_version_required"

    concept_identities: set[tuple[str, str]] = set()
    for mapping in mappings:
        assert mapping["value_kind"] in contract["unit_policy"]
        assert mapping["period_basis"] in contract["period_policy"]
        priorities = [concept["priority"] for concept in mapping["concepts"]]
        assert priorities == sorted(priorities)
        assert len(priorities) == len(set(priorities))
        assert all(priority > 0 for priority in priorities)

        for concept in mapping["concepts"]:
            namespace = concept["namespace_authority"]
            assert namespace in authorities
            identity = (namespace, concept["local_name"])
            assert identity not in concept_identities
            concept_identities.add(identity)

    concept_to_metric = {
        concept["local_name"]: mapping["metric_key"]
        for mapping in mappings
        for concept in mapping["concepts"]
    }
    assert concept_to_metric["EntityCommonStockSharesOutstanding"] == (
        "equity.shares_outstanding"
    )
    dei_concept = next(
        concept
        for mapping in mappings
        for concept in mapping["concepts"]
        if concept["local_name"] == "EntityCommonStockSharesOutstanding"
    )
    assert dei_concept["namespace_authority"] == "dei"


def test_non_equivalent_sec_concepts_have_distinct_canonical_keys():
    _, contract = _approved_sec_contract()
    by_concept = {
        concept["local_name"]: mapping["metric_key"]
        for mapping in contract["mappings"]
        for concept in mapping["concepts"]
    }

    isolated_groups = (
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
        (
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        (
            "LongTermDebtCurrent",
            "ShortTermBorrowings",
            "LongTermDebtNoncurrent",
        ),
    )
    for concepts in isolated_groups:
        keys = {by_concept[concept] for concept in concepts}
        assert len(keys) == len(concepts)

    assert by_concept["Revenues"] == "is.revenue"
    assert "is.sales" not in EXPECTED_SEC_METRICS


def _evaluate_priority_fixture(fixture: dict) -> dict:
    candidates = fixture["candidates"]
    for priority in sorted({candidate["priority"] for candidate in candidates}):
        valid = [
            candidate
            for candidate in candidates
            if candidate["priority"] == priority and candidate["valid"]
        ]
        if not valid:
            continue
        lower_count = sum(candidate["priority"] > priority for candidate in candidates)
        if len({candidate["value"] for candidate in valid}) > 1:
            return {
                "outcome": "unresolved_conflicting_candidates",
                "lower_priority_decisions": lower_count,
            }
        return {
            "selected_raw_fact_id": min(candidate["raw_fact_id"] for candidate in valid),
            "lower_priority_decisions": lower_count,
        }
    raise AssertionError("fixture must contain one valid group")


def test_concept_priority_pipeline_is_grouped_deterministic_and_never_falls_through():
    _, contract = _approved_sec_contract()
    pipeline = contract["concept_priority_pipeline"]
    assert pipeline["group_order"] == "priority_ascending"
    assert pipeline["validation_order"] == [
        "namespace_authority",
        "unit_shape",
        "period",
        "dimensions",
        "value",
    ]
    assert pipeline["advance_to_next_group_only_when"] == (
        "all_group_candidates_typed_invalid"
    )
    assert pipeline["valid_group_policy"] == {
        "lower_priority_groups_participate": False,
        "identical_valid_same_slot": "deterministic_lowest_raw_fact_id",
        "conflicting_valid_same_slot": "unresolved_conflicting_candidates",
        "conflict_fall_through": "prohibited",
    }
    assert pipeline["audit_policy"] == {
        "lower_priority_raw_candidate_outcome": "lower_priority_concept_not_selected",
        "decision_cardinality": "one_bounded_decision_per_lower_priority_raw_candidate",
    }

    fixtures = {fixture["id"]: fixture for fixture in pipeline["contract_fixtures"]}
    assert set(fixtures) == {
        "higher_valid",
        "higher_invalid_lower_valid",
        "cross_priority_same_value",
        "cross_priority_different_value",
        "same_priority_conflict",
    }
    for fixture in fixtures.values():
        assert _evaluate_priority_fixture(fixture) == fixture["expected"]


def test_sec_mapping_preserves_source_currency_and_has_typed_fail_closed_rules():
    spec, contract = _approved_sec_contract()
    unit_policy = contract["unit_policy"]

    assert unit_policy["decimal_arithmetic"] == "required"
    currency_registry = unit_policy["currency_registry"]
    assert currency_registry["id"] == "locked_ft00_gold_set_v1"
    assert currency_registry["approved_currency_codes"] == ["DKK", "EUR", "TWD", "USD"]
    canonical = currency_registry["canonical_serialization"].encode("utf-8")
    assert currency_registry["canonical_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert currency_registry["registry_persistence"] == (
        "ordered_codes_serialization_sha256_with_mapping_spec_digest"
    )
    assert currency_registry["external_runtime_currency_list"] == "ignored_for_replay"
    assert currency_registry["unlisted_code_outcome"] == "unresolved_currency"
    assert currency_registry["expansion_policy"] == "new_mapping_version_required"

    simulated_external_list_after_drift = {"DKK", "EUR", "GBP", "TWD", "USD", "XXX"}
    replay_eligible = set(currency_registry["approved_currency_codes"])
    assert replay_eligible == {"DKK", "EUR", "TWD", "USD"}
    assert replay_eligible != simulated_external_list_after_drift
    assert {"GBP", "XXX"}.isdisjoint(replay_eligible)
    assert unit_policy["numeric_storage"] == "numeric_38_12_normalized_base_unit"
    assert unit_policy["fx_conversion"] == "prohibited"
    assert unit_policy["unknown_currency_outcome"] == "unresolved_currency"
    for value_kind in ("monetary", "currency_per_share"):
        policy = unit_policy[value_kind]
        assert policy["accepted_currency"] == "iso_4217_source_reported"
        assert re.fullmatch(policy["currency_pattern"], "EUR")
        assert not re.fullmatch(policy["currency_pattern"], "US$")
    assert unit_policy["monetary"]["metric_facts_unit"] == "currency"
    assert unit_policy["currency_per_share"]["metric_facts_unit"] == (
        "currency_per_share"
    )
    assert unit_policy["shares"] == {
        "metric_facts_unit": "shares",
        "metric_facts_currency": None,
    }
    target_units = {
        unit_policy[mapping["value_kind"]]["metric_facts_unit"]
        for mapping in contract["mappings"]
    }
    assert target_units.issubset(set(spec["enums"]["units"]))

    assert contract["dimensions_policy"] == {
        "accepted": "consolidated_no_dimensions",
        "dimensional_outcome": "unresolved_dimensions",
        "custom_concept_outcome": "unresolved_custom_concept",
    }
    assert contract["duplicate_policy"]["conflicting_candidates"] == (
        "unresolved_conflicting_candidates"
    )
    assert contract["duplicate_policy"]["last_write_wins"] == "prohibited"
    assert {
        "unresolved_custom_concept",
        "unresolved_dimensions",
        "unresolved_conflicting_candidates",
        "unresolved_currency",
        "unresolved_unit",
        "unresolved_period",
    }.issubset(contract["unresolved_outcomes"])


def _raw_unit_shape_is_valid(
    unit_policy: dict,
    value_kind: str,
    numerator: list[tuple[str, str]],
    denominator: list[tuple[str, str]],
    *,
    source_currency: str | None = None,
) -> bool:
    raw_policy = unit_policy["raw_structured_unit"]
    authorities = raw_policy["namespace_authorities"]
    shape = raw_policy["accepted_shapes"][value_kind]

    def resolved(expected: list[dict]) -> list[tuple[str, str]]:
        result = []
        for measure in expected:
            authority = authorities[measure["namespace_authority"]]
            local_name = measure["local_name"]
            if local_name == "source_currency":
                local_name = source_currency
            result.append((authority["namespace_uri"], local_name))
        return result

    return numerator == resolved(shape["numerator"]) and denominator == resolved(
        shape["denominator"]
    )


def test_sec_raw_unit_qname_shapes_accept_only_exact_ordered_authorities():
    _, contract = _approved_sec_contract()
    policy = contract["unit_policy"]
    raw = policy["raw_structured_unit"]
    assert raw["representation"] == {
        "numerator_measures": "ordered_qname_list",
        "denominator_measures": "ordered_qname_list",
        "qname_fields": ["namespace_uri", "local_name"],
        "prefix_role": "display_only",
    }
    assert raw["namespace_authorities"] == {
        "iso_4217": {
            "namespace_uri": "http://www.xbrl.org/2003/iso4217",
            "local_name": "approved_iso_4217_currency_code",
        },
        "xbrli": {
            "namespace_uri": "http://www.xbrl.org/2003/instance",
            "shares_local_name": "shares",
        },
    }

    iso = "http://www.xbrl.org/2003/iso4217"
    xbrli = "http://www.xbrl.org/2003/instance"
    assert _raw_unit_shape_is_valid(policy, "monetary", [(iso, "EUR")], [], source_currency="EUR")
    assert _raw_unit_shape_is_valid(
        policy,
        "currency_per_share",
        [(iso, "USD")],
        [(xbrli, "shares")],
        source_currency="USD",
    )
    assert _raw_unit_shape_is_valid(policy, "shares", [(xbrli, "shares")], [])

    invalid_shapes = (
        ("monetary", [(iso, "USD"), (xbrli, "shares")], [], "USD"),
        ("monetary", [("http://evil.example/iso4217", "USD")], [], "USD"),
        ("currency_per_share", [(xbrli, "shares")], [(iso, "USD")], "USD"),
        ("currency_per_share", [(iso, "USD")], [(xbrli, "units")], "USD"),
        ("shares", [(iso, "shares")], [], None),
        ("shares", [(xbrli, "shares")], [(xbrli, "shares")], None),
    )
    for value_kind, numerator, denominator, currency in invalid_shapes:
        assert not _raw_unit_shape_is_valid(
            policy,
            value_kind,
            numerator,
            denominator,
            source_currency=currency,
        )
    assert raw["extra_wrong_or_reordered_measure_outcome"] == "unresolved_unit"


def _classify_duration(period_policy: dict, form: str, elapsed_days: int) -> str:
    if form == "6-K":
        return period_policy["foreign_6k_semantics"]
    matches = [
        rule["output_period_type"]
        for rule in period_policy["duration"]["rules"]
        if form in rule["forms"]
        and rule["elapsed_days"]["min"] <= elapsed_days <= rule["elapsed_days"]["max"]
    ]
    assert len(matches) <= 1
    return matches[0] if matches else period_policy["duration"]["unmatched_outcome"]


def test_sec_mapping_period_classification_truth_table_is_form_first_and_unambiguous():
    _, contract = _approved_sec_contract()
    period_policy = contract["period_policy"]
    assert period_policy["classification_order"] == (
        "form_then_period_shape_then_fiscal_cycle"
    )
    assert period_policy["instant"]["allowed_period_types"] == ["FY", "Q"]
    assert period_policy["instant"]["required_alignment"] == (
        "explicit_statement_period_and_fiscal_cycle"
    )
    assert period_policy["instant"]["mismatch_outcome"] == (
        "unresolved_period_filing_cycle_mismatch"
    )
    assert period_policy["duration"]["fifty_two_or_fifty_three_week_years"] == (
        "supported_within_rule_bounds"
    )
    assert period_policy["foreign_6k_semantics"] == (
        "unresolved_without_approved_period_rule"
    )

    for fixture in period_policy["contract_fixtures"]:
        assert fixture["period_basis"] == "duration"
        assert _classify_duration(
            period_policy, fixture["form"], fixture["elapsed_days"]
        ) == fixture["expected"]

    forms = {form for rule in period_policy["duration"]["rules"] for form in rule["forms"]}
    for form in forms:
        for elapsed_days in range(0, 401):
            matches = [
                rule
                for rule in period_policy["duration"]["rules"]
                if form in rule["forms"]
                and rule["elapsed_days"]["min"]
                <= elapsed_days
                <= rule["elapsed_days"]["max"]
            ]
            assert len(matches) <= 1


def test_sec_mapping_derived_quarter_contract_requires_compatible_exact_inputs():
    _, contract = _approved_sec_contract()

    derived = contract["derived_quarter_policy"]
    assert derived["direct_disclosure_precedence"] is True
    assert set(derived["allowed_rules"]) == {
        "current_ytd_minus_immediately_prior_ytd",
        "fiscal_year_minus_nine_month_ytd",
    }
    assert derived["exact_input_publication_links"] == "required"
    assert derived["arithmetic"] == "decimal"
    assert derived["fiscal_year_minus_nine_month_sources"] == {
        "cross_10k_10q_run_sources": "permitted"
    }
    assert derived["operand_compatibility"] == {
        "stock_id": "same",
        "metric_key": "same",
        "mapping_semantics_id": "same",
        "fiscal_year_start": "same",
        "unit": "same",
        "currency": "same",
        "context_policy": "consolidated_no_dimensions",
        "dimensions": "exact_empty_set",
        "filing_selection": "eligible_under_run_amendment_policy",
        "knowledge_time": "at_or_before_publication_cutoff",
    }
    assert set(derived["incompatibility_outcomes"]) == {
        "stock_id",
        "metric_or_mapping_semantics",
        "fiscal_year_start",
        "unit",
        "currency",
        "context_or_dimensions",
        "filing_or_amendment_selection",
        "knowledge_time",
    }
    assert set(derived["incompatibility_outcomes"].values()).issubset(
        contract["unresolved_outcomes"]
    )

    time_rules = derived["time_identity_rules"]
    adjacent = time_rules["current_ytd_minus_immediately_prior_ytd"]
    assert adjacent["eligible_output_quarter_ordinals"] == [2, 3]
    assert adjacent["right_fiscal_quarter_ordinal"] == "left_ordinal_minus_one"
    assert adjacent["difference_duration_days"] == {"min": 70, "max": 110}
    assert adjacent["output"] == {
        "period_type": "Q",
        "fiscal_quarter_ordinal": "left_fiscal_quarter_ordinal",
        "start": "day_after_right_end",
        "end": "left_end",
    }
    q4 = time_rules["fiscal_year_minus_nine_month_ytd"]
    assert q4["left_duration_days"] == {"min": 300, "max": 380}
    assert q4["right_fiscal_quarter_ordinal"] == 3
    assert q4["difference_duration_days"] == {"min": 70, "max": 110}
    assert q4["output"] == {
        "period_type": "Q",
        "fiscal_quarter_ordinal": 4,
        "start": "day_after_right_end",
        "end": "left_end",
    }

    for fixture in derived["time_identity_fixtures"]:
        if not fixture["same_fiscal_year_start"]:
            actual = "unresolved_derived_fiscal_year_mismatch"
        elif fixture["rule"] == "current_ytd_minus_immediately_prior_ytd":
            eligible = (
                fixture["left_ordinal"] in adjacent["eligible_output_quarter_ordinals"]
                and fixture["right_ordinal"] == fixture["left_ordinal"] - 1
                and fixture["left_end_after_right_end"]
                and adjacent["difference_duration_days"]["min"]
                <= fixture["difference_days"]
                <= adjacent["difference_duration_days"]["max"]
            )
            actual = "Q" if eligible else "unresolved_derived_period_identity"
        else:
            eligible = (
                q4["left_duration_days"]["min"]
                <= fixture["left_duration_days"]
                <= q4["left_duration_days"]["max"]
                and fixture["right_ordinal"] == q4["right_fiscal_quarter_ordinal"]
                and fixture["left_end_after_right_end"]
                and q4["difference_duration_days"]["min"]
                <= fixture["difference_days"]
                <= q4["difference_duration_days"]["max"]
            )
            actual = "Q" if eligible else "unresolved_derived_period_identity"
        assert actual == fixture["expected"]

    assert contract["source_precedence"] == "none"
    assert set(contract["consumer_gate"].values()) == {"prohibited"}


def test_prd_raw_fact_contract_preserves_authoritative_concept_and_unit_qnames():
    prd = PRD_PATH.read_text(encoding="utf-8")
    section = prd.split("### H.5 Parse runs and raw XBRL facts", maxsplit=1)[1]
    section = section.split("### H.6", maxsplit=1)[0]
    section_text = " ".join(section.split())

    for invariant in (
        "concept namespace URI and local name",
        "prefix as display-only metadata",
        "ordered numerator/denominator measures each preserve namespace URI and local name",
        "raw unit ID is retained but is not authority",
        "Neither concept nor unit identity may be reconstructed by trusting an XBRL prefix string",
        "structured QName resolves to the exact ISO-4217 authority URI",
        "`http://www.xbrl.org/2003/iso4217`",
        "`http://www.xbrl.org/2003/instance`",
        "ordered numerator and denominator QName lists",
    ):
        assert invariant in section_text


def test_prd_locks_exact_numeric_ownership_and_ordered_publication_sources():
    prd = PRD_PATH.read_text(encoding="utf-8")
    section = prd.split("### H.9 Canonical SEC publication (FT-04)", maxsplit=1)[1]
    section = section.split("\n---", maxsplit=1)[0]
    section_text = " ".join(section.split())

    for invariant in (
        "`metric_facts` remains the only product-queryable fundamentals store",
        "`source_type='sec'`, `user_id=NULL`",
        "`source_document_id=NULL`",
        "`source_ref_id` identifies the exact `sec_metric_publications` decision",
        "`sec_metric_publication_run_sources`",
        "`sec_metric_mapping_version_namespaces`",
        "`sec_metric_mapping_version_currencies`",
        "Runtime pattern matching is not publication authority",
        "Runtime library contents do not add or remove eligible codes during replay",
        "ordered exact source set",
        "finalized, PIT-eligible, storage-verified succeeded parse run",
        "`metric_facts.user_id` to nullable",
        "`metric_facts.value_numeric` to exact `NUMERIC(38,12)`",
        "Numeric→double→`NUMERIC(38,12)` round trip",
        "Otherwise downgrade fails explicitly",
        "empty upgrade/downgrade/upgrade",
        "safe legacy value such as `42.5`",
        "presence of any SEC fact",
        "`9007199254740993.000000000001` refuses downgrade",
        "EUR-per-share and other SEC values must remain exact on upgrade",
        "monetary facts use `unit='currency'`",
        "per-share monetary facts use `unit='currency_per_share'`",
        "share counts use `unit='shares'`",
        "partial unique current-slot constraint",
        "reciprocal `metric_fact_id`, stock, metric, period, value, unit and currency match",
        "One transaction appends the run's decisions",
        "period_end_date, source_type='sec')` slot",
        "Mapping version is part of replay and provenance identity, not current-slot identity",
        "This uniqueness is SEC- and period-scoped",
        "For knowledge cutoff `T`",
        "MUST NOT return a raw-table browsing endpoint",
        "internal storage key/path",
        "Until FT-06",
    ):
        assert invariant in section_text


def test_prd_locks_form_first_period_derivation_and_slot_level_amendments():
    prd = PRD_PATH.read_text(encoding="utf-8")
    section = prd.split("### H.9 Canonical SEC publication (FT-04)", maxsplit=1)[1]
    section = " ".join(section.split("\n---", maxsplit=1)[0].split())

    for invariant in (
        "accepts only the exact US-GAAP and DEI URIs enumerated",
        "a URI that merely has a plausible year/host/path shape is not eligible",
        "`[DKK, EUR, TWD, USD]` observed in the locked FT-00 gold set",
        "does not consult a runtime ISO library for replay eligibility",
        "Candidate groups are evaluated by ascending concept priority",
        "next priority group is considered only when every candidate in the current group is typed-invalid",
        "different valid values in the same group yield `unresolved_conflicting_candidates` and never fall through",
        "`lower_priority_concept_not_selected` audit decision",
        "Period classification is deterministic and form-first",
        "300-day annual and nine-month boundaries are not ambiguous",
        "52/53-week years",
        "same stock, canonical metric and mapping semantics, fiscal-year start, unit, currency",
        "`current_ytd_minus_immediately_prior_ytd` applies only to Q2 or Q3",
        "right ordinal is exactly one less",
        "difference duration is 70–110 days",
        "starts the day after the right end and ends at the left end",
        "left FY is 300–380 days",
        "This rule may use one selected 10-K source and one selected 10-Q source",
        "V1 amendment authority is slot-level",
        "`nonfinancial_amendment_no_slot_effect`",
        "`unresolved_amendment_parse_failure`",
        "does not imply deletion",
        "before its own acceptance, availability, mapping-effective and knowledge boundaries",
    ):
        assert invariant in section


def test_source_policy_authorizes_only_canonical_coverage_directed_publication():
    source_policy = SOURCE_POLICY_PATH.read_text(encoding="utf-8")

    assert "canonical SEC actual publication" in source_policy
    assert "approved mapping version" in source_policy
    assert "coverage-directed" in source_policy
    assert "Raw XBRL is never directly exposed" in source_policy
