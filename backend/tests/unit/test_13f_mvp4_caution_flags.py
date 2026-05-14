"""MVP4-05 caution flags surface tests."""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    ParseRun13F,
    QualityFinding13F,
    QualityReport13F,
)
from app.models.oracles_lens import OraclesLensSignal
from app.models.stocks import Stock
from app.services.oracles_lens.caution_flags import (
    CAUTION_FLAG_REGISTRY,
    CAVEAT_AMENDMENT_FAILED,
    CAVEAT_AMENDMENTS_PENDING,
    enrich_caveat_codes,
)
from app.services.oracles_lens.signal_weighted_score import (
    build_oracles_lens_response,
    compute_signal_weighted_scores,
)
from app.services.thirteenf_quality_codes import (
    OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION,
)


_CIK_SEQ = count(9995500000)
_ACC_SEQ = count(970001)
_STOCK_SEQ = count(95001)


# ===========================================================================
# Registry
# ===========================================================================


def test_registry_covers_all_canonical_codes():
    required_codes = {
        "CONFIDENTIAL_TREATMENT",
        "PARTIAL_COVERAGE",
        "AMENDMENTS_PENDING",
        "AMENDMENT_FAILED",
        "OWNERSHIP_CHANGES_NEEDS_RECOMPUTE",
        "HISTORICAL_BACKFILL_NEEDS_VALIDATION",
        "NT_QUARTER_STREAK_BREAK",
        "PRE_2023_PRE_HISTORY_UNAVAILABLE",
        # The score-emitted spelling is also registered so the
        # persisted flat list can be enriched without lossy lookup.
        "stale_until_recompute",
    }
    actual_codes = set(CAUTION_FLAG_REGISTRY.keys())
    missing = required_codes - actual_codes
    assert not missing, f"caution-flag registry missing canonical codes: {missing}"


def test_registry_severity_tiers_match_score_confidence_demotion():
    """Severity tiers must mirror the worst-wins rule in
    determine_score_confidence so a UI rendering 'this score is
    `low` because X' can map back to the same caveat that triggered
    the demotion.
    """
    low_tier = {
        "OWNERSHIP_CHANGES_NEEDS_RECOMPUTE",
        "HISTORICAL_BACKFILL_NEEDS_VALIDATION",
        "stale_until_recompute",
    }
    medium_tier = {
        "CONFIDENTIAL_TREATMENT",
        "PARTIAL_COVERAGE",
        "AMENDMENTS_PENDING",
        "AMENDMENT_FAILED",
        "NT_QUARTER_STREAK_BREAK",
        "PRE_2023_PRE_HISTORY_UNAVAILABLE",
    }
    for code in low_tier:
        assert CAUTION_FLAG_REGISTRY[code].severity == "low", code
    for code in medium_tier:
        assert CAUTION_FLAG_REGISTRY[code].severity == "medium", code


# ===========================================================================
# enrich_caveat_codes
# ===========================================================================


def test_enrich_dedupes_score_emitted_and_readiness_aliases():
    """stale_until_recompute and OWNERSHIP_CHANGES_NEEDS_RECOMPUTE
    describe the same finding; the surface must return one entry
    using the canonical readiness vocabulary."""
    structured = enrich_caveat_codes([
        "stale_until_recompute",
        "OWNERSHIP_CHANGES_NEEDS_RECOMPUTE",
    ])
    codes = [item["code"] for item in structured]
    assert codes == ["OWNERSHIP_CHANGES_NEEDS_RECOMPUTE"], codes


def test_enrich_preserves_order_of_first_occurrence():
    structured = enrich_caveat_codes([
        "CONFIDENTIAL_TREATMENT",
        "stale_until_recompute",
        "PARTIAL_COVERAGE",
        "CONFIDENTIAL_TREATMENT",  # duplicate, should be ignored
    ])
    codes = [item["code"] for item in structured]
    assert codes == [
        "CONFIDENTIAL_TREATMENT",
        "OWNERSHIP_CHANGES_NEEDS_RECOMPUTE",
        "PARTIAL_COVERAGE",
    ]


def test_enrich_surfaces_unknown_codes_with_unknown_severity():
    """Forward-compat: unknown codes don't get silently dropped;
    they surface with severity=unknown so the regression is visible
    in QA."""
    structured = enrich_caveat_codes(["BRAND_NEW_CODE_42"])
    assert len(structured) == 1
    assert structured[0]["code"] == "BRAND_NEW_CODE_42"
    assert structured[0]["severity"] == "unknown"


