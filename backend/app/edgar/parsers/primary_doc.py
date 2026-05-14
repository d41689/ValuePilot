"""Parse 13F primary-doc.xml to extract summary fields.

The primary doc may be:
  - A standalone XML file (primary_doc.xml / primary-doc.xml)
  - Embedded inside an SGML .txt wrapper (the full EDGAR submission file)

We extract from <summaryPage>:
  - tableEntryTotal  (entry count)
  - tableValueTotal  (total value in thousands)
  - periodOfReport   (from <coverPage>)
"""
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

_NS_RE = re.compile(r"\{[^}]+\}")
_SGML_XML_RE = re.compile(r"<XML>(.*?)</XML>", re.DOTALL | re.IGNORECASE)


@dataclass
class PrimaryDocSummary:
    period_of_report: Optional[str]   # MM-DD-YYYY or YYYY-MM-DD (raw from XML)
    table_entry_total: Optional[int]
    table_value_total: Optional[int]  # reported total value in thousands
    accepted_at: Optional[datetime] = None
    form_type: Optional[str] = None
    report_type: Optional[str] = None
    form_spec_version: Optional[str] = None
    xml_schema_version: Optional[str] = None
    has_confidential_treatment: Optional[bool] = None
    amendment_type: Optional[str] = None
    is_amendment: bool = False
    # NT-specific: list of {name, file_number, cik?} from otherManagersInfo/otherManager
    other_managers_reporting: list = None  # type: ignore[assignment]
    # HR combination: list of {name, file_number, cik?} from otherManagers2Info/otherManager2
    other_managers_included: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.other_managers_reporting is None:
            self.other_managers_reporting = []
        if self.other_managers_included is None:
            self.other_managers_included = []


def _strip_ns(tag: str) -> str:
    return _NS_RE.sub("", tag)


