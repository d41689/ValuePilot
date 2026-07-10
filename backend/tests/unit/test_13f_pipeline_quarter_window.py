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


def _quarter_of(d):
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def _filing(
    db_session, manager, *, accession, period, filed, ingested=False,
    form_type="13F-HR", routed=None,
):
    """`routed` mirrors `backfill_period_routing`, which writes period_of_report,
    quarter_end_date and report_quarter in one pass. Defaults to `ingested`.
    Pass `routed=False, ingested=True` to model a job that died between Phase 1
    (infotable fetched) and Phase 2 (period routed).
    """
    is_routed = ingested if routed is None else routed
    f = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        form_type=form_type,
        period_of_report=period,
        filed_at=datetime.combine(filed, datetime.min.time(), tzinfo=timezone.utc),
        parse_status="succeeded" if ingested else "pending",
        report_quarter=_quarter_of(period) if is_routed else None,
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
    """After routing, a 2025-Q4 filing must not also answer to `ingest(2026-Q1)`."""
    parsed = _filing(
        db_session, manager,
        accession="0001067983-26-000004",
        period=date(2025, 12, 31),
        filed=date(2026, 2, 17),
        ingested=True,
    )

    picked = _ingest_candidate_filings(db_session, "2026-Q1")

    assert parsed.accession_no not in _accessions(picked)


def test_an_unrouted_filing_is_claimed_by_exactly_one_quarter(db_session, manager):
    """The P1 regression, reproduced by the external reviewer.

    A 2025-Q4 13F-HR filed 2026-02-17 carries proxy period 2026-02-17. Under the
    first fix it satisfied BOTH `ingest(2025-Q4)`'s filed-window arm AND
    `ingest(2026-Q1)`'s period-window arm. `lock_key` is
    `ingest_holdings:{quarter}`, so the two jobs do not exclude each other:
    whichever ran first parsed the other's filings, and the rightful quarter's
    downstream stages scored holdings it never ingested — with
    `filings_processed > 0`, so the D2 guard stayed silent.
    """
    proxy = _filing(
        db_session, manager,
        accession="0001067983-26-000010",
        period=date(2026, 2, 17),
        filed=date(2026, 2, 17),
    )

    claimed_by = [
        q for q in ("2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2")
        if proxy.accession_no in _accessions(_ingest_candidate_filings(db_session, q))
    ]

    assert claimed_by == ["2025-Q4"], f"claimed by {claimed_by}, must be exactly one"


def test_every_unrouted_filing_across_adjacent_quarters_is_claimed_once(
    db_session, manager
):
    """No un-routed row may be claimed twice, and none may be orphaned."""
    rows = {
        # (accession suffix, proxy period == filed_at) -> the quarter that owns it
        "000011": (date(2026, 2, 17), "2025-Q4"),   # 2025-Q4 HR, filed on time
        "000012": (date(2026, 5, 14), "2026-Q1"),   # 2026-Q1 HR, filed on time
        "000013": (date(2026, 8, 12), "2026-Q2"),   # 2026-Q2 HR, filed on time
    }
    for suffix, (period, _) in rows.items():
        _filing(
            db_session, manager,
            accession=f"0001067983-26-{suffix}", period=period, filed=period,
        )

    for suffix, (_, owner) in rows.items():
        accession = f"0001067983-26-{suffix}"
        claimed_by = [
            q for q in ("2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3")
            if accession in _accessions(_ingest_candidate_filings(db_session, q))
        ]
        assert claimed_by == [owner], f"{accession} claimed by {claimed_by}"


def test_a_filing_with_an_infotable_but_no_routed_period_uses_the_filed_window(
    db_session, manager
):
    """`raw_infotable_doc_id` is not a routing marker.

    Phase 1 of `_execute_ingest_job` sets the infotable link; Phase 2 routes the
    period. A job that dies between them leaves a row with an infotable and a
    still-proxy period. Keying the routed arm on `raw_infotable_doc_id` would
    file that row under its filed quarter instead of its report quarter.
    """
    half_done = _filing(
        db_session, manager,
        accession="0001067983-26-000014",
        period=date(2026, 2, 17),   # still the proxy
        filed=date(2026, 2, 17),
        ingested=True,              # infotable fetched
        routed=False,               # ...but Phase 2 never ran
    )

    assert half_done.accession_no in _accessions(
        _ingest_candidate_filings(db_session, "2025-Q4")
    )
    assert half_done.accession_no not in _accessions(
        _ingest_candidate_filings(db_session, "2026-Q1")
    )


