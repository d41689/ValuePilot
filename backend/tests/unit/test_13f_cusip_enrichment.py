import pytest
from datetime import date
from unittest.mock import patch, MagicMock

from app.models.institutions import CusipTickerMap, Filing13F, Holding13F, InstitutionManager
from app.services.cusip_enrichment import (
    _has_overlap,
    upsert_cusip_mapping,
    evaluate_openfigi_matches,
    enrich_unmapped_holdings,
    enrich_all_unmapped_holdings,
    enrich_cusips_from_openfigi,
    enrich_from_dataroma,
)
from app.services.cusip_validation import is_valid_cusip
from app.openfigi.client import OpenFigiClient


def test_is_valid_cusip():
    assert not is_valid_cusip(None)
    assert not is_valid_cusip("12345678")  # too short
    assert not is_valid_cusip("000000000") # all zeros
    assert not is_valid_cusip("12345678!") # invalid format
    assert is_valid_cusip("037833100")   # Apple CUSIP

    # 2026-05-22: pin the invariant that letter-prefixed CINS identifiers
    # (e.g. ``G0403H108`` Aon plc, ``L8681T102`` Spotify, ``N07059210`` ASML)
    # PASS the validator. ``enrich_unmapped_holdings`` only routes through
    # ``OpenFigiClient.map_cusips`` for identifiers that pass this check; if
    # the validator started rejecting letters, the new CINS → ``ID_CINS``
    # routing logic in ``openfigi/client.py`` would be silently bypassed and
    # every foreign-issuer holding would land in ``invalid_cusip``.
    assert is_valid_cusip("G0403H108")   # Aon plc CINS
    assert is_valid_cusip("L8681T102")   # Spotify CINS
    assert is_valid_cusip("N07059210")   # ASML CINS


def test_evaluate_openfigi_matches():
    # Single exact US Common Stock match.
    matches = [{"ticker": "AAPL", "name": "Apple Inc", "securityType": "Common Stock", "exchCode": "US"}]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "high"
    assert ticker == "AAPL"

    # 2026-05-22: an Option-only US match must NOT auto-link to the
    # underlying — Options share the CUSIP only by coincidence. The new
    # auto-confirm rule allowlists equity instruments only (Common Stock /
    # Depositary Receipt / REIT / ETP / Mutual Fund / Open-End Fund /
    # Preferred Stock); Option-only / Warrant-only / Future-only land in
    # review_needed:medium just as before.
    matches = [{"ticker": "AAPL", "name": "Apple Inc", "securityType": "Option", "exchCode": "US"}]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "review_needed:medium"
    assert ticker == "AAPL"

    # Multiple US-exchange matches on different tickers — still review_needed.
    matches = [
        {"ticker": "A", "name": "A", "securityType": "Common Stock", "exchCode": "US"},
        {"ticker": "B", "name": "B", "securityType": "Common Stock", "exchCode": "US"}
    ]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "review_needed:low"
    assert ticker is None

    # No matches.
    conf, reason, ticker, name = evaluate_openfigi_matches([])
    assert conf == "low"
    assert ticker is None


def test_evaluate_openfigi_matches_us_adr_auto_confirms():
    """ADRs (single US ticker across all US listings) should auto-confirm.

    Pre-fix: ``securityType='ADR'`` + many non-US cross-listings landed in
    review_needed:low ("Multiple matches, no US Common Stock listing"). The
    13F filer reports it as US-traded under the ADR ticker, so auto-confirm
    is correct. The literal string is ``ADR`` as OpenFIGI returns it (not
    ``Depositary Receipt``).
    """
    matches = [
        {"ticker": "TSM", "name": "TAIWAN SEMICONDUCTOR-SP ADR", "securityType": "ADR", "exchCode": "US"},
        {"ticker": "TSM", "name": "TAIWAN SEMICONDUCTOR-SP ADR", "securityType": "ADR", "exchCode": "UN"},
        {"ticker": "2330", "name": "TAIWAN SEMICONDUCTOR", "securityType": "Common Stock", "exchCode": "TT"},
    ]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "high"
    assert ticker == "TSM"


def test_evaluate_openfigi_matches_us_gdr_auto_confirms():
    """Global Depositary Receipts (a few of these trade on US OTC as well)
    report securityType ``GDR``. When a single US-exchange listing exists,
    auto-confirm — same shape as ADRs."""
    matches = [
        {"ticker": "OZONY", "name": "OZON HOLDINGS PLC-GDR", "securityType": "GDR", "exchCode": "US"},
    ]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "high"
    assert ticker == "OZONY"


