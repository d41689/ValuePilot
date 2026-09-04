from __future__ import annotations

import argparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.facts import MetricFact
from app.services.owners_earnings import OEPS_KEY, OEPS_NORM_KEY


def backfill_in_session(
    session: Session,
    *,
    dry_run: bool = False,
    metric_fact_ids: list[int] | None = None,
) -> dict[str, int]:
    tx = session.begin_nested() if dry_run else None
    try:
        rows = session.scalars(
            select(MetricFact).where(
                MetricFact.source_type == "parsed",
                MetricFact.metric_key.in_([OEPS_KEY, OEPS_NORM_KEY]),
                or_(
                    MetricFact.value_json.is_(None),
                    MetricFact.value_json["fact_nature"].astext.is_(None),
                ),
                *( [MetricFact.id.in_(metric_fact_ids)] if metric_fact_ids else [] ),
            )
        ).all()

        if rows:
            raise RuntimeError(
                "owners-earnings fact-nature backfill is retired after the "
                "immutable Value Line lineage cutover; reparse each source "
                "document to append corrected facts"
            )
        if dry_run:
            tx.rollback()
        return {"matched": 0, "updated": 0}
    except Exception:
        if tx is not None and tx.is_active:
            tx.rollback()
        raise


def backfill(*, dry_run: bool = False) -> dict[str, int]:
    session = SessionLocal()
    try:
        return backfill_in_session(session, dry_run=dry_run)
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill fact_nature for parsed owners earnings facts."
    )
    parser.add_argument("--dry-run", action="store_true", help="Report changes without committing.")
    args = parser.parse_args()

    result = backfill(dry_run=args.dry_run)
    print(f"matched={result['matched']} updated={result['updated']} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
