from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import logging
import re
from typing import Any, Iterable, Optional

import yaml


LOGGER = logging.getLogger(__name__)

METRIC_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
TOKEN_RE = re.compile(r"^(?P<key>.+?)(?P<list>\[\])?$")


@dataclass(frozen=True)
class MappingMatch:
    value: Any
    path: str
    context: dict[str, Any]


class MappingSpec:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.mappings = spec.get("mappings", [])

    @classmethod
    def load(cls, path: Path) -> "MappingSpec":
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls(data)

    def generate_facts(self, page_json: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str], set[str]]:
        facts: list[dict[str, Any]] = []
        used_paths: set[str] = set()
        for mapping in self.mappings:
            json_path = mapping.get("json_path")
            if not json_path:
                continue
            for match in _iter_matches(page_json, json_path):
                used_paths.add(match.path)
                metric_key = _resolve_metric_key(mapping, match)
                if metric_key is None:
                    continue
                value_numeric, value_text, value_json, unit, used = _extract_value(
                    mapping,
                    match,
                    page_json,
                )
                used_paths.update(used)
                if value_numeric is None and value_text is None and value_json is None:
                    continue
                period_end_date, period_type = _resolve_period_end(mapping, match, page_json)
                if period_end_date is None and period_type in {"FY", "Q", "EVENT", "AS_OF"}:
                    # Skip facts that require a concrete date but none is available.
                    continue
                facts.append(
                    {
                        "metric_key": metric_key,
                        "value_numeric": value_numeric,
                        "value_text": value_text,
                        "value_json": value_json,
                        "unit": unit,
                        "period_type": period_type,
                        "period_end_date": period_end_date,
                    }
                )
        unmapped = _unmapped_paths(page_json, used_paths)
        return facts, used_paths, unmapped


def _iter_matches(root: dict[str, Any], json_path: str) -> Iterable[MappingMatch]:
    tokens = json_path.split(".")
    yield from _walk_tokens(root, tokens, [], {}, root)


def _walk_tokens(
    node: Any,
    tokens: list[str],
    path_parts: list[str],
    context: dict[str, Any],
    root: dict[str, Any],
) -> Iterable[MappingMatch]:
    if not tokens:
        yield MappingMatch(node, ".".join(path_parts), context)
        return

    token = tokens[0]
    if token == "*":
        if isinstance(node, dict):
            for key, value in node.items():
                next_context = dict(context)
                next_context["key"] = key
                if isinstance(value, dict) and "period_end" in value:
                    next_context["period_end"] = value.get("period_end")
                yield from _walk_tokens(
                    value,
                    tokens[1:],
                    path_parts + [str(key)],
                    next_context,
                    root,
                )
        return

    match = TOKEN_RE.match(token)
    if not match:
        return
    key = match.group("key")
    is_list = bool(match.group("list"))
    if not isinstance(node, dict) or key not in node:
        return
    next_node = node[key]
    if not is_list:
        yield from _walk_tokens(next_node, tokens[1:], path_parts + [key], context, root)
        return

    if isinstance(next_node, list):
        for idx, item in enumerate(next_node):
            next_context = dict(context)
            next_context["index"] = idx
            if isinstance(item, dict):
                if "calendar_year" in item:
                    next_context["calendar_year"] = item.get("calendar_year")
                if "period_end" in item:
                    next_context["period_end"] = item.get("period_end")
                if "fact_nature" in item:
                    next_context["fact_nature"] = item.get("fact_nature")
                full_year = item.get("full_year") if isinstance(item.get("full_year"), dict) else None
                if full_year is not None and "is_estimated" in full_year:
                    next_context["is_estimated"] = full_year.get("is_estimated")
                if full_year is not None and "fact_nature" in full_year:
                    next_context["fact_nature"] = full_year.get("fact_nature")
            yield from _walk_tokens(
                item,
                tokens[1:],
                path_parts + [f"{key}[{idx}]"],
                next_context,
                root,
            )


