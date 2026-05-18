"""MVP5-03 Phase 1 — Oracle's Lens persisted vs legacy formula comparison.

Used by the admin endpoint
``GET /api/v1/admin/13f/oracles-lens/formula-comparison`` to produce
a per-stock side-by-side of the legacy in-memory dashboard formula
against the persisted MVP4-03 scorer. The product owner reviews the
output before flipping the server-side
``use_persisted_scores`` default to ``True`` (Phase 3).

The pure-function ``compute_formula_comparison`` is decoupled from
the DB / dashboard so the divergence-detection logic can be tested
with synthetic data; ``build_formula_comparison`` is the
session-aware wrapper the endpoint calls.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.oracles_lens import OraclesLensSignal
from app.services.oracles_lens.constants import SCORE_VERSION
from app.services.oracles_lens.dashboard import build_oracles_lens_dashboard


# Stable string codes for the divergence flags. Frontend / admin
# consumers can switch on these.
DIVERGENCE_TOP10_RANK_SWAP = "TOP10_RANK_SWAP"
DIVERGENCE_MAGNITUDE_25_PCT = "MAGNITUDE_DIFF_25_PCT"


# Material-discrepancy thresholds. Calibrated per MVP5-03 task spec:
# top 10 under one path / below position 20 under the other is a
# clear product-judgment red flag; 25% magnitude diff is the cutoff
# below which the legacy/persisted gap is informational, not
# blocking.
_TOP10_THRESHOLD = 10
_BELOW_THRESHOLD = 20
_MAGNITUDE_DIFF_THRESHOLD = 0.25


def compute_formula_comparison(
    legacy_by_stock: dict[int, float],
    persisted_by_stock: dict[int, float],
) -> dict[str, Any]:
    """Produce the comparison payload from two per-stock score dicts.

    Pure function — no DB / no session. The intersection of stock_ids
    is what goes into ``items``; stocks present in only one of the
    two dicts are counted separately as ``legacy_only_count`` /
    ``persisted_only_count``.

    Ranks are 1-indexed and computed independently per side (i.e.
    ``legacy_rank`` is the rank of the stock among all legacy-scored
    stocks, NOT just the intersection — this matches what a product
    owner sees when they sort the dashboard).
    """
    intersection = sorted(set(legacy_by_stock) & set(persisted_by_stock))
    legacy_only = set(legacy_by_stock) - set(persisted_by_stock)
    persisted_only = set(persisted_by_stock) - set(legacy_by_stock)

    legacy_ranks = _rank_by_score(legacy_by_stock)
    persisted_ranks = _rank_by_score(persisted_by_stock)

    items: list[dict[str, Any]] = []
    top10_swap_count = 0
    magnitude_diff_count = 0

    for stock_id in intersection:
        legacy_score = float(legacy_by_stock[stock_id])
        persisted_score = float(persisted_by_stock[stock_id])
        legacy_rank = legacy_ranks[stock_id]
        persisted_rank = persisted_ranks[stock_id]

        flags: list[str] = []
        if _is_top10_swap(legacy_rank, persisted_rank):
            flags.append(DIVERGENCE_TOP10_RANK_SWAP)
            top10_swap_count += 1
        if _is_magnitude_diff(legacy_score, persisted_score):
            flags.append(DIVERGENCE_MAGNITUDE_25_PCT)
            magnitude_diff_count += 1

        items.append(
            {
                "stock_id": stock_id,
                "legacy_score": legacy_score,
                "persisted_score": persisted_score,
                "score_delta": persisted_score - legacy_score,
                "legacy_rank": legacy_rank,
                "persisted_rank": persisted_rank,
                "divergence_flags": flags,
            }
        )

    return {
        "total_stocks_compared": len(items),
        "legacy_only_count": len(legacy_only),
        "persisted_only_count": len(persisted_only),
        "top10_swap_count": top10_swap_count,
        "magnitude_diff_count": magnitude_diff_count,
        "items": items,
    }


def build_formula_comparison(
    session: Session,
    *,
    quarter: str | None = None,
    score_version: str = SCORE_VERSION,
) -> dict[str, Any]:
    """Session-aware wrapper. Resolves the target quarter (latest
    scored quarter if not specified), pulls legacy scores from
    ``build_oracles_lens_dashboard`` with ``use_persisted_scores=False``,
    pulls persisted scores from ``oracles_lens_signals``, and runs
    ``compute_formula_comparison``."""
    target_quarter = quarter or _latest_scored_quarter(
        session, score_version=score_version,
    )
    if target_quarter is None:
        return {
            "quarter": None,
            "score_version": score_version,
            "total_stocks_compared": 0,
            "legacy_only_count": 0,
            "persisted_only_count": 0,
            "top10_swap_count": 0,
            "magnitude_diff_count": 0,
            "items": [],
        }

    legacy_payload = build_oracles_lens_dashboard(
        session,
        period=target_quarter,
        use_persisted_scores=False,
        limit=0,  # 0 = unlimited; we want the full universe for the comparison
    )
    legacy_by_stock = {
        int(item["stock_id"]): float(item["signal_weighted_consensus_score"])
        for item in legacy_payload.get("items", [])
        if item.get("stock_id") is not None
    }

    persisted_rows = (
        session.query(
            OraclesLensSignal.stock_id,
            OraclesLensSignal.signal_weighted_consensus_score,
        )
        .filter(OraclesLensSignal.report_quarter == target_quarter)
        .filter(OraclesLensSignal.score_version == score_version)
        .all()
    )
    persisted_by_stock = {
        int(row[0]): float(row[1]) for row in persisted_rows if row[1] is not None
    }

    comparison = compute_formula_comparison(legacy_by_stock, persisted_by_stock)
    return {
        "quarter": target_quarter,
        "score_version": score_version,
        **comparison,
    }


def _latest_scored_quarter(
    session: Session, *, score_version: str,
) -> str | None:
    row = (
        session.query(OraclesLensSignal.report_quarter)
        .filter(OraclesLensSignal.score_version == score_version)
        .order_by(OraclesLensSignal.report_quarter.desc())
        .first()
    )
    return row[0] if row else None


def _rank_by_score(scores: dict[int, float]) -> dict[int, int]:
    """1-indexed rank per stock, sorted by score descending. Ties
    resolved by stock_id ascending so the ranks are deterministic."""
    ordered = sorted(
        scores.items(), key=lambda kv: (-kv[1], kv[0]),
    )
    return {stock_id: idx + 1 for idx, (stock_id, _) in enumerate(ordered)}


def _is_top10_swap(legacy_rank: int, persisted_rank: int) -> bool:
    legacy_top = legacy_rank <= _TOP10_THRESHOLD
    persisted_top = persisted_rank <= _TOP10_THRESHOLD
    legacy_below = legacy_rank > _BELOW_THRESHOLD
    persisted_below = persisted_rank > _BELOW_THRESHOLD
    return (legacy_top and persisted_below) or (persisted_top and legacy_below)


def _is_magnitude_diff(legacy: float, persisted: float) -> bool:
    denom = max(abs(legacy), abs(persisted))
    if denom == 0:
        return False
    return abs(legacy - persisted) / denom > _MAGNITUDE_DIFF_THRESHOLD
