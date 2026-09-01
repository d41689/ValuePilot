"""Bounded, non-networking retained SEC statement presentation authority."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
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
_DATE = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
_MONTH = {name.lower(): index for index, name in enumerate(("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}
_CLASS_TO_CYCLE = {"current_period": "filing_quarter_end", "prior_same_fiscal_quarter": "explicit_prior_same_fiscal_quarter_comparative", "prior_fiscal_year_comparative": "explicit_prior_fiscal_year_comparative", "prior_fiscal_year_balance_sheet": "explicit_prior_fiscal_year_end_balance_sheet"}

class StatementAuthorityParseError(ValueError): reason_code = "statement_authority_parse_failed"

@dataclass(frozen=True)
class StatementReportReference:
    report_ordinal: int; report_name: str; filename: str; statement_role: str; statement_type: str
    fallback_filename: str | None = None

@dataclass(frozen=True)
class StatementOccurrence:
    context_id: str; concept: str; occurrence_ordinal: int; locator: dict[str, object]
    fact_id: str | None; raw_value: str; unit_id: str | None; column_header: str; semantic_digest: str

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
        fields = {_local(child.tag): (child.text or "").strip() for child in node}
        filename = fields.get("xmlfilename") or fields.get("htmlfilename") or ""
        fallback = fields.get("htmlfilename") if fields.get("xmlfilename") and fields.get("htmlfilename") else None
        if not filename: continue
        role = fields.get("role", ""); name = fields.get("shortname") or fields.get("longname") or filename; kind = _statement_type(role, name)
        if kind is None: continue
        position = fields.get("position")
        if not position or not position.isdigit() or int(position) <= 0: raise StatementAuthorityParseError("missing_statement_report_position")
        ordinal = int(position)
        reports.append(StatementReportReference(ordinal, name[:255], _safe_filename(filename), role, kind, _safe_filename(fallback) if fallback else None))
        if len(reports) > MAX_STATEMENT_REPORTS: raise StatementAuthorityParseError("statement_report_count_exceeded")
    if not reports: raise StatementAuthorityParseError("no_statement_reports")
    identities = [(row.filename.lower(), row.report_ordinal) for row in reports]
    if len(identities) != len(set(identities)): raise StatementAuthorityParseError("duplicate_statement_report_reference")
    return tuple(sorted(reports, key=lambda row: (row.report_ordinal, row.filename.lower())))

def _digest(context, concept, fact_id, value, unit, header) -> str:
    material = chr(31).join((context, concept, fact_id or "", " ".join(value.split()), unit or ""))
    return hashlib.sha256(material.encode()).hexdigest()

def statement_reference_digest(summary_sha256: str, reference: StatementReportReference) -> str:
    material = chr(31).join((summary_sha256, reference.filename, str(reference.report_ordinal),
                             reference.statement_role, reference.statement_type, reference.report_name))
    return hashlib.sha256(material.encode()).hexdigest()

def parse_statement_header_date(header: str) -> date:
    match = _DATE.search(header)
    if match is None: raise StatementAuthorityParseError("unproven_statement_column_header")
    return date(int(match.group(3)), _MONTH[match.group(1).lower()], int(match.group(2)))

def statement_occurrence_digest(report_sha256: str, report_ordinal: int,
                                occurrence: StatementOccurrence, header_date: date) -> str:
    material = chr(31).join((report_sha256, str(report_ordinal), str(occurrence.locator.get("row", 0)),
        str(occurrence.locator.get("column", 0)), str(occurrence.occurrence_ordinal), occurrence.fact_id or "",
        occurrence.context_id, occurrence.concept, " ".join(occurrence.raw_value.split()), occurrence.unit_id or "",
        occurrence.column_header, " ".join(occurrence.column_header.split()), header_date.isoformat(),
        str(occurrence.locator.get("kind", "")), str(occurrence.locator.get("row", "")),
        str(occurrence.locator.get("column", "")), str(occurrence.locator.get("fact_id") or "")))
    return hashlib.sha256(material.encode()).hexdigest()

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
        quarter = None; current_phrase = ("year ended", "twelve months ended"); bounds = (300, 380)
    else:
        if form not in {"10-Q", "10-Q/A"} or re.fullmatch(r"Q[1-3]", period_focus) is None:
            raise StatementAuthorityParseError("dei_fiscal_period_form_mismatch")
        quarter = int(period_focus[1])
        if quarter == 1: current_phrase = ("three months ended",); bounds = (70, 110)
        elif quarter == 2: current_phrase = ("six months ended",); bounds = (150, 210)
        else: current_phrase = ("nine months ended",); bounds = (240, 300)
    def eligible(row: PresentedPeriodEvidence, *, current: bool) -> bool:
        if row.period_start is None or (row.period_end == statement_period_end) is not current: return False
        match = _DATE.search(row.column_header)
        if match is None: return False
        header_date = date(int(match.group(3)), _MONTH[match.group(1).lower()], int(match.group(2)))
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
    label = occurrence.column_header.lower(); is_instant = "as of" in label; is_quarter = "three months ended" in label; is_annual = "year ended" in label or "twelve months ended" in label
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
