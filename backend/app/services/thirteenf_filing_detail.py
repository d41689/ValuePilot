from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.edgar.fetcher import fetch_and_store, load_body
from app.edgar.parsers.primary_doc import (
    PrimaryDocSummary,
    edgar_accepted_date_eastern,
    parse_primary_doc,
)
from app.models.institutions import Filing13F, InstitutionManager, NoIndexExpectedDate
from app.services.thirteenf_holdings_query import (
    HR_FORM_TYPES as _HR_FORM_TYPES,
    NT_FORM_TYPES as _NT_FORM_TYPES,
)


INGESTION_FORMS = {"13F-HR", "13F-HR/A", "13F-NT"}


def merge_accepted_at(filing: Filing13F, parsed_accepted_at: datetime | None) -> bool:
    """Single merge rule for the three accepted_at writers (T1-FU).

    - NEVER erase a known acceptance timestamp with NULL: a temporarily
      tag-less / partially-fetched document must not destroy load-bearing
      ranking metadata (the old ingest_accession path wrote unconditionally,
      including None).
    - A NON-NULL re-parse of the same primary doc IS authoritative — parser
      corrections (e.g. the Eastern→UTC fix) must propagate on the next parse
      rather than being frozen behind the first-written value.

    Returns True if the filing was updated.
    """
    if parsed_accepted_at is None or filing.accepted_at == parsed_accepted_at:
        return False
    filing.accepted_at = parsed_accepted_at
    return True


@dataclass(frozen=True)
class PeriodRouting:
    period_of_report: date
    quarter_end_date: date | None
    report_quarter: str | None
    parse_status: str
    parse_warning: str | None = None
    parse_error: str | None = None