def _resolve_metric_key(mapping: dict[str, Any], match: MappingMatch) -> Optional[str]:
    template = mapping.get("metric_key_template")
    metric_key_from = mapping.get("metric_key_from")
    if template:
        if not metric_key_from:
            return None
        source = _resolve_relative_path(match.value, metric_key_from)
        if not isinstance(source, str):
            LOGGER.warning("Mapping %s missing metric_key_from value", mapping.get("id"))
            return None
        source = source.strip()
        if not re.fullmatch(r"[a-z0-9_]+", source):
            LOGGER.warning("Invalid metric_key_from token: %s", source)
            return None
        metric_key = template.format(metric_key=source)
    else:
        metric_key = mapping.get("metric_key")
        if not isinstance(metric_key, str):
            return None

    if not METRIC_KEY_RE.fullmatch(metric_key):
        LOGGER.warning("Invalid metric_key: %s", metric_key)
        return None
    return metric_key


def _extract_value(
    mapping: dict[str, Any],
    match: MappingMatch,
    root: dict[str, Any],
) -> tuple[Optional[float], Optional[str], Optional[dict[str, Any]], Optional[str], set[str]]:
    value_spec = mapping.get("value", {})
    value_numeric = None
    value_text = None
    value_json: Optional[dict[str, Any]] = None
    unit = mapping.get("unit")
    used_paths: set[str] = set()

    if "numeric_from" in value_spec:
        numeric, path = _resolve_value_path(match, root, value_spec.get("numeric_from"))
        if path:
            used_paths.add(path)
        if numeric is not None:
            value_numeric, unit = _normalize_numeric(numeric, unit)
    if "text_from" in value_spec:
        text_val, path = _resolve_value_path(match, root, value_spec.get("text_from"))
        if path:
            used_paths.add(path)
        if text_val is not None:
            value_text = str(text_val)
    if "json_from" in value_spec:
        json_val, path = _resolve_value_path(match, root, value_spec.get("json_from"))
        if path:
            used_paths.add(path)
        if isinstance(json_val, dict):
            value_json = json_val

    if value_json is None and (value_numeric is not None or value_text is not None):
        fact_nature = _fact_nature(mapping, match, root)
        if fact_nature is not None:
            value_json = {"fact_nature": fact_nature}
            if fact_nature == "estimate":
                value_json["is_estimate"] = True

    return value_numeric, value_text, value_json, unit, used_paths


def _resolve_period_end(
    mapping: dict[str, Any],
    match: MappingMatch,
    root: dict[str, Any],
) -> tuple[Optional[date], Optional[str]]:
    period_type = mapping.get("period_type")
    period_spec = mapping.get("period_end_date", {})
    period_end: Optional[date] = None
    if "from" in period_spec:
        raw, _ = _resolve_value_path(match, root, period_spec.get("from"))
        period_end = _parse_date(raw)
    elif "derive" in period_spec:
        derive = period_spec.get("derive")
        if derive == "year_end_from_key":
            year = _parse_year(match.context.get("key"))
            period_end = date(year, 12, 31) if year else None
        elif derive == "year_end_from_context":
            year = _parse_year(match.context.get("calendar_year"))
            period_end = date(year, 12, 31) if year else None
        elif derive == "quarter_end_from_context":
            raw = match.context.get("period_end")
            period_end = _parse_date(raw)
        elif derive == "financial_position_date_from_index":
            period_end, period_type = _financial_position_date(match, root, period_type)
    return period_end, period_type


def _financial_position_date(
    match: MappingMatch,
    root: dict[str, Any],
    period_type: Optional[str],
) -> tuple[Optional[date], Optional[str]]:
    idx = match.context.get("index")
    if idx is None:
        return None, period_type
    years = _resolve_path(root, "financial_position.years")
    if not isinstance(years, list) or idx >= len(years):
        return None, period_type
    label = years[idx]
    year = _parse_year(label)
    if year and len(str(label)) == 4:
        return date(year, 12, 31), "FY"
    parsed = _parse_date(label)
    return parsed, period_type


