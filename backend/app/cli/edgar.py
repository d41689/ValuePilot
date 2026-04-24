"""CLI: SEC EDGAR 13F ingestion commands.

Usage (from backend/):
  python -m app.cli.edgar bootstrap-whitelist
  python -m app.cli.edgar fetch-holdings --quarter 2025-Q1
  python -m app.cli.edgar backfill --quarters 4
  python -m app.cli.edgar reparse-filing --accession 0001234567-25-000001
  python -m app.cli.edgar match-cik
"""
import logging
import sys

import typer

from app.core.db import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = typer.Typer(
    name="edgar",
    help="SEC EDGAR 13F ingestion commands",
    no_args_is_help=True,
)


@app.command()
def bootstrap_whitelist() -> None:
    """Seed institution_managers from Dataroma superinvestor list (Step 0)."""
    from app.services.edgar_ingestion import bootstrap_whitelist as _bs

    db = SessionLocal()
    try:
        n = _bs(db)
        db.commit()
        typer.echo(f"Inserted {n} new managers.")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def match_cik(
    min_score: float = typer.Option(0.6, help="Minimum name similarity score"),
) -> None:
    """Match seeded managers to EDGAR CIKs via name search."""
    from app.services.edgar_ingestion import match_cik_candidates

    db = SessionLocal()
    try:
        n = match_cik_candidates(db, min_score=min_score)
        db.commit()
        typer.echo(f"Updated {n} manager CIK candidates.")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def fetch_holdings(
    quarter: str = typer.Option(..., help="Quarter in YYYY-Qn format, e.g. 2025-Q1"),
) -> None:
    """Fetch form.idx for a quarter and ingest filing metadata (Step 1)."""
    from app.services.edgar_ingestion import ingest_quarter_index

    db = SessionLocal()
    try:
        n = ingest_quarter_index(db, quarter)
        db.commit()
        typer.echo(f"Inserted {n} new filings for {quarter}.")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def ingest_holdings(
    quarter: str = typer.Option(..., help="Quarter in YYYY-Qn format, e.g. 2025-Q1"),
    limit: int = typer.Option(0, help="Max filings to process (0 = all)"),
) -> None:
    """Download and parse infotable.xml for filings in a quarter (Step 2)."""
    from app.models.institutions import Filing13F
    from app.services.edgar_ingestion import ingest_filing_holdings

    db = SessionLocal()
    try:
        from datetime import date
        from app.edgar.parsers.form_idx import quarter_to_year_qtr

        year, qtr = quarter_to_year_qtr(quarter)
        # period_of_report falls within the quarter
        q_start = date(year, (qtr - 1) * 3 + 1, 1)
        import calendar
        end_month = qtr * 3
        q_end = date(year, end_month, calendar.monthrange(year, end_month)[1])

        filings = (
            db.query(Filing13F)
            .filter(Filing13F.period_of_report.between(q_start, q_end))
            .filter(Filing13F.raw_infotable_doc_id.is_(None))
            .order_by(Filing13F.filed_at)
            .all()
        )
        if limit:
            filings = filings[:limit]

        total_inserted = 0
        for filing in filings:
            try:
                n = ingest_filing_holdings(db, filing)
                db.commit()
                total_inserted += n
                logger.info("  %s → %d holdings", filing.accession_no, n)
            except Exception as exc:
                db.rollback()
                logger.error("  %s failed: %s", filing.accession_no, exc)

        typer.echo(f"Processed {len(filings)} filings, {total_inserted} holdings inserted.")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def reparse_filing(
    accession: str = typer.Option(..., help="Accession number (dashed format)"),
) -> None:
    """Re-parse a single filing from stored raw document (replay)."""
    from app.models.institutions import Filing13F
    from app.services.edgar_ingestion import ingest_filing_holdings

    db = SessionLocal()
    try:
        filing = db.query(Filing13F).filter_by(accession_no=accession).one_or_none()
        if filing is None:
            typer.echo(f"Filing {accession} not found.", err=True)
            raise typer.Exit(1)

        n = ingest_filing_holdings(db, filing, force_refresh=False, replace_holdings=True)
        db.commit()
        typer.echo(f"Reparsed {accession}: {n} holdings.")
    except typer.Exit:
        raise
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def backfill(
    quarters: int = typer.Option(4, help="Number of recent quarters to backfill"),
    index_only: bool = typer.Option(False, help="Only seed form.idx (skip holdings download)"),
) -> None:
    """Backfill form.idx + holdings for recent N quarters."""
    from app.services.edgar_ingestion import backfill_quarters, ingest_filing_holdings, _recent_quarters
    from app.models.institutions import Filing13F
    from datetime import date
    import calendar
    from app.edgar.parsers.form_idx import quarter_to_year_qtr

    db = SessionLocal()
    try:
        # Step 1: seed form.idx for all quarters
        results = backfill_quarters(db, num_quarters=quarters)
        db.commit()
        for q, n in results.items():
            status = f"{n} new filings indexed" if n >= 0 else "FAILED"
            typer.echo(f"  {q}: {status}")

        if index_only:
            return

        # Step 2: fetch holdings for each quarter
        today = date.today()
        quarter_list = _recent_quarters(today.year, today.month, quarters)
        for quarter in quarter_list:
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
            if not pending:
                typer.echo(f"  {quarter}: holdings already ingested")
                continue

            typer.echo(f"  {quarter}: ingesting {len(pending)} filings...")
            total = 0
            failed = 0
            for filing in pending:
                try:
                    n = ingest_filing_holdings(db, filing)
                    db.commit()
                    total += n
                except Exception as exc:
                    db.rollback()
                    logger.error("  %s failed: %s", filing.accession_no, exc)
                    failed += 1
            typer.echo(f"  {quarter}: {total} holdings inserted ({failed} failed)")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def reparse_all(
    quarter: str = typer.Option("", help="Limit to a quarter, e.g. 2025-Q1 (empty = all)"),
) -> None:
    """Reparse all filings from stored raw docs (no network calls). Replaces existing holdings."""
    from app.models.institutions import Filing13F
    from app.services.edgar_ingestion import ingest_filing_holdings
    import calendar
    from app.edgar.parsers.form_idx import quarter_to_year_qtr
    from datetime import date

    db = SessionLocal()
    try:
        query = db.query(Filing13F).filter(Filing13F.raw_infotable_doc_id.isnot(None))
        if quarter:
            year, qtr = quarter_to_year_qtr(quarter)
            q_start = date(year, (qtr - 1) * 3 + 1, 1)
            end_month = qtr * 3
            q_end = date(year, end_month, calendar.monthrange(year, end_month)[1])
            query = query.filter(Filing13F.period_of_report.between(q_start, q_end))

        filings = query.order_by(Filing13F.period_of_report).all()
        typer.echo(f"Reparsing {len(filings)} filings...")

        total = 0
        failed = 0
        for filing in filings:
            try:
                n = ingest_filing_holdings(db, filing, force_refresh=False, replace_holdings=True)
                db.commit()
                total += n
            except Exception as exc:
                db.rollback()
                logger.error("  %s failed: %s", filing.accession_no, exc)
                failed += 1

        typer.echo(f"Done: {total:,} holdings, {failed} failed")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def backfill_reported_totals() -> None:
    """Backfill reported_total_value_thousands from already-stored primary docs."""
    from app.edgar.fetcher import load_body
    from app.edgar.parsers.primary_doc import parse_primary_doc
    from app.models.institutions import Filing13F, RawSourceDocument

    db = SessionLocal()
    try:
        filings = (
            db.query(Filing13F)
            .filter(Filing13F.raw_primary_doc_id.isnot(None))
            .filter(Filing13F.reported_total_value_thousands.is_(None))
            .all()
        )
        updated = 0
        for filing in filings:
            try:
                doc = db.get(RawSourceDocument, filing.raw_primary_doc_id)
                body = load_body(doc)
                summary = parse_primary_doc(body)
                if summary.table_value_total is not None:
                    filing.reported_total_value_thousands = summary.table_value_total
                    updated += 1
            except Exception as exc:
                logger.warning("  %s: %s", filing.accession_no, exc)
        db.commit()
        typer.echo(f"Updated {updated}/{len(filings)} filings with reported total value.")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def quality_check(
    quarter: str = typer.Option("", help="Scope to a quarter, e.g. 2025-Q1 (empty = all quarters)"),
) -> None:
    """Run data quality checks on ingested holdings."""
    from app.services.edgar_quality import run_quality_checks

    db = SessionLocal()
    try:
        report = run_quality_checks(db, quarter or None)
        for issue in report.issues:
            prefix = {"error": "ERROR", "warning": "WARN ", "info": "INFO "}.get(issue.severity, "?")
            acc = f"  [{issue.accession_no}]" if issue.accession_no else ""
            typer.echo(f"  [{prefix}] {issue.check}{acc}: {issue.detail}")
        typer.echo(f"\nResult: {report.summary()}")
        if report.errors:
            raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def backfill_period_dates() -> None:
    """Fix period_of_report for all filings by re-parsing stored primary docs."""
    from app.services.edgar_ingestion import backfill_period_of_report

    db = SessionLocal()
    try:
        n = backfill_period_of_report(db)
        db.commit()
        typer.echo(f"Corrected period_of_report for {n} filings.")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def enrich_cusip() -> None:
    """Seed cusip_ticker_map from Dataroma holdings pages (name-based matching)."""
    from app.services.cusip_enrichment import enrich_from_dataroma

    db = SessionLocal()
    try:
        n = enrich_from_dataroma(db)
        db.commit()
        typer.echo(f"Inserted {n} CUSIP→ticker mappings.")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def bootstrap_stocks() -> None:
    """Step 1: upsert stocks from cusip_ticker_map, then backfill holdings_13f.stock_id."""
    from app.services.cusip_enrichment import bootstrap_stocks_from_cusip_map, backfill_stock_ids

    db = SessionLocal()
    try:
        created = bootstrap_stocks_from_cusip_map(db)
        linked = backfill_stock_ids(db)
        db.commit()
        typer.echo(f"Stocks created: {created}")
        typer.echo(f"Holdings linked: {linked}")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def enrich_stocks_edgar() -> None:
    """Step 2: match remaining unlinked CUSIPs against SEC company_tickers.json."""
    from app.services.cusip_enrichment import enrich_stocks_from_edgar_tickers

    db = SessionLocal()
    try:
        result = enrich_stocks_from_edgar_tickers(db)
        db.commit()
        typer.echo(f"EDGAR tickers fetched: {result['tickers_fetched']:,}")
        typer.echo(f"New CUSIP mappings:    {result['new_mappings']}")
        typer.echo(f"New stock rows:        {result['new_stocks']}")
        typer.echo(f"Holdings linked:       {result['holdings_linked']}")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    app()
