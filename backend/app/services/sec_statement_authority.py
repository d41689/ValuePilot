"""Bounded, non-networking retained SEC statement presentation authority."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import hashlib, json, re
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
from typing import Sequence
from bs4 import BeautifulSoup, Tag
from app.services.sec_financial_mapping import RawFactSnapshot

MAX_FILING_SUMMARY_BYTES = 1_000_000
MAX_STATEMENT_REPORTS = 64
MAX_STATEMENT_REPORT_BYTES = 5_000_000
MAX_OCCURRENCES_PER_REPORT = 20_000
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_MONTH = {name.lower(): index for index, name in enumerate(_MONTH_NAMES, 1)}
_MONTH.update({name[:3].lower(): index for index, name in enumerate(_MONTH_NAMES, 1)})
_MONTH["sept"] = 9
_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)"
    r"\s+(\d{1,2}),?\s+(\d{4})\b",
    re.I,
)
_DEFREF = re.compile(
    r"\A\s*(?:top\.)?Show\.showAR\(\s*this\s*,\s*"
    r"(?P<quote>['\"])defref_(?P<target>[A-Za-z0-9_-]+)(?P=quote)"
    r"\s*,\s*window\s*\)\s*;?\s*\Z",
    re.I,
)
_RAW_ONCLICK_ATTRIBUTE = re.compile(
    r"(?<!\S)(?P<attribute>onclick\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote))",
    re.I | re.S,
)
_XLINK = "{http://www.w3.org/1999/xlink}"
_STANDARD_LABEL_ROLE = "http://www.xbrl.org/2003/role/label"
_STATEMENT_REPORT_FIELDS = frozenset({
    "position", "role", "xmlfilename", "htmlfilename", "shortname",
    "longname", "menucategory",
})
_CLASS_TO_CYCLE = {"current_period": "filing_quarter_end", "prior_same_fiscal_quarter": "explicit_prior_same_fiscal_quarter_comparative", "prior_fiscal_year_comparative": "explicit_prior_fiscal_year_comparative", "prior_fiscal_year_balance_sheet": "explicit_prior_fiscal_year_end_balance_sheet"}

class StatementAuthorityParseError(ValueError): reason_code = "statement_authority_parse_failed"


@dataclass(frozen=True)
class _RawAnchorAuthority:
    onclick_values: tuple[str, ...]
    start_tag: str


class _RawAnchorParser(HTMLParser):
    """Keep duplicate anchor attributes before an HTML tree can collapse them."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[_RawAnchorAuthority] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        self.anchors.append(_RawAnchorAuthority(
            tuple(
                value or ""
                for name, value in attrs
                if name.lower() == "onclick"
            ),
            self.get_starttag_text(),
        ))

@dataclass(frozen=True)
class StatementReportReference:
    report_ordinal: int; report_name: str; filename: str; statement_role: str; statement_type: str
    fallback_filename: str | None = None

@dataclass(frozen=True)
class StatementOccurrence:
    context_id: str; concept: str; occurrence_ordinal: int; locator: dict[str, object]
    fact_id: str | None; raw_value: str; unit_id: str | None; column_header: str; semantic_digest: str

@dataclass(frozen=True)
class GeneratedConceptRejection:
    concept: str; reason: str; row_ordinal: int; column_ordinal: int

@dataclass(frozen=True)
class GeneratedStatementResolution:
    occurrences: tuple[StatementOccurrence, ...]
    rejected_concepts: frozenset[str]
    rejections: tuple[GeneratedConceptRejection, ...]

@dataclass(frozen=True)
class ExplicitFiscalFocus:
    statement_period_end: date; fiscal_year: int; fiscal_quarter_ordinal: int | None
    fiscal_year_start: date; prior_fiscal_year_start: date | None = None

@dataclass(frozen=True)
class DeiFocusEvidence:
    namespace_uri: str | None; local_name: str; raw_value: str
    dimensions: tuple[object, ...]

@dataclass(frozen=True)
class PresentedPeriodEvidence:
    column_header: str; period_start: date | None; period_end: date
    reference_key: str = ""; row_ordinal: int = 0; concept: str = ""; column_ordinal: int = 0

@dataclass(frozen=True)
class RawOccurrenceIdentity:
    raw_fact_id: int; context_id: str; concept: str; raw_value: str
    unit_id: str | None; element_id: str | None
    period_start: date | None = None; period_end: date | None = None
    dimensions: tuple[object, ...] = ()
    unit_numerator: tuple[object, ...] = (); unit_denominator: tuple[object, ...] = ()
    decimals: str | None = None; scale: int | None = None; sign: str | None = None
    is_nil: bool = False; is_hidden: bool = False

@dataclass(frozen=True)
class ClassifiedPresentation:
    presentation_class: str; statement_period_end: date; fiscal_year: int
    fiscal_quarter_ordinal: int | None; fiscal_year_start: date

@dataclass(frozen=True)
class StatementAuthoritySnapshot:
    raw_fact_id: int; parse_run_id: int; context_id: str; presentation_class: str
    statement_period_end: date; fiscal_year: int; fiscal_quarter_ordinal: int | None
    fiscal_year_start: date; report_ordinal: int; occurrence_ordinal: int

def _local(tag: str) -> str: return tag.rsplit("}", 1)[-1].lower()
def _reject_declarations(content: bytes) -> None:
    lowered = content.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered: raise StatementAuthorityParseError("unsafe_xml_declaration")
