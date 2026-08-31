from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Protocol
from urllib.parse import quote
import uuid

from sqlalchemy import Date, and_, cast, exists, func, or_, select, text
from sqlalchemy.orm import Session, aliased

from app.edgar.parsers.financial_submissions import (
    DiscoveredFinancialFiling,
    parse_financial_submissions,
    parse_historical_financial_submissions,
)
from app.edgar.parsers.inline_xbrl import parse_inline_xbrl, parse_standalone_xbrl, safe_xml_preflight
from app.models.sec_financials import (
    SecFilingArtifact,
    SecFinancialAccessionAttempt,
    SecFinancialAccessionAttemptArtifact,
    SecFinancialAcquisitionFailure,
    SecFinancialAcquisitionResolution,
    SecFinancialFiling,
    SecFinancialIngestionOperation,
    SecFinancialHistoryContinuation,
    SecFinancialHistoryConsumptionClaim,
    SecFinancialHistoryContinuationFailure,
    SecFinancialLegacyParseRun,
    SecFinancialLineageAvailability,
    SecFinancialOperationResult,
    SecFinancialOperationSnapshot,
    SecFinancialParseRun,
    SecFinancialParseRunArtifact,
    SecFinancialResourceAnchor,
    SecIssuerIdentity,
    SecRawXbrlFact,
    SecSubmissionSnapshot,
)
from app.rate_guard.client import RateGuardFetchError
from app.services.sec_financial_validation import validate_submission_source


CIK_RE = re.compile(r"^[0-9]{10}$")
ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
SAFE_SEC_ARTIFACT_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
MAX_MANIFEST_ITEMS = 500
MAX_HISTORICAL_SUBMISSION_FILES = 20
MAX_DISCOVERY_IDENTITY_FAILURES = 50
HISTORICAL_SUBMISSION_FILENAME_RE = re.compile(
    r"^CIK(?P<cik>[0-9]{10})-submissions-[0-9]+[.]json$"
)
PARSER_NAME = "valuepilot-inline-xbrl-lineage"
PARSER_V2 = "xbrl-lineage-v2"
ARTIFACT_RETENTION_POLICY_VERSION = "sec-financial-artifacts-v1"
ANNUAL_FORMS_BY_REGIME = {
    "us_10k_10q": frozenset({"10-K", "10-K/A"}),
    "foreign_20f_6k": frozenset({"20-F", "20-F/A"}),
}
FINANCIAL_6K_DESCRIPTION_RE = re.compile(
    r"\b(?:earnings (?:release|report|results)|financial (?:results|statements)|"
    r"(?:annual|interim|quarterly) financial (?:report|results|statements)|"
    r"(?:interim|quarterly) results)\b",
    re.IGNORECASE,
)
NON_FINANCIAL_6K_DESCRIPTION_RE = re.compile(
    r"\b(?:call|conference|announcement|notice)\b",
    re.IGNORECASE,
)


class SecFinancialIngestionError(RuntimeError):
    pass


class SecFinancialIntegrityError(SecFinancialIngestionError):
    pass


class SecFinancialFetchError(SecFinancialIngestionError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class EdgarLikeClient(Protocol):
    def get(self, url: str) -> bytes:
        ...

    def get_revalidated(self, url: str) -> bytes:
        ...


@dataclass(frozen=True)
class FinancialFilingSelection:
    accession_no: str
    form_type: str
    accepted_at: datetime
    report_date: date | None = None


@dataclass(frozen=True)
class FinancialIngestionReport:
    operation_id: str
    stock_id: int
    cik: str
    filings_discovered: int
    filings_created: int
    artifacts_created: int
    parse_runs_created: int
    raw_facts_created: int
    failures: tuple[str, ...]
    selected_filings: tuple[FinancialFilingSelection, ...] = ()
    next_history_cursor: str | None = None


@dataclass(frozen=True)
class FinancialHistoryTarget:
    filing_regime: str
    fiscal_year_end_mmdd: str
    available_start_on: date
    completed_fiscal_year_cap: int
    filing_selection_as_of: datetime


@dataclass(frozen=True)
class SecFinancialEvidenceAsOf:
    filing_id: int
    accession_no: str
    form_type: str
    accepted_at: datetime
    parse_run_id: int
    parser_version: str
    input_manifest_hash: str
    fact_count: int


@dataclass(frozen=True)
class SecFinancialEvidenceFailureAsOf:
    filing_id: int | None
    accession_no: str
    parse_run_id: int | None
    error_code: str


@dataclass(frozen=True)
class _AttemptEligibility:
    eligible: bool
    replayable_at: datetime | None = None


@dataclass(frozen=True)
class _DiscoveryResult:
    filings: tuple[DiscoveredFinancialFiling, ...]
    source_payloads: dict[str, bytes]
    failures: tuple[str, ...]
    audit_failures: tuple["_DiscoveryFailure", ...] = ()
    resolutions: tuple["_DiscoveryResolution", ...] = ()
    next_history_cursor: str | None = None
    continuation_references: tuple[str, ...] = ()
    continuation_next_index: int | None = None
    continuation_start_index: int | None = None
    continuation_end_index: int | None = None
    main_sha256: str | None = None


def _history_manifest_identity(cik: str, main_sha256: str, names: list[str]) -> str:
    material = json.dumps(
        {"cik": cik, "main_sha256": main_sha256, "names": names},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _history_target_payload(target: FinancialHistoryTarget | None) -> dict[str, Any]:
    if target is None:
        return {}
    return {
        "filing_regime": target.filing_regime,
        "fiscal_year_end_mmdd": target.fiscal_year_end_mmdd,
        "available_start_on": target.available_start_on.isoformat(),
        "completed_fiscal_year_cap": target.completed_fiscal_year_cap,
        "filing_selection_as_of": _aware(target.filing_selection_as_of).isoformat(),
    }


@dataclass(frozen=True)
class _ContinuationAuthority:
    id: str
    main_content: bytes
    main_sha256: str
    references: tuple[str, ...]
    next_index: int


@dataclass(frozen=True)
class _DiscoveryFailure:
    snapshot_source_url: str
    stage: str
    error_code: str
    resource_role: str
    resource_key: str
    accession_no: str | None = None


@dataclass(frozen=True)
class _DiscoveryResolution:
    snapshot_source_url: str
    resource_role: str
    resource_key: str


def _selected_filing_summaries(
    filings: tuple[DiscoveredFinancialFiling, ...],
) -> tuple[FinancialFilingSelection, ...]:
    return tuple(
        FinancialFilingSelection(
            accession_no=item.accession_no,
            form_type=item.form_type,
            accepted_at=item.accepted_at,
            report_date=item.report_date,
        )
        for item in filings
    )


def _expected_completed_fiscal_years(
    target: FinancialHistoryTarget,
) -> tuple[int, ...]:
    cutoff = _aware(target.filing_selection_as_of)
    if target.filing_regime not in ANNUAL_FORMS_BY_REGIME:
        raise SecFinancialIngestionError("unsupported financial filing regime")
    if not re.fullmatch(r"[0-9]{4}", target.fiscal_year_end_mmdd):
        raise SecFinancialIngestionError("fiscal_year_end_mmdd must be MMDD")
    if target.fiscal_year_end_mmdd == "0229":
        raise SecFinancialIngestionError(
            "0229 is unsupported for a recurring fiscal year end"
        )
    month = int(target.fiscal_year_end_mmdd[:2])
    day = int(target.fiscal_year_end_mmdd[2:])
    if target.completed_fiscal_year_cap < 1 or target.completed_fiscal_year_cap > 10:
        raise SecFinancialIngestionError(
            "completed_fiscal_year_cap must be between 1 and 10"
        )

    years: list[int] = []
    for year in range(cutoff.year, target.available_start_on.year - 2, -1):
        try:
            fiscal_year_end = date(year, month, day)
        except ValueError as exc:
            raise SecFinancialIngestionError(
                "fiscal_year_end_mmdd must be a real month/day"
            ) from exc
        if fiscal_year_end > cutoff.date():
            continue
        if fiscal_year_end < target.available_start_on:
            break
        years.append(year)
        if len(years) >= target.completed_fiscal_year_cap:
            break
    return tuple(years)


def _annual_fiscal_years(
    filings: list[DiscoveredFinancialFiling],
    target: FinancialHistoryTarget,
) -> set[int]:
    annual_forms = ANNUAL_FORMS_BY_REGIME[target.filing_regime]
    expected = set(_expected_completed_fiscal_years(target))
    return {
        filing.report_date.year
        for filing in filings
        if filing.form_type in annual_forms
        and filing.report_date is not None
        and filing.report_date.year in expected
    }


def _financially_useful_6k(filing: DiscoveredFinancialFiling) -> bool:
    if filing.form_type != "6-K" or filing.primary_doc_description is None:
        return False
    if NON_FINANCIAL_6K_DESCRIPTION_RE.search(filing.primary_doc_description):
        return False
    return FINANCIAL_6K_DESCRIPTION_RE.search(filing.primary_doc_description) is not None


def _filing_semantic_identity(filing: DiscoveredFinancialFiling) -> tuple[Any, ...]:
    return (
        filing.form_type,
        filing.report_date,
        filing.filed_on,
        filing.accepted_at,
        filing.primary_document,
        filing.primary_doc_description,
    )


def _canonicalize_discovered_filings(
    filings: list[DiscoveredFinancialFiling],
) -> tuple[
    list[DiscoveredFinancialFiling],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    by_accession: dict[str, list[DiscoveredFinancialFiling]] = {}
    invalid_accession_tokens: set[str] = set()
    invalid_period_accessions: set[str] = set()
    for filing in filings:
        if not ACCESSION_RE.fullmatch(filing.accession_no):
            invalid_accession_tokens.add(
                hashlib.sha256(
                    filing.accession_no.encode("utf-8", errors="backslashreplace")
                ).hexdigest()[:16]
            )
            continue
        accepted_on = filing.accepted_at.astimezone(timezone.utc).date()
        if (
            filing.report_date is not None
            and (
                filing.report_date > filing.filed_on
                or filing.report_date > accepted_on
            )
        ):
            invalid_period_accessions.add(filing.accession_no)
            continue
        by_accession.setdefault(filing.accession_no, []).append(filing)

    canonical: list[DiscoveredFinancialFiling] = []
    conflicts: list[str] = []
    for accession_no in sorted(by_accession):
        candidates = by_accession[accession_no]
        semantic_identities = {
            _filing_semantic_identity(candidate) for candidate in candidates
        }
        if len(semantic_identities) != 1:
            conflicts.append(accession_no)
            continue
        canonical.append(
            min(
                candidates,
                key=lambda item: (
                    "-submissions-" in item.submissions_source_url,
                    item.submissions_source_url,
                    item.discovery_payload_sha256,
                ),
            )
        )
    return (
        canonical,
        tuple(conflicts),
        tuple(sorted(invalid_accession_tokens)),
        tuple(sorted(invalid_period_accessions)),
    )


def _select_history_filings(
    filings: list[DiscoveredFinancialFiling],
    *,
    target: FinancialHistoryTarget,
    max_filings: int,
) -> tuple[list[DiscoveredFinancialFiling], tuple[int, ...]]:
    expected_years = _expected_completed_fiscal_years(target)
    annual_forms = ANNUAL_FORMS_BY_REGIME[target.filing_regime]
    annual_by_year: dict[int, list[DiscoveredFinancialFiling]] = {
        year: [] for year in expected_years
    }
    for filing in filings:
        if (
            filing.form_type in annual_forms
            and filing.report_date is not None
            and filing.report_date.year in annual_by_year
        ):
            annual_by_year[filing.report_date.year].append(filing)
    for candidates in annual_by_year.values():
        candidates.sort(
            key=lambda item: (item.accepted_at, item.accession_no), reverse=True
        )

    selected: list[DiscoveredFinancialFiling] = []
    selected_accessions: set[str] = set()
    for year in expected_years:
        candidates = annual_by_year[year]
        if candidates and len(selected) < max_filings:
            selected.append(candidates[0])
            selected_accessions.add(candidates[0].accession_no)

    companions = sorted(
        (
            filing
            for candidates in annual_by_year.values()
            for filing in candidates[1:]
        ),
        key=lambda item: (item.accepted_at, item.accession_no),
        reverse=True,
    )
    if target.filing_regime == "us_10k_10q":
        supplemental = [
            filing
            for filing in filings
            if filing.form_type in {"10-Q", "10-Q/A"}
            and (filing.report_date or filing.filed_on) >= target.available_start_on
        ]
    else:
        supplemental = [
            filing
            for filing in filings
            if _financially_useful_6k(filing)
            and (filing.report_date or filing.filed_on) >= target.available_start_on
        ]
    supplemental.sort(
        key=lambda item: (item.accepted_at, item.accession_no), reverse=True
    )

    for filing in [*companions, *supplemental]:
        if len(selected) >= max_filings:
            break
        if filing.accession_no not in selected_accessions:
            selected.append(filing)
            selected_accessions.add(filing.accession_no)

    covered_years = _annual_fiscal_years(selected, target)
    missing_years = tuple(year for year in expected_years if year not in covered_years)
    selected.sort(
        key=lambda item: (item.accepted_at, item.accession_no), reverse=True
    )
    return selected, missing_years


def _fetch_bytes(
    client: EdgarLikeClient,
    url: str,
    *,
    revalidate: bool = False,
) -> bytes:
    try:
        if revalidate:
            return client.get_revalidated(url)
        return client.get(url)
    except RateGuardFetchError as exc:
        if exc.status_code == 403:
            reason = "sec_forbidden"
        elif exc.status_code == 404:
            reason = "sec_not_found"
        elif exc.status_code in {429, 503}:
            reason = "sec_temporarily_unavailable"
        elif exc.status_code is not None:
            reason = "sec_http_error"
        else:
            reason = "rate_guard_unavailable_or_blocked"
        raise SecFinancialFetchError(reason, str(exc)) from exc


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise SecFinancialIngestionError("timestamps must be timezone-aware")
    return value


def _overlaps(
    left_start: date,
    left_end: date | None,
    right_start: date,
    right_end: date | None,
) -> bool:
    return (left_end is None or right_start <= left_end) and (
        right_end is None or left_start <= right_end
    )


def _lock_keys(db: Session, *names: str) -> None:
    """Serialize idempotent identity/acquisition writes on PostgreSQL."""
    for name in sorted(set(names)):
        db.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"
            ),
            {"name": name},
        )


def _assert_identity_transition_not_backdated(
    db: Session,
    *,
    identity_id: int,
    known_at: datetime,
) -> None:
    has_invalidated_lineage = db.scalar(
        select(
            or_(
                exists().where(
                    SecSubmissionSnapshot.issuer_identity_id == identity_id,
                    SecSubmissionSnapshot.known_at >= known_at,
                ),
                exists().where(
                    SecFinancialFiling.issuer_identity_id == identity_id,
                    SecFinancialFiling.known_at >= known_at,
                ),
            )
        )
    )
    if has_invalidated_lineage:
        raise SecFinancialIngestionError(
            "identity transition predates persisted SEC lineage"
        )


def register_reviewed_sec_identity(
    db: Session,
    *,
    stock_id: int,
    cik: str,
    effective_from: date,
    known_at: datetime,
    review_reason: str,
    effective_to: date | None = None,
    reviewer_user_id: int | None = None,
    supersedes_identity_id: int | None = None,
) -> SecIssuerIdentity:
    known_at = _aware(known_at)
    cik = cik.strip()
    if not CIK_RE.fullmatch(cik):
        raise SecFinancialIngestionError("CIK must be zero-padded to 10 digits")
    if not review_reason.strip():
        raise SecFinancialIngestionError("review_reason is required")
    if effective_to is not None and effective_to < effective_from:
        raise SecFinancialIngestionError("effective_to precedes effective_from")

    _lock_keys(db, f"sec-issuer-stock:{stock_id}", f"sec-issuer-cik:{cik}")

    existing = db.scalars(
        select(SecIssuerIdentity)
        .where(
            or_(
                SecIssuerIdentity.stock_id == stock_id,
                SecIssuerIdentity.cik == cik,
            )
        )
        .order_by(SecIssuerIdentity.known_at.desc(), SecIssuerIdentity.id.desc())
    ).all()
    superseded_ids = {
        row.supersedes_identity_id
        for row in existing
        if row.supersedes_identity_id is not None
    }
    terminal = [row for row in existing if row.id not in superseded_ids]
    superseded = next(
        (row for row in existing if row.id == supersedes_identity_id), None
    )
    if supersedes_identity_id is not None:
        if (
            superseded is None
            or superseded.stock_id != stock_id
            or superseded.id not in {row.id for row in terminal}
            or known_at <= superseded.known_at
        ):
            raise SecFinancialIngestionError("invalid or stale identity supersession")
        _assert_identity_transition_not_backdated(
            db,
            identity_id=superseded.id,
            known_at=known_at,
        )

    for row in terminal:
        if (
            row.status == "reviewed"
            and row.stock_id == stock_id
            and row.cik == cik
            and row.effective_from == effective_from
            and row.effective_to == effective_to
            and supersedes_identity_id is None
        ):
            return row
        if (
            row.status in {"reviewed", "retired"}
            and row.id != supersedes_identity_id
            and _overlaps(effective_from, effective_to, row.effective_from, row.effective_to)
        ):
            if row.stock_id == stock_id:
                raise SecFinancialIngestionError(
                    "stock already has an overlapping reviewed SEC identity"
                )
            if row.cik == cik:
                raise SecFinancialIngestionError(
                    "CIK already has an overlapping reviewed stock identity"
                )

    identity = SecIssuerIdentity(
        stock_id=stock_id,
        cik=cik,
        status="reviewed",
        confidence=None,
        review_reason=review_reason.strip(),
        effective_from=effective_from,
        effective_to=effective_to,
        known_at=known_at,
        reviewer_user_id=reviewer_user_id,
        supersedes_identity_id=supersedes_identity_id,
    )
    db.add(identity)
    db.flush()
    return identity


def _identity_decision_at(db: Session, stock_id: int, at: datetime) -> SecIssuerIdentity | None:
    at = _aware(at)
    return db.scalar(
        select(SecIssuerIdentity)
        .where(
            SecIssuerIdentity.stock_id == stock_id,
            SecIssuerIdentity.known_at <= at,
            SecIssuerIdentity.effective_from <= at.date(),
            or_(
                SecIssuerIdentity.effective_to.is_(None),
                SecIssuerIdentity.effective_to >= at.date(),
            ),
        )
        .order_by(SecIssuerIdentity.known_at.desc(), SecIssuerIdentity.id.desc())
        .limit(1)
    )


def _reviewed_identity(db: Session, stock_id: int, at: datetime) -> SecIssuerIdentity:
    row = _identity_decision_at(db, stock_id, at)
    if row is None or row.status != "reviewed":
        raise SecFinancialIngestionError("reviewed SEC issuer identity is required")
    return row


def retire_sec_identity(
    db: Session,
    *,
    identity_id: int,
    known_at: datetime,
    review_reason: str,
    reviewer_user_id: int | None = None,
) -> SecIssuerIdentity:
    known_at = _aware(known_at)
    current = db.get(SecIssuerIdentity, identity_id)
    if current is None or current.status != "reviewed":
        raise SecFinancialIngestionError("reviewed identity to retire was not found")
    _lock_keys(
        db,
        f"sec-issuer-stock:{current.stock_id}",
        f"sec-issuer-cik:{current.cik}",
    )
    current = db.scalar(
        select(SecIssuerIdentity)
        .where(SecIssuerIdentity.id == identity_id)
        .with_for_update()
    )
    if current is None or current.status != "reviewed":
        raise SecFinancialIngestionError("reviewed identity to retire was not found")
    existing_child = db.scalar(
        select(SecIssuerIdentity.id).where(
            SecIssuerIdentity.supersedes_identity_id == identity_id
        )
    )
    if existing_child is not None or known_at <= current.known_at:
        raise SecFinancialIngestionError(
            "identity is already superseded or retirement is stale"
        )
    if not review_reason.strip():
        raise SecFinancialIngestionError("review_reason is required")
    _assert_identity_transition_not_backdated(
        db,
        identity_id=current.id,
        known_at=known_at,
    )
    retired = SecIssuerIdentity(
        stock_id=current.stock_id,
        cik=current.cik,
        status="retired",
        review_reason=review_reason.strip(),
        effective_from=current.effective_from,
        effective_to=current.effective_to,
        known_at=known_at,
        reviewer_user_id=reviewer_user_id,
        supersedes_identity_id=current.id,
    )
    db.add(retired)
    db.flush()
    return retired


def _filing_urls(cik: str, filing: DiscoveredFinancialFiling) -> tuple[str, str]:
    if not ACCESSION_RE.fullmatch(filing.accession_no):
        raise SecFinancialIngestionError("malformed SEC accession number")
    if PurePosixPath(filing.primary_document).name != filing.primary_document:
        raise SecFinancialIngestionError("unsafe SEC primary document name")
    accession_raw = filing.accession_no.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_raw}"
    return f"{base}/index.json", f"{base}/{quote(filing.primary_document, safe='._-')}"


