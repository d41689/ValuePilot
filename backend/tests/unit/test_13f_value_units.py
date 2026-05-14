from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.edgar.parsers.value_units import VALUE_UNIT_UNCERTAIN, infer_value_unit


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "13f" / "value_units"


def _fixture(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


def _accepted(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def test_pre_2023_real_fixtures_resolve_to_schema_thousands():
    fixtures = [
        ("2022_sio_capital_0001214659-22-013603_infotable.xml", "2022-11-14T12:49:28"),
        ("2022_mit_0001214659-22-013108_infotable.xml", "2022-11-03T16:23:40"),
    ]

    for filename, accepted_at in fixtures:
        decision = infer_value_unit(_fixture(filename), accepted_at=_accepted(accepted_at))

        assert decision.value_unit_raw == "thousands"
        assert decision.value_parse_rule == "schema_thousands"
        assert decision.warnings == []
        assert decision.evidence["decided_by"] == "accepted_at"


def test_2023_and_later_real_fixtures_resolve_to_schema_dollars():
    fixtures = [
        ("2023_berkshire_0000950123-23-005270_22815.xml", "2023-05-15T16:01:08"),
        ("2023_toms_capital_0000902664-23-004449_infotable.xml", "2023-08-14T16:30:16"),
    ]

    for filename, accepted_at in fixtures:
        decision = infer_value_unit(_fixture(filename), accepted_at=_accepted(accepted_at))

        assert decision.value_unit_raw == "dollars"
        assert decision.value_parse_rule == "schema_dollars"
        assert decision.warnings == []
        assert decision.evidence["decided_by"] == "accepted_at"


def test_explicit_form_spec_version_takes_priority_over_accepted_at():
    decision = infer_value_unit(
        _fixture("2022_sio_capital_0001214659-22-013603_infotable.xml"),
        accepted_at=_accepted("2022-11-14T12:49:28"),
        form_spec_version="2023",
    )

    assert decision.value_unit_raw == "dollars"
    assert decision.value_parse_rule == "schema_dollars"
    assert decision.evidence["decided_by"] == "form_spec_version"


def test_explicit_xml_schema_version_supports_dotted_versions():
    decision = infer_value_unit(
        _fixture("2023_berkshire_0000950123-23-005270_22815.xml"),
        accepted_at=_accepted("2023-05-15T16:01:08"),
        xml_schema_version="1.6",
    )

    assert decision.value_unit_raw == "thousands"
    assert decision.value_parse_rule == "schema_thousands"
    assert decision.evidence["decided_by"] == "xml_schema_version"


def test_unknown_version_format_falls_through_to_accepted_at():
    decision = infer_value_unit(
        _fixture("2023_toms_capital_0000902664-23-004449_infotable.xml"),
        accepted_at=_accepted("2023-08-14T16:30:16"),
        form_spec_version="unknown",
    )

    assert decision.value_unit_raw == "dollars"
    assert decision.value_parse_rule == "schema_dollars"
    assert decision.evidence["decided_by"] == "accepted_at"


def test_q4_2022_submitted_after_transition_does_not_use_report_quarter_only():
    decision = infer_value_unit(
        _fixture("2022q4_accepted_2023_arex_0000919574-23-001400_infotable.xml"),
        accepted_at=_accepted("2023-02-14T10:01:06"),
        report_period="2022-12-31",
    )

    assert decision.value_unit_raw == "dollars"
    assert decision.value_parse_rule == "schema_dollars"
    assert decision.evidence["report_period"] == "2022-12-31"
    assert decision.evidence["decided_by"] == "accepted_at"


def test_unknown_schema_returns_inferred_with_uncertain_warning():
    unknown_xml = b'<informationTable xmlns="https://example.test/unknown"><infoTable><value>123</value></infoTable></informationTable>'

    decision = infer_value_unit(unknown_xml, accepted_at=None)

    assert decision.value_unit_raw == "unknown"
    assert decision.value_parse_rule == "inferred"
    assert decision.warnings == [VALUE_UNIT_UNCERTAIN]
    assert decision.evidence["decided_by"] == "fallback_uncertain"
