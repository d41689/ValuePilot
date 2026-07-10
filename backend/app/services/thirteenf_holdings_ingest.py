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
    """Attribution for a holding in a manager's OWN infotable (T3, PO ruling §2).

    A holding that appears in a manager's HR/HR-A infotable IS that manager's
    reportable 13(f) position. SOLE is sole discretion; DFND/OTR is shared
    discretion — the co-managers may be the filing's own included managers or a
    sub-threshold manager whose securities are aggregated into this filing. Per
    SEC Form 13F FAQ 37/46/48, that sub-threshold case is reported WITHOUT naming
    the other manager in Column 7 (`other_managers_raw`), so an empty Column 7 is
    NOT an exclusion signal — the position still belongs to the filer. Therefore
    SOLE/DFND/OTR all attribute to the filer as `direct` regardless of Column 7.
    Only a holding with no recognized discretion is `unresolved`. Exclusion of
    holdings "reported by other managers" lives at the FILING level (13F-NT, which
    has no infotable), not here. The sole-vs-shared nuance is preserved in the
    stored `investment_discretion` column; whether discretion is shared (and with
    whom) drives a caveat, not exclusion. `other_managers_raw` is accepted for
    signature compatibility but no longer gates attribution.
    """
    if normalized_discretion in ("SOLE", "DFND", "OTR"):
        return "direct"
    return "unresolved"


def backfill_holding_attribution(session: Session) -> int:
    """Recompute holding_attribution_status for existing DFND/OTR holdings under
    the current rule (T3). `investment_discretion` is stored already-normalized,
    so it feeds `_compute_attribution_status` directly. Idempotent; returns the
    number of rows changed. Run post-deploy to migrate historical data; SOLE rows
    are untouched (already `direct`). Ownership-change and Oracle's Lens recompute
    for affected managers must follow."""
    holdings = (
        session.query(Holding13F)
        .filter(Holding13F.investment_discretion.in_(["DFND", "OTR"]))
        .all()
    )
    changed = 0
    for holding in holdings:
        new_status = _compute_attribution_status(
            holding.investment_discretion, holding.other_managers_raw
        )
        if holding.holding_attribution_status != new_status:
            holding.holding_attribution_status = new_status
            changed += 1
    session.flush()
    return changed


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
    """Converge a period's active filing after a RESTATEMENT parse.

    T1-FU: thin delegate to :func:`apply_active_filing_policy` — the single
    authority for ``is_active_for_manager_period`` (ranking, ties, terminal
    admin statuses, and the (manager, period) advisory lock all live there).
    The guards keep this callable cheap on non-restatement / unparsed filings.

    Note a deliberate behavior strengthening vs T1: calling this on a
    NON-winner restatement now converges the group immediately (the ranked
    winner gets activated), where T1's version was a strict no-op. Terminal
    state is identical; convergence is just no longer call-order dependent.
    Returns True if the group's state changed in this call.
    """
    if not (filing.is_amendment and filing.amendment_type == "RESTATEMENT"):
        return False
    if filing.parse_status != "succeeded" or filing.quarter_end_date is None:
        return False

    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    outcome = apply_active_filing_policy(
        session, filing.manager_id, filing.quarter_end_date
    )
    return bool(outcome.get("changed"))


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
        # The value this run actually stored. It is the PREFERRED denominator in
        # `compute_portfolio_weight` (`computed ... or reported ...`) and the
        # left-hand side of the quality reconciliation against the filer's own
        # reported total. The legacy per-filing path wrote it; this one did not,
        # so an automated database had NULL weights everywhere and a
        # reconciliation check that compared nothing and passed.
        filing.computed_total_value_thousands = sum(
            h.value_thousands or 0 for h in holdings
        )
        filing.common_holdings_count = sum(1 for h in holdings if h.put_call is None)
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
                # Mirror the failed outcome onto the filing.
                filing.parse_status = "failed"
                session.add(filing)
                # Series-review P1: on a REPARSE failure, restore the demoted
                # old current run IN THE SAME TRANSACTION as the failure
                # audit. The commit below used to persist the caller's demote
                # alongside the audit while the restore happened in a LATER
                # commit (reparse_accession's except handler) — a committed
                # window, permanent after a crash, in which an active filing
                # had NO current ParseRun and product holdings vanished.
                if old_current_run_id is not None:
                    old_run = session.get(ParseRun13F, old_current_run_id)
                    if old_run is not None and not old_run.is_current:
                        old_run.is_current = True
                        session.add(old_run)
                        # The prior good holdings keep serving — the filing is
                        # not "failed" from the product's point of view.
                        if old_run.status == "succeeded":
                            filing.parse_status = "succeeded"
                            session.add(filing)
            # Commit the failure audit (failed_run + filing.parse_status +
            # old-current restore) atomically. The bulk ingest caller
            # (thirteenf_admin_dashboard._execute_ingest_job) does
            # session.rollback() on a per-filing exception; without this
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
        # Backstop restore. The PRIMARY restore now happens inside
        # _do_ingest_holdings' failure path, in the same transaction as the
        # failure audit (series-review P1: no committed no-current window).
        # This handler only fires for exceptions raised BEFORE that path
        # (e.g. parse bootstrap errors) — the not-is_current guard makes it
        # a no-op when the inner restore already ran.
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