def test_a_late_filed_13f_is_claimed_by_its_filed_quarters_pipeline(
    db_session, manager
):
    """A 2025-Q4 HR filed in 2026-Q3 (two quarters late).

    No `quarterly_pipeline(2025-Q4)` can reach it — its proxy is 2026-Q3, and a
    report-quarter job only widens to Q+1. It is claimed by `ingest(2026-Q2)`,
    whose filed-window is 2026-Q3, and routes to 2025-Q4 on parse. The pipeline
    must then say so rather than leave 2025-Q4's stale scores unannounced; see
    `test_a_pipeline_that_restated_another_quarter_says_so`.
    """
    late = _filing(
        db_session, manager,
        accession="0001067983-26-000015",
        period=date(2026, 7, 15),
        filed=date(2026, 7, 15),
    )

    claimed_by = [
        q for q in ("2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3")
        if late.accession_no in _accessions(_ingest_candidate_filings(db_session, q))
    ]

    assert claimed_by == ["2026-Q2"], f"claimed by {claimed_by}"


def test_an_amendment_restating_an_old_period_is_claimed_by_its_filed_quarter(
    db_session, manager
):
    """A 13F-HR/A filed 2026-05-14 restating 2025-Q1.

    Before parse its proxy is 2026-Q2, so `ingest(2026-Q1)` claims it. After
    routing, `report_quarter` becomes 2025-Q1 and only `ingest(2025-Q1)` will
    ever pick it up again — the re-run / heal path stays keyed to the truth.
    """
    amendment = _filing(
        db_session, manager,
        accession="0001067983-26-000016",
        period=date(2026, 5, 14),
        filed=date(2026, 5, 14),
        form_type="13F-HR/A",
    )
    assert amendment.accession_no in _accessions(
        _ingest_candidate_filings(db_session, "2026-Q1")
    )

    # backfill_period_routing corrects it
    amendment.period_of_report = date(2025, 3, 31)
    amendment.report_quarter = "2025-Q1"
    db_session.flush()

    assert amendment.accession_no in _accessions(
        _ingest_candidate_filings(db_session, "2025-Q1")
    )
    assert amendment.accession_no not in _accessions(
        _ingest_candidate_filings(db_session, "2026-Q1")
    )


