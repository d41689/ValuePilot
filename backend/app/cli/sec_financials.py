"""Operator CLI for the FT-03 SEC financial-filing lineage slice.

Examples, inside the API container:

    python -m app.cli.sec_financials ingest-gold-case --case-id aapl-primary --max-filings 1
    python -m app.cli.sec_financials replay --ticker AAPL --cutoff 2026-08-27T23:59:59+00:00

The CLI exposes counts and durable identities only. It never dumps filing bytes
or raw fact values. Canonical publication is an explicit, separate command.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select
import typer
import yaml

from app.acceptance.financial_truth_gold_set import (
    expected_completed_fiscal_years,
    validate_gold_set,
)
from app.core.config import settings
from app.core.db import SessionLocal
from app.edgar.client import EdgarClient
from app.models.sec_financials import SecFinancialFiling, SecIssuerIdentity
from app.models.stocks import Stock
from app.services.sec_financial_ingestion import (
    ingest_latest_financial_filings,
    register_reviewed_sec_identity,
    select_sec_financial_evidence_as_of,
)
from app.services.sec_metric_publication import publish_sec_metric_facts


app = typer.Typer(add_completion=False, no_args_is_help=True)
MANIFEST_PATH = Path("/code/docs/acceptance/financial_truth_beta_gold_set.yml")


def _gold_case(case_id: str) -> dict:
    data = _gold_manifest()
    matches = [item for item in data["cases"] if item["case_id"] == case_id]
    if len(matches) != 1:
        raise typer.BadParameter("case-id is not present exactly once in the locked manifest")
    return matches[0]


def _gold_manifest() -> dict:
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    validate_gold_set(data)
    return data


def _aware_iso(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone offset is required")
        return parsed
    except ValueError as exc:
        raise typer.BadParameter(f"invalid {field}: {exc}") from exc


def _single_stock(db, ticker: str) -> Stock:
    rows = _matching_stocks(db, ticker)
    if len(rows) != 1:
        raise typer.BadParameter(
            f"ticker must resolve to exactly one reviewed stock row; found {len(rows)}"
        )
    return rows[0]


def _matching_stocks(db, ticker: str) -> list[Stock]:
    canonical = ticker.strip().upper().replace("/", "-").replace(".", "-")
    candidates = {
        ticker.strip().upper(),
        canonical,
        canonical.replace("-", "/"),
        canonical.replace("-", "."),
    }
    rows = db.scalars(select(Stock).where(Stock.ticker.in_(sorted(candidates)))).all()
    return [
        stock
        for stock in rows
        if stock.ticker.upper().replace("/", "-").replace(".", "-") == canonical
    ]


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
        parsed_as_of = _aware_iso(as_of, field="as-of")
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
    parsed_cutoff = _aware_iso(cutoff, field="cutoff")
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


@app.command("publish")
def publish(
    ticker: str = typer.Option(...),
    cutoff: str = typer.Option(..., help="Timezone-aware SEC knowledge cutoff."),
    mapping_version: str = typer.Option("sec-us-gaap-v2"),
) -> None:
    """Publish approved SEC actuals into canonical metric_facts."""
    parsed_cutoff = _aware_iso(cutoff, field="cutoff")
    db = SessionLocal()
    try:
        stock = _single_stock(db, ticker)
        report = publish_sec_metric_facts(
            db,
            stock_id=stock.id,
            cutoff=parsed_cutoff,
            mapping_version=mapping_version,
        )
        typer.echo(
            f"ticker={stock.ticker} stock_id={stock.id} mapping={report.mapping_version} "
            f"eligible_filings={report.eligible_filing_count} "
            f"created={report.created_count} published={report.published_count} "
            f"unresolved={report.unresolved_count} rejected={report.rejected_count}"
        )
        if report.unresolved_count or report.rejected_count:
            raise typer.Exit(2)
    except typer.Exit:
        raise
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command("coverage-gold-set")
def coverage_gold_set() -> None:
    """Report the complete locked denominator without fetching any source."""
    manifest = _gold_manifest()
    locked_cutoff = _aware_iso(
        str(manifest["cycle"]["cutoff_at"]), field="cycle.cutoff_at"
    )
    db = SessionLocal()
    incomplete = 0
    try:
        typer.echo(
            f"cycle={manifest['cycle']['id']} expected_cases={len(manifest['cases'])}"
        )
        for case in manifest["cases"]:
            ticker = case["primary_listing"]["ticker"]
            stocks = _matching_stocks(db, ticker)
            identity = None
            filing_count = 0
            evidence = []
            if len(stocks) == 1:
                identity = db.scalar(
                    select(SecIssuerIdentity)
                    .where(
                        SecIssuerIdentity.stock_id == stocks[0].id,
                        SecIssuerIdentity.cik == case["cik"],
                        SecIssuerIdentity.status == "reviewed",
                        SecIssuerIdentity.known_at <= locked_cutoff,
                    )
                    .order_by(
                        SecIssuerIdentity.known_at.desc(),
                        SecIssuerIdentity.id.desc(),
                    )
                    .limit(1)
                )
                if identity is not None:
                    filing_count = len(
                        db.scalars(
                            select(SecFinancialFiling.id).where(
                                SecFinancialFiling.issuer_identity_id == identity.id,
                                SecFinancialFiling.known_at <= locked_cutoff,
                                SecFinancialFiling.accepted_at <= locked_cutoff,
                            )
                        ).all()
                    )
                    evidence = select_sec_financial_evidence_as_of(
                        db,
                        stock_id=stocks[0].id,
                        cutoff=locked_cutoff,
                    )
            completed_fy_years = {
                row.report_date.year
                for row in db.scalars(
                    select(SecFinancialFiling).where(
                        SecFinancialFiling.id.in_(
                            [item.filing_id for item in evidence] or [-1]
                        ),
                        SecFinancialFiling.form_type.in_(
                            ["10-K", "10-K/A", "20-F", "20-F/A"]
                        ),
                        SecFinancialFiling.report_date.is_not(None),
                    )
                ).all()
                if row.report_date is not None
            }
            expected_fy_years = set(
                expected_completed_fiscal_years(
                    case, cutoff_at=locked_cutoff
                )
            )
            observed_fy_years = completed_fy_years & expected_fy_years
            dispositions = {
                int(item["fiscal_year"]): item["disposition"]
                for item in case["expected_history"]["unavailable_years"]
            }
            missing_fy_years = expected_fy_years - observed_fy_years
            expected_unavailable = {
                year
                for year in missing_fy_years
                if dispositions.get(year) == "expected"
            }
            blocking_missing = missing_fy_years - expected_unavailable
            resolved_fy_years = observed_fy_years | expected_unavailable
            vertical_state = "ready" if evidence else "incomplete"
            state = (
                "complete"
                if vertical_state == "ready"
                and not blocking_missing
                else "incomplete"
            )
            if state != "complete":
                incomplete += 1
            typer.echo(
                f"case={case['case_id']} ticker={ticker} state={state} "
                f"vertical_state={vertical_state} "
                f"stock_matches={len(stocks)} identity_reviewed={identity is not None} "
                f"filings={filing_count} eligible_parses={len(evidence)} "
                f"resolved_fy_years={len(resolved_fy_years)}/{len(expected_fy_years)} "
                f"expected_fy_years={sorted(expected_fy_years)} "
                f"observed_fy_years={sorted(observed_fy_years)} "
                f"missing_fy_years={sorted(missing_fy_years)} "
                f"expected_unavailable={sorted(expected_unavailable)} "
                f"unexpected_unavailable={sorted(year for year in missing_fy_years if dispositions.get(year) == 'unexpected')}"
            )
        typer.echo(
            f"observed_cases={len(manifest['cases'])} incomplete_cases={incomplete}"
        )
        if incomplete:
            raise typer.Exit(2)
    finally:
        db.close()


if __name__ == "__main__":
    app()