def _manifest_items(content: bytes) -> list[dict[str, Any]]:
    data = json.loads(content)
    raw_items = data.get("directory", {}).get("item", [])
    if not isinstance(raw_items, list):
        raise SecFinancialIngestionError("SEC accession index has no item manifest")
    if len(raw_items) > MAX_MANIFEST_ITEMS:
        raise SecFinancialIngestionError("SEC accession manifest exceeds item limit")
    items: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for sequence, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise SecFinancialIngestionError("SEC accession manifest item is malformed")
        name = str(raw.get("name") or "")
        if name in seen_names:
            raise SecFinancialIngestionError("SEC accession manifest contains duplicate filenames")
        seen_names.add(name)
        item = {
            "sequence": sequence,
            "name": name,
            "type": str(raw.get("type") or "") or None,
            "size": int(raw["size"]) if str(raw.get("size") or "").isdigit() else None,
            "description": str(raw.get("description") or "") or None,
        }
        items.append(item)
    return items


def _retain_item(item: dict[str, Any], primary_document: str) -> bool:
    sec_type = str(item.get("type") or "").upper()
    name = str(item.get("name") or "").lower()
    return (
        item.get("name") == primary_document
        or sec_type.startswith("EX-101")
        or name.endswith(".xsd")
        or name.endswith("_cal.xml")
        or name.endswith("_def.xml")
        or name.endswith("_htm.xml")
        or name.endswith("_lab.xml")
        or name.endswith("_pre.xml")
    )


@dataclass(frozen=True)
class _VerifiedStandaloneInstance:
    artifact: SecFilingArtifact
    raw_content: bytes
    content: bytes
    root_name: tuple[str, str]


def _standalone_instance_artifact(
    artifacts: list[SecFilingArtifact], *, primary_document: str, storage_root: Path
) -> _VerifiedStandaloneInstance | None:
    excluded_suffixes = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml", "_htm.xml")
    candidates = []
    for artifact in artifacts:
        name = artifact.filename.lower()
        if artifact.state != "retained" or artifact.filename == primary_document:
            continue
        if not name.endswith(".xml") or name.endswith(excluded_suffixes) or name.endswith(".xsd"):
            continue
        if str(artifact.sec_type or "").upper() not in {"EX-101.INS", "XML"}:
            continue
        raw_content = _read_verified_artifact(storage_root, artifact)
        try:
            root_name, content = safe_xml_preflight(raw_content)
        except ValueError:
            continue
        if root_name == ("http://www.xbrl.org/2003/instance", "xbrl"):
            candidates.append(_VerifiedStandaloneInstance(artifact, raw_content, content, root_name))
    if len(candidates) > 1:
        raise SecFinancialIngestionError("ambiguous standalone XBRL instance documents")
    return candidates[0] if candidates else None


def _safe_artifact_url(cik: str, accession_no: str, filename: str) -> str:
    if (
        not filename
        or PurePosixPath(filename).name != filename
        or SAFE_SEC_ARTIFACT_FILENAME_RE.fullmatch(filename) is None
        or ".." in filename
    ):
        raise SecFinancialIngestionError("unsafe SEC artifact filename")
    if not ACCESSION_RE.fullmatch(accession_no):
        raise SecFinancialIngestionError("malformed SEC accession number")
    base = (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession_no.replace('-', '')}"
    )
    return f"{base}/{filename}"


def _store_content_immutable(storage_root: Path, content: bytes) -> tuple[str, str]:
    sha256 = hashlib.sha256(content).hexdigest()
    relative = Path("financial") / sha256[:2] / sha256
    target = storage_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise SecFinancialIntegrityError(
                "content-addressed artifact target is not a regular file"
            )
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
            raise SecFinancialIntegrityError(
                "existing content-addressed artifact hash mismatch"
            )
        return relative.as_posix(), sha256

    temporary = target.parent / f".{sha256}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
                raise SecFinancialIntegrityError(
                    "concurrent content-addressed artifact hash mismatch"
                )
    finally:
        temporary.unlink(missing_ok=True)
    return relative.as_posix(), sha256


def _read_verified_artifact(storage_root: Path, artifact: SecFilingArtifact) -> bytes:
    if (
        artifact.state != "retained"
        or not artifact.storage_key
        or not artifact.sha256
        or artifact.byte_size is None
    ):
        raise SecFinancialIntegrityError("retained artifact metadata is incomplete")
    relative = PurePosixPath(artifact.storage_key)
    if relative.is_absolute() or ".." in relative.parts:
        raise SecFinancialIntegrityError("retained artifact storage key is unsafe")
    root = storage_root.resolve()
    target = (root / Path(*relative.parts)).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise SecFinancialIntegrityError("retained artifact file is unavailable")
    content = target.read_bytes()
    if len(content) != artifact.byte_size:
        raise SecFinancialIntegrityError("retained artifact byte size mismatch")
    if artifact.declared_size is not None and artifact.byte_size != artifact.declared_size:
        raise SecFinancialIntegrityError("retained artifact differs from SEC declared size")
    if hashlib.sha256(content).hexdigest() != artifact.sha256:
        raise SecFinancialIntegrityError("retained artifact hash mismatch")
    return content


def _verify_retained_artifact(storage_root: Path, artifact: SecFilingArtifact) -> None:
    _read_verified_artifact(storage_root, artifact)


def _verify_submission_snapshot(
    storage_root: Path,
    snapshot: SecSubmissionSnapshot,
) -> None:
    relative = PurePosixPath(snapshot.storage_key)
    if relative.is_absolute() or ".." in relative.parts:
        raise SecFinancialIntegrityError("submission snapshot storage key is unsafe")
    root = storage_root.resolve()
    target = (root / Path(*relative.parts)).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise SecFinancialIntegrityError("submission snapshot file is unavailable")
    content = target.read_bytes()
    if len(content) != snapshot.byte_size:
        raise SecFinancialIntegrityError("submission snapshot byte size mismatch")
    if hashlib.sha256(content).hexdigest() != snapshot.sha256:
        raise SecFinancialIntegrityError("submission snapshot hash mismatch")


def _read_verified_submission_snapshot(
    storage_root: Path,
    snapshot: SecSubmissionSnapshot,
) -> bytes:
    _verify_submission_snapshot(storage_root, snapshot)
    relative = PurePosixPath(snapshot.storage_key)
    return (storage_root.resolve() / Path(*relative.parts)).read_bytes()


def _persist_submission_snapshots(
    db: Session,
    *,
    issuer_identity_id: int,
    source_payloads: dict[str, bytes],
    storage_root: Path,
    now: datetime,
    operation_id: str,
) -> dict[str, SecSubmissionSnapshot]:
    snapshots: dict[str, SecSubmissionSnapshot] = {}
    for source_url, content in sorted(source_payloads.items()):
        if len(content) > MAX_ARTIFACT_BYTES:
            raise SecFinancialIngestionError(
                "SEC submissions snapshot exceeds byte limit"
            )
        sha256 = hashlib.sha256(content).hexdigest()
        existing = db.scalar(
            select(SecSubmissionSnapshot).where(
                SecSubmissionSnapshot.issuer_identity_id == issuer_identity_id,
                SecSubmissionSnapshot.source_url == source_url,
                SecSubmissionSnapshot.sha256 == sha256,
            )
        )
        if existing is not None:
            _verify_submission_snapshot(storage_root, existing)
            snapshots[source_url] = existing
            db.add(
                SecFinancialOperationSnapshot(
                    operation_id=operation_id,
                    snapshot_id=existing.id,
                )
            )
            continue
        storage_key, stored_sha256 = _store_content_immutable(storage_root, content)
        if stored_sha256 != sha256:
            raise SecFinancialIntegrityError(
                "submission snapshot content-address mismatch"
            )
        snapshot = SecSubmissionSnapshot(
                issuer_identity_id=issuer_identity_id,
                operation_id=operation_id,
                source_url=source_url,
                sha256=sha256,
                byte_size=len(content),
                storage_key=storage_key,
                fetched_at=now,
                known_at=now,
            )
        db.add(snapshot)
        db.flush()
        snapshots[source_url] = snapshot
        db.add(
            SecFinancialOperationSnapshot(
                operation_id=operation_id,
                snapshot_id=snapshot.id,
            )
        )
    db.flush()
    return snapshots