def _safe_filename(value: str) -> str:
    name = value.strip()
    if not name or PurePosixPath(name).name != name or ".." in name or _SAFE_NAME.fullmatch(name) is None or PurePosixPath(name).suffix.lower() not in {".xml", ".htm", ".html"}: raise StatementAuthorityParseError("unsafe_statement_report_reference")
    return name
def _statement_type(role: str, name: str) -> str | None:
    value = f"{role} {name}".lower()
    if "balance" in value or "financial position" in value: return "balance_sheet"
    if "cash flow" in value: return "cash_flow"
    if "comprehensive" in value: return "comprehensive_income"
    if "income" in value or "operations" in value or "earnings" in value: return "income_statement"
    if "equity" in value or "stockholder" in value: return "equity"
    return None

def discover_statement_reports(content: bytes) -> tuple[StatementReportReference, ...]:
    if len(content) > MAX_FILING_SUMMARY_BYTES: raise StatementAuthorityParseError("filing_summary_exceeds_byte_limit")
    _reject_declarations(content)
    try: root = ET.fromstring(content)
    except ET.ParseError as exc: raise StatementAuthorityParseError("malformed_filing_summary") from exc
    reports = []
    for node in root.iter():
        if _local(node.tag) != "report": continue
        fields: dict[str, str] = {}
        for child in node:
            field = _local(child.tag)
            if field not in _STATEMENT_REPORT_FIELDS:
                continue
            if field in fields:
                raise StatementAuthorityParseError("ambiguous_statement_report_field")
            fields[field] = (child.text or "").strip()
        menu_category = fields.get("menucategory")
        if menu_category and menu_category.lower() != "statements":
            continue
        filename = fields.get("xmlfilename") or fields.get("htmlfilename") or ""
        fallback = fields.get("htmlfilename") if fields.get("xmlfilename") and fields.get("htmlfilename") else None
        if not filename: continue
        role = fields.get("role", "").strip()
        name = fields.get("shortname") or fields.get("longname") or filename
        kind = _statement_type(role, "")
        if kind is None: continue
        position = fields.get("position")
        if not position or not position.isdigit() or int(position) <= 0: raise StatementAuthorityParseError("missing_statement_report_position")
        ordinal = int(position)
        reports.append(StatementReportReference(ordinal, name[:255], _safe_filename(filename), role, kind, _safe_filename(fallback) if fallback else None))
        if len(reports) > MAX_STATEMENT_REPORTS: raise StatementAuthorityParseError("statement_report_count_exceeded")
    if not reports: raise StatementAuthorityParseError("no_statement_reports")
    identities = [(row.filename.lower(), row.report_ordinal) for row in reports]
    if (
        len(identities) != len(set(identities))
        or len({row.report_ordinal for row in reports}) != len(reports)
    ):
        raise StatementAuthorityParseError("duplicate_statement_report_reference")
    return tuple(sorted(reports, key=lambda row: (row.report_ordinal, row.filename.lower())))

def _digest(context, concept, fact_id, value, unit, header) -> str:
    material = chr(31).join((context, concept, fact_id or "", " ".join(value.split()), unit or ""))
    return hashlib.sha256(material.encode()).hexdigest()

def statement_reference_digest(summary_sha256: str, reference: StatementReportReference) -> str:
    material = chr(31).join((summary_sha256, reference.filename, str(reference.report_ordinal),
                             reference.statement_role, reference.statement_type, reference.report_name))
    return hashlib.sha256(material.encode()).hexdigest()

def parse_statement_header_date(header: str) -> date:
    matches = list(_DATE.finditer(header))
    if len(matches) != 1:
        raise StatementAuthorityParseError("unproven_statement_column_header")
    match = matches[0]
    month = match.group(1).lower().rstrip(".")
    return date(int(match.group(3)), _MONTH[month], int(match.group(2)))

def statement_occurrence_digest(report_sha256: str, report_ordinal: int,
                                occurrence: StatementOccurrence, header_date: date) -> str:
    fields = [report_sha256, str(report_ordinal), str(occurrence.locator.get("row", 0)),
        str(occurrence.locator.get("column", 0)), str(occurrence.occurrence_ordinal), occurrence.fact_id or "",
        occurrence.context_id, occurrence.concept, " ".join(occurrence.raw_value.split()), occurrence.unit_id or "",
        occurrence.column_header, " ".join(occurrence.column_header.split()), header_date.isoformat(),
        str(occurrence.locator.get("kind", "")), str(occurrence.locator.get("row", "")),
        str(occurrence.locator.get("column", "")), str(occurrence.locator.get("fact_id") or "")]
    if occurrence.locator.get("kind") == "sec_generated_statement_html_v2":
        fields.extend(str(occurrence.locator.get(key) if occurrence.locator.get(key) is not None else "") for key in (
            "display_value", "row_label", "statement_role", "presentation_order",
            "preferred_label_role", "scale_multiplier", "period_start", "period_end",
            "dimensions_sha256", "decimals", "presentation_artifact_id",
            "presentation_sha256", "label_artifact_id", "label_sha256",
            "canonical_duplicate_rule", "equivalent_raw_fact_ids", "onclick",
            "onclick_sha256", "onclick_attribute", "onclick_attribute_sha256",
            "anchor_start_tag", "anchor_start_tag_sha256",
        ))
    return hashlib.sha256(chr(31).join(fields).encode()).hexdigest()

