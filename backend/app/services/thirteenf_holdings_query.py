"""PRD §7.3 holdings query contract enforcement.

All product-facing 13F holdings queries must go through `active_hr_holdings_query`.
NT filings are excluded by the form_type filter; they never produce holdings rows
and must never be interpreted as "no positions" (PRD §2.2, §7.3).
"""
from __future__ import annotations

from sqlalchemy import not_
from sqlalchemy.orm import Query, Session

from app.models.institutions import Filing13F, Holding13F, ParseRun13F

HR_FORM_TYPES = ("13F-HR", "13F-HR/A")
# NT family: the notice and its amendment form. An active 13F-NT/A must be
# treated as a notice everywhere exact "13F-NT" was (SEC defines 13F-NT/A as
# the amendment form for a 13F Notice). T1-FU re-review P2: an admin-applied
# NT/A could be active yet invisible to nt_only_manager_ids, wrongly counting
# the manager in the expected-HR denominator.
NT_FORM_TYPES = ("13F-NT", "13F-NT/A")


def current_parse_holdings_query(session: Session) -> Query:
    """Holdings from the current successful parse of each accession.

    This is the audit/version-detail primitive. Product snapshots should use
    :func:`active_hr_holdings_query`, which adds active-filing authority.
    """
    return (
        session.query(Holding13F)
        .join(ParseRun13F, Holding13F.parse_run_id == ParseRun13F.id)
        .filter(
            ParseRun13F.is_current.is_(True),
            ParseRun13F.status == "succeeded",
        )
    )


def active_hr_holdings_query(session: Session) -> Query:
    """Base query for product-facing 13F holdings (PRD §7.3 contract).

    Enforces three filters simultaneously:
    - form_type IN ('13F-HR', '13F-HR/A')         — excludes NT
    - is_active_for_manager_period = true          — only the current active filing per manager/quarter
    - parse_runs.is_current = true                 — only the current parse run per accession

    Any future holdings endpoint or service consumer must build on this query
    rather than querying holdings_13f directly.
    """
    return (
        current_parse_holdings_query(session)
        .join(
            Filing13F,
            Filing13F.accession_number == ParseRun13F.accession_number,
        )
        .filter(
            Filing13F.form_type.in_(HR_FORM_TYPES),
            Filing13F.is_active_for_manager_period.is_(True),
        )
    )


def nt_only_manager_ids(session: Session, quarter: str | None = None) -> set[int]:
    """Manager IDs that have an active NT-family filing but no active HR/HR-A.

    Used to exclude NT-only managers from the expected-filers denominator in
    readiness calculations (PRD §10.1). A manager that files NT has no direct
    holdings — their positions are reported by other managers — so they should
    not count against coverage metrics. NT-FAMILY match (13F-NT and 13F-NT/A):
    an admin-applied active NT/A is still a notice, not a holdings report.
    """
    hr_q = session.query(Filing13F.manager_id).filter(
        Filing13F.form_type.in_(HR_FORM_TYPES),
        Filing13F.is_active_for_manager_period.is_(True),
    )
    if quarter:
        hr_q = hr_q.filter(Filing13F.report_quarter == quarter)

    nt_q = session.query(Filing13F.manager_id).filter(
        Filing13F.form_type.in_(NT_FORM_TYPES),
        Filing13F.is_active_for_manager_period.is_(True),
        not_(Filing13F.manager_id.in_(hr_q)),
    )
    if quarter:
        nt_q = nt_q.filter(Filing13F.report_quarter == quarter)

    return {row.manager_id for row in nt_q.all()}
