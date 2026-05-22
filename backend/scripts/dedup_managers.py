"""Hard-delete the 4 duplicate institution managers.

Four firms each exist as two `institution_managers` rows under different CIKs;
the duplicate of each pair was created by the 2026-05-20 seed-confirmed-managers
run and carries no 13F data. This deletes the duplicate (and its single
manager_type audit row) and keeps the row with the live data / active CIK.

See docs/tasks/2026-05-21_dedup-duplicate-managers.md.

Safety: a pre-flight check verifies each delete target has zero rows in every
FK table except `institution_manager_type_review_events`. If anything else
depends on it the run aborts before writing. The delete is one transaction.

Dry-run by default; pass --apply to delete. Run inside the prod api container:

    docker exec -i valuepilot-prod-api-1 python - --apply < dedup_managers.py
"""
from __future__ import annotations

import sys

from app.core.db import SessionLocal
from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    InstitutionManagerTypeReviewEvent,
    OwnershipChange13F,
    QualityFinding13F,
)
from app.models.oracles_lens import OraclesLensScoreComponent

# (delete_id, keep_id, firm) — the duplicate to remove, the row that survives.
PAIRS = [
    (84, 18, "Abrams Capital"),
    (81, 15, "Akre Capital"),
    (83, 46, "Himalaya Capital"),
    (63, 85, "Baupost Group"),
]


def _deps(session, mid: int) -> dict[str, int]:
    """Count every FK reference to a manager EXCEPT its manager_type audit
    rows (those are deleted with it)."""
    return {
        "filings": session.query(Filing13F).filter_by(manager_id=mid).count(),
        "holdings": session.query(Holding13F).filter_by(manager_id=mid).count(),
        "ownership_changes": session.query(OwnershipChange13F).filter_by(manager_id=mid).count(),
        "cik_review_events": session.query(InstitutionManagerCikReviewEvent).filter_by(manager_id=mid).count(),
        "score_components": session.query(OraclesLensScoreComponent).filter_by(manager_id=mid).count(),
        "quality_findings": session.query(QualityFinding13F).filter_by(manager_id=mid).count(),
        "children": session.query(InstitutionManager).filter_by(parent_manager_id=mid).count(),
    }


def main() -> None:
    apply = "--apply" in sys.argv
    session = SessionLocal()
    try:
        blocked = False
        for del_id, keep_id, firm in PAIRS:
            mgr = session.get(InstitutionManager, del_id)
            keep = session.get(InstitutionManager, keep_id)
            if mgr is None:
                print(f"  SKIP {firm}: id {del_id} already gone")
                continue
            if keep is None:
                print(f"  ABORT {firm}: keep id {keep_id} not found")
                blocked = True
                continue
            offending = {k: v for k, v in _deps(session, del_id).items() if v}
            audit = session.query(InstitutionManagerTypeReviewEvent).filter_by(
                manager_id=del_id
            ).count()
            verdict = "OK" if not offending else f"BLOCKED {offending}"
            if offending:
                blocked = True
            print(
                f"  {firm}: delete id {del_id} (cik {mgr.cik}) -> "
                f"keep id {keep_id} (cik {keep.cik}) | "
                f"manager_type audit rows to delete: {audit} | {verdict}"
            )

        if blocked:
            print("=== ABORTED: a delete target has unexpected dependent rows ===")
            sys.exit(1)
        if not apply:
            print("=== dry-run: re-run with --apply to delete ===")
            return

        deleted = 0
        for del_id, keep_id, firm in PAIRS:
            if session.get(InstitutionManager, del_id) is None:
                continue
            audit = session.query(InstitutionManagerTypeReviewEvent).filter_by(
                manager_id=del_id
            ).delete()
            session.query(InstitutionManager).filter_by(id=del_id).delete()
            deleted += 1
            print(f"  deleted id {del_id} ({firm}) + {audit} audit row(s)")
        session.commit()
        print(f"=== done: {deleted} duplicate managers deleted ===")
    finally:
        session.close()


if __name__ == "__main__":
    main()