def _xml_occurrences(content: bytes) -> list[StatementOccurrence]:
    _reject_declarations(content)
    try: root = ET.fromstring(content)
    except ET.ParseError as exc: raise StatementAuthorityParseError("malformed_statement_report") from exc
    columns = []
    for column in (node for node in root.iter() if _local(node.tag) == "column"):
        labels = [(node.get("Label") or node.get("label") or node.text or "").strip() for node in column.iter() if _local(node.tag) == "label"]
        columns.append(" ".join(item for item in labels if item))
    items = []
    for row_ordinal, row in enumerate((node for node in root.iter() if _local(node.tag) == "row"), start=1):
        concept = next(((node.text or "").strip() for node in row.iter() if _local(node.tag) == "elementname"), "")
        if ":" not in concept and "_" in concept: concept = concept.replace("_", ":", 1)
        if not concept: continue
        for index, cell in enumerate(node for node in row.iter() if _local(node.tag) == "cell"):
            fields = {_local(node.tag): (node.text or "").strip() for node in cell.iter() if node is not cell}
            context = cell.get("contextRef") or cell.get("contextref") or fields.get("contextref") or ""
            if not context: continue
            fact_id = cell.get("factId") or cell.get("factid") or fields.get("factid"); value = fields.get("numericamount") or fields.get("nonfractionvalue") or fields.get("text") or ""; unit = cell.get("unitRef") or cell.get("unitref") or fields.get("unitref"); header = columns[index] if index < len(columns) else ""
            locator = {"kind": "sec_statement_report_xml", "row": row_ordinal, "column": index + 1, "fact_id": fact_id}
            items.append(StatementOccurrence(context, concept, len(items) + 1, locator, fact_id, value, unit, header, _digest(context, concept, fact_id, value, unit, header)))
    return items

def _html_occurrences(content: bytes) -> list[StatementOccurrence]:
    try: soup = BeautifulSoup(content.decode("utf-8"), "html.parser")
    except UnicodeDecodeError as exc: raise StatementAuthorityParseError("malformed_statement_report") from exc
    items = []
    for fact in soup.find_all(lambda n: isinstance(n, Tag) and n.get("name") and (n.get("contextref") or n.get("contextRef"))):
        context = str(fact.get("contextref") or fact.get("contextRef")); concept = str(fact.get("name")); cell = fact.find_parent(["td", "th"]); header = ""
        if cell is not None and (table := cell.find_parent("table")) is not None:
            row = cell.find_parent("tr"); cells = row.find_all(["td", "th"], recursive=False) if row else []; index = cells.index(cell) if cell in cells else -1
            if index >= 0:
                labels = []
                for header_row in table.find_all("tr"):
                    candidates = header_row.find_all(["th", "td"], recursive=False)
                    if index < len(candidates) and candidates[index].find(attrs={"name": True}) is None: labels.append(candidates[index].get_text(" ", strip=True))
                header = " ".join(item for item in labels if item)
        fact_id = str(fact.get("id")) if fact.get("id") else None; value = fact.get_text(" ", strip=True); unit = fact.get("unitref") or fact.get("unitRef"); unit = str(unit) if unit else None
        locator = {"kind": "sec_statement_report_html", "fact_id": fact_id, "dom_ordinal": len(items) + 1}
        items.append(StatementOccurrence(context, concept, len(items) + 1, locator, fact_id, value, unit, header, _digest(context, concept, fact_id, value, unit, header)))
    return items

def parse_statement_occurrences(content: bytes, *, filename: str) -> tuple[StatementOccurrence, ...]:
    _safe_filename(filename)
    if len(content) > MAX_STATEMENT_REPORT_BYTES: raise StatementAuthorityParseError("statement_report_exceeds_byte_limit")
    items = _xml_occurrences(content) if filename.lower().endswith(".xml") else _html_occurrences(content)
    if len(items) > MAX_OCCURRENCES_PER_REPORT: raise StatementAuthorityParseError("statement_occurrence_count_exceeded")
    if not items: raise StatementAuthorityParseError("no_explicit_statement_occurrences")
    return tuple(items)


def _concept_from_fragment(value: str) -> str:
    fragment = value.rsplit("#", 1)[-1]
    if not fragment or re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]*_[A-Za-z_][A-Za-z0-9._-]*", fragment) is None:
        raise StatementAuthorityParseError("unsafe_presentation_concept_reference")
    return fragment.replace("_", ":", 1)


def _presentation_arcs(content: bytes, statement_role: str) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    if len(content) > MAX_STATEMENT_REPORT_BYTES:
        raise StatementAuthorityParseError("presentation_linkbase_exceeds_byte_limit")
    _reject_declarations(content)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise StatementAuthorityParseError("malformed_presentation_linkbase") from exc
    if not statement_role.strip():
        raise StatementAuthorityParseError("missing_statement_presentation_role")
    matches: dict[str, list[tuple[str, str]]] = {}
    for link in (node for node in root.iter() if _local(node.tag) == "presentationlink"):
        if (link.get(f"{_XLINK}role") or "") != statement_role:
            continue
        locators: dict[str, str] = {}
        for node in link:
            if _local(node.tag) != "loc":
                continue
            label = node.get(f"{_XLINK}label") or ""
            href = node.get(f"{_XLINK}href") or ""
            if not label or label in locators:
                raise StatementAuthorityParseError("ambiguous_presentation_locator")
            locators[label] = _concept_from_fragment(href)
        for arc in link:
            if _local(arc.tag) != "presentationarc":
                continue
            target = arc.get(f"{_XLINK}to") or ""
            concept = locators.get(target)
            order = (arc.get("order") or "").strip()
            preferred = (arc.get("preferredLabel") or _STANDARD_LABEL_ROLE).strip()
            try:
                order_value = Decimal(order)
            except InvalidOperation as exc:
                raise StatementAuthorityParseError("invalid_presentation_order") from exc
            if concept is None or not order_value.is_finite() or order_value <= 0 or not preferred:
                raise StatementAuthorityParseError("invalid_presentation_arc")
            canonical_order = format(order_value.normalize(), "f")
            matches.setdefault(concept, []).append((canonical_order, preferred))
    if not matches:
        raise StatementAuthorityParseError("missing_statement_presentation_role")
    result = {}
    rejected = {}
    for concept, rows in matches.items():
        if len(rows) != 1:
            rejected[concept] = "ambiguous_statement_presentation_arc"
            continue
        result[concept] = rows[0]
    return result, rejected


