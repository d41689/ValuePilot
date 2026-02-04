from pathlib import Path

from app.services.mapping_spec import MappingSpec


SPEC_PATH = Path("docs/metric_facts_mapping_spec.yml")


def test_mapping_spec_defines_manual_fair_value_semantics():
    spec = MappingSpec.load(SPEC_PATH)
    candidates = [m for m in spec.mappings if m.get("metric_key") == "val.fair_value"]
    assert candidates, "mapping spec must define val.fair_value semantics"
    mapping = candidates[0]
    assert mapping.get("unit") == "USD"
    assert mapping.get("period_type") == "AS_OF"

