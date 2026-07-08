"""Pin the per-share estimate math in the Oracle's Lens dashboard payload.

Task doc: ``docs/tasks/2026-05-25_eod-prices-and-holder-estimate-fix.md``

The motivating bug: MSFT in 2025-Q4 surfaced a "Holder estimate
$483.60–$483,620.35" range — a 1000× spread caused by treating the SEC
13F ``<value>`` field as if it were always in thousands. After the SEC
amendment effective for filings ACCEPTED on or after 2023-01-03, the
``<value>`` field is reported in dollars (not thousands).

The helper under test centralizes the unit decision in one place so the
dashboard's aggregate range and per-holder estimates can no longer drift.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.services.oracles_lens.dashboard import (
    ManagerHolding,
    _holder_price_estimate,
    _resolve_peer_anchor,
)


def _h(
    *,
    value_thousands: int | None,
    value_usd: int | None = None,
    shares: int | None,
    period: date = date(2025, 9, 30),
) -> ManagerHolding:
    """Minimal ManagerHolding for peer_anchor tests — only the fields the
    helpers actually read need to be set."""
    return ManagerHolding(
        manager_id=0,
        manager_name="",
        stock_id=0,
        ticker="",
        company_name="",
        shares=shares or 0,
        value_thousands=value_thousands or 0,
        filing_total_value_thousands=None,
        position_weight=0.0,
        value_usd=value_usd,
        accepted_at=None,
        period_of_report=period,
    )


# ---------------------------------------------------------------------------
# Happy path — uses value_usd when populated (the canonical column)
# ---------------------------------------------------------------------------


def test_prefers_value_usd_when_populated():
    """When ``value_usd`` is populated, it is the single source of truth.

    Don't second-guess it with period heuristics — the parser already made
    that decision using ``accepted_at`` and schema evidence.
    """
    assert _holder_price_estimate(
        value_thousands=999_999_999,  # ignored
        value_usd=418_220_281,         # ← used
        shares=807_453,
        accepted_at=None,
        period_of_report=None,
    ) == pytest.approx(418_220_281 / 807_453, rel=1e-9)


# ---------------------------------------------------------------------------
# Fallback path — value_usd missing, use accepted_at to decide unit
# ---------------------------------------------------------------------------


def test_accepted_at_post_transition_treats_value_as_dollars():
    """SEC amendment in effect for filings accepted on/after 2023-01-03.

    For an accepted_at of 2025-02-14, the raw <value> stored in
    value_thousands is already in DOLLARS, so per-share = value / shares.
    """
    p = _holder_price_estimate(
        value_thousands=418_220_281,   # raw dollars per the new SEC rule
        value_usd=None,
        shares=807_453,
        accepted_at=date(2025, 2, 14),
        period_of_report=date(2024, 12, 31),
    )
    # MSFT-like price ~ $517.95/share
    assert p == pytest.approx(517.95, abs=0.01)


def test_accepted_at_pre_transition_treats_value_as_thousands():
    """Accepted_at before 2023-01-03 → raw <value> is in THOUSANDS.

    Per-share = (value_thousands * 1000) / shares.
    """
    p = _holder_price_estimate(
        value_thousands=42_000,         # thousands, i.e. $42,000,000 total
        value_usd=None,
        shares=100_000,
        accepted_at=date(2022, 11, 14),
        period_of_report=date(2022, 9, 30),
    )
    assert p == pytest.approx(420.0, abs=0.01)


def test_accepted_at_exactly_on_transition_is_dollars():
    """Boundary: TRANSITION_ACCEPTED_DATE itself (2023-01-03) is the FIRST
    day under the new rule — treat as dollars."""
    p = _holder_price_estimate(
        value_thousands=1_000_000,
        value_usd=None,
        shares=2_000,
        accepted_at=date(2023, 1, 3),
        period_of_report=date(2022, 12, 31),
    )
    # $1,000,000 / 2,000 shares = $500 (NOT $500,000)
    assert p == pytest.approx(500.0, abs=0.01)


# ---------------------------------------------------------------------------
# Fallback to period_of_report when accepted_at is missing
# ---------------------------------------------------------------------------


def test_falls_back_to_period_of_report_when_accepted_at_missing():
    """If accepted_at is None (our PR #96 backfilled filings have no
    accepted_at), fall back to period_of_report. Periods on or after the
    2022-12-31 quarter end are post-transition — almost all amendments
    for those periods would have been accepted post-2023-01-03.
    """
    p = _holder_price_estimate(
        value_thousands=418_220_281,
        value_usd=None,
        shares=807_453,
        accepted_at=None,
        period_of_report=date(2025, 9, 30),
    )
    assert p == pytest.approx(517.95, abs=0.01)


def test_falls_back_to_period_of_report_pre_transition():
    p = _holder_price_estimate(
        value_thousands=42_000,
        value_usd=None,
        shares=100_000,
        accepted_at=None,
        period_of_report=date(2022, 6, 30),  # pre-transition period
    )
    assert p == pytest.approx(420.0, abs=0.01)


# ---------------------------------------------------------------------------
# Defensive — None / zero / missing data returns None, never raises
# ---------------------------------------------------------------------------


def test_returns_none_when_shares_missing():
    assert _holder_price_estimate(
        value_thousands=1_000, value_usd=None, shares=None,
        accepted_at=date(2025, 1, 1), period_of_report=date(2024, 12, 31),
    ) is None


def test_returns_none_when_shares_zero():
    assert _holder_price_estimate(
        value_thousands=1_000, value_usd=None, shares=0,
        accepted_at=date(2025, 1, 1), period_of_report=date(2024, 12, 31),
    ) is None


def test_returns_none_when_value_thousands_and_value_usd_missing():
    assert _holder_price_estimate(
        value_thousands=None, value_usd=None, shares=1_000,
        accepted_at=date(2025, 1, 1), period_of_report=date(2024, 12, 31),
    ) is None


def test_returns_none_when_value_thousands_zero_and_value_usd_missing():
    assert _holder_price_estimate(
        value_thousands=0, value_usd=None, shares=1_000,
        accepted_at=date(2025, 1, 1), period_of_report=date(2024, 12, 31),
    ) is None


def test_returns_none_when_no_unit_evidence_available():
    """Both accepted_at AND period_of_report missing AND value_usd missing.

    We CANNOT make a defensible per-share estimate — refuse rather than
    guess a possibly-1000×-wrong number.
    """
    assert _holder_price_estimate(
        value_thousands=42_000, value_usd=None, shares=1_000,
        accepted_at=None, period_of_report=None,
    ) is None


def test_value_usd_zero_falls_through_to_period_logic():
    """Some rows in the DB have value_usd=0 (not NULL). 0 is a sentinel for
    "not normalized", not a real value — fall through to the same
    period-aware path."""
    p = _holder_price_estimate(
        value_thousands=418_220_281,
        value_usd=0,
        shares=807_453,
        accepted_at=None,
        period_of_report=date(2025, 9, 30),
    )
    assert p == pytest.approx(517.95, abs=0.01)


# ---------------------------------------------------------------------------
# peer_anchor — per-row unit disambiguation when sibling holders disagree
# ---------------------------------------------------------------------------


def test_peer_anchor_picks_thousands_rule_for_minority_old_unit_row():
    """The hero case from MSFT 2025-Q4 production data: 29 of 32 holders
    file in the new "dollars" rule, 3 still file in the legacy "thousands"
    rule. A minority row's raw <value> is in THOUSANDS even though its
    period is post-transition. The peer anchor (median per-share from
    the 29 dominant holders) is ~$483.62, so for the minority row we
    must pick the THOUSANDS rule (value*1000/shares=$483.62), NOT the
    dollars rule (value/shares=$0.4836).
    """
    # AKO Capital's actual MSFT 2025-Q4 holding.
    p = _holder_price_estimate(
        value_thousands=493_638,
        value_usd=None,
        shares=1_020_715,
        accepted_at=None,
        period_of_report=date(2025, 12, 31),
        peer_anchor=483.62,
    )
    # Thousands rule: 493638 * 1000 / 1020715 = $483.62
    assert p == pytest.approx(483.62, abs=0.05)


def test_peer_anchor_picks_dollars_rule_for_majority_post_transition_row():
    """The majority case: most 2025-Q4 holders report in dollars
    correctly. With peer_anchor at $483.62, dollars rule wins."""
    # Chase Coleman's actual MSFT 2025-Q4 holding.
    p = _holder_price_estimate(
        value_thousands=2_649_148_004,
        value_usd=None,
        shares=5_477_747,
        accepted_at=None,
        period_of_report=date(2025, 12, 31),
        peer_anchor=483.62,
    )
    assert p == pytest.approx(483.62, abs=0.05)


def test_peer_anchor_overrides_period_heuristic():
    """If accepted_at says one rule but peer_anchor says the other,
    peer_anchor wins. It carries direct evidence from sibling holdings
    on the same stock; accepted_at is an indirect proxy."""
    p = _holder_price_estimate(
        value_thousands=420_000,        # raw THOUSANDS interpretation = $420
        value_usd=None,
        shares=1_000_000,
        # accepted_at is post-transition → period heuristic would pick dollars
        # rule (=$0.42), but the sibling cluster says ~$420.
        accepted_at=date(2024, 1, 1),
        period_of_report=date(2023, 12, 31),
        peer_anchor=420.0,
    )
    assert p == pytest.approx(420.0, abs=0.5)


def test_peer_anchor_zero_or_negative_ignored():
    """A degenerate peer_anchor (0 or negative) must not poison the
    decision — fall back to the period heuristic."""
    p = _holder_price_estimate(
        value_thousands=418_220_281,
        value_usd=None,
        shares=807_453,
        accepted_at=None,
        period_of_report=date(2025, 9, 30),
        peer_anchor=0.0,
    )
    # Falls back to period heuristic → dollars rule → $517.95
    assert p == pytest.approx(517.95, abs=0.01)


# ---------------------------------------------------------------------------
# _resolve_peer_anchor — picks the tightest-cluster median across rule choice
# ---------------------------------------------------------------------------


def test_resolve_peer_anchor_returns_dominant_dollars_cluster():
    """30 dollars-rule rows around $100 + 2 thousands-rule rows whose
    dollars-rule reading happens to land at $0.10 (1000× off). The
    consensus by margin is the dollars-rule median ($100)."""
    holdings = []
    # 30 majority holders, dollars rule, true price ~$100
    for i in range(30):
        holdings.append(_h(value_thousands=100_000 + i * 100, shares=1_000))
    # 2 outlier holders, thousands rule — their dollars reading = $0.10
    for i in range(2):
        holdings.append(_h(value_thousands=100, shares=1_000))

    anchor = _resolve_peer_anchor(holdings)
    # The 30-row dollars-rule cluster centered at $100 wins consensus.
    assert anchor is not None
    assert 95 <= anchor <= 105


def test_resolve_peer_anchor_returns_thousands_cluster_when_majority_uses_old_unit():
    """The mirror case: 30 thousands-rule rows around $200 + 2
    dollars-rule rows. The thousands-rule cluster (anchor=$200) wins."""
    holdings = []
    # 30 majority holders, thousands rule. value_thousands stores ACTUAL
    # thousands, so per-share = value*1000/shares. To hit $200/share
    # with shares=1000, value_thousands needs to be 200.
    for i in range(30):
        holdings.append(_h(value_thousands=200 + i, shares=1_000))
    # 2 outliers in dollars rule.
    for i in range(2):
        holdings.append(_h(value_thousands=200_000, shares=1_000))

    anchor = _resolve_peer_anchor(holdings)
    assert anchor is not None
    # value_thousands varies 200..229 with shares=1000 → thousands rule
    # gives per-share values in [200, 229]; cluster median ~ 214.5.
    assert 200 <= anchor <= 230


def test_resolve_peer_anchor_prefers_value_usd_when_any_row_has_it():
    """value_usd is the canonical normalized column. Even one populated
    row should anchor the cluster — it's gold-standard evidence."""
    holdings = [
        # value_usd populated → per-share = 500_000_000 / 1_000_000 = $500
        _h(value_thousands=500_000, value_usd=500_000_000, shares=1_000_000),
        # raw rows with ambiguous interpretation
        _h(value_thousands=500_000_000, shares=1_000_000),
    ]
    anchor = _resolve_peer_anchor(holdings)
    assert anchor == pytest.approx(500.0, abs=1.0)


def test_resolve_peer_anchor_returns_none_for_empty_input():
    assert _resolve_peer_anchor([]) is None


def test_resolve_peer_anchor_returns_none_when_no_shares():
    holdings = [_h(value_thousands=100, shares=None)]
    assert _resolve_peer_anchor(holdings) is None
