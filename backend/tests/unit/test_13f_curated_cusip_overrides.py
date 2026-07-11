"""Curated CUSIP override seed — the safe, deterministic resolution for mega-caps
OpenFIGI cannot map (no US-composite listing).

Root cause (verified live 2026-07-10 via Rate Guard): for ExxonMobil (30231G102),
Honeywell (438516106), Carnival (143658300) and their class, OpenFIGI's mapCusips
returns either only foreign-venue listings or venue-coded US listings mixed with
foreign variants — and for HON/Carnival the correct US ticker is ABSENT entirely.
No forward-lookup heuristic can recover it without risking a wrong foreign-currency
link (HONGBP, CCL1USD). A wrong link is worse than a known-unresolved CUSIP, so we
resolve deterministically with a human-verified override that cannot mis-link.

The override rides existing precedence machinery: source="manual" /
confidence="manual" is rank 4, so it (a) beats any OpenFIGI row for the same CUSIP,
(b) is never downgraded by a later OpenFIGI run, and (c) passes the
~confidence.like("review_needed:%") filter in both bootstrap and link. These tests
pin exactly that behaviour.
"""
import itertools
import json
from datetime import date
from pathlib import Path

import pytest

from app.models.institutions import CusipTickerMap, Filing13F, Holding13F, InstitutionManager
from app.models.stocks import Stock
from app.services import cusip_enrichment
from app.services.cusip_enrichment import (
    _active_mapping,
    backfill_stock_ids,
    bootstrap_stocks_from_cusip_map,
    seed_curated_cusip_overrides,
    upsert_cusip_mapping,
)
from app.services.cusip_validation import is_valid_cusip

_SEQ = itertools.count(1)

REAL_SEED_PATH = Path(cusip_enrichment.__file__).parent / "seed_data" / "curated_cusip_overrides.json"


def _write_seed(tmp_path, entries):
    p = tmp_path / "overrides.json"
    p.write_text(json.dumps(entries))
    return p


def _active(db_session, cusip):
    return _active_mapping(db_session, cusip, None)


def _holding(db_session, *, cusip, status="needs_review", qend=date(2024, 3, 31)):
    """One manager + filing + holding for `cusip` in the given map status."""
    n = next(_SEQ)
    mgr = InstitutionManager(cik=None, legal_name=f"M{n}", display_name=f"M{n}",
                             name_normalized=f"m{n}", match_status="seeded")
    db_session.add(mgr); db_session.flush()
    acc = f"CUR{n:016d}"
    f = Filing13F(manager_id=mgr.id, accession_no=acc, accession_number=acc,
                  form_type="13F-HR", period_of_report=qend, filed_at=date(2024, 5, 15),
                  report_quarter="2024-Q1", quarter_end_date=qend)
    db_session.add(f); db_session.flush()
    h = Holding13F(filing_id=f.id, manager_id=mgr.id, accession_number=acc,
                   report_quarter="2024-Q1", quarter_end_date=qend,
                   row_fingerprint=f"cur-{n}", cusip=cusip, issuer_name=f"Issuer {cusip}",
                   value_thousands=100, cusip_mapping_status=status)
    db_session.add(h); db_session.flush()
    return h


# --------------------------------------------------------------------------
# The seed file is a checked-in contract (CI validity gate).
# --------------------------------------------------------------------------


def test_the_seed_file_is_structurally_valid():
    data = json.loads(REAL_SEED_PATH.read_text())
    assert isinstance(data, list) and data, "seed must be a non-empty list"
    seen = set()
    for e in data:
        for field in ("cusip", "ticker", "issuer_name", "reason"):
            assert e.get(field), f"entry missing/empty '{field}': {e}"
        assert is_valid_cusip(e["cusip"]), f"invalid cusip {e['cusip']}"
        # The stored form is uppercase (the parser uppercases holdings and the
        # link match is exact) — the checked-in file must already be canonical so
        # a case typo can never slip a mega-cap past the linker.
        assert e["cusip"] == e["cusip"].upper(), f"seed cusip not uppercase: {e['cusip']}"
        assert e["ticker"] == e["ticker"].upper(), f"seed ticker not uppercase: {e['ticker']}"
        assert e["cusip"] not in seen, f"duplicate cusip {e['cusip']}"
        seen.add(e["cusip"])
    # The two backlog-named, guardrail-flagged mega-caps must be present.
    by_cusip = {e["cusip"]: e["ticker"] for e in data}
    assert by_cusip.get("30231G102") == "XOM"
    assert by_cusip.get("438516106") == "HON"


