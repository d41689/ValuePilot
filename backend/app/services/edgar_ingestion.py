"""EDGAR 13F ingestion orchestration.

Implements the three-step pipeline from the plan:
  Step 0 – seed confirmed managers (offline, from confirmed_managers.json)
           + on-demand sync_dataroma_managers (read-only diff)
  Step 1 – fetch quarter form.idx and upsert filing metadata
  Step 2 – fetch + parse infotable.xml and write holdings
"""
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dataroma.client import DataromaClient
from app.dataroma.parsers.managers import DataromaManager, parse_managers
from app.edgar.client import EdgarClient
from app.edgar.fetcher import fetch_and_store, load_body
from app.edgar.parsers.form_idx import (
    FormIdxRecord,
    form_idx_url,
    next_quarter_label,
    parse_form_idx,
    quarter_to_year_qtr,
)
from app.edgar.parsers.infotable import compute_total_value, parse_infotable
from app.edgar.parsers.primary_doc import parse_primary_doc
from app.edgar.parsers.submissions import parse_submissions, submissions_url
from app.models.institutions import (
    CusipTickerMap,
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    RawSourceDocument,
)
from app.services.oracles_lens.manager_style import derive_legacy_manager_type

logger = logging.getLogger(__name__)

_RECONCILE_THRESHOLD = 0.001  # 0.1%


