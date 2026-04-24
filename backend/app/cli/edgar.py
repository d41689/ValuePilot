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

        n = ingest_filing_holdings(db, filing, force_refresh=False)
        db.commit()
        typer.echo(f"Reparsed {accession}: {n} holdings upserted.")
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
) -> None:
    """Backfill form.idx metadata for recent N quarters."""
    from app.services.edgar_ingestion import backfill_quarters

    db = SessionLocal()
    try:
        results = backfill_quarters(db, num_quarters=quarters)
        db.commit()
        for q, n in results.items():
            status = f"{n} filings" if n >= 0 else "FAILED"
            typer.echo(f"  {q}: {status}")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    app()
