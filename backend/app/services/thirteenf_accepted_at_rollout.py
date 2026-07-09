"""T1-FU accepted_at production backfill + deploy gate (testable core).

Series-review P2 required an explicit accepted_at backfill BEFORE any authority
path (sweep / reparse / admin resolve / old-quarter ingest) runs on a database
whose filings predate T1-FU: a ≥2 competition pool containing a NULL
`accepted_at` trips the missing-acceptance rule and freezes the group.

The logic lives here — not in the script — so the GATE itself is unit-tested.
(The first cut buried it in the script's `main()` and shipped a gate that
returned 0 while NULL rows remained: it only inspected filings that had a
stored primary doc. Same lesson as the T3 rollout, whose verification lives in
`thirteenf_attribution_rollout`.)

Contract: the gate passes only when NO filing has `accepted_at IS NULL`.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.institutions import Filing13F
from app.services.edgar_ingestion import backfill_period_routing
from app.services.thirteenf_filing_detail import competition_pool


def _null_accepted_at_filings(session: Session) -> list[Filing13F]:
    return (
        session.query(Filing13F)
        .filter(Filing13F.accepted_at.is_(None))
        .order_by(Filing13F.accession_no)
        .all()
    )


def _at_risk_groups(session: Session, null_filings: list[Filing13F]) -> list[dict[str, Any]]:
    """(manager, quarter_end_date) groups where a NULL accepted_at will actually
    freeze the authority.

    The missing-acceptance rule fires only when the COMPETITION POOL has ≥2
    members AND one of them lacks `accepted_at`. A filing alone in its pool wins
    without ordering evidence (see
    `test_solo_restatement_with_null_acceptance_still_wins`); an
    admin-`applied` amendment owns its slot by decision, not by ranking.

    We ask :func:`competition_pool` — the SAME function the authority uses — so
    this diagnostic cannot drift from the rule it describes. It previously
    approximated the pool as "the group has ≥2 filings", which on a real
    373-filing snapshot reported 16 groups as "will freeze" when only 2 could:
    a Berkshire quarter holding one original plus one non-restatement amendment
    has a ONE-member pool. An operator reading an 8×-inflated blocker list
    either aborts a safe deploy or learns to ignore the diagnostic.

    Filings without a quarter_end_date belong to no group (the authority returns
    `no_period`) and are excluded here, though they still fail the gate.
    """
    affected = {
        (f.manager_id, f.quarter_end_date)
        for f in null_filings
        if f.quarter_end_date is not None
    }
    groups: list[dict[str, Any]] = []
    for manager_id, quarter_end_date in sorted(affected, key=lambda g: (g[0], g[1])):
        filings = (
            session.query(Filing13F)
            .filter(Filing13F.manager_id == manager_id)
            .filter(Filing13F.quarter_end_date == quarter_end_date)
            .all()
        )
        kind, pool = competition_pool(filings)
        if kind not in ("restatement", "originals"):
            continue  # amendment_owned / none: no ordering evidence required
        if len(pool) < 2 or all(f.accepted_at is not None for f in pool):
            continue
        groups.append(
            {
                "manager_id": manager_id,
                "quarter_end_date": quarter_end_date.isoformat(),
                "pool_kind": kind,
                "pool_size": len(pool),
                "pool_missing_accepted_at": sum(1 for f in pool if f.accepted_at is None),
            }
        )
    return groups


def verify_accepted_at_populated(session: Session) -> dict[str, Any]:
    """Read-only gate check. `failures` empty ⇔ safe to run authority paths."""
    null_filings = _null_accepted_at_filings(session)
    total = session.query(Filing13F).count()

    # Why each row is still NULL decides the operator's remediation:
    #  - has a stored primary doc  -> the doc carries no ACCEPTANCE-DATETIME
    #    (or failed to parse); re-fetching the doc is the fix.
    #  - has no stored primary doc -> never fetched; run the ingest job for
    #    that quarter (Phase 1 fetches primary docs), then re-run this gate.
    with_doc = [f.accession_no for f in null_filings if f.raw_primary_doc_id is not None]
    without_doc = [f.accession_no for f in null_filings if f.raw_primary_doc_id is None]

    failures: list[str] = []
    if null_filings:
        failures.append(
            f"{len(null_filings)} filing(s) still have accepted_at IS NULL "
            f"({len(with_doc)} with a stored primary doc, {len(without_doc)} without)"
        )

    return {
        "total_filings": total,
        "null_total": len(null_filings),
        "null_with_primary_doc": with_doc,
        "null_without_primary_doc": without_doc,
        "at_risk_groups": _at_risk_groups(session, null_filings),
        "failures": failures,
    }


def run_accepted_at_backfill(session: Session) -> dict[str, Any]:
    """Backfill accepted_at from stored primary docs, then verify the gate.

    Idempotent: re-running re-parses the stored docs and re-applies the same
    values (also how the Eastern→UTC parser correction propagates, via
    `merge_accepted_at`, which never erases a known value with NULL).
    """
    routing = backfill_period_routing(session)
    session.commit()
    report = verify_accepted_at_populated(session)
    report["routing"] = routing
    return report
