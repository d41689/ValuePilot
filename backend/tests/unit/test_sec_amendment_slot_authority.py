from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from app.services.sec_financial_mapping import (
    FilingCycleSourceAuthority,
    MappingRunAuthority,
    RawFactSnapshot,
    canonical_sec_mapping_v1,
    map_sec_financial_snapshot,
)


US_GAAP = "http://fasb.org/us-gaap/2026"
USD = ({"namespace_uri": "http://www.xbrl.org/2003/iso4217", "local_name": "USD"},)
CUTOFF = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _source(
    accession: str,
    *,
    parse_run_id: int,
    form: str,
    report_date: date,
    accepted_at: datetime,
) -> FilingCycleSourceAuthority:
    return FilingCycleSourceAuthority(
        filing_authority_id=accession,
        parse_run_id=parse_run_id,
        base_form=form.removesuffix("/A"),
        report_date=report_date,
        accepted_at=accepted_at,
        is_amendment=form.endswith("/A"),
    )


def _fact(
    raw_id: int,
    source: FilingCycleSourceAuthority,
    *,
    concept: str = "RevenueFromContractWithCustomerExcludingAssessedTax",
    value: str | None = "10",
    period_start: date = date(2026, 1, 1),
    period_end: date = date(2026, 3, 31),
    fiscal_quarter: int | None = 1,
    fiscal_year_start: date = date(2026, 1, 1),
    occurrence: bool = True,
) -> RawFactSnapshot:
    return RawFactSnapshot(
        raw_fact_id=raw_id,
        parse_run_id=source.parse_run_id,
        normalization_id=None if value is None else 100 + raw_id,
        namespace_uri=US_GAAP,
        local_name=concept,
        normalized_value=None if value is None else Decimal(value),
        unit_numerator=USD,
        unit_denominator=(),
        context_id="C1",
        dimensions=(),
        form=source.base_form + ("/A" if source.is_amendment else ""),
        period_start=period_start,
        period_end=period_end,
        statement_period_end=period_end,
        fiscal_year=2026,
        fiscal_quarter_ordinal=fiscal_quarter,
        fiscal_year_start=fiscal_year_start,
        stock_id=7,
        filing_authority_id=source.filing_authority_id,
        publication_cutoff=CUTOFF,
        fiscal_cycle=(
            "filing_fiscal_year_end"
            if source.base_form in ("10-K", "20-F")
            else "filing_quarter_end"
        ),
        amendment_policy_id="latest-known-v1",
        known_at=source.accepted_at,
        is_nil=value is None,
        occurrence_authorities=(
            ({"raw_fact_id": raw_id, "parse_run_id": source.parse_run_id},)
            if occurrence
            else ()
        ),
    )


def _map(facts, sources):
    authority = MappingRunAuthority(
        publication_cutoff=CUTOFF,
        selected_filing_authority_ids=tuple(source.filing_authority_id for source in sources),
        amendment_policy_id="latest-known-v1",
        filing_cycle_sources=tuple(sources),
    )
    return map_sec_financial_snapshot(canonical_sec_mapping_v1(), facts, authority)


