"""Phase D: quarterly EDGAR ingestion scheduler.

Controlled by EDGAR_SCHEDULER_ENABLED (default False).
When enabled, a background thread checks weekly whether a new quarter's
filings are available and runs the full pipeline if so.

Pipeline per quarter:
  1. Fetch form.idx + ingest filing metadata
  2. Download + parse infotable.xml for all new filings
  3. Refresh CUSIP → ticker mappings (Dataroma + EDGAR company_tickers.json)
  4. Backfill holdings_13f.stock_id
  5. Run data quality checks; log any errors
"""
import logging
from datetime import date
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Quarter availability logic
# ---------------------------------------------------------------------------

def latest_available_quarter(today: date) -> str:
    """Return the most recent quarter whose 45-day filing deadline has passed.

    Deadlines (approximate):
      Q4 (ends Dec 31) → due Feb 14 of the following year
      Q1 (ends Mar 31) → due May 15
      Q2 (ends Jun 30) → due Aug 14
      Q3 (ends Sep 30) → due Nov 14
    """
    # (deadline_month, deadline_day, quarter_label, year_offset_from_current)
    checkpoints = [
        (2,  14, "Q4", -1),
        (5,  15, "Q1",  0),
        (8,  14, "Q2",  0),
        (11, 14, "Q3",  0),
    ]
    result = f"{today.year - 1}-Q3"  # safe fallback
    for month, day, label, year_offset in checkpoints:
        if (today.month, today.day) >= (month, day):
            result = f"{today.year + year_offset}-{label}"
    return result


def _quarter_already_ingested(db, quarter: str) -> bool:
    """True if we already have at least one filing for this quarter."""
    from app.edgar.parsers.form_idx import quarter_to_year_qtr
    from app.models.institutions import Filing13F
    import calendar

    year, qtr = quarter_to_year_qtr(quarter)
    q_start = date(year, (qtr - 1) * 3 + 1, 1)
    end_month = qtr * 3
    q_end = date(year, end_month, calendar.monthrange(year, end_month)[1])
    count = (
        db.query(Filing13F)
        .filter(Filing13F.period_of_report.between(q_start, q_end))
        .count()
    )
    return count > 0


# ---------------------------------------------------------------------------
# Quarterly pipeline job
# ---------------------------------------------------------------------------

def run_quarterly_pipeline(db_factory: Callable) -> None:
    """Check for new quarter and run the full ingestion pipeline if needed."""
    today = date.today()
    quarter = latest_available_quarter(today)
    logger.info("Quarterly pipeline check: latest available quarter = %s", quarter)

    db = db_factory()
    try:
        if _quarter_already_ingested(db, quarter):
            logger.info("Quarterly pipeline: %s already ingested — skipping", quarter)
            return

        logger.info("Quarterly pipeline: starting ingestion for %s", quarter)

        # Step 1: fetch form.idx and seed filing metadata
        from app.services.edgar_ingestion import ingest_quarter_index, ingest_filing_holdings
        from app.models.institutions import Filing13F
        from app.edgar.parsers.form_idx import quarter_to_year_qtr
        import calendar

        n_filings = ingest_quarter_index(db, quarter)
        db.commit()
        logger.info("  form.idx: %d new filings indexed", n_filings)

        # Step 2: download + parse infotable for all new filings
        year, qtr = quarter_to_year_qtr(quarter)
        q_start = date(year, (qtr - 1) * 3 + 1, 1)
        end_month = qtr * 3
        q_end = date(year, end_month, calendar.monthrange(year, end_month)[1])

        pending = (
            db.query(Filing13F)
            .filter(Filing13F.period_of_report.between(q_start, q_end))
            .filter(Filing13F.raw_infotable_doc_id.is_(None))
            .order_by(Filing13F.filed_at)
            .all()
        )
        total_holdings = 0
        failed = 0
        for filing in pending:
            try:
                n = ingest_filing_holdings(db, filing)
                db.commit()
                total_holdings += n
            except Exception as exc:
                db.rollback()
                logger.error("  %s failed: %s", filing.accession_no, exc)
                failed += 1
        logger.info("  holdings: %d inserted (%d filings failed)", total_holdings, failed)

        # Step 3: refresh CUSIP → ticker mappings
        from app.services.cusip_enrichment import (
            enrich_from_dataroma,
            bootstrap_stocks_from_cusip_map,
            backfill_stock_ids,
            enrich_stocks_from_edgar_tickers,
        )
        n_cusip = enrich_from_dataroma(db)
        db.commit()
        logger.info("  enrich_from_dataroma: %d new mappings", n_cusip)

        # Step 4: bootstrap stocks + backfill stock_id
        bootstrap_stocks_from_cusip_map(db)
        linked = backfill_stock_ids(db)
        db.commit()
        logger.info("  stock_id backfill: %d holdings linked", linked)

        # Step 5: EDGAR company_tickers.json for remaining unmatched
        try:
            result = enrich_stocks_from_edgar_tickers(db)
            db.commit()
            logger.info(
                "  enrich_stocks_from_edgar: %d new mappings, %d holdings linked",
                result["new_mappings"], result["holdings_linked"],
            )
        except Exception as exc:
            db.rollback()
            logger.warning("  enrich_stocks_from_edgar failed: %s", exc)

        # Step 6: data quality check — log errors only
        from app.services.edgar_quality import run_quality_checks
        report = run_quality_checks(db, quarter)
        if report.errors:
            logger.error(
                "Quality check after %s ingestion: %s",
                quarter, report.summary(),
            )
            for issue in report.errors:
                logger.error("  [%s] %s", issue.check, issue.detail)
        else:
            logger.info("Quality check: %s", report.summary())

        logger.info("Quarterly pipeline complete for %s", quarter)

    except Exception as exc:
        db.rollback()
        logger.exception("Quarterly pipeline failed for %s: %s", quarter, exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Scheduler factory
# ---------------------------------------------------------------------------

def create_scheduler(db_factory: Callable) -> BackgroundScheduler:
    """Build and return a configured BackgroundScheduler (not yet started)."""
    scheduler = BackgroundScheduler(timezone="UTC")

    # Run every Monday at 06:00 UTC.
    # The job itself checks whether there is a new quarter to ingest
    # and no-ops if the latest available quarter is already in the DB.
    scheduler.add_job(
        run_quarterly_pipeline,
        trigger=CronTrigger(day_of_week="mon", hour=6, minute=0, timezone="UTC"),
        args=[db_factory],
        id="quarterly_edgar_pipeline",
        name="Quarterly EDGAR 13F ingestion",
        replace_existing=True,
        misfire_grace_time=3600,  # allow up to 1h late firing
    )
    return scheduler
