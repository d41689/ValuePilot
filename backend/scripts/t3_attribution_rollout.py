"""T3 combination-attribution production rollout — idempotent + self-verifying.

Run ONCE post-deploy (after the T3 code is live), in the api container. Use the
module form so /code is on sys.path and `app` imports:

    docker compose -f docker-compose.prod.yml exec -T api python -m scripts.t3_attribution_rollout

Ordered so no product surface is left stale:
  1. backfill holding_attribution under the new rule (SOLE/DFND/OTR -> direct);
  2. recompute ownership_changes for every affected quarter;
  3. recompute Oracle's Lens ONLY after ownership changes complete;
  4. verify: no legacy reported_for_other/shared statuses remain, zero per-manager
     compute failures, and a representative flagship (Berkshire, CIK 0001067983)
     now has direct holdings + real changes.

Idempotent: the backfill and both recomputes replace/upsert, so re-running is
safe. Exits non-zero if any verification check fails (so a deploy runbook / CI
step can gate on it). Read-only DB access is never assumed — writes are committed
per step.
"""
from __future__ import annotations

import sys

from sqlalchemy import text

from app.core.db import SessionLocal
from app.services.thirteenf_admin_dashboard import execute_job_payload
from app.services.thirteenf_holdings_ingest import backfill_holding_attribution

BERKSHIRE_CIK = "0001067983"


def main() -> int:
    session = SessionLocal()
    failures: list[str] = []
    try:
        # 1. Attribution backfill.
        reattributed = backfill_holding_attribution(session)
        session.commit()
        print(f"[1/4] re-attributed holdings: {reattributed}")

        quarters = [
            row[0]
            for row in session.execute(
                text(
                    "SELECT DISTINCT report_quarter FROM filings_13f "
                    "WHERE report_quarter IS NOT NULL ORDER BY report_quarter"
                )
            ).fetchall()
        ]

        # 2. Ownership-change recompute per quarter.
        change_failures = 0
        for quarter in quarters:
            summary = execute_job_payload(session, "compute_ownership_changes", {"quarter": quarter})
            session.commit()
            change_failures += int(summary.get("failure_count", 0))
            print(
                f"[2/4] ownership_changes {quarter}: status={summary['status']} "
                f"rows={summary['rows_created']} failures={summary['failure_count']}"
            )
        if change_failures:
            failures.append(f"ownership_changes recompute had {change_failures} per-manager failures")

        # 3. Oracle's Lens recompute — AFTER ownership changes.
        for quarter in quarters:
            summary = execute_job_payload(session, "oracles_lens_score_backfill", {"quarter": quarter})
            session.commit()
            print(f"[3/4] oracles_lens {quarter}: status={summary.get('status')} scored={summary.get('filings_scored')}")

        # 4. Verify.
        legacy = session.execute(
            text(
                "SELECT COUNT(*) FROM holdings_13f "
                "WHERE holding_attribution_status IN ('reported_for_other', 'shared')"
            )
        ).scalar()
        if legacy:
            failures.append(f"{legacy} holdings still at legacy reported_for_other/shared status")

        zero_direct = session.execute(
            text(
                "SELECT COUNT(*) FROM (SELECT manager_id FROM holdings_13f GROUP BY 1 "
                "HAVING COUNT(*) FILTER (WHERE holding_attribution_status='direct')=0) x"
            )
        ).scalar()
        print(f"[4/4] managers with zero direct holdings: {zero_direct}")

        berk = session.execute(
            text(
                "SELECT h.direct, c.real_changes FROM "
                "(SELECT COUNT(*) direct FROM holdings_13f hh JOIN institution_managers im ON im.id=hh.manager_id "
                " WHERE im.cik=:cik AND hh.holding_attribution_status='direct') h, "
                "(SELECT COUNT(*) real_changes FROM ownership_changes oc JOIN institution_managers im ON im.id=oc.manager_id "
                " WHERE im.cik=:cik AND oc.confidence_level<>'unavailable') c"
            ),
            {"cik": BERKSHIRE_CIK},
        ).fetchone()
        direct, real_changes = (berk[0], berk[1]) if berk else (0, 0)
        print(f"[4/4] flagship Berkshire: direct_holdings={direct} real_changes={real_changes}")
        if direct == 0:
            failures.append("flagship Berkshire has zero direct holdings after rollout")
        if real_changes == 0:
            failures.append("flagship Berkshire has zero real ownership changes after rollout")

        if failures:
            print("\nROLLOUT VERIFICATION FAILED:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("\nROLLOUT VERIFICATION PASSED.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
