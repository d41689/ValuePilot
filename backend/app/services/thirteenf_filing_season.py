"""Investor-facing 13F filing-season state and daily digest.

The digest universe is the reviewed Value DNA subset, not ``is_featured``.
The current curated seed intentionally has no featured rows; making that flag
the denominator would produce a permanently empty product surface.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.institutions import Filing13F, InstitutionManager
from app.models.notifications import ManagerFollow
from app.models.research import ResearchCase
from app.models.stocks import PoolMembership
from app.models.users import NotificationEvent, User
from app.services.oracles_lens.new_buys_clusters import build_new_buys_clusters
from app.services.thirteenf_filing_detail import calculate_official_filing_deadline
from app.services.thirteenf_holdings_query import HR_FORM_TYPES
from app.services.thirteenf_user_api import VALUE_STYLE_PRIMARY, _filing_caveats, _manager_payload


FILING_SEASON_DAYS = 14
DIGEST_EVENT_TYPE = "thirteenf_filing_season_digest"


def filing_season_state(
    session: Session,
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    today = as_of_date or date.today()
    candidates: list[tuple[date, date]] = []
    for quarter_end in _recent_quarter_ends(today):
        deadline = calculate_official_filing_deadline(session, quarter_end)
        if deadline <= today:
            candidates.append((quarter_end, deadline))
    if not candidates:
        return {
            "in_season": False,
            "deadline_date": None,
            "days_since_deadline": None,
            "quarter": None,
        }
    quarter_end, deadline = max(candidates, key=lambda item: item[1])
    days_since = (today - deadline).days
    return {
        "in_season": 0 <= days_since <= FILING_SEASON_DAYS,
        "deadline_date": deadline.isoformat(),
        "days_since_deadline": days_since,
        "quarter": _quarter_label(quarter_end),
    }


def build_filing_season_digest(
    session: Session,
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    digest_date = as_of_date or date.today()
    season = filing_season_state(session, as_of_date=digest_date)
    if not season["in_season"] or season["quarter"] is None:
        return {
            "digest_date": digest_date.isoformat(),
            "season": season,
            "coverage": {"reported_manager_count": 0, "tracked_manager_count": 0},
            "items": [],
        }

    quarter = season["quarter"]
    tracked = _tracked_value_managers(session)
    tracked_ids = {manager.id for manager in tracked}
    reported_ids = {
        manager_id
        for (manager_id,) in session.query(Filing13F.manager_id)
        .filter(
            Filing13F.report_quarter == quarter,
            Filing13F.is_active_for_manager_period.is_(True),
            Filing13F.form_type.in_(HR_FORM_TYPES),
        )
        .all()
        if manager_id in tracked_ids
    }

    yesterday_start = datetime.combine(
        digest_date - timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )
    today_start = datetime.combine(digest_date, time.min, tzinfo=timezone.utc)
    filings = (
        session.query(Filing13F)
        .filter(
            Filing13F.manager_id.in_(tracked_ids or {-1}),
            Filing13F.report_quarter == quarter,
            Filing13F.is_active_for_manager_period.is_(True),
            Filing13F.form_type.in_(HR_FORM_TYPES),
            Filing13F.ingested_at >= yesterday_start,
            Filing13F.ingested_at < today_start,
        )
        .order_by(Filing13F.accepted_at.desc().nullslast(), Filing13F.manager_id)
        .all()
    )
    clusters = build_new_buys_clusters(
        session,
        quarter=quarter,
        min_cluster_size=1,
        superinvestors_only=False,
        manager_scope="value",
        as_of_date=digest_date,
    )
    positions_by_manager = _positions_by_manager(clusters["items"])

    items: list[dict[str, Any]] = []
    for filing in filings:
        manager = filing.manager
        items.append(
            {
                "manager": _manager_payload(manager),
                "quarter": quarter,
                "filing_date": filing.filing_date.isoformat() if filing.filing_date else None,
                "accepted_at": filing.accepted_at.isoformat() if filing.accepted_at else None,
                "holdings_count": filing.holdings_count,
                "filing_status": "available" if filing.coverage_completeness == "complete" else "available_with_caveat",
                "caveats": _filing_caveats(filing),
                "top_new_positions": positions_by_manager.get(manager.id, [])[:3],
            }
        )
    return {
        "digest_date": digest_date.isoformat(),
        "season": season,
        "coverage": {
            "reported_manager_count": len(reported_ids),
            "tracked_manager_count": len(tracked_ids),
        },
        "items": items,
    }


def persist_filing_season_digest(
    session: Session,
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    digest = build_filing_season_digest(session, as_of_date=as_of_date)
    if not digest["season"]["in_season"]:
        return {"status": "outside_filing_season", "created": 0, "existing": 0}

    digest_date = digest["digest_date"]
    users = session.query(User).filter(User.is_active.is_(True)).all()
    existing_events = (
        session.query(NotificationEvent)
        .filter(
            NotificationEvent.event_type == DIGEST_EVENT_TYPE,
            NotificationEvent.user_id.in_([user.id for user in users] or [-1]),
        )
        .all()
    )
    existing_user_ids = {
        event.user_id
        for event in existing_events
        if (event.payload_json or {}).get("digest_date") == digest_date
    }
    from app.services.research_notifications import produce_notification

    created = 0
    for user in users:
        user_digest = build_user_filing_season_digest(
            session,
            user_id=user.id,
            as_of_date=as_of_date,
            base_digest=digest,
        )
        if user.id not in existing_user_ids:
            session.add(
                NotificationEvent(
                    user_id=user.id,
                    event_type=DIGEST_EVENT_TYPE,
                    payload_json=user_digest,
                )
            )
            created += 1
        if not user_digest.get("items"):
            continue
        manager_names = [
            (item.get("manager") or {}).get("display_name")
            or (item.get("manager") or {}).get("canonical_name")
            for item in user_digest["items"][:10]
        ]
        manager_names = [name for name in manager_names if name]
        body = (
            f"{len(user_digest['items'])} followed or research-relevant managers "
            f"reported in the delayed {user_digest['season']['quarter']} filing cycle."
        )
        if manager_names:
            body += f" Review: {', '.join(manager_names)}."
        body += " Treat filings as quarter-end research evidence, not current trades."
        produce_notification(
            session,
            user_id=user.id,
            event_family="filing_season_digest",
            subject_type="filing_season_digest",
            subject_key=f"filing-season:{digest_date}",
            source_version=(
                f"{user_digest['season']['quarter']}:"
                f"{user_digest['scope']['policy_version']}"
            ),
            title=f"13F filing-season digest — {digest_date}",
            body=body,
            evidence_route="/13f/oracles-lens#filing-season-digest",
            payload={
                "digest_date": digest_date,
                "quarter": user_digest["season"]["quarter"],
                "scope_policy_version": user_digest["scope"]["policy_version"],
                "relevant_manager_count": len(user_digest["items"]),
            },
        )
    session.commit()
    return {
        "status": "persisted",
        "created": created,
        "existing": len(existing_user_ids),
    }


def build_filing_season_surface(
    session: Session,
    *,
    user_id: int,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    today = as_of_date or date.today()
    current = build_user_filing_season_digest(
        session, user_id=user_id, as_of_date=today
    )
    if not current["season"]["in_season"]:
        return {**current, "digests": []}

    events = (
        session.query(NotificationEvent)
        .filter(
            NotificationEvent.user_id == user_id,
            NotificationEvent.event_type == DIGEST_EVENT_TYPE,
        )
        .order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc())
        .limit(FILING_SEASON_DAYS + 1)
        .all()
    )
    digests = [event.payload_json for event in events if event.payload_json]
    if not any(item.get("digest_date") == current["digest_date"] for item in digests):
        digests.insert(0, current)
    return {**current, "digests": digests}


def build_user_filing_season_digest(
    session: Session,
    *,
    user_id: int,
    as_of_date: date | None = None,
    base_digest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scope a digest to followed managers and the user's active stock work."""
    digest = base_digest or build_filing_season_digest(
        session, as_of_date=as_of_date
    )
    followed_manager_ids = {
        manager_id
        for (manager_id,) in session.query(ManagerFollow.manager_id)
        .filter(ManagerFollow.user_id == user_id)
        .all()
    }
    scoped_stock_ids = {
        stock_id
        for (stock_id,) in session.query(PoolMembership.stock_id)
        .filter(PoolMembership.user_id == user_id)
        .distinct()
        .all()
    }
    scoped_stock_ids.update(
        stock_id
        for (stock_id,) in session.query(ResearchCase.stock_id)
        .filter(
            ResearchCase.user_id == user_id,
            ResearchCase.state.in_(["queued", "researching", "monitoring"]),
        )
        .distinct()
        .all()
    )
    items = []
    for item in digest.get("items", []):
        manager_id = (item.get("manager") or {}).get("id")
        relevant_stock = any(
            ((position.get("stock") or {}).get("id") in scoped_stock_ids)
            for position in item.get("top_new_positions", [])
        )
        if manager_id in followed_manager_ids or relevant_stock:
            items.append(item)
    return {
        **digest,
        "scope": {
            "policy_version": "follow-watch-case-v1.0",
            "followed_manager_count": len(followed_manager_ids),
            "active_stock_count": len(scoped_stock_ids),
        },
        "items": items,
    }


