"""The `quarterly_pipeline` stages must agree on what `quarter` means.

`fetch_quarter_index(Q)` treats `Q` as a **report quarter**: 13Fs for period Q
are filed within 45 days *after* Q ends, so it deliberately downloads the
form.idx of the *following* calendar quarter (`next_quarter_label(Q)`).

`ingest_holdings(Q)` used to window on `Filing13F.period_of_report` alone. For a
filing that has not been parsed yet, `period_of_report` is only a **proxy** — it
equals `filed_at`, and the true period is written later by
`backfill_period_routing`. So the rows `fetch_quarter_index(Q)` had just
inserted carried a proxy period of Q+1 and fell *outside* the window `Q`.

Consequence, reproduced from zero against real EDGAR data (2026-07-10):

    fetch_quarter_index:2025-Q4   75 filings inserted
    ingest_holdings:2025-Q4        0 filings processed   (7 ms, "succeeded")
    quality_check:2025-Q4          ran on an empty quarter
    compute_ownership_changes      ran on an empty quarter
    oracles_lens_score_backfill    0 signals

    fetch_quarter_index:2026-Q1   73 filings inserted (report quarter 2026-Q1,
                                  filed in 2026-Q2 → proxy period 2026-Q2)
    ingest_holdings:2026-Q1       75 filings processed — the *2025-Q4* batch

Every stage reported green. The newest report quarter is unreachable: no
pipeline for 2026-Q2 is ever enqueued (`latest_scoreable_quarter()` stops at
2026-Q1 until the 45-day window opens), so those 73 filings stay `pending`
forever. This is F5 — the defect T4 fixed in the CLI `backfill` path — alive in
the automated pipeline.
"""
from datetime import date, datetime, timezone

import pytest

from app.models.institutions import Filing13F, InstitutionManager, RawSourceDocument
from app.services.thirteenf_admin_dashboard import (
    _ingest_candidate_filings,
    quarter_window,
)


@pytest.fixture
def manager(db_session):
    m = InstitutionManager(
        cik="0001067983",
        legal_name="Berkshire Hathaway Inc",
        display_name="Warren Buffett - Berkshire Hathaway",
        name_normalized="berkshire hathaway",
        match_status="confirmed",
    )
    db_session.add(m)
    db_session.flush()
    return m


def _infotable_doc(db_session, accession):
    """`raw_infotable_doc_id` is a real FK — an ingested filing needs a real row."""
    doc = RawSourceDocument(
        source_system="edgar",
        document_type="infotable",
        accession_no=accession,
        source_url=f"https://sec.gov/{accession}/infotable.xml",
        body_path=f"/tmp/{accession}.xml",
    )
    db_session.add(doc)
    db_session.flush()
    return doc


def _filing(db_session, manager, *, accession, period, filed, ingested=False):
    f = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        form_type="13F-HR",
        period_of_report=period,
        filed_at=datetime.combine(filed, datetime.min.time(), tzinfo=timezone.utc),
        parse_status="succeeded" if ingested else "pending",
        raw_infotable_doc_id=(
            _infotable_doc(db_session, accession).id if ingested else None
        ),
    )
    db_session.add(f)
    db_session.flush()
    return f


def _accessions(filings):
    return {f.accession_no for f in filings}


def test_an_unparsed_filing_carries_a_filed_at_proxy_not_its_report_quarter(
    db_session, manager
):
    """The premise. A 2025-Q4 13F-HR is filed in Feb 2026, so its proxy is 2026-Q1."""
    f = _filing(
        db_session, manager,
        accession="0001067983-26-000001",
        period=date(2026, 2, 17),   # proxy == filed_at, set at index time
        filed=date(2026, 2, 17),
    )
    q4 = quarter_window("2025-Q4")
    assert not (q4.start <= f.period_of_report <= q4.end)


def test_ingest_for_a_report_quarter_picks_up_the_filings_the_index_just_inserted(
    db_session, manager
):
    """The regression. `ingest_holdings(2025-Q4)` must see the Feb-2026 filing."""
    fresh = _filing(
        db_session, manager,
        accession="0001067983-26-000001",
        period=date(2026, 2, 17),
        filed=date(2026, 2, 17),
    )

    picked = _ingest_candidate_filings(db_session, "2025-Q4")

    assert fresh.accession_no in _accessions(picked)


def test_ingest_still_picks_up_already_parsed_filings_of_that_report_quarter(
    db_session, manager
):
    """Heal / re-run path: after parsing, period_of_report is the TRUE quarter."""
    parsed = _filing(
        db_session, manager,
        accession="0001067983-26-000002",
        period=date(2025, 12, 31),  # corrected by backfill_period_routing
        filed=date(2026, 2, 17),
        ingested=True,
    )

    picked = _ingest_candidate_filings(db_session, "2025-Q4")

    assert parsed.accession_no in _accessions(picked)


