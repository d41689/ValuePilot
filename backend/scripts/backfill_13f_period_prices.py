from __future__ import annotations

import argparse
from datetime import date

from app.core.db import SessionLocal
from app.services.market_data_service import MarketDataService


def _parse_periods(raw_periods: list[str] | None) -> list[date] | None:
    if not raw_periods:
        return None
    return [date.fromisoformat(raw) for raw in raw_periods]


def backfill(
    *,
    periods: list[date] | None = None,
    superinvestor_only: bool = True,
    limit: int | None = None,
) -> list[dict]:
    session = SessionLocal()
    try:
        service = MarketDataService(session)
        return service.backfill_13f_linked_period_prices(
            periods=periods,
            superinvestor_only=superinvestor_only,
            reason="13f_period_price_backfill",
            limit=limit,
        )
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill local EOD prices for stocks linked from 13F periods."
    )
    parser.add_argument(
        "--period",
        action="append",
        dest="periods",
        help="13F period_of_report date, e.g. 2024-03-31. May be passed multiple times.",
    )
    parser.add_argument(
        "--include-all-managers",
        action="store_true",
        help="Include non-superinvestor managers. Default is superinvestors only.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum stock/date pairs to process.")
    args = parser.parse_args()

    results = backfill(
        periods=_parse_periods(args.periods),
        superinvestor_only=not args.include_all_managers,
        limit=args.limit,
    )
    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(
        " ".join(
            [
                f"processed={len(results)}",
                f"refreshed={counts.get('refreshed', 0)}",
                f"skipped={counts.get('skipped', 0)}",
                f"failed={counts.get('failed', 0)}",
            ]
        )
    )


if __name__ == "__main__":
    main()