# --------------------------------------------------------------------------
# The mechanism.
# --------------------------------------------------------------------------


def test_override_resolves_a_cusip_openfigi_left_in_review(db_session, tmp_path):
    """The core fix: a CUSIP OpenFIGI could only mark review_needed (no US listing)
    becomes a confirmed manual mapping, a Stock, and a linked holding."""
    cusip = "111111118"
    # Reproduce the real pre-state: OpenFIGI wrote a review_needed:low row (no
    # ticker) and the holding sits in the human queue, invisible to the product.
    upsert_cusip_mapping(db_session, cusip=cusip, ticker=None, issuer_name=None,
                         source="openfigi", confidence="review_needed:low")
    h = _holding(db_session, cusip=cusip, status="needs_review")

    seed = _write_seed(tmp_path, [
        {"cusip": cusip, "ticker": "FAKE", "issuer_name": "Fake Mega Co", "reason": "test"},
    ])
    report = seed_curated_cusip_overrides(db_session, seed_path=seed)

    assert cusip in report["applied_cusips"]
    m = _active(db_session, cusip)
    assert m.source == "manual" and m.confidence == "manual" and m.ticker == "FAKE"
    # The stale OpenFIGI row was deactivated, not left as a competing active row.
    openfigi_rows = (db_session.query(CusipTickerMap)
                     .filter_by(cusip=cusip, source="openfigi").all())
    assert all(not r.is_active for r in openfigi_rows)

    # bootstrap + link: the holding becomes visible to the product.
    bootstrap_stocks_from_cusip_map(db_session)
    backfill_stock_ids(db_session)
    db_session.refresh(h)
    assert h.cusip_mapping_status == "linked"
    assert h.stock_id is not None
    stock = db_session.get(Stock, h.stock_id)
    assert stock.ticker == "FAKE" and stock.company_name == "Fake Mega Co"


def test_a_lowercase_seed_cusip_is_canonicalized_and_links_an_uppercase_holding(db_session, tmp_path):
    """P1 regression: a case-variant CUSIP must not become a silent omission.
    The validator (is_valid_cusip) only uppercases a local copy, so a lowercase
    seed value passes; holdings are stored uppercase and the link match is exact.
    The loader must canonicalize to uppercase so the override actually links —
    and report the canonical CUSIP, never the lowercase input."""
    canonical = "11111A118"  # has a letter, so case matters
    h = _holding(db_session, cusip=canonical, status="needs_review")  # parser stores uppercase
    seed = _write_seed(tmp_path, [
        {"cusip": canonical.lower(), "ticker": "meg", "issuer_name": "Mega Co", "reason": "test"},
    ])
    report = seed_curated_cusip_overrides(db_session, seed_path=seed)

    # Reported + stored in canonical UPPERCASE, not the lowercase input.
    assert canonical in report["applied_cusips"]
    assert canonical.lower() not in report["applied_cusips"]
    m = _active(db_session, canonical)
    assert m is not None and m.cusip == canonical and m.ticker == "MEG"
    assert _active(db_session, canonical.lower()) is None

    # And it actually links the real (uppercase) holding — no silent omission.
    bootstrap_stocks_from_cusip_map(db_session)
    backfill_stock_ids(db_session)
    db_session.refresh(h)
    assert h.cusip_mapping_status == "linked" and h.stock_id is not None


def test_a_later_openfigi_run_never_overrides_a_curated_ticker(db_session, tmp_path):
    """Rank-4 protection: once curated, a subsequent OpenFIGI 'high' match with a
    WRONG (e.g. foreign-currency) ticker must not replace the curated identity."""
    cusip = "222222226"
    seed = _write_seed(tmp_path, [
        {"cusip": cusip, "ticker": "CLEAN", "issuer_name": "Clean Co", "reason": "test"},
    ])
    seed_curated_cusip_overrides(db_session, seed_path=seed)

    # A later enrichment pass mis-reads a foreign listing as high-confidence.
    upsert_cusip_mapping(db_session, cusip=cusip, ticker="WRONGFX", issuer_name="Foreign Variant",
                         source="openfigi", confidence="high")

    m = _active(db_session, cusip)
    assert m.ticker == "CLEAN" and m.source == "manual" and m.confidence == "manual"


