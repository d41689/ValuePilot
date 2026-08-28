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

from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.orm import Session, aliased

from app.edgar.parsers.financial_submissions import (
    DiscoveredFinancialFiling,
    parse_financial_submissions,
    parse_historical_financial_submissions,
)
from app.edgar.parsers.inline_xbrl import parse_inline_xbrl
from app.models.sec_financials import (
    SecFilingArtifact,
    SecFinancialFiling,
    SecFinancialParseRun,
    SecFinancialParseRunArtifact,
    SecIssuerIdentity,
    SecRawXbrlFact,
)
from app.rate_guard.client import RateGuardFetchError


CIK_RE = re.compile(r"^[0-9]{10}$")
ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
MAX_MANIFEST_ITEMS = 500
MAX_HISTORICAL_SUBMISSION_FILES = 20
HISTORICAL_SUBMISSION_FILENAME_RE = re.compile(
    r"^CIK(?P<cik>[0-9]{10})-submissions-[0-9]+[.]json$"
)
PARSER_NAME = "valuepilot-inline-xbrl-lineage"
ARTIFACT_RETENTION_POLICY_VERSION = "sec-financial-artifacts-v1"


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


@dataclass(frozen=True)
class FinancialIngestionReport:
    stock_id: int
    cik: str
    filings_discovered: int
    filings_created: int
    artifacts_created: int
    parse_runs_created: int
    raw_facts_created: int
    failures: tuple[str, ...]


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
class _DiscoveryResult:
    filings: tuple[DiscoveredFinancialFiling, ...]
    source_payloads: dict[str, bytes]
    failures: tuple[str, ...]


def _fetch_bytes(client: EdgarLikeClient, url: str) -> bytes:
    try:
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
    keys = sorted(
        {
            int.from_bytes(
                hashlib.sha256(name.encode("utf-8")).digest()[:8],
                byteorder="big",
                signed=True,
            )
            for name in names
        }
    )
    for key in keys:
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


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

    _lock_keys(db, f"sec-identity-stock:{stock_id}", f"sec-identity-cik:{cik}")

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


def _safe_artifact_url(cik: str, accession_no: str, filename: str) -> str:
    if not filename or PurePosixPath(filename).name != filename or filename in {".", ".."}:
        raise SecFinancialIngestionError("unsafe SEC artifact filename")
    if not ACCESSION_RE.fullmatch(accession_no):
        raise SecFinancialIngestionError("malformed SEC accession number")
    base = (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession_no.replace('-', '')}"
    )
    return f"{base}/{quote(filename, safe='._-')}"


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


