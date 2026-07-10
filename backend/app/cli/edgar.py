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
def seed_confirmed_managers() -> None:
    """Seed institution_managers from the curated confirmed-managers list (Step 0).

    Safe to re-run (and to run on every deploy): the seed expresses intent, a
    human owns lifecycle. Retired managers are skipped, nobody is deactivated,
    and rows awaiting human confirmation are reported rather than promoted.
    """
    from app.services.edgar_ingestion import seed_confirmed_managers as _seed

    db = SessionLocal()
    try:
        report = _seed(db)
        db.commit()
        _echo_seed_report(report)
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


def _echo_seed_report(report: dict) -> None:
    """Print the seeding diff, never a bare count — an operator must be able to
    see what a deploy-time re-seed did (and refused to do)."""
    typer.echo(
        f"Seed entries {report['seed_entries']}: "
        f"created {report['created']}, updated {report['updated']}, "
        f"skipped human-decided {report['skipped_human_decided']}, "
        f"skipped needs-review {report['skipped_needs_review']}, "
        f"awaiting confirmation {report['awaiting_confirmation']}, "
        f"ambiguous name match {report['ambiguous_name_match']}"
    )
    for key, header in (
        ("skipped_human_decided_ciks",
         "skipped - an operator retired/revoked/rejected these; seeding will not resurrect them:"),
        ("skipped_needs_review_ciks",
         "skipped - an operator parked these in needs_review; seeding will not touch them:"),
        ("awaiting_confirmation_ciks",
         "in the seed file but NOT confirmed - confirm them in the admin Managers page:"),
        ("ambiguous_name_match_ciks",
         "NOT created - another row normalizes to the same name; resolve the duplicate by hand:"),
    ):
        if report.get(key):
            typer.echo(f"  {header}")
            for cik in report[key]:
                typer.echo(f"    - {cik}")