def test_enrich_empty_list_returns_empty_list():
    assert enrich_caveat_codes([]) == []


# ===========================================================================
# DB integration — amendment_status caveat collection
# ===========================================================================


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv4-05 Mgr {cik}",
        legal_name=f"Mv4-05 Mgr {cik}",
        edgar_legal_name=f"Mv4-05 Mgr {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
        manager_type="long_term_fundamental",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session) -> Stock:
    seq = next(_STOCK_SEQ)
    stock = Stock(
        ticker=f"F4{seq:05d}"[-10:],
        exchange="NYSE",
        company_name=f"F4Co {seq}",
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(
    db_session, manager: InstitutionManager, *, amendment_status: str = "no_amendments_seen",
) -> Filing13F:
    accession = f"00099550-26-{next(_ACC_SEQ):06d}"
    period_end = date(2026, 3, 31)
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=period_end,
        filed_at=period_end,
        filing_date=period_end,
        accepted_at=datetime(2026, 3, 31, 17, tzinfo=timezone.utc),
        form_type="13F-HR",
        report_type="holdings_report",
        coverage_completeness="complete",
        coverage_type="normal",
        quarter_end_date=period_end,
        report_quarter="2026-Q1",
        official_filing_deadline=date(2026, 5, 15),
        parse_status="succeeded",
        is_active_for_manager_period=True,
        is_latest_for_period=True,
        amendment_status=amendment_status,
        computed_total_value_thousands=1_000_000,
        reported_total_value_thousands=1_000_000,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _holding(db_session, filing: Filing13F, stock: Stock) -> Holding13F:
    pr = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="test",
        fingerprint_version="v1",
        status="succeeded",
        holdings_count=1,
        is_current=True,
    )
    db_session.add(pr)
    db_session.flush()
    holding = Holding13F(
        filing_id=filing.id,
        parse_run_id=pr.id,
        manager_id=filing.manager_id,
        accession_number=filing.accession_number,
        report_quarter=filing.report_quarter,
        quarter_end_date=filing.quarter_end_date,
        row_fingerprint=f"{filing.accession_number}-{stock.id}",
        holding_row_fingerprint=f"{filing.accession_number}-{stock.id}",
        cusip=f"{stock.id:09d}",
        issuer_name=f"Issuer {stock.id}",
        name_of_issuer=f"Issuer {stock.id}",
        title_of_class="COM",
        value_thousands=50_000,
        value_raw="50000000",
        value_unit_raw="dollars",
        value_parse_rule="schema_dollars",
        value_usd=50_000_000,
        shares=1000,
        ssh_prnamt=1000,
        share_type="SH",
        ssh_prnamt_type="SH",
        investment_discretion="SOLE",
        holding_attribution_status="direct",
        voting_sole=1000,
        voting_shared=0,
        voting_none=0,
        stock_id=stock.id,
        cusip_mapping_status="linked",
        source_row_index=0,
    )
    db_session.add(holding)
    db_session.flush()
    return holding


def test_amendments_pending_filing_emits_caveat(db_session):
    stock = _stock(db_session)
    # One holder filed an amendment-pending filing; the others are
    # clean. MVP5-02 excludes the amendment-pending holder from the
    # score aggregate but still surfaces its caveat at the page level,
    # so we pad clean holders to 3 so the post-exclusion count stays
    # at or above the min_holders=3 floor.
    pending_mgr = _manager(db_session)
    _holding(db_session, _filing(db_session, pending_mgr, amendment_status="amendments_pending"), stock)
    for _ in range(3):
        mgr = _manager(db_session)
        _holding(db_session, _filing(db_session, mgr), stock)

    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    signal = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one()
    )
    assert CAVEAT_AMENDMENTS_PENDING in (signal.caution_flag_codes or [])


def test_amendment_failed_filing_emits_caveat(db_session):
    stock = _stock(db_session)
    failed_mgr = _manager(db_session)
    _holding(db_session, _filing(db_session, failed_mgr, amendment_status="amendment_failed"), stock)
    for _ in range(3):
        # MVP5-02: 3 clean + 1 excluded amendment-failed = 3 included
        # after exclusion. Same rationale as amendments_pending above.
        mgr = _manager(db_session)
        _holding(db_session, _filing(db_session, mgr), stock)

    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    signal = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one()
    )
    assert CAVEAT_AMENDMENT_FAILED in (signal.caution_flag_codes or [])


