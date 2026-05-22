"""Apply manager_type classifications through the audited service.

Reads a decisions JSON (argv positional) — the output of
classify_managers_decide.py — and applies each row via
app.services.manager_type_review.update_manager_type, which writes the
manager_type column and an institution_manager_type_review_events audit row
in one transaction. reviewed_by_user_id is left NULL: this is a machine
first pass, not a human review (the note says so).

Dry-run by default; pass --apply to write. Idempotent — a re-run no-ops on
any row whose value already matches (no duplicate audit row).

Run inside the prod api container (it has the prod DATABASE_URL):

    docker cp decisions.json valuepilot-prod-api-1:/tmp/decisions.json
    docker exec -i valuepilot-prod-api-1 \\
        python - /tmp/decisions.json --apply < classify_managers_apply.py
"""
from __future__ import annotations

import json
import sys

from app.core.db import SessionLocal
from app.models.institutions import InstitutionManager
from app.services.manager_type_review import (
    ManagerTypeUpdateError,
    update_manager_type,
)


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "-"]
    apply = "--apply" in args
    paths = [a for a in args if not a.startswith("--")]
    if not paths:
        print("usage: <decisions.json> [--apply]", file=sys.stderr)
        sys.exit(2)
    decisions = json.load(open(paths[0]))

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"=== manager_type classification — {mode} — {len(decisions)} rows ===")

    session = SessionLocal()
    changed = unchanged = failed = 0
    try:
        if not apply:
            known = {
                mid for (mid,) in session.query(InstitutionManager.id).all()
            }
            for d in decisions:
                mid = d["manager_id"]
                flag = "" if mid in known else "  <-- MANAGER ID NOT FOUND"
                print(
                    f"  [dry-run] {mid:>3} "
                    f"{d['canonical_name'][:38]:<38} -> {d['manager_type']}{flag}"
                )
            missing = [d["manager_id"] for d in decisions if d["manager_id"] not in known]
            print(
                f"=== dry-run: {len(decisions)} rows, "
                f"{len(missing)} unknown ids; re-run with --apply to write ==="
            )
            return

        for d in decisions:
            mid = d["manager_id"]
            mtype = d["manager_type"]
            try:
                result = update_manager_type(
                    session,
                    mid,
                    new_manager_type=mtype,
                    reviewer_user_id=None,
                    note=d["note"],
                    evidence_json=d.get("evidence_json"),
                )
            except ManagerTypeUpdateError as exc:
                failed += 1
                print(f"  FAIL {mid:>3} {d['canonical_name'][:34]:<34} {exc}")
                continue
            if result["changed"]:
                changed += 1
                print(
                    f"  set  {mid:>3} {d['canonical_name'][:34]:<34} "
                    f"{result['old_manager_type']} -> {mtype} "
                    f"(audit #{result['audit_event_id']})"
                )
            else:
                unchanged += 1
                print(
                    f"  noop {mid:>3} {d['canonical_name'][:34]:<34} "
                    f"already {mtype}"
                )
        print(
            f"=== done: {changed} changed, {unchanged} unchanged, "
            f"{failed} failed ==="
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