def test_every_filing_shape_is_claimed_by_exactly_one_quarter(db_session):
    """The whole selection, stated as one property.

    Not "the cases I thought of" — every shape a `Filing13F` can hold. Claimed
    twice means two pipelines race for it (their `lock_key`s differ, so nothing
    stops them). Claimed zero times means it is stranded forever.

    The degraded row is the subtle one: `route_period` can return a REAL period
    with `report_quarter = None` (`PERIOD_TOO_FAR_FROM_QUARTER_END`,
    `PERIOD_WEEKEND_ADJUSTED_UNVERIFIABLE`). It is claimed by the filed-window
    arm of whichever quarter contains that period, gets re-routed on every pass,
    and is surfaced to a human through `filings_routing_needs_review`. Landing in
    an unexpected quarter is acceptable; being stranded is not.
    """
    shapes = {
        "unrouted, filed on time for 2025-Q4": (
            date(2026, 2, 17), date(2026, 2, 17), None, "2025-Q4",
        ),
        "unrouted, filed on time for 2026-Q1": (
            date(2026, 5, 14), date(2026, 5, 14), None, "2026-Q1",
        ),
        "unrouted, filed two quarters late": (
            date(2026, 7, 15), date(2026, 7, 15), None, "2026-Q2",
        ),
        "routed to 2025-Q4": (
            date(2025, 12, 31), date(2026, 2, 17), "2025-Q4", "2025-Q4",
        ),
        "routed to 2026-Q1": (
            date(2026, 3, 31), date(2026, 5, 14), "2026-Q1", "2026-Q1",
        ),
        "routed amendment restating 2025-Q1": (
            date(2025, 3, 31), date(2026, 5, 14), "2025-Q1", "2025-Q1",
        ),
        "degraded: real period, report_quarter NULL": (
            date(2025, 11, 15), date(2026, 2, 14), None, "2025-Q3",
        ),
        "half-done: infotable fetched, never routed": (
            date(2026, 2, 18), date(2026, 2, 18), None, "2025-Q4",
        ),
    }
    every_quarter = [f"{y}-Q{q}" for y in (2024, 2025, 2026, 2027) for q in (1, 2, 3, 4)]

    for index, (name, (period, filed, rq, _)) in enumerate(shapes.items()):
        # One manager each: `uq_filings_13f_latest_per_period` is on
        # (manager_id, period_of_report).
        m = InstitutionManager(
            cik=f"999999{index:04d}", legal_name=f"Shape {index}",
            name_normalized=f"shape-{index}", match_status="confirmed",
        )
        db_session.add(m)
        db_session.flush()
        _filing(
            db_session, m, accession=f"9999999998-26-{index:06d}",
            period=period, filed=filed, routed=rq is not None,
        )

    for index, (name, (_, _, _, owner)) in enumerate(shapes.items()):
        accession = f"9999999998-26-{index:06d}"
        claimed_by = [
            q for q in every_quarter
            if accession in _accessions(_ingest_candidate_filings(db_session, q))
        ]
        assert claimed_by == [owner], f"{name}: claimed by {claimed_by}, want [{owner}]"


def test_pending_ingest_quarters_speaks_the_same_language_as_the_ingest_job(
    db_session, manager
):
    """The CLI hands `pending_ingest_quarters()` output straight to the job.

    `ingest_pending_holdings` calls `run_locked_job("ingest_holdings", {"quarter": q})`
    for each label this returns, so the two must agree on what a quarter label
    means. They did not: the helper grouped by the *proxy* period (the filing
    quarter) while `_ingest_candidate_filings` reads a *report* quarter. The CLI
    would have handed the job a label one quarter ahead of the filings it was
    meant to parse, and ingested nothing.

    No test caught it because every CLI test injects its own `ingest_fn`, so the
    label's meaning was never exercised against the real selection.
    """
    from app.services.edgar_ingestion import pending_ingest_quarters

    db_session.query(Filing13F).delete()
    db_session.flush()
    pending = _filing(
        db_session, manager,
        accession="0001067983-26-000020",
        period=date(2026, 2, 17),   # proxy == filed_at
        filed=date(2026, 2, 17),
    )

    targets = pending_ingest_quarters(db_session)

    assert targets == ["2025-Q4"], f"got {targets}"
    reached = set()
    for quarter in targets:
        reached |= _accessions(_ingest_candidate_filings(db_session, quarter))
    assert pending.accession_no in reached, (
        "the CLI would call ingest_holdings with a quarter that selects nothing"
    )


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

    _stub_pipeline(monkeypatch, inserted=75, ingest_summary={
        "filings_processed": 0,
        "filings_for_requested_quarter": 0,
        "filings_routed_to_other_quarters": {},
        "filings_failed": 0, "holdings_inserted": 0,
    })

    result = execute_job_payload(
        db_session, "quarterly_pipeline", {"quarter": "2025-Q4", "_job_id": 1}
    )

    assert result["status"] == "partial_success"
    assert "ingest_holdings processed 0" in result["pipeline_warning"]
    assert {s["status"] for s in result["stages"]} == {"succeeded"}