def test_evaluate_openfigi_matches_us_etp_auto_confirms():
    """An ETP (SPY) with a single US ticker should auto-confirm."""
    matches = [
        {"ticker": "SPY", "name": "SPDR S&P 500 ETF TRUST", "securityType": "ETP", "exchCode": "US"},
        {"ticker": "SPY", "name": "SPDR S&P 500 ETF TRUST", "securityType": "ETP", "exchCode": "UN"},
    ]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "high"
    assert ticker == "SPY"


def test_evaluate_openfigi_matches_us_reit_auto_confirms():
    """A US REIT (AMT) with a single US ticker should auto-confirm."""
    matches = [
        {"ticker": "AMT", "name": "AMERICAN TOWER CORP", "securityType": "REIT", "exchCode": "US"},
    ]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "high"
    assert ticker == "AMT"


def test_evaluate_openfigi_matches_tracking_stock_auto_confirms():
    """Liberty Media tracking stocks (FWONK / LSXMK) report securityType
    ``Tracking Stk`` in OpenFIGI but are tradable US common equity from the
    13F filer's perspective."""
    matches = [
        {"ticker": "FWONK", "name": "LIBERTY MEDIA FRMULA1 C", "securityType": "Tracking Stk", "exchCode": "US"},
        {"ticker": "FWONK", "name": "LIBERTY MEDIA FRMULA1 C", "securityType": "Tracking Stk", "exchCode": "UN"},
    ]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "high"
    assert ticker == "FWONK"


def test_evaluate_openfigi_matches_mlp_auto_confirms():
    """Master Limited Partnerships (ARLP, EPD, …) report securityType
    ``MLP`` and are tradable US common-equity instruments from a 13F
    filer's perspective."""
    matches = [
        {"ticker": "ARLP", "name": "ALLIANCE RESOURCE PARTNERS", "securityType": "MLP", "exchCode": "US"},
        {"ticker": "ARLP", "name": "ALLIANCE RESOURCE PARTNERS", "securityType": "MLP", "exchCode": "UQ"},
    ]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "high"
    assert ticker == "ARLP"


def test_evaluate_openfigi_matches_bond_stays_in_review():
    """Bond / convertible CUSIPs (single match on TRACE exchange) must NOT
    auto-link. Pre-fix and post-fix this stays in review_needed:medium so
    the admin can decide whether to map it to the issuer or leave it."""
    matches = [
        {"ticker": "AFRM 0 11/15/26", "name": "AFFIRM HLDGS INC", "securityType": "US DOMESTIC", "exchCode": "TRACE"},
    ]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "review_needed:medium"


def test_evaluate_openfigi_matches_ny_reg_shrs_auto_confirms():
    """ASML and similar Dutch / European dual-listed equities report
    securityType ``NY Reg Shrs`` (New York Registry Shares) on US exchanges.
    """
    matches = [
        {"ticker": "ASML", "name": "ASML HOLDING NV-NY REG SHS", "securityType": "NY Reg Shrs", "exchCode": "US"},
    ]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "high"
    assert ticker == "ASML"


def test_evaluate_openfigi_matches_us_ticker_conflict_still_review():
    """Cross-listed US tickers on the SAME CUSIP must still go to review.

    Safety regression: the relaxed rule must not auto-link when two different
    US tickers share the CUSIP (rare but possible across share classes).
    """
    matches = [
        {"ticker": "GOOG", "name": "Alphabet Inc Class C", "securityType": "Common Stock", "exchCode": "US"},
        {"ticker": "GOOGL", "name": "Alphabet Inc Class A", "securityType": "Common Stock", "exchCode": "US"},
    ]
    conf, reason, ticker, name = evaluate_openfigi_matches(matches)
    assert conf == "review_needed:low"
    assert ticker is None


def test_openfigi_enrichment_entrypoints_are_explicitly_non_dataroma(monkeypatch, db_session):
    calls: list[int] = []

    def fake_enrich(session, *, client=None, limit=100):
        calls.append(limit)
        return 7

    monkeypatch.setattr("app.services.cusip_enrichment.enrich_unmapped_holdings", fake_enrich)

    assert enrich_cusips_from_openfigi(db_session, limit=25) == 7
    assert enrich_from_dataroma(db_session, limit=30) == 7
    assert calls == [25, 30]
    assert "Dataroma is not used" in enrich_cusips_from_openfigi.__doc__
    assert "does not call Dataroma" in enrich_from_dataroma.__doc__