def _verify_retained_artifact(storage_root: Path, artifact: SecFilingArtifact) -> None:
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
    submissions_content: bytes,
    storage_root: Path,
    now: datetime,
) -> tuple[list[SecFilingArtifact], int, list[str]]:
    if len(index_content) > MAX_ARTIFACT_BYTES or len(submissions_content) > MAX_ARTIFACT_BYTES:
        raise SecFinancialIngestionError("SEC discovery manifest exceeds byte limit")
    items = _manifest_items(index_content)
    manifest_material = {
        "retention_policy_version": ARTIFACT_RETENTION_POLICY_VERSION,
        "submissions_sha256": hashlib.sha256(submissions_content).hexdigest(),
        "index_sha256": hashlib.sha256(index_content).hexdigest(),
        "items": items,
    }
    manifest_hash = hashlib.sha256(
        json.dumps(manifest_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = _existing_artifacts(db, filing.id, manifest_hash)
    existing_by_name: dict[str, SecFilingArtifact] = {}
    for artifact in sorted(existing, key=lambda row: row.id, reverse=True):
        existing_by_name.setdefault(artifact.filename, artifact)

    artifacts: list[SecFilingArtifact] = []
    failures: list[str] = []
    created_count = 0
    for sequence, filename, description, source_url, content in (
        (
            -1,
            "__submissions__.json",
            "SEC submissions discovery payload",
            filing.submissions_source_url,
            submissions_content,
        ),
        (
            0,
            "__accession_index__.json",
            "SEC accession artifact index",
            filing.index_url,
            index_content,
        ),
    ):
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
        existing_artifact = existing_by_name.get(filename)
        if existing_artifact is not None and existing_artifact.state != "unavailable":
            if existing_artifact.state == "retained":
                _verify_retained_artifact(storage_root, existing_artifact)
            artifacts.append(existing_artifact)
            continue
        try:
            source_url = _safe_artifact_url(cik, filing.accession_no, filename)
        except SecFinancialIngestionError:
            if existing_artifact is not None:
                artifacts.append(existing_artifact)
                failures.append(f"{filing.accession_no}:{filename}:unsafe_filename")
                continue
            artifact = SecFilingArtifact(
                filing_id=filing.id,
                sequence=item["sequence"],
                filename=filename[:255],
                description=item["description"],
                sec_type=item["type"],
                declared_size=item["size"],
                source_url=None,
                manifest_hash=manifest_hash,
                state="rejected",
                reason_code="unsafe_filename",
                known_at=now,
            )
            db.add(artifact)
            artifacts.append(artifact)
            created_count += 1
            failures.append(f"{filing.accession_no}:{filename}:unsafe_filename")
            continue

        if not _retain_item(item, filing.primary_document):
            if existing_artifact is not None:
                artifacts.append(existing_artifact)
                continue
            artifact = SecFilingArtifact(
                filing_id=filing.id,
                sequence=item["sequence"],
                filename=filename,
                description=item["description"],
                sec_type=item["type"],
                declared_size=item["size"],
                source_url=source_url,
                manifest_hash=manifest_hash,
                state="manifest_only",
                reason_code="artifact_type_not_in_ft03_retention_scope",
                known_at=now,
            )
            db.add(artifact)
            artifacts.append(artifact)
            created_count += 1
            continue

        if item["size"] is not None and item["size"] > MAX_ARTIFACT_BYTES:
            artifact = SecFilingArtifact(
                filing_id=filing.id,
                sequence=item["sequence"],
                filename=filename,
                description=item["description"],
                sec_type=item["type"],
                declared_size=item["size"],
                source_url=source_url,
                manifest_hash=manifest_hash,
                state="rejected",
                reason_code="artifact_exceeds_byte_limit",
                known_at=now,
            )
            db.add(artifact)
            artifacts.append(artifact)
            created_count += 1
            failures.append(f"{filing.accession_no}:{filename}:artifact_exceeds_byte_limit")
            continue

        try:
            content = _fetch_bytes(client, source_url)
            if len(content) > MAX_ARTIFACT_BYTES:
                raise SecFinancialIngestionError("artifact exceeds byte limit")
            if item["size"] is not None and len(content) != item["size"]:
                artifact = SecFilingArtifact(
                    filing_id=filing.id,
                    sequence=item["sequence"],
                    filename=filename,
                    description=item["description"],
                    sec_type=item["type"],
                    declared_size=item["size"],
                    source_url=source_url,
                    manifest_hash=manifest_hash,
                    state="rejected",
                    reason_code="declared_size_mismatch",
                    known_at=now,
                )
                db.add(artifact)
                artifacts.append(artifact)
                created_count += 1
                failures.append(
                    f"{filing.accession_no}:{filename}:declared_size_mismatch"
                )
                continue
            storage_key, sha256 = _store_content_immutable(storage_root, content)
            artifact = SecFilingArtifact(
                filing_id=filing.id,
                sequence=item["sequence"],
                filename=filename,
                description=item["description"],
                sec_type=item["type"],
                declared_size=item["size"],
                source_url=source_url,
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
        except SecFinancialIntegrityError:
            raise
        except SecFinancialIngestionError as exc:
            if existing_artifact is not None:
                artifacts.append(existing_artifact)
                failures.append(
                    f"{filing.accession_no}:{filename}:artifact_policy_rejected"
                )
                continue
            artifact = SecFilingArtifact(
                filing_id=filing.id,
                sequence=item["sequence"],
                filename=filename,
                description=item["description"],
                sec_type=item["type"],
                declared_size=item["size"],
                source_url=source_url,
                manifest_hash=manifest_hash,
                state="rejected",
                reason_code="artifact_policy_rejected",
                known_at=now,
            )
            failures.append(
                f"{filing.accession_no}:{filename}:artifact_policy_rejected:{type(exc).__name__}"
            )
        except SecFinancialFetchError as exc:
            if existing_artifact is not None:
                artifacts.append(existing_artifact)
                failures.append(f"{filing.accession_no}:{filename}:{exc.reason_code}")
                continue
            artifact = SecFilingArtifact(
                filing_id=filing.id,
                sequence=item["sequence"],
                filename=filename,
                description=item["description"],
                sec_type=item["type"],
                declared_size=item["size"],
                source_url=source_url,
                manifest_hash=manifest_hash,
                state="unavailable",
                reason_code=exc.reason_code,
                known_at=now,
            )
            failures.append(f"{filing.accession_no}:{filename}:{exc.reason_code}")
        except Exception as exc:
            if existing_artifact is not None:
                artifacts.append(existing_artifact)
                failures.append(
                    f"{filing.accession_no}:{filename}:fetch_failed:{type(exc).__name__}"
                )
                continue
            artifact = SecFilingArtifact(
                filing_id=filing.id,
                sequence=item["sequence"],
                filename=filename,
                description=item["description"],
                sec_type=item["type"],
                declared_size=item["size"],
                source_url=source_url,
                manifest_hash=manifest_hash,
                state="unavailable",
                reason_code="fetch_failed",
                known_at=now,
            )
            failures.append(f"{filing.accession_no}:{filename}:fetch_failed:{type(exc).__name__}")
        db.add(artifact)
        artifacts.append(artifact)
        created_count += 1
    db.flush()
    return sorted(artifacts, key=lambda row: (row.sequence, row.id)), created_count, failures


def _parse_primary_artifact(
    db: Session,
    *,
    filing: SecFinancialFiling,
    artifacts: list[SecFilingArtifact],
    storage_root: Path,
    parser_version: str,
    now: datetime,
) -> tuple[int, int, list[str]]:
    input_hash = _artifact_input_hash(artifacts)
    existing = db.scalar(
        select(SecFinancialParseRun).where(
            SecFinancialParseRun.filing_id == filing.id,
            SecFinancialParseRun.parser_version == parser_version,
            SecFinancialParseRun.input_manifest_hash == input_hash,
        )
    )
    if existing is not None:
        if existing.status == "failed":
            return 0, 0, [
                f"{filing.accession_no}:{existing.error_code or 'parse_failed'}"
            ]
        return 0, 0, []

    primary = next(
        (
            item
            for item in artifacts
            if item.filename == filing.primary_document and item.state == "retained"
        ),
        None,
    )
    started_at = now
    retained_inputs = [item for item in artifacts if item.state == "retained"]
    incomplete_required = [
        item for item in artifacts if item.state in {"unavailable", "rejected"}
    ]
    if incomplete_required:
        run = SecFinancialParseRun(
            filing_id=filing.id,
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
        return 1, 0, [f"{filing.accession_no}:required_artifact_unavailable"]
    if primary is None or not primary.storage_key:
        run = SecFinancialParseRun(
            filing_id=filing.id,
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
        return 1, 0, [f"{filing.accession_no}:primary_artifact_unavailable"]

    try:
        content = (storage_root / primary.storage_key).read_bytes()
        if hashlib.sha256(content).hexdigest() != primary.sha256:
            raise SecFinancialIntegrityError("stored primary artifact hash mismatch")
        parsed = parse_inline_xbrl(content, artifact_id=primary.id)
        if not parsed:
            run = SecFinancialParseRun(
                filing_id=filing.id,
                parser_name=PARSER_NAME,
                parser_version=parser_version,
                input_manifest_hash=input_hash,
                status="failed",
                started_at=started_at,
                completed_at=now,
                known_at=now,
                fact_count=0,
                error_code="no_inline_xbrl_facts",
                error_detail="The retained primary document contained no inline-XBRL facts.",
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
            return 1, 0, [f"{filing.accession_no}:no_inline_xbrl_facts"]
        run = SecFinancialParseRun(
            filing_id=filing.id,
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
                    artifact_id=primary.id,
                    ordinal=ordinal,
                    concept=item.concept,
                    concept_namespace_uri=item.concept_namespace_uri,
                    context_id=item.context_id,
                    unit_id=item.unit_id,
                    unit_measure=item.unit_measure,
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
                    locator_json=item.locator,
                )
            )
        db.flush()
        return 1, len(parsed), []
    except SecFinancialIntegrityError:
        raise
    except Exception as exc:
        run = SecFinancialParseRun(
            filing_id=filing.id,
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
        return 1, 0, [f"{filing.accession_no}:parse_failed:{type(exc).__name__}"]


def _discover(
    client: EdgarLikeClient,
    cik: str,
    *,
    max_filings: int,
    as_of: datetime | None,
) -> _DiscoveryResult:
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    main_content = _fetch_bytes(client, submissions_url)
    main = parse_financial_submissions(main_content, source_url=submissions_url)
    if main.issuer.cik != cik:
        raise SecFinancialIngestionError("SEC submissions CIK does not match reviewed identity")
    discovered = list(main.filings)
    source_payloads = {submissions_url: main_content}
    failures: list[str] = []
    def eligible_count() -> int:
        return sum(1 for item in discovered if as_of is None or item.accepted_at <= as_of)

    if eligible_count() < max_filings:
        safe_historical_files: list[str] = []
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
        for filename in safe_historical_files[:MAX_HISTORICAL_SUBMISSION_FILES]:
            url = f"https://data.sec.gov/submissions/{quote(filename, safe='._-')}"
            content = _fetch_bytes(client, url)
            source_payloads[url] = content
            discovered.extend(parse_historical_financial_submissions(content, source_url=url))
            if eligible_count() >= max_filings:
                break
        if (
            eligible_count() < max_filings
            and len(safe_historical_files) > MAX_HISTORICAL_SUBMISSION_FILES
        ):
            failures.append("history_scan_limit_exceeded")
    by_accession = {item.accession_no: item for item in discovered}
    eligible = [
        item
        for item in by_accession.values()
        if as_of is None or item.accepted_at <= as_of
    ]
    selected = sorted(
        eligible, key=lambda item: (item.accepted_at, item.accession_no), reverse=True
    )[:max_filings]
    return _DiscoveryResult(
        filings=tuple(selected),
        source_payloads=source_payloads,
        failures=tuple(failures),
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
    as_of: datetime | None = None,
) -> FinancialIngestionReport:
    now = _aware(now or datetime.now(timezone.utc))
    as_of = _aware(as_of) if as_of is not None else None
    if max_filings < 1 or max_filings > 200:
        raise SecFinancialIngestionError("max_filings must be between 1 and 200")
    if not parser_version.strip():
        raise SecFinancialIngestionError("parser_version is required")
    _lock_keys(db, f"sec-identity-stock:{stock_id}")
    identity = _reviewed_identity(db, stock_id, now)
    discovery = _discover(
        client, identity.cik, max_filings=max_filings, as_of=as_of
    )
    discovered = discovery.filings
    created_filings = 0
    created_artifacts = 0
    created_runs = 0
    created_facts = 0
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
            filing_identity = db.get(SecIssuerIdentity, filing.issuer_identity_id)
            if (
                filing_identity is None
                or filing_identity.stock_id != identity.stock_id
                or filing_identity.cik != identity.cik
            ):
                raise SecFinancialIngestionError(
                    "accession already belongs to another reviewed issuer identity"
                )

        try:
            index_content = _fetch_bytes(client, filing.index_url)
            submissions_content = discovery.source_payloads.get(filing.submissions_source_url)
            if submissions_content is None:
                submissions_content = _fetch_bytes(client, filing.submissions_source_url)
            artifacts, artifact_count, artifact_failures = _create_artifacts(
                db,
                client=client,
                filing=filing,
                cik=identity.cik,
                index_content=index_content,
                submissions_content=submissions_content,
                storage_root=storage_root,
                now=now,
            )
            created_artifacts += artifact_count
            failures.extend(artifact_failures)
        except SecFinancialIntegrityError:
            raise
        except SecFinancialFetchError as exc:
            failures.append(f"{filing.accession_no}:manifest:{exc.reason_code}")
            continue
        except Exception as exc:
            failures.append(f"{filing.accession_no}:manifest_failed:{type(exc).__name__}")
            continue

        runs, facts, parse_failures = _parse_primary_artifact(
            db,
            filing=filing,
            artifacts=artifacts,
            storage_root=storage_root,
            parser_version=parser_version.strip(),
            now=now,
        )
        created_runs += runs
        created_facts += facts
        failures.extend(parse_failures)

    return FinancialIngestionReport(
        stock_id=stock_id,
        cik=identity.cik,
        filings_discovered=len(discovered),
        filings_created=created_filings,
        artifacts_created=created_artifacts,
        parse_runs_created=created_runs,
        raw_facts_created=created_facts,
        failures=tuple(failures),
    )


def select_sec_financial_evidence_as_of(
    db: Session,
    *,
    stock_id: int,
    cutoff: datetime,
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
    latest_by_filing: dict[int, SecFinancialEvidenceAsOf] = {}
    for filing, run in rows:
        latest_by_filing.setdefault(
            filing.id,
            SecFinancialEvidenceAsOf(
                filing_id=filing.id,
                accession_no=filing.accession_no,
                form_type=filing.form_type,
                accepted_at=filing.accepted_at,
                parse_run_id=run.id,
                parser_version=run.parser_version,
                input_manifest_hash=run.input_manifest_hash,
                fact_count=run.fact_count,
            ),
        )
    return list(latest_by_filing.values())
