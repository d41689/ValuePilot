"""T3 combination-attribution production rollout — thin CLI wrapper.

Run ONCE post-deploy (after the T3 code is live), in the api container. The
module form puts /code on sys.path so `app` imports:

    docker compose -f docker-compose.prod.yml exec -T api python -m scripts.t3_attribution_rollout

Logic + verification live in app.services.thirteenf_attribution_rollout (so they
are unit-tested, including failure injection and lock conflicts). This wrapper
just runs it against a real session and maps the outcome to an exit code:
  0  -> all invariants hold;
  1  -> a verification invariant failed;
  2  -> a conflicting job was already running (quiesce jobs and retry).

The recomputes run through the canonical LOCKED JobRun mechanism, so a concurrent
scheduled pipeline / admin job / second rollout is rejected, not raced.
"""
from __future__ import annotations

import sys

from app.core.db import SessionLocal
from app.services.thirteenf_attribution_rollout import (
    RolloutConflictError,
    run_attribution_rollout,
)


def main() -> int:
    session = SessionLocal()
    try:
        try:
            report = run_attribution_rollout(session)
        except RolloutConflictError as exc:
            print(f"ROLLOUT ABORTED — {exc}")
            return 2
        if report["failures"]:
            print("\nROLLOUT VERIFICATION FAILED:")
            for failure in report["failures"]:
                print(f"  - {failure}")
            return 1
        print("\nROLLOUT VERIFICATION PASSED.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