def _label_authorities(content: bytes) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    if len(content) > MAX_STATEMENT_REPORT_BYTES:
        raise StatementAuthorityParseError("label_linkbase_exceeds_byte_limit")
    _reject_declarations(content)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise StatementAuthorityParseError("malformed_label_linkbase") from exc
    xml_language = "{http://www.w3.org/XML/1998/namespace}lang"
    effective_languages: dict[ET.Element, str | None] = {}

    def record_effective_language(
        node: ET.Element, inherited: str | None
    ) -> None:
        declared = node.get(xml_language)
        effective = inherited if declared is None else declared.strip().lower()
        effective_languages[node] = effective
        for child in node:
            record_effective_language(child, effective)

    record_effective_language(root, None)
    values: dict[tuple[str, str], list[str]] = {}
    for link in (node for node in root.iter() if _local(node.tag) == "labellink"):
        locators: dict[str, str] = {}
        for node in link:
            if _local(node.tag) != "loc":
                continue
            label = (node.get(f"{_XLINK}label") or "").strip()
            if not label or label in locators:
                raise StatementAuthorityParseError("ambiguous_label_locator")
            locators[label] = _concept_from_fragment(
                node.get(f"{_XLINK}href") or ""
            )
        resources: dict[str, list[tuple[str | None, str, str]]] = {}
        resource_identities: set[tuple[str, str | None, str]] = set()
        for node in link:
            if _local(node.tag) != "label":
                continue
            resource_label = (node.get(f"{_XLINK}label") or "").strip()
            language = effective_languages[node]
            role = (node.get(f"{_XLINK}role") or _STANDARD_LABEL_ROLE).strip()
            identity = (resource_label, language, role)
            if not resource_label or not role or identity in resource_identities:
                raise StatementAuthorityParseError("ambiguous_label_resource")
            resource_identities.add(identity)
            resources.setdefault(resource_label, []).append(
                (language, role, " ".join(node.itertext()).strip())
            )
        arc_identities: set[tuple[str, str]] = set()
        for arc in (node for node in link if _local(node.tag) == "labelarc"):
            source = (arc.get(f"{_XLINK}from") or "").strip()
            target = (arc.get(f"{_XLINK}to") or "").strip()
            identity = (source, target)
            if (
                not source
                or not target
                or identity in arc_identities
                or source not in locators
                or target not in resources
            ):
                raise StatementAuthorityParseError("invalid_label_arc")
            arc_identities.add(identity)
            for language, role, label_text in resources[target]:
                if language not in {"en", "en-us"}:
                    continue
                if not label_text:
                    raise StatementAuthorityParseError("invalid_label_arc")
                values.setdefault((locators[source], role), []).append(label_text)
    result = {}
    rejected = {}
    for identity, labels in values.items():
        distinct = {" ".join(item.split()) for item in labels}
        if len(distinct) != 1:
            rejected[identity[0]] = "ambiguous_presentation_label"
            continue
        result[identity] = next(iter(distinct))
    return result, rejected


def _html_grid(table: Tag) -> list[list[tuple[Tag, str] | None]]:
    rows: list[list[tuple[Tag, str] | None]] = []
    spans: dict[int, tuple[int, tuple[Tag, str]]] = {}
    for tr in table.find_all("tr", recursive=False):
        row: list[tuple[Tag, str] | None] = []
        column = 0
        cells = tr.find_all(["td", "th"], recursive=False)
        for cell in cells:
            while column in spans:
                remaining, value = spans[column]
                row.append(value)
                if remaining == 1: del spans[column]
                else: spans[column] = (remaining - 1, value)
                column += 1
            try:
                colspan = int(cell.get("colspan") or 1); rowspan = int(cell.get("rowspan") or 1)
            except (TypeError, ValueError) as exc:
                raise StatementAuthorityParseError("invalid_statement_table_span") from exc
            if not (1 <= colspan <= 256 and 1 <= rowspan <= 256):
                raise StatementAuthorityParseError("invalid_statement_table_span")
            value = (cell, " ".join(cell.get_text(" ", strip=True).split()))
            for _ in range(colspan):
                row.append(value)
                if rowspan > 1: spans[column] = (rowspan - 1, value)
                column += 1
        while column in spans:
            remaining, value = spans[column]
            row.append(value)
            if remaining == 1: del spans[column]
            else: spans[column] = (remaining - 1, value)
            column += 1
        rows.append(row)
    if spans or len(rows) > MAX_OCCURRENCES_PER_REPORT:
        raise StatementAuthorityParseError("invalid_statement_table_shape")
    return rows


def _display_decimal(value: str) -> Decimal | None:
    lexical = " ".join(value.split()).strip()
    if not lexical or lexical in {"-", "--", "—"}:
        return None
    negative = lexical.startswith("(") and lexical.endswith(")")
    if negative: lexical = lexical[1:-1]
    lexical = lexical.replace("$", "").replace(",", "").strip()
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", lexical) is None:
        return None
    number = Decimal(lexical)
    return -number if negative else number


def _canonical_dimensions(value: tuple[object, ...]) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except TypeError as exc:
        raise StatementAuthorityParseError("invalid_raw_dimension_identity") from exc