def _resolve_value_path(match: MappingMatch, root: dict[str, Any], path: Any) -> tuple[Any, Optional[str]]:
    if not isinstance(path, str):
        return None, None
    if path == "$value":
        return match.value, match.path
    relative = _resolve_relative_path(match.value, path)
    if relative is not None:
        return relative, f"{match.path}.{path}"
    return _resolve_path(root, path), path


def _resolve_relative_path(node: Any, path: str) -> Any:
    if path is None:
        return None
    if path == "$value":
        return node
    if not isinstance(node, dict):
        return None
    return _resolve_path(node, path)


def _resolve_path(node: Any, path: str) -> Any:
    if not path:
        return None
    parts = path.split(".")
    current: Any = node
    for part in parts:
        if current is None:
            return None
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _normalize_numeric(value: Any, unit: Optional[str]) -> tuple[Optional[float], Optional[str]]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None, unit

    if unit == "USD_millions":
        return numeric * 1_000_000.0, "USD"
    if unit == "million_shares":
        return numeric * 1_000_000.0, "shares"
    if unit == "percent":
        return numeric / 100.0, "ratio"
    if unit == "USD_per_share":
        return numeric, "USD"
    return numeric, unit


def _is_estimate(mapping: dict[str, Any], match: MappingMatch, root: dict[str, Any]) -> bool:
    fact_nature = match.context.get("fact_nature")
    if fact_nature == "estimate":
        return True
    if match.context.get("is_estimated") is True:
        return True
    if mapping.get("period_type") != "FY":
        return False
    year = _parse_year(match.context.get("key") or match.context.get("calendar_year"))
    if year is None:
        return False
    estimate_years = _resolve_path(root, "annual_financials.meta.estimate_years")
    if isinstance(estimate_years, list):
        return year in {int(y) for y in estimate_years if _parse_year(y) is not None}
    years = _resolve_path(root, "annual_financials.meta.historical_years")
    if isinstance(years, list) and years:
        try:
            return int(years[-1]) == year
        except (TypeError, ValueError):
            return False
    return False


def _fact_nature(mapping: dict[str, Any], match: MappingMatch, root: dict[str, Any]) -> Optional[str]:
    fact_nature = match.context.get("fact_nature")
    if isinstance(fact_nature, str):
        return fact_nature
    if mapping.get("period_type") == "FY":
        year = _parse_year(match.context.get("key") or match.context.get("calendar_year"))
        if year is None:
            return None
        estimate_years = _resolve_path(root, "annual_financials.meta.estimate_years")
        if isinstance(estimate_years, list) and year in {int(y) for y in estimate_years if _parse_year(y) is not None}:
            return "estimate"
        actual_years = _resolve_path(root, "annual_financials.meta.actual_years")
        if isinstance(actual_years, list) and year in {int(y) for y in actual_years if _parse_year(y) is not None}:
            return "actual"
    if _is_estimate(mapping, match, root):
        return "estimate"
    return None


def _parse_year(value: Any) -> Optional[int]:
    if value is None:
        return None
    raw = str(value)
    if raw.isdigit() and len(raw) == 4:
        return int(raw)
    return None


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    raw = str(value)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _unmapped_paths(page_json: dict[str, Any], used_paths: set[str]) -> set[str]:
    leaf_paths = set(_flatten_paths(page_json))
    normalized_used = {_normalize_path(p) for p in used_paths}
    return {p for p in leaf_paths if _normalize_path(p) not in normalized_used}


def _flatten_paths(node: Any, prefix: str = "") -> Iterable[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            yield from _flatten_paths(value, next_prefix)
        return
    if isinstance(node, list):
        for idx, item in enumerate(node):
            next_prefix = f"{prefix}[{idx}]"
            yield from _flatten_paths(item, next_prefix)
        return
    yield prefix


def _normalize_path(path: str) -> str:
    path = re.sub(r"\[\d+\]", "[]", path)
    parts = []
    for part in path.split("."):
        if part.isdigit():
            parts.append("*")
            continue
        if re.match(r"^projection_\d", part):
            parts.append("projection_*")
            continue
        parts.append(part)
    return ".".join(parts)
