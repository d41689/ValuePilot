from __future__ import annotations

import argparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.facts import MetricFact
from app.services.owners_earnings import (
    OEPS_KEY,
    OEPS_NORM_KEY,
    OE_INPUT_KEYS,
    infer_owners_earnings_fact_nature,
)


def _owners_earnings_input_facts(session: Session, fact: MetricFact) -> list[MetricFact]:
    filters = [
        MetricFact.source_type == "parsed",
        MetricFact.stock_id == fact.stock_id,
        MetricFact.period_type == "FY",
        MetricFact.period_end_date == fact.period_end_date,
        MetricFact.metric_key.in_(sorted(OE_INPUT_KEYS)),
    ]
    if fact.source_document_id is not None:
        filters.append(MetricFact.source_document_id == fact.source_document_id)
    return session.scalars(select(MetricFact).where(*filters)).all()


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

        updated = 0
        for fact in rows:
            payload = dict(fact.value_json or {})
            if fact.metric_key == OEPS_NORM_KEY:
                target_fact_nature = "snapshot"
            else:
                target_fact_nature = infer_owners_earnings_fact_nature(
                    _owners_earnings_input_facts(session, fact)
                )
            if payload.get("fact_nature") == target_fact_nature:
                continue
            payload["fact_nature"] = target_fact_nature
            fact.value_json = payload
            session.add(fact)
            updated += 1

        if dry_run:
            session.flush()
            tx.rollback()
        else:
            session.commit()

        return {"matched": len(rows), "updated": updated}
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