def test_ingest_does_not_steal_the_next_quarters_unparsed_filings(
    db_session, manager
):
    """A filing filed in 2026-Q2 belongs to report quarter 2026-Q1, not 2025-Q4.

    Without this bound the fix would over-collect and every pipeline would drag
    the whole pending backlog into its own quarter's window.
    """
    next_quarter = _filing(
        db_session, manager,
        accession="0001067983-26-000003",
        period=date(2026, 5, 14),   # proxy: filed in 2026-Q2
        filed=date(2026, 5, 14),
    )

    picked = _ingest_candidate_filings(db_session, "2025-Q4")

    assert next_quarter.accession_no not in _accessions(picked)
    assert next_quarter.accession_no in _accessions(
        _ingest_candidate_filings(db_session, "2026-Q1")
    )


def test_an_already_parsed_filing_is_not_reclaimed_by_the_filed_quarter_window(
    db_session, manager
):
    """After parsing, a 2025-Q4 filing must not also answer to `ingest(2026-Q1)`.

    Its proxy period is gone — `period_of_report` is now 2025-12-31 — but the
    filed-quarter arm of the selection is restricted to un-ingested rows, so it
    cannot match. Otherwise every quarter would re-ingest its predecessor.
    """
    parsed = _filing(
        db_session, manager,
        accession="0001067983-26-000004",
        period=date(2025, 12, 31),
        filed=date(2026, 2, 17),
        ingested=True,
    )

    picked = _ingest_candidate_filings(db_session, "2026-Q1")

    assert parsed.accession_no not in _accessions(picked)


def test_a_pipeline_that_fetched_filings_but_ingested_none_is_not_green(
    db_session, monkeypatch
):
    """The cross-stage invariant that would have caught this class of bug.

    Per-stage statuses cannot see it: `ingest_holdings` legitimately returns
    "succeeded" when its query matches nothing. Only the *pair* — 75 filings
    inserted, 0 processed — reveals that the four downstream stages are about to
    score an empty quarter.
    """
    from app.services.thirteenf_admin_dashboard import execute_job_payload
    from app.services.edgar_quality import QualityReport

    monkeypatch.setattr(
        "app.services.edgar_ingestion.ingest_quarter_index",
        lambda session, quarter: 75,
    )
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard._execute_ingest_job",
        lambda session, job_type, payload: {
            "filings_processed": 0, "filings_failed": 0,
            "holdings_inserted": 0, "status": "succeeded",
        },
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_cusips_from_openfigi", lambda session: 0
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.bootstrap_stocks_from_cusip_map", lambda session: 0
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.backfill_stock_ids", lambda session: 0
    )
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.run_quality_checks",
        lambda session, quarter: QualityReport(),
    )
    monkeypatch.setattr(
        "app.services.oracles_lens.signal_weighted_score.compute_signal_weighted_scores",
        lambda session, **kw: {"quarter": kw["quarter"], "filings_scored": 0},
    )

    result = execute_job_payload(
        db_session, "quarterly_pipeline", {"quarter": "2025-Q4", "_job_id": 1}
    )

    assert result["status"] == "partial_success"
    assert "ingest_holdings processed 0" in result["pipeline_warning"]
    assert {s["status"] for s in result["stages"]} == {"succeeded"}


def test_a_pipeline_rerun_that_fetches_nothing_new_stays_green(
    db_session, monkeypatch
):
    """The legitimate no-op: idempotent re-run, 0 inserted and 0 processed."""
    from app.services.thirteenf_admin_dashboard import execute_job_payload
    from app.services.edgar_quality import QualityReport

    monkeypatch.setattr(
        "app.services.edgar_ingestion.ingest_quarter_index", lambda session, quarter: 0
    )
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard._execute_ingest_job",
        lambda session, job_type, payload: {
            "filings_processed": 0, "filings_failed": 0,
            "holdings_inserted": 0, "status": "succeeded",
        },
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_cusips_from_openfigi", lambda session: 0
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.bootstrap_stocks_from_cusip_map", lambda session: 0
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.backfill_stock_ids", lambda session: 0
    )
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.run_quality_checks",
        lambda session, quarter: QualityReport(),
    )
    monkeypatch.setattr(
        "app.services.oracles_lens.signal_weighted_score.compute_signal_weighted_scores",
        lambda session, **kw: {"quarter": kw["quarter"], "filings_scored": 0},
    )

    result = execute_job_payload(
        db_session, "quarterly_pipeline", {"quarter": "2025-Q4", "_job_id": 2}
    )

    assert result["status"] == "succeeded"
    assert "pipeline_warning" not in result


def test_the_newest_report_quarter_is_reachable(db_session, manager):
    """The bug's sharpest edge: 2026-Q1's filings are filed in 2026-Q2.

    `latest_scoreable_quarter()` never enqueues a 2026-Q2 pipeline until the
    45-day window opens, so under the old window these filings were unreachable
    by any automated run.
    """
    newest = _filing(
        db_session, manager,
        accession="0001067983-26-000005",
        period=date(2026, 5, 14),
        filed=date(2026, 5, 14),
    )

    picked = _ingest_candidate_filings(db_session, "2026-Q1")

    assert newest.accession_no in _accessions(picked)
