"""Infer 13F information table value-unit rules without parsing holdings."""
from __future__ import annotations

import re
from statistics import median
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable
from xml.etree import ElementTree as ET


SEC_13F_INFORMATION_TABLE_NAMESPACE = (
    "http://www.sec.gov/edgar/document/thirteenf/informationtable"
)
TRANSITION_ACCEPTED_DATE = date(2023, 1, 3)
VALUE_UNIT_UNCERTAIN = "VALUE_UNIT_UNCERTAIN"
VALUE_UNIT_SCHEMA_NONCOMPLIANT = "VALUE_UNIT_SCHEMA_NONCOMPLIANT"
XSI_SCHEMA_LOCATION = "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"

_IMPLIED_PRICE_MIN_SAMPLE = 3
_RAW_DOLLAR_PRICE_MAX = 1.0
_CORRECTED_PRICE_MIN = 1.0
_CORRECTED_PRICE_MAX = 1_000_000.0


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


def reconcile_with_implied_prices(
    decision: ValueUnitDecision,
    positions: Iterable[tuple[int | None, int | None, str | None]],
) -> ValueUnitDecision:
    """Correct a narrow class of post-2023 filer schema violations.

    Form 13F v1.7 requires nearest-dollar values, but some filers continue to
    submit legacy thousands under the current namespace/schema. The filing's
    own summary total repeats the same wrong scale, so reconciliation cannot
    detect it. A portfolio-level common-stock implied-price median can.

    Fail closed unless at least three usable common positions all produce a
    median below $1 as dollars and a plausible $1-$1,000,000 median after a
    1000x correction. Pre-2023/schema-thousands and uncertain decisions are
    never changed here.
    """
    if decision.value_parse_rule != "schema_dollars":
        return decision

    implied_prices = [
        value / shares
        for value, shares, put_call in positions
        if put_call is None and value is not None and shares is not None
        and value > 0 and shares > 0
    ]
    if len(implied_prices) < _IMPLIED_PRICE_MIN_SAMPLE:
        return decision

    raw_median = float(median(implied_prices))
    corrected_median = raw_median * 1000
    if not (
        raw_median < _RAW_DOLLAR_PRICE_MAX
        and _CORRECTED_PRICE_MIN <= corrected_median <= _CORRECTED_PRICE_MAX
    ):
        return decision

    return ValueUnitDecision(
        value_unit_raw="thousands",
        value_parse_rule="implied_price_thousands",
        warnings=[*decision.warnings, VALUE_UNIT_SCHEMA_NONCOMPLIANT],
        evidence=decision.evidence | {
            "schema_rule": decision.value_parse_rule,
            "implied_price_sample_size": str(len(implied_prices)),
            "raw_implied_price_median": f"{raw_median:.8g}",
            "corrected_implied_price_median": f"{corrected_median:.8g}",
            "decided_by": "implied_price_sanity",
        },
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
        # The SEC schema-transition cutover is an EASTERN calendar date; the
        # stored acceptance instant is UTC (T1-FU).
        from app.edgar.parsers.primary_doc import edgar_accepted_date_eastern

        return edgar_accepted_date_eastern(value)
    return value


def _iso_date_or_datetime(value: datetime | date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
