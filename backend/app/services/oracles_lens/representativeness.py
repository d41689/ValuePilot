"""Reviewed policy for how faithfully a manager's 13F represents its strategy.

A 13F is a delayed snapshot of reportable long US-listed securities.  It is a
good proxy for a long-only equity picker, but only a sleeve view for a
long/short, activist, special-situations, credit, or macro manager.  This module
keeps that economic distinction separate from investment-style taxonomy.

The initial policy was reviewed manager-by-manager through the curated V2 seed
on 2026-07-20.  The style mapping is the common methodology; each manager's
existing ``classification_rationale`` remains the individual evidence behind
the style decision.  Startup seeding persists the resulting current projection
and policy version.  Score components preserve the version actually used.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.models.institutions import InstitutionManager, STYLE_PRIMARY
from app.services.oracles_lens.constants import REPRESENTATIVENESS_POLICY_VERSION


REPRESENTATIVENESS_CLASSIFICATIONS = {
    "faithful",
    "partial",
    "unrepresentative",
    "unknown",
}

REPRESENTATIVENESS_FACTORS: dict[str, Decimal] = {
    "faithful": Decimal("1.00"),
    "partial": Decimal("0.70"),
    "unrepresentative": Decimal("0.20"),
    "unknown": Decimal("0.50"),
}

_STYLE_CLASSIFICATION = {
    "value_deep": "faithful",
    "value_concentrated": "faithful",
    "quality_compounder": "faithful",
    "activist": "partial",
    "growth_long_short": "partial",
    "special_situations": "partial",
    "multi_strategy_macro": "partial",
    "endowment_passive": "unrepresentative",
    "unknown": "unknown",
}

_RATIONALES = {
    "faithful": (
        "The reviewed strategy is primarily expressed through reportable long "
        "listed-equity positions, so the 13F is a useful—still delayed—proxy."
    ),
    "partial": (
        "The reviewed strategy also uses omitted exposures such as shorts, "
        "derivatives, credit, private assets, control activity, or macro "
        "instruments; the 13F represents only its long listed-equity sleeve."
    ),
    "unrepresentative": (
        "Observed 13F changes are materially driven by a non-investment or "
        "non-discretionary mechanism, so they are a weak proxy for conviction."
    ),
    "unknown": (
        "No reviewed evidence is sufficient to say how faithfully the 13F "
        "represents the manager's full strategy."
    ),
}


@dataclass(frozen=True)
class ReviewedStyleClassification:
    classification: str
    policy_version: str
    rationale: str


@dataclass(frozen=True)
class ManagerRepresentativenessResolution:
    classification: str
    factor: Decimal
    policy_version: str | None
    source: str
    scoring_applied: bool
    reviewed_at: datetime | None


def classify_reviewed_style(style_primary: str) -> ReviewedStyleClassification:
    if set(_STYLE_CLASSIFICATION) != STYLE_PRIMARY:
        raise RuntimeError(
            "representativeness style policy is not exhaustive over STYLE_PRIMARY"
        )
    try:
        classification = _STYLE_CLASSIFICATION[style_primary]
    except KeyError as exc:
        raise ValueError(f"unknown reviewed style_primary={style_primary!r}") from exc
    return ReviewedStyleClassification(
        classification=classification,
        policy_version=REPRESENTATIVENESS_POLICY_VERSION,
        rationale=_RATIONALES[classification],
    )


def resolve_manager_representativeness(
    manager: InstitutionManager,
) -> ManagerRepresentativenessResolution:
    """Resolve the persisted reviewed projection, failing visibly to unknown.

    Legacy/test rows that have not passed the reviewed-policy rollout retain
    the old score weight temporarily, but are explicitly emitted as unknown
    with ``scoring_applied=False``.  This avoids silently rewriting historical
    scores while also avoiding the false claim that unknown means faithful.
    """
    classification = manager.thirteenf_representativeness or "unknown"
    policy_version = manager.representativeness_policy_version
    if (
        classification in REPRESENTATIVENESS_CLASSIFICATIONS
        and policy_version == REPRESENTATIVENESS_POLICY_VERSION
    ):
        return ManagerRepresentativenessResolution(
            classification=classification,
            factor=REPRESENTATIVENESS_FACTORS[classification],
            policy_version=policy_version,
            source="reviewed_projection",
            scoring_applied=True,
            reviewed_at=manager.representativeness_reviewed_at,
        )
    return ManagerRepresentativenessResolution(
        classification="unknown",
        factor=Decimal("1.00"),
        policy_version=None,
        source="unreviewed_compatibility",
        scoring_applied=False,
        reviewed_at=None,
    )
