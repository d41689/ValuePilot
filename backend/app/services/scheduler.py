"""Phase D: quarterly EDGAR ingestion scheduler.

Controlled by EDGAR_SCHEDULER_ENABLED (default False).
When enabled, a background thread checks weekly whether a new quarter's
filings are available and enqueues a quarterly_pipeline job via the
JobRun system. The job is executed asynchronously by the ThirteenFJobWorker.

Pipeline steps (run by the worker, not the scheduler directly):
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

from app.core.config import settings
from app.edgar.client import edgar_rate_limit_status
from app.services.thirteenf_alerts import emit_alert

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
    """True if ingestion for this quarter has already completed (at least one filing exists).

    This is a fast-path skip for the common case where the quarter is fully
    ingested. During active execution, the quarterly_pipeline lock_key prevents
    duplicate jobs — so this check is the primary guard only after the worker
    has finished and committed filings.
    """
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
    """Check for new quarter and trigger the quarterly pipeline job if needed."""
    today = date.today()
    quarter = latest_available_quarter(today)
    logger.info("Quarterly pipeline check: latest available quarter = %s", quarter)

    db = db_factory()
    try:
        if _quarter_already_ingested(db, quarter):
            logger.info("Quarterly pipeline: %s already ingested — skipping", quarter)
            return

        # Trigger the pipeline via the dashboard service so it's visible in the UI
        # and benefits from lock-key duplicate prevention. During the window between
        # enqueue and the worker's first commit, the lock_key prevents a second job
        # from being created even if the scheduler fires again.
        from app.services.thirteenf_admin_dashboard import trigger_job
        result = trigger_job(db, requested_by_user_id=None, payload={
            "job_type": "quarterly_pipeline",
            "quarter": quarter,
            "trigger_source": "scheduler",
        })
        if result.get("conflict"):
            logger.info(
                "Quarterly pipeline: job already active for %s (job_id=%s) — skipping",
                quarter, result.get("active_job_id"),
            )
        else:
            logger.info(
                "Quarterly pipeline: job enqueued for %s (job_id=%s)",
                quarter, result.get("id"),
            )

    except Exception as exc:
        db.rollback()
        logger.exception("Quarterly pipeline trigger failed for %s: %s", quarter, exc)
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

    scheduler.add_job(
        run_daily_sync_poll,
        trigger=CronTrigger(minute=0, timezone="UTC"),
        args=[db_factory],
        id="daily_13f_sync_poll",
        name="Daily 13F form.idx sync poll",
        replace_existing=True,
        misfire_grace_time=900,
    )

    scheduler.add_job(
        run_job_watchdog,
        trigger=CronTrigger(minute=f"*/{settings.THIRTEENF_WATCHDOG_INTERVAL_MINUTES}", timezone="UTC"),
        args=[db_factory],
        id="thirteenf_job_watchdog",
        name="13F job lease watchdog",
        replace_existing=True,
        misfire_grace_time=900,
    )

    scheduler.add_job(
        run_13f_health_summary,
        trigger=CronTrigger(hour=8, minute=0, timezone="America/New_York"),
        args=[db_factory],
        id="thirteenf_daily_health_summary",
        name="13F daily health summary",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    if settings.THIRTEENF_SMART_RETRY_ENABLED:
        # Run every day at 02:00 UTC.
        # Checks for partially failed jobs and retries safe targets if they are old enough.
        scheduler.add_job(
            run_smart_retries,
            trigger=CronTrigger(hour=2, minute=0, timezone="UTC"),
            args=[db_factory],
            id="smart_retries",
            name="13F Smart Retries",
            replace_existing=True,
            misfire_grace_time=3600,
        )
    return scheduler


def run_daily_sync_poll(db_factory: Callable) -> None:
    """Hourly poll that queues eligible daily 13F sync jobs."""
    db = db_factory()
    try:
        from app.services.thirteenf_scheduler import (
            mark_retry_exhausted_daily_syncs_no_data,
            queue_daily_sync_poll,
        )

        mark_retry_exhausted_daily_syncs_no_data(db)
        result = queue_daily_sync_poll(db)
        logger.info("Daily 13F sync poll: %s", result)
    except Exception as exc:
        db.rollback()
        logger.exception("Daily 13F sync poll failed: %s", exc)
    finally:
        db.close()


def run_job_watchdog(db_factory: Callable) -> None:
    """Mark timed-out running jobs only after their lease has expired."""
    db = db_factory()
    try:
        from app.services.thirteenf_job_worker import mark_stale_running_jobs_abandoned

        result = mark_stale_running_jobs_abandoned(db)
        logger.info("13F job watchdog: %s", result)
    except Exception as exc:
        db.rollback()
        logger.exception("13F job watchdog failed: %s", exc)
    finally:
        db.close()


def run_13f_health_summary(db_factory: Callable) -> None:
    """Send the daily 13F health summary through the alert abstraction."""
    db = db_factory()
    try:
        from app.services.thirteenf_health import emit_daily_health_summary, evaluate_13f_alerts

        alerts = evaluate_13f_alerts(db, edgar_rate_limit_status=edgar_rate_limit_status())
        for alert in alerts:
            emit_alert(
                severity=alert["severity"],
                title=alert["title"],
                message=alert["message"],
                context=alert.get("context"),
            )
        result = emit_daily_health_summary(db)
        logger.info("13F daily health summary: alerts=%d summary=%s", len(alerts), result)
    except Exception as exc:
        db.rollback()
        logger.exception("13F daily health summary failed: %s", exc)
    finally:
        db.close()


def run_smart_retries(db_factory: Callable) -> None:
    """Check for partially failed jobs and trigger targeted retries."""
    if not settings.THIRTEENF_SMART_RETRY_ENABLED:
        logger.info("Smart retries disabled — skipping")
        return
    logger.info("Smart retries check: starting")
    db = db_factory()
    try:
        from app.services.thirteenf_admin_dashboard import smart_retry_failed_jobs
        results = smart_retry_failed_jobs(db)
        if results:
            logger.info("Smart retries: triggered %d new jobs", len(results))
        else:
            logger.info("Smart retries: no eligible jobs found")
    except Exception as exc:
        db.rollback()
        logger.exception("Smart retries failed: %s", exc)
    finally:
        db.close()
