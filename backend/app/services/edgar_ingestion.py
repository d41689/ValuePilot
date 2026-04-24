"""EDGAR 13F ingestion orchestration.

Implements the three-step pipeline from the plan:
  Step 0 – bootstrap whitelist from Dataroma
  Step 1 – fetch quarter form.idx and upsert filing metadata
  Step 2 – fetch + parse infotable.xml and write holdings
"""
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dataroma.client import DataromaClient
from app.dataroma.parsers.holdings import parse_holdings
from app.dataroma.parsers.managers import parse_managers
from app.edgar.client import EdgarClient
from app.edgar.fetcher import fetch_and_store, load_body
from app.edgar.parsers.form_idx import (
    FormIdxRecord,
    form_idx_url,
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

def bootstrap_whitelist(db: Session) -> int:
    """Seed institution_managers from Dataroma superinvestor list.

    Returns number of new records inserted.
    """
    with DataromaClient() as dc:
        html = dc.get_managers()

    managers = parse_managers(html)
    logger.info("Dataroma returned %d manager entries", len(managers))

    inserted = 0
    for mgr in managers:
        existing = (
            db.query(InstitutionManager)
            .filter_by(dataroma_code=mgr.dataroma_code)
            .one_or_none()
        )
        if existing is not None:
            existing.last_seen_at = datetime.now(timezone.utc)
            existing.dataroma_synced_at = datetime.now(timezone.utc)
            continue

        record = InstitutionManager(
            legal_name=mgr.name,
            name_normalized=_normalize_name(mgr.name),
            dataroma_code=mgr.dataroma_code,
            match_status="seeded",
            is_superinvestor=True,
            dataroma_synced_at=datetime.now(timezone.utc),
        )
        db.add(record)
        inserted += 1

    db.flush()
    logger.info("bootstrap_whitelist: inserted %d new managers", inserted)
    return inserted


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
                mgr.display_name = f"[candidate_cik={best_cik} score={best_score:.2f}] {best_entity}"
                logger.info("Candidate %s → CIK %s (score=%.2f)", company_name, best_cik, best_score)
            updated += 1

    db.flush()
    return updated


# ---------------------------------------------------------------------------
# Step 1 – fetch quarter index and ingest filing metadata
# ---------------------------------------------------------------------------

def ingest_quarter_index(
    db: Session,
    quarter: str,
    *,
    cik_whitelist: Optional[set[str]] = None,
) -> int:
    """Fetch form.idx for the given quarter and write new filings_13f rows.

    If cik_whitelist is None, all confirmed managers in institution_managers are used.
    Returns count of new filings inserted.
    """
    year, qtr = quarter_to_year_qtr(quarter)
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


def ingest_filing_holdings(
    db: Session,
    filing: Filing13F,
    *,
    force_refresh: bool = False,
    replace_holdings: bool = False,
) -> int:
    """Download + parse infotable for one filing. Returns count of holdings inserted.

    replace_holdings=True deletes existing holdings before re-inserting (use for reparse).
    """
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
    # Try candidates with HEAD
    for url in candidates:
        try:
            client.get(url)  # will raise if 404 etc.
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
            client.get(url)
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
    """Backfill recent N quarters. Returns dict of quarter → filings inserted."""
    from datetime import date

    today = date.today()
    quarters = _recent_quarters(today.year, today.month, num_quarters)
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
    """Fix period_of_report for all filings by re-parsing stored primary docs.

    On first ingestion, period_of_report is set to filed_at as a proxy.
    The real quarter-end date lives inside the primary document (periodOfReport).
    This function corrects all existing rows.  Safe to run multiple times.

    Returns count of filings updated.
    """
    from app.edgar.fetcher import load_body
    from app.models.institutions import Filing13F, RawSourceDocument

    filings = (
        db.query(Filing13F)
        .filter(Filing13F.raw_primary_doc_id.isnot(None))
        .all()
    )

    # Pass 1: collect corrections (manager_id, old_period, new_period) per filing
    corrections: list[tuple[Filing13F, object, object]] = []
    for filing in filings:
        doc = db.get(RawSourceDocument, filing.raw_primary_doc_id)
        if doc is None:
            continue
        try:
            body = load_body(doc)
            summary = parse_primary_doc(body)
            if summary.period_of_report:
                parsed = _parse_period_date(summary.period_of_report)
                if parsed and parsed != filing.period_of_report:
                    corrections.append((filing, filing.period_of_report, parsed))
        except Exception as exc:
            logger.warning("backfill_period_of_report: %s: %s", filing.accession_no, exc)

    if not corrections:
        logger.info("backfill_period_of_report: nothing to fix")
        return 0

    # Pass 2: gather every period group that will be touched
    affected: set[tuple] = set()
    for filing, old, new in corrections:
        affected.add((filing.manager_id, old))
        affected.add((filing.manager_id, new))

    # Pass 3: clear is_latest for all affected groups before any period changes
    for manager_id, period in affected:
        db.query(Filing13F).filter_by(
            manager_id=manager_id, period_of_report=period
        ).update({"is_latest_for_period": False})
    db.flush()

    # Pass 4: apply period corrections
    for filing, _old, new in corrections:
        filing.period_of_report = new
    db.flush()

    # Pass 5: recalculate version_rank and is_latest for every touched group
    for manager_id, period in affected:
        _recalculate_version_ranks(db, manager_id, period)
    db.flush()

    logger.info("backfill_period_of_report: corrected %d filings", len(corrections))
    return len(corrections)


def _recent_quarters(year: int, month: int, n: int) -> list[str]:
    """Return last N quarters in YYYY-Qn format, most recent first."""
    qtr = (month - 1) // 3 + 1
    result = []
    for _ in range(n):
        result.append(f"{year}-Q{qtr}")
        qtr -= 1
        if qtr == 0:
            qtr = 4
            year -= 1
    return result
