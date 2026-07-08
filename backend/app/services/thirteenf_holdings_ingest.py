"""PRD §6.2, §7.2, §18.1-18.2: HR/HR-A information table ingestion service.

Responsibilities:
- Infer value units (G2 rules) and convert raw values to value_usd.
- Normalize investment_discretion to SOLE/DFND/OTR.
- Compute holding_attribution_status from normalized discretion + other_managers_raw.
- Compute holding_row_fingerprint anchored to raw row values and source_row_index.
- Two-phase ParseRun13F: create running → bulk insert holdings → mark succeeded+is_current.
- Write portfolio_weight_pct=NULL (MVP 2 responsibility).
- Set cusip_mapping_status=pending_mapping on all new rows.
- reparse_accession: atomic switch to new parse_run; retains old holdings on failure (PRD §6.3-§6.5).
- ingest_if_needed: idempotent skip/reparse based on fingerprint_version (PRD §6.1).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.edgar.parsers.infotable import HoldingRow, parse_infotable
from app.edgar.parsers.value_units import infer_value_unit
from app.models.institutions import Filing13F, Holding13F, ParseRun13F

logger = logging.getLogger(__name__)

PARSER_VERSION = "v1"
FINGERPRINT_VERSION = "v1"

# Sentinel for NULL accepted_at when ranking filings — mirrors the key used by
# apply_amendment_policy (thirteenf_filing_detail.py) so the whole amendment
# subsystem orders filings the same way.
_MIN_ACCEPTED_AT = datetime.min.replace(tzinfo=timezone.utc)


def normalize_investment_discretion(raw: str | None) -> str | None:
    if raw is None:
        return None
    upper = raw.strip().upper()
    if upper == "SOLE":
        return "SOLE"
    if upper in ("DEFINED", "DFND"):
        return "DFND"
    if upper in ("OTR", "OTHER", "SHARED"):
        return "OTR"
    return upper


def _compute_attribution_status(
    normalized_discretion: str | None,
    other_managers_raw: str | None,
) -> str:
    if normalized_discretion == "SOLE":
        return "direct"
    if normalized_discretion == "OTR":
        return "shared"
    if normalized_discretion == "DFND":
        return "reported_for_other" if (other_managers_raw and other_managers_raw.strip()) else "unresolved"
    return "unresolved"


def _norm(val: str | int | None) -> str:
    if val is None:
        return "__NULL__"
    v = str(val).strip().upper()
    return v if v else "__NULL__"


def _holding_row_fingerprint(row: HoldingRow, value_unit_raw: str) -> str:
    """Stable fingerprint anchored to raw XML values (PRD §6.2).

    Includes source_row_index so two identical rows at different positions
    always get distinct fingerprints. value_unit_raw and raw investment_discretion
    are included so changes in unit inference or normalization rules produce
    new fingerprints triggering reparse.
    """
    parts = "|".join([
        str(row.source_row_index),
        _norm(row.cusip),
        _norm(row.issuer_name),
        _norm(row.title_of_class),
        _norm(row.value_raw_str),
        _norm(value_unit_raw),
        _norm(row.shares),
        _norm(row.share_type),
        _norm(row.put_call),
        _norm(row.investment_discretion),  # raw, before normalization
        _norm(row.other_managers_raw),
        str(row.voting_sole or 0),
        str(row.voting_shared or 0),
        str(row.voting_none or 0),
    ])
    return hashlib.sha256(parts.encode()).hexdigest()


def reconcile_restatement_activation(session: Session, filing: Filing13F) -> bool:
    """Make a parsed RESTATEMENT amendment the active filing for its period.

    A 13F-HR/A of type RESTATEMENT fully restates the period's holdings, so once
    its holdings are parsed it supersedes the original. Demotes any other active
    filing for the same (manager, quarter_end_date) and marks this one
    ``applied``. Idempotent — safe to call from the holdings-ingest path and
    from a re-run reconciliation phase. Returns True if it changed anything.

    Multi-restatement periods (T1): when a manager files two or more RESTATEMENT
    amendments for the same period, only the latest parsed restatement (ranked
    like apply_amendment_policy: accepted_at, then accession_no) may be active.
    Calling this on an earlier restatement is a no-op — it must never steal
    activation from (or demote) the later winner. This keeps the caller's
    per-filing reconciliation loop (Phase 5) both correct and crash-safe
    regardless of iteration order.
    """
    if not (filing.is_amendment and filing.amendment_type == "RESTATEMENT"):
        return False
    if filing.parse_status != "succeeded" or filing.quarter_end_date is None:
        return False

    # Only the latest parsed RESTATEMENT in the period may be active. Rank by the
    # SAME key apply_amendment_policy (thirteenf_filing_detail.py) uses for
    # originals — accepted_at desc, then accession_no desc — so the whole
    # amendment subsystem shares one ordering. accession_no is unique, so this is
    # a total order yielding a single deterministic winner (never leaves the
    # period without an active filing). Calling this on a non-winner is a no-op,
    # which keeps Phase 5's per-filing loop order-independent and crash-safe.
    #
    # Scoped for T1: accepted_at is NOT yet populated by the bulk-ingest path, so
    # today this degrades to accession_no ordering. Populating accepted_at,
    # honoring the equal-accepted_at "do not auto-switch" tie rule, unifying this
    # with apply_amendment_policy into one authority, and adding a
    # (manager, period) lock for concurrent per-accession reparse jobs are all
    # tracked in T1-FU (see docs/BACKLOG.md).
    def _rank(f: Filing13F) -> tuple:
        return (f.accepted_at or _MIN_ACCEPTED_AT, f.accession_no or "")

    other_restatements = (
        session.query(Filing13F)
        .filter(Filing13F.manager_id == filing.manager_id)
        .filter(Filing13F.quarter_end_date == filing.quarter_end_date)
        .filter(Filing13F.id != filing.id)
        .filter(Filing13F.is_amendment.is_(True))
        .filter(Filing13F.amendment_type == "RESTATEMENT")
        .filter(Filing13F.parse_status == "succeeded")
        .all()
    )
    if any(_rank(other) > _rank(filing) for other in other_restatements):
        return False

    changed = False
    superseded = (
        session.query(Filing13F)
        .filter(Filing13F.manager_id == filing.manager_id)
        .filter(Filing13F.quarter_end_date == filing.quarter_end_date)
        .filter(Filing13F.id != filing.id)
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .all()
    )
    for other in superseded:
        other.is_active_for_manager_period = False
        session.add(other)
        changed = True
    # Flush the demotions before activating this filing so the unique
    # constraint uq_active_filing_per_manager_period never sees two active rows
    # mid-statement — SQLAlchemy's unit of work emits UPDATEs in PK order, so a
    # demotion of a higher-id active row would otherwise fire AFTER this
    # (lower-id) activation.
    if changed:
        session.flush()
    if not filing.is_active_for_manager_period:
        filing.is_active_for_manager_period = True
        changed = True
    if filing.amendment_status != "applied":
        filing.amendment_status = "applied"
        changed = True
    if changed:
        session.add(filing)
    return changed


def _do_ingest_holdings(
    session: Session,
    filing: Filing13F,
    infotable_bytes: bytes,
    *,
    old_current_run_id: int | None = None,
) -> dict[str, Any]:
    """Core two-phase holdings insert (PRD §6.1-§6.2).

    Uses nested transactions (savepoints) so that a failure rolls back only the
    in-progress ingest work without destroying the outer caller/test transaction.

    Phase 1: Savepoint SP1 — create ParseRun13F('running') + parse + bulk insert.
    Phase 2: On success, mark is_current=True + succeeded and release SP1.
    On failure: rollback to SP1, then write a failed parse_run in a new savepoint.

    Returns the same shape as ingest_holdings_for_filing.
    """
    # We capture the accession_number now before any potential rollback
    # detaches the filing object from the session.
    accession_number = filing.accession_number

    exc_to_raise: Exception | None = None
    failed_run_saved = False

    # Use a savepoint so failures don't destroy the outer transaction.
    sp = session.begin_nested()
    parse_run_id_for_audit: int | None = None

    try:
        # Phase 1: create parse_run before parsing so any failure is traceable.
        parse_run = ParseRun13F(
            accession_number=accession_number,
            parser_version=PARSER_VERSION,
            fingerprint_version=FINGERPRINT_VERSION,
            status="running",
            is_current=False,
        )
        session.add(parse_run)
        session.flush()
        parse_run_id_for_audit = parse_run.id

        decision = infer_value_unit(
            infotable_bytes,
            accepted_at=filing.accepted_at,
            form_spec_version=filing.form_spec_version,
            xml_schema_version=filing.xml_schema_version,
        )

        rows = parse_infotable(infotable_bytes)

        holdings: list[Holding13F] = []
        for row in rows:
            inv_disc = normalize_investment_discretion(row.investment_discretion)
            attribution = _compute_attribution_status(inv_disc, row.other_managers_raw)
            holding_fp = _holding_row_fingerprint(row, decision.value_unit_raw)
            # row_fingerprint must be unique per (filing_id, row_fingerprint).
            # Include parse_run_id so re-parses of the same filing don't collide.
            row_fp = hashlib.sha256(f"{holding_fp}|{parse_run.id}".encode()).hexdigest()

            if decision.value_parse_rule == "schema_thousands":
                value_usd = int(row.value_raw_str) * 1000 if row.value_raw_str else row.value_thousands * 1000
            elif decision.value_parse_rule == "schema_dollars":
                value_usd = int(row.value_raw_str) if row.value_raw_str else row.value_thousands
            else:
                value_usd = None

            holding = Holding13F(
                filing_id=filing.id,
                parse_run_id=parse_run.id,
                manager_id=filing.manager_id,
                accession_number=accession_number,
                report_quarter=filing.report_quarter,
                quarter_end_date=filing.quarter_end_date,
                row_fingerprint=row_fp,
                holding_row_fingerprint=holding_fp,
                fingerprint_version=FINGERPRINT_VERSION,
                source_row_index=row.source_row_index,
                cusip=row.cusip,
                issuer_name=row.issuer_name,
                name_of_issuer=row.issuer_name,
                title_of_class=row.title_of_class,
                value_thousands=row.value_thousands,
                value_raw=row.value_raw_str,
                value_unit_raw=decision.value_unit_raw,
                value_parse_rule=decision.value_parse_rule,
                value_usd=value_usd,
                shares=row.shares,
                ssh_prnamt=row.shares,
                share_type=row.share_type,
                ssh_prnamt_type=row.share_type,
                put_call=row.put_call,
                investment_discretion=inv_disc,
                other_managers_raw=row.other_managers_raw,
                holding_attribution_status=attribution,
                voting_sole=row.voting_sole,
                voting_shared=row.voting_shared,
                voting_none=row.voting_none,
                cusip_mapping_status="pending_mapping",
                portfolio_weight_pct=None,
            )
            holdings.append(holding)

        session.bulk_save_objects(holdings)
        session.flush()

        # Phase 2: atomic switch — mark succeeded + is_current=True.
        parse_run.status = "succeeded"
        parse_run.is_current = True
        parse_run.holdings_count = len(holdings)
        parse_run.finished_at = datetime.now(timezone.utc)
        session.add(parse_run)

        # Mirror the run outcome onto the filing — Filing13F.parse_status is the
        # field surfaced as the /admin/13f/filings STATUS column and consumed by
        # readiness/health. Without this it stays "pending" forever even though
        # holdings parsed fine.
        filing.parse_status = "succeeded"
        session.add(filing)
        
        # A parsed RESTATEMENT amendment supersedes the original — activate it
        # and demote the superseded filing. Idempotent; the bulk pipeline's
        # reconciliation phase re-runs it for already-ingested restatements.
        reconcile_restatement_activation(session, filing)


        sp.commit()  # Release the savepoint, merging into outer transaction.
        session.commit()
        session.refresh(parse_run)

        return {
            "parse_run_id": parse_run.id,
            "holdings_count": len(holdings),
            "value_unit_raw": decision.value_unit_raw,
            "value_parse_rule": decision.value_parse_rule,
            "warnings": decision.warnings,
            "skipped": False,
        }

    except Exception as exc:
        exc_to_raise = exc
        # Roll back to the savepoint only — outer transaction is preserved.
        sp.rollback()

    # Write a failed parse_run audit record using a new savepoint.
    if exc_to_raise is not None:
        try:
            with session.begin_nested():
                failed_run = ParseRun13F(
                    accession_number=accession_number,
                    parser_version=PARSER_VERSION,
                    fingerprint_version=FINGERPRINT_VERSION,
                    status="failed",
                    is_current=False,
                    error=str(exc_to_raise),
                    finished_at=datetime.now(timezone.utc),
                )
                session.add(failed_run)
                # Mirror the failed outcome onto the filing. A reparse that
                # fails but restores a prior good run flips this back to
                # "succeeded" in reparse_accession's except handler.
                filing.parse_status = "failed"
                session.add(filing)
            # Commit the failure audit (failed_run + filing.parse_status) now.
            # The bulk ingest caller (thirteenf_admin_dashboard._execute_ingest_job)
            # does session.rollback() on a per-filing exception; without this
            # commit the whole outer transaction — including these
            # savepoint-merged rows — is rolled back and the failure is lost.
            # This mirrors the success path, which also commits per filing.
            session.commit()
            failed_run_saved = True
        except Exception:
            logger.warning(
                "Could not persist failed parse_run for accession %s",
                accession_number,
                exc_info=True,
            )

        raise exc_to_raise








def ingest_holdings_for_filing(
    session: Session,
    filing: Filing13F,
    infotable_bytes: bytes,
) -> dict[str, Any]:
    """Parse and persist holdings for an active HR/HR-A filing.

    Two-phase commit: ParseRun13F starts as 'running', holdings are inserted,
    then the run is atomically marked 'succeeded' + 'is_current=True'.
    """
    return _do_ingest_holdings(session, filing, infotable_bytes)


def reparse_accession(
    session: Session,
    accession_number: str,
    *,
    infotable_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Reparse an existing filing accession (PRD §6.3-§6.5).

    Creates a new parse_run under the same accession_number:
    - If the new run succeeds, it becomes is_current=True; the old current run is
      demoted to is_current=False (old holdings are retained — no DELETE).
    - If the new run fails, the old current run is restored to is_current=True.

    Arguments:
        session: SQLAlchemy session.
        accession_number: Filing accession number to reparse.
        infotable_bytes: Raw infotable XML; if None, fetches from the stored raw document.

    Returns the ingest result dict (same shape as ingest_holdings_for_filing).
    """
    filing = (
        session.query(Filing13F)
        .filter(Filing13F.accession_number == accession_number)
        .one_or_none()
    )
    if filing is None:
        raise ValueError(f"Filing not found for accession: {accession_number}")

    # Resolve infotable bytes
    if infotable_bytes is None:
        if filing.raw_infotable_doc is None:
            raise ValueError(f"No raw infotable document for accession: {accession_number}")
        from app.edgar.fetcher import load_body
        infotable_bytes = load_body(filing.raw_infotable_doc)

    # Demote the old current parse_run so the unique partial index
    # (is_current=true per accession) doesn't block the new run.
    old_current = (
        session.query(ParseRun13F)
        .filter(ParseRun13F.accession_number == accession_number)
        .filter(ParseRun13F.is_current.is_(True))
        .one_or_none()
    )
    old_current_run_id = old_current.id if old_current else None

    if old_current is not None:
        old_current.is_current = False
        session.add(old_current)
        session.flush()

    try:
        result = _do_ingest_holdings(session, filing, infotable_bytes, old_current_run_id=old_current_run_id)
        return result
    except Exception:
        # Restore old current run to is_current=True so product queries still work.
        if old_current_run_id is not None:
            try:
                restored = session.get(ParseRun13F, old_current_run_id)
                if restored is not None and not restored.is_current:
                    restored.is_current = True
                    session.add(restored)
                    # The filing keeps the prior good holdings, so undo the
                    # "failed" parse_status _do_ingest_holdings set on the
                    # failed reparse attempt.
                    if restored.status == "succeeded" and filing.parse_status != "succeeded":
                        filing.parse_status = "succeeded"
                        session.add(filing)
                    session.commit()
            except Exception:
                logger.warning(
                    "Could not restore is_current on old parse_run %s",
                    old_current_run_id,
                    exc_info=True,
                )
                session.rollback()
        raise


