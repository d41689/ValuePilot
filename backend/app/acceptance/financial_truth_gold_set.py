from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import re
from typing import Any

import yaml


EXPECTED_STRATA = {
    "ordinary_us_operating": 6,
    "regulated_financial": 3,
    "insurer": 3,
    "reit": 3,
    "high_sbc_or_acquisitive": 3,
    "cyclical_or_commodity": 3,
    "foreign_issuer": 3,
}

CROSS_CUTTING_MINIMUMS = {
    "non_calendar_fiscal_year": 3,
    "fifty_two_or_fifty_three_week": 2,
    "adr_share_class_or_corporate_action": 3,
    "filing_amendment_or_restatement": 2,
    "non_usd_reporting_currency": 2,
}

ALLOWED_REGIMES = {"us_10k_10q", "foreign_20f_6k"}
CIK_RE = re.compile(r"^[0-9]{10}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
FISCAL_YEAR_END_RE = re.compile(r"^(0[1-9]|1[0-2])([0-2][0-9]|3[01])$")
MIC_RE = re.compile(r"^[A-Z0-9]{4}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")
SHARE_CLASS_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ALLOWED_INSTRUMENT_TYPES = {"common_stock", "depositary_receipt"}


class GoldSetValidationError(ValueError):
    pass


@dataclass(frozen=True)
class GoldSetValidationReport:
    case_count: int
    distinct_economic_issuers: int
    primary_strata: dict[str, int]
    cross_cutting_counts: dict[str, int]


def _iso_value(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, (date, datetime)):
        return
    if not isinstance(value, str):
        errors.append(f"{path} must be an ISO date/datetime")
        return
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            date.fromisoformat(value)
        except ValueError:
            errors.append(f"{path} must be an ISO date/datetime")


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _required_text(container: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}.{key} is required")


def validate_gold_set(data: dict[str, Any]) -> GoldSetValidationReport:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise GoldSetValidationError("manifest root must be a mapping")

    if data.get("schema_version") != 1:
        errors.append("schema_version must equal 1")

    cycle = data.get("cycle")
    if not isinstance(cycle, dict):
        errors.append("cycle is required")
        cycle = {}
    for key in ("id", "status", "locked_at", "cutoff_at"):
        _required_text(cycle, key, "cycle", errors)
    if cycle.get("status") != "locked":
        errors.append("cycle.status must be locked")
    _iso_value(cycle.get("locked_at"), "cycle.locked_at", errors)
    _iso_value(cycle.get("cutoff_at"), "cycle.cutoff_at", errors)
    locked_at = _as_datetime(cycle.get("locked_at"))
    cutoff_at = _as_datetime(cycle.get("cutoff_at"))
    if locked_at is not None and cutoff_at is not None:
        if locked_at.tzinfo is None and cutoff_at.tzinfo is not None:
            locked_at = locked_at.replace(tzinfo=cutoff_at.tzinfo)
        if cutoff_at.tzinfo is None and locked_at.tzinfo is not None:
            cutoff_at = cutoff_at.replace(tzinfo=locked_at.tzinfo)
        if cutoff_at > locked_at:
            errors.append("cycle.cutoff_at must not be after locked_at")

    approvals = cycle.get("approvals")
    if not isinstance(approvals, dict):
        errors.append("cycle.approvals is required")
        approvals = {}
    for role in ("po", "reviewer"):
        approval = approvals.get(role)
        if not isinstance(approval, dict):
            errors.append(f"cycle.approvals.{role} is required")
            continue
        _required_text(approval, "name", f"cycle.approvals.{role}", errors)
        _required_text(approval, "basis", f"cycle.approvals.{role}", errors)
        _iso_value(approval.get("approved_on"), f"cycle.approvals.{role}.approved_on", errors)

    selection = cycle.get("selection_policy")
    if not isinstance(selection, dict):
        errors.append("cycle.selection_policy is required")
    else:
        if selection.get("parser_results_consulted") is not False:
            errors.append("selection must be locked before parser results are consulted")
        _required_text(selection, "basis", "cycle.selection_policy", errors)
        if selection.get("failures_removable_within_cycle") is not False:
            errors.append("failures_removable_within_cycle must be false")

    cases = data.get("cases")
    if not isinstance(cases, list):
        errors.append("cases must be a list")
        cases = []
    if len(cases) != 24:
        errors.append(f"cases must contain exactly 24 entries, found {len(cases)}")

    case_ids: list[str] = []
    issuer_ids: list[str] = []
    listings: list[tuple[str, str]] = []
    ciks: list[str] = []
    strata: Counter[str] = Counter()
    tags: Counter[str] = Counter()

    for index, case in enumerate(cases):
        path = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{path} must be a mapping")
            continue
        for key in (
            "case_id",
            "economic_issuer_id",
            "company_name",
            "cik",
            "reporting_currency",
            "fiscal_year_end_mmdd",
            "filing_regime",
            "primary_stratum",
            "reason",
        ):
            _required_text(case, key, path, errors)

        case_ids.append(str(case.get("case_id") or ""))
        issuer_ids.append(str(case.get("economic_issuer_id") or ""))
        cik = str(case.get("cik") or "")
        ciks.append(cik)
        if not CIK_RE.fullmatch(cik):
            errors.append(f"{path}.cik must be a zero-padded 10-digit CIK")

        currency = str(case.get("reporting_currency") or "")
        if not CURRENCY_RE.fullmatch(currency):
            errors.append(f"{path}.reporting_currency must be ISO-4217 shaped")
        fye = str(case.get("fiscal_year_end_mmdd") or "")
        if not FISCAL_YEAR_END_RE.fullmatch(fye):
            errors.append(f"{path}.fiscal_year_end_mmdd must be MMDD")
        elif fye == "0229":
            errors.append(
                f"{path}.fiscal_year_end_mmdd 0229 is unsupported for a "
                "recurring fiscal year end"
            )
        else:
            try:
                date(2000, int(fye[:2]), int(fye[2:]))
            except ValueError:
                errors.append(f"{path}.fiscal_year_end_mmdd must be a real month/day")

        regime = case.get("filing_regime")
        if regime not in ALLOWED_REGIMES:
            errors.append(f"{path}.filing_regime is unsupported")
        stratum = str(case.get("primary_stratum") or "")
        strata[stratum] += 1

        listing = case.get("primary_listing")
        if not isinstance(listing, dict):
            errors.append(f"{path}.primary_listing is required")
        else:
            for key in ("ticker", "mic", "country", "instrument_type", "share_class"):
                _required_text(listing, key, f"{path}.primary_listing", errors)
            if not TICKER_RE.fullmatch(str(listing.get("ticker") or "")):
                errors.append(f"{path}.primary_listing.ticker is malformed")
            if not MIC_RE.fullmatch(str(listing.get("mic") or "")):
                errors.append(f"{path}.primary_listing.mic is malformed")
            if not COUNTRY_RE.fullmatch(str(listing.get("country") or "")):
                errors.append(f"{path}.primary_listing.country is malformed")
            if listing.get("instrument_type") not in ALLOWED_INSTRUMENT_TYPES:
                errors.append(f"{path}.primary_listing.instrument_type is unsupported")
            if not SHARE_CLASS_RE.fullmatch(str(listing.get("share_class") or "")):
                errors.append(f"{path}.primary_listing.share_class is malformed")
            listings.append((str(listing.get("ticker") or ""), str(listing.get("mic") or "")))

        case_tags = case.get("cross_cutting_tags")
        if not isinstance(case_tags, list):
            errors.append(f"{path}.cross_cutting_tags must be a list")
            case_tags = []
        unknown_tags = set(case_tags) - set(CROSS_CUTTING_MINIMUMS)
        if unknown_tags:
            errors.append(f"{path}.cross_cutting_tags contains unknown values: {sorted(unknown_tags)}")
        tags.update(set(case_tags))
        if currency != "USD" and "non_usd_reporting_currency" not in case_tags:
            errors.append(f"{path} non-USD case must carry non_usd_reporting_currency")
        if stratum == "foreign_issuer" and regime != "foreign_20f_6k":
            errors.append(f"{path} foreign issuer must use foreign_20f_6k")

        history = case.get("expected_history")
        if not isinstance(history, dict):
            errors.append(f"{path}.expected_history is required")
        else:
            _iso_value(history.get("available_start_on"), f"{path}.expected_history.available_start_on", errors)
            if history.get("completed_fiscal_year_cap") != 10:
                errors.append(f"{path}.expected_history.completed_fiscal_year_cap must equal 10")
            unavailable = history.get("unavailable_years")
            if not isinstance(unavailable, list):
                errors.append(f"{path}.expected_history.unavailable_years must be a list")
            else:
                for unavailable_index, item in enumerate(unavailable):
                    if not isinstance(item, dict) or item.get("disposition") not in {
                        "expected",
                        "unexpected",
                    }:
                        errors.append(
                            f"{path}.expected_history.unavailable_years[{unavailable_index}] "
                            "requires expected/unexpected disposition"
                        )

    def _duplicates(values: list[Any]) -> list[Any]:
        counts = Counter(values)
        return [value for value, count in counts.items() if value and count > 1]

    if duplicate := _duplicates(case_ids):
        errors.append(f"duplicate case_id: {duplicate}")
    if duplicate := _duplicates(issuer_ids):
        errors.append(f"duplicate economic issuer: {duplicate}")
    if duplicate := _duplicates(listings):
        errors.append(f"duplicate primary listing: {duplicate}")
    if duplicate := _duplicates(ciks):
        errors.append(f"duplicate CIK: {duplicate}")

    if dict(strata) != EXPECTED_STRATA:
        errors.append(f"primary strata must equal {EXPECTED_STRATA}, found {dict(strata)}")
    for tag, minimum in CROSS_CUTTING_MINIMUMS.items():
        if tags[tag] < minimum:
            errors.append(f"{tag} requires at least {minimum} cases, found {tags[tag]}")

    if errors:
        raise GoldSetValidationError("; ".join(errors))
    return GoldSetValidationReport(
        case_count=len(cases),
        distinct_economic_issuers=len(set(issuer_ids)),
        primary_strata=dict(strata),
        cross_cutting_counts=dict(tags),
    )


def load_and_validate_gold_set(path: Path) -> GoldSetValidationReport:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return validate_gold_set(data)