def ingest_accession_filing_detail(
    session: Session,
    payload: dict[str, Any],
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    accession = str(payload["accession_no"])
    manager_id = int(payload["manager_id"])
    form_type = str(payload.get("form_type") or "")
    if form_type not in INGESTION_FORMS:
        raise ValueError(f"Unsupported 13F filing form_type: {form_type}")

    manager = session.get(InstitutionManager, manager_id)
    if manager is None:
        raise ValueError(f"Manager not found: {manager_id}")

    filing_url = _filing_url(payload)
    raw_doc = fetch_and_store(
        session,
        source_system="edgar",
        document_type="filing_detail",
        source_url=filing_url,
        cik=str(payload.get("cik") or manager.cik or "").zfill(10),
        accession_no=accession,
        client=client,
    )
    summary = parse_primary_doc(load_body(raw_doc))
    accepted_at = summary.accepted_at
    filing_date = accepted_at.date() if accepted_at else _payload_date(payload)
    routing = route_period(
        summary.period_of_report,
        form_type=form_type,
        accepted_at=accepted_at,
        fallback_period=filing_date,
    )

    filing = _filing_for_accession(session, accession)
    if filing is None:
        filing = Filing13F(
            manager_id=manager_id,
            accession_no=accession,
            accession_number=accession,
            cik=str(payload.get("cik") or manager.cik or "").zfill(10),
            period_of_report=routing.period_of_report,
            filed_at=filing_date,
            filing_date=filing_date,
            form_type=form_type,
            version_rank=1,
            is_latest_for_period=False,
        )
        session.add(filing)

    filing.manager_id = manager_id
    filing.accession_no = accession
    filing.accession_number = accession
    filing.cik = str(payload.get("cik") or manager.cik or "").zfill(10)
    filing.form_type = form_type
    filing.period_of_report = routing.period_of_report
    filing.filed_at = filing_date
    filing.filing_date = filing_date
    # merge, never erase-with-NULL (T1-FU shared merge rule)
    merge_accepted_at(filing, accepted_at)
    filing.quarter_end_date = routing.quarter_end_date
    filing.report_quarter = routing.report_quarter
    filing.official_filing_deadline = (
        calculate_official_filing_deadline(session, routing.quarter_end_date)
        if routing.quarter_end_date
        else None
    )
    filing.raw_filing_url = filing_url
    filing.raw_primary_doc_id = raw_doc.id
    filing.reported_total_value_thousands = summary.table_value_total
    filing.holdings_count = summary.table_entry_total or 0
    filing.parse_status = routing.parse_status
    filing.parse_warning = routing.parse_warning
    filing.parse_error = routing.parse_error

    # Primary-doc metadata (report type, coverage, confidential treatment,
    # amendment flags) then the amendment policy — both shared with the bulk
    # ingest pipeline.
    apply_primary_doc_metadata(session, filing, summary)
    session.flush()
    apply_amendment_policy(session, filing)

    session.commit()
    session.refresh(filing)
    return {
        "status": "succeeded" if routing.parse_status == "pending" else routing.parse_status,
        "filing_id": filing.id,
        "accession_number": filing.accession_number,
        "report_quarter": filing.report_quarter,
        "quarter_end_date": filing.quarter_end_date.isoformat() if filing.quarter_end_date else None,
        "parse_warning": filing.parse_warning,
        "parse_error": filing.parse_error,
        "raw_document_id": filing.raw_primary_doc_id,
    }


def route_period(
    raw_period: str | None,
    *,
    form_type: str,
    accepted_at: datetime | None,
    fallback_period: date,
) -> PeriodRouting:
    if not raw_period:
        return PeriodRouting(
            period_of_report=fallback_period,
            quarter_end_date=None,
            report_quarter=None,
            parse_status="needs_review",
            parse_warning="PERIOD_MISSING",
        )

    parsed = _parse_period_date(raw_period)
    if parsed is None:
        return PeriodRouting(
            period_of_report=fallback_period,
            quarter_end_date=None,
            report_quarter=None,
            parse_status="failed",
            parse_error="PERIOD_INVALID",
        )

    nearest = _nearest_quarter_end(parsed)
    delta = abs((parsed - nearest).days)
    if delta == 0:
        return _routed_success(nearest, accepted_at=accepted_at)

    if delta <= 2:
        if form_type in {"13F-HR", "13F-HR/A"} and _accepted_in_valid_window(accepted_at, nearest):
            routed = _routed_success(nearest, accepted_at=accepted_at)
            return PeriodRouting(
                period_of_report=routed.period_of_report,
                quarter_end_date=routed.quarter_end_date,
                report_quarter=routed.report_quarter,
                parse_status=routed.parse_status,
                parse_warning="PERIOD_WEEKEND_ADJUSTED",
            )
        return PeriodRouting(
            period_of_report=parsed,
            quarter_end_date=None,
            report_quarter=None,
            parse_status="needs_review",
            parse_warning="PERIOD_WEEKEND_ADJUSTED_UNVERIFIABLE",
        )

    return PeriodRouting(
        period_of_report=parsed,
        quarter_end_date=None,
        report_quarter=None,
        parse_status="needs_review",
        parse_warning="PERIOD_TOO_FAR_FROM_QUARTER_END",
    )


def calculate_official_filing_deadline(session: Session, quarter_end_date: date) -> date:
    candidate = quarter_end_date + timedelta(days=45)
    while _is_non_operational_edgar_day(session, candidate):
        candidate += timedelta(days=1)
    return candidate


def _filing_for_accession(session: Session, accession: str) -> Filing13F | None:
    return (
        session.query(Filing13F)
        .filter(or_(Filing13F.accession_number == accession, Filing13F.accession_no == accession))
        .one_or_none()
    )


def _filing_url(payload: dict[str, Any]) -> str:
    filename = payload.get("filename")
    if filename:
        filename = str(filename).lstrip("/")
        if filename.startswith("edgar/data/"):
            return f"https://www.sec.gov/Archives/{filename}"
        if filename.startswith("Archives/"):
            return f"https://www.sec.gov/{filename}"
        if filename.startswith("http://") or filename.startswith("https://"):
            return filename
    accession = str(payload["accession_no"])
    accession_raw = accession.replace("-", "")
    cik = str(payload.get("cik") or "").lstrip("0")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_raw}/{accession}.txt"


def _payload_date(payload: dict[str, Any]) -> date:
    sync_date = payload.get("sync_date")
    if sync_date:
        return date.fromisoformat(str(sync_date))
    return datetime.now(timezone.utc).date()


