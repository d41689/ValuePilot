"""Infer 13F information table value-unit rules without parsing holdings."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from xml.etree import ElementTree as ET


SEC_13F_INFORMATION_TABLE_NAMESPACE = (
    "http://www.sec.gov/edgar/document/thirteenf/informationtable"
)
TRANSITION_ACCEPTED_DATE = date(2023, 1, 3)
VALUE_UNIT_UNCERTAIN = "VALUE_UNIT_UNCERTAIN"
XSI_SCHEMA_LOCATION = "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"


@dataclass(frozen=True)
class ValueUnitDecision:
    value_unit_raw: str
    value_parse_rule: str
    warnings: list[str]
    evidence: dict[str, str | None]


def infer_value_unit(
    xml_content: bytes,
    *,
    accepted_at: datetime | date | None = None,
    report_period: str | date | None = None,
    form_spec_version: str | None = None,
    xml_schema_version: str | None = None,
) -> ValueUnitDecision:
    """Classify the 13F <value> unit rule from schema/version evidence.

    This spike helper deliberately stops at unit classification. It does not
    parse holdings rows or normalize values into persistence-ready amounts.
    """
    namespace, schema_location = _xml_evidence(xml_content)
    accepted_date = _accepted_date(accepted_at)
    evidence = {
        "namespace": namespace,
        "schema_location": schema_location,
        "accepted_at": _iso_date_or_datetime(accepted_at),
        "report_period": _iso_date_or_datetime(report_period),
        "form_spec_version": form_spec_version,
        "xml_schema_version": xml_schema_version,
        "transition_date": TRANSITION_ACCEPTED_DATE.isoformat(),
    }

    explicit_rule, explicit_source = _rule_from_versions(
        form_spec_version=form_spec_version,
        xml_schema_version=xml_schema_version,
    )
    if explicit_rule:
        return _decision(explicit_rule, evidence, decided_by=explicit_source)

    if namespace == SEC_13F_INFORMATION_TABLE_NAMESPACE and accepted_date is not None:
        if accepted_date >= TRANSITION_ACCEPTED_DATE:
            return _decision("schema_dollars", evidence, decided_by="accepted_at")
        return _decision("schema_thousands", evidence, decided_by="accepted_at")

    return ValueUnitDecision(
        value_unit_raw="unknown",
        value_parse_rule="inferred",
        warnings=[VALUE_UNIT_UNCERTAIN],
        evidence=evidence | {"decided_by": "fallback_uncertain"},
    )


def _decision(
    value_parse_rule: str,
    evidence: dict[str, str | None],
    *,
    decided_by: str | None,
) -> ValueUnitDecision:
    if value_parse_rule == "schema_dollars":
        value_unit_raw = "dollars"
    elif value_parse_rule == "schema_thousands":
        value_unit_raw = "thousands"
    else:
        value_unit_raw = "unknown"

    return ValueUnitDecision(
        value_unit_raw=value_unit_raw,
        value_parse_rule=value_parse_rule,
        warnings=[],
        evidence=evidence | {"decided_by": decided_by},
    )


def _xml_evidence(xml_content: bytes) -> tuple[str | None, str | None]:
    root = ET.fromstring(xml_content)
    namespace = None
    if root.tag.startswith("{"):
        namespace = root.tag[1:].split("}", 1)[0]
    return namespace, root.attrib.get(XSI_SCHEMA_LOCATION)


def _rule_from_versions(
    *,
    form_spec_version: str | None,
    xml_schema_version: str | None,
) -> tuple[str | None, str | None]:
    for source, version in (
        ("form_spec_version", form_spec_version),
        ("xml_schema_version", xml_schema_version),
    ):
        normalized = _numeric_version(version)
        if normalized is None:
            continue
        if normalized >= (2023,):
            return "schema_dollars", source
        if normalized >= (1, 7):
            return "schema_dollars", source
        if normalized <= (2022,):
            return "schema_thousands", source
        if normalized <= (1, 6):
            return "schema_thousands", source
    return None, None


def _numeric_version(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    parts = re.findall(r"\d+", value)
    if not parts:
        return None
    return tuple(int(part) for part in parts)


def _accepted_date(value: datetime | date | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value


def _iso_date_or_datetime(value: datetime | date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