def test_upsert_cusip_mapping_no_overlap(db_session):
    cusip = "111111111"
    
    # 1. Insert first mapping
    upsert_cusip_mapping(
        db_session, cusip=cusip, ticker="A", issuer_name="Corp A", source="test",
        valid_from=date(2023, 1, 1), valid_to=date(2023, 3, 31)
    )
    
    # 2. Insert non-overlapping mapping
    upsert_cusip_mapping(
        db_session, cusip=cusip, ticker="A", issuer_name="Corp A", source="test",
        valid_from=date(2023, 4, 1), valid_to=None
    )
    
    mappings = db_session.query(CusipTickerMap).filter_by(cusip=cusip).all()
    assert len(mappings) == 2
    assert mappings[0].confidence == "medium" # default
    assert mappings[1].confidence == "medium"


def test_upsert_cusip_mapping_with_overlap(db_session):
    cusip = "222222222"
    
    # 1. Insert first mapping open-ended
    upsert_cusip_mapping(
        db_session, cusip=cusip, ticker="B", issuer_name="Corp B", source="test",
        valid_from=date(2023, 1, 1), valid_to=None
    )
    
    # 2. Insert overlapping mapping
    m2 = upsert_cusip_mapping(
        db_session, cusip=cusip, ticker="B", issuer_name="Corp B", source="test",
        valid_from=date(2023, 6, 1), valid_to=None
    )
    
    # The overlapping mapping gets flagged for review
    assert m2.confidence.startswith("review_needed:")


def test_enrich_unmapped_holdings(db_session):
    cusip = "037833100" # Apple
    bad_cusip = "000000000"

    h_valid = Holding13F(
        filing_id=1, parse_run_id=1, manager_id=1, accession_number="0",
        report_quarter="2023-Q1", row_fingerprint="f1",
        cusip=cusip, issuer_name="APPLE INC", value_thousands=100,
        cusip_mapping_status="pending_mapping"
    )
    h_invalid = Holding13F(
        filing_id=1, parse_run_id=1, manager_id=1, accession_number="0",
        report_quarter="2023-Q1", row_fingerprint="f2",
        cusip=bad_cusip, issuer_name="BAD", value_thousands=100,
        cusip_mapping_status="pending_mapping"
    )
    
    # We need to bypass the foreign key checks for testing by just creating dummy filing and parse run,
    # or just mocking the whole query? It's better to just mock the db_session query output to avoid full DB setup.
    pass

@patch("app.services.cusip_enrichment.OpenFigiClient")
def test_enrich_unmapped_holdings_mocked(MockClient, db_session):
    # Setup mock
    mock_client = MockClient.return_value
    mock_client.map_cusips.return_value = [
        [{"ticker": "AAPL", "name": "Apple Inc", "securityType": "Common Stock", "exchCode": "US"}]
    ]
    
    # In a real integration test we'd create the Filing, ParseRun, Manager etc.
    # But for now we just verify the validation logic directly.
    pass


_AAPL_OPENFIGI = [
    [{"ticker": "AAPL", "name": "Apple Inc", "securityType": "Common Stock", "exchCode": "US"}]
]


def test_enrich_closes_a_self_constructed_client(db_session, monkeypatch):
    """enrich_unmapped_holdings closes the OpenFigiClient it creates itself."""
    _seed_holdings(db_session, [("037833100", "unresolved")])
    mock_client = MagicMock()
    mock_client.map_cusips.return_value = _AAPL_OPENFIGI
    monkeypatch.setattr(
        "app.services.cusip_enrichment.OpenFigiClient", lambda: mock_client
    )

    enrich_unmapped_holdings(db_session)  # no client passed -> self-constructs

    mock_client.map_cusips.assert_called_once()
    mock_client.close.assert_called_once()


def test_enrich_does_not_close_an_injected_client(db_session):
    """An injected client is the caller's to manage — enrich must not close it."""
    _seed_holdings(db_session, [("037833100", "unresolved")])
    injected = MagicMock()
    injected.map_cusips.return_value = _AAPL_OPENFIGI

    enrich_unmapped_holdings(db_session, client=injected)

    injected.map_cusips.assert_called_once()
    injected.close.assert_not_called()


# --- run-to-completion enrichment (CUSIP link-rate fix) -----------------------