def _tracked_value_managers(session: Session) -> list[InstitutionManager]:
    return (
        session.query(InstitutionManager)
        .filter(
            InstitutionManager.status == "active",
            InstitutionManager.cik.isnot(None),
            InstitutionManager.style_primary.in_(sorted(VALUE_STYLE_PRIMARY)),
        )
        .all()
    )


def _positions_by_manager(clusters: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for cluster in clusters:
        for buyer in cluster["buyers"]:
            manager_id = int(buyer["manager"]["id"])
            result.setdefault(manager_id, []).append(
                {
                    "stock": cluster["stock"],
                    "current_value_usd": buyer["current_value_usd"],
                    "portfolio_weight_pct": buyer["portfolio_weight_pct"],
                    "confidence_level": buyer["confidence_level"],
                    "included_in_score": buyer["included_in_score"],
                    "caveat_codes": buyer["caveat_codes"],
                    "score_exclusion_reasons": buyer["score_exclusion_reasons"],
                }
            )
    for positions in result.values():
        positions.sort(
            key=lambda item: (
                not item["included_in_score"],
                -(item["portfolio_weight_pct"] or -1),
                -(item["current_value_usd"] or -1),
            )
        )
    return result


def _recent_quarter_ends(today: date) -> list[date]:
    quarter_ends = [
        date(year, month, day)
        for year in range(today.year - 2, today.year + 1)
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31))
        if date(year, month, day) < today
    ]
    return sorted(quarter_ends, reverse=True)


def _quarter_label(quarter_end: date) -> str:
    quarter = {3: 1, 6: 2, 9: 3, 12: 4}[quarter_end.month]
    return f"{quarter_end.year}-Q{quarter}"