def _unit_local(value: object) -> str:
    if isinstance(value, str):
        return value.rsplit(":", 1)[-1].lower()
    if isinstance(value, dict):
        return str(value.get("local_name") or "").lower()
    return ""


def _declared_multiplier(table_title: str, candidate: RawOccurrenceIdentity) -> Decimal:
    numerator = tuple(_unit_local(item) for item in candidate.unit_numerator)
    denominator = tuple(_unit_local(item) for item in candidate.unit_denominator)
    title = " ".join(table_title.lower().split())
    if denominator:
        return Decimal(1)
    if len(numerator) != 1:
        return Decimal(1)
    unit = numerator[0]
    if unit in {"shares", "share"} and re.search(r"\bshares\s+in\s+thousands\b", title):
        return Decimal(1000)
    if unit in {"usd", "eur", "gbp", "jpy", "cad", "aud", "chf"}:
        if re.search(r"(?:\$|currency|amounts?)\s+in\s+millions\b", title) or "$ in millions" in title:
            return Decimal(1_000_000)
        if re.search(r"(?:\$|currency|amounts?)\s+in\s+thousands\b", title) or "$ in thousands" in title:
            return Decimal(1000)
    return Decimal(1)


def _candidate_numeric(candidate: RawOccurrenceIdentity) -> Decimal | None:
    if candidate.is_nil or candidate.is_hidden:
        return None
    lexical = " ".join(candidate.raw_value.split()).replace(",", "")
    try:
        number = Decimal(lexical)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    if candidate.sign == "-": number = -number
    if candidate.scale is not None: number *= Decimal(10) ** candidate.scale
    return number


def _period_matches(header: str, candidate: RawOccurrenceIdentity) -> bool:
    try:
        header_end = parse_statement_header_date(header)
    except StatementAuthorityParseError:
        return False
    if candidate.period_end != header_end:
        return False
    lowered = header.lower()
    if "as of" in lowered:
        return candidate.period_start is None
    if candidate.period_start is None:
        return False
    days = (candidate.period_end - candidate.period_start).days + 1
    if "3 months ended" in lowered or "three months ended" in lowered: return 70 <= days <= 110
    if "6 months ended" in lowered or "six months ended" in lowered: return 150 <= days <= 210
    if "9 months ended" in lowered or "nine months ended" in lowered: return 240 <= days <= 300
    if "12 months ended" in lowered or "twelve months ended" in lowered or "year ended" in lowered: return 300 <= days <= 380
    return False


