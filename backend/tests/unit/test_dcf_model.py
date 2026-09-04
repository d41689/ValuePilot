from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.services.dcf_inputs import (
    DCF_MAX_ABS_PER_SHARE,
    DCF_MAX_FACT_UNIVERSE_ROWS,
    DCF_MAX_MODEL_YEARS,
    DCF_MAX_RATE_PCT,
    DcfFactUniverseError,
    DcfModelError,
    calculate_dcf_model,
    dcf_evaluation_clock,
    load_canonical_dcf_fact_universe,
)


def _inputs(**overrides):
    inputs = {
        "net_profit_per_share": "12.000",
        "depreciation_per_share": "3.000",
        "capital_spending_per_share": "0.450",
        "based_on_per_share": "14.550",
        "discount_rate_pct": "11",
        "growth_years": "10",
        "growth_rate_pct": "20",
        "terminal_years": "10",
        "terminal_rate_pct": "4",
    }
    inputs.update(overrides)
    return inputs


def test_dcf_model_v1_matches_frontend_gold_fixture():
    result = calculate_dcf_model(_inputs())

    assert result["calculation_version"] == "dcf-two-stage-finite-v1"
    assert abs(result["growth_value_per_share"] - Decimal("229.042892")) < Decimal("0.000001")
    assert abs(result["terminal_value_per_share"] - Decimal("225.645719")) < Decimal("0.000001")
    assert abs(result["value_per_share"] - Decimal("454.688611")) < Decimal("0.000001")


def test_dcf_model_v1_matches_bounded_terminal_edge_and_year_flooring():
    result = calculate_dcf_model(
        _inputs(growth_years="10.9", terminal_years="1000")
    )

    assert result["normalized_inputs"]["growth_years"] == 10
    assert result["normalized_inputs"]["terminal_years"] == 1000
    assert abs(result["value_per_share"] - Decimal("700.433543")) < Decimal("0.000001")


def test_dcf_model_v1_near_equal_ratio_is_stable_at_schema_maxima():
    result = calculate_dcf_model(
        _inputs(
            net_profit_per_share=str(DCF_MAX_ABS_PER_SHARE),
            depreciation_per_share="0",
            capital_spending_per_share="0",
            based_on_per_share=str(DCF_MAX_ABS_PER_SHARE),
            discount_rate_pct=str(DCF_MAX_RATE_PCT),
            growth_rate_pct=str(DCF_MAX_RATE_PCT),
            growth_years=str(DCF_MAX_MODEL_YEARS),
            terminal_rate_pct="999.999",
            terminal_years=str(DCF_MAX_MODEL_YEARS),
        )
    )

    assert result["value_per_share"] == Decimal("1999545137.709673")


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"discount_rate_pct": "4"}, "dcf_discount_not_above_terminal"),
        ({"discount_rate_pct": "3"}, "dcf_discount_not_above_terminal"),
        ({"net_profit_per_share": "NaN"}, "dcf_model_input_invalid"),
        ({"based_on_per_share": "-1"}, "dcf_model_input_invalid"),
        ({"growth_years": "1001"}, "dcf_model_input_out_of_range"),
        ({"terminal_years": "100000"}, "dcf_model_input_out_of_range"),
        ({"discount_rate_pct": "1000.001"}, "dcf_model_input_out_of_range"),
        ({"based_on_per_share": "1000000.001"}, "dcf_model_input_out_of_range"),
        ({"terminal_years": "Infinity"}, "dcf_model_input_invalid"),
    ],
)
def test_dcf_model_v1_rejects_invalid_or_unbounded_domains(overrides, reason_code):
    with pytest.raises(DcfModelError) as caught:
        calculate_dcf_model(_inputs(**overrides))

    assert caught.value.code == reason_code


def test_dcf_evaluation_clock_derives_effective_date_in_new_york():
    clock = dcf_evaluation_clock(
        datetime(2026, 9, 4, 1, 30, tzinfo=timezone.utc)
    )

    assert clock.evaluated_at == datetime(2026, 9, 4, 1, 30, tzinfo=timezone.utc)
    assert clock.effective_as_of.isoformat() == "2026-09-03"


def test_dcf_fact_universe_fails_closed_above_bounded_query_limit():
    session = MagicMock()
    session.scalars.return_value.all.return_value = [
        object() for _ in range(DCF_MAX_FACT_UNIVERSE_ROWS + 1)
    ]

    with pytest.raises(DcfFactUniverseError) as caught:
        load_canonical_dcf_fact_universe(
            session,
            stock_id=1,
            user_id=1,
            evaluated_at=datetime(2026, 9, 4, 1, 30, tzinfo=timezone.utc),
            effective_as_of=dcf_evaluation_clock(
                datetime(2026, 9, 4, 1, 30, tzinfo=timezone.utc)
            ).effective_as_of,
        )

    assert caught.value.code == "dcf_fact_universe_too_large"
