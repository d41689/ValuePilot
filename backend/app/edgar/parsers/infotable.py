"""Parse SEC 13F infotable XML → holdings rows with idempotent fingerprints."""
import hashlib
import re
from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree as ET


@dataclass
class HoldingRow:
    cusip: str
    issuer_name: str
    title_of_class: Optional[str]
    value_thousands: int
    shares: Optional[int]
    share_type: Optional[str]
    put_call: Optional[str]
    investment_discretion: Optional[str]
    voting_sole: Optional[int]
    voting_shared: Optional[int]
    voting_none: Optional[int]
    row_fingerprint: str


# EDGAR namespaces vary across filings; strip them for robust parsing
_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    return _NS_RE.sub("", tag)


def _text(elem: ET.Element, tag: str) -> Optional[str]:
    child = elem.find(".//" + tag)
    if child is None:
        # Try without namespace strip fallback
        for el in elem.iter():
            if _strip_ns(el.tag) == tag:
                return (el.text or "").strip() or None
        return None
    return (child.text or "").strip() or None


def _int(val: Optional[str]) -> Optional[int]:
    if val is None:
        return None
    cleaned = re.sub(r"[^\d]", "", val)
    return int(cleaned) if cleaned else None


def _norm(val: Optional[str]) -> str:
    """Normalize for fingerprint: strip, uppercase, empty → __NULL__."""
    if val is None:
        return "__NULL__"
    v = val.strip().upper()
    return v if v else "__NULL__"


def _fingerprint(row: dict) -> str:
    parts = "|".join([
        _norm(row.get("cusip")),
        _norm(row.get("issuer_name")),
        _norm(row.get("title_of_class")),
        str(row.get("value_thousands", 0)),
        str(row.get("shares") or 0),
        _norm(row.get("share_type")),
        _norm(row.get("put_call")),
        _norm(row.get("investment_discretion")),
        str(row.get("voting_sole") or 0),
        str(row.get("voting_shared") or 0),
        str(row.get("voting_none") or 0),
    ])
    return hashlib.sha256(parts.encode()).hexdigest()


def parse_infotable(content: bytes) -> list[HoldingRow]:
    """Parse infotable XML bytes → list of HoldingRow."""
    # Strip XML declaration encoding issues; EDGAR often uses UTF-8
    root = ET.fromstring(content)

    rows: list[HoldingRow] = []
    for elem in root.iter():
        if _strip_ns(elem.tag) != "infoTable":
            continue

        raw: dict = {}
        for child in elem:
            tag = _strip_ns(child.tag)
            raw[tag] = (child.text or "").strip()

        # votingAuthority is a nested element in some filings
        voting_elem = None
        for child in elem:
            if _strip_ns(child.tag) == "votingAuthority":
                voting_elem = child
                break

        cusip = raw.get("cusip", "").upper()
        issuer_name = raw.get("nameOfIssuer", "") or raw.get("issuerName", "")
        title_of_class = raw.get("titleOfClass") or None
        value_raw = raw.get("value") or raw.get("sshPrnamt")  # fallback
        shares_raw = raw.get("sshPrnamt") or raw.get("shares")
        share_type = raw.get("sshPrnamtType") or raw.get("shareType") or None
        put_call = raw.get("putCall") or None
        inv_discretion = raw.get("investmentDiscretion") or None

        if voting_elem is not None:
            voting_sole = _int(_text(voting_elem, "Sole") or _text(voting_elem, "sole"))
            voting_shared = _int(_text(voting_elem, "Shared") or _text(voting_elem, "shared"))
            voting_none = _int(_text(voting_elem, "None") or _text(voting_elem, "none"))
        else:
            voting_sole = _int(raw.get("votingAuthoritySole"))
            voting_shared = _int(raw.get("votingAuthorityShared"))
            voting_none = _int(raw.get("votingAuthorityNone"))

        value_thousands = _int(value_raw) or 0
        shares = _int(shares_raw)

        row_data = {
            "cusip": cusip,
            "issuer_name": issuer_name,
            "title_of_class": title_of_class,
            "value_thousands": value_thousands,
            "shares": shares,
            "share_type": share_type,
            "put_call": put_call,
            "investment_discretion": inv_discretion,
            "voting_sole": voting_sole,
            "voting_shared": voting_shared,
            "voting_none": voting_none,
        }

        rows.append(
            HoldingRow(
                **row_data,
                row_fingerprint=_fingerprint(row_data),
            )
        )

    return rows


def compute_total_value(rows: list[HoldingRow]) -> int:
    return sum(r.value_thousands for r in rows)
