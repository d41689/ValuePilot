"""Operator CLI for the FT-03 SEC financial-filing lineage slice.

Examples, inside the API container:

    python -m app.cli.sec_financials ingest-gold-case --case-id aapl-primary --max-filings 1
    python -m app.cli.sec_financials replay --ticker AAPL --cutoff 2026-08-27T23:59:59+00:00

The CLI exposes counts and durable identities only. It never dumps filing bytes
or raw fact values, and it never publishes ``metric_facts``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select
import typer
import yaml

from app.acceptance.financial_truth_gold_set import validate_gold_set
from app.core.config import settings
from app.core.db import SessionLocal
from app.edgar.client import EdgarClient
from app.models.stocks import Stock
from app.services.sec_financial_ingestion import (
    ingest_latest_financial_filings,
    register_reviewed_sec_identity,
    select_sec_financial_evidence_as_of,
)


app = typer.Typer(add_completion=False, no_args_is_help=True)
MANIFEST_PATH = Path("/code/docs/acceptance/financial_truth_beta_gold_set.yml")


def _gold_case(case_id: str) -> dict:
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    validate_gold_set(data)
    matches = [item for item in data["cases"] if item["case_id"] == case_id]
    if len(matches) != 1:
        raise typer.BadParameter("case-id is not present exactly once in the locked manifest")
    return matches[0]


def _single_stock(db, ticker: str) -> Stock:
    rows = db.scalars(select(Stock).where(Stock.ticker == ticker.upper())).all()
    if len(rows) != 1:
        raise typer.BadParameter(
            f"ticker must resolve to exactly one reviewed stock row; found {len(rows)}"
        )
    return rows[0]


@app.command("ingest-gold-case")
def ingest_gold_case(
    case_id: str = typer.Option(..., help="Locked FT-00 case id."),
    max_filings: int = typer.Option(1, min=1, max=200),
    parser_version: str = typer.Option("inline-xbrl-v1"),
    as_of: str | None = typer.Option(
        None, help="Optional timezone-aware SEC acceptance cutoff."
    ),
) -> None:
    """Register the locked identity and ingest a bounded SEC lineage slice."""
    case = _gold_case(case_id)
    now = datetime.now(timezone.utc)
    parsed_as_of: datetime | None = None
    if as_of is not None:
        try:
            parsed_as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            if parsed_as_of.tzinfo is None:
                raise ValueError("timezone offset is required")
        except ValueError as exc:
            raise typer.BadParameter(f"invalid as-of: {exc}") from exc
    db = SessionLocal()
    try:
        stock = _single_stock(db, case["primary_listing"]["ticker"])
        register_reviewed_sec_identity(
            db,
            stock_id=stock.id,
            cik=case["cik"],
            effective_from=date.fromisoformat(
                str(case["expected_history"]["available_start_on"])
            ),
            known_at=now,
            review_reason=(
                f"Locked FT-00 case {case_id}; PO/reviewer approvals recorded in "
                "financial_truth_beta_gold_set.yml."
            ),
        )
        with EdgarClient() as client:
            report = ingest_latest_financial_filings(
                db,
                stock_id=stock.id,
                client=client,
                storage_root=Path(settings.EDGAR_RAW_STORAGE_DIR),
                max_filings=max_filings,
                now=now,
                parser_version=parser_version,
                as_of=parsed_as_of,
            )
        db.commit()
        typer.echo(
            f"case={case_id} stock_id={report.stock_id} cik={report.cik} "
            f"discovered={report.filings_discovered} filings_created={report.filings_created} "
            f"artifacts_created={report.artifacts_created} "
            f"parse_runs_created={report.parse_runs_created} "
            f"raw_facts_created={report.raw_facts_created} failures={len(report.failures)}"
        )
        for failure in report.failures:
            typer.echo(f"failure={failure}", err=True)
        if report.failures:
            raise typer.Exit(2)
    except typer.Exit:
        raise
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def replay(
    ticker: str = typer.Option(...),
    cutoff: str = typer.Option(..., help="Timezone-aware ISO-8601 knowledge cutoff."),
) -> None:
    """Read the PIT-safe lineage projection without displaying raw values."""
    try:
        parsed_cutoff = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
        if parsed_cutoff.tzinfo is None:
            raise ValueError("timezone offset is required")
    except ValueError as exc:
        raise typer.BadParameter(f"invalid cutoff: {exc}") from exc
    db = SessionLocal()
    try:
        stock = _single_stock(db, ticker)
        rows = select_sec_financial_evidence_as_of(
            db, stock_id=stock.id, cutoff=parsed_cutoff
        )
        db.rollback()
        typer.echo(f"ticker={stock.ticker} cutoff={parsed_cutoff.isoformat()} filings={len(rows)}")
        for row in rows:
            typer.echo(
                f"accession={row.accession_no} form={row.form_type} "
                f"parser={row.parser_version} facts={row.fact_count}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    app()