def parse_primary_doc(content: bytes) -> PrimaryDocSummary:
    """Parse primary doc bytes (XML or SGML wrapper containing XML)."""
    text = content.decode("utf-8", errors="replace")

    # If SGML wrapper, extract the first embedded <XML>...</XML> block that
    # looks like the edgarSubmission document (not the infotable).
    xml_blocks = _SGML_XML_RE.findall(text)
    xml_text: Optional[str] = None
    for block in xml_blocks:
        if "edgarSubmission" in block or "summaryPage" in block:
            xml_text = block.strip()
            break

    if xml_text is None:
        # Assume the content itself is XML
        xml_text = text

    # Use regex to extract fields — avoids namespace and encoding edge cases.
    def _extract(tag: str) -> Optional[str]:
        m = re.search(rf"<(?:[^:>]*:)?{re.escape(tag)}\s*>(.*?)</", xml_text, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else None

    period = _extract("periodOfReport") or _extract("reportCalendarOrQuarter")
    entry_total_s = _extract("tableEntryTotal")
    value_total_s = _extract("tableValueTotal")
    report_type = _extract("reportType")
    form_spec_version = _extract("formSpecVersion") or _extract("schemaVersion")
    confidential_raw = _extract("isConfidentialOmitted") or _extract("isConfidentialTreatmentRequested")

    acceptance_match = re.search(r"<ACCEPTANCE-DATETIME>\s*(\d{14})", text, re.IGNORECASE)
    accepted_at = None
    if acceptance_match:
        accepted_at = datetime.strptime(acceptance_match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)

    form_type = _extract("submissionType")
    if not form_type:
        type_match = re.search(r"<TYPE>\s*([^\s<]+)", text, re.IGNORECASE)
        form_type = type_match.group(1).strip() if type_match else None

    amendment_type = _extract("amendmentType")
    is_amendment = bool(amendment_type) or bool(_extract("amendmentInfo"))
    if not is_amendment and form_type and form_type.endswith("/A"):
        is_amendment = True

    xml_schema_version = _extract_schema_evidence(xml_text)
    confidential = None
    if confidential_raw is not None:
        confidential = confidential_raw.strip().lower() in {"true", "1", "yes", "y"}

    return PrimaryDocSummary(
        period_of_report=period,
        table_entry_total=int(entry_total_s) if entry_total_s and entry_total_s.isdigit() else None,
        table_value_total=int(value_total_s) if value_total_s and value_total_s.isdigit() else None,
        accepted_at=accepted_at,
        form_type=form_type,
        report_type=report_type,
        form_spec_version=form_spec_version,
        xml_schema_version=xml_schema_version,
        has_confidential_treatment=confidential,
        amendment_type=amendment_type,
        is_amendment=is_amendment,
        other_managers_reporting=_parse_other_managers_reporting(xml_text),
        other_managers_included=_parse_other_managers_included(xml_text),
    )


def _extract_schema_evidence(xml_text: str) -> Optional[str]:
    root = re.search(r"<(?:[^:>\s]+:)?edgarSubmission\b([^>]*)>", xml_text, re.IGNORECASE | re.DOTALL)
    if not root:
        return None
    attrs = root.group(1)
    namespace = _attr(attrs, "xmlns")
    schema_location = _attr(attrs, "schemaLocation")
    parts = [part for part in (namespace, schema_location) if part]
    return " ".join(parts) if parts else None


def _attr(attrs: str, name: str) -> Optional[str]:
    pattern = re.compile(
        rf'(?:\b|:){re.escape(name)}\s*=\s*["\']([^"\']+)["\']',
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(attrs)
    return match.group(1).strip() if match else None


_OTHER_MANAGER_BLOCK_RE = re.compile(
    r"<(?:[^:>]*:)?otherManager\b[^>]*>(.*?)</(?:[^:>]*:)?otherManager>",
    re.DOTALL | re.IGNORECASE,
)

_OTHER_MANAGER2_BLOCK_RE = re.compile(
    r"<(?:[^:>]*:)?otherManager2\b[^>]*>(.*?)</(?:[^:>]*:)?otherManager2>",
    re.DOTALL | re.IGNORECASE,
)


def _parse_other_managers_reporting(xml_text: str) -> list:
    """Extract otherManagersInfo entries from a 13F-NT cover page.

    Returns a list of dicts with distinct keys: name, file_number, and cik
    (cik omitted when absent in the XML). Preserves order of appearance.
    """
    result = []
    for block in _OTHER_MANAGER_BLOCK_RE.finditer(xml_text):
        inner = block.group(1)

        def _get(tag: str) -> Optional[str]:
            m = re.search(
                rf"<(?:[^:>]*:)?{re.escape(tag)}\s*>(.*?)</",
                inner,
                re.IGNORECASE | re.DOTALL,
            )
            return m.group(1).strip() if m else None

        entry: dict = {}
        name = _get("name")
        file_number = _get("form13FFileNumber")
        cik = _get("cik")
        if name:
            entry["name"] = name
        if file_number:
            entry["file_number"] = file_number
        if cik:
            entry["cik"] = cik
        if entry:
            result.append(entry)
    return result


def _parse_other_managers_included(xml_text: str) -> list:
    """Extract otherManagers2Info entries from a 13F-HR combination report cover page.

    Returns a list of dicts with distinct keys: name, file_number, and cik
    (cik omitted when absent). Used to populate other_managers_included on Filing13F.
    """
    result = []
    for block in _OTHER_MANAGER2_BLOCK_RE.finditer(xml_text):
        inner = block.group(1)

        def _get(tag: str) -> Optional[str]:
            m = re.search(
                rf"<(?:[^:>]*:)?{re.escape(tag)}\s*>(.*?)</",
                inner,
                re.IGNORECASE | re.DOTALL,
            )
            return m.group(1).strip() if m else None

        entry: dict = {}
        name = _get("name")
        file_number = _get("form13FFileNumber")
        cik = _get("cik")
        if name:
            entry["name"] = name
        if file_number:
            entry["file_number"] = file_number
        if cik:
            entry["cik"] = cik
        if entry:
            result.append(entry)
    return result