def _reusable_acquisition_failure_operation(
    db: Session,
    *,
    issuer_identity_id: int,
    discovery: _DiscoveryResult,
    storage_root: Path,
) -> str | None:
    """Reuse an exact, already-audited failed discovery without cross-owning rows."""
    if not discovery.audit_failures:
        return None
    snapshots_by_url: dict[str, SecSubmissionSnapshot] = {}
    for source_url, content in sorted(discovery.source_payloads.items()):
        snapshot = db.scalar(
            select(SecSubmissionSnapshot).where(
                SecSubmissionSnapshot.issuer_identity_id == issuer_identity_id,
                SecSubmissionSnapshot.source_url == source_url,
                SecSubmissionSnapshot.sha256
                == hashlib.sha256(content).hexdigest(),
            )
        )
        if snapshot is None:
            return None
        _verify_submission_snapshot(storage_root, snapshot)
        snapshots_by_url[source_url] = snapshot
    candidate_operation_ids: set[str] | None = None
    matching_failure_ids_by_operation: dict[str, set[int]] = {}
    for failure in discovery.audit_failures:
        snapshot = snapshots_by_url.get(failure.snapshot_source_url)
        if snapshot is None:
            return None
        audits = db.scalars(
            select(SecFinancialAcquisitionFailure).where(
                SecFinancialAcquisitionFailure.submission_snapshot_id == snapshot.id,
                SecFinancialAcquisitionFailure.stage == failure.stage,
                SecFinancialAcquisitionFailure.error_code == failure.error_code,
                SecFinancialAcquisitionFailure.resource_role
                == failure.resource_role,
                SecFinancialAcquisitionFailure.resource_key == failure.resource_key,
                SecFinancialAcquisitionFailure.accession_no
                == failure.accession_no,
            )
        ).all()
        matching_operation_ids = {audit.operation_id for audit in audits}
        if not matching_operation_ids:
            return None
        for audit in audits:
            matching_failure_ids_by_operation.setdefault(
                audit.operation_id, set()
            ).add(audit.id)
        candidate_operation_ids = (
            matching_operation_ids
            if candidate_operation_ids is None
            else candidate_operation_ids & matching_operation_ids
        )
        if not candidate_operation_ids:
            return None
    expected_snapshot_ids = {
        snapshot.id for snapshot in snapshots_by_url.values()
    }
    expected_resolutions = {
        (
            resolution.resource_role,
            resolution.resource_key,
            snapshots_by_url[resolution.snapshot_source_url].id,
        )
        for resolution in discovery.resolutions
    }
    for operation_id in sorted(candidate_operation_ids or ()):
        operation = db.get(SecFinancialIngestionOperation, operation_id)
        if operation is None or operation.issuer_identity_id != issuer_identity_id:
            continue
        result = db.get(SecFinancialOperationResult, operation_id)
        if (
            result is None
            or result.result_kind != "acquisition_failure"
            or result.acquisition_failure_id
            not in matching_failure_ids_by_operation.get(operation_id, set())
        ):
            continue
        linked_snapshot_ids = set(
            db.scalars(
                select(SecFinancialOperationSnapshot.snapshot_id).where(
                    SecFinancialOperationSnapshot.operation_id == operation_id
                )
            ).all()
        )
        actual_resolutions = {
            (row.resource_role, row.resource_key, row.submission_snapshot_id)
            for row in db.scalars(
                select(SecFinancialAcquisitionResolution).where(
                    SecFinancialAcquisitionResolution.operation_id == operation_id,
                    SecFinancialAcquisitionResolution.resolution_kind
                    == "resource_validated",
                )
            ).all()
        }
        if (
            expected_snapshot_ids == linked_snapshot_ids
            and expected_resolutions == actual_resolutions
        ):
            return operation_id
    return None


def _reusable_initial_main_failure_operation(
    db: Session,
    *,
    issuer_identity_id: int,
    resource_key: str,
    error_code: str,
) -> str | None:
    rows = db.execute(
        select(
            SecFinancialAcquisitionFailure,
            SecFinancialResourceAnchor,
            SecFinancialOperationResult,
        )
        .join(
            SecFinancialResourceAnchor,
            SecFinancialResourceAnchor.id
            == SecFinancialAcquisitionFailure.resource_anchor_id,
        )
        .join(
            SecFinancialIngestionOperation,
            SecFinancialIngestionOperation.id
            == SecFinancialAcquisitionFailure.operation_id,
        )
        .join(
            SecFinancialOperationResult,
            SecFinancialOperationResult.operation_id
            == SecFinancialAcquisitionFailure.operation_id,
        )
        .where(
            SecFinancialIngestionOperation.issuer_identity_id
            == issuer_identity_id,
            SecFinancialAcquisitionFailure.stage == "submissions_fetch",
            SecFinancialAcquisitionFailure.error_code == error_code,
            SecFinancialAcquisitionFailure.resource_role == "main_submissions",
            SecFinancialAcquisitionFailure.resource_key == resource_key,
            SecFinancialResourceAnchor.operation_id
            == SecFinancialAcquisitionFailure.operation_id,
            SecFinancialResourceAnchor.resource_role == "main_submissions",
            SecFinancialResourceAnchor.resource_key == resource_key,
            SecFinancialOperationResult.result_kind == "acquisition_failure",
            SecFinancialOperationResult.acquisition_failure_id
            == SecFinancialAcquisitionFailure.id,
        )
        .order_by(SecFinancialAcquisitionFailure.id.desc())
    ).all()
    for failure, _anchor, _result in rows:
        failure_availability = db.get(
            SecFinancialLineageAvailability, failure.operation_id
        )
        if failure_availability is None:
            return failure.operation_id
        resolver_operation = aliased(SecFinancialIngestionOperation)
        resolver_availability = aliased(SecFinancialLineageAvailability)
        resolved = db.scalar(
            select(
                exists(
                    select(SecFinancialAcquisitionResolution.id)
                    .join(
                        resolver_operation,
                        resolver_operation.id
                        == SecFinancialAcquisitionResolution.operation_id,
                    )
                    .join(
                        resolver_availability,
                        resolver_availability.operation_id
                        == SecFinancialAcquisitionResolution.operation_id,
                    )
                    .where(
                        resolver_operation.issuer_identity_id
                        == issuer_identity_id,
                        resolver_availability.available_at
                        > failure_availability.available_at,
                        SecFinancialAcquisitionResolution.created_at
                        >= failure.created_at,
                        SecFinancialAcquisitionResolution.resource_role
                        == "main_submissions",
                        SecFinancialAcquisitionResolution.resource_key
                        == resource_key,
                        SecFinancialAcquisitionResolution.resolution_kind
                        == "resource_validated",
                    )
                )
            )
        )
        if not resolved:
            return failure.operation_id
    return None


def _record_initial_main_fetch_failure(
    db: Session,
    *,
    stock_id: int,
    identity: SecIssuerIdentity,
    now: datetime,
    error_code: str,
) -> FinancialIngestionReport:
    resource_key = f"https://data.sec.gov/submissions/CIK{identity.cik}.json"
    existing_operation_id = _reusable_initial_main_failure_operation(
        db,
        issuer_identity_id=identity.id,
        resource_key=resource_key,
        error_code=error_code,
    )
    failure_summary = (
        (error_code,)
        if error_code.startswith("history_cursor")
        or error_code == "invalid_history_cursor"
        else (f"main_submissions:{error_code}",)
    )
    if existing_operation_id is not None:
        return FinancialIngestionReport(
            operation_id=existing_operation_id,
            stock_id=stock_id,
            cik=identity.cik,
            filings_discovered=0,
            filings_created=0,
            artifacts_created=0,
            parse_runs_created=0,
            raw_facts_created=0,
            failures=failure_summary,
        )

    operation_id = str(uuid.uuid4())
    db.add(
        SecFinancialIngestionOperation(
            id=operation_id,
            issuer_identity_id=identity.id,
            attempted_at=now,
        )
    )
    db.flush()
    anchor = SecFinancialResourceAnchor(
        operation_id=operation_id,
        resource_role="main_submissions",
        resource_key=resource_key,
    )
    db.add(anchor)
    db.flush()
    failure = SecFinancialAcquisitionFailure(
        operation_id=operation_id,
        submission_snapshot_id=None,
        resource_anchor_id=anchor.id,
        stage="submissions_fetch",
        error_code=error_code,
        accession_no=None,
        resource_role="main_submissions",
        resource_key=resource_key,
    )
    db.add(failure)
    db.flush()
    db.add(
        SecFinancialOperationResult(
            operation_id=operation_id,
            result_kind="acquisition_failure",
            acquisition_failure_id=failure.id,
        )
    )
    db.flush()
    return FinancialIngestionReport(
        operation_id=operation_id,
        stock_id=stock_id,
        cik=identity.cik,
        filings_discovered=0,
        filings_created=0,
        artifacts_created=0,
        parse_runs_created=0,
        raw_facts_created=0,
        failures=failure_summary,
    )


def _record_history_continuation_failure(
    db: Session,
    *,
    stock_id: int,
    identity: SecIssuerIdentity,
    cursor_id: str,
    reason_code: str,
    now: datetime,
    filing_selection_as_of: datetime | None,
    history_target: FinancialHistoryTarget | None,
    main_snapshot_id: int | None = None,
) -> FinancialIngestionReport:
    operation_id = str(uuid.uuid4())
    db.add(
        SecFinancialIngestionOperation(
            id=operation_id, issuer_identity_id=identity.id, attempted_at=now
        )
    )
    db.flush()
    failure = SecFinancialHistoryContinuationFailure(
        operation_id=operation_id,
        issuer_identity_id=identity.id,
        cursor_id=cursor_id,
        reason_code=reason_code,
        main_snapshot_id=main_snapshot_id,
        request_contract_json={
            "filing_selection_as_of": (
                filing_selection_as_of.isoformat()
                if filing_selection_as_of is not None
                else None
            ),
            "history_target": _history_target_payload(history_target),
        },
    )
    db.add(failure)
    db.flush()
    db.add(
        SecFinancialOperationResult(
            operation_id=operation_id,
            result_kind="history_continuation_failure",
            history_continuation_failure_id=failure.id,
        )
    )
    db.flush()
    return FinancialIngestionReport(
        operation_id=operation_id,
        stock_id=stock_id,
        cik=identity.cik,
        filings_discovered=0,
        filings_created=0,
        artifacts_created=0,
        parse_runs_created=0,
        raw_facts_created=0,
        failures=(reason_code,),
    )


def _existing_artifacts(
    db: Session, filing_id: int, manifest_hash: str
) -> list[SecFilingArtifact]:
    return db.scalars(
        select(SecFilingArtifact)
        .where(
            SecFilingArtifact.filing_id == filing_id,
            SecFilingArtifact.manifest_hash == manifest_hash,
        )
        .order_by(SecFilingArtifact.sequence, SecFilingArtifact.id)
    ).all()


