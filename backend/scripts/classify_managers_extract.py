"""Read-only: dump every institution manager + its 13F portfolio behavior.

Feeds the manager_type first-pass classification
(docs/tasks/2026-05-21_manager-type-classification.md). Behavior metrics
mirror what app/services/oracles_lens/manager_signal.py reasons over:
top-10 concentration, holding count, option usage, a turnover proxy
(new positions vs the prior quarter), and a trailing holding-period span.

Run inside the prod api container — it has the prod DATABASE_URL:

    docker exec -i valuepilot-prod-api-1 python - < classify_managers_extract.py

Writes JSON to stdout. Makes no writes.
"""
from __future__ import annotations

import json
from collections import defaultdict

from app.core.db import SessionLocal
from app.models.institutions import Filing13F, Holding13F, InstitutionManager


def _val(h: Holding13F) -> int:
    # value_thousands is NOT NULL on Holding13F and is a single consistent unit
    # (thousands of USD). Concentration is a ratio, so the unit does not matter
    # as long as it is consistent across a filing — hence value_thousands only,
    # never a value_usd-or-value_thousands fallback that could mix units (USD vs
    # thousands) within one filing and distort the weights 1000x.
    return int(h.value_thousands or 0)


def main() -> None:
    session = SessionLocal()
    try:
        managers = (
            session.query(InstitutionManager)
            .order_by(InstitutionManager.id)
            .all()
        )
        out = []
        for m in managers:
            filings = (
                session.query(Filing13F)
                .filter(
                    Filing13F.manager_id == m.id,
                    Filing13F.is_active_for_manager_period.is_(True),
                )
                .order_by(Filing13F.quarter_end_date.asc())
                .all()
            )
            rec: dict = {
                "id": m.id,
                "canonical_name": m.canonical_name,
                "legal_name": m.legal_name,
                "cik": m.cik,
                "manager_type": m.manager_type,
                "is_superinvestor": m.is_superinvestor,
                "status": m.status,
                "dataroma_code": m.dataroma_code,
                "active_filings": len(filings),
                "quarters": [
                    f.quarter_end_date.isoformat() if f.quarter_end_date else None
                    for f in filings
                ],
            }
            if filings:
                latest = filings[-1]
                holds = (
                    session.query(Holding13F)
                    .filter(Holding13F.filing_id == latest.id)
                    .all()
                )
                total = sum(_val(h) for h in holds) or 1
                weights = sorted(
                    (_val(h) / total for h in holds), reverse=True
                )
                top = sorted(holds, key=_val, reverse=True)[:15]
                rec["latest_quarter"] = (
                    latest.quarter_end_date.isoformat()
                    if latest.quarter_end_date
                    else None
                )
                rec["latest_holdings_count"] = len(holds)
                rec["latest_common_count"] = latest.common_holdings_count
                rec["option_positions"] = sum(1 for h in holds if h.put_call)
                rec["top10_concentration"] = round(sum(weights[:10]), 4)
                rec["top_holdings"] = [
                    {
                        "issuer": h.issuer_name,
                        "weight": round(_val(h) / total, 4),
                        "put_call": h.put_call,
                    }
                    for h in top
                ]

                if len(filings) >= 2:
                    prior = filings[-2]
                    prior_cusips = {
                        c
                        for (c,) in session.query(Holding13F.cusip)
                        .filter(Holding13F.filing_id == prior.id)
                        .all()
                    }
                    latest_cusips = {h.cusip for h in holds}
                    if latest_cusips:
                        rec["new_position_fraction_vs_prior_q"] = round(
                            len(latest_cusips - prior_cusips)
                            / len(latest_cusips),
                            4,
                        )

                cusip_quarters: dict[str, set] = defaultdict(set)
                for f in filings:
                    for (c,) in (
                        session.query(Holding13F.cusip)
                        .filter(Holding13F.filing_id == f.id)
                        .all()
                    ):
                        cusip_quarters[c].add(f.quarter_end_date)
                qorder = [f.quarter_end_date for f in filings]
                spans = []
                for c in {h.cusip for h in holds}:
                    span = 0
                    for q in reversed(qorder):
                        if q in cusip_quarters[c]:
                            span += 1
                        else:
                            break
                    spans.append(span)
                if spans:
                    rec["avg_trailing_hold_quarters"] = round(
                        sum(spans) / len(spans), 2
                    )
                    rec["max_trailing_hold_quarters"] = max(spans)
            out.append(rec)
        print(json.dumps(out, indent=1, default=str))
    finally:
        session.close()


if __name__ == "__main__":
    main()