def test_partial_amendment_replaces_only_its_mapped_slot_and_preserves_omitted_metric():
    original = _source(
        "0000000001-26-000001",
        parse_run_id=10,
        form="10-Q",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    amendment = _source(
        "0000000001-26-000002",
        parse_run_id=20,
        form="10-Q/A",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )
    result = _map(
        [
            _fact(1, original, value="10"),
            _fact(2, original, concept="GrossProfit", value="4"),
            _fact(3, amendment, value="11"),
        ],
        [original, amendment],
    )

    by_metric = {candidate.metric_key: candidate for candidate in result.candidates}
    assert by_metric["is.revenue"].value == Decimal("11")
    assert by_metric["is.revenue"].parse_run_ids == (20,)
    assert by_metric["is.gross_profit"].value == Decimal("4")
    assert by_metric["is.gross_profit"].parse_run_ids == (10,)


def test_amended_unresolved_slot_blocks_original_but_omission_does_not():
    original = _source(
        "0000000001-26-000001",
        parse_run_id=10,
        form="10-Q",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    amendment = _source(
        "0000000001-26-000002",
        parse_run_id=20,
        form="10-Q/A",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )
    result = _map(
        [
            _fact(1, original, value="10"),
            _fact(2, original, concept="GrossProfit", value="4"),
            _fact(3, amendment, value=None),
        ],
        [original, amendment],
    )

    assert {candidate.metric_key for candidate in result.candidates} == {"is.gross_profit"}
    unresolved = [item for item in result.dispositions if item.slot is not None]
    assert len(unresolved) == 1
    assert unresolved[0].reason == "unresolved_value"
    assert unresolved[0].raw_fact_ids == (3,)
    assert unresolved[0].slot.parse_run_ids == (20,)


def test_latest_amendment_with_a_slot_wins_independent_of_raw_id_and_input_order():
    original = _source(
        "0000000001-26-000001",
        parse_run_id=10,
        form="10-Q",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    first_amendment = _source(
        "0000000001-26-000002",
        parse_run_id=20,
        form="10-Q/A",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )
    latest_amendment = _source(
        "0000000001-26-000003",
        parse_run_id=30,
        form="10-Q/A",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
    )
    facts = [
        _fact(900, original, value="10"),
        _fact(800, first_amendment, value="11"),
        _fact(1, latest_amendment, value="12"),
    ]

    forward = _map(facts, [original, first_amendment, latest_amendment])
    reversed_input = _map(list(reversed(facts)), [original, first_amendment, latest_amendment])
    assert forward == reversed_input
    assert len(forward.candidates) == 1
    assert forward.candidates[0].value == Decimal("12")
    assert forward.candidates[0].parse_run_ids == (30,)


def test_nonfinancial_amendment_has_no_slot_effect_and_is_typed():
    original = _source(
        "0000000001-26-000001",
        parse_run_id=10,
        form="10-Q",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    amendment = _source(
        "0000000001-26-000002",
        parse_run_id=20,
        form="10-Q/A",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )
    result = _map(
        [
            _fact(1, original, value="10"),
            _fact(2, amendment, concept="IssuerNarrativeOnly", value="7"),
        ],
        [original, amendment],
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].parse_run_ids == (10,)
    assert any(
        item.reason == "nonfinancial_amendment_no_slot_effect"
        and item.raw_fact_ids == ()
        and item.slot is None
        for item in result.dispositions
    )


def test_custom_namespace_local_name_collision_is_nonfinancial_and_preserves_original():
    original = _source(
        "0000000001-26-000001",
        parse_run_id=10,
        form="10-Q",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    amendment = _source(
        "0000000001-26-000002",
        parse_run_id=20,
        form="10-Q/A",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )
    colliding = replace(
        _fact(2, amendment, value="99"),
        namespace_uri="https://issuer.example/custom/2026",
    )
    result = _map([_fact(1, original, value="10"), colliding], [original, amendment])

    assert len(result.candidates) == 1
    assert result.candidates[0].value == Decimal("10")
    assert result.candidates[0].parse_run_ids == (10,)
    assert any(
        item.reason == "unresolved_custom_concept" and item.raw_fact_ids == (2,)
        for item in result.dispositions
    )
    assert any(
        item.reason == "nonfinancial_amendment_no_slot_effect"
        for item in result.dispositions
    )


def test_original_and_amendment_selected_inputs_can_derive_a_quarter():
    q1 = _source(
        "0000000001-26-000001",
        parse_run_id=10,
        form="10-Q",
        report_date=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    q2_original = _source(
        "0000000001-26-000010",
        parse_run_id=20,
        form="10-Q",
        report_date=date(2026, 6, 30),
        accepted_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    q2_amendment = _source(
        "0000000001-26-000011",
        parse_run_id=30,
        form="10-Q/A",
        report_date=date(2026, 6, 30),
        accepted_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    result = _map(
        [
            _fact(1, q1, value="40"),
            _fact(2, q2_original, value="90", period_end=date(2026, 6, 30), fiscal_quarter=2),
            _fact(3, q2_amendment, value="100", period_end=date(2026, 6, 30), fiscal_quarter=2),
        ],
        [q1, q2_original, q2_amendment],
    )

    derived = next(candidate for candidate in result.candidates if candidate.derivation_kind == "current_ytd_minus_prior_ytd")
    assert derived.value == Decimal("60")
    assert derived.parse_run_ids == (30, 10)
    assert derived.raw_fact_ids == (3, 1)


def test_same_report_date_different_base_form_is_not_an_amendment_cycle():
    quarterly = _source(
        "0000000001-26-000001",
        parse_run_id=10,
        form="10-Q",
        report_date=date(2025, 12, 31),
        accepted_at=datetime(2026, 1, 20, tzinfo=timezone.utc),
    )
    annual_amendment = _source(
        "0000000001-26-000002",
        parse_run_id=20,
        form="10-K/A",
        report_date=date(2025, 12, 31),
        accepted_at=datetime(2026, 2, 20, tzinfo=timezone.utc),
    )
    result = _map(
        [
            _fact(
                1,
                quarterly,
                value="10",
                period_start=date(2025, 10, 1),
                period_end=date(2025, 12, 31),
            ),
            _fact(
                2,
                annual_amendment,
                concept="GrossProfit",
                value="40",
                period_start=date(2025, 1, 1),
                period_end=date(2025, 12, 31),
                fiscal_quarter=None,
                fiscal_year_start=date(2025, 1, 1),
            ),
        ],
        [quarterly, annual_amendment],
    )

    assert {(candidate.metric_key, candidate.period_type) for candidate in result.candidates} == {
        ("is.revenue", "Q"),
        ("is.gross_profit", "FY"),
    }