def parse_generated_statement_occurrences(
    content: bytes,
    *,
    filename: str,
    statement_role: str,
    presentation_linkbase: bytes,
    label_linkbase: bytes,
    candidates: Sequence[RawOccurrenceIdentity],
    presentation_artifact_id: int,
    presentation_sha256: str,
    label_artifact_id: int,
    label_sha256: str,
    allow_partial: bool = False,
) -> GeneratedStatementResolution:
    """Resolve SEC generated statement cells to one exact retained instance fact.

    R*.htm is presentation evidence, never fact authority by itself.  A cell is
    accepted only when the FilingSummary role, presentation arc, preferred
    English label, explicit period header, unit-aware declared scale and exact
    value identify one retained instance occurrence.
    """
    _safe_filename(filename)
    if not filename.lower().endswith((".htm", ".html")):
        raise StatementAuthorityParseError("generated_statement_html_required")
    if len(content) > MAX_STATEMENT_REPORT_BYTES:
        raise StatementAuthorityParseError("statement_report_exceeds_byte_limit")
    try:
        report_text = content.decode("utf-8")
        raw_anchor_parser = _RawAnchorParser()
        raw_anchor_parser.feed(report_text)
        raw_anchor_parser.close()
        soup = BeautifulSoup(report_text, "html.parser")
    except UnicodeDecodeError as exc:
        raise StatementAuthorityParseError("malformed_statement_report") from exc
    parsed_anchors = soup.find_all("a")
    if len(parsed_anchors) != len(raw_anchor_parser.anchors):
        raise StatementAuthorityParseError("malformed_statement_report")
    raw_anchor_authority = {
        id(anchor): raw
        for anchor, raw in zip(parsed_anchors, raw_anchor_parser.anchors, strict=True)
    }
    arcs, arc_rejections = _presentation_arcs(presentation_linkbase, statement_role)
    labels, label_rejections = _label_authorities(label_linkbase)
    items: list[StatementOccurrence] = []
    rejected_concepts = set(arc_rejections) | set(label_rejections)
    rejections = [
        GeneratedConceptRejection(concept, reason, 0, 0)
        for concept, reason in sorted({**arc_rejections, **label_rejections}.items())
    ]

    def reject(concept: str, reason: str, row: int, column: int) -> None:
        if not allow_partial:
            raise StatementAuthorityParseError(
                f"{reason}:{row}:{column}:{concept}"
            )
        rejected_concepts.add(concept)
        rejections.append(GeneratedConceptRejection(concept, reason, row, column))

    for table in soup.find_all("table"):
        grid = _html_grid(table)
        table_title = " ".join(table.get_text(" ", strip=True).split())[:2000]
        for row_index, row in enumerate(grid, start=1):
            if not row: continue
            anchors = row[0][0].find_all("a") if row[0] is not None else []
            identities = []
            for anchor in anchors:
                raw_anchor = raw_anchor_authority[id(anchor)]
                raw_matches = list(
                    _RAW_ONCLICK_ATTRIBUTE.finditer(raw_anchor.start_tag)
                )
                relevant = any(
                    "showar" in value.lower() or "defref_" in value.lower()
                    for value in raw_anchor.onclick_values
                ) or any(
                    "showar" in match.group("value").lower()
                    or "defref_" in match.group("value").lower()
                    for match in raw_matches
                )
                if len(raw_anchor.onclick_values) != 1 or len(raw_matches) != 1:
                    if relevant:
                        raise StatementAuthorityParseError(
                            "ambiguous_generated_statement_onclick"
                        )
                    continue
                onclick = raw_matches[0].group("value")
                if "showar" not in onclick.lower() and "defref_" not in onclick.lower():
                    continue
                match = _DEFREF.fullmatch(onclick)
                if match is None:
                    raise StatementAuthorityParseError("ambiguous_generated_statement_onclick")
                identities.append((
                    _concept_from_fragment(match.group("target")),
                    " ".join(anchor.get_text(" ", strip=True).split()),
                    onclick,
                    raw_matches[0].group("attribute"),
                    raw_anchor.start_tag,
                ))
            if not identities: continue
            if len(identities) != 1:
                raise StatementAuthorityParseError("ambiguous_generated_statement_concept")
            concept, row_label, onclick, onclick_attribute, anchor_start_tag = identities[0]
            arc = arcs.get(concept)
            numeric_cells = [
                (column_index, cell)
                for column_index, cell in enumerate(row[1:], start=2)
                if cell is not None and _display_decimal(cell[1]) is not None
            ]
            if arc is None or labels.get((concept, arc[1])) != row_label:
                for column_index, _ in numeric_cells:
                    reject(
                        concept,
                        "unproven_generated_statement_presentation",
                        row_index,
                        column_index,
                    )
                continue
            for column_index, cell in enumerate(row[1:], start=2):
                if cell is None: continue
                display_raw = cell[1]
                display = _display_decimal(display_raw)
                if display is None: continue
                header_parts = []
                for header_row in grid[:row_index - 1]:
                    if column_index - 1 < len(header_row) and header_row[column_index - 1] is not None:
                        token = header_row[column_index - 1][1]
                        if _DATE.search(token) is not None or re.search(r"\b(?:three|six|nine|twelve|3|6|9|12)\s+months?\s+ended\b|\bas of\b|\byear ended\b", token, re.I):
                            if token not in header_parts: header_parts.append(token)
                header = " ".join(header_parts)
                matching = []
                for candidate in candidates:
                    if candidate.concept != concept or not _period_matches(header, candidate): continue
                    numeric = _candidate_numeric(candidate)
                    multiplier = _declared_multiplier(table_title, candidate)
                    if numeric is not None and display * multiplier == numeric:
                        matching.append((candidate, multiplier))
                if not matching:
                    reject(
                        concept,
                        "unresolved_generated_statement_occurrence",
                        row_index,
                        column_index,
                    )
                    continue
                identity_groups: dict[tuple[object, ...], list[tuple[RawOccurrenceIdentity, Decimal]]] = {}
                for matched, multiplier in matching:
                    identity_groups.setdefault((
                        matched.context_id,
                        matched.concept,
                        " ".join(matched.raw_value.split()),
                        matched.unit_id,
                        matched.period_start,
                        matched.period_end,
                        _canonical_dimensions(matched.dimensions),
                        tuple(json.dumps(item, sort_keys=True) if isinstance(item, dict) else str(item) for item in matched.unit_numerator),
                        tuple(json.dumps(item, sort_keys=True) if isinstance(item, dict) else str(item) for item in matched.unit_denominator),
                        matched.decimals,
                        matched.scale,
                        matched.sign,
                    ), []).append((matched, multiplier))
                if len(identity_groups) != 1:
                    reject(
                        concept,
                        "ambiguous_generated_statement_occurrence",
                        row_index,
                        column_index,
                    )
                    continue
                equivalent = next(iter(identity_groups.values()))
                candidate, multiplier = min(equivalent, key=lambda item: item[0].raw_fact_id)
                equivalent_ids = sorted(item[0].raw_fact_id for item in equivalent)
                dimensions = _canonical_dimensions(candidate.dimensions)
                locator = {
                    "kind": "sec_generated_statement_html_v2",
                    "row": row_index,
                    "column": column_index,
                    "fact_id": candidate.element_id,
                    "display_value": display_raw,
                    "row_label": row_label,
                    "statement_role": statement_role,
                    "presentation_order": arc[0],
                    "preferred_label_role": arc[1],
                    "scale_multiplier": format(multiplier, "f"),
                    "period_start": candidate.period_start.isoformat() if candidate.period_start else None,
                    "period_end": candidate.period_end.isoformat() if candidate.period_end else None,
                    "dimensions": json.loads(dimensions),
                    "dimensions_sha256": hashlib.sha256(dimensions.encode()).hexdigest(),
                    "decimals": candidate.decimals,
                    "presentation_artifact_id": presentation_artifact_id,
                    "presentation_sha256": presentation_sha256,
                    "label_artifact_id": label_artifact_id,
                    "label_sha256": label_sha256,
                    "canonical_duplicate_rule": "lowest_raw_fact_id_for_exact_identity_v1",
                    "equivalent_raw_fact_ids": equivalent_ids,
                    "onclick": onclick,
                    "onclick_sha256": hashlib.sha256(onclick.encode()).hexdigest(),
                    "onclick_attribute": onclick_attribute,
                    "onclick_attribute_sha256": hashlib.sha256(
                        onclick_attribute.encode()
                    ).hexdigest(),
                    "anchor_start_tag": anchor_start_tag,
                    "anchor_start_tag_sha256": hashlib.sha256(
                        anchor_start_tag.encode()
                    ).hexdigest(),
                }
                raw = " ".join(candidate.raw_value.split())
                items.append(StatementOccurrence(
                    candidate.context_id, concept, len(items) + 1, locator,
                    candidate.element_id, raw, candidate.unit_id, header,
                    _digest(candidate.context_id, concept, candidate.element_id, raw, candidate.unit_id, header),
                ))
                if len(items) > MAX_OCCURRENCES_PER_REPORT:
                    raise StatementAuthorityParseError("statement_occurrence_count_exceeded")
    items = [item for item in items if item.concept not in rejected_concepts]
    for ordinal, item in enumerate(items, start=1):
        items[ordinal - 1] = replace(item, occurrence_ordinal=ordinal)
    if not items and not allow_partial:
        raise StatementAuthorityParseError("no_explicit_statement_occurrences")
    return GeneratedStatementResolution(
        tuple(items), frozenset(rejected_concepts), tuple(rejections)
    )


