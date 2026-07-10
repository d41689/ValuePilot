"""The pipeline's enrichment stage must run CUSIP mapping to completion.

`stock_id` is the join key for every product surface: the Watchlist × 13F
columns, the stock-detail drawer, and Oracle's Lens eligibility
(`_eligible_stock_ids`). A holding whose CUSIP never reaches `cusip_ticker_map`
is invisible to all of them.

Two entry points existed, and only one converged:

* the standalone `enrich_cusip` job → `enrich_all_unmapped_holdings`, which
  loops batch-by-batch until no enrichable holding remains;
* the `quarterly_pipeline`'s `enrich_metadata` stage →
  `enrich_cusips_from_openfigi`, a **single batch of 100**.

So the manual path converged and the automated path did not. Measured from zero
against real EDGAR data (2026-07-10): 2084 distinct CUSIPs across 10707
holdings, and after five `enrich_metadata` runs only 363 CUSIPs were mapped —
each run added ~90-100 and stopped. 63.5% of holdings had no `stock_id`, which
is why Oracle's Lens produced only 309 signals.
"""
import pytest

from app.services.thirteenf_admin_dashboard import _execute_enrichment_metadata


def test_enrich_metadata_runs_cusip_mapping_to_completion(db_session, monkeypatch):
    """The stage must delegate to the converging loop, not one 100-row batch."""
    called: dict[str, object] = {}

    def fake_enrich_all(session, **kwargs):
        called["ran"] = True
        return {
            "mappings_created": 1721,
            "batches_run": 18,
            "new_stocks": 402,
            "holdings_linked": 9903,
            "holdings_still_unmapped": 0,
        }

    def fail_single_batch(session, *a, **kw):  # pragma: no cover - must not run
        raise AssertionError(
            "enrich_metadata called the single-batch enricher; it maps at most "
            "100 CUSIPs per quarterly_pipeline run and never converges"
        )

    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_all_unmapped_holdings", fake_enrich_all
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_cusips_from_openfigi", fail_single_batch
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_stocks_from_edgar_tickers",
        lambda session: {"new_mappings": 0},
    )

    result = _execute_enrichment_metadata(db_session, {"quarter": "2025-Q4"})

    assert called.get("ran") is True
    assert result["status"] == "succeeded"


def test_enrich_metadata_keeps_its_published_summary_keys(db_session, monkeypatch):
    """`enrich_metadata_summary.v1` is read by the admin UI and stored on JobRun."""
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_all_unmapped_holdings",
        lambda session, **kw: {
            "mappings_created": 92, "batches_run": 1, "new_stocks": 7,
            "holdings_linked": 3907, "holdings_still_unmapped": 6800,
        },
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_stocks_from_edgar_tickers",
        lambda session: {"new_mappings": 0},
    )

    result = _execute_enrichment_metadata(db_session, {"quarter": "2025-Q4"})

    for key in ("cusip_mappings", "mappings_created", "new_stocks",
                "holdings_linked", "edgar_stock_enrichment", "status"):
        assert key in result, f"{key} dropped from enrich_metadata summary"
    assert result["cusip_mappings"] == result["mappings_created"] == 92


def test_enrich_metadata_reports_what_it_could_not_map(db_session, monkeypatch):
    """Leftovers must be visible: a converged run that still can't map is a finding.

    Unlinked holdings are silently absent from Oracle's Lens, so "how many are
    still unmapped" belongs in the job summary, not only in a log line.
    """
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_all_unmapped_holdings",
        lambda session, **kw: {
            "mappings_created": 1721, "batches_run": 18, "new_stocks": 402,
            "holdings_linked": 9903, "holdings_still_unmapped": 41,
        },
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_stocks_from_edgar_tickers",
        lambda session: {"new_mappings": 0},
    )

    result = _execute_enrichment_metadata(db_session, {"quarter": "2025-Q4"})

    assert result["holdings_still_unmapped"] == 41
    assert result["batches_run"] == 18