def _parse_period_date(value: str) -> date | None:
    value = value.strip()
    for fmt in ("%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _nearest_quarter_end(value: date) -> date:
    candidates: list[date] = []
    for year in (value.year - 1, value.year, value.year + 1):
        candidates.extend(
            [
                date(year, 3, 31),
                date(year, 6, 30),
                date(year, 9, 30),
                date(year, 12, 31),
            ]
        )
    return min(candidates, key=lambda candidate: abs((value - candidate).days))


def _accepted_in_valid_window(accepted_at: datetime | None, quarter_end: date) -> bool:
    if accepted_at is None:
        return False
    # SEC filing-date rules run on the EASTERN calendar date (T1-FU: the
    # stored instant is now real UTC; a post-19:00-ET acceptance has a UTC
    # date one day later).
    accepted_date = edgar_accepted_date_eastern(accepted_at)
    return quarter_end <= accepted_date <= quarter_end + timedelta(days=180)


def _routed_success(quarter_end: date, *, accepted_at: datetime | None) -> PeriodRouting:
    if _accepted_more_than_three_quarters_from_period(accepted_at, quarter_end):
        return PeriodRouting(
            period_of_report=quarter_end,
            quarter_end_date=quarter_end,
            report_quarter=_report_quarter(quarter_end),
            parse_status="needs_review",
            parse_warning="PERIOD_SUSPICIOUSLY_STALE",
        )
    return PeriodRouting(
        period_of_report=quarter_end,
        quarter_end_date=quarter_end,
        report_quarter=_report_quarter(quarter_end),
        parse_status="pending",
    )


def _report_quarter(quarter_end: date) -> str:
    quarter_by_month = {3: 1, 6: 2, 9: 3, 12: 4}
    return f"{quarter_end.year}-Q{quarter_by_month[quarter_end.month]}"


def _accepted_more_than_three_quarters_from_period(accepted_at: datetime | None, quarter_end: date) -> bool:
    if accepted_at is None:
        return False
    return abs(_quarter_index(edgar_accepted_date_eastern(accepted_at)) - _quarter_index(quarter_end)) > 3


def _quarter_index(value: date) -> int:
    return value.year * 4 + ((value.month - 1) // 3)


def _is_non_operational_edgar_day(session: Session, value: date) -> bool:
    if value.weekday() >= 5:
        return True
    return NoIndexExpectedDate.active_for_date(session, value)


def _normalize_report_type(raw: str | None, form_type: str) -> str:
    text = (raw or "").strip().lower().replace("-", " ")
    if form_type in _NT_FORM_TYPES or "notice" in text:
        return "notice_report"
    if "combination" in text:
        return "combination_report"
    if "holding" in text:
        return "holdings_report"
    return "holdings_report"


def _coverage_completeness(report_type: str | None) -> str:
    if report_type == "holdings_report":
        return "complete"
    if report_type == "combination_report":
        return "partial"
    return "unknown"


def _coverage_type(report_type: str | None, form_type: str) -> str:
    if form_type in _NT_FORM_TYPES or report_type == "notice_report":
        return "notice_reported_elsewhere"
    if report_type == "combination_report":
        return "combination_partial"
    return "normal"


def _normalize_amendment_type(raw: str | None) -> str:
    if not raw:
        return "unknown"
    upper = raw.strip().upper()
    if upper == "RESTATEMENT":
        return "RESTATEMENT"
    if upper == "NEW HOLDINGS":
        return "NEW_HOLDINGS"
    if upper == "ADDITIONS, CORRECTIONS OR DELETIONS" or "ADDITIONS" in upper:
        return "ADDITIONS_CORRECTIONS_DELETIONS"
    return "unknown"


def apply_primary_doc_metadata(session: Session, filing: Filing13F, summary: Any) -> None:
    """Apply primary-document-derived filing metadata (no amendment policy).

    Sets the Filing13F fields that come from the 13F *primary document* — report
    type, coverage, confidential treatment, amendment flags. The caller runs
    `apply_amendment_policy` afterwards — the bulk pipeline does so in a second
    pass, once every sibling's `is_amendment` is set, because the policy's
    active-original selection reads sibling rows. Period routing, parse_status
    and holdings stay the caller's responsibility.
    """
    form_type = str(filing.form_type or "")
    filing.form_spec_version = summary.form_spec_version
    filing.xml_schema_version = summary.xml_schema_version
    filing.report_type = _normalize_report_type(summary.report_type, form_type)
    filing.coverage_completeness = _coverage_completeness(filing.report_type)
    filing.coverage_type = _coverage_type(filing.report_type, form_type)
    filing.has_confidential_treatment = bool(summary.has_confidential_treatment)
    filing.confidential_treatment_status = (
        "applied" if filing.has_confidential_treatment else "none"
    )
    # T1-FU: the SEC <ACCEPTANCE-DATETIME> is primary-doc metadata too — and it
    # is the PRIMARY ranking key for active-filing selection. The bulk-ingest
    # path parsed the primary doc but never wrote it (all 373 real filings had
    # accepted_at NULL, silently degrading every ranking to the accession_no
    # fallback). getattr: summary is typed Any and some callers pass partial
    # stubs.
    merge_accepted_at(filing, getattr(summary, "accepted_at", None))
    filing.other_managers_reporting = summary.other_managers_reporting or None
    filing.other_managers_included = summary.other_managers_included or None
    # A "/A" form type is, by definition, an amendment — trust it even when the
    # primary-doc parser does not flag is_amendment.
    filing.is_amendment = bool(summary.is_amendment) or form_type.endswith("/A")
    filing.amendment_type_raw = summary.amendment_type
    session.add(filing)


# Admin-decided statuses the pipeline must never auto-rewrite: an auto/admin
# apply, an admin reject / mark-informational, or an admin DEFER (T1-FU
# re-review P1 — "deferred" parks a parsed restatement outside automatic
# competition; without a dedicated status the authority re-applied it in the
# very transaction that deferred it).
_TERMINAL_AMENDMENT_STATUSES = frozenset({"applied", "rejected", "informational", "deferred"})


def apply_amendment_policy(session: Session, filing: Filing13F) -> None:
    """Per-filing amendment normalization + group active-filing convergence.

    T1-FU: the original-selection logic moved into
    :func:`apply_active_filing_policy` — the single authority every activation
    site calls. This function keeps only the per-filing normalization (amendment
    type/status initialization) and then converges the filing's
    (manager, quarter_end_date) group through the authority.
    """
    if filing.is_amendment:
        filing.amendment_type = _normalize_amendment_type(filing.amendment_type_raw)
        # A resolved amendment is terminal — an auto-applied restatement, or an
        # admin apply / reject / mark-informational. Re-running the policy on a
        # bulk re-ingest must not revert is_active / amendment_status and undo
        # the resolution.
        if filing.amendment_status in _TERMINAL_AMENDMENT_STATUSES:
            return
        filing.is_active_for_manager_period = False
        if filing.amendment_type == "RESTATEMENT":
            filing.amendment_status = "pending_parse"
        else:
            filing.amendment_status = "amendments_pending"
        session.add(filing)
        # Converge the group: a parsed sibling restatement or the originals
        # pool may need (re)activation now that this amendment is normalized.
        if filing.quarter_end_date is not None:
            apply_active_filing_policy(session, filing.manager_id, filing.quarter_end_date)
        return

    # Original filing: per-filing normalization, then the group authority.
    filing.is_amendment = False
    filing.amendment_type = None

    if not filing.quarter_end_date:
        filing.is_active_for_manager_period = False
        return

    apply_active_filing_policy(session, filing.manager_id, filing.quarter_end_date)


_MIN_ACCEPTED_AT = datetime.min.replace(tzinfo=timezone.utc)


def _active_filing_rank(f: Filing13F) -> tuple:
    """Total order for active-filing selection: (accepted_at, accession_no)
    desc. accession_no is unique → single deterministic winner."""
    return (f.accepted_at or _MIN_ACCEPTED_AT, f.accession_no or "")


def _acquire_period_lock(session: Session, manager_id: int, quarter_end_date: date) -> None:
    """Serialize active-filing decisions for one (manager, period).

    pg_advisory_xact_lock: released automatically at COMMIT/ROLLBACK, reentrant
    within a session (a caller already holding it never self-deadlocks), and a
    text-hash collision merely over-serializes — it can never corrupt. Without
    it, two per-accession reparse jobs for two restatements of the SAME period
    race the SELECT-then-demote/activate under READ COMMITTED into a silent
    wrong-winner or a uq_active_filing_per_manager_period abort (T1-FU item 4).
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"active_filing:{manager_id}:{quarter_end_date.isoformat()}"},
    )


def apply_active_filing_policy(
    session: Session, manager_id: int, quarter_end_date: date | None
) -> dict[str, Any]:
    """THE single authority for ``is_active_for_manager_period`` (T1-FU).

    Every activation site delegates here: ``apply_amendment_policy`` (metadata
    pass), ``reconcile_restatement_activation`` (post-parse), and the ingest
    job's per-quarter sweep (which replaced the Phase-4c solo-HR heuristic and
    the Phase-5 reconcile loop).

    Rules, in precedence order:
    1. Parsed (``parse_status == 'succeeded'``), HR-family (``13F-HR/A`` — an
       NT/A never competes for the holdings slot), non-rejected/-informational
       RESTATEMENTs supersede everything; ranked by ``(accepted_at,
       accession_no)`` desc.
       - **Missing acceptance evidence**: with ≥2 candidates and ANY NULL
         ``accepted_at``, ordering is unknowable — NULL is missing evidence,
         not "earliest". No auto-switch; NULL candidates AND the kept-active
         filing are flagged (``amendment_sort_warning`` + non-terminal →
         ``amendments_pending``) so the dispute reaches admins and product
         consumers (Oracle's Lens excludes/annotates ``amendments_pending``
         active filings). The accession_no fallback was dropped: accession
         prefixes identify the SUBMITTING agent (231/373 real filings differ
         from the manager CIK) and dev holds 3 real groups where lexical order
         inverts acceptance order — it is not a time proxy.
       - **Tie** (equal AND non-NULL top-two): no auto-switch; tied
         restatements AND the kept-active filing flagged as above.
    2. Otherwise the ``applied`` amendments (admin apply / activate_as_original)
       own the slot: the ranked-latest applied amendment is activated and
       everything else — including a rejected-but-still-active amendment — is
       demoted. Admin shapes eligibility via statuses (reject what you don't
       want); ranking picks deterministically among the eligible.
    3. Otherwise originals compete — HR family first: an NT original never
       beats a 13F-HR (it competes only when the period has no HR original).
       Missing-acceptance (≥2, any NULL) → no auto-switch + flags, as in rule
       1. Ties deactivate the whole pool + warning (existing semantics).
    4. No eligible filing at all → every active row is demoted (a rejected/
       stray active filing must not keep serving the product).

    Convergence invariant: on return, the period's active filing is the
    selected winner, the deliberately-kept current active (tie / missing
    evidence), or nothing. Winner paths also run a group-wide residue
    recovery: a resolved tie clears ``amendment_sort_warning`` everywhere and
    restores the flag-induced ``amendments_pending`` (originals →
    ``no_amendments_seen``; restatements → ``pending_parse``), so a stale
    admin task can't outlive its tie.

    Amendment detection is ``is_amendment OR form_type endswith '/A'`` — the
    bulk path populates ``is_amendment`` unreliably; the form suffix is
    authoritative (Phase-4c lesson, PR #56 re-review).

    Demote → flush → activate ordering keeps
    ``uq_active_filing_per_manager_period`` satisfied mid-transaction (T1).

    Returns ``{"decision", "changed", "newly_activated", "active_id"}``.
    Never commits — the caller owns the transaction boundary.
    """
    if quarter_end_date is None:
        return {"decision": "no_period", "changed": False, "newly_activated": False, "active_id": None}

    _acquire_period_lock(session, manager_id, quarter_end_date)

    filings = (
        session.query(Filing13F)
        .filter(Filing13F.manager_id == manager_id)
        .filter(Filing13F.quarter_end_date == quarter_end_date)
        .all()
    )
    if not filings:
        return {"decision": "no_filings", "changed": False, "newly_activated": False, "active_id": None}

    def _is_amendment(f: Filing13F) -> bool:
        return bool(f.is_amendment) or str(f.form_type or "").endswith("/A")

    amendments = [f for f in filings if _is_amendment(f)]
    originals = [f for f in filings if not _is_amendment(f)]

    changed = False
    newly_activated = False

    def _set_active(winner: Filing13F) -> None:
        nonlocal changed, newly_activated
        demoted = False
        for f in filings:
            if f is not winner and f.is_active_for_manager_period:
                f.is_active_for_manager_period = False
                session.add(f)
                demoted = True
                changed = True
        if demoted:
            # Flush demotions before activating so the partial unique index
            # never sees two active rows mid-statement (UPDATEs are emitted in
            # PK order otherwise — the T1 crash).
            session.flush()
        if not winner.is_active_for_manager_period:
            winner.is_active_for_manager_period = True
            session.add(winner)
            changed = True
            newly_activated = True

    def _result(decision: str) -> dict[str, Any]:
        active_id = next(
            (f.id for f in filings if f.is_active_for_manager_period), None
        )
        return {
            "decision": decision,
            "changed": changed,
            "newly_activated": newly_activated,
            "active_id": active_id,
        }

    def _flag_pending(f: Filing13F) -> None:
        """Flag a filing whose ordering/eligibility is disputed: warning +
        (non-terminal only) amendments_pending — the state admins queue on and
        Oracle's Lens excludes/annotates (MVP4-05 / MVP5-02)."""
        nonlocal changed
        if not f.amendment_sort_warning:
            f.amendment_sort_warning = True
            changed = True
        if (
            f.amendment_status not in _TERMINAL_AMENDMENT_STATUSES
            and f.amendment_status != "amendments_pending"
        ):
            f.amendment_status = "amendments_pending"
            changed = True
        session.add(f)

    def _current_active() -> Filing13F | None:
        return next((f for f in filings if f.is_active_for_manager_period), None)

    def _clear_stale_residue(members: list[Filing13F]) -> None:
        """Group-wide recovery once a winner is decided: clear tie/missing
        flags and restore the flag-induced amendments_pending. Read the
        warning BEFORE clearing it (the pre-T1-FU code checked after
        clearing, so the recovery never fired)."""
        nonlocal changed
        for f in members:
            was_warned = bool(f.amendment_sort_warning)
            if was_warned:
                f.amendment_sort_warning = False
                changed = True
            if was_warned and f.amendment_status == "amendments_pending":
                if not _is_amendment(f):
                    f.amendment_status = "no_amendments_seen"
                    changed = True
                elif f.amendment_type == "RESTATEMENT":
                    # Its pre-flag state: parsed but not applied.
                    f.amendment_status = "pending_parse"
                    changed = True
                # Other amendments: amendments_pending IS their normal state —
                # only the warning was residue.
            session.add(f)

    # --- Rule 1: parsed, non-rejected HR-family restatements supersede all. ---
    # Excluded statuses: rejected / informational (admin negative) and
    # deferred (admin "park it — do NOT auto-apply"; re-review P1: without
    # this exclusion the authority re-applied a restatement in the same
    # transaction that deferred it).
    competing = [
        a for a in amendments
        if a.amendment_type == "RESTATEMENT"
        and (a.form_type or "") in _HR_FORM_TYPES  # an NT/A never owns holdings
        and a.parse_status == "succeeded"
        and a.amendment_status not in ("rejected", "informational", "deferred")
    ]
    if competing:
        # Missing acceptance evidence: NULL is missing data, NOT "earliest".
        # With ≥2 candidates and any NULL, ordering is unknowable — do not
        # switch; flag the unrankable candidates AND the kept-active filing so
        # the dispute is visible to admins and product consumers. (The old
        # accession_no fallback is gone: accession prefixes identify the
        # SUBMITTING agent, not the manager — 231/373 real filings differ, and
        # 3 real groups lexically invert acceptance order.)
        if len(competing) > 1 and any(c.accepted_at is None for c in competing):
            # Flag the WHOLE disputed pool, not just the NULL members — the
            # rankable sibling is frozen out by the missing evidence and the
            # admin queue must show every party to the dispute.
            for c in competing:
                _flag_pending(c)
            cur = _current_active()
            if cur is not None:
                _flag_pending(cur)
            return _result("missing_acceptance")
        ranked = sorted(competing, key=_active_filing_rank, reverse=True)
        top_at = ranked[0].accepted_at
        if (
            len(ranked) > 1
            and top_at is not None
            and ranked[1].accepted_at == top_at
        ):
            # Tie: no auto-switch. Flag the tied restatements AND the filing
            # that keeps serving the product, so the uncertainty propagates
            # to consumers (Oracle's Lens pending-amendment handling) instead
            # of the active filing scoring as a clean signal.
            for r in ranked:
                if r.accepted_at == top_at:
                    _flag_pending(r)
            cur = _current_active()
            if cur is not None:
                _flag_pending(cur)
            return _result("restatement_tie")
        winner = ranked[0]
        _set_active(winner)
        if winner.amendment_status != "applied":
            winner.amendment_status = "applied"
            changed = True
        if winner.amendment_sort_warning:
            winner.amendment_sort_warning = False
            changed = True
        session.add(winner)
        _clear_stale_residue([f for f in filings if f is not winner])
        return _result("restatement")

    # --- Rule 2: applied amendments own the slot (admin decision). ---
    applied_amendments = [a for a in amendments if a.amendment_status == "applied"]
    if applied_amendments:
        # Select ONE owner (ranked latest) and converge the whole group:
        # a rejected-but-still-active amendment or a stale original must be
        # demoted, not merely tolerated. Admin intent is expressed through
        # statuses — reject what should not own the slot.
        owner = max(applied_amendments, key=_active_filing_rank)
        _set_active(owner)
        _clear_stale_residue([f for f in filings if f is not owner])
        return _result("amendment_owned")

    # --- Rule 3: originals compete; HR family beats NT. ---
    hr_originals = [o for o in originals if (o.form_type or "") in _HR_FORM_TYPES]
    pool = hr_originals or originals
    if not pool:
        # Nothing eligible (only unresolved/rejected amendments): nothing may
        # keep serving the product — demote any stray active row.
        stray = _current_active()
        if stray is not None:
            stray.is_active_for_manager_period = False
            session.add(stray)
            changed = True
        return _result("none_eligible")

    # Missing acceptance evidence — same rule and rationale as rule 1 (flag
    # the whole disputed pool + the kept-active filing).
    if len(pool) > 1 and any(o.accepted_at is None for o in pool):
        for o in pool:
            _flag_pending(o)
        cur = _current_active()
        if cur is not None:
            _flag_pending(cur)
        return _result("missing_acceptance")

    ranked = sorted(pool, key=_active_filing_rank, reverse=True)
    top_at = ranked[0].accepted_at
    tie = (
        len(ranked) > 1
        and top_at is not None
        and ranked[1].accepted_at == top_at
    )

    if tie:
        # Ambiguous ordering: deactivate everything, flag the pool for a human
        # (existing apply_amendment_policy semantics).
        for o in originals:
            if o.is_active_for_manager_period:
                o.is_active_for_manager_period = False
                changed = True
            session.add(o)
        for o in pool:
            _flag_pending(o)
        return _result("original_tie")

    winner = ranked[0]
    _set_active(winner)
    if winner.amendment_sort_warning:
        winner.amendment_sort_warning = False
        changed = True
    if winner.amendment_status == "amendments_pending":
        # Flag-induced only: an original never gets amendments_pending except
        # from a tie/missing flag, so restoring here is safe.
        winner.amendment_status = "no_amendments_seen"
        changed = True
    session.add(winner)
    _clear_stale_residue([f for f in filings if f is not winner])
    return _result("original")
