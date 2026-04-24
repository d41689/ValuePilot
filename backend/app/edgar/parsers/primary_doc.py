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
from typing import Optional

_NS_RE = re.compile(r"\{[^}]+\}")
_SGML_XML_RE = re.compile(r"<XML>(.*?)</XML>", re.DOTALL | re.IGNORECASE)


@dataclass
class PrimaryDocSummary:
    period_of_report: Optional[str]   # MM-DD-YYYY or YYYY-MM-DD (raw from XML)
    table_entry_total: Optional[int]
    table_value_total: Optional[int]  # reported total value in thousands


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

    return PrimaryDocSummary(
        period_of_report=period,
        table_entry_total=int(entry_total_s) if entry_total_s and entry_total_s.isdigit() else None,
        table_value_total=int(value_total_s) if value_total_s and value_total_s.isdigit() else None,
    )