def _legacy_compatible_artifacts(
    db: Session,
    *,
    filing: SecFinancialFiling,
    cik: str,
    index_content: bytes,
    items: list[dict[str, Any]],
    item_observations: dict[str, dict[str, Any]],
    storage_root: Path,
) -> list[SecFilingArtifact]:
    """Reuse complete v1 manifests whose only obsolete input is submissions."""
    if ARTIFACT_RETENTION_POLICY_VERSION != "sec-financial-artifacts-v1":
        return []
    index_sha256 = hashlib.sha256(index_content).hexdigest()
    index_candidates = db.scalars(
        select(SecFilingArtifact)
        .where(
            SecFilingArtifact.filing_id == filing.id,
            SecFilingArtifact.filename == "__accession_index__.json",
            SecFilingArtifact.state == "retained",
            SecFilingArtifact.sha256 == index_sha256,
        )
        .order_by(SecFilingArtifact.id.desc())
    ).all()
    expected_names = {"__submissions__.json", "__accession_index__.json"} | {
        item["name"] for item in items
    }
    for index_artifact in index_candidates:
        group = _existing_artifacts(db, filing.id, index_artifact.manifest_hash)
        by_name: dict[str, SecFilingArtifact] = {}
        for artifact in sorted(group, key=lambda row: row.id, reverse=True):
            by_name.setdefault(artifact.filename, artifact)
        if set(by_name) != expected_names:
            continue
        submissions = by_name["__submissions__.json"]
        index = by_name["__accession_index__.json"]
        expected_manifest_hash = hashlib.sha256(
            json.dumps(
                {
                    "retention_policy_version": ARTIFACT_RETENTION_POLICY_VERSION,
                    "submissions_sha256": submissions.sha256,
                    "index_sha256": index_sha256,
                    "items": items,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if (
            index_artifact.manifest_hash != expected_manifest_hash
            or submissions.sequence != -1
            or submissions.description != "SEC submissions discovery payload"
            or submissions.sec_type != "SEC-DISCOVERY-MANIFEST"
            or submissions.declared_size != submissions.byte_size
            or submissions.source_url not in {None, filing.submissions_source_url}
            or submissions.state != "retained"
            or submissions.content_mime != "application/json"
            or submissions.sha256 != filing.discovery_payload_sha256
            or index.sequence != 0
            or index.description != "SEC accession artifact index"
            or index.sec_type != "SEC-DISCOVERY-MANIFEST"
            or index.declared_size != len(index_content)
            or index.source_url != filing.index_url
            or index.content_mime != "application/json"
            or index.byte_size != len(index_content)
        ):
            continue
        compatible = True
        for item in items:
            artifact = by_name[item["name"]]
            try:
                expected_source_url = _safe_artifact_url(
                    cik,
                    filing.accession_no,
                    item["name"],
                )
            except SecFinancialIngestionError:
                compatible = False
                break
            expected_state = (
                "retained"
                if _retain_item(item, filing.primary_document)
                else "manifest_only"
            )
            if (
                artifact.sequence != item["sequence"]
                or artifact.description != item["description"]
                or artifact.sec_type != item["type"]
                or artifact.declared_size != item["size"]
                or artifact.source_url != expected_source_url
                or artifact.state != expected_state
                or (
                    expected_state == "retained"
                    and (
                        item_observations[item["name"]]["state"] != "retained"
                        or artifact.sha256
                        != item_observations[item["name"]]["sha256"]
                        or artifact.byte_size
                        != item_observations[item["name"]]["byte_size"]
                    )
                )
            ):
                compatible = False
                break
        if not compatible:
            continue
        _verify_retained_artifact(storage_root, submissions)
        filtered = [
            artifact
            for name, artifact in by_name.items()
            if name != "__submissions__.json"
        ]
        for artifact in filtered:
            if artifact.state == "retained":
                _verify_retained_artifact(storage_root, artifact)
        return sorted(filtered, key=lambda row: (row.sequence, row.id))
    return []


def _artifact_input_hash(artifacts: list[SecFilingArtifact]) -> str:
    retained = [
        {"filename": item.filename, "sha256": item.sha256}
        for item in artifacts
        if item.state == "retained"
    ]
    encoded = json.dumps(retained, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _create_artifacts(
    db: Session,
    *,
    client: EdgarLikeClient,
    filing: SecFinancialFiling,
    cik: str,
    index_content: bytes,
    storage_root: Path,
    now: datetime,
) -> tuple[
    list[SecFilingArtifact],
    int,
    list[str],
    bool,
]:
    if len(index_content) > MAX_ARTIFACT_BYTES:
        raise SecFinancialIngestionError("SEC accession manifest exceeds byte limit")
    items = _manifest_items(index_content)
    item_observations: dict[str, dict[str, Any]] = {}
    for item in items:
        filename = item["name"]
        try:
            source_url = _safe_artifact_url(cik, filing.accession_no, filename)
        except SecFinancialIngestionError:
            item_observations[filename] = {
                "state": "rejected",
                "reason_code": "unsafe_filename",
                "source_url": None,
                "content": None,
                "sha256": None,
                "byte_size": None,
                "failure": f"{filing.accession_no}:{filename}:unsafe_filename",
            }
            continue

        if not _retain_item(item, filing.primary_document):
            item_observations[filename] = {
                "state": "manifest_only",
                "reason_code": "artifact_type_not_in_ft03_retention_scope",
                "source_url": source_url,
                "content": None,
                "sha256": None,
                "byte_size": None,
                "failure": None,
            }
            continue
        if item["size"] is not None and item["size"] > MAX_ARTIFACT_BYTES:
            item_observations[filename] = {
                "state": "rejected",
                "reason_code": "artifact_exceeds_byte_limit",
                "source_url": source_url,
                "content": None,
                "sha256": None,
                "byte_size": None,
                "failure": (
                    f"{filing.accession_no}:{filename}:artifact_exceeds_byte_limit"
                ),
            }
            continue
        try:
            content = _fetch_bytes(client, source_url, revalidate=True)
            if len(content) > MAX_ARTIFACT_BYTES:
                raise SecFinancialIngestionError("artifact exceeds byte limit")
            if item["size"] is not None and len(content) != item["size"]:
                item_observations[filename] = {
                    "state": "rejected",
                    "reason_code": "declared_size_mismatch",
                    "source_url": source_url,
                    "content": None,
                    "sha256": None,
                    "byte_size": None,
                    "failure": (
                        f"{filing.accession_no}:{filename}:declared_size_mismatch"
                    ),
                }
                continue
            item_observations[filename] = {
                "state": "retained",
                "reason_code": None,
                "source_url": source_url,
                "content": content,
                "sha256": hashlib.sha256(content).hexdigest(),
                "byte_size": len(content),
                "failure": None,
            }
        except SecFinancialIntegrityError:
            raise
        except SecFinancialFetchError as exc:
            item_observations[filename] = {
                "state": "unavailable",
                "reason_code": exc.reason_code,
                "source_url": source_url,
                "content": None,
                "sha256": None,
                "byte_size": None,
                "failure": f"{filing.accession_no}:{filename}:{exc.reason_code}",
            }
        except SecFinancialIngestionError as exc:
            item_observations[filename] = {
                "state": "rejected",
                "reason_code": "artifact_policy_rejected",
                "source_url": source_url,
                "content": None,
                "sha256": None,
                "byte_size": None,
                "failure": (
                    f"{filing.accession_no}:{filename}:"
                    f"artifact_policy_rejected:{type(exc).__name__}"
                ),
            }
        except Exception as exc:
            item_observations[filename] = {
                "state": "unavailable",
                "reason_code": "fetch_failed",
                "source_url": source_url,
                "content": None,
                "sha256": None,
                "byte_size": None,
                "failure": (
                    f"{filing.accession_no}:{filename}:"
                    f"fetch_failed:{type(exc).__name__}"
                ),
            }

    manifest_material = {
        "retention_policy_version": ARTIFACT_RETENTION_POLICY_VERSION,
        "index_sha256": hashlib.sha256(index_content).hexdigest(),
        "items": items,
        "item_content_observations": [
            {
                "name": item["name"],
                "state": item_observations[item["name"]]["state"],
                "reason_code": item_observations[item["name"]]["reason_code"],
                "sha256": item_observations[item["name"]]["sha256"],
                "byte_size": item_observations[item["name"]]["byte_size"],
            }
            for item in items
        ],
    }
    manifest_hash = hashlib.sha256(
        json.dumps(manifest_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = _existing_artifacts(db, filing.id, manifest_hash)
    if not existing:
        legacy = _legacy_compatible_artifacts(
            db,
            filing=filing,
            cik=cik,
            index_content=index_content,
            items=items,
            item_observations=item_observations,
            storage_root=storage_root,
        )
        if legacy:
            return legacy, 0, [], True
    existing_by_name: dict[str, SecFilingArtifact] = {}
    for artifact in sorted(existing, key=lambda row: row.id, reverse=True):
        existing_by_name.setdefault(artifact.filename, artifact)

    artifacts: list[SecFilingArtifact] = []
    failures: list[str] = []
    created_count = 0
    for sequence, filename, description, source_url, content in ((
        0,
        "__accession_index__.json",
        "SEC accession artifact index",
        filing.index_url,
        index_content,
    ),):
        if existing_artifact := existing_by_name.get(filename):
            if existing_artifact.state == "retained":
                _verify_retained_artifact(storage_root, existing_artifact)
            artifacts.append(existing_artifact)
            continue
        storage_key, sha256 = _store_content_immutable(storage_root, content)
        artifact = SecFilingArtifact(
            filing_id=filing.id,
            sequence=sequence,
            filename=filename,
            description=description,
            sec_type="SEC-DISCOVERY-MANIFEST",
            declared_size=len(content),
            source_url=source_url,
            manifest_hash=manifest_hash,
            state="retained",
            content_mime="application/json",
            sha256=sha256,
            byte_size=len(content),
            storage_key=storage_key,
            fetched_at=now,
            known_at=now,
        )
        db.add(artifact)
        artifacts.append(artifact)
        created_count += 1
    for item in items:
        filename = item["name"]
        observation = item_observations[filename]
        stored_filename = (
            filename[:255]
            if observation["reason_code"] == "unsafe_filename"
            else filename
        )
        existing_artifact = existing_by_name.get(stored_filename)
        if existing_artifact is not None:
            if existing_artifact.state == "retained":
                _verify_retained_artifact(storage_root, existing_artifact)
            artifacts.append(existing_artifact)
            if observation["failure"] is not None:
                failures.append(observation["failure"])
            continue
        if observation["state"] == "retained":
            content = observation["content"]
            if not isinstance(content, bytes):
                raise SecFinancialIntegrityError(
                    "retained artifact observation has no content"
                )
            storage_key, sha256 = _store_content_immutable(storage_root, content)
            if sha256 != observation["sha256"]:
                raise SecFinancialIntegrityError(
                    "retained artifact content identity changed during storage"
                )
            artifact = SecFilingArtifact(
                filing_id=filing.id,
                sequence=item["sequence"],
                filename=stored_filename,
                description=item["description"],
                sec_type=item["type"],
                declared_size=item["size"],
                source_url=observation["source_url"],
                manifest_hash=manifest_hash,
                state="retained",
                reason_code=None,
                content_mime=mimetypes.guess_type(filename)[0] or "application/octet-stream",
                sha256=sha256,
                byte_size=len(content),
                storage_key=storage_key,
                fetched_at=now,
                known_at=now,
            )
        else:
            artifact = SecFilingArtifact(
                filing_id=filing.id,
                sequence=item["sequence"],
                filename=stored_filename,
                description=item["description"],
                sec_type=item["type"],
                declared_size=item["size"],
                source_url=observation["source_url"],
                manifest_hash=manifest_hash,
                state=observation["state"],
                reason_code=observation["reason_code"],
                known_at=now,
            )
        if observation["failure"] is not None:
            failures.append(observation["failure"])
        db.add(artifact)
        artifacts.append(artifact)
        created_count += 1
    db.flush()
    return (
        sorted(artifacts, key=lambda row: (row.sequence, row.id)),
        created_count,
        failures,
        False,
    )


def _parse_primary_artifact(
    db: Session,
    *,
    filing: SecFinancialFiling,
    artifacts: list[SecFilingArtifact],
    storage_root: Path,
    parser_version: str,
    now: datetime,
    allow_legacy_run_reuse: bool,
    operation_id: str,
) -> tuple[int, int, list[str], int]:
    input_hash = _artifact_input_hash(artifacts)
    existing = db.scalar(
        select(SecFinancialParseRun).where(
            SecFinancialParseRun.filing_id == filing.id,
            SecFinancialParseRun.parser_version == parser_version,
            SecFinancialParseRun.input_manifest_hash == input_hash,
        )
    )
    if existing is None and allow_legacy_run_reuse:
        retained_artifact_ids = {
            artifact.id for artifact in artifacts if artifact.state == "retained"
        }
        candidate_runs = db.scalars(
            select(SecFinancialParseRun)
            .where(
                SecFinancialParseRun.filing_id == filing.id,
                SecFinancialParseRun.parser_version == parser_version,
            )
            .order_by(SecFinancialParseRun.known_at.desc(), SecFinancialParseRun.id.desc())
        ).all()
        for candidate in candidate_runs:
            linked = db.scalars(
                select(SecFilingArtifact)
                .join(
                    SecFinancialParseRunArtifact,
                    SecFinancialParseRunArtifact.artifact_id == SecFilingArtifact.id,
                )
                .where(SecFinancialParseRunArtifact.parse_run_id == candidate.id)
            ).all()
            legacy_submission_inputs = [
                artifact
                for artifact in linked
                if artifact.filename == "__submissions__.json"
            ]
            linked_filing_input_ids = {
                artifact.id
                for artifact in linked
                if artifact.filename != "__submissions__.json"
            }
            if (
                len(legacy_submission_inputs) == 1
                and legacy_submission_inputs[0].state == "retained"
                and linked_filing_input_ids == retained_artifact_ids
            ):
                existing = candidate
                break
    if existing is not None:
        if existing.status == "failed":
            return (
                0,
                0,
                [f"{filing.accession_no}:{existing.error_code or 'parse_failed'}"],
                existing.id,
            )
        return 0, 0, [], existing.id

    primary = next(
        (
            item
            for item in artifacts
            if item.filename == filing.primary_document and item.state == "retained"
        ),
        None,
    )
    parse_artifact = primary
    standalone_authority: _VerifiedStandaloneInstance | None = None
    if parser_version == PARSER_V2:
        if primary is None:
            standalone_authority = _standalone_instance_artifact(
                artifacts, primary_document=filing.primary_document, storage_root=storage_root
            )
            parse_artifact = standalone_authority.artifact if standalone_authority else None
    started_at = now
    retained_inputs = [item for item in artifacts if item.state == "retained"]
    incomplete_required = [
        item for item in artifacts if item.state in {"unavailable", "rejected"}
    ]
    if incomplete_required:
        run = SecFinancialParseRun(
            filing_id=filing.id,
            operation_id=operation_id,
            parser_name=PARSER_NAME,
            parser_version=parser_version,
            input_manifest_hash=input_hash,
            status="failed",
            started_at=started_at,
            completed_at=now,
            known_at=now,
            fact_count=0,
            error_code="required_artifact_unavailable",
            error_detail=(
                "Required or manifest-integrity artifact unavailable: "
                + ", ".join(item.filename for item in incomplete_required[:20])
            ),
        )
        db.add(run)
        db.flush()
        for artifact in retained_inputs:
            db.add(
                SecFinancialParseRunArtifact(
                    parse_run_id=run.id,
                    artifact_id=artifact.id,
                    known_at=now,
                )
            )
        return 1, 0, [f"{filing.accession_no}:required_artifact_unavailable"], run.id
    if parse_artifact is None or not parse_artifact.storage_key:
        run = SecFinancialParseRun(
            filing_id=filing.id,
            operation_id=operation_id,
            parser_name=PARSER_NAME,
            parser_version=parser_version,
            input_manifest_hash=input_hash,
            status="failed",
            started_at=started_at,
            completed_at=now,
            known_at=now,
            fact_count=0,
            error_code="primary_artifact_unavailable",
            error_detail="The SEC primary document was not retained.",
        )
        db.add(run)
        db.flush()
        for artifact in retained_inputs:
            db.add(
                SecFinancialParseRunArtifact(
                    parse_run_id=run.id,
                    artifact_id=artifact.id,
                    known_at=now,
                )
            )
        return 1, 0, [f"{filing.accession_no}:primary_artifact_unavailable"], run.id

    try:
        if standalone_authority is not None and standalone_authority.artifact.id == parse_artifact.id:
            content = standalone_authority.content
            raw_content = standalone_authority.raw_content
            root_name = standalone_authority.root_name
        else:
            raw_content = _read_verified_artifact(storage_root, parse_artifact)
            try:
                root_name, content = safe_xml_preflight(raw_content)
            except ValueError:
                if parser_version == PARSER_V2:
                    raise
                content = raw_content
                root_name = None
        if root_name == ("http://www.xbrl.org/2003/instance", "xbrl"):
            parsed = parse_standalone_xbrl(content, artifact_id=parse_artifact.id)
        else:
            parsed = parse_inline_xbrl(
                content,
                artifact_id=parse_artifact.id,
                strict=parser_version == PARSER_V2,
            )
        if not parsed and parser_version == PARSER_V2:
            standalone = _standalone_instance_artifact(
                artifacts, primary_document=filing.primary_document, storage_root=storage_root
            )
            if standalone is not None:
                parse_artifact = standalone.artifact
                content = standalone.content
                raw_content = standalone.raw_content
                parsed = parse_standalone_xbrl(content, artifact_id=parse_artifact.id)
        if _read_verified_artifact(storage_root, parse_artifact) != raw_content:
            raise SecFinancialIntegrityError("retained parse authority changed after verification")
        if not parsed:
            run = SecFinancialParseRun(
                filing_id=filing.id,
                operation_id=operation_id,
                parser_name=PARSER_NAME,
                parser_version=parser_version,
                input_manifest_hash=input_hash,
                status="failed",
                started_at=started_at,
                completed_at=now,
                known_at=now,
                fact_count=0,
                error_code=(
                    "no_xbrl_facts"
                    if parser_version == PARSER_V2
                    else "no_inline_xbrl_facts"
                ),
                error_detail=(
                    "The retained parse authority contained no XBRL facts."
                    if parser_version == PARSER_V2
                    else "The retained primary document contained no inline-XBRL facts."
                ),
            )
            db.add(run)
            db.flush()
            for artifact in retained_inputs:
                db.add(
                    SecFinancialParseRunArtifact(
                        parse_run_id=run.id,
                        artifact_id=artifact.id,
                        known_at=now,
                    )
                )
            no_facts_code = (
                "no_xbrl_facts"
                if parser_version == PARSER_V2
                else "no_inline_xbrl_facts"
            )
            return 1, 0, [f"{filing.accession_no}:{no_facts_code}"], run.id
        run = SecFinancialParseRun(
            filing_id=filing.id,
            operation_id=operation_id,
            parser_name=PARSER_NAME,
            parser_version=parser_version,
            input_manifest_hash=input_hash,
            status="succeeded",
            started_at=started_at,
            completed_at=now,
            known_at=now,
            fact_count=len(parsed),
            error_code=None,
            error_detail=None,
        )
        db.add(run)
        db.flush()
        for artifact in retained_inputs:
            db.add(
                SecFinancialParseRunArtifact(
                    parse_run_id=run.id,
                    artifact_id=artifact.id,
                    known_at=now,
                )
            )
        db.flush()
        for ordinal, item in enumerate(parsed, start=1):
            db.add(
                SecRawXbrlFact(
                    parse_run_id=run.id,
                    artifact_id=parse_artifact.id,
                    ordinal=ordinal,
                    concept=item.concept,
                    concept_namespace_uri=item.concept_namespace_uri,
                    context_id=item.context_id,
                    unit_id=item.unit_id,
                    unit_measure=item.unit_measure,
                    unit_numerator_json=(
                        list(item.unit_numerator)
                        if parser_version == PARSER_V2
                        else None
                    ),
                    unit_denominator_json=(
                        list(item.unit_denominator)
                        if parser_version == PARSER_V2
                        else None
                    ),
                    raw_value=item.raw_value,
                    transformation_format=item.transformation_format,
                    language=item.language,
                    continued_at=item.continued_at,
                    decimals=item.decimals,
                    scale=item.scale,
                    sign=item.sign,
                    is_nil=item.is_nil,
                    period_instant=item.period_instant,
                    period_start=item.period_start,
                    period_end=item.period_end,
                    entity_identifier=item.entity_identifier,
                    dimensions_json=item.dimensions,
                    dimensions_structured_json=(
                        list(item.dimensions_structured)
                        if parser_version == PARSER_V2
                        else None
                    ),
                    locator_json=item.locator,
                )
            )
        db.flush()
        return 1, len(parsed), [], run.id
    except SecFinancialIntegrityError:
        raise
    except Exception as exc:
        run = SecFinancialParseRun(
            filing_id=filing.id,
            operation_id=operation_id,
            parser_name=PARSER_NAME,
            parser_version=parser_version,
            input_manifest_hash=input_hash,
            status="failed",
            started_at=started_at,
            completed_at=now,
            known_at=now,
            fact_count=0,
            error_code="parse_failed",
            error_detail=f"{type(exc).__name__}: {str(exc)[:500]}",
        )
        db.add(run)
        db.flush()
        for artifact in retained_inputs:
            db.add(
                SecFinancialParseRunArtifact(
                    parse_run_id=run.id,
                    artifact_id=artifact.id,
                    known_at=now,
                )
            )
        return (
            1,
            0,
            [f"{filing.accession_no}:parse_failed:{type(exc).__name__}"],
            run.id,
        )


def _discover(
    client: EdgarLikeClient,
    cik: str,
    *,
    max_filings: int,
    filing_selection_as_of: datetime | None,
    history_target: FinancialHistoryTarget | None = None,
    continuation: _ContinuationAuthority | None = None,
) -> _DiscoveryResult:
    if filing_selection_as_of is not None:
        filing_selection_as_of = _aware(filing_selection_as_of)
    if history_target is not None:
        target_cutoff = _aware(history_target.filing_selection_as_of)
        if (
            filing_selection_as_of is not None
            and filing_selection_as_of != target_cutoff
        ):
            raise SecFinancialIngestionError(
                "history target cutoff must match filing_selection_as_of"
            )
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    main_content = (
        continuation.main_content
        if continuation is not None
        else _fetch_bytes(client, submissions_url)
    )
    source_payloads = {submissions_url: main_content}
    try:
        main = parse_financial_submissions(main_content, source_url=submissions_url)
    except Exception:
        return _DiscoveryResult(
            filings=(),
            source_payloads=source_payloads,
            failures=("invalid_main_submissions_payload",),
            audit_failures=(
                _DiscoveryFailure(
                    snapshot_source_url=submissions_url,
                    stage="submissions_parse",
                    error_code="invalid_main_submissions_payload",
                    resource_role="main_submissions",
                    resource_key=submissions_url,
                ),
            ),
        )
    if main.issuer.cik != cik:
        return _DiscoveryResult(
            filings=(),
            source_payloads=source_payloads,
            failures=("main_submissions_cik_mismatch",),
            audit_failures=(
                _DiscoveryFailure(
                    snapshot_source_url=submissions_url,
                    stage="submissions_identity",
                    error_code="main_submissions_cik_mismatch",
                    resource_role="main_submissions",
                    resource_key=submissions_url,
                ),
            ),
        )
    discovered = list(main.filings)
    failures: list[str] = []
    audit_failures: list[_DiscoveryFailure] = []
    resolutions: list[_DiscoveryResolution] = [
        _DiscoveryResolution(
            snapshot_source_url=submissions_url,
            resource_role="main_submissions",
            resource_key=submissions_url,
        )
    ]
    selection_cutoff = filing_selection_as_of or (
        history_target.filing_selection_as_of if history_target else None
    )

    def canonical_eligible() -> list[DiscoveredFinancialFiling]:
        canonical, _, _, _ = _canonicalize_discovered_filings(discovered)
        return [
            item
            for item in canonical
            if selection_cutoff is None or item.accepted_at <= selection_cutoff
        ]

    def eligible_count() -> int:
        return len(canonical_eligible())

    def annual_coverage_complete() -> bool:
        if history_target is None:
            return eligible_count() >= max_filings
        eligible = canonical_eligible()
        return set(_expected_completed_fiscal_years(history_target)) <= _annual_fiscal_years(
            eligible, history_target
        )

    safe_historical_files: list[str] = []
    next_index: int | None = None
    if not annual_coverage_complete() or continuation is not None:
        unsafe_historical_files: list[str] = []
        for reference in main.historical_submission_references:
            if reference.error_code is not None or reference.name is None:
                unsafe_historical_files.append(
                    f"index={reference.index}:"
                    f"{reference.error_code or 'invalid_reference'}"
                )
                continue
            filename = reference.name
            match = HISTORICAL_SUBMISSION_FILENAME_RE.fullmatch(filename)
            if (
                PurePosixPath(filename).name == filename
                and match is not None
                and match.group("cik") == cik
            ):
                safe_historical_files.append(filename)
            else:
                unsafe_historical_files.append(filename)
        failures.extend(
            "unsafe_historical_submission_reference:" + filename[:160]
            for filename in unsafe_historical_files[:MAX_HISTORICAL_SUBMISSION_FILES]
        )
        if len(unsafe_historical_files) > MAX_HISTORICAL_SUBMISSION_FILES:
            failures.append(
                "unsafe_historical_submission_reference_additional:"
                f"{len(unsafe_historical_files) - MAX_HISTORICAL_SUBMISSION_FILES}"
            )
        cursor_start = 0
        if continuation is not None:
            if (
                continuation.main_sha256
                != hashlib.sha256(main_content).hexdigest()
                or continuation.references != tuple(safe_historical_files)
                or continuation.next_index > len(safe_historical_files)
            ):
                raise SecFinancialIntegrityError("history continuation authority mismatch")
            cursor_start = continuation.next_index
        scanned = 0
        for filename in safe_historical_files[
            cursor_start : cursor_start + MAX_HISTORICAL_SUBMISSION_FILES
        ]:
            scanned += 1
            url = f"https://data.sec.gov/submissions/{quote(filename, safe='._-')}"
            try:
                content = _fetch_bytes(client, url)
            except SecFinancialFetchError as exc:
                error_code = f"historical_submissions_{exc.reason_code}"
                failures.append(error_code)
                audit_failures.append(
                    _DiscoveryFailure(
                        snapshot_source_url=submissions_url,
                        stage="historical_submissions_fetch",
                        error_code=error_code,
                        resource_role="historical_submissions",
                        resource_key=url,
                    )
                )
                continue
            except Exception:
                error_code = "historical_submissions_fetch_failed"
                failures.append(error_code)
                audit_failures.append(
                    _DiscoveryFailure(
                        snapshot_source_url=submissions_url,
                        stage="historical_submissions_fetch",
                        error_code=error_code,
                        resource_role="historical_submissions",
                        resource_key=url,
                    )
                )
                continue
            source_payloads[url] = content
            try:
                historical = parse_historical_financial_submissions(
                    content, source_url=url
                )
            except Exception:
                failures.append("invalid_historical_submissions_payload")
                audit_failures.append(
                    _DiscoveryFailure(
                        snapshot_source_url=url,
                        stage="historical_submissions_parse",
                        error_code="invalid_historical_submissions_payload",
                        resource_role="historical_submissions",
                        resource_key=url,
                    )
                )
                continue
            resolutions.append(
                _DiscoveryResolution(
                    snapshot_source_url=url,
                    resource_role="historical_submissions",
                    resource_key=url,
                )
            )
            discovered.extend(historical)
            if annual_coverage_complete():
                break
        next_index = cursor_start + scanned
        next_history_cursor = None
        if not annual_coverage_complete() and next_index < len(safe_historical_files):
            failures.append("history_scan_limit_exceeded")
            next_history_cursor = "pending"
    else:
        next_history_cursor = None
    (
        canonical,
        conflicting_accessions,
        invalid_accession_tokens,
        invalid_period_accessions,
    ) = _canonicalize_discovered_filings(discovered)
    failures.extend(
        "invalid_filing_accession:sha256=" + token
        for token in invalid_accession_tokens[:MAX_DISCOVERY_IDENTITY_FAILURES]
    )
    if len(invalid_accession_tokens) > MAX_DISCOVERY_IDENTITY_FAILURES:
        failures.append(
            "invalid_filing_accession_additional:"
            f"{len(invalid_accession_tokens) - MAX_DISCOVERY_IDENTITY_FAILURES}"
        )
    failures.extend(
        "invalid_filing_period_metadata:" + accession_no
        for accession_no in invalid_period_accessions[:MAX_DISCOVERY_IDENTITY_FAILURES]
    )
    if len(invalid_period_accessions) > MAX_DISCOVERY_IDENTITY_FAILURES:
        failures.append(
            "invalid_filing_period_metadata_additional:"
            f"{len(invalid_period_accessions) - MAX_DISCOVERY_IDENTITY_FAILURES}"
        )
    failures.extend(
        "conflicting_filing_metadata:" + accession_no
        for accession_no in conflicting_accessions[:MAX_DISCOVERY_IDENTITY_FAILURES]
    )
    if len(conflicting_accessions) > MAX_DISCOVERY_IDENTITY_FAILURES:
        failures.append(
            "conflicting_filing_metadata_additional:"
            f"{len(conflicting_accessions) - MAX_DISCOVERY_IDENTITY_FAILURES}"
        )
    eligible = [
        item
        for item in canonical
        if selection_cutoff is None or item.accepted_at <= selection_cutoff
    ]
    if history_target is None:
        selected = sorted(
            eligible, key=lambda item: (item.accepted_at, item.accession_no), reverse=True
        )[:max_filings]
    else:
        selected, missing_years = _select_history_filings(
            eligible,
            target=history_target,
            max_filings=max_filings,
        )
        if missing_years:
            failures.append(
                "annual_coverage_gap:" + ",".join(str(year) for year in missing_years)
            )
    return _DiscoveryResult(
        filings=tuple(selected),
        source_payloads=source_payloads,
        failures=tuple(failures),
        audit_failures=tuple(audit_failures),
        resolutions=tuple(resolutions),
        next_history_cursor=next_history_cursor,
        continuation_references=tuple(safe_historical_files),
        continuation_next_index=(next_index if next_history_cursor else None),
        continuation_start_index=(cursor_start if next_index is not None else None),
        continuation_end_index=next_index,
        main_sha256=hashlib.sha256(main_content).hexdigest(),
    )


def ingest_latest_financial_filings(
    db: Session,
    *,
    stock_id: int,
    client: EdgarLikeClient,
    storage_root: Path,
    max_filings: int,
    now: datetime | None = None,
    parser_version: str = "inline-xbrl-v1",
    filing_selection_as_of: datetime | None = None,
    history_target: FinancialHistoryTarget | None = None,
    history_cursor: str | None = None,
) -> FinancialIngestionReport:
    now = _aware(now or datetime.now(timezone.utc))
    filing_selection_as_of = (
        _aware(filing_selection_as_of)
        if filing_selection_as_of is not None
        else None
    )
    if max_filings < 1 or max_filings > 200:
        raise SecFinancialIngestionError("max_filings must be between 1 and 200")
    if not parser_version.strip():
        raise SecFinancialIngestionError("parser_version is required")
    candidate_identity = _reviewed_identity(db, stock_id, now)
    _lock_keys(
        db,
        f"sec-issuer-stock:{stock_id}",
        f"sec-issuer-cik:{candidate_identity.cik}",
    )
    identity = _reviewed_identity(db, stock_id, now)
    if identity.id != candidate_identity.id:
        raise SecFinancialIngestionError(
            "reviewed SEC issuer identity changed during acquisition"
        )
    continuation_authority: _ContinuationAuthority | None = None
    continuation_row: SecFinancialHistoryContinuation | None = None
    def continuation_failure(
        reason_code: str, *, snapshot_id: int | None = None
    ) -> FinancialIngestionReport:
        return _record_history_continuation_failure(
            db,
            stock_id=stock_id,
            identity=identity,
            cursor_id=history_cursor or "invalid",
            reason_code=reason_code,
            now=now,
            filing_selection_as_of=filing_selection_as_of,
            history_target=history_target,
            main_snapshot_id=snapshot_id,
        )
    if history_cursor is not None:
        try:
            uuid.UUID(history_cursor)
        except ValueError:
            return continuation_failure("invalid_history_cursor")
        continuation_row = db.get(SecFinancialHistoryContinuation, history_cursor)
        continuation_available = (
            continuation_row is not None
            and db.get(
                SecFinancialLineageAvailability,
                continuation_row.source_operation_id,
            )
            is not None
        )
        if (
            continuation_row is None
            or not continuation_available
            or continuation_row.issuer_identity_id != identity.id
            or continuation_row.filing_selection_as_of != filing_selection_as_of
            or continuation_row.history_target_json != _history_target_payload(history_target)
        ):
            return continuation_failure(
                    "history_cursor_not_available"
                    if continuation_row is not None and not continuation_available
                    else "history_cursor_mismatch"
            )
        snapshot = db.get(SecSubmissionSnapshot, continuation_row.main_snapshot_id)
        if (
            snapshot is None
            or snapshot.issuer_identity_id != identity.id
            or snapshot.sha256 != continuation_row.main_sha256
        ):
            return continuation_failure(
                "history_cursor_integrity_failure",
                snapshot_id=(snapshot.id if snapshot is not None else None),
            )
        try:
            main_content = _read_verified_submission_snapshot(storage_root, snapshot)
        except SecFinancialIntegrityError:
            return continuation_failure(
                "history_cursor_integrity_failure", snapshot_id=snapshot.id
            )
        references = tuple(continuation_row.validated_references_json)
        if continuation_row.manifest_identity != _history_manifest_identity(
            identity.cik, continuation_row.main_sha256, list(references)
        ):
            return continuation_failure(
                "history_cursor_integrity_failure", snapshot_id=snapshot.id
            )
        continuation_authority = _ContinuationAuthority(
            id=continuation_row.id,
            main_content=main_content,
            main_sha256=continuation_row.main_sha256,
            references=references,
            next_index=continuation_row.next_index,
        )
    try:
        discovery = _discover(
            client,
            identity.cik,
            max_filings=max_filings,
            filing_selection_as_of=filing_selection_as_of,
            history_target=history_target,
            continuation=continuation_authority,
        )
    except SecFinancialFetchError as exc:
        return _record_initial_main_fetch_failure(
            db,
            stock_id=stock_id,
            identity=identity,
            now=now,
            error_code=exc.reason_code,
        )
    for item in discovery.filings:
        existing_filing_identity_id = db.scalar(
            select(SecFinancialFiling.issuer_identity_id).where(
                SecFinancialFiling.accession_no == item.accession_no
            )
        )
        if (
            existing_filing_identity_id is not None
            and existing_filing_identity_id != identity.id
        ):
            raise SecFinancialIngestionError(
                "accession already belongs to a different reviewed issuer identity"
            )
    reusable_failed_operation_id = (
        None
        if discovery.continuation_next_index is not None
        else _reusable_acquisition_failure_operation(
            db,
            issuer_identity_id=identity.id,
            discovery=discovery,
            storage_root=storage_root,
        )
    )
    if reusable_failed_operation_id is not None:
        return FinancialIngestionReport(
            operation_id=reusable_failed_operation_id,
            stock_id=stock_id,
            cik=identity.cik,
            filings_discovered=len(discovery.filings),
            filings_created=0,
            artifacts_created=0,
            parse_runs_created=0,
            raw_facts_created=0,
            failures=discovery.failures,
            selected_filings=_selected_filing_summaries(discovery.filings),
            next_history_cursor=discovery.next_history_cursor,
        )
    operation_id = str(uuid.uuid4())
    db.add(
        SecFinancialIngestionOperation(
            id=operation_id,
            issuer_identity_id=identity.id,
            attempted_at=now,
        )
    )
    db.flush()
    snapshots = _persist_submission_snapshots(
        db,
        issuer_identity_id=identity.id,
        source_payloads=discovery.source_payloads,
        storage_root=storage_root,
        now=now,
        operation_id=operation_id,
    )
    continuation_token: str | None = None
    continuation_claim_payload: dict[str, Any] | None = None
    if (
        discovery.continuation_end_index is not None
        and discovery.continuation_end_index
        > (discovery.continuation_start_index or 0)
    ):
        main_url = f"https://data.sec.gov/submissions/CIK{identity.cik}.json"
        main_snapshot = snapshots.get(main_url)
        if main_snapshot is None or main_snapshot.sha256 != discovery.main_sha256:
            raise SecFinancialIntegrityError(
                "history continuation requires exact retained main snapshot"
            )
        manifest_identity = _history_manifest_identity(
            identity.cik,
            main_snapshot.sha256,
            list(discovery.continuation_references),
        )
        start_index = discovery.continuation_start_index or 0
        attempted_references = list(discovery.continuation_references)[
            start_index : discovery.continuation_end_index
        ]
        failure_keys = {
            item.resource_key: item.error_code for item in discovery.audit_failures
        }
        continuation_claim_payload = {
                "operation_id": operation_id,
                "issuer_identity_id": identity.id,
                "parent_id": (continuation_row.id if continuation_row else None),
                "main_snapshot_id": main_snapshot.id,
                "manifest_identity": manifest_identity,
                "filing_selection_as_of": filing_selection_as_of,
                "history_target_json": _history_target_payload(history_target),
                "start_index": start_index,
                "end_index": discovery.continuation_end_index,
                "attempted_references_json": attempted_references,
                "terminal_outcomes_json": [
                    {
                        "reference": reference,
                        "outcome": failure_keys.get(
                            f"https://data.sec.gov/submissions/{reference}",
                            "retained_and_parsed",
                        ),
                    }
                    for reference in attempted_references
                ],
                "main_snapshot": main_snapshot,
                "manifest_references": list(discovery.continuation_references),
        }
    acquisition_failure_ids: list[int] = []
    recorded_acquisition_failures: dict[
        tuple[str, str, str, str, str | None],
        SecFinancialAcquisitionFailure,
    ] = {}
    def record_acquisition_failure(
        failure: _DiscoveryFailure,
    ) -> SecFinancialAcquisitionFailure:
        snapshot = snapshots.get(failure.snapshot_source_url)
        if snapshot is None:
            raise SecFinancialIntegrityError(
                "acquisition failure has no retained submissions snapshot"
            )
        identity = (
            failure.resource_role,
            failure.resource_key,
            failure.stage,
            failure.error_code,
            failure.accession_no,
        )
        if identity in recorded_acquisition_failures:
            return recorded_acquisition_failures[identity]
        audit_failure = SecFinancialAcquisitionFailure(
            operation_id=operation_id,
            submission_snapshot_id=snapshot.id,
            stage=failure.stage,
            error_code=failure.error_code,
            accession_no=failure.accession_no,
            resource_role=failure.resource_role,
            resource_key=failure.resource_key,
        )
        db.add(audit_failure)
        db.flush()
        acquisition_failure_ids.append(audit_failure.id)
        recorded_acquisition_failures[identity] = audit_failure
        return audit_failure

    for failure in discovery.audit_failures:
        record_acquisition_failure(failure)
    for resolution in discovery.resolutions:
        snapshot = snapshots.get(resolution.snapshot_source_url)
        if snapshot is None:
            raise SecFinancialIntegrityError(
                "acquisition resolution has no retained submissions snapshot"
            )
        try:
            snapshot_content = _read_verified_submission_snapshot(
                storage_root, snapshot
            )
            main_url = (
                f"https://data.sec.gov/submissions/CIK{identity.cik}.json"
            )
            main_snapshot = snapshots.get(main_url)
            main_snapshot_content = (
                _read_verified_submission_snapshot(storage_root, main_snapshot)
                if main_snapshot is not None
                else None
            )
            validate_submission_source(
                resource_role=resolution.resource_role,
                normalized_url=resolution.resource_key,
                snapshot_content=snapshot_content,
                snapshot_sha256=snapshot.sha256,
                snapshot_size=snapshot.byte_size,
                expected_cik=identity.cik,
                main_snapshot_content=main_snapshot_content,
            )
        except ValueError as exc:
            raise SecFinancialIntegrityError(str(exc)) from exc
        db.add(
            SecFinancialAcquisitionResolution(
                operation_id=operation_id,
                resource_role=resolution.resource_role,
                resource_key=resolution.resource_key,
                resolution_kind="resource_validated",
                submission_snapshot_id=snapshot.id,
            )
        )
    db.flush()
    if continuation_claim_payload is not None:
        child_payload = dict(continuation_claim_payload)
        main_snapshot = child_payload.pop("main_snapshot")
        manifest_references = child_payload.pop("manifest_references")
        db.add(SecFinancialHistoryConsumptionClaim(**child_payload))
        db.flush()
        existing_child = None
        if continuation_row is not None:
            existing_child = db.scalar(select(SecFinancialHistoryContinuation).where(
                SecFinancialHistoryContinuation.parent_id == continuation_row.id
            ))
        if discovery.continuation_next_index is None:
            continuation_token = None
        elif existing_child is not None:
            continuation_token = existing_child.id
        else:
            continuation_token = str(uuid.uuid4())
            db.add(SecFinancialHistoryContinuation(
                id=continuation_token, issuer_identity_id=identity.id,
                main_snapshot_id=main_snapshot.id, source_operation_id=operation_id,
                parent_id=(continuation_row.id if continuation_row else None),
                main_sha256=main_snapshot.sha256,
                manifest_identity=child_payload["manifest_identity"],
                validated_references_json=manifest_references,
                filing_selection_as_of=filing_selection_as_of,
                history_target_json=_history_target_payload(history_target),
                next_index=discovery.continuation_next_index,
            ))
            db.flush()

    def record_accession_attempt(
        *,
        filing: SecFinancialFiling,
        outcome: str,
        index_content: bytes | None = None,
        artifacts: tuple[SecFilingArtifact, ...] | list[SecFilingArtifact] = (),
        parse_run: SecFinancialParseRun | None = None,
        acquisition_failure: SecFinancialAcquisitionFailure | None = None,
    ) -> SecFinancialAccessionAttempt:
        attempt = SecFinancialAccessionAttempt(
            operation_id=operation_id,
            filing_id=filing.id,
            accession_no=filing.accession_no,
            index_resource_key=filing.index_url,
            outcome=outcome,
            index_sha256=(
                hashlib.sha256(index_content).hexdigest()
                if index_content is not None
                else None
            ),
            input_manifest_hash=(
                _artifact_input_hash(artifacts) if parse_run is not None else None
            ),
            parse_run_id=parse_run.id if parse_run is not None else None,
            acquisition_failure_id=(
                acquisition_failure.id
                if acquisition_failure is not None
                else None
            ),
        )
        db.add(attempt)
        db.flush()
        for artifact in artifacts:
            if artifact.state == "retained":
                db.add(
                    SecFinancialAccessionAttemptArtifact(
                        attempt_id=attempt.id,
                        artifact_id=artifact.id,
                    )
                )
        db.flush()
        return attempt
    discovered = discovery.filings
    created_filings = 0
    created_artifacts = 0
    created_runs = 0
    created_facts = 0
    terminal_parse_run_id: int | None = None
    failures: list[str] = list(discovery.failures)

    for item in reversed(discovered):
        filing = db.scalar(
            select(SecFinancialFiling).where(
                SecFinancialFiling.accession_no == item.accession_no
            )
        )
        if filing is None:
            index_url, source_url = _filing_urls(identity.cik, item)
            amends_filing_id = None
            if item.form_type.endswith("/A") and item.report_date is not None:
                base_form = item.form_type[:-2]
                amends_filing_id = db.scalar(
                    select(SecFinancialFiling.id)
                    .join(
                        SecIssuerIdentity,
                        SecIssuerIdentity.id == SecFinancialFiling.issuer_identity_id,
                    )
                    .where(
                        SecIssuerIdentity.stock_id == stock_id,
                        SecFinancialFiling.form_type == base_form,
                        SecFinancialFiling.report_date == item.report_date,
                        SecFinancialFiling.accepted_at < item.accepted_at,
                    )
                    .order_by(
                        SecFinancialFiling.accepted_at.desc(),
                        SecFinancialFiling.id.desc(),
                    )
                    .limit(1)
                )
            filing = SecFinancialFiling(
                issuer_identity_id=identity.id,
                accession_no=item.accession_no,
                form_type=item.form_type,
                is_amendment=item.form_type.endswith("/A"),
                filed_on=item.filed_on,
                report_date=item.report_date,
                accepted_at=item.accepted_at,
                known_at=now,
                primary_document=item.primary_document,
                primary_doc_description=item.primary_doc_description,
                index_url=index_url,
                source_url=source_url,
                submissions_source_url=item.submissions_source_url,
                discovery_payload_sha256=item.discovery_payload_sha256,
                amends_filing_id=amends_filing_id,
            )
            db.add(filing)
            db.flush()
            created_filings += 1
        elif filing.issuer_identity_id != identity.id:
            raise SecFinancialIngestionError(
                "accession identity changed during acquisition"
            )

        try:
            index_content = _fetch_bytes(client, filing.index_url, revalidate=True)
            (
                artifacts,
                artifact_count,
                artifact_failures,
                used_legacy_artifacts,
            ) = _create_artifacts(
                db,
                client=client,
                filing=filing,
                cik=identity.cik,
                index_content=index_content,
                storage_root=storage_root,
                now=now,
            )
            created_artifacts += artifact_count
            failures.extend(artifact_failures)
        except SecFinancialIntegrityError:
            raise
        except SecFinancialFetchError as exc:
            failures.append(f"{filing.accession_no}:manifest:{exc.reason_code}")
            acquisition_failure = record_acquisition_failure(
                _DiscoveryFailure(
                    snapshot_source_url=item.submissions_source_url,
                    stage="accession_index_fetch",
                    error_code=exc.reason_code,
                    resource_role="accession_index",
                    resource_key=filing.index_url,
                    accession_no=filing.accession_no,
                )
            )
            record_accession_attempt(
                filing=filing,
                outcome="acquisition_failed",
                acquisition_failure=acquisition_failure,
            )
            continue
        except Exception:
            failures.append(f"{filing.accession_no}:manifest_failed")
            acquisition_failure = record_acquisition_failure(
                _DiscoveryFailure(
                    snapshot_source_url=item.submissions_source_url,
                    stage="accession_index_fetch",
                    error_code="accession_index_failed",
                    resource_role="accession_index",
                    resource_key=filing.index_url,
                    accession_no=filing.accession_no,
                )
            )
            record_accession_attempt(
                filing=filing,
                outcome="acquisition_failed",
                acquisition_failure=acquisition_failure,
            )
            continue

        for artifact in artifacts:
            if artifact.state not in {"rejected", "unavailable"}:
                continue
            error_code = artifact.reason_code or "artifact_acquisition_failed"
            if re.fullmatch(r"[a-z0-9_]{1,80}", error_code) is None:
                error_code = "artifact_acquisition_failed"
            resource_key = artifact.source_url
            if resource_key is None:
                safe_filename_token = hashlib.sha256(
                    artifact.filename.encode("utf-8", "backslashreplace")
                ).hexdigest()
                resource_key = (
                    "urn:valuepilot:sec-filing-artifact:"
                    f"{filing.accession_no}:sha256:{safe_filename_token}"
                )
            record_acquisition_failure(
                _DiscoveryFailure(
                    snapshot_source_url=item.submissions_source_url,
                    stage="filing_artifact_acquisition",
                    error_code=error_code,
                    resource_role="filing_artifact",
                    resource_key=resource_key,
                    accession_no=filing.accession_no,
                )
            )

        runs, facts, parse_failures, parse_run_id = _parse_primary_artifact(
            db,
            filing=filing,
            artifacts=artifacts,
            storage_root=storage_root,
            parser_version=parser_version.strip(),
            now=now,
            allow_legacy_run_reuse=used_legacy_artifacts,
            operation_id=operation_id,
        )
        created_runs += runs
        created_facts += facts
        failures.extend(parse_failures)
        terminal_parse_run_id = parse_run_id
        parse_run = db.get(SecFinancialParseRun, parse_run_id)
        if parse_run is None or parse_run.status not in {"succeeded", "failed"}:
            raise SecFinancialIntegrityError(
                "accession acquisition did not produce terminal parse lineage"
            )
        reused = parse_run.operation_id != operation_id
        if (
            reused
            and parse_run.operation_id is not None
            and db.get(
                SecFinancialLineageAvailability,
                parse_run.operation_id,
            )
            is None
        ):
            raise SecFinancialIngestionError(
                "prior SEC financial lineage is pending finalization"
            )
        attempt = record_accession_attempt(
            filing=filing,
            outcome=(
                f"parse_reused_{parse_run.status}"
                if reused
                else f"parse_{parse_run.status}"
            ),
            index_content=index_content,
            artifacts=artifacts,
            parse_run=parse_run,
        )
        db.add(
            SecFinancialAcquisitionResolution(
                operation_id=operation_id,
                resource_role="accession_terminal",
                resource_key=filing.accession_no,
                resolution_kind=(
                    "parse_succeeded"
                    if parse_run.status == "succeeded"
                    else "parse_failed"
                ),
                parse_run_id=parse_run.id,
                accession_attempt_id=attempt.id,
                accession_no=filing.accession_no,
            )
        )
        db.flush()

    if acquisition_failure_ids:
        operation_result = SecFinancialOperationResult(
            operation_id=operation_id,
            result_kind="acquisition_failure",
            acquisition_failure_id=acquisition_failure_ids[0],
        )
    elif terminal_parse_run_id is not None:
        terminal_run_operation_id = db.scalar(
            select(SecFinancialParseRun.operation_id).where(
                SecFinancialParseRun.id == terminal_parse_run_id
            )
        )
        if (
            terminal_run_operation_id is not None
            and terminal_run_operation_id != operation_id
            and db.get(
                SecFinancialLineageAvailability,
                terminal_run_operation_id,
            )
            is None
        ):
            raise SecFinancialIngestionError(
                "prior SEC financial lineage is pending finalization"
            )
        operation_result = SecFinancialOperationResult(
            operation_id=operation_id,
            result_kind="parse_run",
            parse_run_id=terminal_parse_run_id,
        )
    elif not discovered:
        operation_result = SecFinancialOperationResult(
            operation_id=operation_id,
            result_kind="no_eligible_filings",
        )
    else:
        operation_result = None
    if operation_result is not None:
        db.add(operation_result)
        db.flush()

    return FinancialIngestionReport(
        operation_id=operation_id,
        stock_id=stock_id,
        cik=identity.cik,
        filings_discovered=len(discovered),
        filings_created=created_filings,
        artifacts_created=created_artifacts,
        parse_runs_created=created_runs,
        raw_facts_created=created_facts,
        failures=tuple(failures),
        selected_filings=_selected_filing_summaries(discovered),
        next_history_cursor=continuation_token,
    )


def finalize_sec_financial_ingestion_operation(
    db: Session,
    *,
    operation_id: str,
) -> datetime:
    """Make committed lineage visible using a separately committed DB marker."""
    operation = db.scalar(
        select(SecFinancialIngestionOperation)
        .where(SecFinancialIngestionOperation.id == operation_id)
        .with_for_update()
    )
    if operation is None:
        raise SecFinancialIngestionError("SEC financial ingestion operation not found")
    availability = db.get(SecFinancialLineageAvailability, operation_id)
    if availability is None:
        current_txid = int(db.scalar(select(func.txid_current())))
        if current_txid == operation.created_txid:
            raise SecFinancialIngestionError(
                "availability requires the ingestion transaction to commit first"
            )
        snapshot_count = int(
            db.scalar(
                select(func.count())
                .select_from(SecFinancialOperationSnapshot)
                .where(SecFinancialOperationSnapshot.operation_id == operation_id)
            )
            or 0
        )
        anchor_count = int(
            db.scalar(
                select(func.count())
                .select_from(SecFinancialResourceAnchor)
                .where(SecFinancialResourceAnchor.operation_id == operation_id)
            )
            or 0
        )
        result = db.get(SecFinancialOperationResult, operation_id)
        if (
            snapshot_count < 1
            and anchor_count < 1
            and (
                result is None
                or result.result_kind != "history_continuation_failure"
            )
        ):
            raise SecFinancialIngestionError(
                "availability requires retained submissions snapshot or no-bytes resource anchor"
            )
        if result is None:
            raise SecFinancialIngestionError(
                "availability requires terminal operation result"
            )
        if anchor_count and (
            snapshot_count
            or anchor_count != 1
            or result.result_kind
            not in {"acquisition_failure", "history_continuation_failure"}
        ):
            raise SecFinancialIngestionError(
                "no-bytes resource anchor requires acquisition failure terminal"
            )
        availability = SecFinancialLineageAvailability(operation_id=operation_id)
        db.add(availability)
        db.flush()
        db.refresh(availability)
    return _aware(availability.available_at)


def finalize_pending_sec_financial_ingestion_operations(
    db: Session,
    *,
    stock_id: int,
) -> tuple[tuple[str, datetime], ...]:
    """Recover committed pending lineage under an explicit operator rerun."""
    operation_ids = db.scalars(
        select(SecFinancialIngestionOperation.id)
        .join(
            SecIssuerIdentity,
            SecIssuerIdentity.id
            == SecFinancialIngestionOperation.issuer_identity_id,
        )
        .where(
            SecIssuerIdentity.stock_id == stock_id,
            ~exists(
                select(SecFinancialLineageAvailability.operation_id).where(
                    SecFinancialLineageAvailability.operation_id
                    == SecFinancialIngestionOperation.id
                )
            ),
        )
        .order_by(SecFinancialIngestionOperation.created_at, SecFinancialIngestionOperation.id)
        .with_for_update(of=SecFinancialIngestionOperation)
    ).all()
    return tuple(
        (
            operation_id,
            finalize_sec_financial_ingestion_operation(
                db, operation_id=operation_id
            ),
        )
        for operation_id in operation_ids
    )


def has_pending_sec_financial_lineage(
    db: Session,
    *,
    stock_id: int,
) -> bool:
    return bool(
        db.scalar(
            select(
                exists(
                    select(SecFinancialIngestionOperation.id)
                    .join(
                        SecIssuerIdentity,
                        SecIssuerIdentity.id
                        == SecFinancialIngestionOperation.issuer_identity_id,
                    )
                    .where(
                        SecIssuerIdentity.stock_id == stock_id,
                        ~exists(
                            select(
                                SecFinancialLineageAvailability.operation_id
                            ).where(
                                SecFinancialLineageAvailability.operation_id
                                == SecFinancialIngestionOperation.id
                            )
                        ),
                    )
                )
            )
        )
    )


def _operation_available_as_of(
    operation_id_column: Any,
    parse_run_id_column: Any,
    cutoff: datetime,
) -> Any:
    return or_(
        and_(
            operation_id_column.is_(None),
            exists(
                select(SecFinancialLegacyParseRun.parse_run_id).where(
                    SecFinancialLegacyParseRun.parse_run_id == parse_run_id_column
                )
            ),
        ),
        exists(
            select(SecFinancialLineageAvailability.operation_id).where(
                SecFinancialLineageAvailability.operation_id
                == operation_id_column,
                SecFinancialLineageAvailability.available_at <= cutoff,
            )
        ),
    )


def select_sec_financial_evidence_as_of(
    db: Session,
    *,
    stock_id: int,
    cutoff: datetime,
    storage_root: Path,
) -> list[SecFinancialEvidenceAsOf]:
    cutoff = _aware(cutoff)
    current_identity = aliased(SecIssuerIdentity)
    superseding_identity = aliased(SecIssuerIdentity)
    current_reviewed_identity_exists = exists(
        select(current_identity.id).where(
            current_identity.stock_id == stock_id,
            current_identity.cik == SecIssuerIdentity.cik,
            current_identity.status == "reviewed",
            current_identity.known_at <= cutoff,
            current_identity.effective_from
            <= func.coalesce(SecFinancialFiling.report_date, SecFinancialFiling.filed_on),
            or_(
                current_identity.effective_to.is_(None),
                current_identity.effective_to
                >= func.coalesce(SecFinancialFiling.report_date, SecFinancialFiling.filed_on),
            ),
            ~exists(
                select(superseding_identity.id).where(
                    superseding_identity.supersedes_identity_id == current_identity.id,
                    superseding_identity.known_at <= cutoff,
                )
            ),
        )
    )
    linked_artifact_exists = exists(
        select(SecFinancialParseRunArtifact.id).where(
            SecFinancialParseRunArtifact.parse_run_id == SecFinancialParseRun.id,
            SecFinancialParseRunArtifact.known_at <= cutoff,
            SecFinancialParseRunArtifact.created_at <= cutoff,
        )
    )
    late_linked_artifact_exists = exists(
        select(SecFinancialParseRunArtifact.id)
        .join(
            SecFilingArtifact,
            SecFilingArtifact.id == SecFinancialParseRunArtifact.artifact_id,
        )
        .where(
            SecFinancialParseRunArtifact.parse_run_id == SecFinancialParseRun.id,
            or_(
                SecFinancialParseRunArtifact.known_at > cutoff,
                SecFinancialParseRunArtifact.created_at > cutoff,
                SecFilingArtifact.state != "retained",
                SecFilingArtifact.known_at > cutoff,
            ),
        )
    )
    rows = db.execute(
        select(SecFinancialFiling, SecFinancialParseRun)
        .join(
            SecIssuerIdentity,
            SecIssuerIdentity.id == SecFinancialFiling.issuer_identity_id,
        )
        .join(
            SecFinancialParseRun,
            SecFinancialParseRun.filing_id == SecFinancialFiling.id,
        )
        .where(
            SecIssuerIdentity.stock_id == stock_id,
            SecIssuerIdentity.status == "reviewed",
            SecIssuerIdentity.known_at <= cutoff,
            current_reviewed_identity_exists,
            SecFinancialFiling.accepted_at <= cutoff,
            SecFinancialFiling.known_at <= cutoff,
            SecFinancialParseRun.status == "succeeded",
            SecFinancialParseRun.fact_count > 0,
            SecFinancialParseRun.completed_at <= cutoff,
            SecFinancialParseRun.known_at <= cutoff,
            _operation_available_as_of(
                SecFinancialParseRun.operation_id,
                SecFinancialParseRun.id,
                cutoff,
            ),
            linked_artifact_exists,
            ~late_linked_artifact_exists,
        )
        .order_by(
            SecFinancialFiling.accepted_at.desc(),
            SecFinancialFiling.id.desc(),
            SecFinancialParseRun.known_at.desc(),
            SecFinancialParseRun.id.desc(),
        )
    ).all()
    latest_by_filing: dict[int, SecFinancialEvidenceAsOf | None] = {}
    for filing, run in rows:
        if filing.id in latest_by_filing:
            continue
        if not _parse_run_attempt_eligibility(
            db, run=run, cutoff=cutoff, storage_root=storage_root
        ).eligible:
            if _run_has_retained_storage_integrity_failure(
                db, run=run, storage_root=storage_root
            ):
                latest_by_filing[filing.id] = None
            continue
        latest_by_filing[filing.id] = SecFinancialEvidenceAsOf(
            filing_id=filing.id,
            accession_no=filing.accession_no,
            form_type=filing.form_type,
            accepted_at=filing.accepted_at,
            parse_run_id=run.id,
            parser_version=run.parser_version,
            input_manifest_hash=run.input_manifest_hash,
            fact_count=run.fact_count,
        )
    return [item for item in latest_by_filing.values() if item is not None]


def _run_input_links(
    db: Session, run_id: int
) -> list[tuple[SecFinancialParseRunArtifact, SecFilingArtifact]]:
    return db.execute(
        select(SecFinancialParseRunArtifact, SecFilingArtifact)
        .join(
            SecFilingArtifact,
            SecFilingArtifact.id == SecFinancialParseRunArtifact.artifact_id,
        )
        .where(SecFinancialParseRunArtifact.parse_run_id == run_id)
        .order_by(SecFilingArtifact.sequence, SecFilingArtifact.id)
    ).all()


def _run_has_retained_storage_integrity_failure(
    db: Session,
    *,
    run: SecFinancialParseRun,
    storage_root: Path,
) -> bool:
    links = _run_input_links(db, run.id)
    if not links:
        return False
    try:
        for _link, artifact in links:
            if artifact.state == "retained":
                _verify_retained_artifact(storage_root, artifact)
    except SecFinancialIntegrityError:
        return True
    return False


def _verified_run_inputs_as_of(
    db: Session,
    *,
    run: SecFinancialParseRun,
    cutoff: datetime,
    storage_root: Path,
) -> tuple[list[tuple[SecFinancialParseRunArtifact, SecFilingArtifact]], list[datetime]] | None:
    links = _run_input_links(db, run.id)
    if not links:
        return None
    boundaries: list[datetime] = []
    try:
        for link, artifact in links:
            if (
                artifact.state != "retained"
                or link.known_at > cutoff
                or link.created_at > cutoff
                or artifact.known_at > cutoff
                or artifact.created_at > cutoff
            ):
                return None
            _verify_retained_artifact(storage_root, artifact)
            boundaries.extend(
                (link.known_at, link.created_at, artifact.known_at, artifact.created_at)
            )
            if artifact.fetched_at is not None:
                boundaries.append(artifact.fetched_at)
    except SecFinancialIntegrityError:
        return None
    return links, boundaries


def _current_operation_attempt_eligibility(
    db: Session,
    *,
    attempt_id: int,
    cutoff: datetime,
    storage_root: Path,
) -> _AttemptEligibility:
    """Validate operation ownership, exact inputs, PIT, and retained bytes."""
    cutoff = _aware(cutoff)
    attempt = db.get(SecFinancialAccessionAttempt, attempt_id)
    if attempt is None:
        return _AttemptEligibility(False)
    filing = db.get(SecFinancialFiling, attempt.filing_id)
    run = db.get(SecFinancialParseRun, attempt.parse_run_id) if attempt.parse_run_id else None
    operation = db.get(SecFinancialIngestionOperation, attempt.operation_id)
    availability = db.get(SecFinancialLineageAvailability, attempt.operation_id)
    resolution = db.scalar(
        select(SecFinancialAcquisitionResolution).where(
            SecFinancialAcquisitionResolution.operation_id == attempt.operation_id,
            SecFinancialAcquisitionResolution.accession_attempt_id == attempt.id,
            SecFinancialAcquisitionResolution.parse_run_id == attempt.parse_run_id,
            SecFinancialAcquisitionResolution.accession_no == attempt.accession_no,
            SecFinancialAcquisitionResolution.resource_role == "accession_terminal",
            SecFinancialAcquisitionResolution.resource_key == attempt.accession_no,
        )
    )
    attempt_links = db.execute(
        select(SecFinancialAccessionAttemptArtifact, SecFilingArtifact)
        .join(
            SecFilingArtifact,
            SecFilingArtifact.id == SecFinancialAccessionAttemptArtifact.artifact_id,
        )
        .where(SecFinancialAccessionAttemptArtifact.attempt_id == attempt_id)
        .order_by(SecFilingArtifact.sequence, SecFilingArtifact.id)
    ).all()
    if (
        filing is None
        or run is None
        or operation is None
        or availability is None
        or resolution is None
        or not attempt_links
        or operation.issuer_identity_id != filing.issuer_identity_id
        or run.filing_id != filing.id
        or attempt.accession_no != filing.accession_no
        or attempt.index_resource_key != filing.index_url
        or resolution.resolution_kind != f"parse_{run.status}"
        or attempt.outcome not in {f"parse_{run.status}", f"parse_reused_{run.status}"}
    ):
        return _AttemptEligibility(False)
    owned_run = run.operation_id == attempt.operation_id
    if owned_run == attempt.outcome.startswith("parse_reused_"):
        return _AttemptEligibility(False)
    legacy = run.operation_id is None
    if legacy:
        if db.get(SecFinancialLegacyParseRun, run.id) is None:
            return _AttemptEligibility(False)
    elif run.operation_id != attempt.operation_id:
        prior = db.get(SecFinancialLineageAvailability, run.operation_id)
        if prior is None or prior.available_at > cutoff:
            return _AttemptEligibility(False)

    verified = _verified_run_inputs_as_of(
        db, run=run, cutoff=cutoff, storage_root=storage_root
    )
    if verified is None:
        return _AttemptEligibility(False)
    run_links, input_boundaries = verified
    attempted_ids = {artifact.id for _link, artifact in attempt_links}
    run_ids = {artifact.id for _link, artifact in run_links}
    if legacy and attempt.input_manifest_hash != run.input_manifest_hash:
        obsolete = {
            artifact.id
            for _link, artifact in run_links
            if artifact.filename == "__submissions__.json"
        }
        if len(obsolete) != 1 or attempted_ids != run_ids - obsolete:
            return _AttemptEligibility(False)
    elif attempt.input_manifest_hash != run.input_manifest_hash or attempted_ids != run_ids:
        return _AttemptEligibility(False)

    index_inputs = [
        artifact for _link, artifact in attempt_links if artifact.source_url == filing.index_url
    ]
    if (
        attempt.index_sha256 is None
        or len(index_inputs) != 1
        or index_inputs[0].sha256 != attempt.index_sha256
    ):
        return _AttemptEligibility(False)
    cutoff_values = [
        operation.attempted_at,
        operation.created_at,
        availability.available_at,
        attempt.attempted_at,
        attempt.created_at,
        resolution.created_at,
        filing.accepted_at,
        filing.known_at,
        run.completed_at,
        run.known_at,
        run.created_at,
        *input_boundaries,
    ]
    try:
        for link, artifact in attempt_links:
            if link.created_at > cutoff or artifact.state != "retained":
                return _AttemptEligibility(False)
            _verify_retained_artifact(storage_root, artifact)
            cutoff_values.extend((link.created_at, artifact.known_at, artifact.created_at))
            if artifact.fetched_at is not None:
                cutoff_values.append(artifact.fetched_at)
    except SecFinancialIntegrityError:
        return _AttemptEligibility(False)
    if any(_aware(value) > cutoff for value in cutoff_values):
        return _AttemptEligibility(False)
    return _AttemptEligibility(True, max(_aware(value) for value in cutoff_values))


def _parse_run_attempt_eligibility(
    db: Session,
    *,
    run: SecFinancialParseRun,
    cutoff: datetime,
    storage_root: Path,
) -> _AttemptEligibility:
    cutoff = _aware(cutoff)
    if run.operation_id is None:
        if db.get(SecFinancialLegacyParseRun, run.id) is None:
            return _AttemptEligibility(False)
        verified = _verified_run_inputs_as_of(
            db, run=run, cutoff=cutoff, storage_root=storage_root
        )
        if verified is None:
            return _AttemptEligibility(False)
        _links, boundaries = verified
        return _AttemptEligibility(True, max(boundaries) if boundaries else None)
    attempt_id = db.scalar(
        select(SecFinancialAccessionAttempt.id).where(
            SecFinancialAccessionAttempt.operation_id == run.operation_id,
            SecFinancialAccessionAttempt.parse_run_id == run.id,
            SecFinancialAccessionAttempt.filing_id == run.filing_id,
        )
    )
    if attempt_id is None:
        return _AttemptEligibility(False)
    return _current_operation_attempt_eligibility(
        db, attempt_id=attempt_id, cutoff=cutoff, storage_root=storage_root
    )


def select_sec_financial_failures_as_of(
    db: Session,
    *,
    stock_id: int,
    cutoff: datetime,
    storage_root: Path,
) -> list[SecFinancialEvidenceFailureAsOf]:
    """Return cutoff-visible terminal parse failures for identity-valid filings."""
    cutoff = _aware(cutoff)
    current_identity = aliased(SecIssuerIdentity)
    superseding_identity = aliased(SecIssuerIdentity)
    current_reviewed_identity_exists = exists(
        select(current_identity.id).where(
            current_identity.stock_id == stock_id,
            current_identity.cik == SecIssuerIdentity.cik,
            current_identity.status == "reviewed",
            current_identity.known_at <= cutoff,
            current_identity.created_at <= cutoff,
            current_identity.effective_from
            <= func.coalesce(SecFinancialFiling.report_date, SecFinancialFiling.filed_on),
            or_(
                current_identity.effective_to.is_(None),
                current_identity.effective_to
                >= func.coalesce(
                    SecFinancialFiling.report_date, SecFinancialFiling.filed_on
                ),
            ),
            ~exists(
                select(superseding_identity.id).where(
                    superseding_identity.supersedes_identity_id == current_identity.id,
                    superseding_identity.known_at <= cutoff,
                    superseding_identity.created_at <= cutoff,
                )
            ),
        )
    )
    late_linked_input_exists = exists(
        select(SecFinancialParseRunArtifact.id)
        .join(
            SecFilingArtifact,
            SecFilingArtifact.id == SecFinancialParseRunArtifact.artifact_id,
        )
        .where(
            SecFinancialParseRunArtifact.parse_run_id == SecFinancialParseRun.id,
            or_(
                SecFinancialParseRunArtifact.known_at > cutoff,
                SecFinancialParseRunArtifact.created_at > cutoff,
                SecFilingArtifact.known_at > cutoff,
                SecFilingArtifact.created_at > cutoff,
            ),
        )
    )
    rows = db.execute(
        select(SecFinancialFiling, SecFinancialParseRun)
        .join(
            SecIssuerIdentity,
            SecIssuerIdentity.id == SecFinancialFiling.issuer_identity_id,
        )
        .join(
            SecFinancialParseRun,
            SecFinancialParseRun.filing_id == SecFinancialFiling.id,
        )
        .where(
            SecIssuerIdentity.stock_id == stock_id,
            SecIssuerIdentity.status == "reviewed",
            SecIssuerIdentity.known_at <= cutoff,
            SecIssuerIdentity.created_at <= cutoff,
            current_reviewed_identity_exists,
            SecFinancialFiling.accepted_at <= cutoff,
            SecFinancialFiling.known_at <= cutoff,
            SecFinancialFiling.created_at <= cutoff,
            SecFinancialParseRun.completed_at <= cutoff,
            SecFinancialParseRun.known_at <= cutoff,
            SecFinancialParseRun.created_at <= cutoff,
            _operation_available_as_of(
                SecFinancialParseRun.operation_id,
                SecFinancialParseRun.id,
                cutoff,
            ),
            ~late_linked_input_exists,
        )
        .order_by(
            SecFinancialFiling.accepted_at.desc(),
            SecFinancialFiling.id.desc(),
            SecFinancialParseRun.known_at.desc(),
            SecFinancialParseRun.id.desc(),
        )
    ).all()
    terminal_by_filing: dict[int, SecFinancialEvidenceFailureAsOf | None] = {}
    for filing, run in rows:
        if filing.id in terminal_by_filing:
            continue
        if not _parse_run_attempt_eligibility(
            db, run=run, cutoff=cutoff, storage_root=storage_root
        ).eligible:
            if _run_has_retained_storage_integrity_failure(
                db, run=run, storage_root=storage_root
            ):
                terminal_by_filing[filing.id] = SecFinancialEvidenceFailureAsOf(
                    filing_id=filing.id,
                    accession_no=filing.accession_no,
                    parse_run_id=run.id,
                    error_code="retained_artifact_integrity_failure",
                )
            continue
        if run.status == "failed":
            error_code = run.error_code or "parse_failed"
            if re.fullmatch(r"[a-z0-9_]{1,80}", error_code) is None:
                error_code = "parse_failed"
            terminal_by_filing[filing.id] = SecFinancialEvidenceFailureAsOf(
                filing_id=filing.id,
                accession_no=filing.accession_no,
                parse_run_id=run.id,
                error_code=error_code,
            )
        else:
            terminal_by_filing[filing.id] = None
    failures = [item for item in terminal_by_filing.values() if item is not None]
    failure_identity = aliased(SecIssuerIdentity)
    failure_current_identity = aliased(SecIssuerIdentity)
    failure_superseding_identity = aliased(SecIssuerIdentity)
    failure_has_terminal_reviewed_identity = exists(
        select(failure_current_identity.id).where(
            failure_current_identity.stock_id == stock_id,
            failure_current_identity.cik == failure_identity.cik,
            failure_current_identity.status == "reviewed",
            failure_current_identity.known_at <= cutoff,
            failure_current_identity.created_at <= cutoff,
            failure_current_identity.effective_from
            <= cast(SecFinancialIngestionOperation.attempted_at, Date),
            or_(
                failure_current_identity.effective_to.is_(None),
                failure_current_identity.effective_to
                >= cast(SecFinancialIngestionOperation.attempted_at, Date),
            ),
            ~exists(
                select(failure_superseding_identity.id).where(
                    failure_superseding_identity.supersedes_identity_id
                    == failure_current_identity.id,
                    failure_superseding_identity.known_at <= cutoff,
                    failure_superseding_identity.created_at <= cutoff,
                )
            ),
        )
    )
    acquisition_failure_rows = db.execute(
        select(
            SecFinancialAcquisitionFailure,
            SecFinancialIngestionOperation.issuer_identity_id,
            SecFinancialLineageAvailability.available_at,
        )
        .join(
            SecFinancialIngestionOperation,
            SecFinancialIngestionOperation.id
            == SecFinancialAcquisitionFailure.operation_id,
        )
        .join(
            failure_identity,
            failure_identity.id
            == SecFinancialIngestionOperation.issuer_identity_id,
        )
        .join(
            SecFinancialLineageAvailability,
            SecFinancialLineageAvailability.operation_id
            == SecFinancialAcquisitionFailure.operation_id,
        )
        .where(
            failure_identity.stock_id == stock_id,
            failure_identity.status == "reviewed",
            failure_identity.known_at <= cutoff,
            failure_identity.created_at <= cutoff,
            SecFinancialIngestionOperation.attempted_at <= cutoff,
            failure_has_terminal_reviewed_identity,
            SecFinancialLineageAvailability.available_at <= cutoff,
            SecFinancialAcquisitionFailure.created_at <= cutoff,
        )
        .order_by(
            SecFinancialLineageAvailability.available_at.desc(),
            SecFinancialAcquisitionFailure.id.desc(),
        )
    ).all()
    acquisition_failures = []
    seen_failure_scopes: set[tuple[int, str | None, str, str, str]] = set()
    for item, issuer_identity_id, failure_available_at in acquisition_failure_rows:
        scope = (
            issuer_identity_id,
            item.accession_no,
            item.resource_role,
            item.resource_key,
            item.stage,
        )
        if scope in seen_failure_scopes:
            continue
        seen_failure_scopes.add(scope)
        resolver_operation = aliased(SecFinancialIngestionOperation)
        resolver_availability = aliased(SecFinancialLineageAvailability)
        resolution_predicate = (
            and_(
                SecFinancialAcquisitionResolution.resource_role
                == "accession_terminal",
                SecFinancialAcquisitionResolution.accession_no
                == item.accession_no,
                SecFinancialAcquisitionResolution.resource_key
                == item.accession_no,
                SecFinancialAcquisitionResolution.resolution_kind.in_(
                    ("parse_succeeded", "parse_failed")
                ),
            )
            if item.accession_no is not None
            else and_(
                SecFinancialAcquisitionResolution.resource_role
                == item.resource_role,
                SecFinancialAcquisitionResolution.resource_key
                == item.resource_key,
                SecFinancialAcquisitionResolution.resolution_kind
                == "resource_validated",
            )
        )
        resolution_rows = db.execute(
            select(SecFinancialAcquisitionResolution, SecSubmissionSnapshot)
            .join(
                resolver_operation,
                resolver_operation.id
                == SecFinancialAcquisitionResolution.operation_id,
            )
            .join(
                resolver_availability,
                resolver_availability.operation_id
                == SecFinancialAcquisitionResolution.operation_id,
            )
            .outerjoin(
                SecSubmissionSnapshot,
                SecSubmissionSnapshot.id
                == SecFinancialAcquisitionResolution.submission_snapshot_id,
            )
            .where(
                resolver_operation.issuer_identity_id == issuer_identity_id,
                or_(
                    resolver_availability.available_at > failure_available_at,
                    and_(
                        SecFinancialAcquisitionResolution.operation_id
                        == item.operation_id,
                        SecFinancialAcquisitionResolution.created_at
                        >= item.created_at,
                    ),
                ),
                resolver_availability.available_at <= cutoff,
                SecFinancialAcquisitionResolution.created_at <= cutoff,
                SecFinancialAcquisitionResolution.created_at >= item.created_at,
                or_(
                    SecFinancialAcquisitionResolution.resource_role
                    != "accession_terminal",
                    exists(
                        select(SecFinancialAccessionAttempt.id).where(
                            SecFinancialAccessionAttempt.id
                            == SecFinancialAcquisitionResolution.accession_attempt_id,
                            SecFinancialAccessionAttempt.attempted_at
                            >= item.created_at,
                        )
                    ),
                ),
                resolution_predicate,
            )
        ).all()
        resolved = False
        for resolution, snapshot in resolution_rows:
            if resolution.resource_role == "accession_terminal":
                if (
                    resolution.accession_attempt_id is not None
                    and _current_operation_attempt_eligibility(
                        db,
                        attempt_id=resolution.accession_attempt_id,
                        cutoff=cutoff,
                        storage_root=storage_root,
                    ).eligible
                ):
                    resolved = True
                    break
                continue
            expected_cik = db.scalar(
                select(SecIssuerIdentity.cik)
                .join(
                    SecFinancialIngestionOperation,
                    SecFinancialIngestionOperation.issuer_identity_id
                    == SecIssuerIdentity.id,
                )
                .where(SecFinancialIngestionOperation.id == resolution.operation_id)
            )
            if snapshot is None or expected_cik is None:
                continue
            main_url = f"https://data.sec.gov/submissions/CIK{expected_cik}.json"
            main_snapshot = db.scalar(
                select(SecSubmissionSnapshot)
                .join(
                    SecFinancialOperationSnapshot,
                    SecFinancialOperationSnapshot.snapshot_id == SecSubmissionSnapshot.id,
                )
                .where(
                    SecFinancialOperationSnapshot.operation_id == resolution.operation_id,
                    SecSubmissionSnapshot.source_url == main_url,
                )
            )
            try:
                snapshot_content = _read_verified_submission_snapshot(
                    storage_root, snapshot
                )
                main_content = (
                    _read_verified_submission_snapshot(storage_root, main_snapshot)
                    if main_snapshot is not None
                    else None
                )
                validate_submission_source(
                    resource_role=resolution.resource_role,
                    normalized_url=resolution.resource_key,
                    snapshot_content=snapshot_content,
                    snapshot_sha256=snapshot.sha256,
                    snapshot_size=snapshot.byte_size,
                    expected_cik=expected_cik,
                    main_snapshot_content=main_content,
                )
            except (SecFinancialIntegrityError, ValueError):
                continue
            else:
                resolved = True
                break
        if not resolved:
            acquisition_failures.append(item)
    failures.extend(
        SecFinancialEvidenceFailureAsOf(
            filing_id=None,
            accession_no=item.accession_no or "submissions",
            parse_run_id=None,
            error_code=item.error_code,
        )
        for item in acquisition_failures
    )
    return failures


def earliest_replayable_sec_financial_evidence_at(
    db: Session,
    *,
    stock_id: int,
    storage_root: Path,
) -> datetime | None:
    """Return the first cutoff with one complete, PIT-eligible evidence set."""
    candidates = db.execute(
        select(SecFinancialParseRun, SecFinancialFiling, SecIssuerIdentity)
        .join(
            SecFinancialFiling,
            SecFinancialFiling.id == SecFinancialParseRun.filing_id,
        )
        .join(
            SecIssuerIdentity,
            SecIssuerIdentity.id == SecFinancialFiling.issuer_identity_id,
        )
        .where(
            SecIssuerIdentity.stock_id == stock_id,
            SecIssuerIdentity.status == "reviewed",
            SecFinancialParseRun.status == "succeeded",
            SecFinancialParseRun.fact_count > 0,
        )
        .order_by(SecFinancialParseRun.id.asc())
    ).all()
    latest_finalized_by_filing: dict[
        int, tuple[SecFinancialParseRun, SecFinancialFiling]
    ] = {}
    for run, filing, _identity in candidates:
        if run.operation_id is not None:
            if db.get(SecFinancialLineageAvailability, run.operation_id) is None:
                continue
        elif db.get(SecFinancialLegacyParseRun, run.id) is None:
            continue
        current = latest_finalized_by_filing.get(filing.id)
        if current is None or (
            _aware(run.known_at), run.id
        ) > (
            _aware(current[0].known_at), current[0].id
        ):
            latest_finalized_by_filing[filing.id] = (run, filing)
    storage_blocked_filings = {
        filing_id
        for filing_id, (run, _filing) in latest_finalized_by_filing.items()
        if _run_has_retained_storage_integrity_failure(
            db, run=run, storage_root=storage_root
        )
    }
    replayable_boundaries: list[datetime] = []
    for run, filing, identity in candidates:
        if filing.id in storage_blocked_filings:
            continue
        availability = None
        if run.operation_id is not None:
            availability = db.get(
                SecFinancialLineageAvailability, run.operation_id
            )
            if availability is None:
                continue
        elif db.get(SecFinancialLegacyParseRun, run.id) is None:
            continue
        attempt_eligibility = _parse_run_attempt_eligibility(
            db,
            run=run,
            cutoff=datetime.max.replace(tzinfo=timezone.utc),
            storage_root=storage_root,
        )
        if not attempt_eligibility.eligible:
            continue
        linked_inputs = db.execute(
            select(SecFinancialParseRunArtifact, SecFilingArtifact)
            .join(
                SecFilingArtifact,
                SecFilingArtifact.id == SecFinancialParseRunArtifact.artifact_id,
            )
            .where(SecFinancialParseRunArtifact.parse_run_id == run.id)
            .order_by(SecFinancialParseRunArtifact.id.asc())
        ).all()
        if not linked_inputs or any(
            artifact.state != "retained" for _, artifact in linked_inputs
        ):
            continue
        boundary_values = [
            identity.known_at,
            filing.accepted_at,
            filing.known_at,
            run.completed_at,
            run.known_at,
            run.created_at,
        ]
        if availability is not None:
            boundary_values.append(availability.available_at)
        if attempt_eligibility.replayable_at is not None:
            boundary_values.append(attempt_eligibility.replayable_at)
        for link, artifact in linked_inputs:
            boundary_values.extend(
                [
                    link.known_at,
                    link.created_at,
                    artifact.known_at,
                    artifact.created_at,
                ]
            )
            if artifact.fetched_at is not None:
                boundary_values.append(artifact.fetched_at)
        boundary = max(boundary_values)
        eligible = select_sec_financial_evidence_as_of(
            db,
            stock_id=stock_id,
            cutoff=boundary,
            storage_root=storage_root,
        )
        if any(item.parse_run_id == run.id for item in eligible):
            replayable_boundaries.append(boundary)
    return min(replayable_boundaries) if replayable_boundaries else None
