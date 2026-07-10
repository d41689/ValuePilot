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
from datetime import date, datetime, timezone

import pytest

from app.models.institutions import (
    CusipTickerMap,
    Filing13F,
    Holding13F,
    InstitutionManager,
)
from app.models.stocks import Stock
from app.services.cusip_enrichment import _count_enrichable_holdings
from app.services.thirteenf_admin_dashboard import _execute_enrichment_metadata


def _clear_holdings(db_session):
    db_session.query(Holding13F).delete()
    db_session.query(CusipTickerMap).delete()
    db_session.flush()


def _manager(db_session):
    m = InstitutionManager(
        cik="0001067983", legal_name="Berkshire Hathaway Inc",
        name_normalized="berkshire-enrich", match_status="confirmed",
    )
    db_session.add(m)
    db_session.flush()
    return m


def _filing(db_session, manager):
    f = Filing13F(
        manager_id=manager.id, accession_no="0001067983-26-000099",
        form_type="13F-HR", period_of_report=date(2025, 12, 31),
        filed_at=datetime(2026, 2, 17, tzinfo=timezone.utc),
        report_quarter="2025-Q4", parse_status="succeeded",
    )
    db_session.add(f)
    db_session.flush()
    return f


def _stock(db_session):
    s = Stock(ticker="AAPL", company_name="Apple Inc", exchange="US")
    db_session.add(s)
    db_session.flush()
    return s


def _holding(db_session, filing, cusip, status, *, stock_id=None, mapped=False):
    if mapped:
        # OpenFIGI was consulted and returned nothing usable. The CUSIP has a map
        # row, so it drops out of the enrichable pool — permanently unlinked.
        db_session.add(CusipTickerMap(cusip=cusip, ticker=None, confidence="none"))
    h = Holding13F(
        filing_id=filing.id, manager_id=filing.manager_id, cusip=cusip,
        issuer_name="Test Issuer", cusip_mapping_status=status, stock_id=stock_id,
        row_fingerprint=f"fp-{cusip}", value_thousands=1000,   # both NOT NULL
    )
    db_session.add(h)
    return h


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
            "holdings_still_enrichable": 0,
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
            "holdings_linked": 3907, "holdings_still_enrichable": 6800,
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
            "holdings_linked": 9903, "holdings_still_enrichable": 41,
        },
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_stocks_from_edgar_tickers",
        lambda session: {"new_mappings": 0},
    )

    result = _execute_enrichment_metadata(db_session, {"quarter": "2025-Q4"})

    assert result["holdings_still_enrichable"] == 41
    assert result["batches_run"] == 18


def test_a_drained_openfigi_queue_does_not_mean_every_holding_is_linked(
    db_session, monkeypatch
):
    """`holdings_still_enrichable == 0` and 527 holdings with no `stock_id`.

    `_count_enrichable_holdings` is the OpenFIGI work queue. It excludes
    `needs_review` (the human adjudication queue) and any CUSIP that already has
    a `cusip_ticker_map` row — including one that resolved to nothing. Those
    holdings stay unlinked, so they stay invisible to Oracle's Lens.

    Reading a drained queue as "everything is linked" is the exact misreading the
    old field name `holdings_still_unmapped` invited (external review P2). The
    summary must carry the product-visible truth: `stock_id IS NULL`, bucketed.
    """
    _clear_holdings(db_session)
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    # Mapped and linked — invisible to nobody.
    _holding(db_session, filing, "037833100", "linked", stock_id=_stock(db_session).id)
    # The three ways a holding stays unlinked while the OpenFIGI queue is empty.
    _holding(db_session, filing, "111111111", "needs_review")
    _holding(db_session, filing, "222222222", "unresolved", mapped=True)
    _holding(db_session, filing, "33333333Z", "invalid_cusip")
    db_session.flush()

    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_all_unmapped_holdings",
        lambda session, **kw: {
            "mappings_created": 0, "batches_run": 0, "new_stocks": 0,
            "holdings_linked": 0,
            "holdings_still_enrichable": _count_enrichable_holdings(session),
        },
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_stocks_from_edgar_tickers",
        lambda session: {"new_mappings": 0},
    )

    result = _execute_enrichment_metadata(db_session, {"quarter": "2025-Q4"})

    assert result["holdings_still_enrichable"] == 0, "the OpenFIGI queue is drained"
    assert result["holdings_unlinked_total"] == 3, "but three holdings have no stock_id"
    assert result["holdings_unlinked_by_status"] == {
        "invalid_cusip": 1, "needs_review": 1, "unresolved": 1,
    }