@app.command()
def seed_pending_cik_review_fixture() -> None:
    """Seed a deterministic pending CIK candidate for admin dashboard QA."""
    from app.services.edgar_ingestion import seed_pending_cik_review_fixture as _seed

    db = SessionLocal()
    try:
        n = _seed(db)
        db.commit()
        typer.echo(f"Seeded {n} pending CIK review fixture managers.")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def bootstrap_whitelist() -> None:
    """DEPRECATED: alias for ``seed-confirmed-managers``. Bootstrap is now
    offline (driven by ``confirmed_managers.json``) — Dataroma is consulted
    on demand via ``sync-dataroma``. See
    ``docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md``.
    """
    typer.echo(
        "WARNING: 'bootstrap-whitelist' is deprecated and now runs "
        "'seed-confirmed-managers' (offline JSON). Use 'sync-dataroma' "
        "to diff Dataroma's current list against ours.",
        err=True,
    )
    from app.services.edgar_ingestion import seed_confirmed_managers as _seed

    db = SessionLocal()
    try:
        report = _seed(db)
        db.commit()
        _echo_seed_report(report)
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def sync_dataroma() -> None:
    """Diff Dataroma's current manager list against our DB.

    Read-only: does NOT insert new managers. Prints the three buckets
    (new / known / dropped). Use the admin Managers page (or a follow-up
    command) to add specific Dataroma codes as candidates.
    """
    from app.services.edgar_ingestion import sync_dataroma_managers

    db = SessionLocal()
    try:
        diff = sync_dataroma_managers(db)
        # Read-only — no commit needed, but be explicit.
        db.rollback()
        typer.echo(
            f"Fetched at {diff.fetched_at.isoformat()}: "
            f"new={len(diff.new)} known={len(diff.known)} "
            f"dropped={len(diff.dropped)}"
        )
        for label, entries in (
            ("NEW", diff.new),
            ("DROPPED", diff.dropped),
        ):
            if entries:
                typer.echo(f"\n{label}:")
                for e in entries:
                    typer.echo(f"  {e.dataroma_code:12s}  {e.name}")
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
) -> None:
    """Download and parse infotable.xml for a quarter (Step 2).

    Delegates to the modern ``ingest_holdings`` job so holdings are
    ParseRun-backed and product-visible (fixes F6 — the legacy path wrote
    ``parse_run_id = NULL`` holdings invisible to the product query contract).
    Runs under the shared ``ingest_holdings:{quarter}`` lock, so a concurrent
    scheduled/dashboard ingest for the same quarter is reported as a conflict
    rather than run as an untracked second copy.

    ``quarter`` is a **report quarter** — the period the holdings are "as of",
    the same thing ``fetch-holdings`` means by it. The job widens to the filing
    quarter internally (13Fs for Q are filed within 45 days after Q ends); see
    ``_ingest_candidate_filings``.
    """
    from app.services.thirteenf_admin_dashboard import run_locked_job

    db = SessionLocal()
    try:
        result = run_locked_job(db, "ingest_holdings", {"quarter": quarter}, trigger_source="cli")
        typer.echo(f"{quarter}: {result['summary']}")
        if result.get("error"):
            typer.echo(f"Error: {result['error']}", err=True)
            raise typer.Exit(1)
    except typer.Exit:
        raise
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
    """Re-parse a single filing from its stored raw document (replay).

    Delegates to the ParseRun-backed ``reparse_accession`` job: the new run
    becomes ``is_current`` and the prior holdings are RETAINED (no destructive
    delete), so a reparse can never blank a filing out of the product surface
    (fixes F7 — the legacy path deleted the visible holdings and re-inserted
    ``parse_run_id = NULL`` invisible ones). Runs under the
    ``reparse_accession:{accession}`` lock.
    """
    from app.services.thirteenf_admin_dashboard import run_locked_job

    db = SessionLocal()
    try:
        result = run_locked_job(
            db, "reparse_accession", {"accession_no": accession}, trigger_source="cli"
        )
        if result.get("error"):
            typer.echo(f"Error: {result['error']}", err=True)
            raise typer.Exit(1)
        summary = result["summary"]
        typer.echo(
            f"Reparsed {accession}: {summary.get('holdings_count')} holdings "
            f"(parse_run {summary.get('parse_run_id')})."
        )
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
    from app.services.edgar_ingestion import (
        backfill_quarters,
        ingest_pending_holdings,
    )

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

        # Step 2: ingest the freshly-indexed (un-ingested) filings via the modern
        # job path. `ingest_pending_holdings` groups pending filings by the
        # REPORT quarter their filings belong to, and delegates each to the
        # ingest job so holdings are ParseRun-backed and product-visible (F6).
        #
        # The bound is exactly the report quarters Step 1 indexed. It used to be
        # widened to `{q} | {next_quarter_label(q)}` because `ingest_holdings`
        # windowed on the proxy period, so the newest report quarter's filings —
        # submitted the following calendar quarter — fell outside every
        # report-quarter window (F5). `_ingest_candidate_filings` now owns that
        # translation, so the widening here would only reach into a quarter this
        # backfill never indexed.
        #
        # The bound keeps `--quarters N` honest: without it, one permanently
        # stuck filing (e.g. a CIK-less manager) drags every historical quarter
        # into every run.
        scoped = set(results)
        summaries = ingest_pending_holdings(
            db, quarters=scoped, log=lambda m: typer.echo(f"  {m}")
        )
        if not summaries:
            typer.echo("  no pending holdings in the requested quarters")
        failed = [q for q, s in summaries.items() if isinstance(s, dict) and s.get("error")]
        if failed:
            typer.echo(
                f"Error: {len(failed)} quarter(s) failed: {', '.join(sorted(failed))}",
                err=True,
            )
            raise typer.Exit(1)
    except typer.Exit:
        raise
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
    """Reparse all stored filings from their raw docs (no network calls).

    Each accession goes through the ParseRun-backed ``reparse_accession`` job,
    which swaps ``is_current`` and RETAINS the prior holdings — non-destructive
    and product-visible (fixes F7). The legacy path deleted every filing's
    visible holdings and re-inserted invisible ``parse_run_id = NULL`` rows.
    """
    from app.models.institutions import Filing13F
    from app.services.thirteenf_admin_dashboard import run_locked_job
    import calendar
    from app.edgar.parsers.form_idx import quarter_to_year_qtr
    from datetime import date

    db = SessionLocal()
    try:
        query = db.query(Filing13F.accession_no).filter(Filing13F.raw_infotable_doc_id.isnot(None))
        if quarter:
            year, qtr = quarter_to_year_qtr(quarter)
            q_start = date(year, (qtr - 1) * 3 + 1, 1)
            end_month = qtr * 3
            q_end = date(year, end_month, calendar.monthrange(year, end_month)[1])
            query = query.filter(Filing13F.period_of_report.between(q_start, q_end))

        # Collect accession strings up front: each reparse_accession job commits,
        # which would expire ORM Filing rows mid-loop.
        accessions = [row[0] for row in query.order_by(Filing13F.period_of_report).all()]
        typer.echo(f"Reparsing {len(accessions)} filings...")

        total = 0
        failed = 0
        for accession in accessions:
            result = run_locked_job(
                db, "reparse_accession", {"accession_no": accession}, trigger_source="cli"
            )
            if result.get("error"):
                logger.error("  %s failed: %s", accession, result["error"])
                failed += 1
            else:
                total += result["summary"].get("holdings_count", 0) or 0

        typer.echo(f"Done: {total:,} holdings, {failed} failed")
        if failed:
            raise typer.Exit(1)
    except typer.Exit:
        raise
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
    """Map pending CUSIPs through OpenFIGI; Dataroma is not a CUSIP source."""
    from app.services.cusip_enrichment import enrich_cusips_from_openfigi

    db = SessionLocal()
    try:
        n = enrich_cusips_from_openfigi(db)
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
def backfill_attribution() -> None:
    """Recompute holding_attribution_status for DFND/OTR holdings (T3 combination
    fix). Run post-deploy; then recompute ownership_changes + Oracle's Lens for
    affected managers."""
    from app.services.thirteenf_holdings_ingest import backfill_holding_attribution

    db = SessionLocal()
    try:
        n = backfill_holding_attribution(db)
        db.commit()
        typer.echo(f"Re-attributed {n} holdings.")
    except Exception as exc:
        db.rollback()
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    app()