def generated_occurrence_candidate_ordinals(
    occurrence: StatementOccurrence,
    candidates: Sequence[RawOccurrenceIdentity],
) -> tuple[int, ...]:
    """Validate and return the resolver-owned exact duplicate ordinal set."""
    ordinals = occurrence.locator.get("equivalent_raw_fact_ids")
    if (
        occurrence.locator.get("kind") != "sec_generated_statement_html_v2"
        or not isinstance(ordinals, list)
        or not ordinals
        or len(ordinals) > MAX_OCCURRENCES_PER_REPORT
        or any(
            isinstance(item, bool)
            or not isinstance(item, int)
            or item <= 0
            or item > len(candidates)
            for item in ordinals
        )
        or ordinals != sorted(set(ordinals))
    ):
        raise StatementAuthorityParseError(
            "invalid_generated_duplicate_identity_ordinals"
        )
    selected = [candidates[item - 1] for item in ordinals]
    canonical = selected[0]
    identity = lambda item: (
        item.context_id,
        item.concept,
        " ".join(item.raw_value.split()),
        item.unit_id,
        item.period_start,
        item.period_end,
        _canonical_dimensions(item.dimensions),
        tuple(json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value) for value in item.unit_numerator),
        tuple(json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value) for value in item.unit_denominator),
        item.decimals,
        item.scale,
        item.sign,
        item.is_nil,
        item.is_hidden,
    )
    if (
        any(identity(item) != identity(canonical) for item in selected[1:])
        or canonical.context_id != occurrence.context_id
        or canonical.concept != occurrence.concept
        or " ".join(canonical.raw_value.split()) != " ".join(occurrence.raw_value.split())
        or canonical.unit_id != occurrence.unit_id
        or canonical.element_id != occurrence.fact_id
        or canonical.is_nil
        or canonical.is_hidden
    ):
        raise StatementAuthorityParseError(
            "invalid_generated_duplicate_semantic_identity"
        )
    return tuple(ordinals)

def match_statement_occurrence(occurrence: StatementOccurrence, candidates: Sequence[RawOccurrenceIdentity]) -> int:
    matches = [row for row in candidates if row.context_id == occurrence.context_id and row.concept == occurrence.concept]
    if occurrence.fact_id is not None: matches = [row for row in matches if row.element_id == occurrence.fact_id]
    matches = [row for row in matches if " ".join(row.raw_value.split()) == " ".join(occurrence.raw_value.split()) and row.unit_id == occurrence.unit_id]
    if len(matches) != 1: raise StatementAuthorityParseError("ambiguous_statement_occurrence_identity")
    return matches[0].raw_fact_id