_SEED_SEQ = iter(range(1, 10_000))


def _seed_holdings(db_session, specs):
    """specs: list of (cusip, cusip_mapping_status). Creates one manager + one
    filing + the holdings, against the real db_session."""
    n = next(_SEED_SEQ)
    mgr = InstitutionManager(
        cik=None, legal_name=f"Seed Mgr {n}", display_name=f"Seed Mgr {n}",
        name_normalized=f"seed mgr {n}", match_status="seeded", is_superinvestor=False,
    )
    db_session.add(mgr)
    db_session.flush()
    accession = f"SEED{n:016d}"
    filing = Filing13F(
        manager_id=mgr.id, accession_no=accession, accession_number=accession,
        form_type="13F-HR", period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 15), report_quarter="2024-Q1",
        quarter_end_date=date(2024, 3, 31),
    )
    db_session.add(filing)
    db_session.flush()
    holdings = []
    for i, (cusip, status) in enumerate(specs):
        h = Holding13F(
            filing_id=filing.id, manager_id=mgr.id, accession_number=accession,
            report_quarter="2024-Q1", quarter_end_date=date(2024, 3, 31),
            row_fingerprint=f"seed-{n}-{i}", cusip=cusip,
            issuer_name=f"Issuer {cusip}", value_thousands=100,
            cusip_mapping_status=status,
        )
        db_session.add(h)
        holdings.append(h)
    db_session.flush()
    return holdings


def test_enrich_picks_up_unresolved_holdings(db_session):
    """Regression: a holding in status 'unresolved' (not just 'pending_mapping')
    must be enriched. The old filter only matched 'pending_mapping', so the
    13,981 unresolved prod holdings were a permanent no-op."""
    (h,) = _seed_holdings(db_session, [("037833100", "unresolved")])

    n = enrich_unmapped_holdings(db_session, client=OpenFigiClient(use_stub=True))

    assert n == 1
    db_session.refresh(h)
    assert h.cusip_mapping_status == "linked"
    assert h.stock_id is not None


def test_enrich_skips_cusips_already_mapped(db_session):
    """A CUSIP already in cusip_ticker_map is not re-sent to OpenFIGI — this is
    what lets the run-to-completion loop terminate."""
    _seed_holdings(db_session, [("023135106", "unresolved"), ("594918104", "unresolved")])
    upsert_cusip_mapping(
        db_session, cusip="023135106", ticker="AMZN", issuer_name="Amazon",
        source="manual", confidence="high",
    )
    db_session.flush()
    before = db_session.query(CusipTickerMap).count()

    enrich_unmapped_holdings(db_session, client=OpenFigiClient(use_stub=True))

    after = db_session.query(CusipTickerMap).count()
    assert after == before + 1  # only the un-mapped CUSIP (594918104) is enriched


def test_enrich_all_runs_to_completion(db_session):
    """enrich_all_unmapped_holdings loops over batches until no unmapped CUSIP
    remains, then bootstraps stocks and links holdings."""
    _seed_holdings(db_session, [
        ("037833100", "unresolved"),       # Apple
        ("594918104", "unresolved"),       # Microsoft
        ("023135106", "pending_mapping"),  # Amazon
        ("92826C839", "unresolved"),       # Visa
    ])

    summary = enrich_all_unmapped_holdings(
        db_session, client=OpenFigiClient(use_stub=True), batch_size=2,
    )

    assert summary["holdings_still_unmapped"] == 0
    assert summary["batches_run"] >= 2          # 4 CUSIPs at batch_size 2
    assert summary["mappings_created"] >= 4
    assert summary["holdings_linked"] >= 4


def test_enrich_all_terminates_on_unresolvable_cusip(db_session):
    """A CUSIP OpenFIGI cannot resolve gets a low/no-ticker map row once, leaves
    the unmapped pool, and the loop terminates — it does not spin to max_batches."""
    _seed_holdings(db_session, [("037833100", "unresolved")])
    no_match_client = MagicMock()
    no_match_client.map_cusips.return_value = [[]]  # OpenFIGI: no match

    summary = enrich_all_unmapped_holdings(
        db_session, client=no_match_client, batch_size=2, max_batches=5
    )

    assert summary["batches_run"] == 1            # terminated, did not spin
    assert summary["holdings_still_unmapped"] == 0
    assert db_session.query(CusipTickerMap).filter_by(cusip="037833100").count() == 1
