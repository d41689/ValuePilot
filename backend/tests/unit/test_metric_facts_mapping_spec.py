import json
from datetime import date
from pathlib import Path

import pytest

from app.services.mapping_spec import MappingSpec


FIXTURE_JSON = Path("tests/fixtures/value_line/axs_v1.parser.json")
SPEC_PATH = Path("docs/metric_facts_mapping_spec.yml")


def load_page_json() -> dict:
    with FIXTURE_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_mapping_spec_generates_core_facts():
    spec = MappingSpec.load(SPEC_PATH)
    page_json = load_page_json()

    facts, _, unmapped = spec.generate_facts(page_json)
    by_key = {(f["metric_key"], f.get("period_type"), f.get("period_end_date")): f for f in facts}

    eps_2024 = by_key.get(("per_share.eps", "FY", date(2024, 12, 31)))
    assert eps_2024 is not None
    assert eps_2024["value_numeric"] == pytest.approx(11.18)

    rate = by_key.get(("rates.premium_income.cagr_10y", "AS_OF", date(2026, 1, 9)))
    assert rate is not None
    assert rate["value_numeric"] == pytest.approx(0.065)

    strength = by_key.get(("quality.financial_strength", "AS_OF", date(2026, 1, 9)))
    assert strength is not None
    assert strength["value_numeric"] is None
    assert strength["value_text"] == "A"

    assert ("rating.timeliness_change", "EVENT", date(2026, 1, 9)) not in by_key
    assert ("rating.safety_change", "EVENT", date(2026, 1, 9)) not in by_key
    assert ("rating.technical_change", "EVENT", date(2026, 1, 9)) not in by_key
    assert ("analyst.commentary", "AS_OF", date(2026, 1, 9)) not in by_key
    assert ("company.business_description", "AS_OF", date(2026, 1, 9)) not in by_key

    assert any(path.startswith("historical_price_range") for path in unmapped)