# ---------------------------------------------------------------------------
# Name normalization helpers
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Lowercase, strip accents, collapse whitespace, remove common suffixes."""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode()
    name = name.lower()
    name = re.sub(r"\b(inc|llc|lp|ltd|llp|corp|co|group|management|capital|advisors?|associates?|partners?|holdings?|fund|investments?)\b", "", name)
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _name_score(a: str, b: str) -> float:
    """Containment similarity: fraction of the smaller word set covered by the larger.

    Filters single-char tokens so "L.P." → {"l","p"} doesn't pollute the score.
    'Pershing Square' vs 'Pershing Square Capital Management, L.P.' → 1.0
    """
    wa = {w for w in _normalize_name(a).split() if len(w) > 1}
    wb = {w for w in _normalize_name(b).split() if len(w) > 1}
    if not wa or not wb:
        return 0.0
    smaller = wa if len(wa) <= len(wb) else wb
    larger = wb if len(wa) <= len(wb) else wa
    return len(smaller & larger) / len(smaller)


# ---------------------------------------------------------------------------
# Step 0 – whitelist bootstrap
# ---------------------------------------------------------------------------

# Lifecycle states a human owns. Seeding must not touch these rows at all.
#   status:       PRD lifecycle field; admin "retire" writes inactive,
#                 a rejected CIK match derives ignored.
#   match_status: revoked = an audited, note-required decision that this CIK
#                 does NOT belong to this manager (revoke_confirmed_cik also
#                 nulls the CIK); rejected / inactive likewise.
_DEACTIVATED_MANAGER_STATUSES = frozenset({"inactive", "ignored"})
_HUMAN_DECIDED_MATCH_STATUSES = frozenset({"inactive", "revoked", "rejected"})
# An operator explicitly parked this row (admin PATCH sets status +
# match_status). Distinct from `awaiting_confirmation`, which merely means
# "the seed knows him but nobody has confirmed him yet" — the operator action
# differs, so the buckets must differ.
_NEEDS_REVIEW_STATES = frozenset({"needs_review"})


def _human_owns_lifecycle(manager: "InstitutionManager") -> bool:
    return (
        manager.status in _DEACTIVATED_MANAGER_STATUSES
        or manager.match_status in _HUMAN_DECIDED_MATCH_STATUSES
    )


def _human_parked_for_review(manager: "InstitutionManager") -> bool:
    return (
        manager.status in _NEEDS_REVIEW_STATES
        or manager.match_status in _NEEDS_REVIEW_STATES
    )


def _cik_was_revoked_by_a_human(db: Session, cik: str) -> bool:
    """Did an operator revoke exactly this CIK from some manager?

    `revoke_confirmed_cik` is the heaviest decision in this table: it demands a
    note, writes an `InstitutionManagerCikReviewEvent`, and NULLs the CIK —
    meaning "this CIK is not this manager". That NULL also removes the only key
    the seed matched on for the 62 of 82 entries that carry no dataroma_code, so
    a naive re-seed CREATES A DUPLICATE `confirmed` row and defeats the
    revocation entirely.

    The audit trail is the exact, non-fuzzy way to detect it. (An earlier fix
    used a `name_normalized` fallback instead; `_normalize_name` strips
    'capital' / 'management' / 'investments' / … so 35 of the 82 seed names
    collapse to a single token — 'ariel', 'atlantic', 'cas' — and the fallback
    could silently attach a seed CIK to an unrelated manager. Names are now used
    only to REFUSE and report, never to write.)
    """
    return (
        db.query(InstitutionManagerCikReviewEvent.id)
        .filter(InstitutionManagerCikReviewEvent.old_cik == cik)
        .filter(InstitutionManagerCikReviewEvent.event_type == "revoke_confirmed_cik")
        .first()
        is not None
    )


def seed_confirmed_managers(db: Session) -> dict[str, Any]:
    """Seed institution_managers from the curated `confirmed_managers.json`.

    **The seed expresses INTENT; a human expresses LIFECYCLE; the human wins.**
    This function is meant to run on every deploy, so it must never silently
    undo an operator's decision:

    - It **never writes** ``match_status`` or ``status`` on an existing row.
      Re-seeding used to force ``match_status = "confirmed"`` unconditionally,
      which resurrected a retired manager — and worse, left him split-brained:
      ``ingest_quarter_index`` selects on ``match_status == "confirmed"`` while
      daily-sync / readiness / historical-backfill filter ``status ==
      "active"``, and the model's before_update listener only derives ``status``
      when it is NULL/``candidate``. So the row would be ingested into the
      product and Oracle's Lens consensus while missing from the expected-filers
      denominator.
    - A manager whose lifecycle a human decided — retired (``inactive``),
      ``revoked`` (an audited, note-required CIK detachment) or ``rejected`` —
      is skipped entirely; not even his identity fields are refreshed, because
      re-writing ``cik`` would undo the revocation.
    - It **never deactivates** anyone. A manager absent from the JSON is left
      untouched; proposing removals is the Dataroma sync's job, and it only
      ever proposes.
    - A row that exists but is **not yet confirmed** (e.g. a Dataroma candidate
      later added to the JSON) gets its identity/classification refreshed but is
      NOT promoted — a human confirms it. Such rows are reported under
      ``awaiting_confirmation`` so that "I added them to the seed and nothing
      happened" can never be a silent failure.
    - A row an operator explicitly parked in ``needs_review`` is also skipped
      whole (bucket ``skipped_needs_review``): refreshing its name or
      classification mid-review would overwrite the very fields being
      adjudicated.
    - New rows are created ``match_status = "confirmed"``; the model's
      before_insert listener derives ``status = "active"`` from that. This
      implicit dependency is pinned by
      ``test_new_rows_are_active_so_the_universe_is_actually_tracked``.
    - Names are used only to REFUSE and report (``ambiguous_name_match``), never
      to write: 35 of the 82 curated names normalize to a single token, so a
      name-keyed update could attach a curated CIK to an unrelated manager and
      ingest the wrong SEC filer.
    - The whole seed runs under a transaction-scoped advisory lock, so two api
      containers starting at once cannot race the create path into the unique
      ``cik`` index.

    Why it matters: the manager universe is a scoring input — Oracle's Lens
    requires ``min_holders = 3`` for consensus, so a universe that changes
    silently changes historical scores silently.

    Returns a diff report::

        {"seed_entries", "created", "updated", "skipped_human_decided",
         "skipped_needs_review", "awaiting_confirmation",
         "ambiguous_name_match", + the matching *_ciks lists}

    Idempotent: a second run creates nothing and rewrites the same values.
    """
    import json
    import os
    from pathlib import Path

    def _report(**kw: Any) -> dict[str, Any]:
        base = {
            "seed_entries": 0, "created": 0, "updated": 0,
            "skipped_human_decided": 0, "skipped_needs_review": 0,
            "awaiting_confirmation": 0, "ambiguous_name_match": 0,
            "created_ciks": [],
            "skipped_human_decided_ciks": [], "skipped_needs_review_ciks": [],
            "awaiting_confirmation_ciks": [], "ambiguous_name_match_ciks": [],
        }
        base.update(kw)
        return base

    seed_path = Path(__file__).parent / "seed_data" / "confirmed_managers.json"
    if not os.path.exists(seed_path):
        logger.warning("Seed data not found at %s", seed_path)
        return _report()

    with open(seed_path, "r") as f:
        seed_data = json.load(f)

    # Serialize the whole seed. M2 runs this on every deploy, and prod may
    # start more than one api container: two processes would each see "no such
    # manager", both INSERT, and one would die on the unique `cik` index —
    # aborting startup into a `restart: unless-stopped` crash loop. Same
    # mechanism the 13F authority uses (`_acquire_period_lock`). Transaction
    # scoped: released when the caller commits or rolls back.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended('seed_confirmed_managers', 0))")
    )

    created = 0
    created_ciks: list[str] = []
    updated = 0
    skipped_human_decided: list[str] = []
    skipped_needs_review: list[str] = []
    awaiting_confirmation: list[str] = []
    ambiguous_name_match: list[str] = []
    for entry in seed_data:
        dataroma_code = entry.get("dataroma_code")
        cik = entry.get("cik")
        if not cik:
            continue

        # Derive legacy manager_type once per entry; missing
        # style_primary defaults to 'unknown', which derive maps to
        # legacy 'unknown'. Garbage style_primary raises ValueError so
        # a typo in the JSON fails the seed loudly rather than silently
        # defaulting to a wrong weight.
        style_primary = entry.get("style_primary", "unknown")
        legacy_manager_type = derive_legacy_manager_type(style_primary)
        capital_structure = entry.get("capital_structure", "unknown")

        # Match by CIK first (authoritative SEC identifier), then fall back to dataroma_code.
        # Avoids MultipleResultsFound when separate DB records each satisfy one side of an OR.
        existing = db.query(InstitutionManager).filter_by(cik=cik).one_or_none()
        if existing is None and dataroma_code:
            existing = (
                db.query(InstitutionManager)
                .filter_by(dataroma_code=dataroma_code)
                .one_or_none()
            )
        if existing is None and _cik_was_revoked_by_a_human(db, cik):
            # A human detached exactly this CIK, with a note and an audit event.
            # Neither key above can find that manager (revoke NULLs the CIK, and
            # only 20/82 entries carry a dataroma_code) — so without this the
            # create path below would mint a fresh `confirmed` row and undo the
            # revocation. The seed and the operator disagree; the operator wins.
            skipped_human_decided.append(cik)
            continue

        if existing:
            # LIFECYCLE IS THE HUMAN'S. Retired / revoked / rejected rows are
            # skipped WHOLE — touching even their identity fields would be an
            # automated system reaching into a decision it does not own. In
            # particular, writing `existing.cik = cik` on a revoked manager
            # would silently re-attach the very CIK a human detached, leaving
            # the row contradicting its own audit trail.
            if _human_owns_lifecycle(existing):
                skipped_human_decided.append(cik)
                continue
            # Checked AFTER the line above on purpose: a `revoked` row derives
            # status='needs_review', and it belongs in the human-decided bucket.
            # What lands here is a row an operator explicitly PATCHed into
            # needs_review — refreshing its name/classification mid-review would
            # overwrite the very fields the operator is adjudicating.
            if _human_parked_for_review(existing):
                skipped_needs_review.append(cik)
                continue
            # Exists but not yet confirmed (e.g. a Dataroma candidate that was
            # later curated into the JSON). Refresh what the seed owns, but do
            # NOT promote him — a human confirms. Reported so this is visible.
            if existing.match_status != "confirmed":
                awaiting_confirmation.append(cik)

            # Identity + classification only. `match_status` / `status` are
            # deliberately NOT written here (see the docstring).
            existing.cik = cik
            if entry.get("display_name"):
                existing.display_name = entry["display_name"]
            if entry.get("legal_name"):
                existing.legal_name = entry["legal_name"]
                existing.name_normalized = _normalize_name(entry["legal_name"])
            existing.style_primary = style_primary
            existing.capital_structure = capital_structure
            existing.manager_type = legacy_manager_type
            # Optional metadata: only overwrite when the seed entry
            # actually specifies a value, so a sparse re-seed doesn't
            # wipe richer downstream data on existing rows.
            if entry.get("market_cap_focus") is not None:
                existing.market_cap_focus = entry["market_cap_focus"]
            if entry.get("geo_focus") is not None:
                existing.geo_focus = entry["geo_focus"]
            if entry.get("historical_turnover") is not None:
                existing.historical_turnover = entry["historical_turnover"]
            if entry.get("position_concentration_top10_pct") is not None:
                existing.position_concentration_top10_pct = entry[
                    "position_concentration_top10_pct"
                ]
            if entry.get("ideology_tags") is not None:
                existing.ideology_tags = entry["ideology_tags"]
            updated += 1
        else:
            # Before minting a new manager, REFUSE if some row already
            # normalizes to the same name. 35 of the 82 curated names collapse
            # to a single token ('ariel', 'atlantic', 'cas'), so this is not
            # hypothetical. Names are used ONLY to refuse — never to write
            # through — because attaching a curated CIK to the wrong manager
            # would ingest and score the wrong SEC filer.
            #
            # Refusing (rather than minting a second row) is the conservative
            # default, and it also covers a `revoked` manager whose audit event
            # is missing — legacy rows, or a manual DB edit — for whom
            # `_cik_was_revoked_by_a_human` returns False. When the seed and the
            # database disagree about who someone is, an automated writer should
            # do nothing and name the conflict.
            normalized = _normalize_name(entry.get("legal_name") or entry.get("display_name"))
            if normalized and (
                db.query(InstitutionManager.id)
                .filter(InstitutionManager.name_normalized == normalized)
                .first()
            ):
                ambiguous_name_match.append(cik)
                continue

            # Create new confirmed record with V2 classification
            record = InstitutionManager(
                cik=cik,
                legal_name=entry.get("legal_name") or entry.get("display_name"),
                display_name=entry.get("display_name"),
                name_normalized=_normalize_name(entry.get("legal_name") or entry.get("display_name")),
                dataroma_code=dataroma_code,
                match_status="confirmed",
                is_superinvestor=True,
                dataroma_synced_at=datetime.now(timezone.utc),
                style_primary=style_primary,
                capital_structure=capital_structure,
                manager_type=legacy_manager_type,
                market_cap_focus=entry.get("market_cap_focus"),
                geo_focus=entry.get("geo_focus"),
                historical_turnover=entry.get("historical_turnover"),
                position_concentration_top10_pct=entry.get(
                    "position_concentration_top10_pct"
                ),
                ideology_tags=entry.get("ideology_tags"),
            )
            db.add(record)
            created += 1
            created_ciks.append(cik)

    report = {
        "seed_entries": len(seed_data),
        "created": created,
        "created_ciks": created_ciks,
        "updated": updated,
        "skipped_human_decided": len(skipped_human_decided),
        "skipped_needs_review": len(skipped_needs_review),
        "awaiting_confirmation": len(awaiting_confirmation),
        "ambiguous_name_match": len(ambiguous_name_match),
        "skipped_human_decided_ciks": skipped_human_decided,
        "skipped_needs_review_ciks": skipped_needs_review,
        "awaiting_confirmation_ciks": awaiting_confirmation,
        "ambiguous_name_match_ciks": ambiguous_name_match,
    }
    logger.info(
        "seed_confirmed_managers: entries=%d created=%d updated=%d "
        "skipped_human_decided=%d skipped_needs_review=%d "
        "awaiting_confirmation=%d ambiguous_name_match=%d",
        report["seed_entries"], created, updated,
        report["skipped_human_decided"], report["skipped_needs_review"],
        report["awaiting_confirmation"], report["ambiguous_name_match"],
    )
    return report


def seed_pending_cik_review_fixture(db: Session) -> int:
    """Seed deterministic candidate managers for admin CIK review QA.

    This is intentionally separate from confirmed-manager seeding so the fixture
    never expands the ingestion whitelist without an explicit admin review.
    """
    import json
    import os
    from pathlib import Path

    seed_path = Path(__file__).parent / "seed_data" / "pending_cik_review_fixture.json"
    if not os.path.exists(seed_path):
        logger.warning("Pending CIK fixture seed not found at %s", seed_path)
        return 0

    with open(seed_path, "r") as f:
        seed_data = json.load(f)

    updated = 0
    for entry in seed_data:
        dataroma_code = entry.get("dataroma_code")
        candidate_cik = entry.get("candidate_cik")
        legal_name = entry.get("legal_name") or entry.get("display_name")
        if not dataroma_code or not candidate_cik or not legal_name:
            continue

        manager = (
            db.query(InstitutionManager)
            .filter_by(dataroma_code=dataroma_code)
            .one_or_none()
        )
        if manager is None:
            manager = InstitutionManager(
                cik=None,
                legal_name=legal_name,
                display_name=entry.get("display_name"),
                name_normalized=_normalize_name(legal_name),
                dataroma_code=dataroma_code,
                match_status="candidate",
                is_superinvestor=True,
                dataroma_synced_at=datetime.now(timezone.utc),
            )
            db.add(manager)
        else:
            manager.cik = None
            manager.legal_name = legal_name
            manager.display_name = entry.get("display_name")
            manager.name_normalized = _normalize_name(legal_name)
            manager.match_status = "candidate"
            manager.is_superinvestor = True

        manager.candidate_cik = candidate_cik
        manager.candidate_legal_name = entry.get("candidate_legal_name")
        manager.candidate_similarity_score = entry.get("candidate_similarity_score")
        manager.candidate_source = entry.get("candidate_source") or "qa_fixture"
        manager.candidate_evidence_url = entry.get("candidate_evidence_url")
        manager.candidate_found_at = datetime.now(timezone.utc)
        manager.reviewed_by_user_id = None
        manager.reviewed_at = None
        manager.review_note = None
        updated += 1

    db.flush()
    return updated


# ---------------------------------------------------------------------------
# Dataroma sync (decoupled from bootstrap as of
# docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md)
#
# Bootstrap now means "load the canonical V2-classified universe from
# confirmed_managers.json" (see ``seed_confirmed_managers`` above) and
# never touches the network. Dataroma is only consulted on demand when
# an admin presses "Sync with Dataroma" on the Managers page to look
# for *new* names Dataroma started tracking. The diff is returned for
# admin review; no rows are written by ``sync_dataroma_managers``
# itself — that's ``add_dataroma_candidates`` below, called only when
# the admin clicks Add.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataromaSyncEntry:
    """Single entry in a Dataroma sync diff. Used uniformly across
    new / known / dropped buckets; ``institution_manager_id`` is set
    only for known/dropped entries (which already exist in our DB).
    """

    dataroma_code: str
    name: str
    institution_manager_id: Optional[int] = None


@dataclass(frozen=True)
class DataromaSyncDiff:
    new: list[DataromaSyncEntry]
    known: list[DataromaSyncEntry]
    dropped: list[DataromaSyncEntry]
    fetched_at: datetime

    def to_summary_dict(self, sample_size: int | None = 25) -> dict:
        """JSON shape used for both ``JobRun.summary_json`` storage and the
        synchronous admin endpoint response.

        ``sample_size`` semantics:
        - integer (default 25): cap each ``*_sample`` list at this many
          entries. Used by the job-system path where ``JobRun.summary_json``
          must stay small.
        - ``None``: no cap — return the full diff. Used by the synchronous
          ``/managers/dataroma-sync`` endpoint so the admin UI can render
          (and let the user select) every new Dataroma entry, not just the
          first 25. The full Dataroma universe is currently ~80–100 rows
          so the unbounded response stays well-bounded in practice.
        """
        def _sample(entries: list[DataromaSyncEntry]) -> list[dict]:
            sliced = entries if sample_size is None else entries[:sample_size]
            return [
                {
                    "dataroma_code": e.dataroma_code,
                    "name": e.name,
                    "institution_manager_id": e.institution_manager_id,
                }
                for e in sliced
            ]

        return {
            "fetched_at": self.fetched_at.isoformat(),
            "new_count": len(self.new),
            "known_count": len(self.known),
            "dropped_count": len(self.dropped),
            "new_sample": _sample(self.new),
            "known_sample": _sample(self.known),
            "dropped_sample": _sample(self.dropped),
        }


def _fetch_dataroma_managers() -> list[DataromaManager]:
    """Hit Dataroma through Rate Guard and parse the manager table.

    Extracted into a single seam so tests can monkeypatch this one symbol
    instead of mocking the whole HTTP + Rate Guard chain.
    """
    with DataromaClient() as dc:
        html = dc.get_managers()
    return parse_managers(html)


def sync_dataroma_managers(db: Session) -> DataromaSyncDiff:
    """Diff Dataroma's current manager list against ours; **read-only**.

    Classification rules:
    - ``new``: Dataroma code we have no row for.
    - ``known``: Dataroma code matches an existing manager row by
      ``dataroma_code`` (the authoritative key Dataroma owns).
    - ``dropped``: We hold a manager with a ``dataroma_code`` that
      Dataroma's current payload no longer includes. Managers without
      a ``dataroma_code`` (most V2-seeded ones) are intentionally
      excluded — Dataroma never knew about them, so it can't have
      "dropped" them.

    This function is the read-only twin of ``add_dataroma_candidates``;
    only the latter writes to ``institution_managers``.
    """
    fetched_at = datetime.now(timezone.utc)
    dataroma_entries = _fetch_dataroma_managers()
    logger.info("Dataroma returned %d manager entries", len(dataroma_entries))

    # Index our universe by dataroma_code so the diff is O(N + M)
    # rather than O(N*M). We only care about rows that have a
    # dataroma_code at all.
    by_code: dict[str, InstitutionManager] = {}
    for m in (
        db.query(InstitutionManager)
        .filter(InstitutionManager.dataroma_code.isnot(None))
        .all()
    ):
        by_code[m.dataroma_code] = m

    new_entries: list[DataromaSyncEntry] = []
    known_entries: list[DataromaSyncEntry] = []
    seen_codes: set[str] = set()

    for mgr in dataroma_entries:
        seen_codes.add(mgr.dataroma_code)
        existing = by_code.get(mgr.dataroma_code)
        if existing is None:
            new_entries.append(
                DataromaSyncEntry(dataroma_code=mgr.dataroma_code, name=mgr.name)
            )
        else:
            known_entries.append(
                DataromaSyncEntry(
                    dataroma_code=mgr.dataroma_code,
                    name=mgr.name,
                    institution_manager_id=existing.id,
                )
            )

    dropped_entries: list[DataromaSyncEntry] = [
        DataromaSyncEntry(
            dataroma_code=code,
            name=m.legal_name or m.canonical_name or "",
            institution_manager_id=m.id,
        )
        for code, m in by_code.items()
        if code not in seen_codes
    ]

    return DataromaSyncDiff(
        new=new_entries,
        known=known_entries,
        dropped=dropped_entries,
        fetched_at=fetched_at,
    )


def add_dataroma_candidates(
    db: Session, items: list[DataromaSyncEntry]
) -> dict:
    """Insert a batch of Dataroma-discovered managers as candidates.

    Rows go in with ``match_status='candidate'`` — they still need
    Match CIK + admin classification before they can affect Oracle's
    Lens scoring. V2 fields default to ``unknown`` so the admin's
    next step in the Managers page is "edit manager type".

    Idempotent: skips entries whose ``dataroma_code`` already exists
    anywhere in ``institution_managers`` (regardless of status). Returns
    ``{"added": n, "skipped": n}`` so the calling endpoint can report
    both halves to the admin.

    Concurrency: per-entry inserts run inside a SAVEPOINT so that if a
    concurrent admin add for the same ``dataroma_code`` slipped past
    the TOCTOU check, the resulting ``IntegrityError`` is caught and
    that one entry is counted as skipped instead of poisoning the
    whole batch. The partial UNIQUE index
    ``uq_institution_managers_dataroma_code``
    (WHERE dataroma_code IS NOT NULL, defined in the 13F-ingestion-
    tables migration ``20260423000000``) is what turns a TOCTOU race
    into an IntegrityError rather than a silent duplicate — the
    SAVEPOINT-and-catch defense here is load-bearing on top of that
    DB-level guarantee, not a placeholder.

    Commits on success. The endpoint layer does not commit (per the
    services-own-transactions convention in this repo); add a single
    commit here so the call is durable end-to-end from the FE click.
    """
    now = datetime.now(timezone.utc)
    added = 0
    skipped = 0

    for entry in items:
        code = entry.dataroma_code
        if not code:
            skipped += 1
            continue

        existing = (
            db.query(InstitutionManager).filter_by(dataroma_code=code).one_or_none()
        )
        if existing is not None:
            existing.dataroma_synced_at = now
            existing.last_seen_at = now
            skipped += 1
            continue

        record = InstitutionManager(
            legal_name=entry.name,
            display_name=entry.name,
            name_normalized=_normalize_name(entry.name),
            dataroma_code=code,
            match_status="candidate",
            is_superinvestor=True,
            dataroma_synced_at=now,
            review_note=(
                f"Added from Dataroma sync on {now.date().isoformat()}; "
                f"awaiting Match CIK + V2 classification."
            ),
        )

        sp = db.begin_nested()
        try:
            db.add(record)
            db.flush()
            sp.commit()
            added += 1
        except IntegrityError:
            sp.rollback()
            logger.warning(
                "add_dataroma_candidates: IntegrityError on dataroma_code=%s; "
                "treating as skipped (likely concurrent add).",
                code,
            )
            skipped += 1

    db.commit()
    logger.info(
        "add_dataroma_candidates: added=%d skipped=%d (total submitted=%d)",
        added, skipped, len(items),
    )
    return {"added": added, "skipped": skipped}


# ---------------------------------------------------------------------------
# CIK candidate matching
# ---------------------------------------------------------------------------

def _extract_company_name(dataroma_display_name: str) -> str:
    """Extract searchable company name from Dataroma display names.

    'Bill Ackman - Pershing Square Capital Management' → 'Pershing Square Capital Management'
    'Ariel Investments' → 'Ariel Investments'
    """
    if " - " in dataroma_display_name:
        return dataroma_display_name.split(" - ", 1)[1].strip()
    return dataroma_display_name.strip()


def _parse_display_name(display_name_str: str) -> tuple[str, str]:
    """Parse EDGAR display_names entry like 'Pershing Square Capital Management, L.P.  (CIK 0001336528)'.
    Returns (company_name, cik_padded).
    """
    import re
    m = re.match(r"^(.+?)\s*\(CIK\s+(\d+)\)", display_name_str)
    if m:
        return m.group(1).strip(), m.group(2).zfill(10)
    return display_name_str.strip(), ""


def _submissions_company_name(client: EdgarClient, cik_padded: str) -> str:
    """Fetch entity name from EDGAR submissions API."""
    import json
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    try:
        body = client.get(url)
        return json.loads(body).get("name", "")
    except Exception:
        return ""


def _search_edgar_by_company_name(client: EdgarClient, company_name: str) -> list[tuple[str, str]]:
    """Use EDGAR browse-edgar company name search. Returns [(entity_name, cik_padded), ...].

    Single match: root <company-info> has conformed-name + cik directly.
    Multiple matches: entries have `id: urn:tag:www.sec.gov:cik=XXXXXXXXXX`; we call the
    submissions API to resolve the canonical company name for each CIK.
    """
    import re, urllib.parse, xml.etree.ElementTree as ET

    url = (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        f"?company={urllib.parse.quote(company_name)}"
        "&CIK=&type=13F-HR&dateb=&owner=include&count=10&search_text=&action=getcompany&output=atom"
    )
    body = client.get(url)
    root = ET.fromstring(body)
    NS = "http://www.w3.org/2005/Atom"

    results: list[tuple[str, str]] = []
    seen_cik: set[str] = set()

    def _add(name: str, cik_raw: str) -> None:
        cik = re.sub(r"\D", "", cik_raw).zfill(10)
        if cik and cik not in seen_cik and name:
            seen_cik.add(cik)
            results.append((name.strip(), cik))

    # Case 1: root-level <company-info> (EDGAR resolved to a single entity)
    root_ci = root.find(f"{{{NS}}}company-info")
    if root_ci is not None:
        name_el = root_ci.find(f"{{{NS}}}conformed-name")
        cik_el = root_ci.find(f"{{{NS}}}cik")
        if name_el is not None and cik_el is not None:
            _add(name_el.text or "", cik_el.text or "")

    # Case 2: multiple matches — entries have `id: urn:tag:www.sec.gov:cik=XXXXXXXXXX`
    for entry in root.findall(f".//{{{NS}}}entry"):
        # Try nested company-info first (some EDGAR response variants)
        ci = entry.find(f".//{{{NS}}}company-info")
        if ci is not None:
            name_el = ci.find(f"{{{NS}}}conformed-name")
            cik_el = ci.find(f"{{{NS}}}cik")
            if name_el is not None and cik_el is not None:
                _add(name_el.text or "", cik_el.text or "")
                continue

        # Extract CIK from id field: urn:tag:www.sec.gov:cik=0001336528
        id_el = entry.find(f"{{{NS}}}id")
        if id_el is None or id_el.text is None:
            continue
        m = re.search(r"cik=(\d+)", id_el.text)
        if not m:
            continue
        cik = m.group(1).zfill(10)
        if cik in seen_cik:
            continue
        # Resolve company name via submissions API
        entity_name = _submissions_company_name(client, cik)
        if entity_name:
            _add(entity_name, cik)

    return results


def match_cik_candidates(db: Session, min_score: float = 0.6) -> int:
    """For each seeded manager without CIK, query EDGAR and propose candidates.

    Strategy:
    - Extract company name from Dataroma display name (strip 'Person - ' prefix)
    - Use EDGAR company-name search (browse-edgar) — searches entity names, not filing text
    - Score returned names against extracted company name via Jaccard similarity
    - score ≥ 0.85 → auto-confirm; 0.6–0.85 → candidate for human review

    Returns number of managers updated.
    """
    managers = (
        db.query(InstitutionManager)
        .filter(InstitutionManager.cik.is_(None))
        .filter(InstitutionManager.match_status.in_(["seeded", "candidate"]))
        .all()
    )
    updated = 0
    with EdgarClient() as client:
        for mgr in managers:
            company_name = _extract_company_name(mgr.legal_name)
            evidence_url = _edgar_company_search_url(company_name)
            try:
                candidates = _search_edgar_by_company_name(client, company_name)
            except Exception as exc:
                logger.warning("CIK search failed for %s: %s", company_name, exc)
                continue

            if not candidates:
                logger.debug("No EDGAR results for: %s", company_name)
                continue

            best_score = 0.0
            best_cik = ""
            best_entity = ""

            for entity_name, cik_candidate in candidates:
                score = max(
                    _name_score(company_name, entity_name),
                    _name_score(mgr.legal_name, entity_name),
                )
                if score > best_score:
                    best_score = score
                    best_cik = cik_candidate
                    best_entity = entity_name

            if best_score < min_score:
                logger.debug("No match for %s (best: %s score=%.2f)", company_name, best_entity, best_score)
                continue

            conflict = (
                db.query(InstitutionManager)
                .filter_by(cik=best_cik)
                .filter(InstitutionManager.id != mgr.id)
                .one_or_none()
            )
            if conflict:
                logger.warning("CIK %s already taken by %s, skipping %s", best_cik, conflict.legal_name, mgr.legal_name)
                continue

            if best_score >= 0.85:
                mgr.cik = best_cik
                mgr.legal_name = best_entity
                mgr.match_status = "confirmed"
                logger.info("Confirmed %s → CIK %s (score=%.2f)", best_entity, best_cik, best_score)
            else:
                mgr.match_status = "candidate"
                logger.info("Candidate %s → CIK %s (score=%.2f)", company_name, best_cik, best_score)
            mgr.candidate_cik = best_cik
            mgr.candidate_legal_name = best_entity
            mgr.candidate_similarity_score = best_score
            mgr.candidate_source = "edgar_browse_company"
            mgr.candidate_evidence_url = evidence_url
            mgr.candidate_found_at = datetime.now(timezone.utc)
            updated += 1

    db.flush()
    return updated


def _edgar_company_search_url(company_name: str) -> str:
    import urllib.parse

    return (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        f"?company={urllib.parse.quote(company_name)}"
        "&CIK=&type=13F-HR&dateb=&owner=include&count=10&search_text=&action=getcompany&output=atom"
    )


# ---------------------------------------------------------------------------
# Step 1 – fetch quarter index and ingest filing metadata
# ---------------------------------------------------------------------------

def ingest_quarter_index(
    db: Session,
    quarter: str,
    *,
    cik_whitelist: Optional[set[str]] = None,
) -> int:
    """Fetch form.idx for the given report quarter and write new filings_13f rows.

    `quarter` is a **report quarter** (the period 13F holdings are "as of").
    13Fs are filed within 45 days *after* the quarter ends, so they appear in
    the EDGAR full-index of the *following* calendar quarter — fetch that one.
    Without this translation, requesting report quarter Q would fetch Q's filing
    index, which carries Q-1's holdings (see docs/architecture/parsing.md).

    If cik_whitelist is None, all confirmed managers in institution_managers are used.
    Returns count of new filings inserted.
    """
    filing_quarter = next_quarter_label(quarter)
    year, qtr = quarter_to_year_qtr(filing_quarter)
    url = form_idx_url(year, qtr)

    with EdgarClient() as client:
        idx_doc = fetch_and_store(
            db,
            source_system="edgar",
            document_type="form_idx",
            source_url=url,
            client=client,
        )

    body = load_body(idx_doc)
    records = parse_form_idx(body)
    logger.info("form.idx %s: %d 13F records", quarter, len(records))

    if cik_whitelist is None:
        confirmed = (
            db.query(InstitutionManager.cik)
            .filter(InstitutionManager.match_status == "confirmed")
            .filter(InstitutionManager.cik.isnot(None))
            .all()
        )
        cik_whitelist = {row.cik for row in confirmed}

    manager_by_cik: dict[str, InstitutionManager] = {}
    if cik_whitelist:
        managers = (
            db.query(InstitutionManager)
            .filter(InstitutionManager.cik.in_(cik_whitelist))
            .all()
        )
        manager_by_cik = {m.cik: m for m in managers}

    inserted = 0
    for rec in records:
        cik_padded = rec.cik.zfill(10)
        if cik_padded not in manager_by_cik:
            continue

        manager = manager_by_cik[cik_padded]
        existing = (
            db.query(Filing13F)
            .filter_by(accession_no=rec.accession_no)
            .one_or_none()
        )
        if existing is not None:
            continue

        period = _accession_period_of_report(rec)
        # Clear is_latest_for_period on all existing filings for this group
        # BEFORE inserting to avoid partial-unique-index violation.
        (
            db.query(Filing13F)
            .filter_by(manager_id=manager.id, period_of_report=period)
            .update({"is_latest_for_period": False})
        )
        filing = Filing13F(
            manager_id=manager.id,
            accession_no=rec.accession_no,
            period_of_report=period,
            filed_at=rec.filed_at,
            form_type=rec.form_type,
            version_rank=1,
            is_latest_for_period=False,  # recalculate sets the correct one
        )
        db.add(filing)
        db.flush()
        _recalculate_version_ranks(db, manager.id, period)
        inserted += 1

    db.flush()
    return inserted


def _accession_period_of_report(rec: FormIdxRecord):
    """Use filed_at as a proxy period until the primary doc is parsed."""
    return rec.filed_at


def _parse_period_date(s: str):
    """Parse MM-DD-YYYY or YYYY-MM-DD string from primary doc into a date."""
    from datetime import date as _date
    s = s.strip()
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", s)
    if m:
        return _date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _recalculate_version_ranks(db: Session, manager_id: int, period_of_report) -> None:
    """Recompute version_rank and is_latest_for_period for a (manager, period) group."""
    filings = (
        db.query(Filing13F)
        .filter_by(manager_id=manager_id, period_of_report=period_of_report)
        .order_by(Filing13F.filed_at.asc(), Filing13F.accession_no.asc())
        .all()
    )
    for rank, f in enumerate(filings, start=1):
        f.version_rank = rank
        f.is_latest_for_period = rank == len(filings)


# ---------------------------------------------------------------------------
# Step 2 – fetch + parse infotable for a filing
# ---------------------------------------------------------------------------

_FILING_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_raw}/{filename}"


def _filing_index_url(cik: str, accession_no: str) -> str:
    accession_raw = accession_no.replace("-", "")
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F&dateb=&owner=include&count=40&search_text=&output=atom"


def _filing_doc_list_url(cik: str, accession_no: str) -> str:
    accession_raw = accession_no.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}"
        f"/{accession_raw}/{accession_no}-index.htm"
    )


def ensure_filing_infotable_doc(
    db: Session,
    filing: Filing13F,
    *,
    force_refresh: bool = False,
) -> Optional["RawSourceDocument"]:
    """Idempotently ensure a filing's infotable XML is downloaded and linked.

    If ``filing.raw_infotable_doc_id`` is set, the row is loadable, AND the
    backing file on disk exists, returns the existing RawSourceDocument without
    touching the network. Otherwise resolves primary/infotable URLs on EDGAR,
    fetches both via fetch_and_store (which dedupes by source_url + writes to
    the persistent edgar_raw volume), and sets ``raw_primary_doc_id`` +
    ``raw_infotable_doc_id`` on the filing.

    The on-disk existence check is what makes this self-healing across
    storage-volume wipes: if the DB row exists but the file is gone (e.g.
    actions/checkout cleaned the workspace pre-#48), we promote to a
    force-refresh so fetch_and_store re-fetches and updates body_path.
    Without this, repeated reconcile runs after a wipe just return the
    stale row and leave the disk empty.

    Returns the infotable RawSourceDocument, or None if the filing's manager
    has no confirmed CIK (cannot resolve URLs).

    Use as a prerequisite to ``ingest_if_needed`` from
    ``app.services.thirteenf_holdings_ingest``: ensure XML, then parse.
    """
    from pathlib import Path

    from app.models.institutions import RawSourceDocument

    if not force_refresh and filing.raw_infotable_doc_id:
        existing = db.query(RawSourceDocument).get(filing.raw_infotable_doc_id)
        if existing is not None and Path(existing.body_path).exists():
            primary_doc = (
                db.get(RawSourceDocument, filing.raw_primary_doc_id)
                if filing.raw_primary_doc_id
                else None
            )
            if primary_doc is not None and Path(primary_doc.body_path).exists():
                return existing
        # The DB row exists but body file is missing on disk (or the
        # primary_doc counterpart is). Fall through to refetch.
        force_refresh = True

    manager: InstitutionManager = filing.manager
    if manager is None:
        manager = db.query(InstitutionManager).get(filing.manager_id)
    if manager is None or not (manager.cik or "").strip():
        return None

    cik = (manager.cik or "").lstrip("0")
    accession_raw = filing.accession_no.replace("-", "")

    with EdgarClient() as client:
        infotable_url = _resolve_infotable_url(client, cik, accession_raw, filing.accession_no)
        primary_url = _resolve_primary_doc_url(client, cik, accession_raw, filing.accession_no)

        primary_doc = fetch_and_store(
            db,
            source_system="edgar",
            document_type="primary_doc_xml",
            source_url=primary_url,
            cik=manager.cik,
            accession_no=filing.accession_no,
            client=client,
            force_refresh=force_refresh,
        )
        infotable_doc = fetch_and_store(
            db,
            source_system="edgar",
            document_type="infotable_xml",
            source_url=infotable_url,
            cik=manager.cik,
            accession_no=filing.accession_no,
            client=client,
            force_refresh=force_refresh,
        )

    filing.raw_primary_doc_id = primary_doc.id
    filing.raw_infotable_doc_id = infotable_doc.id
    db.flush()
    return infotable_doc


def ingest_filing_holdings(
    db: Session,
    filing: Filing13F,
    *,
    force_refresh: bool = False,
    replace_holdings: bool = False,
) -> int:
    """Download + parse infotable for one filing. Returns count of holdings inserted.

    replace_holdings=True deletes existing holdings before re-inserting (use for reparse).

    .. deprecated::
        This function uses a destructive "delete and re-insert" pattern that bypasses
        the ParseRun13F audit trail.  Use ``ingest_if_needed`` or ``reparse_accession``
        from ``app.services.thirteenf_holdings_ingest`` instead.
    """
    import warnings
    warnings.warn(
        "ingest_filing_holdings is deprecated. Use thirteenf_holdings_ingest.ingest_if_needed "
        "or thirteenf_holdings_ingest.reparse_accession instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    manager: InstitutionManager = filing.manager
    if manager is None:
        manager = db.query(InstitutionManager).get(filing.manager_id)

    cik = (manager.cik or "").lstrip("0")
    accession_raw = filing.accession_no.replace("-", "")

    # If raw docs are already stored and we're not force-refreshing, skip URL resolution.
    if not force_refresh and filing.raw_infotable_doc_id and filing.raw_primary_doc_id:
        primary_doc = (
            db.query(RawSourceDocument).get(filing.raw_primary_doc_id)
        )
        infotable_doc = (
            db.query(RawSourceDocument).get(filing.raw_infotable_doc_id)
        )
    else:
        with EdgarClient() as client:
            infotable_url = _resolve_infotable_url(client, cik, accession_raw, filing.accession_no)
            primary_url = _resolve_primary_doc_url(client, cik, accession_raw, filing.accession_no)

            primary_doc = fetch_and_store(
                db,
                source_system="edgar",
                document_type="primary_doc_xml",
                source_url=primary_url,
                cik=manager.cik,
                accession_no=filing.accession_no,
                client=client,
                force_refresh=force_refresh,
            )
            infotable_doc = fetch_and_store(
                db,
                source_system="edgar",
                document_type="infotable_xml",
                source_url=infotable_url,
                cik=manager.cik,
                accession_no=filing.accession_no,
                client=client,
                force_refresh=force_refresh,
            )

        filing.raw_primary_doc_id = primary_doc.id
        filing.raw_infotable_doc_id = infotable_doc.id

    try:
        body = load_body(infotable_doc)
        rows = parse_infotable(body)
    except Exception as exc:
        infotable_doc.parse_status = "failed"
        infotable_doc.error_message = str(exc)
        db.flush()
        raise

    if replace_holdings:
        db.query(Holding13F).filter_by(filing_id=filing.id).delete()
        db.flush()

    inserted = 0
    for row in rows:
        if not replace_holdings:
            existing = (
                db.query(Holding13F)
                .filter_by(filing_id=filing.id, row_fingerprint=row.row_fingerprint)
                .one_or_none()
            )
            if existing is not None:
                continue

        holding = Holding13F(
            filing_id=filing.id,
            row_fingerprint=row.row_fingerprint,
            cusip=row.cusip,
            issuer_name=row.issuer_name,
            title_of_class=row.title_of_class,
            value_thousands=row.value_thousands,
            shares=row.shares,
            share_type=row.share_type,
            put_call=row.put_call,
            investment_discretion=row.investment_discretion,
            voting_sole=row.voting_sole,
            voting_shared=row.voting_shared,
            voting_none=row.voting_none,
        )
        db.add(holding)
        inserted += 1

    # Populate reported_total_value_thousands and fix period_of_report from primary doc
    try:
        primary_body = load_body(primary_doc)
        summary = parse_primary_doc(primary_body)

        if not filing.reported_total_value_thousands and summary.table_value_total is not None:
            filing.reported_total_value_thousands = summary.table_value_total

        if summary.period_of_report:
            parsed_period = _parse_period_date(summary.period_of_report)
            if parsed_period and parsed_period != filing.period_of_report:
                old_period = filing.period_of_report
                # Clear is_latest on both old and new period groups before touching
                for period in (old_period, parsed_period):
                    db.query(Filing13F).filter_by(
                        manager_id=filing.manager_id, period_of_report=period
                    ).update({"is_latest_for_period": False})
                filing.period_of_report = parsed_period
                db.flush()
                _recalculate_version_ranks(db, filing.manager_id, parsed_period)
                _recalculate_version_ranks(db, filing.manager_id, old_period)
                logger.info(
                    "Corrected period_of_report for %s: %s → %s",
                    filing.accession_no, old_period, parsed_period,
                )
    except Exception as exc:
        logger.warning("Could not parse primary doc for %s: %s", filing.accession_no, exc)

    # Reconciliation
    computed = compute_total_value(rows)
    filing.computed_total_value_thousands = computed
    if filing.reported_total_value_thousands:
        reported = filing.reported_total_value_thousands
        diff_pct = abs(computed - reported) / max(reported, 1)
        if diff_pct > _RECONCILE_THRESHOLD:
            logger.warning(
                "Reconciliation mismatch for %s: reported=%d computed=%d diff=%.4f%%",
                filing.accession_no,
                reported,
                computed,
                diff_pct * 100,
            )

    infotable_doc.parse_status = "parsed"
    infotable_doc.parsed_at = datetime.now(timezone.utc)
    db.flush()
    return inserted


def _resolve_infotable_url(
    client: EdgarClient, cik: str, accession_raw: str, accession_no: str
) -> str:
    """Try common infotable filenames; fall back to index scan."""
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_raw}"
    candidates = [
        f"{base}/infotable.xml",
        f"{base}/informationtable.xml",
        f"{base}/INFOTABLE.XML",
        f"{base}/form13fInfoTable.xml",
    ]
    for url in candidates:
        try:
            client.head(url)
            return url
        except Exception:
            continue
    # Fall back to index scan
    return _scan_index_for_file(client, cik, accession_raw, accession_no, "infotable")


def _resolve_primary_doc_url(
    client: EdgarClient, cik: str, accession_raw: str, accession_no: str
) -> str:
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_raw}"
    candidates = [
        f"{base}/primary-doc.xml",
        f"{base}/PRIMARY-DOC.XML",
        f"{base}/{accession_no}.txt",
    ]
    for url in candidates:
        try:
            client.head(url)
            return url
        except Exception:
            continue
    return _scan_index_for_file(client, cik, accession_raw, accession_no, "primary")


def _scan_index_for_file(
    client: EdgarClient, cik: str, accession_raw: str, accession_no: str, hint: str
) -> str:
    """Fetch filing index page and extract the relevant document URL."""
    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_raw}/{accession_no}-index.htm"
    )
    try:
        body = client.get(index_url)
    except Exception as exc:
        raise RuntimeError(
            f"Could not locate {hint} document for {accession_no}: {exc}"
        ) from exc

    # Simple regex scan for .xml files in the index
    import re
    pattern = re.compile(
        r'href="(/Archives/edgar/data/[^"]+\.xml)"', re.IGNORECASE
    )
    all_matches = pattern.findall(body.decode("utf-8", errors="replace"))
    # Exclude xslForm paths — those are XSLT-rendered HTML, not machine-readable XML
    matches = [m for m in all_matches if "/xsl" not in m.lower()]
    base = "https://www.sec.gov"
    if hint == "infotable":
        for m in matches:
            basename = m.rsplit("/", 1)[-1].lower()
            if "infotable" in basename or "form13f" in basename:
                return base + m
        # Return last XML if no specific match (often the data file comes last)
        if matches:
            return base + matches[-1]
    else:
        for m in matches:
            if "primary" in m.lower():
                return base + m
        if matches:
            return base + matches[0]
    raise RuntimeError(f"Could not find {hint} XML in filing index for {accession_no}")


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def backfill_quarters(db: Session, num_quarters: int = 4) -> dict[str, int]:
    """Backfill the most recent N usable report quarters.

    Enumerates *report* quarters from the latest one whose 13F filing deadline
    has passed, walking backwards — `ingest_quarter_index` then translates each
    to its (already-started) filing quarter. Starting from the current calendar
    quarter instead would ask EDGAR for a full-index quarter that has not begun.

    Returns dict of report quarter → filings inserted.
    """
    from app.services.thirteenf_admin_dashboard import (
        latest_usable_quarter_label,
        previous_quarter_label,
    )

    quarters: list[str] = []
    q = latest_usable_quarter_label()
    for _ in range(num_quarters):
        quarters.append(q)
        q = previous_quarter_label(q)
    results = {}
    for q in quarters:
        logger.info("Backfilling %s", q)
        try:
            n = ingest_quarter_index(db, q)
            results[q] = n
        except Exception as exc:
            logger.error("Failed to backfill %s: %s", q, exc)
            results[q] = -1
    return results


def _date_to_quarter(d) -> str:
    """Calendar quarter label ("YYYY-Qn") of a date."""
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def next_quarter_label(label: str) -> str:
    """Calendar quarter after ``label`` ("2025-Q4" → "2026-Q1")."""
    year_text, qtr_text = label.upper().split("-Q", 1)
    year, qtr = int(year_text), int(qtr_text)
    return f"{year + 1}-Q1" if qtr == 4 else f"{year}-Q{qtr + 1}"


def previous_quarter_label(label: str) -> str:
    """Calendar quarter before ``label`` ("2026-Q1" → "2025-Q4")."""
    year_text, qtr_text = label.upper().split("-Q", 1)
    year, qtr = int(year_text), int(qtr_text)
    return f"{year - 1}-Q4" if qtr == 1 else f"{year}-Q{qtr - 1}"


def ingest_quarter_for_filing(filing) -> Optional[str]:
    """The one **report** quarter whose ``ingest_holdings`` job claims ``filing``.

    Single source of truth for a rule that ``_ingest_candidate_filings`` expresses
    as a SQL predicate. Stating it twice has now produced two bugs, so state it
    once here and pin the two together with
    ``test_pending_ingest_quarters_matches_the_job_that_claims_each_filing``.

    ``filing`` needs only ``report_quarter`` and ``period_of_report``.

    * **Routed** — ``report_quarter`` is set, so it *is* the answer.
      ``backfill_period_routing`` writes it together with the true
      ``period_of_report``, and the daily-sync path
      (``ingest_accession_filing_detail``) writes it while deliberately leaving
      ``raw_infotable_doc_id`` NULL: that job fetches the primary doc and routes
      the period, never the infotable. Such a filing is routed AND un-ingested,
      and it stays that way until some ``ingest_holdings`` run parses its
      holdings.
    * **Un-routed** — ``period_of_report`` is only a proxy equal to ``filed_at``,
      stamped at index time before any document is read. A 13F for report quarter
      Q is filed within 45 days after Q ends, so the proxy lands in Q+1; translate
      it back.

    Subtracting a quarter from a *routed* filing's period — which is what this
    rule used to do to every un-ingested row — sends the CLI to a quarter that
    selects nothing, and it reports a clean zero (external review, round 2).
    """
    if filing.report_quarter:
        return filing.report_quarter
    if filing.period_of_report is None:
        return None
    return previous_quarter_label(_date_to_quarter(filing.period_of_report))


def pending_ingest_quarters(db: Session) -> list[str]:
    """**Report** quarters that still have un-ingested 13F filings.

    A filing is un-ingested while ``raw_infotable_doc_id IS NULL`` — its infotable
    has not been fetched or parsed. Each such filing is claimed by exactly one
    ``ingest_holdings`` job; :func:`ingest_quarter_for_filing` says which.

    Idempotent: once ingested a filing has ``raw_infotable_doc_id`` set and drops
    out of the pool.
    """
    rows = (
        db.query(Filing13F.report_quarter, Filing13F.period_of_report)
        .filter(Filing13F.raw_infotable_doc_id.is_(None))
        .filter(
            or_(
                Filing13F.report_quarter.isnot(None),
                Filing13F.period_of_report.isnot(None),
            )
        )
        .distinct()
        .all()
    )
    quarters = {ingest_quarter_for_filing(row) for row in rows}
    return sorted(q for q in quarters if q)


def ingest_pending_holdings(db: Session, *, quarters=None, ingest_fn=None, log=None) -> dict:
    """Ingest un-ingested filings via the modern ``ingest_holdings`` job.

    Groups pending filings by :func:`pending_ingest_quarters` and delegates each
    quarter to the job path (``ingest_if_needed`` → ParseRun-backed, product
    visible, with Phase-4 heal + solo-HR activation), replacing the legacy
    ``ingest_filing_holdings`` calls the CLI used to make (which wrote
    product-invisible ``parse_run_id = NULL`` holdings — F6).

    ``quarters`` — optional iterable of calendar-quarter labels to restrict to.
    ``None`` processes every pending quarter; ``backfill`` passes the quarters it
    is responsible for so ``--quarters N`` stays bounded and a permanently-stuck
    filing (e.g. a manager with no confirmed CIK, whose ``raw_infotable_doc_id``
    never gets set) can't drag every historical quarter into each run.

    Per-quarter failures are isolated: a raising ``ingest_fn`` is caught, the
    session rolled back, the error recorded as ``{"error": ...}`` in that
    quarter's summary, and the loop continues — one bad quarter can never
    abandon the healthy ones. The default ``ingest_fn`` runs through the locked
    job runner, which never raises and returns a ``conflict`` / ``failed``
    status with an ``error`` key instead; those surface the same way. ``ingest_fn``
    is injectable for tests.

    Returns ``{quarter: result}`` where each result is the locked-job stage dict
    (``stage`` / ``summary`` / optional ``error``) or the injected fn's return.
    """
    if ingest_fn is None:
        from app.services.thirteenf_admin_dashboard import run_locked_job

        def ingest_fn(quarter: str) -> dict:
            # Locked runner: honors ingest_holdings:{quarter}, so a CLI backfill
            # won't run an untracked second copy against a scheduled ingest.
            return run_locked_job(db, "ingest_holdings", {"quarter": quarter}, trigger_source="cli")

    targets = pending_ingest_quarters(db)
    if quarters is not None:
        allowed = {str(q).upper() for q in quarters}
        targets = [q for q in targets if q.upper() in allowed]

    summaries: dict = {}
    for quarter in targets:
        try:
            summaries[quarter] = ingest_fn(quarter)
        except Exception as exc:  # noqa: BLE001 — isolate one quarter's failure
            db.rollback()
            logger.error("ingest_holdings %s failed: %s", quarter, exc)
            summaries[quarter] = {"error": str(exc)}
        if log is not None:
            log(f"{quarter}: {summaries[quarter]}")
    return summaries


def backfill_period_of_report(db: Session) -> int:
    """Thin compatibility wrapper around ``backfill_period_routing``.

    Pre-existing callers passed nothing extra; the routing version is a
    strict superset (it also populates quarter_end_date / report_quarter /
    official_filing_deadline). Returns the count of period_of_report
    changes for backwards compatibility with existing call sites.
    """
    summary = backfill_period_routing(db)
    return summary["period_changed"]


def backfill_period_routing(db: Session, *, filings=None) -> dict[str, int]:
    """Populate Filing13F.period_of_report / quarter_end_date / report_quarter
    / official_filing_deadline from stored primary_doc XML.

    Called as the prerequisite to bulk holdings parsing and Oracle's Lens
    scoring. The fetch_quarter_index path inserts each Filing13F with
    period_of_report=filed_at (a proxy) and quarter_end_date / report_quarter
    NULL — the real quarter-end lives in the primary_doc XML's
    periodOfReport element, which is only available after
    ensure_filing_infotable_doc fetches it. Without correct quarter_end_date,
    Oracle's Lens computes universe_size=0 for every period.

    Idempotent: filings already routed correctly are skipped. Safe to run
    multiple times.

    Args:
        db: SQLAlchemy session.
        filings: optional iterable of Filing13F to process. If None, walks
            every Filing13F with raw_primary_doc_id set.

    Returns:
        ``{"period_changed": N, "quarter_end_added": M, "report_quarter_added": K}``
    """
    from app.edgar.fetcher import load_body
    from app.models.institutions import Filing13F, RawSourceDocument
    from app.services.thirteenf_filing_detail import (
        route_period,
        calculate_official_filing_deadline,
        merge_accepted_at,
    )

    if filings is None:
        filings = (
            db.query(Filing13F)
            .filter(Filing13F.raw_primary_doc_id.isnot(None))
            .all()
        )

    # Pass 1: collect per-filing corrections from the primary_doc.
    # period_changes: list of (filing, old_period, new_period) — drives the
    # is_latest_for_period dance.
    # other_changes: list of (filing, new_quarter_end, new_report_quarter)
    # — applied independently; no FK/unique-constraint coupling.
    period_changes: list[tuple] = []
    other_changes: list[tuple] = []
    # Degraded-routing visibility (external review R2-P1): route_period can
    # return parse_status needs_review / failed for periods that are missing,
    # invalid, or too far from a quarter end. Count them, log them, and stamp
    # the detail onto Filing13F.parse_warning / parse_error so the outcome is
    # not silent. The counts are returned so the caller can mark the stage
    # partial_success.
    needs_review_count = 0
    failed_count = 0
    accepted_at_filled = 0
    for filing in filings:
        if filing.raw_primary_doc_id is None:
            continue
        doc = db.get(RawSourceDocument, filing.raw_primary_doc_id)
        if doc is None:
            continue
        try:
            body = load_body(doc)
            summary = parse_primary_doc(body)
        except Exception as exc:
            logger.warning("backfill_period_routing: %s: %s", filing.accession_no, exc)
            continue

        # T1-FU: fill accepted_at from the primary doc's <ACCEPTANCE-DATETIME>
        # BEFORE route_period reads it. The bulk path never wrote it (all 373
        # real filings NULL), degrading active-filing ranking to accession_no
        # and starving route_period of the real acceptance date. Idempotent;
        # this loop doubles as the one-time backfill over stored docs.
        # merge_accepted_at: never erases a known value with NULL; a non-NULL
        # re-parse propagates parser corrections (e.g. the Eastern→UTC fix).
        if merge_accepted_at(filing, summary.accepted_at):
            accepted_at_filled += 1

        if not summary.period_of_report:
            continue

        routing = route_period(
            summary.period_of_report,
            form_type=filing.form_type,
            accepted_at=filing.accepted_at,
            fallback_period=filing.period_of_report,
        )

        if routing.parse_status == "needs_review":
            needs_review_count += 1
            filing.parse_warning = routing.parse_warning
            logger.warning(
                "backfill_period_routing: %s routing needs_review (%s)",
                filing.accession_no, routing.parse_warning,
            )
        elif routing.parse_status == "failed":
            failed_count += 1
            filing.parse_error = routing.parse_error
            logger.warning(
                "backfill_period_routing: %s routing failed (%s)",
                filing.accession_no, routing.parse_error,
            )

        if routing.period_of_report != filing.period_of_report:
            period_changes.append((filing, filing.period_of_report, routing.period_of_report))

        new_qend = routing.quarter_end_date
        new_rq = routing.report_quarter
        if (new_qend != filing.quarter_end_date) or (new_rq != filing.report_quarter):
            other_changes.append((filing, new_qend, new_rq))

    period_count = len(period_changes)
    qend_count = sum(1 for f, q, _ in other_changes if q is not None and f.quarter_end_date is None)
    rq_count = sum(1 for f, _, rq in other_changes if rq is not None and f.report_quarter is None)

    if not period_changes and not other_changes:
        if needs_review_count or failed_count or accepted_at_filled:
            db.flush()  # persist warning/error stamps + accepted_at fills
        else:
            logger.info("backfill_period_routing: nothing to fix")
        return {
            "period_changed": 0,
            "quarter_end_added": 0,
            "report_quarter_added": 0,
            "needs_review": needs_review_count,
            "failed": failed_count,
            "accepted_at_filled": accepted_at_filled,
        }

    # Pass 2: apply period_of_report changes with the is_latest_for_period
    # dance. Skip when no period changes are needed — preserves the cheap
    # path for filings that just need quarter_end_date filled in.
    if period_changes:
        affected: set[tuple] = set()
        for filing, old, new in period_changes:
            affected.add((filing.manager_id, old))
            affected.add((filing.manager_id, new))

        for manager_id, period in affected:
            db.query(Filing13F).filter_by(
                manager_id=manager_id, period_of_report=period
            ).update({"is_latest_for_period": False})
        db.flush()

        for filing, _old, new in period_changes:
            filing.period_of_report = new
        db.flush()

        for manager_id, period in affected:
            _recalculate_version_ranks(db, manager_id, period)
        db.flush()

    # Pass 3: apply quarter_end_date / report_quarter / official_filing_deadline
    # for filings whose period_of_report routing produced them. No unique
    # constraints touched; straight column writes.
    for filing, new_qend, new_rq in other_changes:
        if new_qend is not None and filing.quarter_end_date != new_qend:
            filing.quarter_end_date = new_qend
            if filing.official_filing_deadline is None:
                filing.official_filing_deadline = calculate_official_filing_deadline(db, new_qend)
        if new_rq is not None and filing.report_quarter != new_rq:
            filing.report_quarter = new_rq
    db.flush()

    logger.info(
        "backfill_period_routing: period_changed=%d quarter_end_added=%d "
        "report_quarter_added=%d needs_review=%d failed=%d accepted_at_filled=%d",
        period_count, qend_count, rq_count, needs_review_count, failed_count,
        accepted_at_filled,
    )
    return {
        "period_changed": period_count,
        "quarter_end_added": qend_count,
        "report_quarter_added": rq_count,
        "needs_review": needs_review_count,
        "failed": failed_count,
        "accepted_at_filled": accepted_at_filled,
    }
