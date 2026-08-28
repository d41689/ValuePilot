from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from typing import Any

from bs4 import BeautifulSoup, Tag


@dataclass(frozen=True)
class ParsedInlineXbrlFact:
    concept: str
    concept_namespace_uri: str | None
    context_id: str | None
    unit_id: str | None
    unit_measure: str | None
    raw_value: str | None
    transformation_format: str | None
    language: str | None
    continued_at: str | None
    decimals: str | None
    scale: int | None
    sign: str | None
    is_nil: bool
    period_instant: date | None
    period_start: date | None
    period_end: date | None
    entity_identifier: str | None
    dimensions: dict[str, str]
    locator: dict[str, Any]


def _local_name(tag: Tag) -> str:
    return str(tag.name or "").split(":")[-1].lower()


def _attr(tag: Tag, name: str) -> str | None:
    wanted = name.lower()
    for key, value in tag.attrs.items():
        if str(key).lower() == wanted:
            if isinstance(value, list):
                return " ".join(str(item) for item in value)
            return str(value)
    return None


def _first_descendant(tag: Tag, local_name: str) -> Tag | None:
    return tag.find(lambda item: isinstance(item, Tag) and _local_name(item) == local_name)


def _date_text(tag: Tag | None) -> date | None:
    if tag is None:
        return None
    try:
        return date.fromisoformat(tag.get_text(strip=True))
    except ValueError:
        return None


def _context_map(soup: BeautifulSoup) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for context in soup.find_all(lambda item: isinstance(item, Tag) and _local_name(item) == "context"):
        context_id = _attr(context, "id")
        if not context_id:
            continue
        dimensions: dict[str, str] = {}
        for member in context.find_all(
            lambda item: isinstance(item, Tag)
            and _local_name(item) in {"explicitmember", "typedmember"}
        ):
            dimension = _attr(member, "dimension")
            if dimension:
                dimensions[dimension] = member.get_text(" ", strip=True)
        contexts[context_id] = {
            "period_instant": _date_text(_first_descendant(context, "instant")),
            "period_start": _date_text(_first_descendant(context, "startdate")),
            "period_end": _date_text(_first_descendant(context, "enddate")),
            "entity_identifier": (
                _first_descendant(context, "identifier").get_text(strip=True)
                if _first_descendant(context, "identifier")
                else None
            ),
            "dimensions": dimensions,
        }
    return contexts


def _unit_map(soup: BeautifulSoup) -> dict[str, str]:
    units: dict[str, str] = {}
    for unit in soup.find_all(lambda item: isinstance(item, Tag) and _local_name(item) == "unit"):
        unit_id = _attr(unit, "id")
        if not unit_id:
            continue

        def measures_within(container: Tag | None) -> list[str]:
            if container is None:
                return []
            return [
                measure.get_text(strip=True)
                for measure in container.find_all(
                    lambda item: isinstance(item, Tag) and _local_name(item) == "measure"
                )
            ]

        divide = _first_descendant(unit, "divide")
        if divide is not None:
            numerator = measures_within(_first_descendant(divide, "unitnumerator"))
            denominator = measures_within(_first_descendant(divide, "unitdenominator"))
            if numerator and denominator:
                units[unit_id] = f"{'*'.join(numerator)}/{'*'.join(denominator)}"
                continue
        measures = measures_within(unit)
        units[unit_id] = "*".join(measures) if measures else unit_id
    return units


def _namespace_map(soup: BeautifulSoup) -> dict[str, str]:
    namespaces: dict[str, str] = {}
    root = soup.find("html")
    if root is None:
        return namespaces
    for key, value in root.attrs.items():
        raw_key = str(key).lower()
        if raw_key.startswith("xmlns:"):
            namespaces[raw_key.split(":", 1)[1]] = str(value)
    return namespaces


def parse_inline_xbrl(content: bytes, *, artifact_id: int) -> list[ParsedInlineXbrlFact]:
    soup = BeautifulSoup(content, "html.parser")
    contexts = _context_map(soup)
    units = _unit_map(soup)
    namespaces = _namespace_map(soup)
    results: list[ParsedInlineXbrlFact] = []
    for ordinal, fact in enumerate(
        soup.find_all(
            lambda item: isinstance(item, Tag)
            and _local_name(item) in {"nonfraction", "nonnumeric"}
        ),
        start=1,
    ):
        concept = _attr(fact, "name")
        if not concept:
            continue
        context_id = _attr(fact, "contextref")
        context = contexts.get(context_id or "", {})
        raw_value = fact.get_text(" ", strip=True) or None
        nearby = fact.parent.get_text(" ", strip=True)[:500] if fact.parent else (raw_value or "")
        scale_raw = _attr(fact, "scale")
        try:
            scale = int(scale_raw) if scale_raw is not None else None
        except ValueError:
            scale = None
        nil_raw = (_attr(fact, "xsi:nil") or _attr(fact, "nil") or "").lower()
        element_id = _attr(fact, "id")
        locator = {
            "artifact_id": artifact_id,
            "element_id": element_id,
            "dom_ordinal": ordinal,
            "locator_type": "inline_xbrl_html",
            "nearby_text_snippet": nearby,
            "nearby_text_sha256": hashlib.sha256(nearby.encode("utf-8")).hexdigest(),
        }
        results.append(
            ParsedInlineXbrlFact(
                concept=concept,
                concept_namespace_uri=namespaces.get(concept.split(":", 1)[0].lower())
                if ":" in concept
                else None,
                context_id=context_id,
                unit_id=_attr(fact, "unitref"),
                unit_measure=units.get(_attr(fact, "unitref") or ""),
                raw_value=raw_value,
                transformation_format=_attr(fact, "format"),
                language=_attr(fact, "xml:lang") or _attr(fact, "lang"),
                continued_at=_attr(fact, "continuedat"),
                decimals=_attr(fact, "decimals"),
                scale=scale,
                sign=_attr(fact, "sign"),
                is_nil=nil_raw in {"true", "1"},
                period_instant=context.get("period_instant"),
                period_start=context.get("period_start"),
                period_end=context.get("period_end"),
                entity_identifier=context.get("entity_identifier"),
                dimensions=dict(context.get("dimensions") or {}),
                locator=locator,
            )
        )
    return results
