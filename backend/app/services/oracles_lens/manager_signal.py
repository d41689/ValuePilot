from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DerivedManagerSignalProfile:
    manager_type: str
    manager_signal_weight: float
    portfolio_concentration: float
    portfolio_holding_count: int
    average_holding_period_quarters: float | None
    source: str


def derive_manager_signal_profile(
    *,
    position_weights: list[float],
    holding_streak_quarters: list[int],
    turnover_proxy: float | None,
) -> DerivedManagerSignalProfile:
    clean_weights = sorted([max(float(weight or 0), 0) for weight in position_weights], reverse=True)
    holding_count = len(clean_weights)
    concentration = sum(clean_weights[:10])
    average_holding_period = (
        sum(holding_streak_quarters) / len(holding_streak_quarters)
        if holding_streak_quarters
        else None
    )

    manager_type = "unknown"
    signal_weight = 0.6
    if turnover_proxy is not None and turnover_proxy >= 0.6:
        manager_type = "high_turnover"
        signal_weight = 0.3
    elif concentration >= 0.5 and holding_count <= 25:
        manager_type = "value_concentrated"
        signal_weight = 1.0
    elif average_holding_period is not None and average_holding_period >= 4:
        manager_type = "long_term_fundamental"
        signal_weight = 1.0

    return DerivedManagerSignalProfile(
        manager_type=manager_type,
        manager_signal_weight=signal_weight,
        portfolio_concentration=round(concentration, 6),
        portfolio_holding_count=holding_count,
        average_holding_period_quarters=(
            round(average_holding_period, 4) if average_holding_period is not None else None
        ),
        source="derived_13f_behavior",
    )
