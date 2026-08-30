"""Operator CLI for the FT-03 SEC financial-filing lineage slice.

Examples, inside the API container:

    python -m app.cli.sec_financials ingest-gold-case --case-id aapl-primary
    python -m app.cli.sec_financials replay --ticker AAPL --cutoff 2026-08-27T23:59:59+00:00

The CLI exposes counts and durable identities only. It never dumps filing bytes
or raw fact values, and it never publishes ``metric_facts``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import re

from sqlalchemy import func, or_, select
import typer
import yaml

from app.acceptance.financial_truth_gold_set import validate_gold_set
from app.core.config import settings
from app.core.db import SessionLocal
from app.edgar.client import EdgarClient
from app.models.sec_financials import SecIssuerIdentity
from app.models.stocks import Stock
from app.services.sec_financial_ingestion import (
    FinancialHistoryTarget,
    _expected_completed_fiscal_years,
    earliest_replayable_sec_financial_evidence_at,
    ingest_latest_financial_filings,
    register_reviewed_sec_identity,
    select_sec_financial_evidence_as_of,
    select_sec_financial_failures_as_of,
)


app = typer.Typer(add_completion=False, no_args_is_help=True)
MANIFEST_PATH = Path("/code/docs/acceptance/financial_truth_beta_gold_set.yml")
_TICKER_SEPARATOR_RE = re.compile(r"[./-]")
_COMPANY_NAME_TOKEN_RE = re.compile(r"[^A-Z0-9]+")
_GENERIC_LISTING_VALUES = {"", "UNKNOWN", "US"}
_MIC_LISTING_ALIASES = {
    "XNAS": {"XNAS", "NASDAQ", "NDQ", "NAS", "NMS", "NCM", "NGM", "NSDQ"},
    "XNYS": {"XNYS", "NYSE"},
}


@dataclass(frozen=True)
class _GoldCaseStockResolution:
    stock: Stock
    source: str
    manifest_ticker: str


@dataclass(frozen=True)
class _LockedGoldCase:
    case: dict
    cutoff_at: datetime


def _gold_case(case_id: str) -> _LockedGoldCase:
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    validate_gold_set(data)
    matches = [item for item in data["cases"] if item["case_id"] == case_id]
    if len(matches) != 1:
        raise typer.BadParameter("case-id is not present exactly once in the locked manifest")
    cutoff_at = datetime.fromisoformat(
        str(data["cycle"]["cutoff_at"]).replace("Z", "+00:00")
    )
    if cutoff_at.tzinfo is None:
        raise typer.BadParameter("locked gold-set cutoff must be timezone-aware")
    return _LockedGoldCase(case=matches[0], cutoff_at=cutoff_at)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _history_target_for_case(
    case: dict, *, filing_selection_as_of: datetime
) -> FinancialHistoryTarget:
    return FinancialHistoryTarget(
        filing_regime=str(case["filing_regime"]),
        fiscal_year_end_mmdd=str(case["fiscal_year_end_mmdd"]),
        available_start_on=date.fromisoformat(
            str(case["expected_history"]["available_start_on"])
        ),
        completed_fiscal_year_cap=int(
            case["expected_history"]["completed_fiscal_year_cap"]
        ),
        filing_selection_as_of=filing_selection_as_of,
    )


def _single_stock(db, ticker: str) -> Stock:
    rows = db.scalars(select(Stock).where(Stock.ticker == ticker.upper())).all()
    if len(rows) != 1:
        raise typer.BadParameter(
            f"ticker must resolve to exactly one reviewed stock row; found {len(rows)}"
        )
    return rows[0]


def _ticker_aliases(case: dict) -> set[str]:
    listing = case["primary_listing"]
    ticker = str(listing["ticker"]).strip().upper()
    if not str(listing["share_class"]).startswith("class_"):
        return {ticker}
    segments = _TICKER_SEPARATOR_RE.split(ticker)
    if len(segments) == 1 or any(not segment for segment in segments):
        return {ticker}
    return {separator.join(segments) for separator in ("-", ".", "/")}


def _normalized_company_name(value: str) -> str:
    return " ".join(_COMPANY_NAME_TOKEN_RE.sub(" ", value.upper()).split())


def _stock_matches_locked_case(stock: Stock, case: dict) -> bool:
    listing = case["primary_listing"]
    if not stock.is_active:
        return False
    if stock.ticker.strip().upper() not in _ticker_aliases(case):
        return False
    if _normalized_company_name(stock.company_name) != _normalized_company_name(
        str(case["company_name"])
    ):
        return False

    manifest_country = str(listing["country"]).strip().upper()
    stock_country = (stock.market_country or "").strip().upper()
    if stock_country not in {"", "UNKNOWN"} and stock_country != manifest_country:
        return False

    manifest_mic = str(listing["mic"]).strip().upper()
    permitted_venues = _MIC_LISTING_ALIASES.get(manifest_mic, {manifest_mic})
    canonical_venue = (stock.listing_exchange or "").strip().upper()
    if canonical_venue not in _GENERIC_LISTING_VALUES:
        return canonical_venue in permitted_venues

    legacy_venues = {
        str(value).strip().upper()
        for value in (stock.raw_exchange, stock.exchange)
        if value is not None
    } - _GENERIC_LISTING_VALUES
    return not legacy_venues or legacy_venues <= permitted_venues


def _terminal_cik_decisions(db, *, cik: str, at: datetime) -> list[SecIssuerIdentity]:
    stock_ids = set(
        db.scalars(
            select(SecIssuerIdentity.stock_id).where(
                SecIssuerIdentity.cik == cik,
                SecIssuerIdentity.known_at <= at,
                SecIssuerIdentity.effective_from <= at.date(),
                or_(
                    SecIssuerIdentity.effective_to.is_(None),
                    SecIssuerIdentity.effective_to >= at.date(),
                ),
            )
        ).all()
    )
    decisions: list[SecIssuerIdentity] = []
    for stock_id in sorted(stock_ids):
        decision = db.scalar(
            select(SecIssuerIdentity)
            .where(
                SecIssuerIdentity.stock_id == stock_id,
                SecIssuerIdentity.known_at <= at,
                SecIssuerIdentity.effective_from <= at.date(),
                or_(
                    SecIssuerIdentity.effective_to.is_(None),
                    SecIssuerIdentity.effective_to >= at.date(),
                ),
            )
            .order_by(SecIssuerIdentity.known_at.desc(), SecIssuerIdentity.id.desc())
            .limit(1)
        )
        if decision is not None:
            decisions.append(decision)
    return decisions


def _resolve_gold_case_stock(
    db, case: dict, *, at: datetime
) -> _GoldCaseStockResolution:
    if at.tzinfo is None:
        raise typer.BadParameter("gold-case identity cutoff must be timezone-aware")
    case_id = str(case["case_id"])
    cik = str(case["cik"])
    manifest_ticker = str(case["primary_listing"]["ticker"]).strip().upper()
    decisions = _terminal_cik_decisions(db, cik=cik, at=at)
    if decisions:
        reviewed = [
            decision
            for decision in decisions
            if decision.status == "reviewed" and decision.cik == cik
        ]
        if len(decisions) != 1 or len(reviewed) != 1:
            raise typer.BadParameter(
                f"locked CIK must resolve to exactly one terminal reviewed stock identity; "
                f"found {len(reviewed)} reviewed among {len(decisions)} terminal decisions"
            )
        stock = db.get(Stock, reviewed[0].stock_id)
        if stock is None or not _stock_matches_locked_case(stock, case):
            raise typer.BadParameter(
                f"reviewed CIK identity conflicts with locked case {case_id}"
            )
        return _GoldCaseStockResolution(
            stock=stock,
            source="reviewed_cik",
            manifest_ticker=manifest_ticker,
        )

    aliases = _ticker_aliases(case)
    candidates = db.scalars(
        select(Stock).where(
            func.upper(Stock.ticker).in_(aliases),
            Stock.is_active.is_(True),
        )
    ).all()
    consistent = [
        stock for stock in candidates if _stock_matches_locked_case(stock, case)
    ]
    if len(consistent) != 1:
        raise typer.BadParameter(
            "locked case bootstrap must resolve to exactly one consistent stock row; "
            f"found {len(consistent)}"
        )
    return _GoldCaseStockResolution(
        stock=consistent[0],
        source="locked_manifest_bootstrap",
        manifest_ticker=manifest_ticker,
    )


@app.command("ingest-gold-case")
def ingest_gold_case(
    case_id: str = typer.Option(..., help="Locked FT-00 case id."),
    max_filings: int = typer.Option(50, min=1, max=200),
    parser_version: str = typer.Option("inline-xbrl-v1"),
    as_of: str | None = typer.Option(
        None,
        help=(
            "Optional timezone-aware filing-selection acceptance cutoff; defaults "
            "to the locked gold-set evaluation cutoff. This is not evidence "
            "knowledge time."
        ),
    ),
) -> None:
    """Register the locked identity and ingest a bounded SEC lineage slice."""
    locked_case = _gold_case(case_id)
    case = locked_case.case
    ingestion_attempted_at = _utc_now()
    parsed_filing_selection_as_of: datetime | None = None
    if as_of is not None:
        try:
            parsed_filing_selection_as_of = datetime.fromisoformat(
                as_of.replace("Z", "+00:00")
            )
            if parsed_filing_selection_as_of.tzinfo is None:
                raise ValueError("timezone offset is required")
        except ValueError as exc:
            raise typer.BadParameter(f"invalid as-of: {exc}") from exc
    filing_selection_as_of = (
        parsed_filing_selection_as_of or locked_case.cutoff_at
    )
    history_target = _history_target_for_case(
        case, filing_selection_as_of=filing_selection_as_of
    )
    expected_years = _expected_completed_fiscal_years(history_target)
    db = SessionLocal()
    try:
        resolution = _resolve_gold_case_stock(db, case, at=ingestion_attempted_at)
        stock = resolution.stock
        if resolution.source == "locked_manifest_bootstrap":
            register_reviewed_sec_identity(
                db,
                stock_id=stock.id,
                cik=case["cik"],
                effective_from=date.fromisoformat(
                    str(case["expected_history"]["available_start_on"])
                ),
                known_at=ingestion_attempted_at,
                review_reason=(
                    f"Locked FT-00 case {case_id}; PO/reviewer approvals recorded in "
                    "financial_truth_beta_gold_set.yml."
                ),
            )
        typer.echo(
            f"identity_resolution={resolution.source} case={case_id} "
            f"manifest_ticker={resolution.manifest_ticker} stock_ticker={stock.ticker} "
            f"stock_id={stock.id} cik={case['cik']}"
        )
        typer.echo(
            f"filing_selection_as_of={filing_selection_as_of.isoformat()} "
            f"regime={history_target.filing_regime} "
            f"fiscal_year_end_mmdd={history_target.fiscal_year_end_mmdd} "
            f"available_start_on={history_target.available_start_on.isoformat()} "
            "expected_completed_fiscal_years="
            f"{','.join(str(year) for year in expected_years)} "
            f"expected_completed_fiscal_year_count={len(expected_years)}"
        )
        typer.echo(f"ingestion_attempted_at={ingestion_attempted_at.isoformat()}")
        with EdgarClient() as client:
            report = ingest_latest_financial_filings(
                db,
                stock_id=stock.id,
                client=client,
                storage_root=Path(settings.EDGAR_RAW_STORAGE_DIR),
                max_filings=max_filings,
                now=ingestion_attempted_at,
                parser_version=parser_version,
                filing_selection_as_of=filing_selection_as_of,
                history_target=history_target,
            )
        db.commit()
        replayable_at = earliest_replayable_sec_financial_evidence_at(
            db, stock_id=stock.id
        )
        if replayable_at is None:
            typer.echo("pit_evidence_availability=unavailable")
        else:
            typer.echo(
                f"earliest_replayable_evidence_at={replayable_at.isoformat()} "
                "pit_replay_before_earliest_evidence=unavailable"
            )
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
        failures = select_sec_financial_failures_as_of(
            db, stock_id=stock.id, cutoff=parsed_cutoff
        )
        replayable_at = None
        if not rows:
            replayable_at = earliest_replayable_sec_financial_evidence_at(
                db, stock_id=stock.id
            )
        db.rollback()
        if (
            not rows
            and not failures
            and replayable_at is not None
            and parsed_cutoff < replayable_at
        ):
            typer.echo(
                f"ticker={stock.ticker} cutoff={parsed_cutoff.isoformat()} filings=0 "
                "failure=pit_evidence_unavailable "
                f"earliest_replayable_evidence_at={replayable_at.isoformat()}",
                err=True,
            )
            raise typer.Exit(2)
        typer.echo(f"ticker={stock.ticker} cutoff={parsed_cutoff.isoformat()} filings={len(rows)}")
        for row in rows:
            typer.echo(
                f"accession={row.accession_no} form={row.form_type} "
                f"parser={row.parser_version} facts={row.fact_count}"
            )
        for failure in failures:
            typer.echo(
                f"failure={failure.accession_no}:{failure.error_code}",
                err=True,
            )
        if failures:
            raise typer.Exit(2)
    finally:
        db.close()


if __name__ == "__main__":
    app()