def build_explicit_fiscal_focus(*, dei_facts: Sequence[DeiFocusEvidence],
                                presented_periods: Sequence[PresentedPeriodEvidence],
                                form: str, statement_period_end: date,
                                approved_dei_namespaces: Sequence[str]) -> ExplicitFiscalFocus:
    approved = set(approved_dei_namespaces)
    def exact(local_name: str) -> str:
        values = [row.raw_value.strip() for row in dei_facts if row.namespace_uri in approved
                  and row.local_name == local_name and not row.dimensions]
        if len(set(values)) != 1 or not values: raise StatementAuthorityParseError("missing_exact_dei_fiscal_focus")
        return values[0]
    year_text = exact("DocumentFiscalYearFocus"); period_focus = exact("DocumentFiscalPeriodFocus").upper()
    if not year_text.isdigit() or not (1800 <= int(year_text) <= 9999): raise StatementAuthorityParseError("invalid_dei_fiscal_year_focus")
    fiscal_year = int(year_text)
    annual = form in {"10-K", "10-K/A", "20-F", "20-F/A"}
    if annual:
        if period_focus != "FY": raise StatementAuthorityParseError("dei_fiscal_period_form_mismatch")
        quarter = None; current_phrase = ("year ended", "twelve months ended", "12 months ended"); bounds = (300, 380)
    else:
        if form not in {"10-Q", "10-Q/A"} or re.fullmatch(r"Q[1-3]", period_focus) is None:
            raise StatementAuthorityParseError("dei_fiscal_period_form_mismatch")
        quarter = int(period_focus[1])
        if quarter == 1: current_phrase = ("three months ended", "3 months ended"); bounds = (70, 110)
        elif quarter == 2: current_phrase = ("six months ended", "6 months ended"); bounds = (150, 210)
        else: current_phrase = ("nine months ended", "9 months ended"); bounds = (240, 300)
    def eligible(row: PresentedPeriodEvidence, *, current: bool) -> bool:
        if row.period_start is None or (row.period_end == statement_period_end) is not current: return False
        match = _DATE.search(row.column_header)
        if match is None: return False
        header_date = parse_statement_header_date(row.column_header)
        if header_date != row.period_end: return False
        label = row.column_header.lower(); days = (row.period_end - row.period_start).days + 1
        return any(phrase in label for phrase in current_phrase) and bounds[0] <= days <= bounds[1]
    current_rows = [row for row in presented_periods if eligible(row, current=True)]
    starts = {row.period_start for row in current_rows}
    if len(starts) != 1: raise StatementAuthorityParseError(
        "missing_unproven_current_fiscal_year_start" if not starts else "conflicting_explicit_fiscal_cycle_start")
    current_start = next(iter(starts))
    prior_matches = []
    for current_row in current_rows:
        same_identity = [row for row in presented_periods
            if eligible(row, current=False) and row.reference_key == current_row.reference_key
            and row.row_ordinal == current_row.row_ordinal and row.concept == current_row.concept]
        following = sorted((row for row in same_identity if row.column_ordinal > current_row.column_ordinal),
                           key=lambda row: row.column_ordinal)
        if same_identity and not following:
            raise StatementAuthorityParseError("unproven_prior_fiscal_cycle_anchor")
        if following:
            prior = following[0]
            end_gap = (current_row.period_end - prior.period_end).days
            current_days = (current_row.period_end - current_row.period_start).days + 1
            prior_days = (prior.period_end - prior.period_start).days + 1
            if not 350 <= end_gap <= 380 or abs(current_days - prior_days) > 14:
                raise StatementAuthorityParseError("unproven_prior_fiscal_cycle_anchor")
            prior_matches.append(prior)
    prior_starts = {row.period_start for row in prior_matches}
    if len(prior_starts) > 1: raise StatementAuthorityParseError("conflicting_explicit_prior_fiscal_cycle_start")
    prior_start = next(iter(prior_starts)) if prior_starts else None
    return ExplicitFiscalFocus(statement_period_end, fiscal_year, quarter, current_start, prior_start)

def classify_statement_occurrence(occurrence: StatementOccurrence, *, statement_type: str, period_start: date | None, period_end: date, focus: ExplicitFiscalFocus) -> ClassifiedPresentation:
    header_end = parse_statement_header_date(occurrence.column_header)
    if header_end != period_end: raise StatementAuthorityParseError("statement_context_header_mismatch")
    label = occurrence.column_header.lower(); is_instant = "as of" in label; is_quarter = "three months ended" in label or "3 months ended" in label; is_annual = "year ended" in label or "twelve months ended" in label or "12 months ended" in label
    if period_start is None and not is_instant: raise StatementAuthorityParseError("unproven_statement_period_class")
    if period_start is not None and not (is_quarter or is_annual or "months ended" in label): raise StatementAuthorityParseError("unproven_statement_period_class")
    if period_end == focus.statement_period_end: return ClassifiedPresentation("current_period", period_end, focus.fiscal_year, focus.fiscal_quarter_ordinal, focus.fiscal_year_start)
    if is_quarter and focus.fiscal_quarter_ordinal is not None and focus.prior_fiscal_year_start is not None: return ClassifiedPresentation("prior_same_fiscal_quarter", period_end, focus.fiscal_year - 1, focus.fiscal_quarter_ordinal, focus.prior_fiscal_year_start)
    if is_annual and period_start is not None: return ClassifiedPresentation("prior_fiscal_year_comparative", period_end, focus.fiscal_year - 1, None, period_start)
    if is_instant and statement_type == "balance_sheet" and focus.prior_fiscal_year_start is not None: return ClassifiedPresentation("prior_fiscal_year_balance_sheet", period_end, focus.fiscal_year - 1, None, focus.prior_fiscal_year_start)
    raise StatementAuthorityParseError("unproven_statement_presentation_class")

def authoritative_raw_fact_snapshot(base: RawFactSnapshot, authorities: Sequence[StatementAuthoritySnapshot]) -> RawFactSnapshot:
    matching = [row for row in authorities if row.raw_fact_id == base.raw_fact_id and row.parse_run_id == base.parse_run_id and row.context_id == base.context_id]
    if not matching: raise StatementAuthorityParseError("missing_statement_presentation_authority")
    shapes = {(r.presentation_class, r.statement_period_end, r.fiscal_year, r.fiscal_quarter_ordinal, r.fiscal_year_start) for r in matching}
    if len(shapes) != 1: raise StatementAuthorityParseError("conflicting_statement_presentation_authority")
    selected = min(matching, key=lambda r: (r.report_ordinal, r.occurrence_ordinal)); cycle = _CLASS_TO_CYCLE.get(selected.presentation_class)
    if cycle is None: raise StatementAuthorityParseError("unsupported_statement_presentation_class")
    if selected.presentation_class == "current_period": cycle = "filing_fiscal_year_end" if selected.fiscal_quarter_ordinal is None else "filing_quarter_end"
    selected_provenance = tuple(item for item in base.occurrence_authorities
        if item.get("report_ordinal") == selected.report_ordinal
        and item.get("occurrence_ordinal") == selected.occurrence_ordinal)
    if base.occurrence_authorities and len(selected_provenance) != 1:
        raise StatementAuthorityParseError("conflicting_statement_occurrence_provenance")
    return replace(base, statement_period_end=selected.statement_period_end, fiscal_year=selected.fiscal_year, fiscal_quarter_ordinal=selected.fiscal_quarter_ordinal, fiscal_year_start=selected.fiscal_year_start, fiscal_cycle=cycle, occurrence_authorities=selected_provenance)
