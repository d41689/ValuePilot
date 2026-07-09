"""T1-FU accepted_at production backfill — thin CLI wrapper.

Run ONCE post-deploy (after the T1-FU code is live), in the api container. The
module form puts /code on sys.path so `app` imports:

    docker compose -f docker-compose.prod.yml exec -T api python -m scripts.t1fu_accepted_at_backfill

Why (series-review P2): on a database whose filings predate T1-FU,
`accepted_at` is NULL everywhere. The quarterly ingest job self-heals the
quarters it touches (Phase 2 `backfill_period_routing` fills accepted_at before
the Phase 5 sweep), but admin resolve, controlled reparse, CLI `reparse-all`,
and manual `ingest_holdings` for OLD quarters all reach
`apply_active_filing_policy` without a prior routing pass — and a ≥2 competition
pool with a NULL `accepted_at` trips the missing-acceptance rule, freezing a
group this backfill would have made cleanly rankable.

REQUIRED PRODUCTION ORDER (record in the deploy notes):
  1. Deploy the series code.
  2. Run this script; it must exit 0.
  3. Only then allow sweeps / reparses / admin resolutions / old-quarter jobs.
  4. Then run the T3 attribution rollout + changes / Lens recomputes, if this
     is the first deploy of the whole series.

Logic + the gate live in app.services.thirteenf_accepted_at_rollout so they are
unit-tested (including the no-primary-doc row that an earlier gate let slip).
This wrapper just runs it against a real session and maps the outcome:
  0 -> NO filing has accepted_at IS NULL; authority paths are safe to run.
  1 -> some filing still lacks accepted_at. The report says which and why:
       * without a stored primary doc -> run `ingest_holdings` for that quarter
         (Phase 1 fetches primary docs), then re-run this script;
       * with a stored primary doc    -> the doc carries no ACCEPTANCE-DATETIME
         (or failed to parse); re-fetch the doc, then re-run.
       `at_risk_groups` lists the (manager, period) groups that will actually
       freeze — an empty list means the remaining NULLs are solo filings, which
       the authority resolves without ordering evidence. Proceeding then is an
       explicit operator decision, not a silent pass.
"""
from __future__ import annotations

import sys

from app.core.db import SessionLocal
from app.services.thirteenf_accepted_at_rollout import run_accepted_at_backfill


def main() -> int:
    session = SessionLocal()
    try:
        report = run_accepted_at_backfill(session)
        print(f"backfill_period_routing: {report['routing']}")
        print(
            f"filings={report['total_filings']} "
            f"accepted_at_null={report['null_total']}"
        )

        if not report["failures"]:
            print("\nACCEPTED_AT BACKFILL COMPLETE — authority paths are safe to run.")
            return 0

        print("\nACCEPTED_AT GATE FAILED:")
        for failure in report["failures"]:
            print(f"  - {failure}")

        if report["null_without_primary_doc"]:
            print("\n  NULL, no stored primary doc (run ingest_holdings for the "
                  "quarter, then re-run):")
            for accession in report["null_without_primary_doc"]:
                print(f"    - {accession}")
        if report["null_with_primary_doc"]:
            print("\n  NULL, doc stored but no ACCEPTANCE-DATETIME (re-fetch the "
                  "doc, then re-run):")
            for accession in report["null_with_primary_doc"]:
                print(f"    - {accession}")

        groups = report["at_risk_groups"]
        if groups:
            print(f"\n  WILL FREEZE — {len(groups)} group(s) whose competition "
                  "pool has >=2 members and cannot be ordered:")
            for group in groups:
                print(f"    - manager={group['manager_id']} "
                      f"period={group['quarter_end_date']} "
                      f"pool={group['pool_kind']}({group['pool_size']}) "
                      f"missing_accepted_at={group['pool_missing_accepted_at']}")
        else:
            print("\n  No competition pool is affected: every remaining NULL sits "
                  "in a pool the authority resolves without ordering evidence "
                  "(a solo filing, or a slot an admin already decided).")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
