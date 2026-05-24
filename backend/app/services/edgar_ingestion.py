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
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dataroma.client import DataromaClient
from app.dataroma.parsers.managers import parse_managers
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
    RawSourceDocument,
)

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

def seed_confirmed_managers(db: Session) -> int:
    """Seed institution_managers from a predefined list of confirmed CIKs.

    This bypasses the match-cik step for high-priority managers. As of
    the manager-taxonomy-v2 change
    (``docs/tasks/2026-05-24_manager-taxonomy-v2.md``), each seed entry
    also carries the two-layer ``style_primary`` / ``capital_structure``
    classification plus optional metadata, and the legacy
    ``manager_type`` column is derived from ``style_primary`` via
    ``derive_legacy_manager_type``.

    Idempotency contract: re-running this function on a DB that already
    has these managers updates fields in place without duplicating rows
    and without writing to fields the entry doesn't specify.
    """
    import json
    import os
    from pathlib import Path

    # Imported lazily to avoid an import cycle at module load:
    # manager_style imports from app.models.institutions, which is
    # already imported above for InstitutionManager. Keeping it lazy
    # also keeps this function's import surface honest.
    from app.services.oracles_lens.manager_style import derive_legacy_manager_type

    seed_path = Path(__file__).parent / "seed_data" / "confirmed_managers.json"
    if not os.path.exists(seed_path):
        logger.warning("Seed data not found at %s", seed_path)
        return 0

    with open(seed_path, "r") as f:
        seed_data = json.load(f)

    updated = 0
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

        if existing:
            # Update existing record to confirmed + V2 classification
            existing.cik = cik
            existing.match_status = "confirmed"
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
            updated += 1

    return updated


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

    def to_summary_dict(self, sample_size: int = 25) -> dict:
        """Compact JSON shape suitable for ``JobRun.summary_json`` and
        the admin endpoint response. Counts are always exact; sample
        lists are truncated so a 1000-row diff doesn't bloat the
        ``job_runs`` table."""
        def _sample(entries: list[DataromaSyncEntry]) -> list[dict]:
            return [
                {
                    "dataroma_code": e.dataroma_code,
                    "name": e.name,
                    "institution_manager_id": e.institution_manager_id,
                }
                for e in entries[:sample_size]
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


def _fetch_dataroma_managers() -> list:
    """Hit Dataroma through Rate Guard and parse the manager table.

    Extracted into a single seam so tests can monkeypatch this one symbol
    instead of mocking the whole HTTP + Rate Guard chain. Returns a list
    of ``DataromaManager`` (see ``app.dataroma.parsers.managers``).
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
        db.add(record)
        added += 1

    db.flush()
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
        if needs_review_count or failed_count:
            db.flush()  # persist the parse_warning / parse_error stamps
        else:
            logger.info("backfill_period_routing: nothing to fix")
        return {
            "period_changed": 0,
            "quarter_end_added": 0,
            "report_quarter_added": 0,
            "needs_review": needs_review_count,
            "failed": failed_count,
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
        "report_quarter_added=%d needs_review=%d failed=%d",
        period_count, qend_count, rq_count, needs_review_count, failed_count,
    )
    return {
        "period_changed": period_count,
        "quarter_end_added": qend_count,
        "report_quarter_added": rq_count,
        "needs_review": needs_review_count,
        "failed": failed_count,
    }