# ===========================================================================
# Read API surface
# ===========================================================================


def test_build_oracles_lens_response_exposes_structured_caution_flags(db_session):
    stock = _stock(db_session)
    pending_mgr = _manager(db_session)
    _holding(db_session, _filing(db_session, pending_mgr, amendment_status="amendments_pending"), stock)
    # MVP5-02: pad clean holders to 3 so the amendments-pending
    # exclusion still leaves the included count at the
    # min_holders=3 floor.
    for _ in range(3):
        mgr = _manager(db_session)
        _holding(db_session, _filing(db_session, mgr), stock)
    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    payload = build_oracles_lens_response(db_session, period="2026-Q1")
    item = next((i for i in payload["items"] if i["stock_id"] == stock.id), None)
    assert item is not None

    # Flat field preserved for backwards compat.
    assert isinstance(item["caution_flag_codes"], list)
    assert "AMENDMENTS_PENDING" in item["caution_flag_codes"]

    # New structured field.
    assert "caution_flags" in item
    by_code = {flag["code"]: flag for flag in item["caution_flags"]}
    assert "AMENDMENTS_PENDING" in by_code
    flag = by_code["AMENDMENTS_PENDING"]
    assert flag["severity"] == "medium"
    assert flag["scope"] == "row"
    assert flag["label"]


def test_confidence_demotion_reasons_surface_low_and_medium_caveats(db_session):
    """MVP4 review SME #5/#6 finding: when a stock has both a low and a
    medium caveat, ``confidence_demotion_reasons`` must list both, not
    just the tier-winning ones. The pre-fix loop silently dropped the
    medium caveats once the low tier won."""
    stock = _stock(db_session)

    # Holder A: has BOTH a low caveat (STALE_UNTIL_RECOMPUTE via an open
    # OWNERSHIP_CHANGE finding) and a medium caveat (AMENDMENTS_PENDING).
    multi_caveat_mgr = _manager(db_session)
    filing_a = _filing(
        db_session, multi_caveat_mgr, amendment_status="amendments_pending",
    )
    _holding(db_session, filing_a, stock)
    seed_report = QualityReport13F(
        quarter="2026-Q1",
        status="warning",
        error_count=0,
        warning_count=1,
        info_count=0,
        summary="seed: corporate-action recompute pending",
        checked_at=datetime(2026, 3, 31, tzinfo=timezone.utc),
    )
    db_session.add(seed_report)
    db_session.flush()
    db_session.add(
        QualityFinding13F(
            validation_run_id=seed_report.id,
            rule_code=OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION,
            severity="warning",
            entity_type="ownership_change",
            entity_id=None,
            quarter="2026-Q1",
            manager_id=multi_caveat_mgr.id,
            accession_number=filing_a.accession_number,
            detail="seed: corporate-action recompute pending",
            value_json={},
            status="open",
            first_seen_at=datetime(2026, 3, 31, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 3, 31, tzinfo=timezone.utc),
        )
    )
    db_session.flush()

    # MVP5-02: the multi_caveat_mgr is amendments-pending so its
    # contribution is excluded from the score aggregate. Pad clean
    # holders to 3 so the post-exclusion included count satisfies the
    # min_holders=3 floor. The excluded holder's caveats
    # (STALE_UNTIL_RECOMPUTE from the open finding +
    # AMENDMENTS_PENDING from filing.amendment_status) still flow into
    # aggregate_caveats so confidence_demotion_reasons surfaces both.
    for _ in range(3):
        mgr = _manager(db_session)
        _holding(db_session, _filing(db_session, mgr), stock)

    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    payload = build_oracles_lens_response(db_session, period="2026-Q1")
    item = next((i for i in payload["items"] if i["stock_id"] == stock.id), None)
    assert item is not None
    reasons = item.get("score_explanation", {}).get(
        "confidence_demotion_reasons", []
    )
    reasons_by_code = {entry["code"]: entry for entry in reasons}

    # The low caveat is in the list with its own tier label.
    assert "stale_until_recompute" in reasons_by_code
    assert reasons_by_code["stale_until_recompute"]["demoted_to"] == "low_confidence"

    # The medium caveat survives instead of being silently dropped.
    assert "AMENDMENTS_PENDING" in reasons_by_code
    assert reasons_by_code["AMENDMENTS_PENDING"]["demoted_to"] == "medium_confidence"
