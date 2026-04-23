from __future__ import annotations

import argparse

from sqlalchemy import or_, select

from app.core.db import SessionLocal
from app.models.facts import MetricFact


RATE_CAGR_EST_KEYS = {
    "rates.sales.cagr_est",
    "rates.revenues.cagr_est",
    "rates.cash_flow.cagr_est",
    "rates.earnings.cagr_est",
    "rates.dividends.cagr_est",
    "rates.book_value.cagr_est",
    "rates.premium_income.cagr_est",
    "rates.investment_income.cagr_est",
}


def backfill(*, dry_run: bool = False) -> dict[str, int]:
    session = SessionLocal()
    try:
        rows = session.scalars(
            select(MetricFact).where(
                MetricFact.source_type == "parsed",
                MetricFact.metric_key.in_(sorted(RATE_CAGR_EST_KEYS)),
                or_(
                    MetricFact.value_json.is_(None),
                    MetricFact.value_json["fact_nature"].astext.is_(None),
                ),
            )
        ).all()

        updated = 0
        for fact in rows:
            payload = dict(fact.value_json or {})
            if payload.get("fact_nature") == "opinion":
                continue
            payload["fact_nature"] = "opinion"
            fact.value_json = payload
            session.add(fact)
            updated += 1

        if dry_run:
            session.rollback()
        else:
            session.commit()

        return {"matched": len(rows), "updated": updated}
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill fact_nature for parsed rates.*.cagr_est facts.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without committing.")
    args = parser.parse_args()

    result = backfill(dry_run=args.dry_run)
    print(f"matched={result['matched']} updated={result['updated']} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
