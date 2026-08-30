"""Deterministic validation for retained SEC submissions sources."""
from __future__ import annotations

import hashlib
import re

from app.edgar.parsers.financial_submissions import (
    parse_financial_submissions,
    parse_historical_financial_submissions,
)


_HISTORICAL_URL_RE = re.compile(
    r"^https://data[.]sec[.]gov/submissions/"
    r"(?P<filename>CIK(?P<cik>[0-9]{10})-submissions-[0-9]+[.]json)$"
)


def validate_submission_source(
    *,
    resource_role: str,
    normalized_url: str,
    snapshot_content: bytes,
    snapshot_sha256: str,
    snapshot_size: int,
    expected_cik: str,
    main_snapshot_content: bytes | None = None,
) -> None:
    """Validate retained bytes, canonical source scope, and reviewed CIK."""
    if (
        hashlib.sha256(snapshot_content).hexdigest() != snapshot_sha256
        or len(snapshot_content) != snapshot_size
    ):
        raise ValueError("source snapshot content identity mismatch")
    if re.fullmatch(r"[0-9]{10}", expected_cik) is None:
        raise ValueError("invalid expected CIK")

    main_url = f"https://data.sec.gov/submissions/CIK{expected_cik}.json"
    if resource_role == "main_submissions":
        if normalized_url != main_url:
            raise ValueError("main submissions validation scope mismatch")
        parsed = parse_financial_submissions(
            snapshot_content, source_url=normalized_url
        )
        if parsed.issuer.cik != expected_cik:
            raise ValueError("main submissions validation CIK mismatch")
        return

    if resource_role != "historical_submissions":
        raise ValueError("invalid source validation role")
    match = _HISTORICAL_URL_RE.fullmatch(normalized_url)
    if match is None or match.group("cik") != expected_cik:
        raise ValueError("historical submissions validation scope mismatch")
    if main_snapshot_content is None:
        raise ValueError("historical validation has no retained main source")
    main = parse_financial_submissions(main_snapshot_content, source_url=main_url)
    if main.issuer.cik != expected_cik:
        raise ValueError("historical validation main CIK mismatch")
    referenced_names = {
        item.name
        for item in main.historical_submission_references
        if item.error_code is None and item.name is not None
    }
    if match.group("filename") not in referenced_names:
        raise ValueError("historical source is not referenced by main")
    parse_historical_financial_submissions(
        snapshot_content, source_url=normalized_url
    )
