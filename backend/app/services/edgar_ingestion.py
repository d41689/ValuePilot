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
    """Simple Jaccard similarity on word sets, used for CIK candidate matching."""
    wa = set(_normalize_name(a).split())
    wb = set(_normalize_name(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


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

def match_cik_candidates(db: Session, min_score: float = 0.6) -> int:
    """For each seeded manager without CIK, query EDGAR and propose candidates.

    High-confidence matches (score ≥ 0.85) are auto-confirmed.
    Lower scores stay as 'candidate' for human review.
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
            url = (
                f"https://efts.sec.gov/LATEST/search-index"
                f"?q=%22{mgr.legal_name.replace(' ', '+')}%22&forms=13F-HR&hits.hits._source=period_of_report&hits.hits.total.value=1"
            )
            try:
                body = client.get(url)
            except Exception as exc:
                logger.warning("CIK search failed for %s: %s", mgr.legal_name, exc)
                continue

            import json
            try:
                data = json.loads(body)
            except Exception:
                continue

            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                continue

            for hit in hits[:5]:
                source = hit.get("_source", {})
                hit_name = source.get("entity_name", "") or source.get("display_names", [""])[0]
                hit_cik = source.get("file_num", "") or ""
                # Try to extract CIK from _id or entity_id
                cik_raw = (
                    hit.get("_id", "")
                    or source.get("entity_id", "")
                )
                # EDGAR search _id is often the accession; look for cik field
                cik_field = source.get("ciks", [])
                if cik_field:
                    cik_raw = str(cik_field[0]).zfill(10)
                else:
                    continue

                score = _name_score(mgr.legal_name, hit_name)
                if score < min_score:
                    continue

                # Check no other manager has this CIK already confirmed
                conflict = (
                    db.query(InstitutionManager)
                    .filter_by(cik=cik_raw)
                    .filter(InstitutionManager.id != mgr.id)
                    .one_or_none()
                )
                if conflict:
                    continue

                if score >= 0.85:
                    mgr.cik = cik_raw
                    mgr.match_status = "confirmed"
                else:
                    mgr.match_status = "candidate"
                    # Store candidate CIK as display_name annotation
                    mgr.display_name = f"[candidate_cik={cik_raw} score={score:.2f}] {mgr.legal_name}"
                updated += 1
                break

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

        filing = Filing13F(
            manager_id=manager.id,
            accession_no=rec.accession_no,
            period_of_report=_accession_period_of_report(rec),
            filed_at=rec.filed_at,
            form_type=rec.form_type,
            version_rank=1,
            is_latest_for_period=True,
        )
        db.add(filing)
        db.flush()  # get id before version_rank recalculation
        _recalculate_version_ranks(db, manager.id, filing.period_of_report)
        inserted += 1

    db.flush()
    return inserted


def _accession_period_of_report(rec: FormIdxRecord):
    """Derive period_of_report from accession filename suffix as best guess.

    The real period is in the primary document; we use filed_at as proxy
    until the primary doc is parsed.  Returns filed_at date.
    """
    # Will be overwritten when primary doc is parsed
    return rec.filed_at


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
) -> int:
    """Download + parse infotable for one filing. Returns count of holdings inserted."""
    manager: InstitutionManager = filing.manager
    if manager is None:
        manager = db.query(InstitutionManager).get(filing.manager_id)

    cik = (manager.cik or "").lstrip("0")
    accession_raw = filing.accession_no.replace("-", "")

    with EdgarClient() as client:
        # Locate infotable.xml via the filing index
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}"
            f"/{accession_raw}/{filing.accession_no}-index.htm"
        )
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

    inserted = 0
    for row in rows:
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
    matches = pattern.findall(body.decode("utf-8", errors="replace"))
    base = "https://www.sec.gov"
    if hint == "infotable":
        for m in matches:
            if "infotable" in m.lower() or "form13f" in m.lower():
                return base + m
        # Return first XML if no specific match
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
