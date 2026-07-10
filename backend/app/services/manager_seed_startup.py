"""Deploy-time manager seeding — the caller M1 deliberately left unwritten (M2).

`seed_confirmed_managers` (M1) made the seed *function* safe to run on every
deploy: it never writes `match_status` / `status` on an existing row, never
deactivates anyone, refuses rather than guesses when identity is ambiguous, and
serializes itself under a transaction-scoped advisory lock. **The seed expresses
intent; a human expresses lifecycle; the human wins.**

It stops there on purpose. Three decisions belong to whoever calls it, and this
module makes them:

1. **The transaction boundary.** `seed_confirmed_managers` never commits, and
   its `pg_advisory_xact_lock` is released only when the transaction ends. The
   caller opens the session, lets the seed take the lock, commits on success and
   rolls back on failure.

2. **A bad seed file blocks the deploy.** `derive_legacy_manager_type` already
   raises on a typo'd `style_primary` rather than silently defaulting to a wrong
   scoring weight, and a missing file yields an empty report. Both are refused
   here. The nearby precedent — `main.py` wrapping the start-quarter reconcile in
   `try/except` so it "never blocks API startup" — is right for a *reconcile*
   (idempotent, retried next boot) and wrong for a *curated universe*: an API
   that starts with an empty or partial manager universe ingests nothing and
   scores nothing, silently. `test_the_curated_seed_file_is_valid` keeps a bad
   file from ever reaching an image, so failing loud here cannot crash-loop prod
   on anything CI could have caught.

3. **A universe change is a scoring event.** Oracle's Lens requires
   `min_holders = 3` for consensus, so adding a manager to a database that
   already holds 13F data invalidates `ownership_changes`, Lens signals, and
   readiness computed under the old universe. Recomputing that automatically at
   boot would be a large, unbounded write nobody asked for; staying quiet would
   hide a silent change to historical scores. So we name it, loudly, and leave
   the recompute to an operator.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, ContextManager

from sqlalchemy.orm import Session

from app.models.institutions import Holding13F
from app.services.edgar_ingestion import seed_confirmed_managers

logger = logging.getLogger(__name__)

# Enough to act on without turning a boot log into a data dump.
_LOGGED_CIK_CAP = 25


class ManagerSeedError(RuntimeError):
    """The curated manager universe could not be established. Do not start."""


def _database_has_13f_holdings(db: Session) -> bool:
    """Existence check, not a count — prod holds hundreds of thousands of rows."""
    return db.query(Holding13F.id).limit(1).first() is not None


def _capped(ciks: list[str]) -> str:
    head = ciks[:_LOGGED_CIK_CAP]
    suffix = f" (+{len(ciks) - len(head)} more)" if len(ciks) > len(head) else ""
    return ", ".join(head) + suffix


def _require_a_universe(report: dict[str, Any]) -> None:
    if report.get("seed_entries", 0) <= 0:
        raise ManagerSeedError(
            "curated manager seed produced no seed entries — the seed file is "
            "missing or empty. Refusing to start: an API with an empty manager "
            "universe ingests no 13F filings and scores nothing, silently."
        )


def _report_findings(report: dict[str, Any]) -> None:
    """Counts are not actionable; an operator needs the CIKs."""
    if report["ambiguous_name_match"]:
        # A curated manager was NOT created. He is absent from the universe.
        logger.error(
            "Manager seed refused %d create(s): another row normalizes to the "
            "same name. These curated managers are MISSING from the universe "
            "and will not be ingested — resolve the duplicates by hand: %s",
            report["ambiguous_name_match"],
            _capped(report["ambiguous_name_match_ciks"]),
        )
    if report["awaiting_confirmation"]:
        # ingest_quarter_index selects on match_status == 'confirmed'.
        logger.warning(
            "Manager seed left %d manager(s) unconfirmed; they are in the seed "
            "file but will NOT be ingested until a human confirms them in the "
            "admin Managers page: %s",
            report["awaiting_confirmation"],
            _capped(report["awaiting_confirmation_ciks"]),
        )
    if report["skipped_human_decided"]:
        logger.info(
            "Manager seed skipped %d human-decided manager(s) (retired / revoked "
            "/ rejected); the human wins: %s",
            report["skipped_human_decided"],
            _capped(report["skipped_human_decided_ciks"]),
        )
    if report["skipped_needs_review"]:
        logger.info(
            "Manager seed skipped %d manager(s) parked in needs_review: %s",
            report["skipped_needs_review"],
            _capped(report["skipped_needs_review_ciks"]),
        )


def _note_universe_change(db: Session, report: dict[str, Any]) -> bool:
    """True when this deploy widened an already-scored manager universe."""
    if not report["created"]:
        return False
    if not _database_has_13f_holdings(db):
        # Day 0. Managers created, but there is no prior scoring to invalidate.
        return False

    logger.warning(
        "MANAGER UNIVERSE CHANGED: this deploy added %d manager(s) to a database "
        "that already holds 13F data. Oracle's Lens consensus depends on the "
        "universe (min_holders=3), so existing ownership_changes, Lens signals, "
        "and readiness metrics were computed under the OLD universe and are now "
        "stale. No recompute was triggered — an operator must re-run "
        "compute_ownership_changes and oracles_lens_score_backfill for the "
        "affected quarters. Created: %s",
        report["created"],
        _capped(report.get("created_ciks") or []),
    )
    return True


def run_startup_manager_seed(
    session_factory: Callable[[], ContextManager[Session]],
) -> dict[str, Any]:
    """Seed the curated manager universe. Raises `ManagerSeedError` to stop boot.

    Returns the M1 diff report plus a `universe_changed` flag.
    """
    with session_factory() as db:
        try:
            report = seed_confirmed_managers(db)
            _require_a_universe(report)
            report["universe_changed"] = _note_universe_change(db, report)
            db.commit()
        except ManagerSeedError:
            db.rollback()
            raise
        except Exception as exc:  # noqa: BLE001 — re-raised as ManagerSeedError
            db.rollback()
            raise ManagerSeedError(f"curated manager seed failed: {exc}") from exc

    _report_findings(report)
    logger.info(
        "Manager seed complete: entries=%d created=%d updated=%d "
        "skipped_human_decided=%d skipped_needs_review=%d "
        "awaiting_confirmation=%d ambiguous_name_match=%d universe_changed=%s",
        report["seed_entries"], report["created"], report["updated"],
        report["skipped_human_decided"], report["skipped_needs_review"],
        report["awaiting_confirmation"], report["ambiguous_name_match"],
        report["universe_changed"],
    )
    return report