def _stub_pipeline(monkeypatch, *, inserted, ingest_summary):
    from app.services.edgar_quality import QualityReport

    monkeypatch.setattr(
        "app.services.edgar_ingestion.ingest_quarter_index",
        lambda session, quarter: inserted,
    )
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard._execute_ingest_job",
        lambda session, job_type, payload: {**ingest_summary, "status": "succeeded"},
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_all_unmapped_holdings",
        lambda session, **kw: {
            "mappings_created": 0, "batches_run": 0, "new_stocks": 0,
            "holdings_linked": 0, "holdings_still_enrichable": 0,
        },
    )
    monkeypatch.setattr(
        "app.services.cusip_enrichment.enrich_stocks_from_edgar_tickers",
        lambda session: {"new_mappings": 0},
    )
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.run_quality_checks",
        lambda session, quarter: QualityReport(),
    )
    monkeypatch.setattr(
        "app.services.oracles_lens.signal_weighted_score.compute_signal_weighted_scores",
        lambda session, **kw: {"quarter": kw["quarter"], "filings_scored": 0},
    )


def test_a_pipeline_that_ingested_only_another_quarters_filings_is_not_green(
    db_session, monkeypatch
):
    """`filings_processed > 0` is too weak a signal.

    The P1 overlap produced exactly this shape: ingest(2026-Q1) parsed 2025-Q4's
    filings, reported 75 processed, and the D2 guard — which only compared
    inserted against processed — stayed silent while the remaining stages scored
    a quarter that had received nothing.
    """
    from app.services.thirteenf_admin_dashboard import execute_job_payload

    _stub_pipeline(monkeypatch, inserted=73, ingest_summary={
        "filings_processed": 75,
        "filings_for_requested_quarter": 0,
        "filings_routed_to_other_quarters": {"2025-Q4": 75},
        "filings_failed": 0, "holdings_inserted": 5023,
    })

    result = execute_job_payload(
        db_session, "quarterly_pipeline", {"quarter": "2026-Q1", "_job_id": 3}
    )

    assert result["status"] == "partial_success"
    assert "none belong to report quarter 2026-Q1" in result["pipeline_warning"]


def test_a_pipeline_that_restated_another_quarter_says_so(db_session, monkeypatch):
    """A late filing or an old-period amendment leaves that quarter's scores stale.

    The pipeline cannot recompute it (that quarter is not its own), but it must
    not stay green about it — name the quarters and the two jobs to re-run.
    """
    from app.services.thirteenf_admin_dashboard import execute_job_payload

    _stub_pipeline(monkeypatch, inserted=75, ingest_summary={
        "filings_processed": 75,
        "filings_for_requested_quarter": 72,
        "filings_routed_to_other_quarters": {"2025-Q1": 1, "2025-Q2": 1, "2025-Q3": 1},
        "filings_failed": 0, "holdings_inserted": 4798,
    })

    result = execute_job_payload(
        db_session, "quarterly_pipeline", {"quarter": "2025-Q4", "_job_id": 4}
    )

    assert result["status"] == "partial_success"
    assert result["quarters_needing_recompute"] == ["2025-Q1", "2025-Q2", "2025-Q3"]
    assert "oracles_lens_score_backfill" in result["pipeline_warning"]


def test_a_pipeline_rerun_that_fetches_nothing_new_stays_green(
    db_session, monkeypatch
):
    """The legitimate no-op: idempotent re-run, 0 inserted and 0 processed."""
    from app.services.thirteenf_admin_dashboard import execute_job_payload

    _stub_pipeline(monkeypatch, inserted=0, ingest_summary={
        "filings_processed": 0,
        "filings_for_requested_quarter": 0,
        "filings_routed_to_other_quarters": {},
        "filings_failed": 0, "holdings_inserted": 0,
    })

    result = execute_job_payload(
        db_session, "quarterly_pipeline", {"quarter": "2025-Q4", "_job_id": 2}
    )

    assert result["status"] == "succeeded"
    assert "pipeline_warning" not in result


def test_a_healthy_pipeline_that_ingested_its_own_quarter_stays_green(
    db_session, monkeypatch
):
    from app.services.thirteenf_admin_dashboard import execute_job_payload

    _stub_pipeline(monkeypatch, inserted=73, ingest_summary={
        "filings_processed": 73,
        "filings_for_requested_quarter": 73,
        "filings_routed_to_other_quarters": {},
        "filings_failed": 0, "holdings_inserted": 5684,
    })

    result = execute_job_payload(
        db_session, "quarterly_pipeline", {"quarter": "2026-Q1", "_job_id": 5}
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