def ingest_if_needed(
    session: Session,
    filing: Filing13F,
    infotable_bytes: bytes,
) -> dict[str, Any]:
    """Idempotent holdings ingest (PRD §6.1).

    Skip if a current parse_run exists with a matching fingerprint_version.
    Reparse (via reparse_accession) if the current parse_run has a stale fingerprint_version.
    Always ingest if no current parse_run exists.

    Returns:
        dict with 'parse_run_id', 'holdings_count', ... and 'skipped=True' when skipped.
    """
    current_run = (
        session.query(ParseRun13F)
        .filter(ParseRun13F.accession_number == filing.accession_number)
        .filter(ParseRun13F.is_current.is_(True))
        .filter(ParseRun13F.status == "succeeded")
        .one_or_none()
    )

    if current_run is None:
        # No current parse_run — perform first ingest.
        return ingest_holdings_for_filing(session, filing, infotable_bytes)

    if current_run.fingerprint_version == FINGERPRINT_VERSION:
        # Already parsed with the current version — skip the re-parse, but
        # reconcile the filing's stored parse_status with the run outcome. This
        # self-heals filings ingested before parse_status was mirrored: a plain
        # re-run of "Ingest holdings" flips them from "pending" to "succeeded".
        if filing.parse_status != "succeeded":
            filing.parse_status = "succeeded"
            session.add(filing)
            session.flush()
        return {
            "parse_run_id": current_run.id,
            "holdings_count": current_run.holdings_count,
            "value_unit_raw": None,
            "value_parse_rule": None,
            "warnings": [],
            "skipped": True,
        }

    # Stale fingerprint_version — reparse.
    logger.info(
        "Reparsing accession %s: fingerprint_version %s != %s",
        filing.accession_number,
        current_run.fingerprint_version,
        FINGERPRINT_VERSION,
    )
    return reparse_accession(session, filing.accession_number, infotable_bytes=infotable_bytes)