def test_seeding_is_idempotent(db_session, tmp_path):
    """Re-running the seed is a no-op — no duplicate rows, ticker stable."""
    cusip = "333333334"
    seed = _write_seed(tmp_path, [
        {"cusip": cusip, "ticker": "IDEM", "issuer_name": "Idem Co", "reason": "test"},
    ])
    r1 = seed_curated_cusip_overrides(db_session, seed_path=seed)
    r2 = seed_curated_cusip_overrides(db_session, seed_path=seed)

    assert cusip in r1["applied_cusips"]
    assert cusip in r2["unchanged_cusips"] and cusip not in r2["applied_cusips"]
    active = (db_session.query(CusipTickerMap)
              .filter_by(cusip=cusip, is_active=True).all())
    assert len(active) == 1 and active[0].ticker == "IDEM"


def test_a_conflicting_prior_manual_mapping_is_reported_not_silently_dropped(db_session, tmp_path):
    """If an operator already manual-mapped this CUSIP to a DIFFERENT ticker, the
    seed must NOT silently overwrite it (equal rank) NOR silently ignore it — the
    divergence is surfaced as a conflict for a human to reconcile."""
    cusip = "444444442"
    upsert_cusip_mapping(db_session, cusip=cusip, ticker="OLD", issuer_name="Prior Manual",
                         source="manual", confidence="manual")
    seed = _write_seed(tmp_path, [
        {"cusip": cusip, "ticker": "NEW", "issuer_name": "Seed Co", "reason": "test"},
    ])
    report = seed_curated_cusip_overrides(db_session, seed_path=seed)

    assert cusip in report["conflict_cusips"]
    assert cusip not in report["applied_cusips"]
    # The prior human decision is preserved, not clobbered.
    assert _active(db_session, cusip).ticker == "OLD"


def test_a_malformed_seed_entry_fails_loud(db_session, tmp_path):
    """A deploy-time typo (missing ticker / bad cusip) fails loudly rather than
    silently skipping a mega-cap the operator believed was covered."""
    seed = _write_seed(tmp_path, [
        {"cusip": "555555556", "issuer_name": "No Ticker Co", "reason": "test"},
    ])
    with pytest.raises(ValueError):
        seed_curated_cusip_overrides(db_session, seed_path=seed)

    bad_cusip = _write_seed(tmp_path, [
        {"cusip": "NOTACUSIP", "ticker": "X", "issuer_name": "Bad", "reason": "test"},
    ])
    with pytest.raises(ValueError):
        seed_curated_cusip_overrides(db_session, seed_path=bad_cusip)


def test_missing_seed_file_is_a_noop(db_session, tmp_path):
    report = seed_curated_cusip_overrides(db_session, seed_path=tmp_path / "does_not_exist.json")
    assert report["entries"] == 0
    assert report["applied_cusips"] == [] and report["conflict_cusips"] == []


# --------------------------------------------------------------------------
# Wiring into the enrichment pass (gated by the flag).
# --------------------------------------------------------------------------


def test_enrich_all_applies_overrides_only_when_enabled(db_session, monkeypatch):
    """The overrides run as the first step of a full enrichment pass — but only
    when CUSIP_OVERRIDE_SEED_ENABLED is on, so dev/test enrichment stays clean."""
    from app.openfigi.client import OpenFigiClient
    from app.services.cusip_enrichment import enrich_all_unmapped_holdings

    calls = []

    def _spy(db, **kw):
        calls.append(True)
        return {"entries": 0, "applied": 0, "unchanged": 0, "conflicts": 0,
                "applied_cusips": [], "unchanged_cusips": [], "conflict_cusips": []}

    monkeypatch.setattr(cusip_enrichment, "seed_curated_cusip_overrides", _spy)

    monkeypatch.setattr(cusip_enrichment.settings, "CUSIP_OVERRIDE_SEED_ENABLED", False)
    enrich_all_unmapped_holdings(db_session, client=OpenFigiClient(use_stub=True))
    assert calls == []

    monkeypatch.setattr(cusip_enrichment.settings, "CUSIP_OVERRIDE_SEED_ENABLED", True)
    enrich_all_unmapped_holdings(db_session, client=OpenFigiClient(use_stub=True))
    assert calls == [True]
